"""
Tests for board_batten_geometry.py

These tests verify the pure-Python geometry functions work correctly
without requiring FreeCAD to be installed.
"""

import pytest
import sys
from pathlib import Path

# Add parent directory to path to import board_batten_geometry
sys.path.insert(0, str(Path(__file__).parent.parent))

from board_batten_geometry import (
    validate_parameters,
    calculate_board_count,
    detect_face_orientation,
    get_face_orientation_description,
    calculate_board_positions,
    calculate_batten_positions,
    check_for_degenerate_edges,
    check_for_duplicate_edges,
    validate_wire_geometry
)


class TestValidateParameters:
    """Tests for parameter validation."""

    def test_valid_parameters(self):
        """Valid parameters should pass validation."""
        is_valid, errors = validate_parameters(
            board_width=7.0,
            batten_width=0.6,
            board_thickness=0.2,
            batten_projection=0.12
        )
        assert is_valid is True
        assert len(errors) == 0

    def test_negative_board_width(self):
        """Negative board width should fail."""
        is_valid, errors = validate_parameters(
            board_width=-1.0,
            batten_width=0.6,
            board_thickness=0.2,
            batten_projection=0.12
        )
        assert is_valid is False
        assert any("board_width" in e for e in errors)

    def test_zero_batten_width(self):
        """Zero batten width should fail."""
        is_valid, errors = validate_parameters(
            board_width=7.0,
            batten_width=0.0,
            board_thickness=0.2,
            batten_projection=0.12
        )
        assert is_valid is False

    def test_batten_wider_than_board(self):
        """Batten wider than board should fail."""
        is_valid, errors = validate_parameters(
            board_width=0.5,
            batten_width=1.0,
            board_thickness=0.2,
            batten_projection=0.12
        )
        assert is_valid is False
        assert any("batten_width" in e and "board_width" in e for e in errors)

    def test_excessive_batten_projection(self):
        """Batten projection exceeding board thickness should warn."""
        is_valid, errors = validate_parameters(
            board_width=7.0,
            batten_width=0.6,
            board_thickness=0.2,
            batten_projection=0.5
        )
        assert is_valid is False
        assert any("batten_projection" in e for e in errors)


class TestCalculateBoardCount:
    """Tests for board count calculation."""

    def test_exact_fit(self):
        """Wall width exactly divisible by board width."""
        count = calculate_board_count(wall_width=70.0, board_width=7.0)
        assert count == 10

    def test_partial_board_needed(self):
        """Wall width requiring partial board at end."""
        count = calculate_board_count(wall_width=75.0, board_width=7.0)
        assert count == 11  # Need 11 boards to cover 75mm

    def test_single_board(self):
        """Very small wall needs at least one board."""
        count = calculate_board_count(wall_width=1.0, board_width=7.0)
        assert count == 1

    def test_zero_wall_width(self):
        """Zero wall width should return zero boards."""
        count = calculate_board_count(wall_width=0.0, board_width=7.0)
        assert count == 0

    def test_negative_board_width_raises(self):
        """Negative board width should raise ValueError."""
        with pytest.raises(ValueError):
            calculate_board_count(wall_width=70.0, board_width=-7.0)


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


class TestCalculateBoardPositions:
    """Tests for board position calculation."""

    def test_simple_positions(self):
        """Calculate board positions for simple wall.

        v1.0.1: outermost boards overflow wall edges by TOPO_EPS = bw * 0.001
        to avoid OCCT coincident-face segfault.  Interior boards unchanged.
        """
        positions = calculate_board_positions(
            h_min=0.0,
            h_max=21.0,
            board_width=7.0,
            center_align=False
        )
        TOPO_EPS = 7.0 * 0.001
        assert len(positions) == 3
        assert positions[0] == pytest.approx((0.0 - TOPO_EPS, 7.0))
        assert positions[1] == (7.0, 14.0)
        assert positions[2] == pytest.approx((14.0, 21.0 + TOPO_EPS))

    def test_center_aligned(self):
        """Center-aligned boards should be symmetric and unclipped.

        v1.0.1: boards are no longer clipped to wall bounds in Python; they
        overflow naturally so OCCT common() can do the clipping safely.
        """
        positions = calculate_board_positions(
            h_min=0.0,
            h_max=20.0,
            board_width=7.0,
            center_align=True
        )
        # 20mm needs 3 boards @ 7mm = 21mm total → 0.5mm overhang per side
        TOPO_EPS = 7.0 * 0.001
        assert len(positions) == 3
        # First board starts at -0.5 - TOPO_EPS (natural overhang + epsilon)
        assert positions[0][0] == pytest.approx(-0.5 - TOPO_EPS)
        # Last board ends at 20.5 + TOPO_EPS
        assert positions[-1][1] == pytest.approx(20.5 + TOPO_EPS)
        # Middle board should be roughly centered around 10mm
        mid_board_center = (positions[1][0] + positions[1][1]) / 2
        assert 9.0 < mid_board_center < 11.0

    def test_partial_board_overlap(self):
        """Boards that partially overlap wall are included and overflow edges.

        v1.0.1: boards unclipped — overflow on both wall edges is invariant.
        """
        positions = calculate_board_positions(
            h_min=1.0,
            h_max=15.0,
            board_width=7.0,
            center_align=False
        )
        # Boards must overflow both wall edges (not clipped to them)
        assert positions[0][0] < 1.0   # first board overflows left
        assert positions[-1][1] > 15.0  # last board overflows right


class TestCalculateBattenPositions:
    """Tests for batten position calculation."""

    def test_simple_battens(self):
        """Battens should be at seams between boards."""
        board_positions = [
            (0.0, 7.0),
            (7.0, 14.0),
            (14.0, 21.0)
        ]
        batten_positions = calculate_batten_positions(board_positions)
        assert len(batten_positions) == 2
        assert batten_positions[0] == 7.0  # Seam between board 1 and 2
        assert batten_positions[1] == 14.0  # Seam between board 2 and 3

    def test_single_board_no_battens(self):
        """Single board should have no battens."""
        board_positions = [(0.0, 7.0)]
        batten_positions = calculate_batten_positions(board_positions)
        assert len(batten_positions) == 0

    def test_no_boards_no_battens(self):
        """No boards should have no battens."""
        board_positions = []
        batten_positions = calculate_batten_positions(board_positions)
        assert len(batten_positions) == 0


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


from boundary_assertions import assert_overflows_boundary


class TestBoundaryOverflow:
    """Boundary-overflow invariant for board-batten wall fills.

    calculate_board_positions() generates board (start, end) tuples that
    feed an OCCT common() clip box in board_batten_proxy._build_engraving.
    If the leftmost/rightmost boards end exactly at the wall edge, common()
    sees coincident boundary faces and segfaults.

    These tests enforce that placed boards always overflow the wall edges
    on both sides — purely in Python, no OCCT needed.
    """

    @pytest.mark.parametrize('h_min,h_max,board_width', [
        (0.0,   50.0, 2.0),   # exact integer multiple: most likely zero remnant
        (0.0,   50.0, 1.5),   # non-integer ratio
        (0.0,  100.0, 5.0),
        (-10.0, 10.0, 4.0),   # negative h_min, exact fit
        (0.0,   8.0,  2.0),   # narrow wall, 4 boards exactly fit
    ])
    def test_boards_overflow_wall_edges(self, h_min, h_max, board_width):
        positions = calculate_board_positions(
            h_min, h_max, board_width, center_align=True
        )
        assert_overflows_boundary(
            positions, lo=h_min, hi=h_max,
            get_extent=lambda p: p,  # positions are already (start, end) tuples
            label=f"board_width={board_width} wall=[{h_min},{h_max}]: ",
        )
