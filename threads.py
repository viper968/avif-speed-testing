#!/usr/bin/env python3
"""Thread-count / tiling sweep: wall time, CPU time, size and quality.

Encodes run strictly one at a time (so wall-clock time is meaningful) in a
shuffled order, REPS times; the median wall and CPU time are kept. Outputs are
then decoded and scored with SSIMULACRA2 in parallel (identical files, found by
hash, are scored once). Results go to threads_results.csv; --analyze prints
speedup and quality-matched size change relative to 1 thread without tiles.

Two image sets:
  kodak  the 10 Kodak photos in images/ (768x512, 0.4 MP)
  large  two 2304x1536 (3.5 MP) mosaics of 3x3 Kodak photos (build/large/)

Usage:
  python3 threads.py            # run (skips rows already in threads_results.csv)
  python3 threads.py --analyze
"""
import csv
import hashlib
import os
import random
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import ssimulacra2
from PIL import Image

import analyze
import bench

ROOT = bench.ROOT
OUT = ROOT / "threads_results.csv"
STORE = ROOT / "build" / "threads"
ENC_BIN = Path(os.environ.get("AVIF_PATCHED_BIN", bench.PATCHED_BIN))
REPS = int(os.environ.get("REPS", 3))
THREADS = [1, 2, 3, 4, 8]
TILINGS = {
    "none": [],
    "auto": ["--autotiling"],
    "2": ["--tilecolslog2", "1"],
    "2x2": ["--tilecolslog2", "1", "--tilerowslog2", "1"],
}
SETS = {
    "kodak": dict(qs=bench.QS, tilings=["none", "auto", "2x2"]),
    "large": dict(qs=[40, 50, 60, 70, 80], tilings=["none", "auto", "2", "2x2"]),
}
# Patched libaom, speed 6, default tune=iq (bit-identical to stock 1.4.2).
BASE_ARGS = ["-c", "aom", "-s", "6"]
FIELDS = ["set", "threads", "tiling", "image", "q", "bytes", "wall_s", "cpu_s", "ssimu2", "md5"]


def images(set_name):
    if set_name == "kodak":
        return bench.IMAGES
    out = ROOT / "build" / "large"
    out.mkdir(parents=True, exist_ok=True)
    kodak = bench.IMAGES
    paths = []
    for name, picks in [("mosaicA", kodak[0:9]), ("mosaicB", kodak[1:10])]:
        p = out / f"{name}.png"
        if not p.exists():
            tiles = [Image.open(f).convert("RGB") for f in picks]
            w, h = tiles[0].size
            m = Image.new("RGB", (3 * w, 3 * h))
            for i, t in enumerate(tiles):
                m.paste(t.resize((w, h)), ((i % 3) * w, (i // 3) * h))
            m.save(p)
        paths.append(p)
    return paths


def encode(threads, tiling, image, q):
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.avif"
        cmd = [str(ENC_BIN / "avifenc"), "-j", str(threads), *BASE_ARGS, *TILINGS[tiling],
               "-q", str(q), str(image), str(out)]
        t0 = time.perf_counter()
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _, status, ru = os.wait4(proc.pid, 0)
        wall = time.perf_counter() - t0
        if os.waitstatus_to_exitcode(status) != 0:
            raise RuntimeError(f"{cmd} failed")
        data = out.read_bytes()
    md5 = hashlib.md5(data).hexdigest()
    STORE.mkdir(parents=True, exist_ok=True)
    stored = STORE / f"{md5}.avif"
    if not stored.exists():
        stored.write_bytes(data)
    return wall, ru.ru_utime + ru.ru_stime, len(data), md5


def score(md5, image):
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "out.png"
        subprocess.run([str(ENC_BIN / "avifdec"), "-d", "8", str(STORE / f"{md5}.avif"), str(png)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return md5, round(ssimulacra2.compute_ssimulacra2(str(image), str(png)), 4)


def run():
    done = set()
    if OUT.exists():
        with OUT.open() as f:
            done = {(r["set"], int(r["threads"]), r["tiling"], r["image"], int(r["q"]))
                    for r in csv.DictReader(f)}
    jobs = []
    for set_name, cfg in SETS.items():
        for img in images(set_name):
            for j in THREADS:
                for tiling in cfg["tilings"]:
                    for q in cfg["qs"]:
                        key = (set_name, j, tiling, img.name, q)
                        if key not in done:
                            jobs.append((key, img))
    print(f"{len(jobs)} configs x {REPS} reps, sequential", flush=True)
    timings = {}
    order = [job for job in jobs for _ in range(REPS)]
    random.seed(1)
    random.shuffle(order)
    for i, (key, img) in enumerate(order, 1):
        _, j, tiling, _, q = key
        wall, cpu, size, md5 = encode(j, tiling, img, q)
        t = timings.setdefault(key, dict(wall=[], cpu=[], bytes=size, md5=md5, img=img))
        if t["md5"] != md5:
            raise RuntimeError(f"non-deterministic output for {key}")
        t["wall"].append(wall)
        t["cpu"].append(cpu)
        if i % 200 == 0:
            print(f"  encoded {i}/{len(order)}", flush=True)
    unique = {(t["md5"], t["img"]) for t in timings.values()}
    print(f"scoring {len(unique)} unique outputs", flush=True)
    with ProcessPoolExecutor(bench.WORKERS) as ex:
        scores = dict(ex.map(score, *zip(*unique))) if unique else {}
    new_file = not OUT.exists()
    with OUT.open("a", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        if new_file:
            w.writeheader()
        for (set_name, j, tiling, image, q), t in timings.items():
            w.writerow(dict(set=set_name, threads=j, tiling=tiling, image=image, q=q,
                            bytes=t["bytes"], wall_s=round(statistics.median(t["wall"]), 4),
                            cpu_s=round(statistics.median(t["cpu"]), 4),
                            ssimu2=scores[t["md5"]], md5=t["md5"]))


def report():
    rows = list(csv.DictReader(OUT.open()))
    for set_name, cfg in SETS.items():
        data = {}
        for r in rows:
            if r["set"] != set_name:
                continue
            k = (int(r["threads"]), r["tiling"])
            data.setdefault(k, {}).setdefault(r["image"], []).append(
                (int(r["q"]), float(r["ssimu2"]), int(r["bytes"]), float(r["wall_s"]),
                 float(r["cpu_s"])))
        base = data[(1, "none")]
        print(f"\n### {set_name}: {len(base)} images, vs 1 thread / no tiles "
              f"(times: geomean over images and q)\n")
        print("| threads | tiling | wall speedup | wall time | CPU time | BD-rate | size @ same quality |"
              " identical files |")
        print("|---|---|---|---|---|---|---|---|")
        mid = cfg["qs"][len(cfg["qs"]) // 2]
        for tiling in cfg["tilings"]:
            for j in THREADS:
                d = data.get((j, tiling))
                if not d:
                    continue
                wall_r, cpu_r, size_r, bds, same, total = [], [], [], [], 0, 0
                for img, brows in base.items():
                    rows_ = sorted(d[img])
                    b = sorted(brows)
                    for (q, s, by, wa, cp), (_, bs, bby, bwa, bcp) in zip(rows_, b):
                        wall_r.append(wa / bwa)
                        cpu_r.append(cp / bcp)
                        same += (by == bby and s == bs)
                        total += 1
                    bmid = next(r for r in b if r[0] == mid)
                    sz = analyze.interp(bmid[1], [r[1] for r in rows_], [np.log(r[2]) for r in rows_])
                    size_r.append(np.exp(sz) / bmid[2])
                    bds.append(analyze.bd_rate(b, rows_))
                wall = analyze.gmean(wall_r)
                print(f"| {j} | {tiling} | {1 / wall:.2f}x | {wall:.2f} | {analyze.gmean(cpu_r):.2f} |"
                      f" {np.nanmean(bds) * 100:+.2f}% | {analyze.gmean(size_r):.4f} | {same}/{total} |")


if __name__ == "__main__":
    report() if "--analyze" in sys.argv else run()
