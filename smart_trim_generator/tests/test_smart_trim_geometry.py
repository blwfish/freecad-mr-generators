"""
Test suite for smart_trim_geometry.py

Run with: pytest test_smart_trim_geometry.py -v
"""

import pytest
import math
from smart_trim_geometry import (
    vector_normalize,
    vector_dot,
    vector_angle_degrees,
    classify_edge,
    classify_edges,
    filter_edges_for_trim,
    get_edge_midpoint,
    get_edge_length,
    validate_trim_parameters,
)


class TestVectorOperations:
    """Test basic vector math utilities."""
    
    def test_vector_normalize_unit(self):
        """Test normalizing a unit vector."""
        result = vector_normalize((1, 0, 0))
        assert abs(result[0] - 1.0) < 1e-6
        assert abs(result[1] - 0.0) < 1e-6
        assert abs(result[2] - 0.0) < 1e-6
    
    def test_vector_normalize_scaled(self):
        """Test normalizing a scaled vector."""
        result = vector_normalize((3, 0, 0))
        assert abs(result[0] - 1.0) < 1e-6
        assert abs(result[1] - 0.0) < 1e-6
    
    def test_vector_normalize_3d(self):
        """Test normalizing a 3D vector."""
        # (3, 4, 0) has length 5
        result = vector_normalize((3, 4, 0))
        assert abs(result[0] - 0.6) < 1e-6
        assert abs(result[1] - 0.8) < 1e-6
        assert abs(result[2] - 0.0) < 1e-6
    
    def test_vector_normalize_zero(self):
        """Test normalizing a zero vector."""
        result = vector_normalize((0, 0, 0))
        assert result == (0, 0, 0)
    
    def test_vector_dot_orthogonal(self):
        """Test dot product of orthogonal vectors."""
        result = vector_dot((1, 0, 0), (0, 1, 0))
        assert abs(result) < 1e-6
    
    def test_vector_dot_parallel(self):
        """Test dot product of parallel vectors."""
        result = vector_dot((1, 0, 0), (1, 0, 0))
        assert abs(result - 1.0) < 1e-6
    
    def test_vector_angle_parallel(self):
        """Test angle between parallel vectors."""
        angle = vector_angle_degrees((1, 0, 0), (1, 0, 0))
        assert abs(angle - 0.0) < 1e-6
    
    def test_vector_angle_orthogonal(self):
        """Test angle between orthogonal vectors."""
        angle = vector_angle_degrees((1, 0, 0), (0, 1, 0))
        assert abs(angle - 90.0) < 1e-6
    
    def test_vector_angle_opposite(self):
        """Test angle between opposite vectors."""
        angle = vector_angle_degrees((1, 0, 0), (-1, 0, 0))
        assert abs(angle - 180.0) < 1e-6


class TestEdgeClassification:
    """Test edge classification logic."""
    
    def test_classify_vertical_edge_z_axis(self):
        """Vertical edge along Z axis."""
        # Direction pointing up (Z)
        classification = classify_edge((0, 0, 1), vertical_axis='z', angle_tolerance=5.0)
        assert classification == 'vertical'
    
    def test_classify_vertical_edge_opposite_z(self):
        """Vertical edge pointing down (opposite Z)."""
        classification = classify_edge((0, 0, -1), vertical_axis='z', angle_tolerance=5.0)
        assert classification == 'vertical'
    
    def test_classify_horizontal_edge_x(self):
        """Horizontal edge along X axis."""
        classification = classify_edge((1, 0, 0), vertical_axis='z', angle_tolerance=5.0)
        assert classification == 'horizontal'
    
    def test_classify_horizontal_edge_y(self):
        """Horizontal edge along Y axis."""
        classification = classify_edge((0, 1, 0), vertical_axis='z', angle_tolerance=5.0)
        assert classification == 'horizontal'
    
    def test_classify_gable_edge_45_degrees(self):
        """Gable edge at 45 degrees."""
        # Direction at 45° in XZ plane (between horizontal and vertical)
        direction = (1, 0, 1)  # 45° when Z is vertical
        classification = classify_edge(direction, vertical_axis='z', angle_tolerance=5.0)
        assert classification == 'gable'
    
    def test_classify_vertical_with_tolerance(self):
        """Vertical edge within tolerance."""
        # Slightly tilted from vertical (4 degrees)
        angle_rad = math.radians(4)
        direction = (math.sin(angle_rad), 0, math.cos(angle_rad))
        classification = classify_edge(direction, vertical_axis='z', angle_tolerance=5.0)
        assert classification == 'vertical'
    
    def test_classify_vertical_y_axis(self):
        """Vertical edge when Y is the vertical axis."""
        classification = classify_edge((0, 1, 0), vertical_axis='y', angle_tolerance=5.0)
        assert classification == 'vertical'
    
    def test_classify_horizontal_y_axis(self):
        """Horizontal edge when Y is vertical."""
        classification = classify_edge((1, 0, 0), vertical_axis='y', angle_tolerance=5.0)
        assert classification == 'horizontal'
    
    def test_classify_edges_multiple(self):
        """Classify multiple edges at once."""
        edges = [
            {'start': (0, 0, 0), 'end': (0, 0, 10)},  # vertical
            {'start': (0, 0, 0), 'end': (10, 0, 0)},  # horizontal
            {'start': (0, 0, 0), 'end': (10, 0, 10)}, # gable
        ]
        
        results = classify_edges(edges, vertical_axis='z', angle_tolerance=5.0)
        
        assert len(results) == 3
        assert results[0] == (0, 'vertical')
        assert results[1] == (1, 'horizontal')
        assert results[2] == (2, 'gable')


class TestEdgeFiltering:
    """Test edge filtering (skip rules)."""
    
    def test_filter_skip_bottom_edge(self):
        """Bottom edge should be filtered out."""
        bbox = {'x_min': 0, 'x_max': 10, 'y_min': 0, 'y_max': 10, 'z_min': 0, 'z_max': 20}
        
        edges = [
            # Bottom edge (both endpoints at z_min)
            {'start': (0, 0, 0), 'end': (10, 0, 0)},
            # Not bottom edge
            {'start': (0, 0, 10), 'end': (10, 0, 10)},
        ]
        
        results = filter_edges_for_trim(edges, bbox, vertical_axis='z', skip_bottom=True)
        
        assert results[0] == (0, False)  # bottom, skip
        assert results[1] == (1, True)   # keep
    
    def test_filter_no_skip_when_disabled(self):
        """When skip_bottom=False, all edges should be kept."""
        bbox = {'x_min': 0, 'x_max': 10, 'y_min': 0, 'y_max': 10, 'z_min': 0, 'z_max': 20}
        
        edges = [
            {'start': (0, 0, 0), 'end': (10, 0, 0)},
        ]
        
        results = filter_edges_for_trim(edges, bbox, vertical_axis='z', skip_bottom=False)
        
        assert results[0] == (0, True)
    
    def test_filter_with_tolerance(self):
        """Test bottom edge detection with tolerance."""
        bbox = {'x_min': 0, 'x_max': 10, 'y_min': 0, 'y_max': 10, 'z_min': 0, 'z_max': 20}
        
        # Edge slightly above minimum (within tolerance)
        edges = [
            {'start': (0, 0, 0.5), 'end': (10, 0, 0.5)},
        ]
        
        results = filter_edges_for_trim(edges, bbox, vertical_axis='z', 
                                       skip_bottom=True, bottom_tolerance=1.0)
        
        assert results[0] == (0, False)  # considered bottom edge
    
    def test_filter_y_axis_vertical(self):
        """Test filtering when Y is the vertical axis."""
        bbox = {'x_min': 0, 'x_max': 10, 'y_min': 0, 'y_max': 20, 'z_min': 0, 'z_max': 10}
        
        edges = [
            # Bottom edge (y_min)
            {'start': (0, 0, 0), 'end': (10, 0, 0)},
            # Not bottom
            {'start': (0, 10, 0), 'end': (10, 10, 0)},
        ]
        
        results = filter_edges_for_trim(edges, bbox, vertical_axis='y', skip_bottom=True)
        
        assert results[0] == (0, False)
        assert results[1] == (1, True)


class TestEdgeGeometry:
    """Test edge geometry calculations."""
    
    def test_edge_midpoint(self):
        """Test calculating edge midpoint."""
        edge = {'start': (0, 0, 0), 'end': (10, 0, 0)}
        midpoint = get_edge_midpoint(edge)
        assert midpoint == (5, 0, 0)
    
    def test_edge_length(self):
        """Test calculating edge length."""
        edge = {'start': (0, 0, 0), 'end': (3, 4, 0)}
        length = get_edge_length(edge)
        assert abs(length - 5.0) < 1e-6
    
    def test_edge_length_3d(self):
        """Test 3D edge length."""
        edge = {'start': (0, 0, 0), 'end': (1, 1, 1)}
        length = get_edge_length(edge)
        assert abs(length - math.sqrt(3)) < 1e-6


class TestParameterValidation:
    """Test parameter validation."""
    
    def test_valid_parameters(self):
        """Test valid trim parameters."""
        is_valid, errors = validate_trim_parameters(trim_width=2.0, trim_thickness=1.0)
        assert is_valid is True
        assert len(errors) == 0
    
    def test_invalid_width_zero(self):
        """Test with zero width."""
        is_valid, errors = validate_trim_parameters(trim_width=0, trim_thickness=1.0)
        assert is_valid is False
        assert len(errors) == 1
    
    def test_invalid_thickness_negative(self):
        """Test with negative thickness."""
        is_valid, errors = validate_trim_parameters(trim_width=2.0, trim_thickness=-1.0)
        assert is_valid is False
        assert len(errors) == 1
    
    def test_invalid_both(self):
        """Test with both parameters invalid."""
        is_valid, errors = validate_trim_parameters(trim_width=-1.0, trim_thickness=0)
        assert is_valid is False
        assert len(errors) == 2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
