"""
Tests for station_sign_geometry.py.

station_sign_generator was, before 2026-08-08 (full-review finding #29),
the one generator in this repo with no *_geometry.py module and no tests/
directory at all -- its sign/border/text sizing math and disconnected-
glyph-island bbox-containment logic had zero verification of any kind.

No TestStationSignProxyParity class here: station_sign_proxy.py's
_wires_to_faces() and generate_sign_shape() call
group_wire_bboxes_into_islands()/calculate_sign_layout() directly and
inline no duplicate copy of this arithmetic. There is exactly one source
of truth.
"""

import pytest

from station_sign_geometry import (
    bbox_contains,
    group_wire_bboxes_into_islands,
    calculate_sign_layout,
)


# ---------------------------------------------------------------------------
# bbox_contains
# ---------------------------------------------------------------------------

class TestBboxContains:

    def test_clearly_contained(self):
        outer = (0.0, 10.0, 0.0, 10.0)
        inner = (2.0, 8.0, 2.0, 8.0)
        assert bbox_contains(outer, inner)

    def test_identical_boxes_contained(self):
        box = (0.0, 10.0, 0.0, 10.0)
        assert bbox_contains(box, box)

    def test_clearly_disjoint_not_contained(self):
        outer = (0.0, 10.0, 0.0, 10.0)
        disjoint = (20.0, 30.0, 20.0, 30.0)
        assert not bbox_contains(outer, disjoint)

    def test_partial_overlap_not_contained(self):
        outer = (0.0, 10.0, 0.0, 10.0)
        partial = (5.0, 15.0, 5.0, 15.0)  # extends past outer's XMax/YMax
        assert not bbox_contains(outer, partial)

    @pytest.mark.parametrize("overshoot,expect_contained", [
        (-1e-7, True),   # within default eps (1e-6): still counts as contained
        (1e-6, True),    # exactly at eps: `<=` boundary, inclusive
        (1e-5, False),   # clearly beyond eps
    ])
    def test_eps_tolerance_boundary(self, overshoot, expect_contained):
        outer = (0.0, 10.0, 0.0, 10.0)
        inner = (0.0, 10.0 + overshoot, 0.0, 10.0)  # XMax overshoots outer's XMax
        assert bbox_contains(outer, inner) == expect_contained

    def test_custom_eps(self):
        outer = (0.0, 10.0, 0.0, 10.0)
        inner = (0.0, 10.05, 0.0, 10.0)
        assert not bbox_contains(outer, inner, eps=1e-6)
        assert bbox_contains(outer, inner, eps=0.1)


# ---------------------------------------------------------------------------
# group_wire_bboxes_into_islands
# ---------------------------------------------------------------------------

class TestGroupWireBboxesIntoIslands:

    def test_empty_input(self):
        assert group_wire_bboxes_into_islands([]) == []

    def test_single_bbox(self):
        assert group_wire_bboxes_into_islands([(0.0, 1.0, 0.0, 1.0)]) == [[0]]

    def test_two_disjoint_islands_like_i_stem_and_dot(self):
        # 'i': a tall thin stem, and a separate dot well above it -- their
        # bboxes don't overlap at all, so both are independent outer wires
        # (2 separate faces), not a hole relationship.
        stem = (0.0, 1.0, 0.0, 5.0)
        dot = (0.0, 1.0, 6.0, 7.0)
        groups = group_wire_bboxes_into_islands([stem, dot])
        assert sorted(groups) == [[0], [1]]

    def test_hole_like_letter_o(self):
        # 'o': an outer ring and a fully-nested inner ring -- the inner
        # ring's bbox is contained within the outer ring's bbox, so they
        # must group together (Part.Face(group) then treats the inner
        # wire as a hole).
        outer_ring = (0.0, 10.0, 0.0, 10.0)
        inner_ring = (2.0, 8.0, 2.0, 8.0)
        groups = group_wire_bboxes_into_islands([outer_ring, inner_ring])
        assert len(groups) == 1
        assert set(groups[0]) == {0, 1}
        assert groups[0][0] == 0  # outer wire's index listed first

    def test_two_separate_letters_each_with_a_hole(self):
        # Two 'o'-like glyphs side by side: 4 wires total, must produce 2
        # groups (one outer+hole pair each), not cross-contaminate.
        o1_outer = (0.0, 10.0, 0.0, 10.0)
        o1_inner = (2.0, 8.0, 2.0, 8.0)
        o2_outer = (20.0, 30.0, 0.0, 10.0)
        o2_inner = (22.0, 28.0, 2.0, 8.0)
        groups = group_wire_bboxes_into_islands(
            [o1_outer, o1_inner, o2_outer, o2_inner])
        assert len(groups) == 2
        group_sets = sorted(set(g) for g in groups)
        assert group_sets == [{0, 1}, {2, 3}]

    def test_doubly_nested_treats_middle_as_outer_of_innermost(self):
        # Three concentric bboxes: outermost contains middle contains
        # innermost. is_outer only marks a bbox False if something ELSE
        # contains it -- middle is contained by outer (is_outer=False),
        # innermost is contained by both outer and middle (is_outer=
        # False). Only the outermost is a true "outer" wire, so this is
        # one single group of all three, not two nested groups -- pins
        # actual behavior for a case the algorithm doesn't try to handle
        # specially (three-level nesting isn't a real glyph shape, but
        # the function must not crash or misbehave on it).
        outer = (0.0, 30.0, 0.0, 30.0)
        middle = (5.0, 25.0, 5.0, 25.0)
        inner = (10.0, 20.0, 10.0, 20.0)
        groups = group_wire_bboxes_into_islands([outer, middle, inner])
        assert len(groups) == 1
        assert set(groups[0]) == {0, 1, 2}


# ---------------------------------------------------------------------------
# calculate_sign_layout
# ---------------------------------------------------------------------------

class TestCalculateSignLayout:

    def test_known_values(self):
        # text_xmin/text_ymin = 0 -- the common case of a font whose glyph
        # outlines already start at the local origin.
        layout = calculate_sign_layout(
            text_w=20.0, text_h=5.0, text_xmin=0.0, text_ymin=0.0,
            mat_thick=0.2, border_thick=0.5, border_gap=1.0)

        assert layout['sign_w'] == pytest.approx(2 * 0.5 + 2 * 1.0 + 20.0)  # 23.0
        assert layout['sign_h'] == pytest.approx(2 * 0.5 + 2 * 1.0 + 5.0)   # 8.0
        assert layout['bg_thickness'] == pytest.approx(0.4)
        assert layout['border_height'] == pytest.approx(0.6)
        assert layout['inner_x'] == pytest.approx(0.5)
        assert layout['inner_y'] == pytest.approx(0.5)
        assert layout['inner_w'] == pytest.approx(22.0)  # sign_w - 2*border_thick
        assert layout['inner_h'] == pytest.approx(7.0)   # sign_h - 2*border_thick
        # text centered in inner area: inner_x + (inner_w - text_w)/2 - text_xmin
        assert layout['text_x'] == pytest.approx(0.5 + (22.0 - 20.0) / 2 - 0.0)
        assert layout['text_y'] == pytest.approx(0.5 + (7.0 - 5.0) / 2 - 0.0)
        assert layout['text_z'] == pytest.approx(0.6)

    def test_nonzero_text_bbox_origin_shifts_text_position(self):
        # A font whose glyph coordinates don't start at (0, 0) -- text_x/
        # text_y must subtract text_xmin/text_ymin so the RENDERED glyph
        # (not its raw coordinate origin) ends up centered.
        layout = calculate_sign_layout(
            text_w=20.0, text_h=5.0, text_xmin=3.0, text_ymin=-1.0,
            mat_thick=0.2, border_thick=0.5, border_gap=1.0)
        assert layout['text_x'] == pytest.approx(0.5 + 1.0 - 3.0)
        assert layout['text_y'] == pytest.approx(0.5 + 1.0 - (-1.0))

    def test_zero_border_gap_is_valid(self):
        # border_gap == 0 is physically meaningful (border touches text
        # directly) -- only a NEGATIVE gap is nonsensical. Distinct
        # threshold from mat_thick/border_thick, which reject <= 0.
        layout = calculate_sign_layout(
            text_w=10.0, text_h=5.0, text_xmin=0.0, text_ymin=0.0,
            mat_thick=0.2, border_thick=0.5, border_gap=0.0)
        assert layout['sign_w'] == pytest.approx(2 * 0.5 + 10.0)

    def test_negative_border_gap_rejected(self):
        with pytest.raises(ValueError, match="border_gap"):
            calculate_sign_layout(
                text_w=10.0, text_h=5.0, text_xmin=0.0, text_ymin=0.0,
                mat_thick=0.2, border_thick=0.5, border_gap=-0.001)

    @pytest.mark.parametrize("mat_thick", [0.0, -0.1])
    def test_nonpositive_mat_thick_rejected(self, mat_thick):
        with pytest.raises(ValueError, match="mat_thick"):
            calculate_sign_layout(
                text_w=10.0, text_h=5.0, text_xmin=0.0, text_ymin=0.0,
                mat_thick=mat_thick, border_thick=0.5, border_gap=1.0)

    @pytest.mark.parametrize("border_thick", [0.0, -0.1])
    def test_nonpositive_border_thick_rejected(self, border_thick):
        with pytest.raises(ValueError, match="border_thick"):
            calculate_sign_layout(
                text_w=10.0, text_h=5.0, text_xmin=0.0, text_ymin=0.0,
                mat_thick=0.2, border_thick=border_thick, border_gap=1.0)

    @pytest.mark.parametrize("text_w,text_h", [(0.0, 5.0), (10.0, 0.0), (-1.0, 5.0)])
    def test_nonpositive_text_dimensions_rejected(self, text_w, text_h):
        with pytest.raises(ValueError):
            calculate_sign_layout(
                text_w=text_w, text_h=text_h, text_xmin=0.0, text_ymin=0.0,
                mat_thick=0.2, border_thick=0.5, border_gap=1.0)

    def test_ho_scale_real_defaults(self):
        # Pinned to this generator's own actual shipped defaults
        # (station_sign_proxy.set_defaults): MaterialThickness=0.2,
        # BorderThickness=0.5, BorderGap=1.0, plus a representative HO-
        # scale text measurement.
        layout = calculate_sign_layout(
            text_w=15.3, text_h=4.67, text_xmin=0.0, text_ymin=0.0,
            mat_thick=0.2, border_thick=0.5, border_gap=1.0)
        assert layout['sign_w'] > 0
        assert layout['sign_h'] > 0
        assert layout['inner_w'] > 0
        assert layout['inner_h'] > 0
