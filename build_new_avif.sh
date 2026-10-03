#!/usr/bin/env bash
# Build libavif 1.4.2 + libaom 3.14.1 twice:
#   build/libavif/build  stock          (bench.py "new_*" configs, AVIF_NEW_BIN)
#   build/patched        patches/ applied (bench.py "p_*" configs, AVIF_PATCHED_BIN)
# Needs: git cmake ninja nasm gcc libpng-dev libjpeg-dev zlib1g-dev
set -euo pipefail
cd "$(dirname "$0")"
ROOT=$PWD
mkdir -p build
[ -d build/libavif ] || git clone --depth 1 -b v1.4.2 https://github.com/AOMediaCodec/libavif build/libavif

AVIF_FLAGS=(-G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF
  -DAVIF_CODEC_AOM=LOCAL -DAVIF_CODEC_DAV1D=OFF -DAVIF_LIBYUV=OFF
  -DAVIF_BUILD_APPS=ON -DAVIF_JPEG=SYSTEM -DAVIF_ZLIBPNG=SYSTEM
  -DAVIF_LIBXML2=OFF -DAVIF_LIBSHARPYUV=OFF)

# Stock build (libavif fetches libaom v3.14.1 itself).
cmake -S build/libavif -B build/libavif/build "${AVIF_FLAGS[@]}"
cmake --build build/libavif/build

# Patched build: same libaom tag, with patches/*.patch applied.
if [ ! -d build/aom-patched ]; then
  git clone --depth 1 -b v3.14.1 https://aomedia.googlesource.com/aom build/aom-patched
  for p in "$ROOT"/patches/*.patch; do git -C build/aom-patched apply "$p"; done
fi
cmake -S build/libavif -B build/libavif/build-patched "${AVIF_FLAGS[@]}" \
  -DFETCHCONTENT_SOURCE_DIR_LIBAOM="$ROOT/build/aom-patched"
cmake --build build/libavif/build-patched
mkdir -p build/patched
cp build/libavif/build-patched/avifenc build/libavif/build-patched/avifdec build/patched/

build/libavif/build/avifenc --version | head -1
build/patched/avifenc --version | head -1
