"""
Tests for roof_geometry.score_face_match / best_matching_candidate /
classify_roof_intersection.

The score_face_match/best_matching_candidate tests back
freecad_utils.resolve_base_face's "which candidate face is really the
source face" decision (see shared/freecad_utils.py and the 2026-08-08 fix
for slate_seam_generator/roof_seam_generator not recognizing the Sources
PropertyLinkSubList convention). Covers the threshold-boundary and
ambiguous-input cases per the project's testing rule: at/below/above the
zero-length-normal epsilon, tie-breaking, orientation-agnostic (abs(dot))
behavior, and empty input.

The TestClassifyRoofIntersectionNormalBased tests cover the 2026-09-14
normal-based convex/reflex-edge test added to classify_roof_intersection,
using real geometry pulled from a live FreeCAD document (the hip case) and
a constructed, OCCT-validated groove solid (the valley case) rather than
hand-derived numbers, per this project's "verify empirically against real
geometry" practice.
"""

import math
import pytest

from roof_geometry import (
    score_face_match, best_matching_candidate, calculate_across_roof_direction,
    classify_roof_intersection,
)


# ---------------------------------------------------------------------------
# score_face_match
# ---------------------------------------------------------------------------

class TestScoreFaceMatch:
    def test_perfect_alignment_zero_distance(self):
        assert score_face_match(0.0, (0, 0, 1), (0, 0, 1)) == pytest.approx(-0.5, abs=1e-9)

    def test_perfect_alignment_nonzero_distance(self):
        assert score_face_match(1.0, (0, 0, 1), (0, 0, 1)) == pytest.approx(0.5, abs=1e-9)

    def test_orthogonal_normals_no_alignment_bonus(self):
        assert score_face_match(0.3, (0, 0, 1), (1, 0, 0)) == pytest.approx(0.3, abs=1e-9)

    def test_antiparallel_scores_identically_to_parallel(self):
        """Orientation-agnostic by design: a Part::MultiFuse result can leave
        locally-inconsistent Face.Orientation flags on otherwise-correct
        faces (confirmed 2026-08-08 on a real fused hip-roof solid), so an
        exactly-reversed normal must not be penalized relative to an
        exactly-aligned one."""
        parallel = score_face_match(2.0, (0, 1, 0), (0, 1, 0))
        antiparallel = score_face_match(2.0, (0, 1, 0), (0, -1, 0))
        assert parallel == pytest.approx(antiparallel, abs=1e-9)
        assert parallel == pytest.approx(1.5, abs=1e-9)

    def test_zero_length_orig_normal_gives_distance_only(self):
        assert score_face_match(0.7, (0, 0, 0), (0, 0, 1)) == pytest.approx(0.7, abs=1e-9)

    def test_zero_length_candidate_normal_gives_distance_only(self):
        assert score_face_match(0.7, (0, 0, 1), (0, 0, 0)) == pytest.approx(0.7, abs=1e-9)

    def test_both_normals_zero_length(self):
        assert score_face_match(0.7, (0, 0, 0), (0, 0, 0)) == pytest.approx(0.7, abs=1e-9)

    def test_non_unit_input_normals_are_normalized(self):
        """Inputs need not be pre-normalized -- a scaled-up parallel vector
        must score the same as its unit form."""
        unit = score_face_match(1.0, (0, 0, 1), (0, 0, 1))
        scaled = score_face_match(1.0, (0, 0, 5), (0, 0, 100))
        assert unit == pytest.approx(scaled, abs=1e-9)

    def test_epsilon_boundary_just_above_treated_as_real_vector(self):
        """A normal with length just above the 1e-9 degenerate-vector cutoff
        must be normalized and contribute a real alignment bonus, not be
        silently treated as zero."""
        tiny_but_real = (0.0, 0.0, 2e-9)
        score = score_face_match(1.0, (0, 0, 1), tiny_but_real)
        assert score == pytest.approx(0.5, abs=1e-6)

    def test_epsilon_boundary_at_cutoff_treated_as_degenerate(self):
        """At/below the 1e-9 cutoff, treated as a zero-length (unknown
        orientation) vector -- distance-only score, not a division blow-up."""
        assert score_face_match(1.0, (0, 0, 1), (0, 0, 1e-10)) == pytest.approx(1.0, abs=1e-9)

    def test_diagonal_normals(self):
        """A non-axis-aligned pair, pinned by exact arithmetic."""
        n1 = (1, 1, 0)   # magnitude sqrt(2)
        n2 = (1, 0, 0)
        expected_dot = abs((1 / math.sqrt(2)) * 1 + (1 / math.sqrt(2)) * 0 + 0)
        assert score_face_match(0.0, n1, n2) == pytest.approx(-expected_dot * 0.5, abs=1e-9)


# ---------------------------------------------------------------------------
# best_matching_candidate
# ---------------------------------------------------------------------------

class TestBestMatchingCandidate:
    def test_empty_candidates_returns_none(self):
        assert best_matching_candidate((0, 0, 1), []) is None

    def test_single_candidate_returns_its_payload(self):
        result = best_matching_candidate((0, 0, 1), [(1.0, (0, 0, 1), "only")])
        assert result == "only"

    def test_lower_score_wins(self):
        candidates = [
            (5.0, (0, 0, 1), "far_aligned"),
            (0.1, (1, 0, 0), "close_misaligned"),
        ]
        # far_aligned: 5.0 - 0.5 = 4.5 ; close_misaligned: 0.1 - 0 = 0.1
        assert best_matching_candidate((0, 0, 1), candidates) == "close_misaligned"

    def test_alignment_can_tip_a_close_distance_race(self):
        candidates = [
            (1.0, (1, 0, 0), "misaligned"),   # score = 1.0
            (1.0, (0, 0, 1), "aligned"),      # score = 0.5
        ]
        assert best_matching_candidate((0, 0, 1), candidates) == "aligned"

    def test_exact_tie_first_candidate_wins(self):
        """Strict '<' comparison: a later candidate must beat, not just
        match, the current best. Load-bearing for callers that pre-sort
        candidates by preference."""
        candidates = [
            (1.0, (0, 0, 1), "first"),
            (1.0, (0, 0, 1), "second"),
        ]
        assert best_matching_candidate((0, 0, 1), candidates) == "first"

    def test_three_way_pick(self):
        candidates = [
            (2.0, (0, 0, 1), "a"),   # 1.5
            (0.5, (1, 0, 0), "b"),   # 0.5
            (0.2, (0, 1, 0), "c"),   # 0.2
        ]
        assert best_matching_candidate((0, 0, 1), candidates) == "c"

    def test_payload_can_be_any_object_not_just_strings(self):
        payload = (object(), 42)
        result = best_matching_candidate((0, 0, 1), [(0.0, (0, 0, 1), payload)])
        assert result is payload


# ---------------------------------------------------------------------------
# calculate_across_roof_direction
#
# Full-review finding #33 (2026-08-08): never directly unit-tested before
# (only imported transitively, and only by an out-of-scope test file).
# Covers both paths (real eave-edge direction vs. cross-product fallback),
# the abs_y >= abs_x sign-convention branch both ways, and the internal
# > 0.001 thresholds at/below/above.
# ---------------------------------------------------------------------------

class TestCalculateAcrossRoofDirection:

    # -- eave-vertices path: sign-convention branches --------------------

    def test_eave_edge_along_x_normalizes_to_positive_x(self):
        result = calculate_across_roof_direction(
            vertices=[], upslope=(0, 1, 0), face_normal=(0, 0, 1),
            eave_vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)])
        assert result == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)

    def test_eave_edge_along_x_reversed_order_same_result(self):
        # Sign convention must depend only on the edge's geometric
        # direction, not which vertex happened to be listed first.
        result = calculate_across_roof_direction(
            vertices=[], upslope=(0, 1, 0), face_normal=(0, 0, 1),
            eave_vertices=[(10.0, 0.0, 0.0), (0.0, 0.0, 0.0)])
        assert result == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)

    def test_eave_edge_along_y_normalizes_to_positive_y(self):
        result = calculate_across_roof_direction(
            vertices=[], upslope=(1, 0, 0), face_normal=(0, 0, 1),
            eave_vertices=[(0.0, 0.0, 0.0), (0.0, 10.0, 0.0)])
        assert result == pytest.approx((0.0, 1.0, 0.0), abs=1e-9)

    def test_eave_edge_along_y_reversed_order_same_result(self):
        result = calculate_across_roof_direction(
            vertices=[], upslope=(1, 0, 0), face_normal=(0, 0, 1),
            eave_vertices=[(0.0, 10.0, 0.0), (0.0, 0.0, 0.0)])
        assert result == pytest.approx((0.0, 1.0, 0.0), abs=1e-9)

    def test_diagonal_edge_at_exact_abs_x_equals_abs_y_takes_y_branch(self):
        # abs_y >= abs_x is `>=`, so an exact tie must take the y-sign
        # branch, not the x-sign branch -- pin which one at the threshold.
        result = calculate_across_roof_direction(
            vertices=[], upslope=(0, 0, 1), face_normal=(1, 0, 0),
            eave_vertices=[(0.0, 0.0, 0.0), (-1.0, -1.0, 0.0)])
        # u = (-0.7071, -0.7071, 0); abs_y(0.7071) >= abs_x(0.7071) -> True
        # -> y-branch flips on u[1] < 0 -> both components flip sign.
        assert result == pytest.approx(
            (1 / math.sqrt(2), 1 / math.sqrt(2), 0.0), abs=1e-9)

    # -- eave-vertices path: falls through to fallback on degenerate input --

    def test_fewer_than_two_eave_vertices_falls_back(self):
        result = calculate_across_roof_direction(
            vertices=[], upslope=(0, 1, 0), face_normal=(0, 0, 1),
            eave_vertices=[(0.0, 0.0, 0.0)])
        # Fallback cross product of face_normal x upslope = (0,0,1)x(0,1,0) = (-1,0,0)
        assert result == pytest.approx((-1.0, 0.0, 0.0), abs=1e-9)

    def test_none_eave_vertices_falls_back(self):
        result = calculate_across_roof_direction(
            vertices=[], upslope=(0, 1, 0), face_normal=(0, 0, 1),
            eave_vertices=None)
        assert result == pytest.approx((-1.0, 0.0, 0.0), abs=1e-9)

    def test_empty_eave_vertices_falls_back(self):
        result = calculate_across_roof_direction(
            vertices=[], upslope=(0, 1, 0), face_normal=(0, 0, 1),
            eave_vertices=[])
        assert result == pytest.approx((-1.0, 0.0, 0.0), abs=1e-9)

    @pytest.mark.parametrize("dx,falls_back", [
        (0.0009, True),    # below threshold
        (0.001, True),     # at threshold -- strict '>' required to use eave path
        (0.0011, False),   # just above threshold -- eave path used
    ])
    def test_max_eave_distance_threshold(self, dx, falls_back):
        result = calculate_across_roof_direction(
            vertices=[], upslope=(0, 1, 0), face_normal=(0, 0, 1),
            eave_vertices=[(0.0, 0.0, 0.0), (dx, 0.0, 0.0)])
        if falls_back:
            # Fallback cross product: (0,0,1) x (0,1,0) = (-1,0,0)
            assert result == pytest.approx((-1.0, 0.0, 0.0), abs=1e-9)
        else:
            assert result == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)

    # -- cross-product fallback path ---------------------------------------

    def test_fallback_cross_product_normal_case(self):
        result = calculate_across_roof_direction(
            vertices=[], upslope=(0, 1, 0), face_normal=(0, 0, 1),
            eave_vertices=None)
        # (0,0,1) x (0,1,0) = (0*0-1*1, 1*0-0*0, 0*1-0*0) = (-1, 0, 0)
        assert result == pytest.approx((-1.0, 0.0, 0.0), abs=1e-9)

    def test_fallback_parallel_normal_and_upslope_returns_default(self):
        # face_normal parallel to upslope -> cross product is the zero
        # vector -> degenerate; function returns the documented (1,0,0)
        # default rather than dividing by zero.
        result = calculate_across_roof_direction(
            vertices=[], upslope=(0, 0, 1), face_normal=(0, 0, 1),
            eave_vertices=None)
        assert result == (1, 0, 0)

    def test_fallback_near_parallel_at_length_threshold_returns_default(self):
        # A tiny non-zero cross product (length just below the 0.001
        # threshold) must still hit the degenerate-fallback branch, not
        # attempt to normalize a near-zero vector.
        result = calculate_across_roof_direction(
            vertices=[], upslope=(0, 0.0005, 1.0), face_normal=(0, 0, 1),
            eave_vertices=None)
        assert result == (1, 0, 0)


# ---------------------------------------------------------------------------
# classify_roof_intersection -- normal-based convex/reflex-edge test
# ---------------------------------------------------------------------------

class TestClassifyRoofIntersectionNormalBased:
    """Regression coverage for the 2026-09-14 fix: a diagonal hip line on a
    symmetric trapezoidal hip face is structurally invisible to the older
    Z-coordinate-average heuristic (the face's own non-shared vertices are
    the exact mirror of the shared edge's endpoints, so their average Z
    always lands exactly on the shared edge's own midpoint Z -- not a
    near-boundary imprecision, a guaranteed miss for this face shape).
    """

    # Real hip corner pulled live from a FreeCAD document (SlateSeamCaps005
    # in equipment_hut_demo, 2026-09-14): two trapezoidal hip faces of a
    # simple rectangular-plan hip roof, meeting along the diagonal hip
    # line at the corner. Confirmed genuinely convex (a hip, not a valley)
    # by inspection of the model. The old Z-average heuristic reported
    # this 'ambiguous' (confidence 'medium') in 5 of 6 real seam objects in
    # that document.
    HIP_FACE1_VERTS = [
        (24.5241, -17.5172, 28.0276), (-24.5241, -17.5172, 28.0276),
        (21.0207, -14.0138, 31.531), (-21.0207, -14.0138, 31.531),
    ]
    HIP_FACE1_NORMAL = (0.0, -0.7071, 0.7071)
    HIP_FACE2_VERTS = [
        (24.5241, 17.5172, 28.0276), (24.5241, -17.5172, 28.0276),
        (21.0207, 14.0138, 31.531), (21.0207, -14.0138, 31.531),
    ]
    HIP_FACE2_NORMAL = (0.7071, -0.0, 0.7071)
    HIP_SHARED_EDGE = ((21.0207, -14.0138, 31.531), (24.5241, -17.5172, 28.0276))

    # A real valley: two sloped faces of a V-groove cut into the top of a
    # box (Part.makeBox + a wedge cut, OCCT-validated solid, real computed
    # face normals) -- constructed and inspected live via FreeCAD MCP
    # 2026-09-14 specifically to cross-check the sign convention of the
    # hip test above against a genuine concave case, not just assumed.
    VALLEY_FACE1_VERTS = [(72.5, 0, 50), (50, 0, 20), (72.5, 100, 50), (50, 100, 20)]
    VALLEY_FACE1_NORMAL = (-0.8, 0.0, 0.6)
    VALLEY_FACE2_VERTS = [(50, 0, 20), (50, 100, 20), (27.5, 100, 50), (27.5, 0, 50)]
    VALLEY_FACE2_NORMAL = (0.8, 0.0, 0.6)
    VALLEY_SHARED_EDGE = ((50, 0, 20), (50, 100, 20))

    def test_diagonal_hip_line_without_normals_is_the_old_ambiguous_bug(self):
        """Documents the pre-fix blind spot: with no normals supplied, the
        Z-average fallback still can't tell this hip line from ambiguous.
        This must keep failing this way for old callers that don't pass
        normals -- the fix is additive, not a change to the fallback."""
        result = classify_roof_intersection(
            self.HIP_FACE1_VERTS, self.HIP_FACE2_VERTS, self.HIP_SHARED_EDGE)
        assert result['classification'] == 'ambiguous'
        assert result['method'] == 'z_average'
        # The structural signature of the bug: both faces' non-shared
        # vertices average to exactly the shared edge's own midpoint Z.
        assert result['face1_other_z'] == pytest.approx(result['shared_edge_z'], abs=1e-6)
        assert result['face2_other_z'] == pytest.approx(result['shared_edge_z'], abs=1e-6)

    def test_diagonal_hip_line_with_normals_is_correctly_ridge(self):
        result = classify_roof_intersection(
            self.HIP_FACE1_VERTS, self.HIP_FACE2_VERTS, self.HIP_SHARED_EDGE,
            face1_normal=self.HIP_FACE1_NORMAL, face2_normal=self.HIP_FACE2_NORMAL)
        assert result['classification'] == 'ridge'
        assert result['confidence'] == 'high'
        assert result['method'] == 'normal'

    def test_real_valley_groove_is_correctly_valley(self):
        """Cross-checks the sign convention: a genuinely concave case must
        not be flipped into 'ridge' by the same normal-based test."""
        result = classify_roof_intersection(
            self.VALLEY_FACE1_VERTS, self.VALLEY_FACE2_VERTS, self.VALLEY_SHARED_EDGE,
            face1_normal=self.VALLEY_FACE1_NORMAL, face2_normal=self.VALLEY_FACE2_NORMAL)
        assert result['classification'] == 'valley'
        assert result['confidence'] == 'high'
        assert result['method'] == 'normal'

    def test_real_valley_without_normals_still_matches_old_behavior(self):
        """This particular valley's shared edge is level (not diagonal), so
        unlike the hip case it was never actually broken -- the Z-average
        fallback already got it right. Pinned so the fix doesn't
        accidentally change behavior for the cases that were already fine."""
        result = classify_roof_intersection(
            self.VALLEY_FACE1_VERTS, self.VALLEY_FACE2_VERTS, self.VALLEY_SHARED_EDGE)
        assert result['classification'] == 'valley'
        assert result['method'] == 'z_average'

    def test_disagreeing_normal_sides_is_ambiguous(self):
        """One non-shared vertex lands on each side of the adjacent face's
        plane -- a genuinely inconsistent case, must not guess."""
        edge = ((0, 0, 0), (0, 10, 0))
        face1_verts = [(0, 0, 0), (0, 10, 0), (0, -5, -5)]
        face2_verts = [(0, 0, 0), (0, 10, 0), (-5, 5, 5), (5, 5, 5)]
        result = classify_roof_intersection(
            face1_verts, face2_verts, edge,
            face1_normal=(1, 0, 0), face2_normal=(0, 1, 0))
        assert result['classification'] == 'ambiguous'
        assert result['method'] == 'normal'
        assert result['confidence'] == 'low'

    @pytest.mark.parametrize("other_z,face1_other_z,expected", [
        # exactly at normal_tolerance -- boundary itself, not decisive.
        # face1_other_z is irrelevant here: side_a alone is already
        # 'mixed' at this boundary, which forces ambiguous regardless of
        # side_b -- kept far on the 'inside' to show it isn't what's
        # driving the ambiguity.
        (-1e-6, -100, 'ambiguous'),
        # inside the tolerance band -- near-coplanar, not decisive either.
        (-0.5e-6, -100, 'ambiguous'),
        # safely past the tolerance on the 'inside' side, and face1's own
        # other vertex agrees (also 'inside') -- decisive ridge.
        (-2e-6, -100, 'ridge'),
        # safely past the tolerance on the 'outside' side, and face1's own
        # other vertex agrees (also 'outside') -- decisive valley.
        (2e-6, 100, 'valley'),
    ])
    def test_normal_tolerance_at_below_above_boundary(self, other_z, face1_other_z, expected):
        """Threshold-boundary coverage for the default normal_tolerance
        (1e-6): a signed distance exactly at the tolerance, or inside the
        band, must not be treated as decisive (avoids a near-coplanar
        vertex flipping the classification on floating-point noise)."""
        edge = ((0, 0, 0), (0, 10, 0))
        face1_verts = [(0, 0, 0), (0, 10, 0), (5, 5, face1_other_z)]
        face2_verts = [(0, 0, 0), (0, 10, 0), (5, 5, other_z)]
        result = classify_roof_intersection(
            face1_verts, face2_verts, edge,
            face1_normal=(0, 0, 1), face2_normal=(0, 0, 1))
        assert result['classification'] == expected
        if expected == 'ambiguous':
            assert result['confidence'] == 'low'
        else:
            assert result['confidence'] == 'high'
