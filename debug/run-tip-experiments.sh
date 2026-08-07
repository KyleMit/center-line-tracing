#!/bin/bash
# Tip-reconstruction experiment matrix for the landscape + dinosaur inputs.
# Writes candidate SVGs and pixel metrics under debug/.
set -e
cd "$(dirname "$0")/.."
PY="DYLD_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python"

eval $PY -m py_compile src/convert_filled_svg_to_stroked_lines.py && echo "compile OK"

common="--mode elements --scale 4 --simplify-epsilon 0 --max-stroke-width 30 \
  --skeleton-method zhang --trace-mode paired --overlap-spur-max 80"

run() {
  name=$1; input=$2; shift 2
  eval $PY src/convert_filled_svg_to_stroked_lines.py "inputs/$input.svg" \
    --output "debug/$input-$name.svg" $common "$@" >/dev/null
  node src/compare.js "inputs/$input.svg" "debug/$input-$name.svg" 1200 \
    "debug/$input-$name-diff.png" | grep differing | sed "s|^|$input/$name: |"
}

for input in landscape dinosaur; do
  run baselineExc "$input" --stroke-scale 1.07
  run excCaps        "$input" --calibrate-caps --stroke-scale 1.07
  run cornerT150     "$input" --tip-mode corner --tip-spur-max 150 --stroke-scale 1.07
  run cornerT150Caps "$input" --tip-mode corner --tip-spur-max 150 --calibrate-caps --stroke-scale 1.07
  run cornerT150CapsS1 "$input" --tip-mode corner --tip-spur-max 150 --calibrate-caps --stroke-scale 1.0
done
