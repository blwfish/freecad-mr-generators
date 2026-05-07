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
    # Standing-seam specific
    'validate_parameters', 'calculate_panel_layout',
    'generate_panel_profile',
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
