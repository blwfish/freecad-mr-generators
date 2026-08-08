"""
Integration tests for trim_geometry.apply_miter_cut_at_corner()/
create_internal_corner_fill() and smart_trim_proxy's inlined OCCT-touching
helpers (_resolve_outward_face, _get_document_centroid, _bbox_corners),
all against REAL FreeCAD geometry.

Full-review finding #27 (2026-08-08): apply_miter_cut_at_corner/
create_internal_corner_fill do nontrivial custom OCCT corner-geometry
construction (a Boolean half-space cut; a triangular-prism fill wedge)
with zero test coverage of any kind -- test_trim_geometry.py explicitly
excludes FreeCAD-dependent functions by its own stated scope.

Full-review finding #39 (2026-08-08): smart_trim_proxy.py's outward-face
resolution, wall-offset, and flip-distance math is inlined directly in
the proxy with no pure-Python extraction and no FreeCAD-integration test
of any kind for this proxy.

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
from smart_trim_proxy import (  # noqa: E402
    _resolve_outward_face,
    _get_document_centroid,
    _bbox_corners,
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
        # keep_direction of zero length: FreeCAD's Vector.normalize()
        # actually RAISES Base.FreeCADError on a zero vector (discovered
        # writing this test, 2026-08-08) rather than silently no-opping --
        # apply_miter_cut_at_corner's kd.normalize() call was outside its
        # own try/except until this test caught it. Now inside, so this
        # exercises that fallback-to-original-solid path.
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


class TestGetDocumentCentroid:

    @pytest.fixture
    def doc(self):
        d = App.newDocument("SmartTrimCentroidTest")
        yield d
        App.closeDocument(d.Name)

    def test_single_box_centroid_is_its_own_center(self, doc):
        box = doc.addObject("Part::Box", "Box")
        box.Length, box.Width, box.Height = 10.0, 10.0, 10.0
        doc.recompute()

        centroid = _get_document_centroid(doc)

        assert centroid == pytest.approx(App.Vector(5.0, 5.0, 5.0), abs=1e-6)

    def test_two_boxes_averages_their_centers(self, doc):
        b1 = doc.addObject("Part::Box", "Box1")
        b1.Length, b1.Width, b1.Height = 10.0, 10.0, 10.0
        b2 = doc.addObject("Part::Box", "Box2")
        b2.Length, b2.Width, b2.Height = 10.0, 10.0, 10.0
        b2.Placement = App.Placement(App.Vector(20.0, 0, 0), App.Rotation())
        doc.recompute()

        centroid = _get_document_centroid(doc)

        # Box1 center (5,5,5), Box2 center (25,5,5) -> average (15,5,5)
        assert centroid == pytest.approx(App.Vector(15.0, 5.0, 5.0), abs=1e-6)

    def test_excluded_object_is_not_counted(self, doc):
        b1 = doc.addObject("Part::Box", "Box1")
        b1.Length, b1.Width, b1.Height = 10.0, 10.0, 10.0
        b2 = doc.addObject("Part::Box", "Box2")
        b2.Length, b2.Width, b2.Height = 10.0, 10.0, 10.0
        b2.Placement = App.Placement(App.Vector(100.0, 0, 0), App.Rotation())
        doc.recompute()

        centroid = _get_document_centroid(doc, exclude_names={"Box2"})

        assert centroid == pytest.approx(App.Vector(5.0, 5.0, 5.0), abs=1e-6)

    def test_empty_document_returns_origin(self, doc):
        centroid = _get_document_centroid(doc)
        assert centroid == App.Vector(0, 0, 0)


class TestBboxCorners:

    def test_returns_all_eight_corners(self):
        box = Part.makeBox(10.0, 20.0, 30.0)
        corners = _bbox_corners(box.BoundBox)

        assert len(corners) == 8
        xs = {round(c.x, 6) for c in corners}
        ys = {round(c.y, 6) for c in corners}
        zs = {round(c.z, 6) for c in corners}
        assert xs == {0.0, 10.0}
        assert ys == {0.0, 20.0}
        assert zs == {0.0, 30.0}
        # All 8 combinations of (xmin/xmax, ymin/ymax, zmin/zmax) present.
        assert len({(round(c.x, 6), round(c.y, 6), round(c.z, 6)) for c in corners}) == 8


class TestResolveOutwardFace:

    @pytest.fixture
    def doc(self):
        d = App.newDocument("SmartTrimOutwardFaceTest")
        yield d
        App.closeDocument(d.Name)

    def test_selecting_the_far_face_returns_it_unchanged(self, doc):
        # A 10x10x10 box centered on the origin-ish document: the "outward"
        # face relative to the document centroid, when the box itself IS
        # the only object (so the document centroid == the box's own
        # center), is genuinely ambiguous for a symmetric box -- so this
        # test picks a box OFFSET from another reference object instead,
        # to give _resolve_outward_face a real "away from centroid" signal.
        box = doc.addObject("Part::Box", "Wall")
        box.Length, box.Width, box.Height = 10.0, 1.0, 10.0
        box.Placement = App.Placement(App.Vector(20.0, 0, 0), App.Rotation())
        ref = doc.addObject("Part::Box", "Reference")
        ref.Length, ref.Width, ref.Height = 1.0, 1.0, 1.0
        doc.recompute()

        # Face1 (x=20 plane, "inward"/near the reference) vs Face2 (x=30
        # plane, "outward"/far from the reference) -- Part.makeBox face
        # ordering: Face1=x-min, Face2=x-max.
        near_face = box.Shape.Faces[0]
        far_face = box.Shape.Faces[1]

        result = _resolve_outward_face(far_face, box.Shape, doc=doc)

        # The far face (already outward-facing away from the document
        # centroid, which sits near the small Reference box at the
        # origin) should be selected as-is or matched by an equivalent
        # face at the same location -- not the near face.
        assert result.CenterOfMass.distanceToPoint(far_face.CenterOfMass) < 0.01

    def test_selecting_the_near_face_resolves_to_the_far_face(self, doc):
        box = doc.addObject("Part::Box", "Wall")
        box.Length, box.Width, box.Height = 10.0, 1.0, 10.0
        box.Placement = App.Placement(App.Vector(20.0, 0, 0), App.Rotation())
        ref = doc.addObject("Part::Box", "Reference")
        ref.Length, ref.Width, ref.Height = 1.0, 1.0, 1.0
        doc.recompute()

        near_face = box.Shape.Faces[0]   # x=20, close to Reference at origin
        far_face = box.Shape.Faces[1]    # x=30, far from Reference

        result = _resolve_outward_face(near_face, box.Shape, doc=doc)

        assert result.CenterOfMass.distanceToPoint(far_face.CenterOfMass) < 0.01

    def test_no_opposite_face_found_falls_back_to_centroid_check(self, doc):
        # A single triangular (non-box) face has no "opposite" face at all
        # within the same shape -- exercises the `opposite is None` branch.
        p1, p2, p3 = App.Vector(0, 0, 0), App.Vector(10, 0, 0), App.Vector(0, 10, 0)
        wire = Part.makePolygon([p1, p2, p3, p1])
        face = Part.Face(wire)
        ref = doc.addObject("Part::Box", "Reference")
        ref.Length, ref.Width, ref.Height = 1.0, 1.0, 1.0
        ref.Placement = App.Placement(App.Vector(100.0, 100.0, 100.0), App.Rotation())
        doc.recompute()

        # face.Faces is just itself as a standalone Part.Face -- pass its
        # own .Shape-like self via face (has .Faces == [face] since a bare
        # Face IS a Shape with one Face).
        result = _resolve_outward_face(face, face, doc=doc)

        assert result is not None
        assert not result.isNull()
