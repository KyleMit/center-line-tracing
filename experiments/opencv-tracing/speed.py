"""Standalone runtime benchmark, merged into `metrics.json`.

    python3 experiments/opencv-tracing/speed.py [target ...]

Split out of bench.py so the headline number of this track can be produced (and
re-produced) without re-running the whole quality matrix. Speed is the entire
value proposition here (report §16): if `cv2.ximgproc.thinning` is not
meaningfully faster than Track 3's `skimage.morphology.medial_axis`, this track
has no reason to exist, so the comparison is run on byte-identical masks in one
process on one machine.
"""

from __future__ import annotations

import json
import sys

import bench


def main():
    names = sys.argv[1:] or None
    targets = bench.resolve_targets(names)

    speed = bench.speed_comparison(targets, bench.DEFAULT_CONFIG["scale"])
    agreement = bench.tracer_agreement(targets, bench.DEFAULT_CONFIG)

    out = bench.DEBUG / "metrics.json"
    payload = json.loads(out.read_text())
    payload["speed"] = speed
    payload["speedTargets"] = [t["name"] for t in targets]
    payload["tracerAgreement"] = agreement
    out.write_text(json.dumps(payload, indent=1))

    bench._print_speed(speed)
    print("\nCross-runtime agreement vs st-c:")
    for label, per_target in agreement.items():
        checked = {k: v for k, v in per_target.items() if v is not None}
        exact = sum(1 for v in checked.values() if v["exact"])
        worst = max((v["maxDeviationPx"] for v in checked.values()), default=0.0)
        print(f"  {label}: bit-identical on {exact}/{len(checked)} targets, "
              f"worst deviation {worst:.2f}px "
              f"({len(per_target) - len(checked)} skipped)")
        for name, entry in checked.items():
            if not entry["exact"]:
                print(f"    - {name}: maxDev {entry['maxDeviationPx']:.2f}px, "
                      f"same polyline count: {entry['samePolylineCount']}")
    print(f"\nmerged into {out}")


if __name__ == "__main__":
    main()
