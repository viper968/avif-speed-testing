# avif-speed-testing

Can we beat the default AVIF encode on one of speed / quality / size without
giving up the other two?

1. faster, same-or-better quality, same-or-better size
2. same-or-better speed, better quality, same-or-better size
3. same-or-better speed, same-or-better quality, smaller size

**Yes, all three, by upgrading the encoder (libavif 1.4.2 + libaom 3.14.1)
and using its new still-image tunings.** No combination of settings on the
older system encoder (libavif 1.0.4 + libaom 3.8.2) managed it.

## Method

- **Baseline:** `avifenc -s 6 -q 60` on libavif 1.0.4 / libaom 3.8.2, i.e. the
  out-of-the-box defaults (libaom, speed 6, 4:4:4, 8-bit, `tune=ssim`).
- **Images:** 10 Kodak photos (768×512) in `images/`.
- **Quality:** [SSIMULACRA2](https://github.com/cloudinary/ssimulacra2)
  (perceptual, 0–100, higher is better; ~70 ≈ "high quality", ~80 ≈
  "very high"). Baseline at q60 averages ~78.
- **Speed:** encoder CPU time (user+sys, single-threaded `-j 1`).
- **Size:** file bytes.
- **Fair comparison:** every config is swept over `-q` 40–80. Per image, we
  interpolate its curve at the *baseline's* SSIMULACRA2 score, giving size and
  time at equal quality (`size@Q`, `time@Q`). We also interpolate at the
  baseline's byte count, giving the quality change at equal size (`dQ@size`).
  Results are geomeans over images. BD-rate is the average size change across
  the whole overlapping quality range.

Comparing raw `-q` values across settings is meaningless: `-q 60` with
`tune=iq` is a very different quality than `-q 60` with `tune=ssim`.

## Headline results (vs baseline, at baseline q60 quality; times re-measured together)

| config | command (libavif 1.4.2 / libaom 3.14.1) | size @ same quality | encode time | quality @ same size | goals met |
|---|---|---|---|---|---|
| **new_s7** | `avifenc -s 7 -q <q>` (default `tune=iq`) | **−4.6%** | **0.57×** | **+0.96** | 1, 2, 3 |
| **new_s7_ssimu2** | `avifenc -s 7 -a tune=ssimulacra2 -q <q>` | **−5.8%** | **0.57×** | **+1.23** | 1, 2, 3 |
| new_s8 | `avifenc -s 8 -q <q>` | −2.6% | 0.40× | +0.57 | 1, 2, 3 |
| new_s8_ssimu2 | `avifenc -s 8 -a tune=ssimulacra2 -q <q>` | −4.0% | 0.39× | +0.83 | 1, 2, 3 |
| new_s6 | `avifenc -s 6 -q <q>` | −7.6% | 1.04× | +1.56 | 3 (within timing noise) |
| new_s6_ssimu2 | `avifenc -s 6 -a tune=ssimulacra2 -q <q>` | −8.7% | 1.04× | +1.77 | 3 (within timing noise) |

Pick one, then spend the gain on whichever axis you care about:

- **Goal 1 (faster):** `new_s8`, 2.5× faster *and* still 2.6% smaller (with patch 0001 below, even faster).
- **Goal 2 (better quality):** `new_s7_ssimu2` at the same byte budget,
  +1.2 SSIMULACRA2 and 1.75× faster.
- **Goal 3 (smaller):** `new_s6`, 7.6% smaller at the same speed. Or take
  `new_s7` for −4.6% *and* 1.75× faster. With patch 0001 + `-a disable-trellis-quant=1`,
  speed 6 is 7.4% smaller *and* 0.78× time (see below).

**`-q` must be re-calibrated** after switching, because the same `-q` number no
longer means the same quality. To match the baseline's `-q 60`, these images
needed on average `-q 63–64` with `tune=iq` (per image 56–69) and `-q 58` with
`tune=ssimulacra2` (51–64). Pick `-q` by target quality, not by number.
`results.csv` has the per-image curves.

### Why it works

`new_s6_ssim` (new encoder forced back to `tune=ssim`) is the same as the
baseline (+0.7% BD-rate, ~0.9× time). So the win is **not** from the libaom
version alone. It comes from **`tune=iq`** (libavif's default since 1.2) and
**`tune=ssimulacra2`**, which are image-quality tunings built for stills.
They save enough bits to pay for dropping a speed preset (6 → 7).

### What didn't work (libavif 1.0.4 / libaom 3.8.2)

| setting | BD-rate | time | notes |
|---|---|---|---|
| speed 0–5 | −11% … −7% | 4–50× | smaller, but far slower |
| speed 7 | +3.0% | 0.54× | best pure speed trade |
| speed 8–10 | +14% … +17% | 0.17–0.41× | 9 and 10 produce identical output |
| 10-bit (`-d 10`) | −2.0% | 1.3× | only knob that saves bytes, but costs time |
| speed 7 + 10-bit | +1.9% | 0.75× | ±0% size at q70, +1.3% at q60: borderline |
| 4:2:0 / 4:2:0 + sharpyuv | +5.3% / +3.9% | ~0.9–1.0× | SSIMULACRA2 punishes chroma loss |
| `tune=psnr` | +5.2% | 1.04× | default `tune=ssim` is already better |
| `enable-qm=1`, `sharpness=2` | +4.4%, +6.2% | ~1× | worse |
| `deltaq-mode=3`, `enable-chroma-deltaq=1` | ~0% | ~1× | no gain |
| `aq-mode=1`, `tune=ssim` | 0% | 1× | no-ops (bit-identical output) |
| `enable-cdef=0`, `enable-restoration=1` | — | — | no-ops at speed 7 (overridden by all-intra speed features) |
| SVT-AV1 (speed 4–10, 4:2:0) | +3% … +7% | 1.6–7.6× | slower *and* bigger for stills |
| rav1e (speed 4–10) | 0% … +25% | 0.6–13× | not competitive |

Full table: [RESULTS.md](RESULTS.md). Raw data: `results.csv`.

## Code-level speedups inside libaom

Profiling `avifenc -s 6` (libaom 3.14.1, `tune=iq`) with callgrind showed the
quantizers running as **scalar C**: `tune=iq`/`tune=ssimulacra2` enable
quantization matrices, and libaom's qmatrix quantizer paths had no x86 SIMD
(`av1_quantize_fp_facade` → `quantize_fp_helper_c`, 16% of instructions; and
`av1_quantize_b_facade` called `aom_quantize_b_helper_c` directly, bypassing
CPU dispatch, so even the existing ARM NEON version was never used).

### Patch 0001: AVX2 quantizers with qmatrix (output byte-identical)

[`patches/0001-libaom-avx2-quantizers-with-qmatrix.patch`](patches/0001-libaom-avx2-quantizers-with-qmatrix.patch)
adds rtcd-dispatched AVX2 versions of both. They reproduce the C code's exact
integer behaviour, including where C uses 64-bit math, where its 32-bit
multiply wraps, and the negative `int16` `quant` values libaom produces.

- **Verified bit-exact:** [`patches/qm_test.c`](patches/qm_test.c) runs 1.5M
  random blocks per function with 0 mismatches. 600 real encodes (10 images ×
  5 q × speed 6/7 × tune iq/ssimulacra2 × trellis full/off/final) produce
  byte-identical `.avif` files.
- **Speed:** 10–13% less encoder CPU at speeds 6, 7 and 8 (sequential A/B).

### Speed features: cheaper than going to speed 7

Speed 7 isn't a small step: it replaces RD partition search with the
real-time variance-based partitioner, guesses CDEF strength from q, and skips
intra modes. To find cheaper trade-offs, the experiment-only
[`patches/0002`](patches/0002-libaom-EXPERIMENT-AOM_SF-speed-feature-overrides.patch)
adds an `AOM_SF="name=value,..."` env var that overrides individual speed
features, and each was measured on top of speed 6.

All configs below were re-timed together in one shuffled run (`retime.py`),
because CPU time on this VM drifts ~15% between runs. Baseline here is
**stock libavif 1.4.2 / libaom 3.14.1 speed 6**:

| config | how | encode time | BD-rate | size @ q60 quality |
|---|---|---|---|---|
| new_s6 (stock) | `-s 6` | 1.00× | 0% | 1.000 |
| **p_s6** | patch 0001, `-s 6` | **0.87×** | **0%** (identical files) | 1.000 |
| **p_s6_trellis_off** | patch 0001, `-s 6 -a disable-trellis-quant=1` | **0.75×** | **+0.3%** | 1.008 |
| p_s6_sqonly8 | + `use_square_partition_only_threshold=BLOCK_8X8` | 0.78× | +0.9% | 1.008 |
| **p_s6_t0_sq8** | trellis off + square-only above 8×8 | **0.68×** | **+1.0%** | 1.013 |
| p_s6_t0_sq8_cdefq | + CDEF strength from q | 0.66× | +1.4% | 1.013 |
| p_s6_trellis_final | trellis only in the final pass | 0.76× | +1.5% | 1.012 |
| new_s7 (stock) | `-s 7` | 0.54× | +4.1% | 1.040 |
| p_s7 | patch 0001, `-s 7` | 0.49× | +4.1% | 1.040 |
| p_s7_trellis_off | patch 0001, `-s 7 -a disable-trellis-quant=1` | 0.43× | +4.7% | 1.044 |

No measurable effect at speed 6 (±0.5% BD-rate, ±3% time): `perform_coeff_opt`
7/8, `prune_part4_search=4`, `top_intra_model_count_allowed=1`, CDEF fast-search
level 5. `default_max_partition_size=16X16` cost +1.1% for only ~5%.

**Takeaways**
- **Free:** patch 0001 makes every `tune=iq` encode ~11% faster with identical output.
- **Trellis is nearly worthless with `tune=iq`** (+0.3% BD-rate) once the
  replacement quantizer is vectorized: `-a disable-trellis-quant=1` is a 25%
  speedup for almost no loss. (Without patch 0001 it only saves ~5%, because the
  fallback quantizer was scalar.)
- **"Speed 6.5":** trellis off + square-only partitions above 8×8 is **32%
  faster than stock speed 6 for +1.0% BD-rate**. That's a new point on the curve
  between speed 6 and 7 (which costs +4.1%). The partition change has no public
  option; it would be a one-line preset change in `av1/encoder/speed_features.c`.
- Per image, `p_s6_t0_sq8` ranged from −0.8% to +3.7% size vs stock speed 6
  at equal quality, and trellis-off from −1.3% to +2.4%.
- Versus the original system baseline (libavif 1.0.4 speed 6): `p_s6_trellis_off`
  is 0.78× time and 7.4% smaller; `p_s6_t0_sq8` is 0.71× time and 7.0% smaller.

### New search methods tried (none paid off)

Profiling the "speed 6.5" config (patched, trellis off, square-only above 8×8)
showed the cost is now spread across mode decision: luma intra-mode search
41%, chroma intra-mode search 17%, final/dry-run block encode ~15%, bitstream
writing ~9%. (PNG decode 7% and RGB→YUV 5% also show up, but the RGB→YUV
cost comes from building without libyuv, which normal libavif builds use.)

Before writing code, each idea was checked with temporary instrumentation
counters in libaom, and three were rejected on the data alone:

| idea | measurement | verdict |
|---|---|---|
| Skip the exact rate calculation when transform-domain distortion alone already loses (exact, lossless) | would skip only ~0.5% of transform-type evaluations | not worth it |
| Rank all luma modes by the Hadamard model first, full RD only on the top K | only ~2.4 modes/block get full RD today; winner is model rank 1 only ~60% (top-3: 87%) | small K loses quality, larger K saves nothing |
| Decide transform size once per block, reuse across modes | libaom already does this (mode eval uses largest tx; size search only for the winner) | already exists |
| Closed-form CfL alpha instead of the stepwise search | the walk already stops after 1 failed step each way in the common case | little to gain |

Two were implemented as an experiment-only patch
([`patches/0003`](patches/0003-libaom-EXPERIMENT-AOM_EXP-new-search-shortcuts.patch),
`AOM_EXP` env var) and benchmarked on top of speed 6.5 (all re-timed together):

| `AOM_EXP` | method | time | BD-rate |
|---|---|---|---|
| 1 | context-free (Laplacian) coefficient rate for luma during mode evaluation; exact rate kept for the winner/final pass | 0.98× | **+2.2%** |
| 2 | prune chroma intra modes whose Hadamard model cost (U+V) > 1.5× the best so far (luma has this, chroma didn't) | 1.02× | 0.0% |
| 4 | same, threshold 1.25× | 1.01× | 0.0% |

The approximate rate makes worse mode choices for little time saved. Chroma
pruning costs about as much as it saves, because libaom already drops most
chroma modes cheaply (mode-rate bound and early exit in the transform RD).
Conclusion: at speed 6, libaom's remaining search is already tightly pruned.
The big remaining cost, the intra mode/partition search itself, is what speed 7
cuts, and that is where its +4% comes from.

## Caveats

- **Averages, not guarantees.** With `new_s7`, 8 of 10 images got 4–15% smaller
  at equal quality, and 2 got up to 5% bigger. `new_s8` was bigger on 3/10.
- **Metric bias.** `tune=ssimulacra2` optimises for the very metric we score
  with, so its extra ~1% over `tune=iq` may be partly "teaching to the test".
  `tune=iq` is the safer recommendation. Next step: spot-check visually,
  and/or confirm with a second metric (Butteraugli, DSSIM).
- **Content.** 10 small natural photos. Screenshots, line art, or very large
  images may behave differently.
- **Timing noise** is about ±3% within a run (bit-identical no-op configs vary 0.99–1.02×), and absolute CPU time drifted ~15% *between* runs on this VM. Only compare times measured together; the configs in the tables above were re-timed in one run with `retime.py`.
- **Decode speed** was not measured.
- The new build has libyuv disabled; it uses libavif's built-in RGB→YUV.
  That's slightly slower if anything, so it doesn't flatter the new encoder.

## Reproduce

```sh
apt-get install libavif-bin nasm libpng-dev libjpeg-dev zlib1g-dev cmake ninja-build
pip install numpy pillow ssimulacra2
./build_new_avif.sh               # libavif 1.4.2 + libaom 3.14.1 -> build/libavif/build
python3 bench.py                  # all configs (cached in results.csv; add configs in CONFIGS)
python3 bench.py new_s7 new_s8    # or just some
python3 analyze.py                # comparison table vs aom_s6 at q 50/60/70
python3 analyze.py new_s6 60      # use a different baseline / operating point
python3 retime.py aom_s6 new_s7   # re-measure CPU time for configs together
```

`build_new_avif.sh` builds both the stock libavif 1.4.2 / libaom 3.14.1
(`build/libavif/build`) and a copy with `patches/*.patch` applied
(`build/patched`), which `bench.py` uses for the `p_*` configs.
