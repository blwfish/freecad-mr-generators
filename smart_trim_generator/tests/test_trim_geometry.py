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


class TestClassifyCornerAngleThresholds:
    """Threshold-boundary tests for classify_corner().

    classify_corner uses `abs(angle - 180.0) < tolerance` for STRAIGHT, then
    `angle < 180` for EXTERNAL, else INTERNAL.  The boundary is at exactly
    `180 ± tolerance` — at those values the strict-< comparison flips the
    classification.  These tests pin the contract.

    Additional cases pulled from the audit:
      - tolerance=0 → STRAIGHT is unreachable (no angle satisfies `abs(...) < 0`)
      - non-default tolerance values still respect strict-< boundary
    """

    @pytest.mark.parametrize('angle,expected', [
        # Default tolerance = 5°.  STRAIGHT zone is (175, 185) exclusive.
        (174.999, CornerType.EXTERNAL),
        (175.0,   CornerType.EXTERNAL),   # exactly at boundary — flip
        (175.001, CornerType.STRAIGHT),
        (180.0,   CornerType.STRAIGHT),
        (184.999, CornerType.STRAIGHT),
        (185.0,   CornerType.INTERNAL),   # exactly at boundary — flip
        (185.001, CornerType.INTERNAL),
        # Pure external / internal far from STRAIGHT zone
        (0.001,   CornerType.EXTERNAL),
        (90.0,    CornerType.EXTERNAL),
        (270.0,   CornerType.INTERNAL),
        (359.999, CornerType.INTERNAL),
    ])
    def test_default_tolerance_boundaries(self, angle, expected):
        assert classify_corner(angle) == expected

    @pytest.mark.parametrize('angle,tolerance,expected', [
        (170.0, 10.0, CornerType.EXTERNAL),     # exactly at boundary (170 = 180-10)
        (170.001, 10.0, CornerType.STRAIGHT),
        (190.0, 10.0, CornerType.INTERNAL),     # exactly at boundary (190 = 180+10)
        (189.999, 10.0, CornerType.STRAIGHT),
        # tolerance=1 — STRAIGHT is a very narrow window
        (179.0, 1.0, CornerType.EXTERNAL),
        (179.001, 1.0, CornerType.STRAIGHT),
        (180.999, 1.0, CornerType.STRAIGHT),
        (181.0, 1.0, CornerType.INTERNAL),
    ])
    def test_custom_tolerance_boundaries(self, angle, tolerance, expected):
        assert classify_corner(angle, tolerance=tolerance) == expected

    def test_zero_tolerance_makes_straight_unreachable(self):
        """With tolerance=0, no angle satisfies abs(a-180) < 0 — STRAIGHT
        becomes unreachable.  An angle of exactly 180 falls through the
        first guard (0 < 0 is False), then through `elif angle < 180`
        (180 < 180 is False), and ends in the INTERNAL else-branch.

        That's almost certainly NOT what callers expect from tolerance=0 —
        but it IS the contract.  Pinning it here makes any future change
        to the strict-< vs <= choice visible.
        """
        assert classify_corner(180.0, tolerance=0.0) == CornerType.INTERNAL
        assert classify_corner(179.9999, tolerance=0.0) == CornerType.EXTERNAL
        assert classify_corner(180.0001, tolerance=0.0) == CornerType.INTERNAL
