"""
Tests for roof_seam_geometry.py -- the pure-Python extraction of
roof_seam_proxy.py's previously-untested cap-placement and hip-cap-profile
math (full-review finding freecad-mr-generators-20260808-a0b9#19).
"""

import math
import pytest

from roof_seam_geometry import (
    validate_exposure,
    calculate_cap_positions,
    calculate_hip_cap_profile,
)


class TestValidateExposure:
    def test_positive_passes(self):
        validate_exposure(1.5)  # no raise

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            validate_exposure(0.0)

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            validate_exposure(-0.5)

    def test_tiny_positive_passes(self):
        validate_exposure(1e-6)  # no raise


class TestCalculateCapPositions:
    def test_exact_multiple(self):
        # edge_len is an exact integer multiple of exposure
        positions = calculate_cap_positions(edge_len=6.0, exposure=1.5)
        assert positions == [0.0, 1.5, 3.0, 4.5]
        for t in positions:
            assert t < 6.0

    def test_non_exact_multiple(self):
        positions = calculate_cap_positions(edge_len=6.2, exposure=1.5)
        assert positions == [0.0, 1.5, 3.0, 4.5, 6.0]

    def test_single_unit_minimum(self):
        # edge_len just under one exposure -- only the t=0 cap fits
        positions = calculate_cap_positions(edge_len=1.4, exposure=1.5)
        assert positions == [0.0]

    def test_edge_len_exactly_zero(self):
        assert calculate_cap_positions(edge_len=0.0, exposure=1.5) == []

    def test_edge_len_negative_is_empty(self):
        # Degenerate/shouldn't-happen input -- must not hang, must not
        # produce nonsensical negative positions.
        assert calculate_cap_positions(edge_len=-5.0, exposure=1.5) == []

    def test_real_model_value(self):
        # A real (non-implementation-example) HO-scale hip length with the
        # shipped default exposure.
        positions = calculate_cap_positions(edge_len=47.3, exposure=1.5)
        assert positions[0] == 0.0
        assert all(t < 47.3 for t in positions)
        assert len(positions) == math.ceil(47.3 / 1.5)

    def test_exposure_zero_raises_not_hangs(self):
        # The original bug this module exists to prevent: exposure<=0 must
        # raise immediately, never enter an infinite non-advancing loop.
        with pytest.raises(ValueError):
            calculate_cap_positions(edge_len=10.0, exposure=0.0)

    def test_positions_strictly_increasing_and_spaced(self):
        positions = calculate_cap_positions(edge_len=20.0, exposure=2.32)
        diffs = [b - a for a, b in zip(positions, positions[1:])]
        assert all(d == pytest.approx(2.32, abs=1e-9) for d in diffs)


class TestCalculateHipCapProfile:
    def test_typical_90_degree_dihedral(self):
        profile = calculate_hip_cap_profile(
            half_width=1.75, mat_thick=0.25, cos_dihed=0.0, angle_depth=0.2)
        assert profile['taper'] == pytest.approx(0.05)
        assert profile['dihed'] == pytest.approx(math.pi / 2)
        # Cap should be symmetric left/right
        assert profile['bl_2d'][0] == pytest.approx(-profile['br_2d'][0])
        assert profile['tl_2d'][0] == pytest.approx(-profile['tr_2d'][0])

    def test_angle_depth_zero_gives_zero_taper(self):
        profile = calculate_hip_cap_profile(
            half_width=1.75, mat_thick=0.25, cos_dihed=0.0, angle_depth=0.0)
        assert profile['taper'] == 0.0

    def test_angle_depth_just_above_zero_gives_nonzero_taper(self):
        profile = calculate_hip_cap_profile(
            half_width=1.75, mat_thick=0.25, cos_dihed=0.0, angle_depth=1e-6)
        assert profile['taper'] > 0.0

    def test_coplanar_faces_zero_h_center(self):
        # cos_dihed=1 -> dihed=0 -- the two "hip" faces are actually
        # coplanar (no real hip). Degenerate but must not crash: cap
        # collapses to zero height in the wing direction.
        profile = calculate_hip_cap_profile(
            half_width=1.75, mat_thick=0.25, cos_dihed=1.0, angle_depth=0.2)
        assert profile['bl_2d'][1] == pytest.approx(profile['bc_2d'][1])
        assert profile['br_2d'][1] == pytest.approx(profile['bc_2d'][1])

    def test_near_180_degree_dihedral_raises(self):
        # The bug this extraction found: as cos_dihed -> -1, h_center =
        # half_width * tan(half_dihed) diverges toward infinity (tan's
        # singularity at half_dihed=pi/2). Must raise a clear error
        # instead of producing an enormous/nonsensical cap.
        with pytest.raises(ValueError):
            calculate_hip_cap_profile(
                half_width=1.75, mat_thick=0.25, cos_dihed=-0.9999999, angle_depth=0.2)

    def test_exactly_180_degree_dihedral_raises(self):
        with pytest.raises(ValueError):
            calculate_hip_cap_profile(
                half_width=1.75, mat_thick=0.25, cos_dihed=-1.0, angle_depth=0.2)

    def test_moderately_obtuse_dihedral_still_works(self):
        # Comfortably away from the degenerate boundary -- a real, if
        # unusual, low-slope hip roof (dihed ~150 degrees).
        cos_dihed = math.cos(math.radians(150))
        profile = calculate_hip_cap_profile(
            half_width=1.75, mat_thick=0.25, cos_dihed=cos_dihed, angle_depth=0.2)
        assert profile['dihed'] == pytest.approx(math.radians(150))

    def test_half_width_zero_raises(self):
        with pytest.raises(ValueError):
            calculate_hip_cap_profile(
                half_width=0.0, mat_thick=0.25, cos_dihed=0.0, angle_depth=0.2)

    def test_half_width_negative_raises(self):
        with pytest.raises(ValueError):
            calculate_hip_cap_profile(
                half_width=-1.0, mat_thick=0.25, cos_dihed=0.0, angle_depth=0.2)

    def test_mat_thick_zero_raises(self):
        with pytest.raises(ValueError):
            calculate_hip_cap_profile(
                half_width=1.75, mat_thick=0.0, cos_dihed=0.0, angle_depth=0.2)

    def test_cos_dihed_out_of_range_raises(self):
        with pytest.raises(ValueError):
            calculate_hip_cap_profile(
                half_width=1.75, mat_thick=0.25, cos_dihed=1.5, angle_depth=0.2)

    def test_real_model_value(self):
        # A real, non-implementation-example combination: HO-scale shingle
        # width default (3.5mm -> half_width=1.75... use a distinct value)
        # with a shallow roof pitch dihedral.
        cos_dihed = math.cos(math.radians(140))
        profile = calculate_hip_cap_profile(
            half_width=2.32, mat_thick=0.35, cos_dihed=cos_dihed, angle_depth=0.15)
        assert profile['taper'] == pytest.approx(0.0525)
        assert profile['cap_lift'] > 0
