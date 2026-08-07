#!/usr/bin/env python3
"""Validate centerline graph JSON against schema v1.

Any track can run this against its own output:

    python3 experiments/pruning-scoring/validate_graphs.py debug/<slug>/graphs
    python3 experiments/pruning-scoring/validate_graphs.py --all --strict

Exit code is 0 when every file passes (no errors), 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clg.schema import validate_document  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def iter_files(targets: list[str], all_tracks: bool) -> list[Path]:
    files: list[Path] = []
    if all_tracks:
        targets = [str(p) for p in sorted((REPO / "debug").glob("*/graphs"))]
    for t in targets:
        p = Path(t)
        if not p.is_absolute():
            p = REPO / p
        if p.is_dir():
            files.extend(sorted(p.rglob("*.json")))
        elif p.exists():
            files.append(p)
        else:
            print(f"skip (not found): {t}", file=sys.stderr)
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("targets", nargs="*", help="graph JSON files or directories")
    ap.add_argument("--all", action="store_true", help="validate every debug/*/graphs directory")
    ap.add_argument("--strict", action="store_true",
                    help="promote recommended-field warnings to errors")
    ap.add_argument("--quiet", "-q", action="store_true", help="only print failures")
    ap.add_argument("--limit", type=int, default=0, help="max files per directory (0 = all)")
    ap.add_argument("--json-out", help="write a machine-readable report here")
    args = ap.parse_args()

    files = iter_files(args.targets, args.all)
    if args.limit:
        by_dir: dict[Path, list[Path]] = {}
        for f in files:
            by_dir.setdefault(f.parent, []).append(f)
        files = [f for group in by_dir.values() for f in group[: args.limit]]
    if not files:
        print("no graph files found", file=sys.stderr)
        return 1

    failures = 0
    codes: Counter[str] = Counter()
    report: list[dict] = []
    for f in files:
        try:
            doc = json.loads(f.read_text())
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {f.relative_to(REPO)}: unreadable ({exc})")
            failures += 1
            continue
        rep = validate_document(doc, strict=args.strict)
        for i in rep.issues:
            codes[f"{i.severity}:{i.code}"] += 1
        report.append({
            "file": str(f.relative_to(REPO)),
            "ok": rep.ok,
            "errors": [i.code for i in rep.errors],
            "warnings": sorted({i.code for i in rep.warnings}),
        })
        if not rep.ok:
            failures += 1
            print(f"FAIL {f.relative_to(REPO)}  {rep.summary()}")
            for i in rep.errors[:8]:
                print(f"      {i}")
        elif not args.quiet:
            warn = f"  ({len(rep.warnings)} warn)" if rep.warnings else ""
            print(f"ok   {f.relative_to(REPO)}{warn}")

    print(f"\n{len(files) - failures}/{len(files)} files conform to schema v1")
    if codes:
        print("issue codes:")
        for code, n in codes.most_common(20):
            print(f"  {n:5d}  {code}")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
