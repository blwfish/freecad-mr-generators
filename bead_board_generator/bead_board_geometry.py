"""
Bead Board Geometry Library v1.0.0

Pure Python geometry functions for bead board trim generator.
These functions are testable without FreeCAD and can be used in pytest.

Bead board consists of vertical ribs separated by thin gaps.
The gaps are extruded slightly above the face (materialThickness depth),
creating a recessed groove pattern.

No dependencies on FreeCAD.Part, FreeCAD.Vector, etc.
Uses standard Python types (tuples, dicts, lists) for I/O.
"""

import math
from typing import List, Tuple, Dict, Optional


def validate_parameters(bead_spacing: float, bead_depth: float, bead_gap: float) -> Tuple[bool, List[str]]:
    """
    Validate bead board parameters.

    Args:
        bead_spacing: Horizontal spacing between bead centers in mm
        bead_depth: How far gaps are extruded above the face in mm
        bead_gap: Width of each gap in mm

    Returns:
        Tuple of (is_valid, error_messages)
    """
    errors = []

    if bead_spacing <= 0:
        errors.append(f"bead_spacing must be positive, got {bead_spacing}")

    if bead_depth <= 0:
        errors.append(f"bead_depth must be positive, got {bead_depth}")

    if bead_gap <= 0:
        errors.append(f"bead_gap must be positive, got {bead_gap}")

    if bead_gap >= bead_spacing:
        errors.append(f"bead_gap ({bead_gap}) must be less than bead_spacing ({bead_spacing})")

    return len(errors) == 0, errors


def calculate_bead_count(wall_width: float, bead_spacing: float) -> int:
    """
    Calculate number of beads needed for a wall width.

    Args:
        wall_width: Width of wall in mm
        bead_spacing: Spacing between bead centers in mm

    Returns:
        Number of beads needed
    """
    if bead_spacing <= 0:
        raise ValueError("bead_spacing must be positive")
    if wall_width < 0:
        raise ValueError("wall_width must be non-negative")

    return int(math.ceil(wall_width / bead_spacing))


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


def calculate_bead_positions(h_min: float, h_max: float, bead_spacing: float) -> List[float]:
    """
    Calculate positions for bead centers starting from left edge.

    Carpenter would start at one edge, so beads begin at h_min and continue
    at regular intervals across the wall width.

    Args:
        h_min: Minimum horizontal position (mm)
        h_max: Maximum horizontal position (mm)
        bead_spacing: Spacing between bead centers (mm)

    Returns:
        List of bead center positions in mm
    """
    wall_width = h_max - h_min
    num_beads = calculate_bead_count(wall_width, bead_spacing)

    positions = []
    for i in range(num_beads):
        bead_center = h_min + i * bead_spacing
        # Only include beads that are within the wall bounds
        if bead_center < h_max:
            positions.append(bead_center)

    return positions


def calculate_gap_positions(bead_positions: List[float], bead_gap: float) -> List[Tuple[float, float]]:
    """
    Calculate start and end positions for each gap based on bead centers.

    Each gap is centered at a bead position, with width bead_gap.

    Args:
        bead_positions: List of bead center positions
        bead_gap: Width of each gap in mm

    Returns:
        List of (gap_start, gap_end) tuples in mm
    """
    gap_positions = []
    half_gap = bead_gap / 2

    for bead_center in bead_positions:
        gap_start = bead_center - half_gap
        gap_end = bead_center + half_gap
        gap_positions.append((gap_start, gap_end))

    return gap_positions


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
