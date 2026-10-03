#!/usr/bin/env python3
"""AVIF speed / quality / size benchmark harness.

For every (config, image, q) it encodes with avifenc, records file size and
encoder CPU time, decodes with avifdec and scores against the source with
SSIMULACRA2. Results are cached in results.csv so runs can be resumed and
new configs added without re-running old ones.

Usage:
    python3 bench.py                 # run every config in CONFIGS
    python3 bench.py aom_s6 aom_s7   # run only the named configs
"""
import csv
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import ssimulacra2

ROOT = Path(__file__).resolve().parent
IMAGES = sorted((ROOT / "images").glob("*.png"))
RESULTS = ROOT / "results.csv"
QS = [40, 50, 55, 60, 65, 70, 80]
WORKERS = int(os.environ.get("WORKERS", os.cpu_count() or 1))
FIELDS = ["config", "image", "q", "bytes", "cpu_s", "ssimu2"]

# Optional newer libavif/libaom build (see README). Configs whose args start
# with NEW run against it instead of the system avifenc/avifdec.
NEW_BIN = Path(os.environ.get("AVIF_NEW_BIN", ROOT / "build" / "libavif" / "build"))
NEW = "@new"
# Same libavif/libaom with patches/ applied (AVX2 QM quantizer + the
# experiment-only AOM_SF speed-feature override hook).
PATCHED_BIN = Path(os.environ.get("AVIF_PATCHED_BIN", ROOT / "build" / "patched"))
PATCHED = "@patched"


def sf(**overrides):
    """Speed-feature overrides for the patched build (AOM_SF env var)."""
    return "AOM_SF=" + ",".join(f"{k}={v}" for k, v in overrides.items())

AOM = ["-c", "aom"]
CONFIGS = {
    # --- baseline: avifenc defaults (aom, speed 6, 4:4:4, 8-bit) ---
    "aom_s6": AOM + ["-s", "6"],
    # --- speed presets ---
    **{f"aom_s{s}": AOM + ["-s", str(s)] for s in [0, 1, 2, 3, 4, 5, 7, 8, 9, 10]},
    # --- chroma / bit depth ---
    "aom_s6_420": AOM + ["-s", "6", "-y", "420"],
    "aom_s6_420_sharpyuv": AOM + ["-s", "6", "-y", "420", "--sharpyuv"],
    "aom_s6_10bit": AOM + ["-s", "6", "-d", "10"],
    # --- libaom tuning knobs ---
    "aom_s6_tune_ssim": AOM + ["-s", "6", "-a", "tune=ssim"],
    "aom_s6_chroma_dq": AOM + ["-s", "6", "-a", "enable-chroma-deltaq=1"],
    "aom_s6_aq1": AOM + ["-s", "6", "-a", "aq-mode=1"],
    "aom_s6_sharp2": AOM + ["-s", "6", "-a", "sharpness=2"],
    "aom_s6_dq3": AOM + ["-s", "6", "-a", "deltaq-mode=3"],
    "aom_s6_qm": AOM + ["-s", "6", "-a", "enable-qm=1"],
    # --- other encoders ---
    **{f"svt_s{s}": ["-c", "svt", "-s", str(s), "-y", "420"] for s in [4, 6, 8, 10]},
    **{f"rav1e_s{s}": ["-c", "rav1e", "-s", str(s)] for s in [4, 6, 8, 10]},
    # --- phase 2: stack knobs on speed 7 (enable-cdef / enable-restoration
    #     are overridden by libaom 3.8's all-intra speed features: no effect) ---
    "aom_s6_tune_psnr": AOM + ["-s", "6", "-a", "tune=psnr"],
    "aom_s7_10bit": AOM + ["-s", "7", "-d", "10"],
    # --- phase 3: libavif 1.4.2 + libaom 3.14.1 (defaults to tune=iq) ---
    **{f"new_s{s}": [NEW, *AOM, "-s", str(s)] for s in [4, 5, 6, 7, 8, 9]},
    "new_s6_ssim": [NEW, *AOM, "-s", "6", "-a", "tune=ssim"],
    **{f"new_s{s}_ssimu2": [NEW, *AOM, "-s", str(s), "-a", "tune=ssimulacra2"] for s in [6, 7, 8]},
    # --- phase 4: patched libaom (bit-identical to new_*, faster) + single
    #     internal speed-feature changes on top of speed 6 ---
    **{f"p_s{s}": [PATCHED, *AOM, "-s", str(s)] for s in [6, 7]},
    "p_s6_coeff7": [PATCHED, *AOM, "-s", "6", sf(perform_coeff_opt=7)],
    "p_s6_coeff8": [PATCHED, *AOM, "-s", "6", sf(perform_coeff_opt=8)],
    "p_s6_trellis_final": [PATCHED, *AOM, "-s", "6", sf(optimize_coefficients=2)],
    "p_s6_trellis_off": [PATCHED, *AOM, "-s", "6", sf(optimize_coefficients=0)],
    "p_s6_cdef5": [PATCHED, *AOM, "-s", "6", sf(cdef_pick_method=5)],
    "p_s6_cdefq": [PATCHED, *AOM, "-s", "6", sf(cdef_pick_method=6)],
    "p_s6_maxpart16": [PATCHED, *AOM, "-s", "6", sf(default_max_partition_size=6)],
    "p_s6_sqonly8": [PATCHED, *AOM, "-s", "6", sf(use_square_partition_only_threshold=3)],
    "p_s6_part4_4": [PATCHED, *AOM, "-s", "6", sf(prune_part4_search=4)],
    "p_s6_topintra1": [PATCHED, *AOM, "-s", "6", sf(top_intra_model_count_allowed=1)],
    # --- phase 4b: combinations of the cheapest wins ---
    "p_s6_t0_sq8": [PATCHED, *AOM, "-s", "6",
                    sf(optimize_coefficients=0, use_square_partition_only_threshold=3)],
    "p_s6_t0_sq8_cdefq": [PATCHED, *AOM, "-s", "6",
                          sf(optimize_coefficients=0, use_square_partition_only_threshold=3,
                             cdef_pick_method=6)],
    "p_s7_t0": [PATCHED, *AOM, "-s", "7", sf(optimize_coefficients=0)],
}


def run_one(config, args, image, q):
    with tempfile.TemporaryDirectory() as tmp:
        avif = Path(tmp) / "out.avif"
        png = Path(tmp) / "out.png"
        enc, dec = "avifenc", "avifdec"
        bins = {NEW: NEW_BIN, PATCHED: PATCHED_BIN}
        if args and args[0] in bins:
            b = bins[args[0]]
            enc, dec, args = str(b / "avifenc"), str(b / "avifdec"), args[1:]
        env = dict(os.environ)
        env.pop("AOM_SF", None)
        for a in [a for a in args if a.startswith("AOM_SF=")]:
            env["AOM_SF"] = a.split("=", 1)[1]
        args = [a for a in args if not a.startswith("AOM_SF=")]
        cmd = [enc, "-j", "1", *args, "-q", str(q), str(image), str(avif)]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env)
        _, status, ru = os.wait4(proc.pid, 0)
        err = proc.stderr.read().decode()
        proc.stderr.close()
        if os.waitstatus_to_exitcode(status) != 0:
            raise RuntimeError(f"{cmd} failed:\n{err}")
        if "WARNING" in err.upper() and "not used" in err:
            raise RuntimeError(f"{config}: avifenc ignored an option:\n{err}")
        cpu = ru.ru_utime + ru.ru_stime
        subprocess.run([dec, "-d", "8", str(avif), str(png)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        score = ssimulacra2.compute_ssimulacra2(str(image), str(png))
        return dict(config=config, image=image.name, q=q, bytes=avif.stat().st_size,
                    cpu_s=round(cpu, 4), ssimu2=round(score, 4))


def main():
    wanted = sys.argv[1:] or list(CONFIGS)
    done = set()
    if RESULTS.exists():
        with RESULTS.open() as f:
            done = {(r["config"], r["image"], int(r["q"])) for r in csv.DictReader(f)}
    jobs = [(c, CONFIGS[c], img, q) for c in wanted for img in IMAGES for q in QS
            if (c, img.name, q) not in done]
    print(f"{len(jobs)} encodes to run with {WORKERS} workers", flush=True)
    new_file = not RESULTS.exists()
    with RESULTS.open("a", newline="") as f, ProcessPoolExecutor(WORKERS) as ex:
        w = csv.DictWriter(f, FIELDS)
        if new_file:
            w.writeheader()
        futs = [ex.submit(run_one, *j) for j in jobs]
        for i, fut in enumerate(as_completed(futs), 1):
            w.writerow(fut.result())
            f.flush()
            if i % 50 == 0 or i == len(futs):
                print(f"  {i}/{len(futs)}", flush=True)


if __name__ == "__main__":
    main()
