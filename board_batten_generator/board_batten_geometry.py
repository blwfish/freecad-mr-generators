"""
Board-and-Batten Geometry Library v1.0.0

Pure Python geometry functions for board-and-batten siding generator.
These functions are testable without FreeCAD and can be used in pytest.

No dependencies on FreeCAD.Part, FreeCAD.Vector, etc.
Uses standard Python types (tuples, dicts, lists) for I/O.
"""

import math
from typing import List, Tuple, Dict, Optional


def validate_parameters(board_width: float, batten_width: float,
                       board_thickness: float, batten_projection: float) -> Tuple[bool, List[str]]:
    """
    Validate board-and-batten parameters.

    Args:
        board_width: Width of each board in mm
        batten_width: Width of batten strips in mm
        board_thickness: Thickness of boards in mm
        batten_projection: How far battens project from board surface in mm

    Returns:
        Tuple of (is_valid, error_messages)
    """
    errors = []

    if board_width <= 0:
        errors.append(f"board_width must be positive, got {board_width}")

    if batten_width <= 0:
        errors.append(f"batten_width must be positive, got {batten_width}")

    if board_thickness <= 0:
        errors.append(f"board_thickness must be positive, got {board_thickness}")

    if batten_projection <= 0:
        errors.append(f"batten_projection must be positive, got {batten_projection}")

    if batten_width > board_width:
        errors.append(f"batten_width ({batten_width}) cannot exceed board_width ({board_width})")

    if batten_projection > board_thickness:
        errors.append(f"batten_projection ({batten_projection}) should not exceed board_thickness ({board_thickness})")

    return len(errors) == 0, errors


def calculate_board_count(wall_width: float, board_width: float) -> int:
    """
    Calculate number of boards needed for a wall width.

    Args:
        wall_width: Width of wall in mm
        board_width: Width of each board in mm

    Returns:
        Number of boards needed
    """
    if board_width <= 0:
        raise ValueError("board_width must be positive")
    if wall_width < 0:
        raise ValueError("wall_width must be non-negative")

    return int(math.ceil(wall_width / board_width))


def detect_face_orientation(bbox: Dict) -> Tuple[str, str, str]:
    """
    Detect which plane a face lies in based on bounding box extents.

    Args:
        bbox: Dict with 'x_min', 'x_max', 'y_min', 'y_max', 'z_min', 'z_max'

    Returns:
        Tuple of (vertical_axis, horizontal_axis, normal_axis)
        where axes are 'x', 'y', or 'z'
    """
    x_extent = bbox.get('x_max', 0) - bbox.get('x_min', 0)
    y_extent = bbox.get('y_max', 0) - bbox.get('y_min', 0)
    z_extent = bbox.get('z_max', 0) - bbox.get('z_min', 0)

    tolerance = 0.1  # mm

    # Check which axis has near-zero extent (that's the normal direction)
    if x_extent < tolerance:
        # YZ plane (normal is X)
        return 'z', 'y', 'x'
    elif y_extent < tolerance:
        # XZ plane (normal is Y)
        return 'z', 'x', 'y'
    elif z_extent < tolerance:
        # XY plane (normal is Z)
        return 'y', 'x', 'z'
    else:
        # All three have extent - face is tilted, use largest as vertical
        if z_extent >= y_extent and z_extent >= x_extent:
            if x_extent > y_extent:
                return 'z', 'x', 'y'
            else:
                return 'z', 'y', 'x'
        else:
            return 'y', 'x', 'z'


def get_face_orientation_description(vertical_axis: str, horizontal_axis: str) -> str:
    """
    Get human-readable description of face orientation.

    Args:
        vertical_axis: 'x', 'y', or 'z'
        horizontal_axis: 'x', 'y', or 'z'

    Returns:
        String description like "XZ plane" or "YZ plane"
    """
    axes = {vertical_axis, horizontal_axis}

    if axes == {'x', 'z'}:
        return "XZ plane"
    elif axes == {'y', 'z'}:
        return "YZ plane"
    elif axes == {'x', 'y'}:
        return "XY plane"
    else:
        return f"{vertical_axis}{horizontal_axis} plane"


def calculate_board_positions(h_min: float, h_max: float, board_width: float,
                              center_align: bool = True) -> List[Tuple[float, float]]:
    """
    Calculate horizontal positions for boards across a wall.

    Args:
        h_min: Minimum horizontal position (mm)
        h_max: Maximum horizontal position (mm)
        board_width: Width of each board (mm)
        center_align: If True, center the board pattern; if False, start from h_min

    Returns:
        List of (board_start, board_end) tuples in mm
    """
    wall_width = h_max - h_min
    num_boards = calculate_board_count(wall_width, board_width)

    if center_align:
        # Center the board pattern
        total_width = num_boards * board_width
        offset = (total_width - wall_width) / 2
        start_pos = h_min - offset
    else:
        # Start from left edge
        start_pos = h_min

    positions = []
    for i in range(num_boards):
        board_start = start_pos + i * board_width
        board_end = board_start + board_width

        # Only include boards that actually overlap with the wall
        if board_end > h_min and board_start < h_max:
            positions.append((max(board_start, h_min), min(board_end, h_max)))

    return positions


def calculate_batten_positions(board_positions: List[Tuple[float, float]]) -> List[float]:
    """
    Calculate center positions for battens between boards.

    Args:
        board_positions: List of (board_start, board_end) tuples

    Returns:
        List of batten center positions (at board seams)
    """
    if len(board_positions) < 2:
        return []

    batten_positions = []
    for i in range(len(board_positions) - 1):
        board_end = board_positions[i][1]
        next_board_start = board_positions[i + 1][0]

        # Batten centered at the seam
        seam_center = (board_end + next_board_start) / 2
        batten_positions.append(seam_center)

    return batten_positions


def check_for_degenerate_edges(edges: List[Dict]) -> List[Tuple[int, float]]:
    """
    Detect edges with zero or near-zero length.

    Args:
        edges: List of edge dicts with 'length' key

    Returns:
        List of (index, length) tuples for degenerate edges
    """
    degenerate = []
    tolerance = 0.001  # mm

    for i, edge in enumerate(edges):
        if edge.get('length', 0) < tolerance:
            degenerate.append((i, edge.get('length', 0)))

    return degenerate


def check_for_duplicate_edges(edges: List[Dict]) -> List[Tuple[int, int]]:
    """
    Detect duplicate or overlapping edges.

    Args:
        edges: List of edge dicts with 'start' and 'end' keys (tuples of x,y,z)

    Returns:
        List of (index1, index2) tuples for duplicate edges
    """
    duplicates = []
    tolerance = 0.001  # mm

    for i in range(len(edges)):
        for j in range(i + 1, len(edges)):
            edge1 = edges[i]
            edge2 = edges[j]

            e1_start = edge1.get('start', (0, 0, 0))
            e1_end = edge1.get('end', (0, 0, 0))
            e2_start = edge2.get('start', (0, 0, 0))
            e2_end = edge2.get('end', (0, 0, 0))

            # Euclidean distance
            def dist(p1, p2):
                return math.sqrt(sum((a - b) ** 2 for a, b in zip(p1, p2)))

            # Same edge in same direction
            if (dist(e1_start, e2_start) < tolerance and
                dist(e1_end, e2_end) < tolerance):
                duplicates.append((i, j))
            # Same edge reversed
            elif (dist(e1_start, e2_end) < tolerance and
                  dist(e1_end, e2_start) < tolerance):
                duplicates.append((i, j))

    return duplicates


def validate_wire_geometry(edges: List[Dict], wire_name: str = "Wire") -> Tuple[bool, List[str]]:
    """
    Validate wire for common geometry errors.

    Args:
        edges: List of edge dicts
        wire_name: Name of wire for error messages

    Returns:
        Tuple of (is_valid, error_messages)
    """
    errors = []

    # Check for degenerate edges
    degenerate = check_for_degenerate_edges(edges)
    if degenerate:
        for i, length in degenerate:
            errors.append(f"{wire_name}: Edge {i} has degenerate length {length:.6f}mm")

    # Check for duplicate edges
    duplicates = check_for_duplicate_edges(edges)
    if duplicates:
        for i, j in duplicates:
            errors.append(f"{wire_name}: Edges {i} and {j} are duplicates")

    return len(errors) == 0, errors
