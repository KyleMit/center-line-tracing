// straight_skeleton — CGAL Straight_skeleton_2 front-end (report §6.12).
//
// Bounded experiment: the report (§3, §4.5) states that a straight skeleton is
// NOT the Euclidean medial axis — its bisectors are equidistant from the
// SUPPORTING LINES of the polygon edges, not from the edges themselves, so it
// is built from straight segments and cannot curve through a curved stroke.
// This tool exists to measure that difference on the same corpus rather than
// leave it as an open question.
//
// Input (text, stdin), user units as doubles:
//   line 1:  <n_rings>                   first ring is the outer boundary
//   per ring: <n_points> x1 y1 x2 y2 ...
//
// Output (JSON, stdout):
//   { "vertices": [{"x":,"y":,"r":}], "edges": [{"a":,"b":}] }
//   `r` is the skeleton vertex's offset time — the straight-skeleton analogue of
//   a clearance radius (distance to the supporting lines).
//
// Build: g++ -O2 -std=c++17 straight_skeleton.cpp -o straight_skeleton -lgmp -lmpfr
// CGAL 5.6.

#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Polygon_2.h>
#include <CGAL/Polygon_with_holes_2.h>
#include <CGAL/create_straight_skeleton_2.h>

#include <cmath>
#include <cstdio>
#include <iostream>
#include <map>
#include <string>
#include <vector>

typedef CGAL::Exact_predicates_inexact_constructions_kernel K;
typedef K::Point_2 Point;
typedef CGAL::Polygon_2<K> Polygon_2;
typedef CGAL::Polygon_with_holes_2<K> Polygon_with_holes;

int main() {
  int n_rings = 0;
  if (scanf("%d", &n_rings) != 1 || n_rings < 1) {
    fprintf(stderr, "straight_skeleton: bad input header\n");
    return 2;
  }
  std::vector<Polygon_2> rings;
  for (int r = 0; r < n_rings; ++r) {
    int n = 0;
    if (scanf("%d", &n) != 1) return 2;
    Polygon_2 p;
    for (int i = 0; i < n; ++i) {
      double x, y;
      if (scanf("%lf %lf", &x, &y) != 2) return 2;
      p.push_back(Point(x, y));
    }
    rings.push_back(p);
  }

  // CGAL wants the outer boundary counter-clockwise and holes clockwise.
  if (rings[0].is_clockwise_oriented()) rings[0].reverse_orientation();
  std::vector<Polygon_2> holes;
  for (size_t i = 1; i < rings.size(); ++i) {
    if (rings[i].is_counterclockwise_oriented()) rings[i].reverse_orientation();
    holes.push_back(rings[i]);
  }

  auto ss = CGAL::create_interior_straight_skeleton_2(
      rings[0].vertices_begin(), rings[0].vertices_end(), holes.begin(), holes.end(), K());
  if (!ss) {
    fprintf(stderr, "straight_skeleton: CGAL returned no skeleton\n");
    return 3;
  }

  std::map<int, int> idmap;
  std::string vout, eout;
  char buf[256];
  int next = 0;
  for (auto v = ss->vertices_begin(); v != ss->vertices_end(); ++v) {
    if (!v->is_skeleton()) continue;  // contour vertices are polygon corners
    idmap[v->id()] = next;
    snprintf(buf, sizeof(buf), "%s{\"x\":%.6f,\"y\":%.6f,\"r\":%.6f}", next ? "," : "",
             v->point().x(), v->point().y(), v->time());
    vout += buf;
    ++next;
  }

  bool first = true;
  for (auto h = ss->halfedges_begin(); h != ss->halfedges_end(); ++h) {
    if (!h->is_bisector()) continue;
    auto a = h->vertex(), b = h->opposite()->vertex();
    if (!a->is_skeleton() || !b->is_skeleton()) continue;  // inner skeleton only
    if (a->id() > b->id()) continue;                       // emit each edge once
    snprintf(buf, sizeof(buf), "%s{\"a\":%d,\"b\":%d}", first ? "" : ",", idmap[a->id()],
             idmap[b->id()]);
    eout += buf;
    first = false;
  }

  printf("{\"vertices\":[%s],\"edges\":[%s]}\n", vout.c_str(), eout.c_str());
  return 0;
}
