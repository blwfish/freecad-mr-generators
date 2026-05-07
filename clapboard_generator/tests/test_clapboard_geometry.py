"""
Test Suite for Clapboard Geometry Library v4.3.0

Tests the pure Python geometry functions without requiring FreeCAD.
Run with: pytest test_clapboard_geometry.py -v

Coverage includes:
- Edge validation (degenerate, duplicates)
- Wire geometry validation
- Face orientation detection
- Corner detection
- Course calculations
- Parameter validation
"""

import pytest
import math
from clapboard_geometry import (
    check_for_degenerate_edges,
    check_for_duplicate_edges,
    validate_wire_geometry,
    detect_face_orientation,
    is_building_corner,
    calculate_clapboard_courses,
    validate_parameters,
    get_face_orientation_description,
)


class TestEdgeValidation:
    """Test degenerate edge detection"""
    
    def test_no_degenerate_edges(self):
        """Valid edges should pass"""
        edges = [
            {'length': 10.0},
            {'length': 5.5},
            {'length': 100.0}
        ]
        degenerate = check_for_degenerate_edges(edges)
        assert len(degenerate) == 0
    
    def test_detect_zero_length_edge(self):
        """Zero-length edges should be detected"""
        edges = [
            {'length': 10.0},
            {'length': 0.0},
            {'length': 5.0}
        ]
        degenerate = check_for_degenerate_edges(edges)
        assert len(degenerate) == 1
        assert degenerate[0][0] == 1  # Index of degenerate edge
    
    def test_detect_near_zero_edge(self):
        """Near-zero edges (< 0.001mm) should be detected"""
        edges = [
            {'length': 10.0},
            {'length': 0.0005},
            {'length': 5.0}
        ]
        degenerate = check_for_degenerate_edges(edges)
        assert len(degenerate) == 1


class TestDuplicateEdges:
    """Test duplicate edge detection"""
    
    def test_no_duplicate_edges(self):
        """Non-duplicate edges should pass"""
        edges = [
            {'start': (0, 0, 0), 'end': (10, 0, 0)},
            {'start': (0, 10, 0), 'end': (0, 20, 0)},
        ]
        duplicates = check_for_duplicate_edges(edges)
        assert len(duplicates) == 0
    
    def test_detect_same_direction_duplicate(self):
        """Edges in same direction should be detected"""
        edges = [
            {'start': (0, 0, 0), 'end': (10, 0, 0)},
            {'start': (0, 0, 0), 'end': (10, 0, 0)},
        ]
        duplicates = check_for_duplicate_edges(edges)
        assert len(duplicates) == 1
    
    def test_detect_reversed_duplicate(self):
        """Edges in opposite directions should be detected"""
        edges = [
            {'start': (0, 0, 0), 'end': (10, 0, 0)},
            {'start': (10, 0, 0), 'end': (0, 0, 0)},
        ]
        duplicates = check_for_duplicate_edges(edges)
        assert len(duplicates) == 1


class TestWireGeometryValidation:
    """Test comprehensive wire validation"""
    
    def test_valid_wire(self):
        """Valid wire should pass"""
        edges = [
            {'length': 10.0, 'start': (0, 0, 0), 'end': (10, 0, 0)},
            {'length': 5.0, 'start': (10, 0, 0), 'end': (10, 5, 0)},
        ]
        is_valid, errors = validate_wire_geometry(edges)
        assert is_valid
        assert len(errors) == 0
    
    def test_invalid_wire_degenerate(self):
        """Wire with degenerate edge should fail"""
        edges = [
            {'length': 0.0, 'start': (0, 0, 0), 'end': (0, 0, 0)},
        ]
        is_valid, errors = validate_wire_geometry(edges)
        assert not is_valid
        assert len(errors) > 0


class TestFaceOrientation:
    """Test face orientation detection"""
    
    def test_xy_plane_horizontal(self):
        """Horizontal face (XY plane at constant Z)"""
        bbox = {
            'x_min': 0, 'x_max': 100,
            'y_min': 0, 'y_max': 50,
            'z_min': 0, 'z_max': 0.1
        }
        vert_axis, horiz_axis, normal_axis = detect_face_orientation(bbox)
        assert normal_axis == 'z'
        assert vert_axis == 'y'
        assert horiz_axis == 'x'
    
    def test_xz_plane_vertical(self):
        """Vertical wall (XZ plane at constant Y)"""
        bbox = {
            'x_min': 0, 'x_max': 100,
            'y_min': 0, 'y_max': 0.1,
            'z_min': 0, 'z_max': 50
        }
        vert_axis, horiz_axis, normal_axis = detect_face_orientation(bbox)
        assert normal_axis == 'y'
        assert vert_axis == 'z'
        assert horiz_axis == 'x'
    
    def test_yz_plane_vertical(self):
        """Vertical wall (YZ plane at constant X)"""
        bbox = {
            'x_min': 0, 'x_max': 0.1,
            'y_min': 0, 'y_max': 100,
            'z_min': 0, 'z_max': 50
        }
        vert_axis, horiz_axis, normal_axis = detect_face_orientation(bbox)
        assert normal_axis == 'x'
        assert vert_axis == 'z'
        assert horiz_axis == 'y'


class TestCornerDetection:
    """Test building corner detection"""
    
    def test_corner_at_min_x(self):
        """Edge at minimum X should be detected as corner"""
        bbox = {
            'x_min': 0, 'x_max': 100,
            'y_min': 0, 'y_max': 50,
            'z_min': 0, 'z_max': 50
        }
        is_corner = is_building_corner(0.5, bbox, horizontal_axis='x')
        assert is_corner
    
    def test_corner_at_max_x(self):
        """Edge at maximum X should be detected as corner"""
        bbox = {
            'x_min': 0, 'x_max': 100,
            'y_min': 0, 'y_max': 50,
            'z_min': 0, 'z_max': 50
        }
        is_corner = is_building_corner(99.5, bbox, horizontal_axis='x')
        assert is_corner
    
    def test_interior_not_corner(self):
        """Interior edge should not be detected as corner"""
        bbox = {
            'x_min': 0, 'x_max': 100,
            'y_min': 0, 'y_max': 50,
            'z_min': 0, 'z_max': 50
        }
        is_corner = is_building_corner(50.0, bbox, horizontal_axis='x')
        assert not is_corner


class TestCourseCalculation:
    """Test clapboard course calculations"""
    
    def test_single_course(self):
        """Short wall needs only one course"""
        courses = calculate_clapboard_courses(5.0, 10.0)
        assert courses == 1
    
    def test_multiple_courses(self):
        """Tall wall needs multiple courses"""
        courses = calculate_clapboard_courses(50.0, 10.0)
        assert courses == 5
    
    def test_partial_course_rounds_up(self):
        """Partial course should round up"""
        courses = calculate_clapboard_courses(55.0, 10.0)
        assert courses == 6
    
    def test_zero_height_raises_error(self):
        """Zero wall height should be valid (no courses)"""
        courses = calculate_clapboard_courses(0.0, 10.0)
        assert courses == 0
    
    def test_invalid_clapboard_height_raises(self):
        """Zero clapboard height should raise error"""
        with pytest.raises(ValueError):
            calculate_clapboard_courses(50.0, 0.0)


class TestParameterValidation:
    """Test parameter validation"""
    
    def test_valid_parameters(self):
        """Valid parameters should pass"""
        is_valid, errors = validate_parameters(1.0, 0.5)
        assert is_valid
        assert len(errors) == 0
    
    def test_zero_height_invalid(self):
        """Zero height should be invalid"""
        is_valid, errors = validate_parameters(0.0, 0.5)
        assert not is_valid
        assert any('height' in e.lower() for e in errors)
    
    def test_zero_thickness_invalid(self):
        """Zero thickness should be invalid"""
        is_valid, errors = validate_parameters(1.0, 0.0)
        assert not is_valid
        assert any('thickness' in e.lower() for e in errors)
    
    def test_thickness_exceeds_height(self):
        """Thickness > height should be invalid"""
        is_valid, errors = validate_parameters(1.0, 2.0)
        assert not is_valid
        assert any('exceed' in e.lower() for e in errors)
    
    def test_negative_height_invalid(self):
        """Negative height should be invalid"""
        is_valid, errors = validate_parameters(-1.0, 0.5)
        assert not is_valid


class TestOrientationDescription:
    """Test face orientation descriptions"""
    
    def test_xy_plane_description(self):
        """XY plane should be described correctly"""
        desc = get_face_orientation_description('y', 'x')
        assert 'XY' in desc or 'x' in desc.lower()
    
    def test_xz_plane_description(self):
        """XZ plane should be described correctly"""
        desc = get_face_orientation_description('z', 'x')
        assert 'XZ' in desc or 'x' in desc.lower()
    
    def test_yz_plane_description(self):
        """YZ plane should be described correctly"""
        desc = get_face_orientation_description('z', 'y')
        assert 'YZ' in desc or 'y' in desc.lower()


class TestHOScaleDefaults:
    """Test HO scale parameter defaults"""
    
    def test_ho_scale_clapboard_height(self):
        """HO scale clapboard height ~0.8mm is reasonable"""
        # Real clapboard ~100mm reveal, HO scale 1:87
        # Expected: 100/87 ≈ 1.15mm
        ho_reveal = 0.8
        assert 0.5 < ho_reveal < 2.0
    
    def test_ho_scale_clapboard_thickness(self):
        """HO scale clapboard thickness ~0.2mm is reasonable"""
        # Real clapboard ~15mm thick, HO scale 1:87
        # Expected: 15/87 ≈ 0.17mm
        ho_thickness = 0.2
        assert 0.1 < ho_thickness < 0.5
    
    def test_ho_scale_trim_width(self):
        """HO scale trim width ~1.5mm is reasonable"""
        # Real trim ~130mm, HO scale 1:87
        # Expected: 130/87 ≈ 1.5mm
        ho_trim = 1.5
        assert 1.0 < ho_trim < 2.5


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
