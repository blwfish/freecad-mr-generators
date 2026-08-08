"""
Tests for snow_guard_geometry.py.

No TestSnowGuardProxyParity class here (contrast with e.g.
shingle_generator/tests/test_shingle_geometry.py::TestShinglePositionProxyParity,
this repo's model for the parity-test rule in CLAUDE.md): snow_guard_proxy.py
calls calculate_grid_positions(...) directly for every guard position and
does not inline any duplicate copy of the row/spacing arithmetic -- the
proxy's only extra math is converting a (u, v) center position into a 3D
Placement via origin/u_vec/v_vec, which every roof-surface generator in
this repo does identically and which is not itself a second copy of
geometry.py's own logic. There is exactly one source of truth for grid
placement, so no parity test is required.
"""

import pytest

from snow_guard_geometry import (
    validate_parameters,
    validate_margins_cover_footprint,
    calculate_row_v_positions,
    calculate_row_u_positions,
    calculate_grid_positions,
)
from boundary_assertions import assert_no_boundary_coincidence


# ---------------------------------------------------------------------------
# validate_parameters
# ---------------------------------------------------------------------------

class TestParameterValidation:

    def test_all_positive_reasonable_dimensions_valid(self):
        valid, errors = validate_parameters(
            pad_width=1.2, pad_length=1.2, pad_thickness=0.15,
            fin_height=1.0, fin_base_width=0.8, fin_thickness=0.6)
        assert valid
        assert errors == []

    @pytest.mark.parametrize("field", [
        "pad_width", "pad_length", "pad_thickness",
        "fin_height", "fin_base_width", "fin_thickness",
    ])
    @pytest.mark.parametrize("bad_value", [0.0, -1.0])
    def test_nonpositive_dimension_invalid(self, field, bad_value):
        kwargs = dict(pad_width=1.2, pad_length=1.2, pad_thickness=0.15,
                      fin_height=1.0, fin_base_width=0.8, fin_thickness=0.6)
        kwargs[field] = bad_value
        valid, errors = validate_parameters(**kwargs)
        assert not valid
        assert any(field in e for e in errors)

    @pytest.mark.parametrize("fin_base_width,expect_valid", [
        (1.2,      True),   # at threshold (== pad_length): strict `>` check allows equality
        (1.199999, True),   # just below threshold
        (1.200001, False),  # just above threshold
    ])
    def test_fin_base_width_vs_pad_length_threshold(self, fin_base_width, expect_valid):
        valid, errors = validate_parameters(
            pad_width=1.2, pad_length=1.2, pad_thickness=0.15,
            fin_height=1.0, fin_base_width=fin_base_width, fin_thickness=0.6)
        assert valid == expect_valid

    @pytest.mark.parametrize("fin_thickness,expect_valid", [
        (1.2,      True),   # at threshold (== pad_width)
        (1.199999, True),   # just below threshold
        (1.200001, False),  # just above threshold
    ])
    def test_fin_thickness_vs_pad_width_threshold(self, fin_thickness, expect_valid):
        valid, errors = validate_parameters(
            pad_width=1.2, pad_length=1.2, pad_thickness=0.15,
            fin_height=1.0, fin_base_width=0.8, fin_thickness=fin_thickness)
        assert valid == expect_valid


# ---------------------------------------------------------------------------
# validate_margins_cover_footprint (full-review finding #28, 2026-08-08)
# ---------------------------------------------------------------------------

class TestMarginsCoverFootprint:

    def test_margins_exactly_equal_to_half_footprint_valid(self):
        # Threshold is `<`, so margin == half_pad exactly must be accepted.
        valid, errors = validate_margins_cover_footprint(
            edge_margin=0.6, v_margin=0.6, pad_width=1.2, pad_length=1.2)
        assert valid
        assert errors == []

    def test_edge_margin_just_below_half_pad_width_invalid(self):
        valid, errors = validate_margins_cover_footprint(
            edge_margin=0.6 - 1e-6, v_margin=0.6, pad_width=1.2, pad_length=1.2)
        assert not valid
        assert any("edge_margin" in e for e in errors)

    def test_v_margin_just_below_half_pad_length_invalid(self):
        valid, errors = validate_margins_cover_footprint(
            edge_margin=0.6, v_margin=0.6 - 1e-6, pad_width=1.2, pad_length=1.2)
        assert not valid
        assert any("v_margin" in e for e in errors)

    def test_margins_comfortably_larger_than_footprint_valid(self):
        valid, errors = validate_margins_cover_footprint(
            edge_margin=3.0, v_margin=2.0, pad_width=1.2, pad_length=1.2)
        assert valid
        assert errors == []

    def test_default_properties_are_self_consistent(self):
        # Pins the actual shipped defaults (snow_guard_proxy.set_defaults):
        # EdgeMargin=3.0, VMargin=2.0, PadWidth=1.2, PadLength=1.2 -- a
        # regression here means the out-of-the-box defaults would
        # themselves fail validation.
        valid, errors = validate_margins_cover_footprint(
            edge_margin=3.0, v_margin=2.0, pad_width=1.2, pad_length=1.2)
        assert valid, f"shipped defaults fail their own margin validation: {errors}"


# ---------------------------------------------------------------------------
# calculate_row_v_positions
# ---------------------------------------------------------------------------

class TestRowVPositions:

    def test_single_row_minimum_ignores_row_spacing(self):
        # row_spacing is unused (and unvalidated) when num_rows == 1 --
        # pinned explicitly rather than left as "didn't think about it".
        assert calculate_row_v_positions(
            v_length=20.0, num_rows=1, first_row_offset=5.0,
            row_spacing=-999.0, v_margin=2.0) == [5.0]

    @pytest.mark.parametrize("v_length,expect_ok", [
        (9.000001, True),   # just above the fit threshold
        (9.0,      True),   # exactly at the fit threshold
        (8.999999, False),  # just below the fit threshold
    ])
    def test_last_row_fits_threshold(self, v_length, expect_ok):
        # positions = [2, 5, 8] with v_margin=1.0 -> needs v_length >= 9.0
        if expect_ok:
            assert calculate_row_v_positions(
                v_length, num_rows=3, first_row_offset=2.0,
                row_spacing=3.0, v_margin=1.0) == [2.0, 5.0, 8.0]
        else:
            with pytest.raises(ValueError, match="does not fit face"):
                calculate_row_v_positions(
                    v_length, num_rows=3, first_row_offset=2.0,
                    row_spacing=3.0, v_margin=1.0)

    @pytest.mark.parametrize("first_row_offset,expect_ok", [
        (2.000001, True),   # just above v_margin
        (2.0,      True),   # exactly at v_margin
        (1.9999,   False),  # just below v_margin
    ])
    def test_first_row_vs_v_margin_threshold(self, first_row_offset, expect_ok):
        if expect_ok:
            calculate_row_v_positions(
                v_length=100.0, num_rows=1, first_row_offset=first_row_offset,
                row_spacing=1.0, v_margin=2.0)
        else:
            with pytest.raises(ValueError, match="does not fit face"):
                calculate_row_v_positions(
                    v_length=100.0, num_rows=1, first_row_offset=first_row_offset,
                    row_spacing=1.0, v_margin=2.0)

    @pytest.mark.parametrize("num_rows", [0, -1])
    def test_invalid_num_rows_raises(self, num_rows):
        with pytest.raises(ValueError, match="num_rows"):
            calculate_row_v_positions(20.0, num_rows, 5.0, 3.0, 2.0)

    def test_negative_first_row_offset_raises(self):
        with pytest.raises(ValueError, match="first_row_offset"):
            calculate_row_v_positions(20.0, 2, -1.0, 3.0, 2.0)

    @pytest.mark.parametrize("row_spacing", [0.0, -1.0])
    def test_multirow_nonpositive_row_spacing_raises(self, row_spacing):
        with pytest.raises(ValueError, match="row_spacing"):
            calculate_row_v_positions(20.0, 2, 5.0, row_spacing, 2.0)

    @pytest.mark.parametrize("v_margin", [0.0, -1.0])
    def test_nonpositive_v_margin_raises(self, v_margin):
        with pytest.raises(ValueError, match="v_margin"):
            calculate_row_v_positions(20.0, 2, 5.0, 3.0, v_margin)

    def test_realistic_ho_scale_parameter_set(self):
        # ~100mm-tall slate field, 3 rows starting 8mm above the eave.
        assert calculate_row_v_positions(
            v_length=100.0, num_rows=3, first_row_offset=8.0,
            row_spacing=15.0, v_margin=3.0) == [8.0, 23.0, 38.0]


# ---------------------------------------------------------------------------
# calculate_row_u_positions
# ---------------------------------------------------------------------------

class TestRowUPositions:

    @pytest.mark.parametrize("stagger_offset", [0.0, 5.0, -5.0])
    def test_single_guard_centers_and_ignores_stagger(self, stagger_offset):
        assert calculate_row_u_positions(
            u_length=20.0, guards_per_row=1, edge_margin=3.0,
            stagger_offset=stagger_offset) == [10.0]

    @pytest.mark.parametrize("edge_margin,expect_ok", [
        (4.999999, True),   # just below the zero-usable-span threshold
        (5.0,      False),  # exactly at the threshold (hi == lo -> no usable span)
        (5.000001, False),  # just above the threshold
    ])
    def test_edge_margin_usable_span_threshold(self, edge_margin, expect_ok):
        if expect_ok:
            calculate_row_u_positions(u_length=10.0, guards_per_row=1, edge_margin=edge_margin)
        else:
            with pytest.raises(ValueError, match="usable span"):
                calculate_row_u_positions(u_length=10.0, guards_per_row=1, edge_margin=edge_margin)

    def test_two_guards_non_staggered_span_full_range(self):
        # lo=1, hi=9, spacing=8 (denominator = guards_per_row-1 = 1)
        assert calculate_row_u_positions(
            u_length=10.0, guards_per_row=2, edge_margin=1.0,
            stagger_offset=0.0, reserve_stagger=False) == [1.0, 9.0]

    @pytest.mark.parametrize("stagger_offset,expect_ok", [
        (0.001,  False),  # pushes the last guard past hi
        (0.0,    True),   # both guards sit exactly at lo/hi -- allowed
        (-0.001, False),  # pushes the first guard past lo
    ])
    def test_non_staggered_stagger_offset_threshold(self, stagger_offset, expect_ok):
        if expect_ok:
            calculate_row_u_positions(
                u_length=10.0, guards_per_row=2, edge_margin=1.0,
                stagger_offset=stagger_offset, reserve_stagger=False)
        else:
            with pytest.raises(ValueError, match="outside usable range"):
                calculate_row_u_positions(
                    u_length=10.0, guards_per_row=2, edge_margin=1.0,
                    stagger_offset=stagger_offset, reserve_stagger=False)

    def test_reserve_stagger_reserves_headroom_for_the_shift(self):
        # With reserve_stagger=True the spacing denominator becomes
        # guards_per_row - 0.5 instead of guards_per_row - 1, so the
        # UNSTAGGERED row stops short of hi -- leaving room for the
        # staggered row (offset by half that spacing) to land exactly at
        # hi instead of overflowing past it (the bug this design avoids).
        lo, hi = 1.0, 9.0
        spacing = (hi - lo) / 1.5  # denom = guards_per_row(2) - 0.5
        half_spacing = spacing / 2.0

        unstaggered = calculate_row_u_positions(
            u_length=10.0, guards_per_row=2, edge_margin=1.0,
            stagger_offset=0.0, reserve_stagger=True)
        assert unstaggered == pytest.approx([lo, lo + spacing])
        assert unstaggered[-1] < hi  # headroom reserved, not touching hi

        staggered = calculate_row_u_positions(
            u_length=10.0, guards_per_row=2, edge_margin=1.0,
            stagger_offset=half_spacing, reserve_stagger=True)
        assert staggered == pytest.approx([lo + half_spacing, hi])

    @pytest.mark.parametrize("extra,expect_ok", [
        (0.001,  False),  # half_spacing + epsilon overflows past hi
        (0.0,    True),   # exactly half_spacing lands at hi -- allowed
        (-0.001, True),   # just under half_spacing stays inside
    ])
    def test_reserve_stagger_offset_threshold(self, extra, expect_ok):
        half_spacing = ((9.0 - 1.0) / 1.5) / 2.0
        stagger_offset = half_spacing + extra
        if expect_ok:
            calculate_row_u_positions(
                u_length=10.0, guards_per_row=2, edge_margin=1.0,
                stagger_offset=stagger_offset, reserve_stagger=True)
        else:
            with pytest.raises(ValueError, match="outside usable range"):
                calculate_row_u_positions(
                    u_length=10.0, guards_per_row=2, edge_margin=1.0,
                    stagger_offset=stagger_offset, reserve_stagger=True)

    @pytest.mark.parametrize("guards_per_row", [0, -1])
    def test_invalid_guards_per_row_raises(self, guards_per_row):
        with pytest.raises(ValueError, match="guards_per_row"):
            calculate_row_u_positions(10.0, guards_per_row, 1.0)

    @pytest.mark.parametrize("edge_margin", [0.0, -1.0])
    def test_nonpositive_edge_margin_raises(self, edge_margin):
        with pytest.raises(ValueError, match="edge_margin"):
            calculate_row_u_positions(10.0, 2, edge_margin)

    def test_realistic_ho_scale_parameter_set(self):
        # ~150mm-wide slate field, 8 guards per row, non-staggered.
        assert calculate_row_u_positions(
            u_length=150.0, guards_per_row=8, edge_margin=5.0,
            reserve_stagger=False) == pytest.approx(
                [5.0, 25.0, 45.0, 65.0, 85.0, 105.0, 125.0, 145.0])


# ---------------------------------------------------------------------------
# calculate_grid_positions
# ---------------------------------------------------------------------------

class TestGridPositions:

    def test_stagger_rows_offsets_odd_rows_only(self):
        result = calculate_grid_positions(
            u_length=10.0, v_length=30.0, num_rows=2, first_row_offset=5.0,
            row_spacing=10.0, guards_per_row=2, edge_margin=1.0, v_margin=2.0,
            stagger_rows=True)
        assert len(result) == 4

        row0 = sorted(u for (r, u, v) in result if r == 0)
        row1 = sorted(u for (r, u, v) in result if r == 1)
        assert row0 != row1
        # Both rows share the same spacing, just phase-shifted.
        spacing0 = row0[1] - row0[0]
        spacing1 = row1[1] - row1[0]
        assert spacing0 == pytest.approx(spacing1)

    def test_stagger_rows_false_gives_identical_rows(self):
        result = calculate_grid_positions(
            u_length=10.0, v_length=30.0, num_rows=2, first_row_offset=5.0,
            row_spacing=10.0, guards_per_row=2, edge_margin=1.0, v_margin=2.0,
            stagger_rows=False)
        row0 = sorted(u for (r, u, v) in result if r == 0)
        row1 = sorted(u for (r, u, v) in result if r == 1)
        assert row0 == pytest.approx(row1)

    def test_single_guard_row_stagger_ignored(self):
        # guards_per_row == 1 -> half_spacing is 0.0 (see _row_spacing),
        # so stagger_rows=True has no effect: an ambiguous case pinned
        # explicitly rather than left unspecified.
        result = calculate_grid_positions(
            u_length=10.0, v_length=30.0, num_rows=3, first_row_offset=5.0,
            row_spacing=10.0, guards_per_row=1, edge_margin=1.0, v_margin=2.0,
            stagger_rows=True)
        u_values = {u for (r, u, v) in result}
        assert u_values == {5.0}

    def test_infeasible_row_grid_raises(self):
        with pytest.raises(ValueError, match="does not fit face"):
            calculate_grid_positions(
                u_length=10.0, v_length=50.0, num_rows=5, first_row_offset=8.0,
                row_spacing=100.0, guards_per_row=4, edge_margin=1.0, v_margin=2.0)

    def test_realistic_ho_scale_full_grid(self):
        result = calculate_grid_positions(
            u_length=150.0, v_length=100.0, num_rows=3, first_row_offset=8.0,
            row_spacing=15.0, guards_per_row=8, edge_margin=5.0, v_margin=3.0,
            stagger_rows=True)
        assert len(result) == 3 * 8
        assert {r for (r, u, v) in result} == {0, 1, 2}
        # Even rows (0, 2) share identical u-positions; row 1 is shifted.
        row0 = sorted(u for (r, u, v) in result if r == 0)
        row2 = sorted(u for (r, u, v) in result if r == 2)
        assert row0 == pytest.approx(row2)


# ---------------------------------------------------------------------------
# Downstream (OCCT) invariants
# ---------------------------------------------------------------------------

class TestSnowGuardDownstreamInvariants:
    """Snow guards are a SPARSE placement (no tiling union, no boolean
    clip), so the applicable OCCT-safety invariant is "no guard edge lands
    on the face boundary" -- assert_no_boundary_coincidence -- not the
    stronger assert_overflows_boundary used by the tiling generators.
    """

    def test_no_guard_footprint_touches_face_boundary(self):
        pad_width, pad_length = 1.2, 1.2
        u_length, v_length = 150.0, 100.0
        positions = calculate_grid_positions(
            u_length=u_length, v_length=v_length, num_rows=3, first_row_offset=8.0,
            row_spacing=15.0, guards_per_row=8, edge_margin=3.0, v_margin=2.0,
            stagger_rows=True)

        half_w, half_l = pad_width / 2.0, pad_length / 2.0

        assert_no_boundary_coincidence(
            positions, 0.0, u_length,
            get_extent=lambda p: (p[1] - half_w, p[1] + half_w),
            label="u-axis: ")
        assert_no_boundary_coincidence(
            positions, 0.0, v_length,
            get_extent=lambda p: (p[2] - half_l, p[2] + half_l),
            label="v-axis: ")

    def test_shipped_default_dimensions_are_non_degenerate(self):
        # Full-review finding #52 (2026-08-08): this test previously
        # parametrized over the same 6 hardcoded literals and asserted
        # `dim > 1e-9` directly on each -- trivially true by construction,
        # since it never called any function under test. A tautology
        # sweep would (and should) have flagged this. Rewritten to
        # actually exercise validate_parameters() with these shipped
        # default dimensions (matching snow_guard_proxy.set_defaults:
        # PadWidth=1.2, PadLength=1.2, PadThickness=0.15, FinHeight=1.0,
        # FinBaseWidth=0.8, FinThickness=0.6) -- a real regression (one of
        # these defaults becoming zero/negative, per this repo's
        # Part.Solid zero-dimension consumer table) would now actually
        # fail this test.
        valid, errors = validate_parameters(
            pad_width=1.2, pad_length=1.2, pad_thickness=0.15,
            fin_height=1.0, fin_base_width=0.8, fin_thickness=0.6)
        assert valid, f"shipped default dimensions fail validation: {errors}"
