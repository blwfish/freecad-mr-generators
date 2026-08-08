"""
Tests for roof_geometry.score_face_match / best_matching_candidate.

These back freecad_utils.resolve_base_face's "which candidate face is
really the source face" decision (see shared/freecad_utils.py and the
2026-08-08 fix for slate_seam_generator/roof_seam_generator not
recognizing the Sources PropertyLinkSubList convention). Covers the
threshold-boundary and ambiguous-input cases per the project's testing
rule: at/below/above the zero-length-normal epsilon, tie-breaking,
orientation-agnostic (abs(dot)) behavior, and empty input.
"""

import math
import pytest

from roof_geometry import (
    score_face_match, best_matching_candidate, calculate_across_roof_direction,
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
