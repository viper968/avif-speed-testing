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

## Headline results (vs baseline, at baseline q60 quality)

| config | command (libavif 1.4.2 / libaom 3.14.1) | size @ same quality | encode time | quality @ same size | goals met |
|---|---|---|---|---|---|
| **new_s7** | `avifenc -s 7 -q <q>` (default `tune=iq`) | **−4.6%** | **0.60×** | **+0.96** | 1, 2, 3 |
| **new_s7_ssimu2** | `avifenc -s 7 -a tune=ssimulacra2 -q <q>` | **−5.8%** | **0.60×** | **+1.23** | 1, 2, 3 |
| new_s8 | `avifenc -s 8 -q <q>` | −2.6% | 0.40× | +0.57 | 1, 2, 3 |
| new_s8_ssimu2 | `avifenc -s 8 -a tune=ssimulacra2 -q <q>` | −4.0% | 0.41× | +0.83 | 1, 2, 3 |
| new_s6 | `avifenc -s 6 -q <q>` | −7.6% | 1.02× | +1.56 | 3 |
| new_s6_ssimu2 | `avifenc -s 6 -a tune=ssimulacra2 -q <q>` | −8.7% | 1.12× | +1.77 | (3, but ~10% slower) |

Pick one, then spend the gain on whichever axis you care about:

- **Goal 1 (faster):** `new_s8`, 2.5× faster *and* still 2.6% smaller.
- **Goal 2 (better quality):** `new_s7_ssimu2` at the same byte budget,
  +1.2 SSIMULACRA2 and 1.7× faster.
- **Goal 3 (smaller):** `new_s6`, 7.6% smaller at the same speed. Or take
  `new_s7` for −4.6% *and* 1.7× faster.

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

## Caveats

- **Averages, not guarantees.** With `new_s7`, 8 of 10 images got 4–15% smaller
  at equal quality, and 2 got up to 5% bigger. `new_s8` was bigger on 3/10.
- **Metric bias.** `tune=ssimulacra2` optimises for the very metric we score
  with, so its extra ~1% over `tune=iq` may be partly "teaching to the test".
  `tune=iq` is the safer recommendation. Next step: spot-check visually,
  and/or confirm with a second metric (Butteraugli, DSSIM).
- **Content.** 10 small natural photos. Screenshots, line art, or very large
  images may behave differently.
- **Timing noise** is about ±3% (the bit-identical no-op configs vary 0.99–1.02×).
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
```
