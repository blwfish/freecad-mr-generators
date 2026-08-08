"""
Integration tests for trim_geometry.apply_miter_cut_at_corner() and
create_internal_corner_fill() against REAL FreeCAD geometry.

Full-review finding #27 (2026-08-08): these two functions do nontrivial
custom OCCT corner-geometry construction (a Boolean half-space cut; a
triangular-prism fill wedge) with zero test coverage of any kind --
test_trim_geometry.py explicitly excludes FreeCAD-dependent functions by
its own stated scope.

Requires a real FreeCAD -- these tests are skipped (not failed) when
FreeCAD isn't importable, e.g. under a plain `python3 -m pytest` run with
no FreeCAD on sys.path. Run them for real with FreeCAD's own bundled
Python via its headless console binary, from the repo root:

    /path/to/FreeCADCmd smart_trim_generator/tests/run_freecad_tests.py

See shared/tests/run_freecad_tests.py for the runner pattern this mirrors.
"""

import dataclasses

import pytest

App = pytest.importorskip("FreeCAD")
import Part  # noqa: E402

from trim_geometry import (  # noqa: E402
    Corner,
    CornerType,
    detect_corners,
    apply_miter_cut_at_corner,
    create_internal_corner_fill,
)


@pytest.fixture
def top_face():
    """A simple 20x10mm rectangular face (the top of a box) -- gives 4
    real EXTERNAL corners with real Part.Edge boundary edges attached."""
    box = Part.makeBox(20.0, 10.0, 5.0)
    # Face6 of Part.makeBox's default box is the top (z=5) face.
    return box.Faces[5]


@pytest.fixture
def a_corner(top_face):
    corners = detect_corners(top_face)
    assert corners, "expected at least one corner on a rectangular face"
    return corners[0]


class TestApplyMiterCutAtCorner:

    def test_cuts_a_real_trim_solid(self, a_corner):
        # A trim solid straddling the corner in both directions along its
        # two boundary edges.
        solid = Part.makeBox(6.0, 0.5, 1.0, App.Vector(*a_corner.position))
        face_normal = App.Vector(0, 0, 1)
        # keep_direction: roughly "into" the solid from the corner.
        keep_direction = App.Vector(1, 1, 0)

        result = apply_miter_cut_at_corner(solid, a_corner, face_normal, keep_direction)

        assert result is not None
        assert not result.isNull()
        assert result.Volume > 0

    def test_degenerate_keep_direction_does_not_raise(self, a_corner):
        # keep_direction of zero length: normalize() on a zero vector is a
        # no-op in FreeCAD (leaves it (0,0,0)) rather than raising, so this
        # exercises the "cut everything away / degenerate result" path
        # through apply_miter_cut_at_corner's own try/except, not a crash.
        solid = Part.makeBox(6.0, 0.5, 1.0, App.Vector(*a_corner.position))
        face_normal = App.Vector(0, 0, 1)
        keep_direction = App.Vector(0, 0, 0)

        result = apply_miter_cut_at_corner(solid, a_corner, face_normal, keep_direction)

        # Contract: never raises, always returns *some* solid (the
        # original on failure/degenerate result -- see the function's own
        # "Guard against degenerate result" comment).
        assert result is not None
        assert not result.isNull()


class TestCreateInternalCornerFill:

    def test_non_internal_corner_returns_none(self, a_corner):
        # Force EXTERNAL explicitly rather than relying on the natural
        # classification of a_corner's source face (Part.makeBox face
        # winding order isn't guaranteed the same across FreeCAD/OCCT
        # versions, and this test only cares about the corner_type gate).
        external_corner = dataclasses.replace(a_corner, corner_type=CornerType.EXTERNAL)
        result = create_internal_corner_fill(external_corner, App.Vector(0, 0, 1), 0.5, 1.0)
        assert result is None

    def test_internal_corner_produces_a_real_prism(self, a_corner):
        # Reuse a real corner's genuine edges but force INTERNAL
        # classification -- this function only cares about corner_type to
        # gate whether to run, not about whether the corner is "really"
        # concave in the source face; the fill-triangle construction from
        # edge_before/edge_after is what's under test here.
        internal_corner = dataclasses.replace(a_corner, corner_type=CornerType.INTERNAL)

        result = create_internal_corner_fill(internal_corner, App.Vector(0, 0, 1), 0.5, 1.0)

        assert result is not None
        assert not result.isNull()
        assert result.Volume > 0

    def test_collinear_edges_return_none(self, a_corner):
        # Both binormals point the same direction when edge_before and
        # edge_after are set to the SAME edge -- the fill triangle
        # degenerates to a line (tri_cross.Length < 1e-6), which the
        # function's own comment says should return None rather than
        # attempt to build a zero-area face.
        degenerate = dataclasses.replace(
            a_corner, corner_type=CornerType.INTERNAL,
            edge_before=a_corner.edge_before, edge_after=a_corner.edge_before)

        result = create_internal_corner_fill(degenerate, App.Vector(0, 0, 1), 0.5, 1.0)

        assert result is None
