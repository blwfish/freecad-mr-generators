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


class TestClassifyEdgeAngleThresholds:
    """Threshold-boundary tests for classify_edge().

    classify_edge uses strict `<` comparisons against `angle_tolerance` to
    decide vertical/horizontal/gable.  We can't reliably construct edges
    that land EXACTLY at the tolerance boundary in IEEE-754 — building
    `(0, sin(5°), cos(5°))` and passing it through `acos(dot)` returns
    4.9999...° because the trig round-trip loses bits.  So instead of
    pinning the exact-boundary behavior (a float-precision question with
    no stable answer), we test the *bracketing* behavior: values clearly
    inside the tolerance window must classify as vertical/horizontal,
    values clearly outside must classify as gable.  The float-precision
    indeterminacy at exactly the boundary is a documented gotcha, not a
    contract.
    """

    @pytest.mark.parametrize('angle_deg,expected', [
        # tolerance = 5°.  Clearly inside / clearly outside, no exact boundary.
        (0.0,    'vertical'),
        (1.0,    'vertical'),
        (4.9,    'vertical'),     # just inside vertical zone
        (5.1,    'gable'),        # just outside vertical zone
        (45.0,   'gable'),
        (84.9,   'gable'),        # just outside horizontal zone (below)
        (85.1,   'horizontal'),   # just inside horizontal zone (below)
        (89.9,   'horizontal'),
        (90.0,   'horizontal'),
        (90.1,   'horizontal'),
        (94.9,   'horizontal'),   # just inside horizontal zone (above)
        (95.1,   'gable'),        # just outside horizontal zone (above)
        (174.9,  'gable'),        # just outside antiparallel-vertical zone
        (175.1,  'vertical'),     # just inside antiparallel-vertical zone
        (179.0,  'vertical'),
        (180.0,  'vertical'),
    ])
    def test_classification_brackets_tolerance(self, angle_deg, expected):
        """Edges clearly inside/outside the tolerance window classify
        as expected.  Exactly-at-boundary behavior is float-dependent
        and intentionally not pinned."""
        a = math.radians(angle_deg)
        edge_dir = (0.0, math.sin(a), math.cos(a))
        result = classify_edge(edge_dir, vertical_axis='z', angle_tolerance=5.0)
        assert result == expected, (
            f"angle={angle_deg}°: got {result}, expected {expected}"
        )

    @pytest.mark.parametrize('tolerance,inside_angle,outside_angle', [
        (1.0,  0.5, 1.5),      # tol=1°: 0.5° inside, 1.5° outside
        (10.0, 5.0, 15.0),     # tol=10°: 5° inside, 15° outside
        (10.0, 95.0, 110.0),   # tol=10° at horizontal: 95° inside, 110° outside
    ])
    def test_custom_tolerance_brackets(self, tolerance, inside_angle, outside_angle):
        """A custom tolerance value must still bracket vertical/horizontal
        regions strictly: edges inside the window are not gable, edges
        outside are gable."""
        def classify_at(deg):
            a = math.radians(deg)
            return classify_edge((0.0, math.sin(a), math.cos(a)),
                                 vertical_axis='z', angle_tolerance=tolerance)
        assert classify_at(inside_angle) != 'gable'
        assert classify_at(outside_angle) == 'gable'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
