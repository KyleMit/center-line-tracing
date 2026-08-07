// voronoi_medial — Boost.Polygon segment-site Voronoi front-end for centerline
// recovery (Track 7 / slug `native-geometry`, report §6.10).
//
// Reads flattened polygon edges as integer segment sites on stdin, builds the
// Voronoi diagram of those SEGMENTS (not sampled points), and emits every
// finite primary Voronoi edge as a polyline with a clearance radius at each
// vertex. Interior filtering, pruning and curve fitting are done by the Python
// front-end, which owns the polygon topology.
//
// Input (text, stdin):
//   line 1:  <n_segments>
//   next n:  <x1> <y1> <x2> <y2>      integers, already scaled by the caller
//
// Output (JSON, stdout):
//   { "vertices": [{"x":,"y":,"r":}], "edges": [{"a":,"b":,"curved":,"pts":[[x,y],...]}] }
//   Coordinates are in the caller's scaled integer space (doubles after
//   discretization of parabolic arcs).
//
// Build: g++ -O2 -std=c++17 voronoi_medial.cpp -o voronoi_medial
// Boost 1.83 (header-only boost/polygon/voronoi.hpp).

#include <boost/polygon/voronoi.hpp>

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <map>
#include <stack>
#include <string>
#include <vector>

using boost::polygon::voronoi_builder;
using boost::polygon::voronoi_diagram;

struct Pt {
  int x, y;
  Pt(int x_ = 0, int y_ = 0) : x(x_), y(y_) {}
};

struct Seg {
  Pt p0, p1;
  Seg(Pt a, Pt b) : p0(a), p1(b) {}
};

namespace boost {
namespace polygon {
template <>
struct geometry_concept<Pt> {
  typedef point_concept type;
};
template <>
struct point_traits<Pt> {
  typedef int coordinate_type;
  static inline coordinate_type get(const Pt& p, orientation_2d orient) {
    return (orient == HORIZONTAL) ? p.x : p.y;
  }
};

template <>
struct geometry_concept<Seg> {
  typedef segment_concept type;
};
template <>
struct segment_traits<Seg> {
  typedef int coordinate_type;
  typedef Pt point_type;
  static inline point_type get(const Seg& s, direction_1d dir) {
    return dir.to_int() ? s.p1 : s.p0;
  }
};
}  // namespace polygon
}  // namespace boost

struct DPt {
  double x, y;
  DPt(double x_ = 0, double y_ = 0) : x(x_), y(y_) {}
};

// Squared distance from a point to a segment.
static double point_seg_dist(double px, double py, const Seg& s) {
  const double ax = s.p0.x, ay = s.p0.y, bx = s.p1.x, by = s.p1.y;
  const double dx = bx - ax, dy = by - ay;
  const double len2 = dx * dx + dy * dy;
  double t = 0.0;
  if (len2 > 0.0) {
    t = ((px - ax) * dx + (py - ay) * dy) / len2;
    if (t < 0.0) t = 0.0;
    if (t > 1.0) t = 1.0;
  }
  const double qx = ax + t * dx, qy = ay + t * dy;
  return std::sqrt((px - qx) * (px - qx) + (py - qy) * (py - qy));
}

// --- parabolic-arc discretization -------------------------------------------
// A Voronoi edge between a point site and a segment site is a parabolic arc.
// This is the algorithm from Boost.Polygon's voronoi_visual_utils example
// header (not shipped in the Ubuntu libboost-dev package), reimplemented here:
// transform so the segment lies on the positive x-axis, walk the parabola
// y = ((x - rot_x)^2 + rot_y^2) / (2 * rot_y), and subdivide until the chord
// error drops below max_dist.

static double parabola_y(double x, double a, double b) {
  return ((x - a) * (x - a) + b * b) / (2.0 * b);
}

// Projection of `p` onto the segment, as a fraction of the segment length.
static double point_projection(const DPt& p, const Seg& s) {
  const double sx = double(s.p1.x) - double(s.p0.x);
  const double sy = double(s.p1.y) - double(s.p0.y);
  const double len2 = sx * sx + sy * sy;
  const double vx = p.x - double(s.p0.x);
  const double vy = p.y - double(s.p0.y);
  return (vx * sx + vy * sy) / len2;
}

static void discretize(const Pt& point, const Seg& segment, double max_dist,
                       std::vector<DPt>* out) {
  const double sx = double(segment.p1.x) - double(segment.p0.x);
  const double sy = double(segment.p1.y) - double(segment.p0.y);
  const double sqr_len = sx * sx + sy * sy;

  const double proj_start = sqr_len * point_projection((*out)[0], segment);
  const double proj_end = sqr_len * point_projection((*out)[1], segment);

  const double pvx = double(point.x) - double(segment.p0.x);
  const double pvy = double(point.y) - double(segment.p0.y);
  const double rot_x = sx * pvx + sy * pvy;
  const double rot_y = sx * pvy - sy * pvx;

  // Degenerate configurations (focus on the directrix, or a zero-extent
  // projection) have no well-defined parabola — keep the chord instead of
  // emitting NaNs.
  if (!std::isfinite(rot_y) || std::fabs(rot_y) < 1e-9 ||
      std::fabs(proj_end - proj_start) < 1e-12) {
    return;
  }

  const DPt last_point = (*out)[1];
  out->pop_back();

  std::stack<double> stack;
  stack.push(proj_end);
  double cur_x = proj_start;
  double cur_y = parabola_y(cur_x, rot_x, rot_y);

  const double max_dist_t = max_dist * max_dist * sqr_len;
  int guard = 0;
  while (!stack.empty() && guard++ < 100000) {
    const double new_x = stack.top();
    const double new_y = parabola_y(new_x, rot_x, rot_y);

    // Point of the parabola furthest from the chord.
    const double mid_x = (new_y - cur_y) / (new_x - cur_x) * rot_y + rot_x;
    const double mid_y = parabola_y(mid_x, rot_x, rot_y);

    double dist = (new_y - cur_y) * (mid_x - cur_x) - (new_x - cur_x) * (mid_y - cur_y);
    dist = dist * dist /
           ((new_y - cur_y) * (new_y - cur_y) + (new_x - cur_x) * (new_x - cur_x));
    if (!std::isfinite(dist) || dist <= max_dist_t) {
      stack.pop();
      const double ix = (sx * new_x - sy * new_y) / sqr_len + double(segment.p0.x);
      const double iy = (sx * new_y + sy * new_x) / sqr_len + double(segment.p0.y);
      if (!std::isfinite(ix) || !std::isfinite(iy)) {
        cur_x = new_x;
        cur_y = new_y;
        continue;
      }
      out->push_back(DPt(ix, iy));
      cur_x = new_x;
      cur_y = new_y;
    } else {
      stack.push(mid_x);
    }
  }
  out->back() = last_point;
}

int main(int argc, char** argv) {
  double max_dist = 10.0;  // scaled units; chord tolerance for parabolic arcs
  if (argc > 1) max_dist = atof(argv[1]);

  long n = 0;
  if (scanf("%ld", &n) != 1) {
    fprintf(stderr, "voronoi_medial: bad input header\n");
    return 2;
  }
  std::vector<Seg> segments;
  segments.reserve(n);
  for (long i = 0; i < n; ++i) {
    long x1, y1, x2, y2;
    if (scanf("%ld %ld %ld %ld", &x1, &y1, &x2, &y2) != 4) {
      fprintf(stderr, "voronoi_medial: bad segment on line %ld\n", i + 2);
      return 2;
    }
    if (x1 == x2 && y1 == y2) continue;  // degenerate; boost rejects these
    segments.push_back(Seg(Pt(int(x1), int(y1)), Pt(int(x2), int(y2))));
  }

  voronoi_diagram<double> vd;
  construct_voronoi(segments.begin(), segments.end(), &vd);

  typedef voronoi_diagram<double>::vertex_type VT;
  typedef voronoi_diagram<double>::edge_type ET;
  typedef voronoi_diagram<double>::cell_type CT;

  // Index vertices, and compute the clearance radius at each one as the
  // distance to the site of any incident cell (all incident sites are
  // equidistant by definition of a Voronoi vertex).
  std::map<const VT*, int> vidx;
  std::vector<DPt> vpos;
  std::vector<double> vrad;
  for (auto it = vd.vertices().begin(); it != vd.vertices().end(); ++it) {
    const VT* v = &(*it);
    vidx[v] = int(vpos.size());
    vpos.push_back(DPt(v->x(), v->y()));
    const CT* c = v->incident_edge()->cell();
    vrad.push_back(point_seg_dist(v->x(), v->y(), segments[c->source_index()]));
  }

  std::string out;
  out.reserve(1 << 20);
  char buf[512];

  out += "{\"segments\":";
  snprintf(buf, sizeof(buf), "%zu", segments.size());
  out += buf;
  out += ",\"max_dist\":";
  snprintf(buf, sizeof(buf), "%.6f", max_dist);
  out += buf;
  out += ",\"vertices\":[";
  for (size_t i = 0; i < vpos.size(); ++i) {
    const double vx = std::isfinite(vpos[i].x) ? vpos[i].x : 0.0;
    const double vy = std::isfinite(vpos[i].y) ? vpos[i].y : 0.0;
    const double vr = std::isfinite(vrad[i]) ? vrad[i] : 0.0;
    snprintf(buf, sizeof(buf), "%s{\"x\":%.6f,\"y\":%.6f,\"r\":%.6f}", i ? "," : "", vx, vy,
             vr);
    out += buf;
  }
  out += "],\"edges\":[";

  bool first_edge = true;
  for (auto it = vd.edges().begin(); it != vd.edges().end(); ++it) {
    const ET* e = &(*it);
    if (!e->is_primary()) continue;   // secondary edges join a segment to its own endpoint
    if (!e->is_finite()) continue;    // infinite edges leave the polygon
    // Emit each edge once (skip the twin).
    if (e > e->twin()) continue;

    const int ia = vidx[e->vertex0()], ib = vidx[e->vertex1()];
    std::vector<DPt> pts;
    pts.push_back(vpos[ia]);  // sanitized copies
    pts.push_back(vpos[ib]);

    bool curved = e->is_curved();
    if (curved) {
      // One cell is a point site (a segment endpoint), the other a segment.
      const CT* cell1 = e->cell();
      const CT* cell2 = e->twin()->cell();
      const CT* point_cell = cell1->contains_point() ? cell1 : cell2;
      const CT* seg_cell = cell1->contains_point() ? cell2 : cell1;
      const Seg& s_pt = segments[point_cell->source_index()];
      const Seg& s_seg = segments[seg_cell->source_index()];
      Pt p = (point_cell->source_category() ==
              boost::polygon::SOURCE_CATEGORY_SEGMENT_START_POINT)
                 ? s_pt.p0
                 : s_pt.p1;
      discretize(p, s_seg, max_dist, &pts);
    }

    snprintf(buf, sizeof(buf), "%s{\"a\":%d,\"b\":%d,\"curved\":%s,\"pts\":[",
             first_edge ? "" : ",", ia, ib, curved ? "true" : "false");
    out += buf;
    bool first_pt = true;
    for (size_t i = 0; i < pts.size(); ++i) {
      if (!std::isfinite(pts[i].x) || !std::isfinite(pts[i].y)) continue;
      snprintf(buf, sizeof(buf), "%s[%.6f,%.6f]", first_pt ? "" : ",", pts[i].x, pts[i].y);
      out += buf;
      first_pt = false;
    }
    out += "]}";
    first_edge = false;
  }
  out += "]}\n";

  fwrite(out.data(), 1, out.size(), stdout);
  return 0;
}
