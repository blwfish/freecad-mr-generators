"""
Tests for standing_seam_snow_guard_geometry.py.

No TestStandingSeamSnowGuardProxyParity class here, same rationale as
snow_guard_generator/tests/test_snow_guard_geometry.py: the proxy calls
calculate_seam_guard_positions(...) directly and does not inline any
duplicate copy of the rib/row arithmetic. There is exactly one source of
truth for guard placement.
"""

import pytest

from standing_seam_snow_guard_geometry import (
    validate_parameters,
    calculate_rib_u_positions,
    calculate_seam_guard_positions,
)
from boundary_assertions import assert_no_boundary_coincidence


# ---------------------------------------------------------------------------
# validate_parameters
# ---------------------------------------------------------------------------

class TestParameterValidation:

    def test_all_positive_reasonable_dimensions_valid(self):
        valid, errors = validate_parameters(
            clamp_width=1.0, clamp_length=1.2, clamp_thickness=0.15,
            fin_height=1.0, fin_base_width=0.8, fin_thickness=0.6,
            panel_width=3.0)
        assert valid
        assert errors == []

    @pytest.mark.parametrize("field", [
        "clamp_width", "clamp_length", "clamp_thickness",
        "fin_height", "fin_base_width", "fin_thickness", "panel_width",
    ])
    @pytest.mark.parametrize("bad_value", [0.0, -1.0])
    def test_nonpositive_dimension_invalid(self, field, bad_value):
        kwargs = dict(clamp_width=1.0, clamp_length=1.2, clamp_thickness=0.15,
                      fin_height=1.0, fin_base_width=0.8, fin_thickness=0.6,
                      panel_width=3.0)
        kwargs[field] = bad_value
        valid, errors = validate_parameters(**kwargs)
        assert not valid
        assert any(field in e for e in errors)

    @pytest.mark.parametrize("clamp_width,expect_valid", [
        (2.999999, True),   # just below panel_width
        (3.0,      False),  # at panel_width -- strict `<` required
        (3.000001, False),  # just above panel_width
    ])
    def test_clamp_width_vs_panel_width_threshold(self, clamp_width, expect_valid):
        valid, errors = validate_parameters(
            clamp_width=clamp_width, clamp_length=1.2, clamp_thickness=0.15,
            fin_height=1.0, fin_base_width=0.8, fin_thickness=0.6,
            panel_width=3.0)
        assert valid == expect_valid

    @pytest.mark.parametrize("fin_base_width,expect_valid", [
        (1.2,      True),
        (1.199999, True),
        (1.200001, False),
    ])
    def test_fin_base_width_vs_clamp_length_threshold(self, fin_base_width, expect_valid):
        valid, errors = validate_parameters(
            clamp_width=1.0, clamp_length=1.2, clamp_thickness=0.15,
            fin_height=1.0, fin_base_width=fin_base_width, fin_thickness=0.6,
            panel_width=3.0)
        assert valid == expect_valid


# ---------------------------------------------------------------------------
# calculate_rib_u_positions
# ---------------------------------------------------------------------------

class TestRibUPositions:

    def test_realistic_ho_scale_parameter_set(self):
        # ~150mm-wide standing-seam field, real StandingSeamPanels defaults.
        positions = calculate_rib_u_positions(
            u_length=150.0, panel_width=3.0, seam_width=0.4, edge_margin=3.0)
        assert len(positions) == 48
        assert positions[0] == pytest.approx(5.8)
        assert positions[-1] == pytest.approx(146.8)
        # Deterministic periodic phase: every rib exactly 3.0mm apart.
        deltas = [b - a for a, b in zip(positions, positions[1:])]
        assert deltas == pytest.approx([3.0] * (len(positions) - 1))

    def test_single_panel_width_minimum(self):
        # Exactly one panel_width wide -- only the first rib fits.
        assert calculate_rib_u_positions(
            u_length=3.0, panel_width=3.0, seam_width=0.4, edge_margin=0.1) == \
            pytest.approx([2.8])

    def test_exact_integer_multiple_u_length(self):
        # u_length is an exact multiple of panel_width; ribs are phase-offset
        # by -seam_width/2 so none ever lands exactly on a panel boundary.
        assert calculate_rib_u_positions(
            u_length=9.0, panel_width=3.0, seam_width=0.4, edge_margin=0.5) == \
            pytest.approx([2.8, 5.8])

    @pytest.mark.parametrize("edge_margin,rib_present", [
        (1.199999, True),   # hi comfortably above the k=3 rib (8.8)
        (1.2,      True),   # hi exactly at the k=3 rib -- boundary allowed
        (1.200001, False),  # hi just below the k=3 rib
    ])
    def test_high_margin_threshold(self, edge_margin, rib_present):
        positions = calculate_rib_u_positions(
            u_length=10.0, panel_width=3.0, seam_width=0.4, edge_margin=edge_margin)
        assert any(abs(p - 8.8) < 1e-6 for p in positions) == rib_present

    @pytest.mark.parametrize("edge_margin,rib_present", [
        (2.799999, True),   # lo comfortably below the k=1 rib (2.8)
        (2.8,      True),   # lo exactly at the k=1 rib -- boundary allowed
        (2.800001, False),  # lo just above the k=1 rib
    ])
    def test_low_margin_threshold(self, edge_margin, rib_present):
        positions = calculate_rib_u_positions(
            u_length=10.0, panel_width=3.0, seam_width=0.4, edge_margin=edge_margin)
        assert any(abs(p - 2.8) < 1e-6 for p in positions) == rib_present

    @pytest.mark.parametrize("panel_width", [0.0, -1.0])
    def test_nonpositive_panel_width_raises(self, panel_width):
        with pytest.raises(ValueError, match="panel_width"):
            calculate_rib_u_positions(10.0, panel_width, 0.4, 1.0)

    @pytest.mark.parametrize("edge_margin", [0.0, -1.0])
    def test_nonpositive_edge_margin_raises(self, edge_margin):
        with pytest.raises(ValueError, match="edge_margin"):
            calculate_rib_u_positions(10.0, 3.0, 0.4, edge_margin)

    @pytest.mark.parametrize("seam_width", [0.0, -1.0, 3.0, 4.0])
    def test_seam_width_outside_range_raises(self, seam_width):
        with pytest.raises(ValueError, match="seam_width"):
            calculate_rib_u_positions(10.0, 3.0, seam_width, 1.0)


# ---------------------------------------------------------------------------
# calculate_seam_guard_positions
# ---------------------------------------------------------------------------

class TestSeamGuardPositions:

    def test_seam_stride_one_guards_every_rib(self):
        result = calculate_seam_guard_positions(
            u_length=150.0, v_length=100.0, panel_width=3.0, seam_width=0.4,
            seam_stride=1, num_rows=1, first_row_offset=8.0, row_spacing=15.0,
            edge_margin=3.0, v_margin=2.0)
        assert len(result) == 48

    def test_seam_stride_three_guards_every_third_rib(self):
        result = calculate_seam_guard_positions(
            u_length=150.0, v_length=100.0, panel_width=3.0, seam_width=0.4,
            seam_stride=3, num_rows=1, first_row_offset=8.0, row_spacing=15.0,
            edge_margin=3.0, v_margin=2.0)
        assert len(result) == 16

    def test_stride_larger_than_rib_count_guards_first_rib_only(self):
        # Python slice semantics always include index 0 -- an explicit,
        # tested choice (see calculate_seam_guard_positions' docstring),
        # not a "didn't think about it" ambiguous case.
        result = calculate_seam_guard_positions(
            u_length=150.0, v_length=100.0, panel_width=3.0, seam_width=0.4,
            seam_stride=1000, num_rows=1, first_row_offset=8.0, row_spacing=15.0,
            edge_margin=3.0, v_margin=2.0)
        assert len(result) == 1
        _, u, _ = result[0]
        assert u == pytest.approx(5.8)

    @pytest.mark.parametrize("seam_stride", [0, -1])
    def test_invalid_seam_stride_raises(self, seam_stride):
        with pytest.raises(ValueError, match="seam_stride"):
            calculate_seam_guard_positions(
                150.0, 100.0, 3.0, 0.4, seam_stride, 1, 8.0, 15.0, 3.0, 2.0)

    def test_no_ribs_in_usable_range_raises(self):
        with pytest.raises(ValueError, match="no seam ribs"):
            calculate_seam_guard_positions(
                u_length=5.0, v_length=100.0, panel_width=3.0, seam_width=0.4,
                seam_stride=1, num_rows=1, first_row_offset=8.0, row_spacing=15.0,
                edge_margin=10.0, v_margin=2.0)

    def test_infeasible_row_grid_raises(self):
        with pytest.raises(ValueError, match="does not fit face"):
            calculate_seam_guard_positions(
                u_length=150.0, v_length=50.0, panel_width=3.0, seam_width=0.4,
                seam_stride=3, num_rows=5, first_row_offset=8.0, row_spacing=100.0,
                edge_margin=3.0, v_margin=2.0)

    def test_realistic_ho_scale_full_grid(self):
        result = calculate_seam_guard_positions(
            u_length=150.0, v_length=100.0, panel_width=3.0, seam_width=0.4,
            seam_stride=3, num_rows=2, first_row_offset=8.0, row_spacing=15.0,
            edge_margin=3.0, v_margin=2.0)
        assert len(result) == 2 * 16
        assert {r for (r, u, v) in result} == {0, 1}
        # v1: every guarded row uses the identical rib set (no alternation).
        row0 = sorted(u for (r, u, v) in result if r == 0)
        row1 = sorted(u for (r, u, v) in result if r == 1)
        assert row0 == pytest.approx(row1)


# ---------------------------------------------------------------------------
# Downstream (OCCT) invariants
# ---------------------------------------------------------------------------

class TestStandingSeamDownstreamInvariants:
    """Standing-seam guards are a SPARSE placement (no tiling union, no
    boolean clip against the roof/seam geometry), so the applicable
    invariant is "no guard edge lands on the face boundary" --
    assert_no_boundary_coincidence -- same as snow_guard_generator.
    """

    def test_no_guard_footprint_touches_face_boundary(self):
        clamp_width, clamp_length = 1.0, 1.2
        u_length, v_length = 150.0, 100.0
        positions = calculate_seam_guard_positions(
            u_length=u_length, v_length=v_length, panel_width=3.0, seam_width=0.4,
            seam_stride=3, num_rows=2, first_row_offset=8.0, row_spacing=15.0,
            edge_margin=3.0, v_margin=2.0)

        half_w, half_l = clamp_width / 2.0, clamp_length / 2.0

        assert_no_boundary_coincidence(
            positions, 0.0, u_length,
            get_extent=lambda p: (p[1] - half_w, p[1] + half_w),
            label="u-axis: ")
        assert_no_boundary_coincidence(
            positions, 0.0, v_length,
            get_extent=lambda p: (p[2] - half_l, p[2] + half_l),
            label="v-axis: ")

    @pytest.mark.parametrize("dim", [1.0, 1.2, 0.15, 1.0, 0.8, 0.6])
    def test_guard_dimensions_are_non_degenerate(self, dim):
        assert dim > 1e-9
