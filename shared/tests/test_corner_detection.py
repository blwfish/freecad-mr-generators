"""
Integration tests for corner_detection.find_corners()/assign_primary(),
against REAL FreeCAD Part.Face geometry.

Requires a real FreeCAD -- skipped (not failed) under a plain
`python3 -m pytest` run with no FreeCAD on sys.path. Run for real via
FreeCAD's own headless console binary:

    /path/to/FreeCADCmd shared/tests/run_freecad_tests.py quoin_generator/tests/test_corner_detection.py

(shared/tests/run_freecad_tests.py is the generic runner used across this
repo's FreeCAD-dependent test files -- see its own docstring.)

The test building is a SYNTHETIC solid, not a load of the real
equipment-hut-demo.FCStd (which lives outside this repo, at a path only
this developer's machine has, and keeps changing as that model is
worked on). It reproduces the exact corner topology that surfaced the
right-quoin-only bug this module exists to detect: a rectangular
building (south/west/north walls) with a door opening on the missing
east side, flanked by two piers -- one of which has its one real corner
on its *right* edge only. All coordinates are clean, hand-picked numbers
(not the real building's mm dimensions), independently verified against
brick_geometry.compute_face_axes' documented behavior in this file's own
setup assertions before the real find_corners() assertions run.
"""

import pytest

App = pytest.importorskip("FreeCAD")
import Part  # noqa: E402

from corner_detection import find_corners, assign_primary  # noqa: E402


def _face(points):
    """Build a single planar Part.Face from an ordered list of (x,y,z)
    corner tuples. Point order determines normal direction via the
    right-hand rule -- callers must pick winding that gives the intended
    outward normal (verified by this file's setup assertions, not assumed)."""
    vecs = [App.Vector(*p) for p in points]
    wire = Part.makePolygon(vecs + [vecs[0]])
    return Part.Face(wire)


@pytest.fixture
def building():
    """
    A synthetic rectangular building, W=20 x D=10 x H=15, footprint
    x in [0,20], y in [0,10], with a door opening on the east side
    (x=20) between y=[4,6] splitting that side into two piers.

    Real building corners (hand-derived from compute_face_axes' documented
    bbox-min-origin convention, verified by this fixture's own assertions
    below before any find_corners() test relies on them):
      south/west   -> both LEFT   (the SW corner)
      west/north   -> west RIGHT, north LEFT   (the NW corner)
      south/s_pier -> south RIGHT, s_pier LEFT (south wall meets its pier)
      north/n_pier -> north RIGHT, n_pier RIGHT (the right-only case that
                      motivated relaxing BrickGeometry's right_quoin
                      constraint -- brick_geometry.py's 5.2.0 changelog)
    south and north are parallel (no shared edge); neither pier touches
    west or the other pier (no shared edge) -- 6 of the 10 possible pairs
    among 5 faces are simply not adjacent, not "ambiguous".
    """
    south = _face([(0, 0, 0), (20, 0, 0), (20, 0, 15), (0, 0, 15)])
    west = _face([(0, 0, 0), (0, 0, 15), (0, 10, 15), (0, 10, 0)])
    north = _face([(0, 10, 0), (0, 10, 15), (20, 10, 15), (20, 10, 0)])
    s_pier = _face([(20, 0, 0), (20, 4, 0), (20, 4, 15), (20, 0, 15)])
    n_pier = _face([(20, 6, 0), (20, 10, 0), (20, 10, 15), (20, 6, 15)])

    # Verify winding actually produced the intended OUTWARD normals before
    # trusting any corner-detection result derived from them -- a sign
    # error here would silently flip every convexity determination.
    def normal_of(face):
        uv = face.ParameterRange
        n = face.normalAt((uv[0] + uv[1]) / 2, (uv[2] + uv[3]) / 2)
        return (round(n.x, 6), round(n.y, 6), round(n.z, 6))

    assert normal_of(south) == (0.0, -1.0, 0.0)
    assert normal_of(west) == (-1.0, 0.0, 0.0)
    assert normal_of(north) == (0.0, 1.0, 0.0)
    assert normal_of(s_pier) == (1.0, 0.0, 0.0)
    assert normal_of(n_pier) == (1.0, 0.0, 0.0)

    compound = Part.Compound([south, west, north, s_pier, n_pier])

    # Identify each face's actual index in the compound by its own
    # bounding box (matching this repo's established by-geometry
    # re-identification convention, e.g. brick_proxy.execute()'s
    # f.isSame(face) index lookup) rather than assuming Part.Compound
    # preserves constructor insertion order.
    def _bbox_key(bbox):
        return (round(bbox.XMin, 6), round(bbox.YMin, 6), round(bbox.ZMin, 6),
                round(bbox.XMax, 6), round(bbox.YMax, 6), round(bbox.ZMax, 6))

    def index_of(face):
        target = _bbox_key(face.BoundBox)
        for i, f in enumerate(compound.Faces):
            if _bbox_key(f.BoundBox) == target:
                return i
        raise AssertionError("face not found in compound by bounding box")

    return {
        'shape': compound,
        'south': index_of(south), 'west': index_of(west),
        'north': index_of(north), 's_pier': index_of(s_pier),
        'n_pier': index_of(n_pier),
    }


def _corner_between(corners, a, b):
    for c in corners:
        if {c['face_a'], c['face_b']} == {a, b}:
            return c
    return None


def _edge_for(corner, face_idx):
    """Return this face's Left/Right classification from a corner record,
    regardless of whether it landed in the 'face_a' or 'face_b' slot."""
    if corner['face_a'] == face_idx:
        return corner['face_a_edge']
    if corner['face_b'] == face_idx:
        return corner['face_b_edge']
    raise AssertionError(f"face {face_idx} not in corner {corner}")


class TestFindCornersRealBuilding:
    def test_exactly_four_corners_found(self, building):
        indices = [building[k] for k in ('south', 'west', 'north', 's_pier', 'n_pier')]
        result = find_corners(building['shape'], indices)
        assert len(result['corners']) == 4
        assert result['ambiguous'] == []

    def test_south_west_corner_is_left_left(self, building):
        indices = [building[k] for k in ('south', 'west', 'north', 's_pier', 'n_pier')]
        result = find_corners(building['shape'], indices)
        c = _corner_between(result['corners'], building['south'], building['west'])
        assert c is not None, "south/west corner not detected"
        assert _edge_for(c, building['south']) == 'left'
        assert _edge_for(c, building['west']) == 'left'

    def test_west_north_corner_is_right_left(self, building):
        indices = [building[k] for k in ('south', 'west', 'north', 's_pier', 'n_pier')]
        result = find_corners(building['shape'], indices)
        c = _corner_between(result['corners'], building['west'], building['north'])
        assert c is not None, "west/north corner not detected"
        assert _edge_for(c, building['west']) == 'right'
        assert _edge_for(c, building['north']) == 'left'

    def test_south_pier_corner_is_right_left(self, building):
        indices = [building[k] for k in ('south', 'west', 'north', 's_pier', 'n_pier')]
        result = find_corners(building['shape'], indices)
        c = _corner_between(result['corners'], building['south'], building['s_pier'])
        assert c is not None, "south/s_pier corner not detected"
        assert _edge_for(c, building['south']) == 'right'
        assert _edge_for(c, building['s_pier']) == 'left'

    def test_north_pier_corner_is_right_right(self, building):
        """The case that motivated relaxing BrickGeometry's right_quoin
        constraint: the north pier's one real corner lands on its RIGHT
        edge only, same as the north wall's."""
        indices = [building[k] for k in ('south', 'west', 'north', 's_pier', 'n_pier')]
        result = find_corners(building['shape'], indices)
        c = _corner_between(result['corners'], building['north'], building['n_pier'])
        assert c is not None, "north/n_pier corner not detected"
        assert _edge_for(c, building['north']) == 'right'
        assert _edge_for(c, building['n_pier']) == 'right'

    def test_non_adjacent_pairs_not_reported(self, building):
        """south/north (parallel, no shared edge) and both cross-pier/
        cross-west pairs must be simply absent, not flagged ambiguous."""
        indices = [building[k] for k in ('south', 'west', 'north', 's_pier', 'n_pier')]
        result = find_corners(building['shape'], indices)
        found_pairs = {frozenset((c['face_a'], c['face_b'])) for c in result['corners']}
        assert frozenset((building['south'], building['north'])) not in found_pairs
        assert frozenset((building['west'], building['s_pier'])) not in found_pairs
        assert frozenset((building['west'], building['n_pier'])) not in found_pairs
        assert frozenset((building['s_pier'], building['n_pier'])) not in found_pairs


class TestFindCornersDuplicateIndices:
    """Regression test for a code-review finding (2026-09-14): a literal
    duplicate index in face_indices used to compare a face to itself,
    silently classifying as 'coplanar' and dropping it rather than
    surfacing the malformed input. find_corners now dedupes instead."""

    def test_duplicate_index_does_not_change_result(self, building):
        # Compare on face_a/face_b/edge classification only -- each call
        # to find_corners constructs fresh Part.Edge wrapper objects, so
        # the 'edge' field is never == across two separate calls even for
        # identical geometry (Part.Edge has no value equality).
        def _key(result):
            return sorted(
                (c['face_a'], c['face_b'], c['face_a_edge'], c['face_b_edge'])
                for c in result['corners']
            )

        indices = [building[k] for k in ('south', 'west', 'north', 's_pier', 'n_pier')]
        clean = find_corners(building['shape'], indices)
        with_dupe = find_corners(building['shape'], indices + [building['south']])
        assert _key(with_dupe) == _key(clean)
        assert with_dupe['ambiguous'] == clean['ambiguous']

    def test_all_duplicates_of_one_face_finds_no_corners(self, building):
        south = building['south']
        result = find_corners(building['shape'], [south, south, south])
        assert result == {'corners': [], 'ambiguous': []}


class TestAssignPrimary:
    def test_lower_index_is_primary(self, building):
        indices = [building[k] for k in ('south', 'west', 'north', 's_pier', 'n_pier')]
        result = find_corners(building['shape'], indices)
        with_primary = assign_primary(result['corners'])
        for c in with_primary:
            expected = c['face_a'] < c['face_b']
            assert c['face_a_primary'] is expected

    def test_does_not_mutate_input_dicts(self, building):
        indices = [building[k] for k in ('south', 'west', 'north', 's_pier', 'n_pier')]
        result = find_corners(building['shape'], indices)
        original = [dict(c) for c in result['corners']]
        assign_primary(result['corners'])
        assert result['corners'] == original
