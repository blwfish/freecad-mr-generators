"""
Slate Seam Cap Geometry Library v1.0.0

Pure Python geometry for slate HIP/RIDGE cap generation — courses of
overlapping caps straddling a hip or ridge seam between two roof faces,
bent to the seam's actual dihedral angle so the cap sits flush against
both faces rather than at a fixed, roof-pitch-agnostic angle.

Valleys are explicitly out of scope: real slate roofs use metal flashing
in valleys, not slate caps (see roof_seam_generator's generate_valley_flashing
for that, material-agnostic, already-existing path).

No FreeCAD dependencies — fully testable with pytest.

Shared face-orientation and hip/valley analysis, plus the generic
coursed-tile layout helpers (is_valid_clip_fragment, is_top_course_complete,
calculate_fitted_exposure), are imported from roof_geometry.py (in shared/).
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
    'is_valid_clip_fragment', 'is_top_course_complete',
    'calculate_fitted_exposure',
    # Slate-seam-specific
    'validate_parameters', 'resolve_cap_eligibility', 'is_dihedral_foldable',
    'calculate_dihedral_fold', 'calculate_wing_profile_2d',
    'calculate_cap_count',
]

# tan(half_dihedral) diverges as dihedral -> 180 deg (the two roof planes
# folding flat back on each other -- not a real, foldable ridge). 179 deg
# gives comfortable margin before the singularity while still covering
# every physically real roof pitch.
MAX_DIHEDRAL_DEGREES = 179.0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_parameters(cap_width: float, cap_length: float,
                         material_thickness: float,
                         exposure: float) -> Tuple[bool, List[str]]:
    """Validate slate seam cap parameters for physical and geometric
    soundness. Mirrors slate_generator.slate_geometry.validate_parameters:
    cap_length plays tile_height's role (the along-seam dimension of one
    cap), cap_width is the total width spanning both wings (across the
    seam, not a coursing dimension)."""
    errors = []
    if cap_width <= 0:
        errors.append(f"cap_width must be positive, got {cap_width}")
    if cap_length <= 0:
        errors.append(f"cap_length must be positive, got {cap_length}")
    if material_thickness <= 0:
        errors.append(f"material_thickness must be positive, got {material_thickness}")
    if exposure <= 0:
        errors.append(f"exposure must be positive, got {exposure}")
    if exposure > cap_length:
        errors.append(
            f"exposure ({exposure}) cannot exceed cap_length ({cap_length})")
    if material_thickness > cap_length:
        errors.append(
            f"material_thickness ({material_thickness}) cannot exceed cap_length ({cap_length})")
    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Seam classification / eligibility
# ---------------------------------------------------------------------------

def resolve_cap_eligibility(classification: str) -> Tuple[bool, str]:
    """Decide whether a hip/ridge cap should be generated for a seam,
    given roof_geometry.classify_roof_intersection's classification string.

    Only 'ridge' (roof_geometry's label for the hip/ridge case -- NOT
    'hip', despite this module's own name) is eligible. Every other value
    is rejected with a message explaining why, rather than silently
    guessing:

    - 'valley': real slate roofs use metal flashing in valleys, not slate
      caps -- this generator deliberately doesn't attempt one. Points at
      roof_seam_generator's existing material-agnostic valley flashing.
    - 'none': no shared edge was found between the two selected faces at
      all -- there's no seam to cap.
    - 'ambiguous': roof_geometry's own classifier couldn't confidently
      tell hip from valley. Critically, this branch has NO verified
      real-world trigger anywhere in this repo's test suite (checked
      2026-07-29: the only existing test for it is a tautology that
      accepts any of the three possible values). Treating 'ambiguous' as
      a safe default-to-hip would risk silently capping an actual valley
      the one time this branch fires for real -- reject instead.
    - anything else (unknown/garbage string): falls through to the same
      rejection path as 'ambiguous' -- a defensive default that is never
      treated as eligible.
    """
    if classification == 'ridge':
        return True, ''
    if classification == 'valley':
        return False, (
            "Seam classified as VALLEY, not a hip/ridge. Real slate roofs "
            "use metal flashing in valleys, not slate caps -- use "
            "roof_seam_generator's valley flashing instead."
        )
    if classification == 'none':
        return False, "No shared edge found between the two selected faces."
    # 'ambiguous' and any unrecognized value share this rejection path.
    return False, (
        f"Seam classification '{classification}' is ambiguous or unrecognized -- "
        "cannot safely determine hip vs valley. No cap generated."
    )


def is_dihedral_foldable(dihedral_degrees: float,
                          max_degrees: float = MAX_DIHEDRAL_DEGREES) -> bool:
    """Return True if a dihedral angle can be folded into a cap cross-section
    without hitting the tan(half_dihedral) singularity (calculate_dihedral_fold).

    A genuine hip/ridge classification (resolve_cap_eligibility) doesn't
    guarantee a foldable angle -- two nearly-coplanar-reversed faces can
    still classify as a ridge while having a dihedral too close to 180 deg
    to build a sane cap for. This is an independent guard, checked
    separately from hip/valley classification.
    """
    return 0.0 <= dihedral_degrees < max_degrees


# ---------------------------------------------------------------------------
# Dihedral fold cross-section
# ---------------------------------------------------------------------------

def calculate_dihedral_fold(dihedral_radians: float, cap_width: float) -> Dict:
    """Compute the bent-V cap cross-section's core geometry from the seam's
    actual dihedral angle, so the cap's peak angle matches the real roof
    pitch instead of a fixed, pitch-agnostic angle.

    half_width = cap_width / 2 (each wing spans half the total cap width).
    half_dihedral = dihedral_radians / 2.
    h_center = half_width * tan(half_dihedral) is how far above the
    wing-tip plane the ridge centerline sits: at half_dihedral=0 (a flat,
    continuous roof) this is 0 (a flat cap, correctly); as half_dihedral
    approaches 90 deg (dihedral approaching 180 deg) it diverges, which is
    exactly the singularity is_dihedral_foldable exists to reject before
    this function is ever called with such an angle.

    The resulting tent's peak angle (measured through the cap's own
    interior) is 180 - 2*half_dihedral = 180 - dihedral_degrees, which
    equals the real roof's own physical ridge angle between the two roof
    planes (dihedral_radians itself is the angle between the two faces'
    OUTWARD normals, which is the supplement of the roof planes' own
    interior angle) -- so the cap genuinely sits flush against both
    faces at their real pitch, not an approximation.

    Raises ValueError if dihedral_radians is outside [0, pi) -- this is an
    internal fail-fast contract for a caller that has already checked
    is_dihedral_foldable(degrees(dihedral_radians)); it is not a second
    UI-facing guard.
    """
    if dihedral_radians < 0 or dihedral_radians >= math.pi:
        raise ValueError(
            f"dihedral_radians must be in [0, pi), got {dihedral_radians}"
        )

    half_width = cap_width / 2.0
    half_dihedral = dihedral_radians / 2.0
    h_center = half_width * math.tan(half_dihedral)
    wing_len = math.sqrt(half_width ** 2 + h_center ** 2)

    return {
        'half_width':    half_width,
        'half_dihedral':  half_dihedral,
        'h_center':      h_center,
        'wing_len':      wing_len,
    }


def calculate_wing_profile_2d(dihedral_fold: Dict,
                               material_thickness: float) -> Dict[str, Tuple[float, float]]:
    """Compute the 7-point 2D cross-section (local x/z plane, x = across
    the seam, z = up along the bisector) of one slate seam cap: a bottom
    profile following the two wing planes (bl -> bc -> br), and a top
    profile offset by material_thickness along EACH wing's own outward
    normal (tr -> tc2 -> tc1 -> tl) -- not simply shifted straight up,
    since the wings are tilted planes and a uniform-thickness slab must be
    offset perpendicular to its own surface.

    ANCHOR CONVENTION (load-bearing for callers): z=0 in this profile is
    the wing-TIP baseline (bl/br), not the real hip/ridge line -- the
    ridge sits at bc, z=+h_center, ABOVE this baseline. A caller placing
    this profile at a real-world 3D point that lies ON the actual shared
    edge (the physically real case: the two roof planes truly meet
    there) must shift the anchor by -h_center along local_z first, or
    the whole cap ends up floating h_center above the real roof surface
    with bl/br also floating at the ridge's own height instead of
    extending down to it -- a real bug caught 2026-07-29 in
    slate_seam_proxy.py's first cut, where the anchor was placed
    directly at the real edge with no such shift.

    Flat degenerate case (h_center == 0, e.g. dihedral_radians == 0):
    both wings' outward normals collapse to the same (0, 1) (straight up),
    so tc1 == tc2 and the whole profile reduces cleanly to a flat
    rectangle -- this is the correct, expected behaviour for a flat roof,
    not a bug.

    Non-degenerate case (h_center > 0): tc1 != tc2 whenever
    material_thickness > 0, since the two wings' outward normals genuinely
    differ. The wire closes bl -> bc -> br -> tr -> tc2 -> tc1 -> tl -> bl;
    tc1/tc2 being distinct points (not one repeated point) is what keeps
    every edge non-zero-length for the downstream Part.Face/Part.Wire
    build (a repeated point produces a degenerate zero-length edge, which
    can silently produce a null face rather than raising -- see this
    repo's OCCT-consumer-invariant table in the root CLAUDE.md).
    """
    half_width = dihedral_fold['half_width']
    h_center = dihedral_fold['h_center']
    wing_len = dihedral_fold['wing_len']

    bl = (-half_width, 0.0)
    bc = (0.0, h_center)
    br = (half_width, 0.0)

    if wing_len > 0:
        # Outward normal for the left wing (tip -> peak direction, rotated
        # +90 deg/counterclockwise) and the right wing (peak -> tip
        # direction, rotated the same +90 deg for consistency -- both
        # collapse to (0, 1) at h_center == 0, confirmed by construction).
        normal_left = (-h_center / wing_len, half_width / wing_len)
        normal_right = (h_center / wing_len, half_width / wing_len)
    else:
        # Degenerate zero-width cap: no meaningful wing direction: offset
        # straight up as a safe fallback rather than dividing by zero.
        normal_left = (0.0, 1.0)
        normal_right = (0.0, 1.0)

    tl = (bl[0] + material_thickness * normal_left[0],
          bl[1] + material_thickness * normal_left[1])
    tc1 = (bc[0] + material_thickness * normal_left[0],
           bc[1] + material_thickness * normal_left[1])
    tc2 = (bc[0] + material_thickness * normal_right[0],
           bc[1] + material_thickness * normal_right[1])
    tr = (br[0] + material_thickness * normal_right[0],
          br[1] + material_thickness * normal_right[1])

    return {'bl': bl, 'bc': bc, 'br': br, 'tr': tr, 'tc2': tc2, 'tc1': tc1, 'tl': tl}


# ---------------------------------------------------------------------------
# Along-seam cap count
# ---------------------------------------------------------------------------

def calculate_cap_count(edge_length: float, exposure: float, margin: int = 2) -> int:
    """Return the number of cap courses to generate along a seam of
    edge_length, before clipping. Mirrors calculate_layout's over-generation
    margin (+3 there; margin defaults to 2 here since a 1D seam run has
    only one axis to overflow, not two): a few extra caps past the seam's
    far end guarantee the end-clip always has real overflow geometry to
    clip against (is_valid_clip_fragment) instead of landing exactly on
    the boundary.

    Degenerate inputs (edge_length <= 0 or exposure <= 0) return 0 --
    there's no meaningful seam to cover.
    """
    if edge_length <= 0 or exposure <= 0:
        return 0
    return int(math.ceil(edge_length / exposure)) + margin
