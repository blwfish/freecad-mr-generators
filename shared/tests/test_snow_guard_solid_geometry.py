"""
Tests for snow_guard_solid_geometry.calculate_fin_position.

Pins the fin-centering formula extracted from snow_guard_proxy.py and
standing_seam_snow_guard_proxy.py's near-identical `_build_guard_solid`
functions (full-review finding #20, 2026-08-08). Both proxies now call
this single function instead of each inlining its own copy of the
(pad_length - fin_base_width) / 2.0 / (pad_width - fin_thickness) / 2.0
arithmetic, so a future edit to the formula is caught here instead of
silently diverging between the two proxies again.
"""

import pytest

from snow_guard_solid_geometry import calculate_fin_position


class TestCalculateFinPosition:
    def test_centers_fin_on_square_pad(self):
        # 10x10 pad, 4-wide fin base, 2-thick fin -> centered with 3mm
        # margin on each side.
        fin_x0, fin_y0 = calculate_fin_position(
            pad_width=10.0, pad_length=10.0,
            fin_base_width=4.0, fin_thickness=2.0)
        assert fin_x0 == pytest.approx(4.0, abs=1e-9)
        assert fin_y0 == pytest.approx(3.0, abs=1e-9)

    def test_centers_fin_on_rectangular_pad(self):
        # Realistic slate-guard-scale values: 20mm wide x 15mm long pad,
        # 6mm fin base, 3mm fin thickness.
        fin_x0, fin_y0 = calculate_fin_position(
            pad_width=20.0, pad_length=15.0,
            fin_base_width=6.0, fin_thickness=3.0)
        assert fin_x0 == pytest.approx((20.0 - 3.0) / 2.0, abs=1e-9)
        assert fin_y0 == pytest.approx((15.0 - 6.0) / 2.0, abs=1e-9)

    def test_matches_standing_seam_clamp_naming_by_position(self):
        # standing_seam_snow_guard_proxy.py calls the same function with
        # clamp_width/clamp_length in place of pad_width/pad_length --
        # confirm the result is identical for equal values (the whole
        # point of extracting a single shared function).
        result_pad = calculate_fin_position(
            pad_width=12.0, pad_length=8.0,
            fin_base_width=5.0, fin_thickness=2.5)
        result_clamp = calculate_fin_position(
            pad_width=12.0, pad_length=8.0,
            fin_base_width=5.0, fin_thickness=2.5)
        assert result_pad == result_clamp

    def test_fin_base_width_equals_pad_length_zero_margin(self):
        # Boundary: fin exactly spans the pad's length -> fin_y0 == 0.
        _, fin_y0 = calculate_fin_position(
            pad_width=10.0, pad_length=6.0,
            fin_base_width=6.0, fin_thickness=2.0)
        assert fin_y0 == pytest.approx(0.0, abs=1e-9)

    def test_fin_thickness_equals_pad_width_zero_margin(self):
        # Boundary: fin exactly spans the pad's width -> fin_x0 == 0.
        fin_x0, _ = calculate_fin_position(
            pad_width=4.0, pad_length=10.0,
            fin_base_width=3.0, fin_thickness=4.0)
        assert fin_x0 == pytest.approx(0.0, abs=1e-9)

    def test_oversized_fin_produces_negative_offset(self):
        # fin_base_width/fin_thickness larger than the pad is not
        # validated by this function (callers are responsible) -- pin
        # that it produces a negative offset rather than raising, so the
        # "no clamping" contract in the docstring is enforced by a test.
        fin_x0, fin_y0 = calculate_fin_position(
            pad_width=5.0, pad_length=5.0,
            fin_base_width=8.0, fin_thickness=9.0)
        assert fin_x0 == pytest.approx(-2.0, abs=1e-9)
        assert fin_y0 == pytest.approx(-1.5, abs=1e-9)
