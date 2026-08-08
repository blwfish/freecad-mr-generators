"""
Slate Tile Geometry Library v1.0.0

Pure Python geometry functions for slate tile generation.
No FreeCAD dependencies — fully testable with pytest.

Slate tiles are flat rectangles in cross-section (unlike wood shingles,
which have their own tapered-wedge profile).  The proxy applies an
optional butt-edge wedge (ButtThickness, default 3x MaterialThickness)
on top of that flat rectangle so overlapping courses show a visible
step at each butt line.

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
    is_valid_clip_fragment,
    is_top_course_complete,
    calculate_fitted_exposure,
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
    'calculate_course_v_position',
    'is_valid_clip_fragment', 'is_top_course_complete',
    'calculate_fitted_exposure',
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


def calculate_course_v_position(row: int, exposure: float,
                                face_v_length: float = None,
                                topo_eps: float = None) -> float:
    """
    Return the placement V-coordinate (course head, up-slope edge) for
    *row*, one course below origin at row=0 -- extracted from
    slate_proxy._generate_tiles_for_face's inline formula so the pipeline
    that actually produces tile geometry is pytest-testable, per this
    repo's established pattern (see clapboard_geometry.
    calculate_course_v_positions, whose docstring this mirrors).

    When *face_v_length* is given, the returned head position is nudged
    strictly away from EITHER face boundary if it would otherwise land
    within *topo_eps* of one:

    - V=face_v_length (the ridge/hip line): when *exposure* is the output
      of calculate_fitted_exposure(), an integer number of courses
      divides face_v_length exactly, so the top complete course's head
      lands EXACTLY there.
    - V=0 (the eave): row=1's head lands at EXACTLY V=0 for *any*
      exposure value, not just a fitted one -- an unconditional property
      of this row-indexing formula (v = (row-1)*exposure), not specific
      to calculate_fitted_exposure().

    _build_clip_volumes() extrudes the *whole* face, so its side faces
    trace every edge of the face -- both boundaries are equally at risk
    of the OCCT coincident-face crash class shared/boundary_assertions.py
    exists to prevent (see CLAUDE.md), not just the ridge/hip line.

    Pass face_v_length=None (the default) to get the raw, un-nudged head
    position -- needed by is_top_course_complete()'s own "at or below
    face_v_length" test, which must see the true geometric position, not
    a boundary-safety nudge.

    topo_eps defaults to 0.1% of exposure, this repo's established
    fraction-of-relevant-dimension convention (see board_batten_geometry.
    TOPO_EPS, clapboard_geometry.calculate_course_v_positions).
    """
    v = row * exposure - exposure
    if face_v_length is not None:
        if topo_eps is None:
            topo_eps = abs(exposure) * 0.001
        if abs(v - face_v_length) < topo_eps:
            v += topo_eps  # push strictly past the ridge/hip boundary
        elif abs(v) < topo_eps:
            v -= topo_eps  # push strictly past (below) the eave boundary
    return v


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
