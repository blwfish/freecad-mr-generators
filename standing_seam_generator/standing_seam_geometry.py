"""
Standing Seam Geometry Library v1.0.0

Pure Python geometry functions for standing seam metal roof generation.
No FreeCAD dependencies — fully testable with pytest.

Standing seam roofs use vertical panels running from eave to ridge, with
raised seam ridges at each panel boundary.  The panel cross-section (in the
U-direction across the roof) is an L-shape:

    z
    ^           ___
    |   flat   |   |   ← seam (seam_height)
    |__________|   |   ← panel_thickness
    0         fw  pw
               (flat_width = panel_width - seam_width)

Each panel is extruded along V (eave → ridge) for the full face height, then
clipped to the face boundary.

Shared face-orientation and hip/valley analysis imported from roof_geometry.py.
"""

import math
from typing import Dict, List, Tuple

# Default panel/seam dimensions (mm). Single source of truth for
# standing_seam_proxy.py's own set_defaults() AND
# standing_seam_snow_guard_generator/standing_seam_snow_guard_proxy.py's
# defaults, which must visually match these -- standing_seam_snow_guard_
# geometry.py independently re-derives rib centerlines from an assumed
# panel/seam layout rather than reading the real one, so a snow guard's
# ribs only land on the real seams if both proxies' defaults agree.
# Previously these were copy-pasted literals in both proxy files with no
# shared source of truth (full-review finding #13, 2026-08-08).
DEFAULT_PANEL_WIDTH = 3.0
DEFAULT_SEAM_WIDTH = 0.4
DEFAULT_SEAM_HEIGHT = 0.35

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

__all__ = [
    # Re-exported from roof_geometry
    'is_planar', 'calculate_face_bounds',
    'find_eave_and_ridge_vertices', 'calculate_upslope_direction',
    'calculate_across_roof_direction', 'get_roof_coordinate_system',
    'find_coincident_edges', 'classify_roof_intersection',
    'calculate_dihedral_angle', 'analyze_roof_intersection',
    'is_valid_clip_fragment',
    # Standing-seam specific
    'validate_parameters', 'calculate_panel_layout',
    'calculate_panel_placements', 'generate_panel_profile',
    'DEFAULT_PANEL_WIDTH', 'DEFAULT_SEAM_WIDTH', 'DEFAULT_SEAM_HEIGHT',
]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_parameters(panel_width: float, seam_height: float,
                        seam_width: float,
                        panel_thickness: float) -> Tuple[bool, List[str]]:
    """Validate standing seam parameters for physical soundness."""
    errors = []
    if panel_width <= 0:
        errors.append(f"panel_width must be positive, got {panel_width}")
    if seam_height <= 0:
        errors.append(f"seam_height must be positive, got {seam_height}")
    if seam_width <= 0:
        errors.append(f"seam_width must be positive, got {seam_width}")
    if panel_thickness <= 0:
        errors.append(f"panel_thickness must be positive, got {panel_thickness}")
    if seam_width >= panel_width:
        errors.append(
            f"seam_width ({seam_width}) must be less than panel_width ({panel_width})")
    if panel_thickness >= seam_height:
        errors.append(
            f"panel_thickness ({panel_thickness}) must be less than seam_height ({seam_height})")
    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def calculate_panel_layout(face_width: float, panel_width: float) -> Dict:
    """
    Calculate how many panels are needed to cover *face_width*.

    Panels start one panel_width before the face edge so clipping handles
    the boundary cleanly, mirroring the shingle generator's approach.

    Returns dict with num_panels and start_u (offset from face origin).
    """
    num_panels = int(math.ceil(face_width / panel_width)) + 2
    return {
        'num_panels': num_panels,
        'start_u':    -panel_width,  # one panel before the left edge
    }


def calculate_panel_placements(face_width: float, v_length: float,
                                panel_width: float) -> List[Dict]:
    """
    Full per-panel placement list: U position (from calculate_panel_layout,
    already overflow-protected -- see TestBoundaryOverflowRegression) plus a
    V-axis start/extent.

    Full-review finding freecad-mr-generators-20260915-e612#14: unlike the
    U axis, the V axis was never given overflow protection.
    standing_seam_proxy._generate_panels_for_face built each panel's
    extrude vector as exactly v_length starting at v=0 (the eave), so the
    panel's own end faces are flush with the clip volume's own eave/ridge
    walls (_build_clip_volumes extrudes the *same* face, whose boundary
    edges those walls trace) -- the identical coincident-boundary-face
    class documented in CLAUDE.md's OCCT failure-mode table, just on one
    shape's own extrude instead of a tiled family of elements. This
    function nudges v_start/v_extent strictly past both the eave and
    ridge/hip edges by topo_eps, this repo's established
    fraction-of-relevant-dimension convention (see board_batten_geometry.
    TOPO_EPS, slate_geometry.calculate_course_v_position).

    Returns a list of dicts, one per panel:
        {'i': int, 'u_start': float, 'v_start': float, 'v_extent': float}
    """
    layout = calculate_panel_layout(face_width, panel_width)
    n_panels = layout['num_panels']
    start_u = layout['start_u']

    topo_eps = panel_width * 0.001
    v_start = -topo_eps
    v_extent = v_length + 2 * topo_eps

    return [
        {
            'i': i,
            'u_start': start_u + i * panel_width,
            'v_start': v_start,
            'v_extent': v_extent,
        }
        for i in range(n_panels)
    ]


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def generate_panel_profile(panel_width: float, seam_height: float,
                            seam_width: float,
                            panel_thickness: float) -> List[Tuple[float, float]]:
    """
    Return the 2D cross-section profile for one panel unit as (u, z) points.

    The profile is a closed polygon representing the L-shaped cross-section:

        z=seam_h            p3------p2
                            |       |
        z=panel_thick  p5--p4       |
                       |            |
        z=0            p0-----------p1
                       u=0   fw    pw

    Points go counter-clockwise (when viewed from +V, the extrusion direction)
    so that the extruded solid's outward normal faces +V and the Part.Face wire
    closes correctly.

    flat_width = panel_width - seam_width
    """
    fw = panel_width - seam_width
    pt = panel_thickness
    sh = seam_height
    pw = panel_width

    return [
        (0.0, 0.0),   # p0 bottom-left
        (pw,  0.0),   # p1 bottom-right
        (pw,  sh),    # p2 top of seam, right
        (fw,  sh),    # p3 top of seam, left
        (fw,  pt),    # p4 flat top, right
        (0.0, pt),    # p5 flat top, left
    ]
