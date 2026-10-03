#!/usr/bin/env bash
# Build libavif 1.4.2 with its bundled libaom (3.14.1) into build/libavif/build.
# bench.py uses these binaries for the "new_*" configs (override with AVIF_NEW_BIN).
# Needs: git cmake ninja nasm gcc libpng-dev libjpeg-dev zlib1g-dev
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p build
[ -d build/libavif ] || git clone --depth 1 -b v1.4.2 https://github.com/AOMediaCodec/libavif build/libavif
cmake -S build/libavif -B build/libavif/build -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF -DAVIF_CODEC_AOM=LOCAL -DAVIF_CODEC_DAV1D=OFF \
  -DAVIF_LIBYUV=OFF -DAVIF_BUILD_APPS=ON -DAVIF_JPEG=SYSTEM -DAVIF_ZLIBPNG=SYSTEM \
  -DAVIF_LIBXML2=OFF -DAVIF_LIBSHARPYUV=OFF
cmake --build build/libavif/build
build/libavif/build/avifenc --version | head -1
