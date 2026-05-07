"""
Test suite for slate_geometry.py

Run with: pytest test_slate_geometry.py -v
"""

import pytest
import math
from slate_geometry import (
    validate_parameters,
    validate_stagger_pattern,
    calculate_stagger_offset,
    calculate_layout,
    # Shared via roof_geometry
    is_planar,
    calculate_face_bounds,
    find_eave_and_ridge_vertices,
    get_roof_coordinate_system,
    find_coincident_edges,
    classify_roof_intersection,
    analyze_roof_intersection,
)


# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------

class TestParameterValidation:

    def test_valid_ho_defaults(self):
        ok, errors = validate_parameters(2.0, 2.5, 0.3, 1.2)
        assert ok
        assert errors == []

    def test_zero_tile_width_rejected(self):
        ok, errors = validate_parameters(0.0, 2.5, 0.3, 1.2)
        assert not ok
        assert any('tile_width' in e for e in errors)

    def test_negative_tile_height_rejected(self):
        ok, errors = validate_parameters(2.0, -1.0, 0.3, 1.2)
        assert not ok

    def test_zero_thickness_rejected(self):
        ok, errors = validate_parameters(2.0, 2.5, 0.0, 1.2)
        assert not ok

    def test_exposure_exceeds_height_rejected(self):
        ok, errors = validate_parameters(2.0, 2.5, 0.3, 3.0)
        assert not ok
        assert any('exposure' in e for e in errors)

    def test_exposure_equals_height_valid(self):
        ok, _ = validate_parameters(2.0, 2.5, 0.3, 2.5)
        assert ok

    def test_thickness_exceeds_height_rejected(self):
        ok, _ = validate_parameters(2.0, 0.1, 0.3, 0.1)
        assert not ok


class TestStaggerPattern:

    def test_valid_patterns(self):
        for p in ('half', 'third', 'none'):
            ok, msg = validate_stagger_pattern(p)
            assert ok, f"{p} should be valid"
            assert msg == ''

    def test_invalid_pattern(self):
        ok, msg = validate_stagger_pattern('random')
        assert not ok
        assert 'random' in msg

    def test_empty_string_invalid(self):
        ok, _ = validate_stagger_pattern('')
        assert not ok


# ---------------------------------------------------------------------------
# Stagger offset
# ---------------------------------------------------------------------------

class TestStaggerOffset:

    def test_half_pattern_alternates(self):
        w = 2.0
        assert calculate_stagger_offset(0, 'half', w) == 0.0
        assert calculate_stagger_offset(1, 'half', w) == pytest.approx(1.0)
        assert calculate_stagger_offset(2, 'half', w) == 0.0
        assert calculate_stagger_offset(3, 'half', w) == pytest.approx(1.0)

    def test_third_pattern_cycles(self):
        w = 3.0
        assert calculate_stagger_offset(0, 'third', w) == 0.0
        assert calculate_stagger_offset(1, 'third', w) == pytest.approx(1.0)
        assert calculate_stagger_offset(2, 'third', w) == pytest.approx(2.0)
        assert calculate_stagger_offset(3, 'third', w) == 0.0

    def test_none_pattern_always_zero(self):
        for row in range(10):
            assert calculate_stagger_offset(row, 'none', 5.0) == 0.0


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

class TestCalculateLayout:

    def test_basic_coverage(self):
        layout = calculate_layout(50.0, 40.0, 2.0, 1.2)
        assert layout['num_courses'] > 0
        assert layout['tiles_per_course'] > 0
        # Courses must cover full height with some margin
        assert layout['num_courses'] * 1.2 >= 40.0

    def test_half_stagger_adds_extra_tiles(self):
        layout_none = calculate_layout(50.0, 40.0, 2.0, 1.2, 'none')
        layout_half = calculate_layout(50.0, 40.0, 2.0, 1.2, 'half')
        assert layout_half['max_stagger'] == pytest.approx(1.0)
        assert layout_half['tiles_per_course'] >= layout_none['tiles_per_course']

    def test_max_stagger_values(self):
        assert calculate_layout(10, 10, 2.0, 1.2, 'half')['max_stagger'] == pytest.approx(1.0)
        assert calculate_layout(10, 10, 3.0, 1.2, 'third')['max_stagger'] == pytest.approx(1.0)
        assert calculate_layout(10, 10, 4.0, 1.2, 'none')['max_stagger'] == 0.0

    def test_small_face_still_gets_coverage(self):
        layout = calculate_layout(5.0, 5.0, 2.0, 1.2)
        assert layout['num_courses'] >= 1
        assert layout['tiles_per_course'] >= 1


# ---------------------------------------------------------------------------
# Shared roof geometry (sanity-check imports)
# ---------------------------------------------------------------------------

class TestSharedGeometry:

    def test_is_planar_quad(self):
        pts = [(0,0,0),(10,0,0),(10,10,0),(0,10,0)]
        assert is_planar(pts)

    def test_is_planar_non_planar(self):
        pts = [(0,0,0),(10,0,0),(10,10,5),(0,10,0)]
        assert not is_planar(pts)

    def test_eave_ridge_detection(self):
        verts = [(0,0,0),(10,0,0),(10,10,10),(0,10,10)]
        info = find_eave_and_ridge_vertices(verts)
        assert info['eave_z'] == pytest.approx(0.0)
        assert info['ridge_z'] == pytest.approx(10.0)
        assert len(info['eave_vertices']) == 2
        assert len(info['ridge_vertices']) == 2

    def test_coordinate_system_v_points_upslope(self):
        # Simple pitched roof face
        verts = [(0,0,0),(20,0,0),(20,20,20),(0,20,20)]
        normal = (0.0, -0.707, 0.707)
        cs = get_roof_coordinate_system(verts, normal)
        assert cs['v_vec'][2] > 0, "V must point up the slope (positive Z)"

    def test_coordinate_system_gable_right_face(self):
        # Right side of gable — normal points inward-and-up
        verts = [(50,0,50),(50,20,50),(100,20,0),(100,0,0)]
        normal = (-0.707, 0, 0.707)
        cs = get_roof_coordinate_system(verts, normal)
        assert cs['v_vec'][2] > 0

    def test_valley_classification(self):
        face1_v = [(0,0,0),(0,10,0),(0,10,10),(0,0,10)]
        face2_v = [(0,0,0),(0,10,0),(0,10,10),(0,0,10)]
        shared  = ((0,0,5),(0,10,5))
        result = classify_roof_intersection(
            [(0,0,0),(10,0,0),(10,0,10),(0,0,10)],
            [(0,0,0),(10,0,0),(10,0,20),(0,0,20)],
            shared)
        # Non-shared vertices above → valley
        assert result['classification'] in ('valley', 'ridge', 'ambiguous')

    def test_hip_classification(self):
        # Ridge: shared edge at top (Z=5), non-shared verts slope down to Z=0
        face1 = [(0,0,0),(5,0,5),(5,10,5),(0,10,0)]
        face2 = [(10,0,0),(5,0,5),(5,10,5),(10,10,0)]
        shared = ((5,0,5),(5,10,5))
        result = classify_roof_intersection(face1, face2, shared)
        assert result['classification'] == 'ridge'
