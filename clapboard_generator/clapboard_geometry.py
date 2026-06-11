"""
Clapboard Geometry Library v5.2.0

Pure Python geometry functions extracted from clapboard_generator.FCMacro.
These functions are testable without FreeCAD and can be used in pytest.

No dependencies on FreeCAD.Part, FreeCAD.Vector, etc.
Uses standard Python types (tuples, dicts, lists) for I/O.

v5.2.0: Added calculate_course_v_positions() — extracted the per-course
        vertical-extent calculation from clapboard_proxy._make_course so it
        can be unit-tested in pure Python.  The new function guarantees no
        course edge falls within `topo_eps` of the wall's vertical bounds,
        preventing the OCCT common() segfault that occurs when a wall
        height equals an integer multiple of clapboard_height (the top of
        the last course would otherwise coincide with the face top edge).
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
    if x_extent <= tolerance:
        # YZ plane (normal is X)
        return 'z', 'y', 'x'
    elif y_extent <= tolerance:
        # XZ plane (normal is Y)
        return 'z', 'x', 'y'
    elif z_extent <= tolerance:
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


def calculate_course_v_positions(wall_v_min: float, wall_v_max: float,
                                 clapboard_height: float,
                                 overlap: float = 0.01,
                                 topo_eps: float = 1e-3
                                 ) -> List[Tuple[float, float]]:
    """
    Calculate (v_bot, v_top) extents for every clapboard course on a wall.

    Courses are laid bottom-up starting from a grid-snapped position
    (round(wall_v_min / clapboard_height) * clapboard_height) so courses
    align across multiple faces of the same building.  Each course above
    the first overlaps the one below by `overlap` mm.

    Boundary safety: when a course edge would land within `topo_eps` of
    either wall boundary (e.g. wall_height is an exact integer multiple
    of clapboard_height), the edge is pushed STRICTLY OUTSIDE the wall.
    This prevents an OCCT common() segfault in clapboard_proxy when the
    course face becomes coincident with the face_slab boundary face.

    Args:
        wall_v_min: bottom edge of wall (mm)
        wall_v_max: top edge of wall (mm)
        clapboard_height: per-course reveal height (mm)
        overlap: how much each non-first course overlaps the one below (mm)
        topo_eps: forbidden zone width at each boundary; coincident edges
                  are pushed this distance strictly outside the wall

    Returns:
        List of (v_bot, v_top) tuples — one per course that intersects the
        wall.  The first course's v_bot is guaranteed < wall_v_min - topo_eps;
        the last course's v_top is guaranteed > wall_v_max + topo_eps.
    """
    if clapboard_height <= 0:
        raise ValueError("clapboard_height must be positive")
    if wall_v_max <= wall_v_min:
        raise ValueError("wall_v_max must exceed wall_v_min")

    wall_h = wall_v_max - wall_v_min
    vert_min = round(wall_v_min / clapboard_height) * clapboard_height
    num_courses = int(math.ceil(wall_h / clapboard_height)) + 1  # +1 ensures top overflow

    positions: List[Tuple[float, float]] = []
    for i in range(num_courses):
        ov = overlap if i > 0 else 0.0
        v_bot = vert_min + i * clapboard_height - ov
        v_top = v_bot + clapboard_height

        # Drop courses entirely outside the wall (can happen at the edges
        # after grid snapping).
        if v_top <= wall_v_min or v_bot >= wall_v_max:
            continue

        # Snap any edge within topo_eps of a wall boundary STRICTLY OUTSIDE.
        if abs(v_bot - wall_v_min) < topo_eps:
            v_bot = wall_v_min - topo_eps
        if abs(v_top - wall_v_max) < topo_eps:
            v_top = wall_v_max + topo_eps

        positions.append((v_bot, v_top))

    if not positions:
        raise ValueError(
            f"No clapboard courses intersect wall [{wall_v_min}, {wall_v_max}] "
            f"with clapboard_height={clapboard_height}. "
            f"Grid snap placed all courses outside the wall bounds."
        )

    # Guarantee the bottom course overflows wall_v_min and the top course
    # overflows wall_v_max — covers cases where natural positions stop just
    # short of the boundary without triggering the abs(...) snap above.
    if positions:
        b0, t0 = positions[0]
        if b0 >= wall_v_min - topo_eps:
            positions[0] = (wall_v_min - topo_eps, t0)
        bN, tN = positions[-1]
        if tN <= wall_v_max + topo_eps:
            positions[-1] = (bN, wall_v_max + topo_eps)

    return positions


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
