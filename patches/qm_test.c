/* Randomized bit-exactness test: C vs AVX2 libaom quantizers with qmatrix
 * (patches/0001). Build against the patched libaom static library:
 *   gcc -O2 -o qm_test qm_test.c <build>/_deps/libaom-build/libaom.a -lm -lpthread
 *   ./qm_test     # expect "0 mismatches" for both functions
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
typedef int32_t tran_low_t; typedef uint8_t qm_val_t;
#define P const tran_low_t *, intptr_t, const int16_t *, const int16_t *, tran_low_t *, tran_low_t *, const int16_t *, uint16_t *, const int16_t *, const int16_t *, const qm_val_t *, const qm_val_t *, int
void av1_quantize_fp_qm_c(P); void av1_quantize_fp_qm_avx2(P);
#define PB const tran_low_t *, intptr_t, const int16_t *, const int16_t *, const int16_t *, const int16_t *, tran_low_t *, tran_low_t *, const int16_t *, uint16_t *, const int16_t *, const int16_t *, const qm_val_t *, const qm_val_t *, const int
void aom_quantize_b_helper_c(PB); void aom_quantize_b_helper_avx2(PB);
static int msb(unsigned n) { int l = 0; while (n >>= 1) l++; return l; }
/* libaom's invert_quant(): quant may wrap negative in int16. */
static void invert_quant(int16_t *quant, int16_t *shift, int d) {
  int l = msb((unsigned)d), m = 1 + (1 << (16 + l)) / d;
  *quant = (int16_t)(m - (1 << 16)); *shift = (int16_t)(1 << (16 - l));
}
static uint64_t s = 88172645463325252ull;
static uint32_t rnd(void) { s ^= s << 13; s ^= s >> 7; s ^= s << 17; return (uint32_t)s; }
int main(void) {
  static tran_low_t c[4096], q0[4096], q1[4096], d0[4096], d1[4096];
  static int16_t scan[4096], iscan[4096]; static qm_val_t qm[4096], iqm[4096];
  const int sizes[] = {16, 32, 64, 128, 256, 512, 1024};
  long fails = 0, fails_b = 0, n = 0;
  for (int it = 0; it < 1500000; it++) {
    int nc = sizes[rnd() % 7], ls = rnd() % 3;
    for (int i = 0; i < nc; i++) scan[i] = i;
    for (int i = nc - 1; i > 0; i--) { int j = rnd() % (i + 1); int16_t t = scan[i]; scan[i] = scan[j]; scan[j] = t; }
    for (int i = 0; i < nc; i++) iscan[scan[i]] = i;
    int mode = rnd() % 4;
    for (int i = 0; i < nc; i++) {
      int32_t v;
      if (mode == 0) v = (int32_t)(rnd() % 64) - 32;                 // tiny / mostly zero
      else if (mode == 1) v = (int32_t)(rnd() % 8192) - 4096;        // typical
      else if (mode == 2) v = (int32_t)(rnd() % (1 << 22)) - (1 << 21); // large
      else v = (int32_t)rnd();                                       // full int32 range
      if (rnd() % 3 == 0) v = 0;
      if (v == INT32_MIN) v = INT32_MIN + 1;  /* abs(INT32_MIN) is UB in the C code */
      if (rnd() % 997 == 0) v = INT32_MIN + 1;
      c[i] = v; qm[i] = rnd() % 256; iqm[i] = rnd() % 256;
      if (rnd() % 50 == 0) qm[i] = 0;
    }
    int16_t dq[2] = { 4 + rnd() % 5000, 4 + rnd() % 5000 };
    if (rnd() % 10 == 0) { dq[0] = 4 + rnd() % 32760; dq[1] = 4 + rnd() % 32760; }
    int16_t qt[2] = { (int16_t)((1 << 16) / dq[0] > 32767 ? 32767 : (1 << 16) / dq[0]), (int16_t)((1 << 16) / dq[1] > 32767 ? 32767 : (1 << 16) / dq[1]) };
    if (rnd() % 10 == 0) { qt[0] = rnd() % 32768; qt[1] = rnd() % 32768; }
    int16_t rd[2] = { rnd() % (dq[0] + 1), rnd() % (dq[1] + 1) };
    /* quantize_b: realistic quant/shift from invert_quant(), sometimes random */
    {
      int16_t zb[2] = { rnd() % (dq[0] + 1), rnd() % (dq[1] + 1) };
      int16_t bq[2], bs[2];
      invert_quant(&bq[0], &bs[0], dq[0]); invert_quant(&bq[1], &bs[1], dq[1]);
      if (rnd() % 10 == 0) { bq[0] = (int16_t)rnd(); bq[1] = (int16_t)rnd(); }
      uint16_t f0 = 0xffff, f1 = 0xfffe;
      /* The C code computes |coeff| * wt in int (UB above 2^31 / 255), so
       * only test the range where it is defined. Real coeffs are < 2^20. */
      static tran_low_t cb[4096];
      for (int i = 0; i < nc; i++) {
        const int32_t lim = (1 << 23) - 1;
        cb[i] = c[i] > lim ? lim : c[i] < -lim ? -lim : c[i];
      }
      memset(q1, 0x55, sizeof(q1)); memset(d1, 0x55, sizeof(d1));
      aom_quantize_b_helper_c(cb, nc, zb, rd, bq, bs, q0, d0, dq, &f0, scan, iscan, qm, iqm, ls);
      aom_quantize_b_helper_avx2(cb, nc, zb, rd, bq, bs, q1, d1, dq, &f1, scan, iscan, qm, iqm, ls);
      if (f0 != f1 || memcmp(q0, q1, nc * 4) || memcmp(d0, d1, nc * 4)) {
        if (fails_b++ < 5) {
          printf("B MISMATCH it=%d nc=%d ls=%d eob %u/%u quant %d/%d shift %d/%d\n", it, nc, ls, f0, f1, bq[0], bq[1], bs[0], bs[1]);
          for (int i = 0; i < nc; i++) if (q0[i] != q1[i] || d0[i] != d1[i]) {
            printf("  i=%d c=%d wt=%d q %d/%d dq %d/%d\n", i, c[i], qm[i], q0[i], q1[i], d0[i], d1[i]); break; }
        }
      }
    }
    uint16_t e0 = 0xffff, e1 = 0xfffe;
    memset(q1, 0x55, sizeof(q1)); memset(d1, 0x55, sizeof(d1));
    av1_quantize_fp_qm_c(c, nc, rd, qt, q0, d0, dq, &e0, scan, iscan, qm, iqm, ls);
    av1_quantize_fp_qm_avx2(c, nc, rd, qt, q1, d1, dq, &e1, scan, iscan, qm, iqm, ls);
    n++;
    if (e0 != e1 || memcmp(q0, q1, nc * 4) || memcmp(d0, d1, nc * 4)) {
      if (fails++ < 5) {
        printf("MISMATCH it=%d nc=%d ls=%d eob %u/%u\n", it, nc, ls, e0, e1);
        for (int i = 0; i < nc; i++) if (q0[i] != q1[i] || d0[i] != d1[i]) {
          printf("  i=%d c=%d wt=%d iwt=%d q %d/%d dq %d/%d\n", i, c[i], qm[i], iqm[i], q0[i], q1[i], d0[i], d1[i]); break; }
      }
    }
  }
  printf("%ld blocks tested: quantize_fp_qm %ld mismatches, quantize_b_helper %ld mismatches\n", n, fails, fails_b);
  return fails != 0 || fails_b != 0;
}
