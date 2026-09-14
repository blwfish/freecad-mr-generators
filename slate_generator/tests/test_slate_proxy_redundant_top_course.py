"""
Integration test for slate_proxy.py's redundant-top-course fix
(2026-09-14): _generate_tiles_for_face used to keep generating courses
for the full num_courses "+3" safety buffer even after the first course
whose head already reaches the ridge/hip boundary -- harmless for a flat
tile (the redundant course clips to a thin sliver, discarded by
is_valid_clip_fragment's volume-ratio threshold), but confirmed live as a
real, visible defect for a WEDGE tile (butt_thickness > material_
thickness, the default whenever ButtThickness=0): the clip boundary can
land near the wedge's THICK butt end instead of its thin head, so a
substantial, unhidden stub survives well above the discard threshold,
sitting right on top of the already-complete course below it at the
ridge/hip line.

Requires a real FreeCAD -- skipped (not failed) under a plain
`python3 -m pytest` run. Run for real via:

    /path/to/FreeCADCmd shared/tests/run_freecad_tests.py slate_generator/tests
"""

import pytest

App = pytest.importorskip("FreeCAD")
import Part  # noqa: E402

import slate_proxy  # noqa: E402
import slate_geometry as sg  # noqa: E402


def _face(points):
    vecs = [App.Vector(*p) for p in points]
    wire = Part.makePolygon(vecs + [vecs[0]])
    return Part.Face(wire)


# Exposure exactly divides v_length (7 * 2.2 = 15.4) so calculate_fitted_
# exposure leaves it unchanged -- the redundant row's own v position is
# then simple to hand-verify: row 8's head lands exactly at 15.4 (the
# ridge), row 9's head lands at 17.6, 2.2 past it.
V_LENGTH = 15.4
U_LENGTH = 10.0
TILE_WIDTH = 2.0
TILE_HEIGHT = 2.5
MAT_THICK = 0.2
BUTT_THICK = MAT_THICK * 3  # matches execute()'s ButtThickness=0 auto-default
EXPOSURE = 2.2


@pytest.fixture
def ridge_face():
    # A single rectangular roof face in the XZ plane, normal -Y, matching
    # the coordinate-system convention get_roof_coordinate_system expects
    # (eave along the bottom edge at Z=0, ridge along the top at Z=V_LENGTH).
    return _face([
        (0, 0, 0), (U_LENGTH, 0, 0),
        (U_LENGTH, 0, V_LENGTH), (0, 0, V_LENGTH),
    ])


def _params(**overrides):
    p = dict(
        tile_width=TILE_WIDTH, tile_height=TILE_HEIGHT,
        material_thickness=MAT_THICK, butt_thickness=BUTT_THICK,
        exposure=EXPOSURE, stagger_pattern='half',
        hide_incomplete_top_course=False,
    )
    p.update(overrides)
    return p


class TestNoRedundantTopCourse:
    def test_only_one_tile_per_column_reaches_the_ridge(self, ridge_face):
        origin, u_vec, v_vec, normal, u_length, v_length = \
            slate_proxy._get_face_coordinate_system(ridge_face)
        assert v_length == pytest.approx(V_LENGTH, abs=1e-6)

        shapes = slate_proxy._generate_tiles_for_face(ridge_face, _params())
        assert shapes, "expected at least some tiles to survive clipping"

        def v_top(shape):
            return max(v.Point.sub(origin).dot(v_vec) for v in shape.Vertexes)

        def u_mid(shape):
            us = [v.Point.sub(origin).dot(u_vec) for v in shape.Vertexes]
            return (min(us) + max(us)) / 2.0

        at_ridge = [s for s in shapes if v_top(s) >= v_length - 1e-3]
        # Group by column (rounded U midpoint) -- each column should
        # contribute AT MOST one tile whose top reaches the ridge. Before
        # the fix, an interior column contributed two: the properly-fitted
        # complete course AND row 9's redundant wedge-butt stub.
        by_column = {}
        for s in at_ridge:
            key = round(u_mid(s), 2)
            by_column.setdefault(key, []).append(s)

        offenders = {k: len(v) for k, v in by_column.items() if len(v) > 1}
        assert not offenders, (
            f"columns with more than one tile reaching the ridge "
            f"(the redundant-stub bug): {offenders}")

    def test_complete_top_course_itself_is_unaffected(self, ridge_face):
        """Regression guard: the fix must not touch the properly-fitted
        complete course's own geometry -- it should still be present and
        still span nearly the tile's full volume (only the tiny topo_eps
        boundary nudge trimmed), not itself get skipped."""
        params = _params()
        origin, u_vec, v_vec, normal, u_length, v_length = \
            slate_proxy._get_face_coordinate_system(ridge_face)
        fitted = sg.calculate_fitted_exposure(v_length, params['exposure'])
        assert fitted == pytest.approx(EXPOSURE, abs=1e-9)  # exact fit by construction

        shapes = slate_proxy._generate_tiles_for_face(ridge_face, params)
        # Non-starter courses (row != 0, this fixture's whole reason for
        # using a wedge profile) are a trapezoid cross-section, not a box:
        # thick at the butt (BUTT_THICK), tapering to top_thick=butt*0.2
        # at the head.
        top_thick = BUTT_THICK * 0.2
        full_wedge_volume = TILE_WIDTH * TILE_HEIGHT * (BUTT_THICK + top_thick) / 2.0

        def v_top(shape):
            return max(v.Point.sub(origin).dot(v_vec) for v in shape.Vertexes)

        at_ridge = [s for s in shapes if v_top(s) >= v_length - 1e-3]
        assert at_ridge, "expected the complete top course to survive"
        # An interior tile's complete-course volume should be close to the
        # full wedge (only a topo_eps-scale nudge trimmed), not the ~30%
        # butt-heavy fragment the redundant row used to leave behind.
        assert any(s.Volume > 0.9 * full_wedge_volume for s in at_ridge), (
            f"no near-full-volume complete-course tile found at the ridge -- "
            f"volumes present: {sorted(round(s.Volume, 4) for s in at_ridge)}")

    def test_hide_incomplete_top_course_is_now_a_no_op(self, ridge_face):
        """Documents an intentional side effect of this fix, rather than
        hiding it: hide_incomplete_top_course used to gate the ONLY check
        that skipped a past-the-ridge course; that check is now
        unconditional (see _generate_tiles_for_face's comment), so the
        parameter no longer changes this function's output at all.
        HideIncompleteTopCourse (the FeaturePython property) is left in
        place for API/document compatibility, but is functionally inert
        as of this fix -- pinned here so a future change that revives its
        effect does so deliberately, not by accident."""
        shapes_false = slate_proxy._generate_tiles_for_face(
            ridge_face, _params(hide_incomplete_top_course=False))
        shapes_true = slate_proxy._generate_tiles_for_face(
            ridge_face, _params(hide_incomplete_top_course=True))

        assert len(shapes_false) == len(shapes_true)
        vols_false = sorted(round(s.Volume, 6) for s in shapes_false)
        vols_true = sorted(round(s.Volume, 6) for s in shapes_true)
        assert vols_false == vols_true
