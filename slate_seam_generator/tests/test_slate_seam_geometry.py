import math
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))

import slate_seam_geometry as ssg
from boundary_assertions import assert_overflows_boundary


# ---------------------------------------------------------------------------
# validate_parameters
# ---------------------------------------------------------------------------

class TestParameterValidation:

    def test_valid_parameters(self):
        ok, errors = ssg.validate_parameters(4.0, 2.5, 0.2, 1.4)
        assert ok
        assert errors == []

    @pytest.mark.parametrize("cap_width", [0.0, -1.0])
    def test_non_positive_cap_width(self, cap_width):
        ok, errors = ssg.validate_parameters(cap_width, 2.5, 0.2, 1.4)
        assert not ok
        assert any('cap_width' in e for e in errors)

    @pytest.mark.parametrize("cap_length", [0.0, -1.0])
    def test_non_positive_cap_length(self, cap_length):
        ok, errors = ssg.validate_parameters(4.0, cap_length, 0.2, 1.4)
        assert not ok
        assert any('cap_length' in e for e in errors)

    @pytest.mark.parametrize("thickness", [0.0, -1.0])
    def test_non_positive_thickness(self, thickness):
        ok, errors = ssg.validate_parameters(4.0, 2.5, thickness, 1.4)
        assert not ok
        assert any('material_thickness' in e for e in errors)

    @pytest.mark.parametrize("exposure", [0.0, -1.0])
    def test_non_positive_exposure(self, exposure):
        ok, errors = ssg.validate_parameters(4.0, 2.5, 0.2, exposure)
        assert not ok
        assert any('exposure' in e for e in errors)

    def test_exposure_exactly_equal_to_cap_length_is_valid(self):
        # Boundary: exposure == cap_length is the zero-overlap limit, not
        # itself invalid (only exposure > cap_length is rejected).
        ok, errors = ssg.validate_parameters(4.0, 2.5, 0.2, 2.5)
        assert ok

    def test_exposure_just_above_cap_length_is_invalid(self):
        ok, errors = ssg.validate_parameters(4.0, 2.5, 0.2, 2.5 + 1e-6)
        assert not ok
        assert any('exposure' in e for e in errors)

    def test_thickness_exactly_equal_to_cap_length_is_valid(self):
        ok, errors = ssg.validate_parameters(4.0, 2.5, 2.5, 1.4)
        assert ok

    def test_thickness_just_above_cap_length_is_invalid(self):
        ok, errors = ssg.validate_parameters(4.0, 2.5, 2.5 + 1e-6, 1.4)
        assert not ok
        assert any('material_thickness' in e for e in errors)

    def test_multiple_errors_all_reported(self):
        ok, errors = ssg.validate_parameters(-1.0, -1.0, -1.0, -1.0)
        assert not ok
        assert len(errors) == 4

    def test_real_model_parameters(self):
        # Values matching slate_generator's shipped defaults (Exposure=2.2)
        # plus a plausible cap geometry, not the docstring's own examples.
        ok, errors = ssg.validate_parameters(3.5, 3.0, 0.25, 2.2)
        assert ok


# ---------------------------------------------------------------------------
# resolve_cap_eligibility
# ---------------------------------------------------------------------------

class TestCapEligibility:

    def test_ridge_is_eligible(self):
        eligible, message = ssg.resolve_cap_eligibility('ridge')
        assert eligible is True
        assert message == ''

    def test_valley_is_rejected_with_flashing_pointer(self):
        eligible, message = ssg.resolve_cap_eligibility('valley')
        assert eligible is False
        assert 'valley' in message.lower() or 'VALLEY' in message
        assert 'roof_seam_generator' in message

    def test_none_is_rejected(self):
        eligible, message = ssg.resolve_cap_eligibility('none')
        assert eligible is False
        assert message != ''

    def test_ambiguous_is_rejected_not_defaulted_to_hip(self):
        # This is the critical case: 'ambiguous' must NOT be silently
        # treated as a hip. It has no verified real-world trigger anywhere
        # in this repo, so defaulting it to eligible would risk capping an
        # actual valley the one time it fires for real.
        eligible, message = ssg.resolve_cap_eligibility('ambiguous')
        assert eligible is False
        assert message != ''

    def test_unrecognized_string_is_rejected(self):
        eligible, message = ssg.resolve_cap_eligibility('some_garbage_value')
        assert eligible is False
        assert message != ''

    def test_empty_string_is_rejected(self):
        eligible, message = ssg.resolve_cap_eligibility('')
        assert eligible is False
        assert message != ''


# ---------------------------------------------------------------------------
# is_dihedral_foldable
# ---------------------------------------------------------------------------

class TestDihedralFoldability:

    def test_zero_degrees_is_foldable(self):
        assert ssg.is_dihedral_foldable(0.0) is True

    def test_typical_roof_pitch_is_foldable(self):
        assert ssg.is_dihedral_foldable(90.0) is True

    def test_just_below_default_max_is_foldable(self):
        assert ssg.is_dihedral_foldable(179.0 - 1e-6) is True

    def test_exactly_default_max_is_not_foldable(self):
        # Strict '<' boundary: the threshold value itself is excluded.
        assert ssg.is_dihedral_foldable(179.0) is False

    def test_just_above_default_max_is_not_foldable(self):
        assert ssg.is_dihedral_foldable(179.0 + 1e-6) is False

    def test_180_degrees_is_not_foldable(self):
        assert ssg.is_dihedral_foldable(180.0) is False

    def test_negative_degrees_is_not_foldable(self):
        assert ssg.is_dihedral_foldable(-1.0) is False

    def test_custom_max_degrees_boundary(self):
        assert ssg.is_dihedral_foldable(150.0, max_degrees=150.0) is False
        assert ssg.is_dihedral_foldable(150.0 - 1e-6, max_degrees=150.0) is True


# ---------------------------------------------------------------------------
# calculate_dihedral_fold
# ---------------------------------------------------------------------------

class TestDihedralFold:

    def test_flat_roof_gives_zero_h_center(self):
        fold = ssg.calculate_dihedral_fold(0.0, 4.0)
        assert fold['h_center'] == pytest.approx(0.0, abs=1e-9)
        assert fold['half_width'] == pytest.approx(2.0, abs=1e-9)
        assert fold['wing_len'] == pytest.approx(2.0, abs=1e-9)

    def test_hand_computed_90_degree_dihedral(self):
        # dihedral = 90 deg -> half_dihedral = 45 deg -> tan(45deg) = 1
        # h_center = half_width * 1 = half_width
        fold = ssg.calculate_dihedral_fold(math.pi / 2, 4.0)
        assert fold['half_width'] == pytest.approx(2.0, abs=1e-9)
        assert fold['h_center'] == pytest.approx(2.0, abs=1e-9)
        assert fold['wing_len'] == pytest.approx(2.0 * math.sqrt(2), abs=1e-9)

    def test_raises_below_domain(self):
        with pytest.raises(ValueError):
            ssg.calculate_dihedral_fold(-1e-6, 4.0)

    def test_raises_at_pi(self):
        with pytest.raises(ValueError):
            ssg.calculate_dihedral_fold(math.pi, 4.0)

    def test_raises_above_pi(self):
        with pytest.raises(ValueError):
            ssg.calculate_dihedral_fold(math.pi + 0.1, 4.0)

    def test_accepts_just_below_pi(self):
        # Should not raise -- caller is responsible for having already
        # checked is_dihedral_foldable; this function's own domain guard
        # is the internal [0, pi) contract, not the 179-degree UI guard.
        fold = ssg.calculate_dihedral_fold(math.pi - 1e-3, 4.0)
        assert fold['h_center'] > 0

    def test_real_model_cap_width(self):
        # A cap width not used anywhere else in this test file or in the
        # module's own docstring examples.
        fold = ssg.calculate_dihedral_fold(math.radians(120.0), 3.5)
        assert fold['half_width'] == pytest.approx(1.75, abs=1e-9)
        expected_h_center = 1.75 * math.tan(math.radians(60.0))
        assert fold['h_center'] == pytest.approx(expected_h_center, abs=1e-9)


# ---------------------------------------------------------------------------
# calculate_wing_profile_2d
# ---------------------------------------------------------------------------

class TestWingProfile2D:

    def test_flat_case_reduces_to_rectangle(self):
        fold = ssg.calculate_dihedral_fold(0.0, 4.0)
        profile = ssg.calculate_wing_profile_2d(fold, 0.2)
        # tc1 == tc2 in the degenerate flat case (both wings share one
        # outward normal), and the top edge is level with the bottom.
        assert profile['tc1'] == pytest.approx(profile['tc2'], abs=1e-9)
        assert profile['tl'][1] == pytest.approx(profile['tr'][1], abs=1e-9)
        assert profile['tl'][1] == pytest.approx(0.2, abs=1e-9)

    def test_non_degenerate_case_tc1_differs_from_tc2(self):
        fold = ssg.calculate_dihedral_fold(math.radians(90.0), 4.0)
        profile = ssg.calculate_wing_profile_2d(fold, 0.2)
        dx = profile['tc1'][0] - profile['tc2'][0]
        dz = profile['tc1'][1] - profile['tc2'][1]
        assert math.hypot(dx, dz) > 1e-6

    def test_zero_thickness_top_equals_bottom(self):
        fold = ssg.calculate_dihedral_fold(math.radians(90.0), 4.0)
        profile = ssg.calculate_wing_profile_2d(fold, 0.0)
        assert profile['tl'] == pytest.approx(profile['bl'], abs=1e-9)
        assert profile['tr'] == pytest.approx(profile['br'], abs=1e-9)

    def test_all_adjacent_edges_nonzero_length(self):
        # OCCT consumer invariant: every edge in the closed wire must be
        # non-degenerate, or Part.Face/Part.Wire can silently build a null
        # face instead of raising.
        fold = ssg.calculate_dihedral_fold(math.radians(90.0), 4.0)
        profile = ssg.calculate_wing_profile_2d(fold, 0.2)
        order = ['bl', 'bc', 'br', 'tr', 'tc2', 'tc1', 'tl']
        pts = [profile[k] for k in order]
        for i in range(len(pts)):
            a = pts[i]
            b = pts[(i + 1) % len(pts)]
            dist = math.hypot(b[0] - a[0], b[1] - a[1])
            assert dist > 1e-6, f"degenerate edge {order[i]}->{order[(i+1)%len(order)]}"

    def test_zero_width_cap_does_not_divide_by_zero(self):
        fold = ssg.calculate_dihedral_fold(math.radians(90.0), 0.0)
        profile = ssg.calculate_wing_profile_2d(fold, 0.2)
        assert profile['bl'] == pytest.approx((0.0, 0.0), abs=1e-9)
        assert profile['tl'][1] == pytest.approx(0.2, abs=1e-9)


# ---------------------------------------------------------------------------
# calculate_cap_count
# ---------------------------------------------------------------------------

class TestCapCount:

    def test_exact_integer_multiple(self):
        # edge_length is exactly 4x exposure -- the case that most readily
        # produces a zero-remainder/boundary-coincidence result elsewhere.
        assert ssg.calculate_cap_count(8.0, 2.0, margin=0) == 4

    def test_single_exposure_minimum(self):
        assert ssg.calculate_cap_count(2.0, 2.0, margin=0) == 1

    def test_just_below_single_exposure(self):
        assert ssg.calculate_cap_count(2.0 - 1e-6, 2.0, margin=0) == 1

    def test_just_above_single_exposure_forces_second_cap(self):
        assert ssg.calculate_cap_count(2.0 + 1e-6, 2.0, margin=0) == 2

    def test_default_margin_adds_two(self):
        assert ssg.calculate_cap_count(8.0, 2.0) == 4 + 2

    def test_zero_edge_length_returns_zero(self):
        assert ssg.calculate_cap_count(0.0, 2.0) == 0

    def test_negative_edge_length_returns_zero(self):
        assert ssg.calculate_cap_count(-1.0, 2.0) == 0

    def test_zero_exposure_returns_zero(self):
        assert ssg.calculate_cap_count(8.0, 0.0) == 0

    def test_negative_exposure_returns_zero(self):
        assert ssg.calculate_cap_count(8.0, -1.0) == 0

    def test_real_model_edge_length(self):
        # A seam length not drawn from this file's own example values.
        assert ssg.calculate_cap_count(17.3, 2.2, margin=2) == \
            int(math.ceil(17.3 / 2.2)) + 2


# ---------------------------------------------------------------------------
# Re-exports from shared/roof_geometry.py
# ---------------------------------------------------------------------------

class TestSharedGeometryReExports:

    def test_relocated_functions_importable(self):
        assert callable(ssg.is_valid_clip_fragment)
        assert callable(ssg.is_top_course_complete)
        assert callable(ssg.calculate_fitted_exposure)

    def test_relocated_functions_behave_as_in_roof_geometry(self):
        import roof_geometry
        assert ssg.is_valid_clip_fragment is roof_geometry.is_valid_clip_fragment
        assert ssg.is_top_course_complete is roof_geometry.is_top_course_complete
        assert ssg.calculate_fitted_exposure is roof_geometry.calculate_fitted_exposure

    def test_roof_orientation_helpers_importable(self):
        assert callable(ssg.classify_roof_intersection)
        assert callable(ssg.calculate_dihedral_angle)
        assert callable(ssg.analyze_roof_intersection)


# ---------------------------------------------------------------------------
# Downstream-consumer invariant: cap placement overflows the seam boundary
# ---------------------------------------------------------------------------

class TestCapPlacementBoundaryOverflow:

    def test_caps_overflow_seam_run_before_clipping(self):
        edge_length = 8.0
        exposure = 2.2
        fitted_exposure = ssg.calculate_fitted_exposure(edge_length, exposure)
        count = ssg.calculate_cap_count(edge_length, fitted_exposure)
        # The clip box is [0, edge_length] on both ends (per the plan's
        # design), so the run must overflow BOTH ends, not just the far
        # one -- placing the first cap exactly at 0 would put its own
        # bottom edge exactly coincident with the clip box's lower face,
        # the very failure mode this invariant exists to catch. Caps
        # therefore start one exposure-length before the seam origin,
        # mirroring calculate_layout's own over-generation-before-the-
        # boundary approach, and run each spanning
        # [start, start + cap_length).
        cap_length = 3.0
        start_offset = -fitted_exposure
        elements = [
            {'start': start_offset + i * fitted_exposure, 'length': cap_length}
            for i in range(count)
        ]
        assert_overflows_boundary(
            elements, 0.0, edge_length,
            get_extent=lambda e: (e['start'], e['start'] + e['length']),
            label='slate_seam cap run',
        )
