"""
Tests for bead_board_geometry.py

These tests verify the pure-Python geometry functions work correctly
without requiring FreeCAD to be installed.
"""

import pytest
import sys
from pathlib import Path

# Add parent directory to path to import bead_board_geometry
sys.path.insert(0, str(Path(__file__).parent.parent))

from bead_board_geometry import (
    validate_parameters,
    calculate_bead_count,
    detect_face_orientation,
    get_face_orientation_description,
    calculate_bead_positions,
    calculate_gap_positions,
    check_for_degenerate_edges,
    check_for_duplicate_edges,
    validate_wire_geometry
)


class TestValidateParameters:
    """Tests for parameter validation."""

    def test_valid_parameters(self):
        """Valid parameters should pass validation."""
        is_valid, errors = validate_parameters(
            bead_spacing=101.6,  # 4 inches
            bead_depth=0.20,     # materialThickness
            bead_gap=0.20
        )
        assert is_valid is True
        assert len(errors) == 0

    def test_negative_bead_spacing(self):
        """Negative bead spacing should fail."""
        is_valid, errors = validate_parameters(
            bead_spacing=-101.6,
            bead_depth=0.20,
            bead_gap=0.20
        )
        assert is_valid is False
        assert any("bead_spacing" in e for e in errors)

    def test_zero_bead_depth(self):
        """Zero bead depth should fail."""
        is_valid, errors = validate_parameters(
            bead_spacing=101.6,
            bead_depth=0.0,
            bead_gap=0.20
        )
        assert is_valid is False

    def test_gap_equals_spacing(self):
        """Gap width equal to spacing should fail."""
        is_valid, errors = validate_parameters(
            bead_spacing=101.6,
            bead_depth=0.20,
            bead_gap=101.6  # Equal to spacing
        )
        assert is_valid is False
        assert any("bead_gap" in e and "bead_spacing" in e for e in errors)

    def test_gap_exceeds_spacing(self):
        """Gap width exceeding spacing should fail."""
        is_valid, errors = validate_parameters(
            bead_spacing=101.6,
            bead_depth=0.20,
            bead_gap=150.0  # Exceeds spacing
        )
        assert is_valid is False


class TestCalculateBeadCount:
    """Tests for bead count calculation."""

    def test_exact_fit(self):
        """Wall width exactly divisible by bead spacing."""
        # 400mm wall at 101.6mm spacing = 3.937 beads, ceil to 4
        count = calculate_bead_count(wall_width=406.4, bead_spacing=101.6)
        assert count == 4

    def test_partial_bead_needed(self):
        """Wall width requiring partial bead at end."""
        count = calculate_bead_count(wall_width=450.0, bead_spacing=101.6)
        assert count == 5  # 450/101.6 = 4.43, ceil to 5

    def test_single_bead(self):
        """Very small wall needs at least one bead."""
        count = calculate_bead_count(wall_width=10.0, bead_spacing=101.6)
        assert count == 1

    def test_zero_wall_width(self):
        """Zero wall width should return zero beads."""
        count = calculate_bead_count(wall_width=0.0, bead_spacing=101.6)
        assert count == 0

    def test_negative_bead_spacing_raises(self):
        """Negative bead spacing should raise ValueError."""
        with pytest.raises(ValueError):
            calculate_bead_count(wall_width=400.0, bead_spacing=-101.6)


class TestDetectFaceOrientation:
    """Tests for face orientation detection."""

    def test_yz_plane(self):
        """Face in YZ plane (normal is X)."""
        bbox = {
            'x_min': 10.0, 'x_max': 10.05,  # Very thin in X
            'y_min': 0.0, 'y_max': 100.0,
            'z_min': 0.0, 'z_max': 50.0
        }
        vert, horiz, norm = detect_face_orientation(bbox)
        assert vert == 'z'  # Vertical is Z
        assert horiz == 'y'  # Horizontal is Y
        assert norm == 'x'  # Normal is X

    def test_xz_plane(self):
        """Face in XZ plane (normal is Y)."""
        bbox = {
            'x_min': 0.0, 'x_max': 100.0,
            'y_min': 20.0, 'y_max': 20.05,  # Very thin in Y
            'z_min': 0.0, 'z_max': 50.0
        }
        vert, horiz, norm = detect_face_orientation(bbox)
        assert vert == 'z'
        assert horiz == 'x'
        assert norm == 'y'

    def test_xy_plane(self):
        """Face in XY plane (normal is Z)."""
        bbox = {
            'x_min': 0.0, 'x_max': 100.0,
            'y_min': 0.0, 'y_max': 50.0,
            'z_min': 0.0, 'z_max': 0.05  # Very thin in Z
        }
        vert, horiz, norm = detect_face_orientation(bbox)
        assert vert == 'y'
        assert horiz == 'x'
        assert norm == 'z'


class TestGetFaceOrientationDescription:
    """Tests for orientation description."""

    def test_xz_plane_description(self):
        """XZ plane description."""
        desc = get_face_orientation_description('z', 'x')
        assert desc == "XZ plane"

    def test_yz_plane_description(self):
        """YZ plane description."""
        desc = get_face_orientation_description('z', 'y')
        assert desc == "YZ plane"

    def test_xy_plane_description(self):
        """XY plane description."""
        desc = get_face_orientation_description('y', 'x')
        assert desc == "XY plane"


class TestCalculateBeadPositions:
    """Tests for bead position calculation."""

    def test_simple_positions(self):
        """Calculate bead positions for simple wall."""
        positions = calculate_bead_positions(
            h_min=0.0,
            h_max=305.0,  # 4 beads at 101.6mm spacing
            bead_spacing=101.6
        )
        assert len(positions) == 4
        assert positions[0] == 0.0
        assert positions[1] == 101.6
        assert positions[2] == 203.2
        assert abs(positions[3] - 304.8) < 0.001

    def test_partial_bead_at_end(self):
        """Last bead may be cut off by wall boundary."""
        positions = calculate_bead_positions(
            h_min=0.0,
            h_max=300.0,
            bead_spacing=101.6
        )
        # 0, 101.6, 203.2, 304.8 (but 304.8 > 300 so excluded)
        assert len(positions) == 3
        assert positions[-1] == 203.2

    def test_offset_wall(self):
        """Wall doesn't start at zero."""
        positions = calculate_bead_positions(
            h_min=50.0,
            h_max=350.0,
            bead_spacing=101.6
        )
        # Should start at h_min and go to h_max
        assert positions[0] == 50.0
        assert all(p >= 50.0 and p < 350.0 for p in positions)

    def test_single_bead_wall(self):
        """Very small wall with only one bead."""
        positions = calculate_bead_positions(
            h_min=0.0,
            h_max=50.0,
            bead_spacing=101.6
        )
        assert len(positions) == 1
        assert positions[0] == 0.0


class TestCalculateGapPositions:
    """Tests for gap position calculation."""

    def test_simple_gaps(self):
        """Calculate gap positions from bead centers."""
        bead_positions = [0.0, 101.6, 203.2]
        gap_positions = calculate_gap_positions(bead_positions, bead_gap=0.20)

        assert len(gap_positions) == 3
        # Each gap is centered at bead position
        assert abs(gap_positions[0][0] - (-0.1)) < 0.001
        assert abs(gap_positions[0][1] - 0.1) < 0.001
        assert abs(gap_positions[1][0] - 101.5) < 0.001
        assert abs(gap_positions[1][1] - 101.7) < 0.001
        assert abs(gap_positions[2][0] - 203.1) < 0.001
        assert abs(gap_positions[2][1] - 203.3) < 0.001

    def test_larger_gap(self):
        """Gaps can be wider."""
        bead_positions = [100.0]
        gap_positions = calculate_gap_positions(bead_positions, bead_gap=1.0)

        assert len(gap_positions) == 1
        assert gap_positions[0] == (99.5, 100.5)

    def test_no_beads(self):
        """No beads means no gaps."""
        gap_positions = calculate_gap_positions([], bead_gap=0.20)
        assert len(gap_positions) == 0


class TestEdgeValidation:
    """Tests for edge geometry validation."""

    def test_valid_edges(self):
        """Valid edges should pass validation."""
        edges = [
            {'length': 10.0, 'start': (0, 0, 0), 'end': (10, 0, 0)},
            {'length': 5.0, 'start': (10, 0, 0), 'end': (10, 5, 0)}
        ]
        is_valid, errors = validate_wire_geometry(edges)
        assert is_valid is True
        assert len(errors) == 0

    def test_degenerate_edge(self):
        """Degenerate edge should be detected."""
        edges = [
            {'length': 10.0, 'start': (0, 0, 0), 'end': (10, 0, 0)},
            {'length': 0.0, 'start': (10, 0, 0), 'end': (10, 0, 0)}  # Zero length
        ]
        degenerate = check_for_degenerate_edges(edges)
        assert len(degenerate) == 1
        assert degenerate[0][0] == 1  # Second edge

    def test_duplicate_edges(self):
        """Duplicate edges should be detected."""
        edges = [
            {'length': 10.0, 'start': (0, 0, 0), 'end': (10, 0, 0)},
            {'length': 10.0, 'start': (0, 0, 0), 'end': (10, 0, 0)}  # Duplicate
        ]
        duplicates = check_for_duplicate_edges(edges)
        assert len(duplicates) == 1
        assert duplicates[0] == (0, 1)

    def test_reversed_duplicate_edges(self):
        """Reversed duplicate edges should be detected."""
        edges = [
            {'length': 10.0, 'start': (0, 0, 0), 'end': (10, 0, 0)},
            {'length': 10.0, 'start': (10, 0, 0), 'end': (0, 0, 0)}  # Reversed
        ]
        duplicates = check_for_duplicate_edges(edges)
        assert len(duplicates) == 1
