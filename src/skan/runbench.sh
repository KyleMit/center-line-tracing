#!/usr/bin/env bash
# Full reproducible bench matrix for this pipeline.
#   bash src/skan/runbench.sh
# Takes ~20 minutes.  Results merge into runs/metrics.json,
# keyed by (image, tag), so re-running one section refreshes just that section.
set -euo pipefail
cd "$(dirname "$0")/../.."

B="python3 src/skan/bench.py"
LADDER=house-wide,butterfly-wide,boat-tall,island-tall,balloon-tall,home-wide,house-tall,dinosaur-wide,landscape-square,sun-square

python3 src/skan/corpus.py

echo "### corpus: medial-axis vs skeletonize @4"
$B corpus --methods medial-axis,skeletonize

echo "### corpus: resolution sweep"
for s in 1 2 8 16; do $B corpus --scale $s --methods medial-axis; done

echo "### corpus: cap extension"
$B corpus --cap-extend

echo "### corpus: piecewise width"
$B corpus --width-mode piecewise

echo "### ladder: constant width (baseline)"
$B inputs --images "$LADDER"

echo "### ladder: piecewise width (promoted)"
$B inputs --images "$LADDER" --width-mode piecewise --promote

echo "### ladder: thinning comparison"
$B inputs --images house-wide,dinosaur-wide,landscape-square,sun-square \
   --methods skeletonize --width-mode piecewise

echo "### ladder: cap extension"
$B inputs --images house-wide,dinosaur-wide,sun-square --width-mode piecewise --cap-extend

echo "### real resolution sweep"
$B sweep --images house-wide,sun-square --scales 1,2,8 --width-mode piecewise

echo "### contact sheets"
python3 src/skan/sheets.py comparison --tag 'medial-axis@4+pw' --crops 2
python3 src/skan/sheets.py comparison --tag 'medial-axis@4+pw' --corpus --crops 0 --name corpus
python3 src/skan/sheets.py progress --image sun-square
python3 src/skan/sheets.py progress --image house-wide

$B report
