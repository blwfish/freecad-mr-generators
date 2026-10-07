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
    is_valid_clip_fragment,
)

# Starter course (row 0: a flat box one exposure tall, vs. the wedge profile of
# every other row).  Switched OFF -- it has never rendered.  Row 0 sits at
# v_row = -exposure, wholly below the eave, so the survival rule below always
# skips it (swept 3375 face/shingle/exposure combinations: zero starters, and
# the pre-39d382a inline code skipped it the same way).  The proxy's starter
# branch (shingle_proxy._generate_shingles_for_face) is kept for a possible
# revisit.  Setting this True does NOT revive the starter by itself: row 0
# would still hit the same survival rule and be skipped; a real starter needs
# its position (v_row) and that rule rethought first.
ENABLE_STARTER_COURSE = False


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


# is_planar and calculate_face_bounds are imported from roof_geometry above.


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


def calculate_shingle_placements(u_length: float, v_length: float,
                                  shingle_width: float, shingle_height: float,
                                  shingle_exposure: float,
                                  stagger_pattern: str = "half") -> List[Dict]:
    """
    Full placement list for every shingle that would actually survive to
    be placed on a face of the given size.

    Full-review finding freecad-mr-generators-20260915-e612#14: this
    generator's boundary-overflow invariant (courses must extend past the
    face edges, or OCCT's common() Boolean risks a coincident-face
    segfault -- see this repo's CLAUDE.md) had no test coverage, because
    the per-shingle position AND the row-skip/row-break survival logic
    that decides which courses actually get placed were both inlined
    directly in shingle_proxy.py's _generate_shingles_for_face -- this
    function (calculate_shingle_position) already existed with the right
    U/V formula but was dead (the proxy inlined its own copy instead),
    and the skip/break logic had no pure-Python form at all. This
    function is now the single source of truth for both: the raw grid
    calculate_layout() produces, filtered by the same "less than half the
    shingle's own height lies on the face" survival rule the proxy used
    to apply only to itself. shingle_proxy.py now iterates over this
    function's output directly instead of maintaining its own copy of
    the loop.

    Returns a list of dicts, one per placed shingle:
        {'row': int, 'col': int, 'u': float, 'v': float,
         'v_butt': float, 'is_starter': bool}
    where (u, v) is the top-left anchor (calculate_shingle_position's own
    convention), v_butt is the bottom edge of the shingle (v - the
    course's own height: shingle_exposure for row 0, shingle_height for
    every other row), and is_starter is True only for row 0 (the
    rectangular starter course, vs. every other row's tapered wedge
    profile).  While ENABLE_STARTER_COURSE is False (the default) row 0 is
    never placed, so is_starter is always False in the result.
    """
    layout = calculate_layout(u_length, v_length, shingle_width,
                              shingle_exposure, stagger_pattern)
    num_courses = layout['num_courses']
    shingles_per_course = layout['shingles_per_course']

    placements = []
    for row in range(num_courses):
        is_starter = (row == 0)
        if is_starter and not ENABLE_STARTER_COURSE:
            continue
        v_row = row * shingle_exposure - shingle_exposure
        v_h = shingle_exposure if is_starter else shingle_height
        v_butt = v_row - v_h
        v_on_face = min(v_row, v_length) - max(v_butt, 0.0)
        if v_on_face < v_h * 0.5:
            if v_butt >= 0.0:
                break
            continue

        for col in range(shingles_per_course):
            u, v = calculate_shingle_position(
                row, col, shingle_width, shingle_height,
                shingle_exposure, stagger_pattern)
            placements.append({
                'row': row, 'col': col, 'u': u, 'v': v,
                'v_butt': v_butt, 'is_starter': is_starter,
            })

    if not placements:
        return placements

    # Full-review finding freecad-mr-generators-20260915-e612#14: discovered
    # live while writing the boundary-overflow test this fix was originally
    # just meant to close -- calculate_layout's "+3 safety margin" guarantees
    # ENOUGH courses/columns exist, but not that the union of their extents
    # strictly overflows the face on every axis. Two confirmed real,
    # previously-undetected cases (no test existed to catch either):
    #   - v_length an exact multiple of shingle_exposure: the surviving top
    #     course's head can land EXACTLY at v_length (verified:
    #     u_length=3.5, v_length=1.5 with the defaults below).
    #   - stagger_pattern='none': zero stagger means every row's col=0
    #     starts at EXACTLY u=0 -- verified live across u_length=5..100mm,
    #     the left edge never overflows regardless of face size, a
    #     systemic gap, not a narrow edge case.
    # Both are the exact OCCT common() coincident-face segfault risk this
    # repo's CLAUDE.md documents. Nudge whichever placement(s) define the
    # union's own extreme edge, only if it isn't already strictly past the
    # boundary -- same "only touch what needs touching" shape as
    # clapboard_geometry.calculate_course_v_positions's post-loop guarantee.
    topo_eps = max(shingle_width, shingle_height) * 0.001

    min_u_p = min(placements, key=lambda p: p['u'])
    if min_u_p['u'] >= 0.0 - topo_eps:
        min_u_p['u'] = -topo_eps

    max_u_p = max(placements, key=lambda p: p['u'] + shingle_width)
    if max_u_p['u'] + shingle_width <= u_length + topo_eps:
        max_u_p['u'] = u_length + topo_eps - shingle_width

    min_v_p = min(placements, key=lambda p: p['v_butt'])
    if min_v_p['v_butt'] >= 0.0 - topo_eps:
        min_v_p['v_butt'] = -topo_eps

    max_v_p = max(placements, key=lambda p: p['v'])
    if max_v_p['v'] <= v_length + topo_eps:
        max_v_p['v'] = v_length + topo_eps

    return placements


# Shared functions (is_planar, calculate_face_bounds, find_eave_and_ridge_vertices,
# calculate_upslope_direction, calculate_across_roof_direction,
# get_roof_coordinate_system, find_coincident_edges,
# classify_roof_intersection, calculate_dihedral_angle,
# analyze_roof_intersection) are imported from roof_geometry above.


def chamfer_failure_message(failed: int, attempted: int, chamfer: float,
                            wedge_thickness: float, first_error) -> str:
    """Report-view text for shingles whose V-groove chamfer could not be cut.

    Without the groove, neighbouring shingles tile edge to edge and fuse into
    one strip on 3D-print export, so this must be visible.  A chamfer at or
    above the wedge thickness is the known cause (OCCT cannot chamfer more
    than the adjoining face allows), so name it when it applies.
    """
    msg = (f"ShingleGenerator: V-groove chamfer FAILED on {failed} of "
           f"{attempted} shingles ({chamfer:g} mm) -- those shingles have no "
           f"groove and will fuse with their neighbours when exported.")
    if chamfer >= wedge_thickness:
        msg += (f" Chamfer {chamfer:g} mm is not smaller than the wedge "
                f"thickness {wedge_thickness:g} mm; reduce Chamfer (or set it "
                f"to 0 for auto) or increase WedgeThickness.")
    if first_error:
        msg += f" First error: {first_error}"
    return msg + "\n"
