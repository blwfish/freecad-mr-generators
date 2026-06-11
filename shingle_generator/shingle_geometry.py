"""
Shingle Geometry Library v5.1.0

Pure Python geometry functions for shingle generation.
These functions are testable without FreeCAD and can be used in pytest.

No dependencies on FreeCAD.Part, FreeCAD.Vector, etc.
Uses standard Python types (tuples, dicts, lists) for I/O.

v5.1.0: Shared face-orientation and hip/valley functions extracted to
        roof_geometry.py (in _shared/).  Imported and re-exported here
        for backward compatibility — all existing callers continue to work.
v5.0.0: Added bounding-box based orientation detection for reliable
        eave-to-ridge direction finding. Also added Z-based valley/ridge
        detection for smart trim functionality.
"""

import math
from typing import List, Tuple, Dict, Optional

from roof_geometry import (
    is_planar,
    calculate_face_bounds,
    find_eave_and_ridge_vertices,
    calculate_upslope_direction,
    calculate_across_roof_direction,
    get_roof_coordinate_system,
    find_coincident_edges,
    classify_roof_intersection,
    calculate_dihedral_angle,
    analyze_roof_intersection,
)


def validate_parameters(shingle_width: float, shingle_height: float, 
                       material_thickness: float, shingle_exposure: float) -> Tuple[bool, List[str]]:
    """
    Validate shingle parameters for physical and geometric soundness.
    
    Args:
        shingle_width: Width of each shingle in mm
        shingle_height: Height (length) of each shingle in mm
        material_thickness: Thickness of shingle material in mm
        shingle_exposure: Exposed portion per course in mm
    
    Returns:
        Tuple of (is_valid, error_messages)
    """
    errors = []
    
    if shingle_width <= 0:
        errors.append(f"shingle_width must be positive, got {shingle_width}")
    
    if shingle_height <= 0:
        errors.append(f"shingle_height must be positive, got {shingle_height}")
    
    if material_thickness <= 0:
        errors.append(f"material_thickness must be positive, got {material_thickness}")
    
    if shingle_exposure <= 0:
        errors.append(f"shingle_exposure must be positive, got {shingle_exposure}")
    
    if shingle_exposure > shingle_height:
        errors.append(f"shingle_exposure ({shingle_exposure}) cannot exceed shingle_height ({shingle_height})")
    
    if material_thickness > shingle_height:
        errors.append(f"material_thickness ({material_thickness}) cannot exceed shingle_height ({shingle_height})")
    
    return len(errors) == 0, errors


def validate_stagger_pattern(pattern: str) -> Tuple[bool, str]:
    """
    Validate stagger pattern is one of the supported types.
    
    Args:
        pattern: Stagger pattern name
    
    Returns:
        Tuple of (is_valid, error_message if invalid)
    """
    valid_patterns = ["half", "third", "none"]
    
    if pattern not in valid_patterns:
        return False, f"Invalid stagger pattern '{pattern}'. Must be one of: {', '.join(valid_patterns)}"
    
    return True, ""


def calculate_stagger_offset(row: int, pattern: str, shingle_width: float) -> float:
    """
    Calculate horizontal stagger offset for a given row.
    
    Args:
        row: Row number (0-indexed)
        pattern: Stagger pattern ("half", "third", or "none")
        shingle_width: Width of each shingle in mm
    
    Returns:
        Stagger offset in mm
    """
    if pattern == "half":
        return (row % 2) * (shingle_width / 2.0)
    elif pattern == "third":
        return (row % 3) * (shingle_width / 3.0)
    else:  # "none"
        return 0.0


def calculate_layout(face_width: float, face_height: float, 
                     shingle_width: float, shingle_exposure: float,
                     stagger_pattern: str = "half") -> Dict:
    """
    Calculate shingle layout parameters for a roof face.
    
    Args:
        face_width: Width of roof face (mm)
        face_height: Height of roof face (mm, along slope)
        shingle_width: Width of each shingle (mm)
        shingle_exposure: Exposed portion per course (mm)
        stagger_pattern: Stagger pattern type
    
    Returns:
        Dict with layout info:
            - num_courses: Number of courses needed
            - shingles_per_course: Number of shingles per course
            - max_stagger: Maximum stagger offset (mm)
            - total_width_needed: Total width coverage needed
            - total_shingles_before_trim: Total shingle count before trimming
    """
    # Calculate number of courses
    # Add 3 extra to ensure full coverage with overlap
    num_courses = int(math.ceil(face_height / shingle_exposure)) + 3
    
    # Calculate maximum stagger offset
    if stagger_pattern == "half":
        max_stagger = shingle_width / 2.0
    elif stagger_pattern == "third":
        max_stagger = shingle_width / 3.0
    else:
        max_stagger = 0.0
    
    # Calculate width coverage needed
    # Start at -max_stagger and cover to face_width + max_stagger
    total_width_needed = face_width + 2 * max_stagger
    
    # Calculate shingles per course
    # Add 3 for safety margin
    shingles_per_course = int(math.ceil(total_width_needed / shingle_width)) + 3
    
    total_shingles = num_courses * shingles_per_course
    
    return {
        'num_courses': num_courses,
        'shingles_per_course': shingles_per_course,
        'max_stagger': max_stagger,
        'total_width_needed': total_width_needed,
        'total_shingles_before_trim': total_shingles
    }


def validate_face_geometry(face_width: float, face_height: float) -> Tuple[bool, List[str]]:
    """
    Validate face dimensions for shingling.
    
    Args:
        face_width: Width of face (mm)
        face_height: Height of face (mm)
    
    Returns:
        Tuple of (is_valid, error_messages)
    """
    errors = []
    
    if face_width <= 0:
        errors.append(f"Face width must be positive, got {face_width}")
    
    if face_height <= 0:
        errors.append(f"Face height must be positive, got {face_height}")
    
    # Warn if face is very small (less than one shingle)
    if face_width < 5 or face_height < 5:
        errors.append(f"Face dimensions ({face_width}x{face_height}mm) are very small for shingling")
    
    return len(errors) == 0, errors


# is_planar and calculate_face_bounds are imported from roof_geometry above.


def detect_face_orientation(bbox: Dict) -> Tuple[str, str]:
    """
    Detect orientation of a planar face based on bounding box extents.
    
    Args:
        bbox: Dict with 'x_min', 'x_max', 'y_min', 'y_max', 'z_min', 'z_max'
    
    Returns:
        Tuple of (vertical_axis, horizontal_axis) where axes are 'x', 'y', or 'z'
    """
    x_extent = bbox.get('x_max', 0) - bbox.get('x_min', 0)
    y_extent = bbox.get('y_max', 0) - bbox.get('y_min', 0)
    z_extent = bbox.get('z_max', 0) - bbox.get('z_min', 0)
    
    tolerance = 0.1  # mm
    
    # Find which axis has near-zero extent (normal to face)
    # The other two define vertical and horizontal directions
    
    if x_extent < tolerance:
        # YZ plane (normal is X)
        if y_extent >= z_extent:
            return 'z', 'y'  # Vertical = Z, Horizontal = Y
        else:
            return 'y', 'z'  # Vertical = Y, Horizontal = Z
    
    elif y_extent < tolerance:
        # XZ plane (normal is Y)
        if x_extent >= z_extent:
            return 'z', 'x'  # Vertical = Z, Horizontal = X
        else:
            return 'x', 'z'  # Vertical = X, Horizontal = Z
    
    elif z_extent < tolerance:
        # XY plane (normal is Z)
        if x_extent >= y_extent:
            return 'y', 'x'  # Vertical = Y, Horizontal = X
        else:
            return 'x', 'y'  # Vertical = X, Horizontal = Y
    
    else:
        # All three have extent - tilted face
        # Use largest as vertical
        if z_extent >= y_extent and z_extent >= x_extent:
            if x_extent > y_extent:
                return 'z', 'x'
            else:
                return 'z', 'y'
        elif y_extent >= x_extent and y_extent >= z_extent:
            if x_extent > z_extent:
                return 'y', 'x'
            else:
                return 'y', 'z'
        else:
            if y_extent > z_extent:
                return 'x', 'y'
            else:
                return 'x', 'z'


def validate_face_for_shingling(points: List[Tuple[float, float, float]],
                               min_width: float = 5.0,
                               min_height: float = 5.0) -> Tuple[bool, List[str]]:
    """
    Comprehensive validation of a face for shingling.
    
    Args:
        points: List of face vertices (x, y, z) tuples
        min_width: Minimum face width in mm
        min_height: Minimum face height in mm
    
    Returns:
        Tuple of (is_valid, error_messages)
    """
    errors = []
    
    # Check we have at least 4 vertices (a quad)
    if len(points) < 4:
        errors.append(f"Face has {len(points)} vertices, need at least 4")
        return False, errors
    
    # Check planarity
    if not is_planar(points):
        errors.append("Face is not planar - cannot generate shingles")
        return False, errors
    
    # Check bounds
    bbox = calculate_face_bounds(points)
    x_extent = bbox['x_max'] - bbox['x_min']
    y_extent = bbox['y_max'] - bbox['y_min']
    z_extent = bbox['z_max'] - bbox['z_min']
    
    # Find the two significant extents (normal to face has minimal extent)
    extents = sorted([x_extent, y_extent, z_extent])
    
    if extents[1] < min_width or extents[2] < min_height:
        errors.append(f"Face too small: {extents[1]:.1f}x{extents[2]:.1f}mm, need {min_width}x{min_height}mm minimum")
    
    # Warn about very small faces
    if extents[2] < 10:
        errors.append(f"Face height {extents[2]:.1f}mm is very small for realistic shingling")
    
    return len(errors) == 0, errors


def get_orientation_description(vertical_axis: str, horizontal_axis: str) -> str:
    """
    Get human-readable description of face orientation.
    
    Args:
        vertical_axis: 'x', 'y', or 'z'
        horizontal_axis: 'x', 'y', or 'z'
    
    Returns:
        String description like "XZ plane" or "tilted face"
    """
    axes = {vertical_axis, horizontal_axis}
    
    if axes == {'x', 'z'}:
        return "XZ plane"
    elif axes == {'y', 'z'}:
        return "YZ plane"
    elif axes == {'x', 'y'}:
        return "XY plane"
    else:
        return f"tilted {vertical_axis}{horizontal_axis} face"


def calculate_shingle_position(row: int, col: int, 
                              shingle_width: float, shingle_height: float,
                              shingle_exposure: float, stagger_pattern: str) -> Tuple[float, float]:
    """
    Calculate the U,V position of a shingle in the layout.
    
    Args:
        row: Row index (0 = bottom)
        col: Column index (0 = left)
        shingle_width: Width of shingle (mm)
        shingle_height: Height of shingle (mm)
        shingle_exposure: Exposed portion per course (mm)
        stagger_pattern: Stagger pattern type
    
    Returns:
        Tuple of (u_position, v_position) in mm
    """
    # Calculate stagger and the maximum stagger for this pattern (used as left-edge offset)
    stagger = calculate_stagger_offset(row, stagger_pattern, shingle_width)
    if stagger_pattern == "half":
        max_stagger = shingle_width / 2.0
    elif stagger_pattern == "third":
        max_stagger = shingle_width / 3.0
    else:
        max_stagger = 0.0

    # U position: starts at -max_stagger so col=0, stagger=0 lands at the left wall edge
    u = col * shingle_width + stagger - max_stagger
    
    # V position (vertical, starting one course below origin)
    v = row * shingle_exposure - shingle_exposure
    
    return u, v


def validate_collar_margin(shingle_width: float, shingle_height: float) -> float:
    """
    Calculate appropriate collar margin for trimming excess shingles.
    
    Args:
        shingle_width: Width of shingle (mm)
        shingle_height: Height of shingle (mm)
    
    Returns:
        Recommended collar margin in mm
    """
    # Margin should be 3x the largest dimension to capture stagger
    return max(shingle_width, shingle_height) * 3


def should_clip_shingles(material_thickness: float) -> bool:
    """
    Determine if individual shingles should be clipped to face boundary.
    
    Clipping is necessary when shingles would overhang significantly,
    which is problematic for 3D printing (supports on flat surfaces).
    
    Args:
        material_thickness: Thickness of shingle material (mm)
    
    Returns:
        True if shingles should be clipped (material_thickness < 1mm typical)
    """
    # If material is very thin, clipping is essential for print support placement
    # Threshold: 1mm (anything thinner needs careful support management)
    return material_thickness < 1.0


def calculate_shingle_clip_volume(face_bounds: Dict,
                                  material_thickness: float) -> Dict:
    """
    Calculate the volume for clipping shingles to face boundary.

    Creates a "clipping box" that represents the valid region for shingles
    (the face + a small margin for material thickness).

    Args:
        face_bounds: Dict with 'x_min', 'x_max', 'y_min', 'y_max', 'z_min', 'z_max'
        material_thickness: Thickness of material (mm)

    Returns:
        Dict describing the clipping volume:
            - bounds: expanded bounds with material_thickness margin
            - needs_clipping: whether clipping is necessary
    """
    margin = material_thickness  # Only expand by actual material thickness

    return {
        'x_min': face_bounds.get('x_min', 0) - margin,
        'x_max': face_bounds.get('x_max', 0) + margin,
        'y_min': face_bounds.get('y_min', 0) - margin,
        'y_max': face_bounds.get('y_max', 0) + margin,
        'z_min': face_bounds.get('z_min', 0) - margin,
        'z_max': face_bounds.get('z_max', 0) + margin,
        'needs_clipping': True
    }



# Shared functions (is_planar, calculate_face_bounds, find_eave_and_ridge_vertices,
# calculate_upslope_direction, calculate_across_roof_direction,
# get_roof_coordinate_system, find_coincident_edges,
# classify_roof_intersection, calculate_dihedral_angle,
# analyze_roof_intersection) are imported from roof_geometry above.
