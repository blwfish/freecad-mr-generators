"""
Standing-Seam Snow Guard Geometry Library v1.0.0

Pure Python geometry for placing snow guards on a standing-seam metal
roof. Unlike snow_guard_generator (slate/shingle: a surface-mounted pad
placed anywhere in a free u/v grid), standing-seam snow guards CLAMP onto
the raised seam rib itself -- so a guard's across-slope (u) position is
not a free choice, it is fixed by wherever a real seam rib sits.

Rib phase is derived independently of standing_seam_generator's own
calculate_panel_layout/generate_panel_profile: that function's
num_panels/start_u exist purely to over-generate coverage for a tiling
OCCT-clip pattern (see standing_seam_proxy.py's _generate_panels_for_face),
a different concern from "where are the real, fully-visible rib
centerlines" -- which is simply periodic, phase-locked to the face's own
u=0 origin (see calculate_rib_u_positions' docstring for the derivation).

Like snow_guard_generator, this is a SPARSE placement (no tiling fill, no
boolean clip against the roof/seam geometry) -- the relevant OCCT-safety
invariant is "no guard position lands on the face boundary"
(shared/boundary_assertions.assert_no_boundary_coincidence), not the
tiling generators' overflow invariant.

No FreeCAD dependencies — fully testable with pytest.
"""

import math
from typing import List, Tuple

from roof_geometry import calculate_row_v_positions

__all__ = [
    # Re-exported from roof_geometry
    'calculate_row_v_positions',
    # Standing-seam-snow-guard specific
    'validate_parameters',
    'validate_margins_cover_footprint',
    'calculate_rib_u_positions',
    'calculate_seam_guard_positions',
]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_parameters(clamp_width: float, clamp_length: float, clamp_thickness: float,
                         fin_height: float, fin_base_width: float, fin_thickness: float,
                         panel_width: float) -> Tuple[bool, List[str]]:
    """Validate standing-seam snow guard clamp dimensions.

    Same dimension-relationship checks as snow_guard_geometry
    .validate_parameters (clamp_width/clamp_length here play the role
    pad_width/pad_length play there), plus one check with no slate
    analogue: clamp_width must be less than panel_width -- a clamp wider
    than one full panel repeat would visually overlap the neighboring
    seam regardless of seam_stride, which is never the intent.
    """
    errors = []
    if clamp_width <= 0:
        errors.append(f"clamp_width must be positive, got {clamp_width}")
    if clamp_length <= 0:
        errors.append(f"clamp_length must be positive, got {clamp_length}")
    if clamp_thickness <= 0:
        errors.append(f"clamp_thickness must be positive, got {clamp_thickness}")
    if fin_height <= 0:
        errors.append(f"fin_height must be positive, got {fin_height}")
    if fin_base_width <= 0:
        errors.append(f"fin_base_width must be positive, got {fin_base_width}")
    if fin_thickness <= 0:
        errors.append(f"fin_thickness must be positive, got {fin_thickness}")
    if panel_width <= 0:
        errors.append(f"panel_width must be positive, got {panel_width}")
    if fin_base_width > 0 and clamp_length > 0 and fin_base_width > clamp_length:
        errors.append(
            f"fin_base_width ({fin_base_width}) cannot exceed clamp_length ({clamp_length})")
    if fin_thickness > 0 and clamp_width > 0 and fin_thickness > clamp_width:
        errors.append(
            f"fin_thickness ({fin_thickness}) cannot exceed clamp_width ({clamp_width})")
    if clamp_width > 0 and panel_width > 0 and clamp_width >= panel_width:
        errors.append(
            f"clamp_width ({clamp_width}) must be less than panel_width ({panel_width})")
    return len(errors) == 0, errors


def validate_margins_cover_footprint(edge_margin: float, v_margin: float,
                                      clamp_width: float, clamp_length: float
                                      ) -> Tuple[bool, List[str]]:
    """Validate that edge_margin/v_margin are large enough to contain the
    guard's own clamp footprint. Same rationale as snow_guard_geometry.
    validate_margins_cover_footprint (clamp_width/clamp_length here play
    the role pad_width/pad_length play there) -- calculate_rib_u_positions
    /calculate_row_v_positions only validate a guard's bare CENTER
    position against [margin, length-margin], with no visibility into the
    clamp's half-width/half-length that standing_seam_snow_guard_proxy.py
    subtracts separately when placing the guard's corner. Whenever
    half_clamp_u > edge_margin or half_clamp_v > v_margin, the guard
    physically overhangs the real face boundary despite the center
    passing its own check (full-review finding #28, 2026-08-08).
    """
    errors = []
    half_clamp_u = clamp_width / 2.0
    half_clamp_v = clamp_length / 2.0
    if edge_margin < half_clamp_u:
        errors.append(
            f"edge_margin ({edge_margin}) must be at least clamp_width/2 "
            f"({half_clamp_u}) or the guard's clamp overhangs the rake edge")
    if v_margin < half_clamp_v:
        errors.append(
            f"v_margin ({v_margin}) must be at least clamp_length/2 "
            f"({half_clamp_v}) or the guard's clamp overhangs the eave/ridge edge")
    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Rib position (across-slope axis, "u")
# ---------------------------------------------------------------------------

def calculate_rib_u_positions(u_length: float, panel_width: float, seam_width: float,
                               edge_margin: float) -> List[float]:
    """Return the across-slope (u) centerline of every real, fully-visible
    seam rib on a face of width u_length.

    standing_seam_proxy.py's real (non-overflow-padding) panels start
    flush with the face's own u=0 origin, so seam rib centerlines recur
    at u = k * panel_width - seam_width / 2 for k = 1, 2, 3, ... This is
    independently derived here (not by calling
    standing_seam_geometry.calculate_panel_layout, whose num_panels/
    start_u answer a different question -- how many over-generated panels
    to build before clipping, not where the real ribs are).

    edge_margin is the same REQUIRED positive safety margin used
    throughout this repo's sparse-placement helpers: a rib whose center
    falls within edge_margin of either rake edge is excluded, guaranteeing
    no guard clamped to it can land on the real face boundary.

    Raises ValueError for non-positive panel_width/edge_margin, or
    seam_width outside (0, panel_width) -- mirrors
    standing_seam_geometry.validate_parameters' own
    "seam_width < panel_width" contract.
    """
    if panel_width <= 0:
        raise ValueError(f"panel_width must be positive, got {panel_width}")
    if edge_margin <= 0:
        raise ValueError(f"edge_margin must be positive, got {edge_margin}")
    if seam_width <= 0 or seam_width >= panel_width:
        raise ValueError(
            f"seam_width ({seam_width}) must be in (0, panel_width={panel_width})")

    lo, hi = edge_margin, u_length - edge_margin
    eps = 1e-9

    k_max = int(math.ceil(u_length / panel_width)) + 1
    positions = []
    for k in range(1, k_max + 1):
        center = k * panel_width - seam_width / 2.0
        if lo - eps <= center <= hi + eps:
            positions.append(center)

    return positions


# ---------------------------------------------------------------------------
# Combined seam-guard placement
# ---------------------------------------------------------------------------

def calculate_seam_guard_positions(u_length: float, v_length: float, panel_width: float,
                                    seam_width: float, seam_stride: int, num_rows: int,
                                    first_row_offset: float, row_spacing: float,
                                    edge_margin: float,
                                    v_margin: float) -> List[Tuple[int, float, float]]:
    """Return (row_index, u, v) for every seam-clamped guard.

    Every guarded row uses the SAME set of ribs (v1 does not alternate
    which ribs are guarded row-to-row -- real installations are typically
    uniform row-to-row; per-row alternation is a straightforward future
    addition, not a blocking gap here).

    seam_stride selects every Nth rib (seam_stride=1 -> every rib;
    seam_stride=3 -> every 3rd) via plain slicing (rib_u_positions
    [::seam_stride]) on the ribs ordered by position, so the exact set
    guarded is deterministic and easy to reason about. A stride larger
    than the number of available ribs is NOT an error: Python slice
    semantics always include index 0, so it deterministically guards just
    the first (lowest-u) rib rather than raising or silently guarding
    nothing -- an explicit, tested choice, not an overlooked edge case.

    Raises ValueError if seam_stride < 1, if no ribs survive the margin
    filter at all, or (propagated from calculate_rib_u_positions /
    calculate_row_v_positions) if the underlying parameters are invalid.
    """
    if seam_stride < 1:
        raise ValueError(f"seam_stride must be >= 1, got {seam_stride}")

    rib_u_positions = calculate_rib_u_positions(u_length, panel_width, seam_width, edge_margin)
    if not rib_u_positions:
        raise ValueError(
            f"no seam ribs fall within the usable range on u_length={u_length} "
            f"(panel_width={panel_width}, seam_width={seam_width}, edge_margin={edge_margin})"
        )

    guarded_u = rib_u_positions[::seam_stride]

    v_positions = calculate_row_v_positions(
        v_length, num_rows, first_row_offset, row_spacing, v_margin)

    return [
        (row_index, u, v)
        for row_index, v in enumerate(v_positions)
        for u in guarded_u
    ]
