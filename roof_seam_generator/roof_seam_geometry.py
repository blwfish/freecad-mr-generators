"""
Roof Seam Geometry Library v1.0.0

Pure Python geometry functions extracted from roof_seam_proxy.py's inline
math -- no FreeCAD imports, importable by pytest.

roof_seam_generator previously had no *_geometry.py module and no tests of
any kind: every threshold/loop/degenerate-guard in the proxy (a
`while t < edge_len` cap-placement loop, an exposure<=0 guard whose own
comment notes getting it wrong hangs FreeCAD's GUI thread forever, a
taper<1e-6 branch, near-zero-vector guards) was untested (full-review
finding freecad-mr-generators-20260808-a0b9#19). This module extracts the
genuinely FreeCAD-independent pieces -- cap placement spacing along an
edge, and the 2D hip-cap cross-section profile math -- so they can be
pinned with real edge-case tests. The 3D shape construction itself
(Part.Face/Part.Wire/extrude) stays in roof_seam_proxy.py, since it
inherently needs FreeCAD's geometry kernel.

Version History:
- 1.0.0: Initial extraction (2026-08-08).
"""

import math
from typing import List, Tuple, Dict


def validate_exposure(exposure: float, caller_name: str = "roof_seam_generator") -> None:
    """Raise ValueError if exposure is not strictly positive.

    The cap-placement loop this feeds advances by `t += exposure` each
    iteration; exposure<=0 makes t never reach edge_len, hanging FreeCAD's
    GUI thread at 100% CPU forever (confirmed live, 2026-08-08).
    """
    if exposure <= 0:
        raise ValueError(
            f"{caller_name}: exposure must be positive to generate caps, "
            f"got {exposure}")


def calculate_cap_positions(edge_len: float, exposure: float) -> List[float]:
    """Return the sequence of t-offsets (distance along the seam edge, from
    its low end) at which to place a cap/tile, replacing the
    `t = 0.0; while t < edge_len: ...; t += exposure` loop pattern
    previously inlined 3 times in roof_seam_proxy.py (generate_hip_caps,
    generate_slate_hip_caps -- generate_metal_hip_strip places a single
    continuous strip and doesn't loop).

    Preconditions:
        - edge_len: must be >= 0
        - exposure: must be > 0 (call validate_exposure() first)

    Postconditions:
        - every returned value satisfies 0 <= t < edge_len
        - the list is empty iff edge_len <= 0
        - values are strictly increasing, spaced by exactly `exposure`
    """
    validate_exposure(exposure)
    if edge_len <= 0:
        return []
    positions = []
    t = 0.0
    while t < edge_len:
        positions.append(t)
        t += exposure
    return positions


def calculate_hip_cap_profile(half_width: float, mat_thick: float,
                               cos_dihed: float, angle_depth: float,
                               max_h_center_ratio: float = 50.0) -> Dict:
    """Compute the 2D cross-section profile for a hip cap straddling a
    seam, given the two adjacent faces' dihedral angle (as cos_dihed, the
    dot product of their two outward unit normals) and the cap's half
    width / material thickness.

    This is the pure-math continuation of roof_seam_proxy.py's
    generate_hip_caps: the proxy computes cos_dihed from two 3D face
    normals (n1_out.dot(n2_out)) and passes it in here; everything
    downstream of that dot product was previously inline float/trig math
    with zero test coverage.

    Degenerate-geometry guard: as the two faces approach anti-parallel
    (cos_dihed -> -1, i.e. dihed -> 180 degrees -- two faces folded almost
    flat back onto each other, an unusual but real degenerate input, e.g.
    a near-flat "ridge" from a modeling mistake), `h_center = half_width *
    tan(half_dihed)` blows up toward infinity as half_dihed approaches 90
    degrees (tan's own singularity there) -- previously undetected because
    this file had no tests at all. Rejected via max_h_center_ratio
    (h_center is capped relative to half_width; beyond that ratio the cap
    geometry is not physically meaningful) rather than a raw angle
    threshold, since it's h_center's magnitude that actually breaks
    downstream shape construction.

    Returns a dict with the 2D points (as (x, z) tuples) and derived
    values needed to build the cap wire: bl_2d, bc_2d, br_2d, tl_2d,
    tc1_2d, tc2_2d, tr_2d, dome_mid_2d, taper, cap_lift, dihed.

    Preconditions:
        - half_width: must be > 0
        - mat_thick: must be > 0
        - cos_dihed: must be in [-1, 1]
        - angle_depth: must be >= 0 (0 = no taper)

    Postconditions:
        - result['taper'] >= 0
        - if angle_depth == 0, result['taper'] == 0 (no wedge cut)
    """
    if half_width <= 0:
        raise ValueError(f"calculate_hip_cap_profile: half_width must be > 0, got {half_width}")
    if mat_thick <= 0:
        raise ValueError(f"calculate_hip_cap_profile: mat_thick must be > 0, got {mat_thick}")
    if not (-1.0 - 1e-9 <= cos_dihed <= 1.0 + 1e-9):
        raise ValueError(f"calculate_hip_cap_profile: cos_dihed must be in [-1, 1], got {cos_dihed}")

    taper = angle_depth * mat_thick

    dihed = math.acos(max(-1.0, min(1.0, cos_dihed)))
    half_dihed = dihed / 2.0
    cap_lift = mat_thick * math.cos(half_dihed)

    # tan(half_dihed) diverges as half_dihed -> pi/2 (cos_dihed -> -1).
    # Guard before computing rather than after, so the failure is a clear
    # ValueError instead of an enormous or inf/nan cap shape downstream.
    cos_half = math.cos(half_dihed)
    if abs(cos_half) < 1e-9:
        raise ValueError(
            f"calculate_hip_cap_profile: dihedral angle too close to 180 "
            f"degrees (cos_dihed={cos_dihed}) -- cap geometry is degenerate")
    h_center = half_width * math.tan(half_dihed)
    if abs(h_center) > half_width * max_h_center_ratio:
        raise ValueError(
            f"calculate_hip_cap_profile: dihedral angle too close to 180 "
            f"degrees (cos_dihed={cos_dihed}) -- h_center={h_center} would "
            f"produce a physically meaningless cap shape")

    wing_len = math.sqrt(half_width ** 2 + h_center ** 2)
    # wing_len == 0 only if half_width == 0, already rejected above.
    nw = h_center / wing_len
    nz = half_width / wing_len

    bl_2d = (-half_width, cap_lift - h_center)
    bc_2d = (0.0, cap_lift)
    br_2d = (half_width, cap_lift - h_center)
    tl_2d = (bl_2d[0] - nw * mat_thick, bl_2d[1] + nz * mat_thick)
    tc1_2d = (bc_2d[0] - nw * mat_thick, bc_2d[1] + nz * mat_thick)
    tc2_2d = (bc_2d[0] + nw * mat_thick, bc_2d[1] + nz * mat_thick)
    tr_2d = (br_2d[0] + nw * mat_thick, br_2d[1] + nz * mat_thick)

    chord_2d = math.sqrt((tc2_2d[0] - tc1_2d[0]) ** 2 + (tc2_2d[1] - tc1_2d[1]) ** 2)
    dome_sagitta = chord_2d * 0.082
    dome_mid_2d = ((tc1_2d[0] + tc2_2d[0]) / 2.0,
                   (tc1_2d[1] + tc2_2d[1]) / 2.0 + dome_sagitta)

    return {
        'bl_2d': bl_2d, 'bc_2d': bc_2d, 'br_2d': br_2d,
        'tl_2d': tl_2d, 'tc1_2d': tc1_2d, 'tc2_2d': tc2_2d, 'tr_2d': tr_2d,
        'dome_mid_2d': dome_mid_2d,
        'taper': taper,
        'cap_lift': cap_lift,
        'dihed': dihed,
    }
