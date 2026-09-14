"""Tests for shared/face_geometry.py's pure math -- compute_face_axes plus
the corner-seam-gap widen-selection helpers (select_widen_edge,
widen_offset_sign). No FreeCAD import needed; these are plain-Python.
"""

import pytest

from face_geometry import compute_face_axes, select_widen_edge, widen_offset_sign


class TestComputeFaceAxes:
    def test_vertical_wall_face_x_wider_than_z(self):
        axes = compute_face_axes(10.0, 0.0, 5.0, (0.0, -1.0, 0.0))
        assert axes['u_axis'] == 'x'
        assert axes['v_axis'] == 'z'
        assert axes['u_length'] == 10.0
        assert axes['v_length'] == 5.0
        assert axes['is_horizontal'] is False

    def test_horizontal_face_raises_with_no_extent(self):
        with pytest.raises(ValueError):
            compute_face_axes(0.0, 0.0, 0.0, (0.0, 0.0, 1.0))


class TestSelectWidenEdge:
    def test_left_selects_minimum_u(self):
        candidates = [('a', 5.0), ('b', 0.0), ('c', 3.0)]
        assert select_widen_edge(candidates, 'left') == 'b'

    def test_right_selects_maximum_u(self):
        candidates = [('a', 5.0), ('b', 0.0), ('c', 3.0)]
        assert select_widen_edge(candidates, 'right') == 'a'

    def test_single_candidate_either_side(self):
        candidates = [('only', 2.5)]
        assert select_widen_edge(candidates, 'left') == 'only'
        assert select_widen_edge(candidates, 'right') == 'only'

    def test_empty_candidates_raises(self):
        with pytest.raises(ValueError, match="No V-parallel"):
            select_widen_edge([], 'left')

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError, match="side must be"):
            select_widen_edge([('a', 0.0)], 'up')

    def test_tie_exactly_at_tolerance_boundary_is_ambiguous(self):
        # Two candidates 0.02 apart tie when tol=0.02 (inclusive <=).
        candidates = [('a', 0.0), ('b', 0.02)]
        with pytest.raises(ValueError, match="Ambiguous"):
            select_widen_edge(candidates, 'left', tol=0.02)

    def test_just_below_tolerance_still_ambiguous(self):
        candidates = [('a', 0.0), ('b', 0.019999)]
        with pytest.raises(ValueError, match="Ambiguous"):
            select_widen_edge(candidates, 'left', tol=0.02)

    def test_just_above_tolerance_is_unambiguous(self):
        candidates = [('a', 0.0), ('b', 0.020001)]
        assert select_widen_edge(candidates, 'left', tol=0.02) == 'a'

    def test_bay_edge_flush_with_real_corner_is_ambiguous_not_guessed(self):
        """The specific real-world case this rule exists for: a door/window
        bay notch whose own edge happens to sit at the same u-extreme as
        the wall's real corner edge. Must raise, not silently pick one."""
        candidates = [
            ('real_corner_edge', 0.0),
            ('bay_notch_edge', 0.0),
            ('interior_edge', 4.0),
        ]
        with pytest.raises(ValueError, match="Ambiguous"):
            select_widen_edge(candidates, 'left')

    def test_three_way_tie_reported_in_error(self):
        candidates = [('a', 0.0), ('b', 0.0), ('c', 0.0)]
        with pytest.raises(ValueError, match="3 V-parallel"):
            select_widen_edge(candidates, 'left')

    def test_default_tolerance_is_tight(self):
        """Default tol=1e-6 should NOT treat visually-distinct edges (a
        few mm apart) as tied -- only near-exact float coincidence."""
        candidates = [('a', 0.0), ('b', 0.5)]
        assert select_widen_edge(candidates, 'left') == 'a'


class TestWidenOffsetSign:
    def test_left_is_negative(self):
        assert widen_offset_sign('left') == -1.0

    def test_right_is_positive(self):
        assert widen_offset_sign('right') == 1.0

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError, match="side must be"):
            widen_offset_sign('center')

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="side must be"):
            widen_offset_sign('')

    def test_case_sensitive(self):
        with pytest.raises(ValueError, match="side must be"):
            widen_offset_sign('Left')
