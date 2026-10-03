#!/usr/bin/env python3
"""Compare every config in results.csv against the baseline.

For each image, a config's q-sweep gives a curve of (SSIMULACRA2, bytes, cpu).
We interpolate that curve at the baseline's operating point so comparisons are
quality-matched (or size-matched), instead of comparing raw -q values, which
mean different things for different encoders/settings.

Reported per config (geometric means over images):
  size@Q   : bytes needed to hit the baseline's SSIMULACRA2 score   (<1 better)
  time@Q   : encoder CPU time at that same quality                  (<1 faster)
  dQ@size  : SSIMULACRA2 change when given the baseline's byte budget (>0 better)
  time@size: encoder CPU time at that byte budget                   (<1 faster)
  BD-rate  : average size change over the overlapping quality range (<0 better)

Usage: python3 analyze.py [baseline_config] [baseline_q ...]
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
BASE = sys.argv[1] if len(sys.argv) > 1 else "aom_s6"
BASE_QS = [int(q) for q in sys.argv[2:]] or [50, 60, 70]


def load():
    data = defaultdict(lambda: defaultdict(list))  # config -> image -> rows
    with (ROOT / "results.csv").open() as f:
        for r in csv.DictReader(f):
            data[r["config"]][r["image"]].append(
                (int(r["q"]), float(r["ssimu2"]), int(r["bytes"]), float(r["cpu_s"])))
    return data


def interp(x, xs, ys):
    """Linear interpolation; NaN outside the measured range (no extrapolation)."""
    order = np.argsort(xs)
    xs, ys = np.asarray(xs)[order], np.asarray(ys)[order]
    if x < xs[0] or x > xs[-1]:
        return np.nan
    return float(np.interp(x, xs, ys))


def gmean(v):
    v = np.asarray(v, float)
    v = v[~np.isnan(v)]
    return float(np.exp(np.mean(np.log(v)))) if len(v) else np.nan


def bd_rate(base_rows, rows):
    """Bjontegaard-style delta rate on log(bytes) vs SSIMULACRA2 (piecewise linear)."""
    bs, bb = [r[1] for r in base_rows], [np.log(r[2]) for r in base_rows]
    ts, tb = [r[1] for r in rows], [np.log(r[2]) for r in rows]
    lo, hi = max(min(bs), min(ts)), min(max(bs), max(ts))
    if hi <= lo:
        return np.nan
    grid = np.linspace(lo, hi, 64)
    diff = [interp(s, ts, tb) - interp(s, bs, bb) for s in grid]
    return float(np.exp(np.mean(diff)) - 1)


def compare(data, cfg):
    out = {}
    for q0 in BASE_QS:
        size_r, time_r, dq, time_s, n_miss = [], [], [], [], 0
        for img, brows in data[BASE].items():
            rows = data[cfg].get(img)
            b = next((r for r in brows if r[0] == q0), None)
            if not rows or b is None:
                continue
            _, bscore, bbytes, bcpu = b
            scores = [r[1] for r in rows]
            lbytes = [np.log(r[2]) for r in rows]
            cpus = [r[3] for r in rows]
            sz = interp(bscore, scores, lbytes)
            n_miss += np.isnan(sz)
            size_r.append(np.exp(sz) / bbytes)
            time_r.append(interp(bscore, scores, cpus) / bcpu)
            dq.append(interp(np.log(bbytes), lbytes, scores) - bscore)
            time_s.append(interp(np.log(bbytes), lbytes, cpus) / bcpu)
        dq = np.asarray(dq)
        out[q0] = dict(size=gmean(size_r), time=gmean(time_r),
                       dq=float(np.nanmean(dq)) if (~np.isnan(dq)).any() else np.nan,
                       time_s=gmean(time_s), miss=n_miss)
    bd = [bd_rate(data[BASE][img], data[cfg][img]) for img in data[BASE] if img in data[cfg]]
    out["bd"] = float(np.nanmean(bd))
    out["cpu"] = gmean([r[3] for rows in data[cfg].values() for r in rows])
    return out


def verdict(m, tol=0.005):
    """Which of the three goals does this config meet at this operating point?"""
    g = []
    if m["time"] < 1 - tol and m["size"] <= 1 + tol:
        g.append("1:faster")
    if m["dq"] > 0.25 and m["time_s"] <= 1 + tol:
        g.append("2:better-Q")
    if m["size"] < 1 - tol and m["time"] <= 1 + tol:
        g.append("3:smaller")
    return " ".join(g) or "-"


def main():
    data = load()
    stats = {c: compare(data, c) for c in data}
    print(f"Baseline: {BASE}. Ratios are vs baseline (geomean over "
          f"{len(data[BASE])} images). Goals met at q={BASE_QS[len(BASE_QS)//2]}.\n")
    hdr = ["config", "BD-rate"]
    for q in BASE_QS:
        hdr += [f"size@Q{q}", f"time@Q{q}"]
    mid = BASE_QS[len(BASE_QS) // 2]
    hdr += [f"dQ@size{mid}", f"time@size{mid}", "goals"]
    print("| " + " | ".join(hdr) + " |")
    print("|" + "---|" * len(hdr))
    for c, s in sorted(stats.items(), key=lambda kv: kv[1]["bd"]):
        row = [c, f"{s['bd']*100:+.1f}%"]
        for q in BASE_QS:
            m = s[q]
            star = "*" if m["miss"] else ""
            row += [f"{m['size']:.3f}{star}", f"{m['time']:.2f}{star}"]
        m = s[mid]
        row += [f"{m['dq']:+.2f}", f"{m['time_s']:.2f}", verdict(m)]
        print("| " + " | ".join(row) + " |")
    print("\n`*` = some images could not reach the baseline's quality within the q sweep "
          "(excluded from that geomean).")


if __name__ == "__main__":
    main()
