#!/usr/bin/env bash
# Parameter sweeps, run AFTER width recovery is in place (the earlier evaluation
# conflated width and geometry, which is what this ordering avoids).
set -u
cd "$(dirname "$0")/../.."
B="python3 experiments/autotrace/bench.py"
IMGS="${IMGS:-house-wide dinosaur-wide landscape-square}"

case "${1:-all}" in
  stat)   # width statistic, with cap extension on
    for s in median trimmed p60 p75 mean; do
      $B --images $IMGS --label "stat-$s" --mode element --scale 4 --cap-extend --stat "$s"
    done ;;
  scale)  # raster resolution -- this backend's structural weakness (report 12.3)
    for r in 1 2 3 4 6 8; do
      $B --images $IMGS --label "scale-$r" --mode element --scale "$r" --cap-extend --stat trimmed
    done ;;
  strokescale)
    for k in 0.96 0.98 1.00 1.02 1.04; do
      $B --images $IMGS --label "ss-$k" --mode element --scale 4 --cap-extend --stat trimmed --stroke-scale "$k"
    done ;;
  atparams)  # autotrace's own knobs
    for e in 0.5 1 2 4; do
      $B --images $IMGS --label "et-$e" --mode element --scale 4 --cap-extend --stat trimmed --error-threshold "$e"
    done
    for c in 60 100 150; do
      $B --images $IMGS --label "ct-$c" --mode element --scale 4 --cap-extend --stat trimmed --corner-threshold "$c"
    done
    for f in 0 2 4 8; do
      $B --images $IMGS --label "fi-$f" --mode element --scale 4 --cap-extend --stat trimmed --filter-iterations "$f"
    done
    for d in 0 5 10 20; do
      $B --images $IMGS --label "ds-$d" --mode element --scale 4 --cap-extend --stat trimmed --despeckle-level "$d"
    done ;;
  granularity)  # the honest baseline ladder
    $B --images $IMGS --label "gran-raw"     --mode raw     --scale 4
    $B --images $IMGS --label "gran-color"   --mode color   --scale 4 --cap-extend --stat trimmed
    $B --images $IMGS --label "gran-element" --mode element --scale 4 --cap-extend --stat trimmed ;;
  *) echo "usage: sweep.sh {stat|scale|strokescale|atparams|granularity}"; exit 2 ;;
esac
