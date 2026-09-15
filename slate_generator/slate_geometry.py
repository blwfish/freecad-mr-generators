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


def calculate_tile_placements(u_length: float, v_length: float,
                               tile_width: float, tile_height: float,
                               exposure: float,
                               stagger_pattern: str = 'half') -> List[Dict]:
    """
    Full placement list for every slate tile that would actually survive
    to be placed on a face of the given size.

    Full-review finding freecad-mr-generators-20260915-e612#14: this
    generator's V axis was already protected against the OCCT
    coincident-face segfault class (see calculate_course_v_position's own
    docstring), but the U axis -- `u = col*tile_width + stagger -
    max_stagger`, previously inlined only in slate_proxy._generate_tiles_
    for_face -- was not, and had no pure-Python form to test either way.
    Confirmed live: stagger_pattern='none' means every row's col=0 starts
    at EXACTLY u=0 for any face width -- the left boundary never
    overflows at all, a systemic gap (the identical bug independently
    confirmed in shingle_geometry.calculate_shingle_placements, whose
    docstring this mirrors). This function is now the single source of
    truth for the row-skip AND full U/V placement logic; slate_proxy.py
    iterates over its output directly instead of maintaining its own copy.

    Caller must pass an already-fitted `exposure` (i.e. the output of
    calculate_fitted_exposure(v_length, raw_exposure)) -- this function
    does not call that itself, matching slate_proxy.py's own existing
    two-step convention (fit exposure once, then lay out courses).

    Returns a list of dicts, one per placed tile:
        {'row': int, 'col': int, 'u': float, 'v': float, 'v_butt': float}
    where (u, v) is the top-left anchor (v already nudged away from
    either V boundary by calculate_course_v_position), and v_butt = v -
    tile_height (the butt/bottom edge, needed for the V-axis boundary
    check -- slate's per-tile geometry always uses a fixed tile_height
    regardless of row, unlike shingle's starter-course exception).

    Row-skip logic (moved here verbatim from slate_proxy.py, where this
    history originally lived):

    A row is skipped entirely (never placed) once its RAW (un-nudged)
    head position already pokes past the face's own top edge (ridge/hip
    line at V=v_length) by more than stop_tolerance. Rows increase v
    monotonically, so once this trips, every subsequent row would too --
    checked explicitly each iteration rather than via break, in case that
    assumption ever stops holding.

    Unconditional as of 2026-09-14 (previously gated behind the optional
    hide_incomplete_top_course flag, generating every "+3 buffer" row
    past the ridge by default and relying on clipping to trim them).
    Since the caller is expected to pass an already-fitted exposure,
    calculate_fitted_exposure() guarantees an integer number of courses
    lands the top course exactly on the ridge/hip line -- every course
    past that one is therefore pure redundant overlap with zero
    legitimate new coverage, never a genuinely-needed partial course. For
    a flat tile that redundancy used to clip to a harmless thin sliver
    (caught by is_valid_clip_fragment's volume-ratio threshold). For a
    WEDGE tile (butt_thickness > material_thickness, the default whenever
    ButtThickness=0) it was NOT harmless: confirmed live on a real hip
    roof, the clip boundary can fall near the wedge's THICK butt end
    instead of its thin head, so a substantial, visually prominent stub
    survived well above the 5% discard threshold -- sitting right on top
    of the already-complete course below it, unhidden, at the ridge/hip
    line. hide_incomplete_top_course's own distinct behavior is now moot
    in practice (there is no longer a "genuinely incomplete" top course
    left for it to hide, since fitting always makes one exact) -- the
    FeaturePython property is left in place on the proxy side rather than
    removed, in case some future caller ever reaches this code without
    fitting.

    stop_tolerance is deliberately looser than is_top_course_complete()'s
    own exact `<=` (used as-is by the optional hide_incomplete_top_course
    feature, untouched by this function). calculate_fitted_exposure()
    computes exposure so that MATHEMATICALLY an integer number of courses
    lands exactly on v_length, but the actual float arithmetic in
    calculate_course_v_position (row*exposure - exposure) can land a few
    ULPs above the true value (confirmed live: row*exposure-exposure
    computed 15.400000000000002 for an intended-exact 15.4) --
    is_top_course_complete()'s strict `<=` would then misclassify the
    intended-exact top course itself as "incomplete" and skip it, leaving
    a real gap at the ridge instead of eliminating a redundant stub. Same
    magnitude convention as calculate_course_v_position's own nudge.
    """
    layout = calculate_layout(u_length, v_length, tile_width, exposure, stagger_pattern)
    num_courses = layout['num_courses']
    tiles_per_course = layout['tiles_per_course']
    max_stagger = layout['max_stagger']
    stop_tolerance = abs(exposure) * 0.001

    placements = []
    for row in range(num_courses):
        raw_v = calculate_course_v_position(row, exposure)
        if raw_v > v_length + stop_tolerance:
            continue

        v = calculate_course_v_position(row, exposure, v_length)
        stagger = calculate_stagger_offset(row, stagger_pattern, tile_width)

        for col in range(tiles_per_course):
            u = col * tile_width + stagger - max_stagger
            placements.append({
                'row': row, 'col': col, 'u': u, 'v': v,
                'v_butt': v - tile_height,
            })

    if not placements:
        return placements

    # U-axis boundary nudge -- see docstring above. Same "only touch what
    # needs touching" shape as calculate_course_v_position's own nudge and
    # clapboard_geometry.calculate_course_v_positions's post-loop guarantee.
    topo_eps = tile_width * 0.001

    min_u_p = min(placements, key=lambda p: p['u'])
    if min_u_p['u'] >= 0.0 - topo_eps:
        min_u_p['u'] = -topo_eps

    max_u_p = max(placements, key=lambda p: p['u'] + tile_width)
    if max_u_p['u'] + tile_width <= u_length + topo_eps:
        max_u_p['u'] = u_length + topo_eps - tile_width

    return placements
