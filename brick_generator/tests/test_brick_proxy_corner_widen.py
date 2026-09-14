"""
Integration tests for BrickProxy's Part 8 corner-seam-gap fix
(_widen_face_boundary + its wiring into execute()), against REAL FreeCAD
Part.Face geometry and real BrickProxy FeaturePython objects.

Requires a real FreeCAD -- skipped (not failed) under a plain
`python3 -m pytest` run with no FreeCAD on sys.path. Run for real via
FreeCAD's own headless console binary:

    /path/to/FreeCADCmd shared/tests/run_freecad_tests.py brick_generator/tests

(shared/tests/run_freecad_tests.py's pytest.main() call accepts extra path
args appended after its own default target -- see its own docstring --
so passing this directory alongside it picks up this file too, without
needing a second copy of the runner.)
"""

import pytest

App = pytest.importorskip("FreeCAD")
import Part  # noqa: E402

import brick_proxy  # noqa: E402


def _face(points):
    """Build a single planar Part.Face from an ordered list of (x,y,z)
    corner tuples -- same helper as shared/tests/test_corner_detection.py,
    duplicated here rather than imported since it's a 5-line test fixture,
    not shared production logic."""
    vecs = [App.Vector(*p) for p in points]
    wire = Part.makePolygon(vecs + [vecs[0]])
    return Part.Face(wire)


@pytest.fixture
def corner_doc():
    """
    A synthetic 90-degree corner: wall A along X at y=0 (normal -Y,
    spanning x in [0, WIDTH_A]), wall B along Y at x=0 (normal -X,
    spanning y in [0, WIDTH_B]), sharing the vertical edge at x=0,y=0.
    Both faces' bbox-minimum corner is at that shared edge, so per
    compute_face_axes' documented convention (see
    shared/corner_detection.py's own worked example) BOTH walls see this
    corner as their LEFT edge (u=0) -- not one left/one right.

    Small, hand-picked, exactly-representable numbers -- not a real
    building's mm dimensions -- verified by this fixture's own assertions
    before any BrickProxy-level assertion relies on them.
    """
    WIDTH_A = 10.0
    WIDTH_B = 8.0
    HEIGHT = 6.0

    wall_a = _face([(0, 0, 0), (WIDTH_A, 0, 0), (WIDTH_A, 0, HEIGHT), (0, 0, HEIGHT)])
    wall_b = _face([(0, 0, 0), (0, 0, HEIGHT), (0, WIDTH_B, HEIGHT), (0, WIDTH_B, 0)])

    def normal_of(face):
        uv = face.ParameterRange
        n = face.normalAt((uv[0] + uv[1]) / 2, (uv[2] + uv[3]) / 2)
        return (round(n.x, 6), round(n.y, 6), round(n.z, 6))

    assert normal_of(wall_a) == (0.0, -1.0, 0.0)
    assert normal_of(wall_b) == (-1.0, 0.0, 0.0)

    compound = Part.Compound([wall_a, wall_b])

    doc = App.newDocument("CornerWidenTest")
    base = doc.addObject("Part::Feature", "Base")
    base.Shape = compound

    def index_of(face):
        target = (round(face.BoundBox.XMin, 6), round(face.BoundBox.YMin, 6),
                  round(face.BoundBox.ZMin, 6), round(face.BoundBox.XMax, 6),
                  round(face.BoundBox.YMax, 6), round(face.BoundBox.ZMax, 6))
        for i, f in enumerate(compound.Faces):
            key = (round(f.BoundBox.XMin, 6), round(f.BoundBox.YMin, 6),
                   round(f.BoundBox.ZMin, 6), round(f.BoundBox.XMax, 6),
                   round(f.BoundBox.YMax, 6), round(f.BoundBox.ZMax, 6))
            if key == target:
                return i
        raise AssertionError("face not found in compound by bounding box")

    yield {
        'doc': doc, 'base': base,
        'wall_a_idx': index_of(wall_a), 'wall_b_idx': index_of(wall_b),
        'WIDTH_A': WIDTH_A, 'WIDTH_B': WIDTH_B, 'HEIGHT': HEIGHT,
    }
    App.closeDocument(doc.Name)


def _make_brick_wall(doc, base, face_idx, name, *, left_quoin=False,
                      left_quoin_primary=True, right_quoin=False,
                      right_quoin_primary=True, skin_depth=0.3,
                      reverse_quoin_sides=False):
    obj = doc.addObject("Part::FeaturePython", name)
    brick_proxy.BrickProxy(obj)
    obj.Sources = [(base, (f"Face{face_idx + 1}",))]
    obj.BondPattern = "stretcher"
    obj.BrickWidth = 2.32
    obj.BrickHeight = 0.65
    obj.BrickDepth = 1.09
    obj.Mortar = 0.11
    obj.MortarDepth = 0.06
    obj.CommonBondCount = 5
    obj.SkinDepth = skin_depth
    obj.LeftQuoin = left_quoin
    obj.LeftQuoinPrimary = left_quoin_primary
    obj.RightQuoin = right_quoin
    obj.RightQuoinPrimary = right_quoin_primary
    obj.ReverseQuoinSides = reverse_quoin_sides
    return obj


class TestCornerSeamGapClosed:
    """The actual bug this Part exists to fix: two independently-built
    BrickProxy skins at a real corner must now meet with no gap, when one
    side is the quoin Primary."""

    def test_primary_skin_widens_to_close_the_wedge(self, corner_doc):
        skin_depth = 0.3
        wall_a = _make_brick_wall(
            corner_doc['doc'], corner_doc['base'], corner_doc['wall_a_idx'], "WallA",
            left_quoin=True, left_quoin_primary=True, skin_depth=skin_depth,
        )
        wall_b = _make_brick_wall(
            corner_doc['doc'], corner_doc['base'], corner_doc['wall_b_idx'], "WallB",
            left_quoin=True, left_quoin_primary=False, skin_depth=skin_depth,
        )
        corner_doc['doc'].recompute()

        assert not wall_a.Shape.isNull()
        assert not wall_b.Shape.isNull()

        bbox_a = wall_a.Shape.BoundBox
        bbox_b = wall_b.Shape.BoundBox
        tol = 1e-6

        # Wall A (Primary) widened its left (x=0) boundary outward by
        # skin_depth: its footprint now reaches x <= -skin_depth ...
        assert bbox_a.XMin <= -skin_depth + tol, (
            f"Primary wall A did not widen: XMin={bbox_a.XMin}, "
            f"expected <= {-skin_depth}")
        # ... AND its own proud-skin thickness already spans the Y depth
        # of the corner wedge, so wall A alone now fully covers the wedge
        # x in [-skin_depth, 0], y in [-skin_depth, 0] that was previously
        # an uncovered gap.
        assert bbox_a.YMin <= -skin_depth + tol, (
            f"Primary wall A's own skin depth doesn't reach the wedge: "
            f"YMin={bbox_a.YMin}, expected <= {-skin_depth}")

        # Wall B (Secondary) must NOT widen -- stays at its own real edge,
        # avoiding double-coverage/self-intersection with wall A's volume.
        assert bbox_b.YMin >= 0.0 - tol, (
            f"Secondary wall B widened when it shouldn't have: "
            f"YMin={bbox_b.YMin}, expected >= 0.0")

    def test_neither_side_widens_when_no_quoin_set(self, corner_doc):
        """Regression guard: plain (no-quoin) walls must be completely
        unaffected by this Part -- same behavior as before it existed."""
        wall_a = _make_brick_wall(
            corner_doc['doc'], corner_doc['base'], corner_doc['wall_a_idx'], "WallA",
        )
        corner_doc['doc'].recompute()
        assert not wall_a.Shape.isNull()
        assert wall_a.Shape.BoundBox.XMin >= 0.0 - 1e-6


class TestReverseQuoinSides:
    """ReverseQuoinSides (v7.4.0): swaps LeftQuoin<->RightQuoin and their
    Primary flags for one face, applied after every other property is
    resolved -- added because LeftQuoin/RightQuoin are u-axis labels
    (independent of which way the face's normal points), not "your
    left/right hand standing outside the building facing this wall," and
    confirmed live to flip unpredictably per-face on a real 2-wall corner."""

    def test_reversed_object_matches_swapped_plain_object(self, corner_doc):
        """The core parity invariant: an object with ReverseQuoinSides=True
        and (LeftQuoin, LeftQuoinPrimary, RightQuoin, RightQuoinPrimary) =
        (False, False, True, True) must produce EXACTLY the shape a plain
        (non-reversed) object with the swapped tuple (True, True, False,
        False) produces -- proving the swap is complete (both quoin flags
        AND both primary flags), not just one half of it."""
        skin_depth = 0.3
        plain = _make_brick_wall(
            corner_doc['doc'], corner_doc['base'], corner_doc['wall_a_idx'], "Plain",
            left_quoin=True, left_quoin_primary=True,
            right_quoin=False, right_quoin_primary=False,
            skin_depth=skin_depth,
        )
        reversed_obj = _make_brick_wall(
            corner_doc['doc'], corner_doc['base'], corner_doc['wall_a_idx'], "Reversed",
            left_quoin=False, left_quoin_primary=False,
            right_quoin=True, right_quoin_primary=True,
            skin_depth=skin_depth, reverse_quoin_sides=True,
        )
        corner_doc['doc'].recompute()

        assert not plain.Shape.isNull()
        assert not reversed_obj.Shape.isNull()
        assert plain.Shape.Volume == pytest.approx(reversed_obj.Shape.Volume, rel=1e-9)
        b1, b2 = plain.Shape.BoundBox, reversed_obj.Shape.BoundBox
        for attr in ('XMin', 'XMax', 'YMin', 'YMax', 'ZMin', 'ZMax'):
            assert getattr(b1, attr) == pytest.approx(getattr(b2, attr), abs=1e-9), (
                f"{attr}: plain={getattr(b1, attr)} reversed={getattr(b2, attr)}")

    def test_reverse_false_is_a_no_op(self, corner_doc):
        """ReverseQuoinSides defaults to False -- existing documents (with
        this property absent or unset) must be completely unaffected."""
        obj = _make_brick_wall(
            corner_doc['doc'], corner_doc['base'], corner_doc['wall_a_idx'], "NoReverse",
            left_quoin=True, left_quoin_primary=True,
        )
        assert obj.ReverseQuoinSides is False
        corner_doc['doc'].recompute()
        assert not obj.Shape.isNull()
        # Unreversed LeftQuoin=True/Primary=True still widens on the left,
        # exactly as before this property existed.
        assert obj.Shape.BoundBox.XMin <= -0.3 + 1e-6

    def test_reverse_true_with_no_quoin_set_is_still_a_no_op(self, corner_doc):
        """Reversing False<->False and True<->True (both quoin flags off)
        changes nothing -- must not raise or otherwise misbehave."""
        obj = _make_brick_wall(
            corner_doc['doc'], corner_doc['base'], corner_doc['wall_a_idx'], "ReverseNoQuoin",
            reverse_quoin_sides=True,
        )
        corner_doc['doc'].recompute()
        assert not obj.Shape.isNull()
        assert obj.Shape.BoundBox.XMin >= 0.0 - 1e-6


class TestWidenFaceBoundaryDirect:
    """Direct tests of _widen_face_boundary against a single face, for
    cases too fiddly to set up via a full two-object corner scenario."""

    def test_both_sides_widened_on_one_face(self, corner_doc):
        """Dual-quoin: a single face Primary on BOTH its left and right
        edges. Verified live: extending both ends outward (away from each
        other) cannot self-intersect regardless of the original span, but
        checked here empirically rather than only trusted algebraically."""
        skin_depth = 0.3
        face = corner_doc['base'].Shape.Faces[corner_doc['wall_a_idx']]
        _, u_vec, v_vec, _, u_length, _, _ = brick_proxy._get_face_coordinate_system(face)

        widened = brick_proxy._widen_face_boundary(face, u_vec, v_vec, 'left', skin_depth)
        widened = brick_proxy._widen_face_boundary(widened, u_vec, v_vec, 'right', skin_depth)

        assert widened.isValid()
        new_bbox = widened.BoundBox
        # u_axis is 'x' for this face (verified by the fixture's own
        # normal check + WIDTH_A > HEIGHT), so the widened extent shows up
        # on X: original [0, WIDTH_A] should now span
        # [-skin_depth, WIDTH_A+skin_depth].
        assert new_bbox.XMin == pytest.approx(-skin_depth, abs=1e-9)
        assert new_bbox.XMax == pytest.approx(corner_doc['WIDTH_A'] + skin_depth, abs=1e-9)

    def test_short_span_both_sides_widened_stays_valid(self, corner_doc):
        """The reviewed concern: a short wall (small u_length) with both
        ends Primary. Re-derivation showed this can't self-intersect
        (both extensions move AWAY from each other, not toward), but this
        pins that empirically rather than resting on the derivation alone
        -- a short pier is exactly the real-world shape (door piers in the
        actual demo model) this needs to keep working for."""
        short = _face([(0, 0, 0), (0.5, 0, 0), (0.5, 0, 6.0), (0, 0, 6.0)])
        u_vec, v_vec = App.Vector(1, 0, 0), App.Vector(0, 0, 1)
        skin_depth = 0.3  # > half of the 0.5 span -- deliberately tight

        widened = brick_proxy._widen_face_boundary(short, u_vec, v_vec, 'left', skin_depth)
        widened = brick_proxy._widen_face_boundary(widened, u_vec, v_vec, 'right', skin_depth)

        assert widened.isValid()
        assert widened.BoundBox.XMin == pytest.approx(-skin_depth, abs=1e-9)
        assert widened.BoundBox.XMax == pytest.approx(0.5 + skin_depth, abs=1e-9)

    def test_ambiguous_bay_at_real_corner_raises(self):
        """The exact case the edge-identity-selection design exists to
        catch: a wall with a rectangular notch cut into its own left
        (u=0) edge (partway up, not touching top or bottom) leaves TWO
        separate wire edges both sitting at x=0 -- the true boundary edge
        below the notch, and another above it. Must raise, not silently
        widen the wrong one (which could distort or ignore the notch)."""
        notchy = _face([
            (0, 0, 0), (10, 0, 0), (10, 0, 6), (0, 0, 6),
            (0, 0, 4), (3, 0, 4), (3, 0, 2), (0, 0, 2),
        ])
        assert notchy.isValid()
        u_vec, v_vec = App.Vector(1, 0, 0), App.Vector(0, 0, 1)

        with pytest.raises(ValueError, match="Ambiguous"):
            brick_proxy._widen_face_boundary(notchy, u_vec, v_vec, 'left', 0.3)
