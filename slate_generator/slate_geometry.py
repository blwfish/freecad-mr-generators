"""
Slate Tile Geometry Library v1.0.0

Pure Python geometry functions for slate tile generation.
No FreeCAD dependencies — fully testable with pytest.

Slate tiles differ from wood shingles in one key way: they are flat
rectangles of uniform thickness (no wedge taper).  The shadow line at
each course butt comes from the overlap geometry alone.

Shared face-orientation and hip/valley analysis is imported from
roof_geometry.py (in _shared/).
"""

import math
from typing import Dict, List, Tuple

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

__all__ = [
    # Re-exported from roof_geometry
    'is_planar', 'calculate_face_bounds',
    'find_eave_and_ridge_vertices', 'calculate_upslope_direction',
    'calculate_across_roof_direction', 'get_roof_coordinate_system',
    'find_coincident_edges', 'classify_roof_intersection',
    'calculate_dihedral_angle', 'analyze_roof_intersection',
    # Slate-specific
    'validate_parameters', 'validate_stagger_pattern',
    'calculate_stagger_offset', 'calculate_layout',
]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_parameters(tile_width: float, tile_height: float,
                        material_thickness: float,
                        exposure: float) -> Tuple[bool, List[str]]:
    """Validate slate tile parameters for physical and geometric soundness."""
    errors = []
    if tile_width <= 0:
        errors.append(f"tile_width must be positive, got {tile_width}")
    if tile_height <= 0:
        errors.append(f"tile_height must be positive, got {tile_height}")
    if material_thickness <= 0:
        errors.append(f"material_thickness must be positive, got {material_thickness}")
    if exposure <= 0:
        errors.append(f"exposure must be positive, got {exposure}")
    if exposure > tile_height:
        errors.append(
            f"exposure ({exposure}) cannot exceed tile_height ({tile_height})")
    if material_thickness > tile_height:
        errors.append(
            f"material_thickness ({material_thickness}) cannot exceed tile_height ({tile_height})")
    return len(errors) == 0, errors


def validate_stagger_pattern(pattern: str) -> Tuple[bool, str]:
    """Return (True, '') for valid patterns; (False, message) otherwise."""
    valid = ['half', 'third', 'none']
    if pattern not in valid:
        return False, f"Invalid stagger pattern '{pattern}'. Must be one of: {', '.join(valid)}"
    return True, ''


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def calculate_stagger_offset(row: int, pattern: str,
                              tile_width: float) -> float:
    """Return horizontal stagger offset (mm) for *row* using *pattern*."""
    if pattern == 'half':
        return (row % 2) * (tile_width / 2.0)
    elif pattern == 'third':
        return (row % 3) * (tile_width / 3.0)
    return 0.0


def calculate_layout(face_width: float, face_height: float,
                     tile_width: float, exposure: float,
                     stagger_pattern: str = 'half') -> Dict:
    """
    Calculate slate tile layout parameters for a single roof face.

    Returns dict with num_courses, tiles_per_course, max_stagger,
    total_width_needed, total_tiles_before_trim.
    """
    num_courses = int(math.ceil(face_height / exposure)) + 3

    if stagger_pattern == 'half':
        max_stagger = tile_width / 2.0
    elif stagger_pattern == 'third':
        max_stagger = tile_width / 3.0
    else:
        max_stagger = 0.0

    total_width_needed = face_width + 2 * max_stagger
    tiles_per_course = int(math.ceil(total_width_needed / tile_width)) + 3

    return {
        'num_courses':            num_courses,
        'tiles_per_course':       tiles_per_course,
        'max_stagger':            max_stagger,
        'total_width_needed':     total_width_needed,
        'total_tiles_before_trim': num_courses * tiles_per_course,
    }
