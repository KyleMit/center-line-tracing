#!/usr/bin/env bash
# Build the vendored skeleton-tracing C implementation as a shared library for
# ctypes. Run once per checkout; the .so is gitignored.
set -euo pipefail
cd "$(dirname "$0")/vendor/skeleton-tracing/c"
gcc -O3 -fPIC -shared -std=c99 st_shim.c -o libtraceskeleton.so -lm
echo "built $(pwd)/libtraceskeleton.so"
