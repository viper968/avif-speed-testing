#!/usr/bin/env python3
"""Re-measure encoder CPU time for a set of configs in one shuffled run.

CPU time on a shared/cloud machine drifts between runs (we saw ~15%), so time
ratios are only trustworthy between configs measured together. This re-encodes
every (config, image, q) of the given configs, in random order, REPS times,
and writes the median CPU time back into results.csv (size and quality are
deterministic and left untouched).

Usage: python3 retime.py aom_s6 new_s7 p_s6 ...
"""
import csv
import os
import random
import statistics
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import bench

REPS = int(os.environ.get("REPS", 2))


def encode_cpu(config, image, q):
    args = list(bench.CONFIGS[config])
    enc = "avifenc"
    bins = {bench.NEW: bench.NEW_BIN, bench.PATCHED: bench.PATCHED_BIN}
    if args and args[0] in bins:
        enc, args = str(bins[args[0]] / "avifenc"), args[1:]
    env = dict(os.environ)
    env.pop("AOM_SF", None)
    for a in [a for a in args if a.startswith("AOM_SF=")]:
        env["AOM_SF"] = a.split("=", 1)[1]
    args = [a for a in args if not a.startswith("AOM_SF=")]
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [enc, "-j", "1", *args, "-q", str(q), str(bench.ROOT / "images" / image),
               str(Path(tmp) / "out.avif")]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        _, status, ru = os.wait4(proc.pid, 0)
        if os.waitstatus_to_exitcode(status) != 0:
            raise RuntimeError(f"{cmd} failed")
        return (config, image, q), ru.ru_utime + ru.ru_stime


def main():
    configs = sys.argv[1:]
    with bench.RESULTS.open() as f:
        rows = list(csv.DictReader(f))
    keys = [(r["config"], r["image"], int(r["q"])) for r in rows if r["config"] in configs]
    jobs = keys * REPS
    random.seed(0)
    random.shuffle(jobs)
    print(f"{len(jobs)} timed encodes ({len(keys)} x {REPS})", flush=True)
    times = {}
    with ProcessPoolExecutor(bench.WORKERS) as ex:
        for i, (key, cpu) in enumerate(ex.map(encode_cpu, *zip(*jobs), chunksize=4), 1):
            times.setdefault(key, []).append(cpu)
            if i % 500 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)
    for r in rows:
        key = (r["config"], r["image"], int(r["q"]))
        if key in times:
            r["cpu_s"] = round(statistics.median(times[key]), 4)
    with bench.RESULTS.open("w", newline="") as f:
        w = csv.DictWriter(f, bench.FIELDS)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
