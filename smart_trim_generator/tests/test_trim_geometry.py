"""
Tests for pure-Python logic in trim_geometry.py.

Functions that require FreeCAD (create_*_profile, compute_miter_bisector,
detect_corners, generate_trim_for_face, etc.) are not covered here — they
need a live FreeCAD environment.
"""

import pytest
from trim_geometry import Corner, CornerType, classify_corner, filter_corners_for_trim


def _make_corner(angle: float, corner_type: CornerType) -> Corner:
    """Build a Corner with dummy edges (not accessed by pure-Python functions)."""
    return Corner(
        position=(0.0, 0.0, 0.0),
        corner_type=corner_type,
        angle=angle,
        edge_before=None,
        edge_after=None,
    )


# ---------------------------------------------------------------------------
# CornerType enum
# ---------------------------------------------------------------------------

class TestCornerType:
    def test_enum_values(self):
        assert CornerType.EXTERNAL.value == "external"
        assert CornerType.INTERNAL.value == "internal"
        assert CornerType.STRAIGHT.value == "straight"

    def test_enum_identity(self):
        assert CornerType.EXTERNAL is not CornerType.INTERNAL
        assert CornerType.INTERNAL is not CornerType.STRAIGHT


# ---------------------------------------------------------------------------
# classify_corner
# ---------------------------------------------------------------------------

class TestClassifyCorner:
    def test_right_angle_is_external(self):
        assert classify_corner(90.0) == CornerType.EXTERNAL

    def test_acute_is_external(self):
        assert classify_corner(45.0) == CornerType.EXTERNAL

    def test_just_below_180_is_external(self):
        assert classify_corner(170.0) == CornerType.EXTERNAL

    def test_straight_at_180(self):
        assert classify_corner(180.0) == CornerType.STRAIGHT

    def test_straight_within_default_tolerance(self):
        assert classify_corner(176.0) == CornerType.STRAIGHT   # 180 - 4 < 5
        assert classify_corner(184.0) == CornerType.STRAIGHT   # 180 + 4 < 5

    def test_straight_at_tolerance_boundary(self):
        # condition is strict <, so exactly at boundary is NOT straight
        assert classify_corner(175.0) == CornerType.EXTERNAL   # |175-180|=5.0, not < 5.0
        assert classify_corner(185.0) == CornerType.INTERNAL   # |185-180|=5.0, not < 5.0
        # just inside boundary IS straight
        assert classify_corner(175.1) == CornerType.STRAIGHT   # |175.1-180|=4.9 < 5.0
        assert classify_corner(184.9) == CornerType.STRAIGHT   # |184.9-180|=4.9 < 5.0

    def test_obtuse_above_180_is_internal(self):
        assert classify_corner(270.0) == CornerType.INTERNAL

    def test_just_above_180_plus_tolerance_is_internal(self):
        assert classify_corner(185.1) == CornerType.INTERNAL

    def test_custom_tolerance_widens_straight_zone(self):
        # 170° is external with default tolerance=5, but straight with tolerance=15
        assert classify_corner(170.0, tolerance=5.0) == CornerType.EXTERNAL
        assert classify_corner(170.0, tolerance=15.0) == CornerType.STRAIGHT

    def test_custom_tolerance_zero(self):
        # With tolerance=0.0 the condition abs(angle-180) < 0 is never true,
        # so STRAIGHT is unreachable — even exactly 180° falls through to INTERNAL.
        assert classify_corner(180.0, tolerance=0.0) == CornerType.INTERNAL
        assert classify_corner(179.9, tolerance=0.0) == CornerType.EXTERNAL
        assert classify_corner(180.1, tolerance=0.0) == CornerType.INTERNAL


# ---------------------------------------------------------------------------
# Corner dataclass and miter_angle
# ---------------------------------------------------------------------------

class TestCorner:
    def test_construction(self):
        c = _make_corner(90.0, CornerType.EXTERNAL)
        assert c.position == (0.0, 0.0, 0.0)
        assert c.corner_type == CornerType.EXTERNAL
        assert c.angle == 90.0
        assert c.edge_before is None
        assert c.edge_after is None

    def test_miter_angle_right_angle(self):
        c = _make_corner(90.0, CornerType.EXTERNAL)
        assert c.miter_angle() == 45.0

    def test_miter_angle_straight(self):
        c = _make_corner(180.0, CornerType.STRAIGHT)
        assert c.miter_angle() == 90.0

    def test_miter_angle_acute(self):
        c = _make_corner(60.0, CornerType.EXTERNAL)
        assert c.miter_angle() == 30.0

    def test_miter_angle_internal(self):
        c = _make_corner(270.0, CornerType.INTERNAL)
        assert c.miter_angle() == 135.0

    def test_miter_angle_is_half_of_interior_angle(self):
        for angle in (30.0, 45.0, 60.0, 90.0, 120.0, 150.0, 210.0, 270.0):
            c = _make_corner(angle, CornerType.EXTERNAL)
            assert c.miter_angle() == angle / 2.0


# ---------------------------------------------------------------------------
# filter_corners_for_trim
# ---------------------------------------------------------------------------

class TestFilterCornersForTrim:
    def _corners(self):
        return [
            _make_corner(90.0,  CornerType.EXTERNAL),
            _make_corner(180.0, CornerType.STRAIGHT),
            _make_corner(270.0, CornerType.INTERNAL),
            _make_corner(88.0,  CornerType.EXTERNAL),
            _make_corner(182.0, CornerType.STRAIGHT),
        ]

    def test_excludes_straight_by_default(self):
        result = filter_corners_for_trim(self._corners())
        types = [c.corner_type for c in result]
        assert CornerType.STRAIGHT not in types

    def test_keeps_external_and_internal(self):
        result = filter_corners_for_trim(self._corners())
        assert len(result) == 3  # 2 external + 1 internal
        assert sum(1 for c in result if c.corner_type == CornerType.EXTERNAL) == 2
        assert sum(1 for c in result if c.corner_type == CornerType.INTERNAL) == 1

    def test_include_straight_returns_all(self):
        corners = self._corners()
        result = filter_corners_for_trim(corners, include_straight=True)
        assert result is corners  # same list, no copy

    def test_empty_input(self):
        assert filter_corners_for_trim([]) == []
        assert filter_corners_for_trim([], include_straight=True) == []

    def test_all_straight_returns_empty(self):
        corners = [_make_corner(180.0, CornerType.STRAIGHT) for _ in range(4)]
        assert filter_corners_for_trim(corners) == []

    def test_all_external_returns_all(self):
        corners = [_make_corner(90.0, CornerType.EXTERNAL) for _ in range(3)]
        result = filter_corners_for_trim(corners)
        assert len(result) == 3

    def test_single_internal_corner(self):
        corners = [_make_corner(270.0, CornerType.INTERNAL)]
        result = filter_corners_for_trim(corners)
        assert len(result) == 1
        assert result[0].corner_type == CornerType.INTERNAL
