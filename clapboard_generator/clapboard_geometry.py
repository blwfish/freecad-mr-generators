"""
Clapboard Geometry Library v5.1.0

Pure Python geometry functions extracted from clapboard_generator.FCMacro.
These functions are testable without FreeCAD and can be used in pytest.

No dependencies on FreeCAD.Part, FreeCAD.Vector, etc.
Uses standard Python types (tuples, dicts, lists) for I/O.
"""

import math
from typing import List, Tuple, Dict, Optional


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


def is_building_corner(edge_h_pos: float, bbox: Dict, horizontal_axis: str = 'x', 
                      tolerance: float = 1.0) -> bool:
    """
    Check if a vertical edge is at a building corner (extreme position).
    
    Args:
        edge_h_pos: Horizontal position of edge
        bbox: Bounding box dict
        horizontal_axis: 'x' or 'y'
        tolerance: Distance tolerance in mm
    
    Returns:
        True if edge is at an extreme (building corner)
    """
    if horizontal_axis == 'x':
        h_min = bbox.get('x_min', 0)
        h_max = bbox.get('x_max', 0)
    else:
        h_min = bbox.get('y_min', 0)
        h_max = bbox.get('y_max', 0)
    
    at_min = abs(edge_h_pos - h_min) < tolerance
    at_max = abs(edge_h_pos - h_max) < tolerance
    
    return at_min or at_max


def calculate_clapboard_courses(wall_height: float, clapboard_height: float) -> int:
    """
    Calculate number of clapboard courses needed for a wall height.
    
    Args:
        wall_height: Height of wall in mm
        clapboard_height: Height of each course (reveal) in mm
    
    Returns:
        Number of courses needed
    """
    if clapboard_height <= 0:
        raise ValueError("clapboard_height must be positive")
    if wall_height < 0:
        raise ValueError("wall_height must be non-negative")
    
    return int(math.ceil(wall_height / clapboard_height))


def validate_parameters(clapboard_height: float, clapboard_thickness: float) -> Tuple[bool, List[str]]:
    """
    Validate clapboard parameters.
    
    Args:
        clapboard_height: Height of each course in mm
        clapboard_thickness: Thickness at bottom edge in mm
    
    Returns:
        Tuple of (is_valid, error_messages)
    """
    errors = []
    
    if clapboard_height <= 0:
        errors.append(f"clapboard_height must be positive, got {clapboard_height}")
    
    if clapboard_thickness <= 0:
        errors.append(f"clapboard_thickness must be positive, got {clapboard_thickness}")
    
    if clapboard_thickness > clapboard_height:
        errors.append(f"clapboard_thickness ({clapboard_thickness}) cannot exceed height ({clapboard_height})")
    
    return len(errors) == 0, errors


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
