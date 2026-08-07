// Ported from Tegaki packages/generator/src/constants.ts (MIT, see VENDOR.md).
// Values kept at Tegaki's defaults unless marked ADAPTED.

export const BEZIER_TOLERANCE = 0.25; // ADAPTED: user units, not font units (Tegaki 0.5 @ 1000upm)
export const RDP_TOLERANCE = 1.5; // bitmap px
export const BITMAP_PADDING = 0.05;

/** Minimum spur length as a fraction of the bitmap resolution (naive pruner). */
export const SPUR_LENGTH_RATIO = 0.08;
/** Tegaki caps the naive spur threshold at 10 px so small glyphs are not erased. */
export const SPUR_LENGTH_CAP = 10;

/** Width-aware spur threshold, from Tegaki's voronoi pruner: L < 1.5 * (2R_parent). */
export const SPUR_WIDTH_RATIO = 1.5;

export const SMOOTH_KINK_MIN_ANGLE = 155; // degrees
export const TRACE_LOOKBACK = 12; // px
export const TRACE_CURVATURE_BIAS = 0.5;
export const SMOOTH_KINK_THRESHOLD = 0.15;

/**
 * ADAPTED: Tegaki merges polyline endpoints within max(w,h) * 0.08 — 8% of the
 * whole bitmap. That is sane for one glyph and catastrophic for a drawing, where
 * unrelated strokes sit far closer than 8% of the page apart. We express the
 * merge threshold in units of the global stroke radius instead.
 */
export const MERGE_THRESHOLD_RATIO = 0.08; // used only in --merge-mode tegaki
export const MERGE_RADIUS_FACTOR = 1.5; // default: k * R_global

export const JUNCTION_CROSSING_COS = -0.7;
export const JUNCTION_ALIGNMENT_COS = 0.5;

export const ORIENT_X_WEIGHT = 2;
export const JUNCTION_CLEANUP_MAX_ITERATIONS = 5;
export const THIN_MAX_ITERATIONS = 25;
export const VORONOI_SAMPLING_INTERVAL = 2;

export const DOT_DIAG_RATIO = 0.15;
export const DOT_ISOLATION_RATIO = 0.04;

export const DEFAULT_RESOLUTION = 400;

/** ADAPTED: our default is px-per-user-unit, not a fixed glyph-wide budget. */
export const DEFAULT_SCALE = 2;

export const SKELETON_METHODS = ['zhang-suen', 'guo-hall', 'medial-axis', 'lee', 'thin', 'voronoi'];
export const DT_METHODS = ['chamfer', 'euclidean'];
export const PRUNE_METHODS = ['tegaki-length', 'tegaki-width', 'none'];
