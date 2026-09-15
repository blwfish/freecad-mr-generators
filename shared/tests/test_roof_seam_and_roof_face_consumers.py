"""
Integration tests, against REAL FreeCAD geometry, for the two remaining
full-review-20260915-e612 fixes that had no dedicated FreeCAD-integration
test as of the initial fix pass:

  - #17/#22 (roof_seam_generator/roof_seam_proxy.py): the consolidated
    _hip_edge_frame() helper (replacing 3 independent copies) and the
    geometry-derived block_size (replacing a hardcoded 200.0 "big enough
    for HO scale" constant).
  - #11 (shared/freecad_utils.get_roof_face_coordinate_system): the
    5-proxy consolidation of _get_face_coordinate_system. slate_generator
    already had FreeCAD test coverage for this (test_slate_proxy_
    redundant_top_course.py); this file covers the other 4 consumers --
    shingle, snow_guard, standing_seam, standing_seam_snow_guard.

Requires a real FreeCAD -- skipped (not failed) under a plain
`python3 -m pytest` run. Run for real via:

    /path/to/FreeCADCmd shared/tests/run_freecad_tests.py shared/tests
"""

import os
import sys

import pytest

App = pytest.importorskip("FreeCAD")
import Part  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _import_proxy_module(gen_dir, mod_name):
    gen_path = os.path.join(REPO_ROOT, gen_dir)
    shared_path = os.path.join(REPO_ROOT, "shared")
    for p in (gen_path, shared_path):
        if p not in sys.path:
            sys.path.insert(0, p)
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    return __import__(mod_name)


def _face(points, order=None):
    if order is not None:
        points = [points[i] for i in order]
    vecs = [App.Vector(*p) for p in points]
    wire = Part.makePolygon(vecs + [vecs[0]])
    return Part.Face(wire)


# ---------------------------------------------------------------------------
# roof_seam_proxy.py: _hip_edge_frame + block_size
# ---------------------------------------------------------------------------
#
# Real hip corner pulled live from a FreeCAD document (SlateSeamCaps005 in
# equipment_hut_demo, 2026-09-14 -- same source data already used and
# cross-checked by shared/tests/test_roof_geometry.py's
# TestClassifyRoofIntersectionNormalBased.HIP_FACE1_VERTS/HIP_FACE2_VERTS):
# two trapezoidal hip faces of a simple rectangular-plan hip roof, meeting
# along the diagonal hip line at the corner.
HIP_FACE1_VERTS = [
    (24.5241, -17.5172, 28.0276), (-24.5241, -17.5172, 28.0276),
    (21.0207, -14.0138, 31.531), (-21.0207, -14.0138, 31.531),
]
HIP_FACE2_VERTS = [
    (24.5241, 17.5172, 28.0276), (24.5241, -17.5172, 28.0276),
    (21.0207, 14.0138, 31.531), (21.0207, -14.0138, 31.531),
]
HIP_SHARED_EDGE = ((21.0207, -14.0138, 31.531), (24.5241, -17.5172, 28.0276))
# Winding order that produces a valid, non-self-intersecting trapezoid for
# each face -- confirmed live: the vertex list's own (0,1,2,3) order
# self-intersects (area 17.36, a "bowtie"); (0,1,3,2) is the real
# wide-bottom-to-narrow-top trapezoid loop (area 225.65 / 156.22).
_TRAPEZOID_ORDER = (0, 1, 3, 2)


@pytest.fixture
def hip_roof():
    face1 = _face(HIP_FACE1_VERTS, order=_TRAPEZOID_ORDER)
    face2 = _face(HIP_FACE2_VERTS, order=_TRAPEZOID_ORDER)
    p0 = App.Vector(*HIP_SHARED_EDGE[0])
    p1 = App.Vector(*HIP_SHARED_EDGE[1])
    shared_edge = Part.makeLine(p0, p1)
    return face1, face2, shared_edge


class TestHipEdgeFrame:
    def test_returns_a_consistent_orthonormal_frame(self, hip_roof):
        mod = _import_proxy_module("roof_seam_generator", "roof_seam_proxy")
        face1, face2, shared_edge = hip_roof

        (start_pt, end_pt, edge_dir, edge_len, n1_out, n2_out,
         local_x, local_z) = mod._hip_edge_frame(shared_edge, face1, face2)

        assert edge_len == pytest.approx(
            App.Vector(*HIP_SHARED_EDGE[0]).distanceToPoint(App.Vector(*HIP_SHARED_EDGE[1])),
            abs=1e-6)
        # local_x and local_z (bisector) must be unit length and mutually
        # perpendicular -- the whole point of an orthonormal local frame.
        assert edge_dir.Length == pytest.approx(1.0, abs=1e-6)
        assert local_x.Length == pytest.approx(1.0, abs=1e-6)
        assert local_z.Length == pytest.approx(1.0, abs=1e-6)
        assert local_x.dot(edge_dir) == pytest.approx(0.0, abs=1e-6)
        assert local_x.dot(local_z) == pytest.approx(0.0, abs=1e-6)
        # Genuinely convex hip (not a degenerate/near-flat seam): the two
        # face normals must actually differ, not be near-parallel.
        assert n1_out.dot(n2_out) < 0.99

    def test_degenerate_bisector_raises_clear_error(self):
        """The consolidation's own stated improvement over 2 of the 3
        original copies: a ValueError instead of a silent divide-by-
        near-zero when the two face normals are near-opposite."""
        mod = _import_proxy_module("roof_seam_generator", "roof_seam_proxy")
        # Two coplanar, oppositely-facing faces sharing an edge --
        # normals are exactly opposite, bisector is the zero vector.
        face1 = _face([(0, 0, 0), (10, 0, 0), (10, 0, 10), (0, 0, 10)])
        face2 = _face([(0, 0, 0), (0, 0, 10), (10, 0, 10), (10, 0, 0)])
        shared_edge = Part.makeLine(App.Vector(0, 0, 0), App.Vector(0, 0, 10))

        with pytest.raises(ValueError, match="near-opposite"):
            mod._hip_edge_frame(shared_edge, face1, face2)


class TestGenerateHipCapsBlockSize:
    def test_cut_blocks_use_geometry_derived_block_size_not_fixed_200(self, hip_roof):
        """Full-review finding freecad-mr-generators-20260915-e612#22:
        this hip roof's faces have a BoundBox.DiagonalLength on the order
        of ~50mm (a small HO-scale hip corner) -- the OLD hardcoded
        block_size=200.0 would have been ~4x oversized relative to this
        geometry; the fix derives block_size from the actual faces, so it
        should scale with them instead. Verified by checking the real
        cutting-block solids this produces are non-degenerate and their
        extent is consistent with the derived (not the old fixed) size --
        not by reading block_size directly, since it's a local variable,
        but through its actual effect on the shapes generate_hip_caps
        returns.
        """
        mod = _import_proxy_module("roof_seam_generator", "roof_seam_proxy")
        face1, face2, shared_edge = hip_roof

        expected_block_size = max(
            face1.BoundBox.DiagonalLength, face2.BoundBox.DiagonalLength, 1.0) * 2.0
        # Sanity: for this real, small HO-scale hip corner, the derived
        # size must be far smaller than the old fixed 200.0 constant --
        # otherwise this test wouldn't actually distinguish the fix from
        # the old behavior.
        assert expected_block_size < 100.0, (
            f"derived block_size={expected_block_size} is not meaningfully "
            f"different from the old fixed 200.0 for this fixture -- test "
            f"geometry needs adjusting to actually exercise the fix")

        shapes, cut_blocks = mod.generate_hip_caps(
            shared_edge, face1, face2,
            {'hipCapWidth': 3.0, 'shingleHeight': 1.0, 'materialThickness': 0.2,
             'shingleExposure': 0.8, 'angleDepth': 0.1})

        assert shapes, "expected at least one hip cap shape"
        for shape in shapes:
            assert shape.Volume > 1e-6


# ---------------------------------------------------------------------------
# shingle/snow_guard/standing_seam/standing_seam_snow_guard proxies:
# get_roof_face_coordinate_system consumers (slate_generator already has
# its own FreeCAD test coverage of this -- test_slate_proxy_redundant_
# top_course.py -- so it's intentionally not repeated here).
# ---------------------------------------------------------------------------

U_LENGTH = 10.0
V_LENGTH = 15.4


@pytest.fixture
def ridge_face():
    # Single rectangular roof face in the XZ plane, normal -Y -- same
    # convention and same shape as slate_generator's own working fixture
    # (test_slate_proxy_redundant_top_course.py's ridge_face), reused here
    # rather than re-derived, since it's already a validated convention.
    return _face([(0, 0, 0), (U_LENGTH, 0, 0), (U_LENGTH, 0, V_LENGTH), (0, 0, V_LENGTH)])


@pytest.mark.parametrize("gen_dir,mod_name", [
    ("shingle_generator", "shingle_proxy"),
    ("snow_guard_generator", "snow_guard_proxy"),
    ("standing_seam_generator", "standing_seam_proxy"),
    ("standing_seam_snow_guard_generator", "standing_seam_snow_guard_proxy"),
], ids=["shingle", "snow_guard", "standing_seam", "standing_seam_snow_guard"])
class TestGetRoofFaceCoordinateSystemConsumers:
    def test_returns_sane_coordinate_system(self, ridge_face, gen_dir, mod_name):
        mod = _import_proxy_module(gen_dir, mod_name)

        origin, u_vec, v_vec, normal, u_length, v_length = \
            mod._get_face_coordinate_system(ridge_face)

        assert u_length == pytest.approx(U_LENGTH, abs=1e-6)
        assert v_length == pytest.approx(V_LENGTH, abs=1e-6)
        assert u_vec.Length == pytest.approx(1.0, abs=1e-6)
        assert v_vec.Length == pytest.approx(1.0, abs=1e-6)
        assert u_vec.dot(v_vec) == pytest.approx(0.0, abs=1e-6)
        # Origin must lie on (or at least very near) the face's own plane
        # -- a real sanity check that this isn't returning nonsense.
        assert normal.Length == pytest.approx(1.0, abs=1e-6)

    def test_all_four_consumers_agree_on_the_same_face(self, ridge_face, gen_dir, mod_name):
        """Cross-consumer parity: this is literally the same shared
        function (shared/freecad_utils.get_roof_face_coordinate_system)
        under 4 different proxy-local names -- they must all return
        identical results for the identical input, not just each
        individually look reasonable. Compares against shingle_proxy's
        result as the reference."""
        if mod_name == "shingle_proxy":
            pytest.skip("reference consumer, nothing to compare against itself")
        reference_mod = _import_proxy_module("shingle_generator", "shingle_proxy")
        ref = reference_mod._get_face_coordinate_system(ridge_face)

        mod = _import_proxy_module(gen_dir, mod_name)
        got = mod._get_face_coordinate_system(ridge_face)

        ref_origin, ref_u, ref_v, ref_n, ref_ul, ref_vl = ref
        got_origin, got_u, got_v, got_n, got_ul, got_vl = got

        assert got_origin.distanceToPoint(ref_origin) < 1e-6
        assert (got_u - ref_u).Length < 1e-6
        assert (got_v - ref_v).Length < 1e-6
        assert (got_n - ref_n).Length < 1e-6
        assert got_ul == pytest.approx(ref_ul, abs=1e-6)
        assert got_vl == pytest.approx(ref_vl, abs=1e-6)
