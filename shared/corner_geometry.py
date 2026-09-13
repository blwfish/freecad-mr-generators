"""
corner_geometry.py — pure classifiers for detecting real building corners
between two adjacent wall faces.

Extracted from quoin_generator/quoin_geometry.py (v1.2.0, added 2026-09-13)
into shared/ so this logic is positioned as generic infrastructure rather
than brick/quoin-specific: clapboard_generator and bead_board_generator have
their own unaddressed corner problem (independently-generated skins overlap
at real building corners with no miter treatment), and smart_trim_generator
-- the generator that would eventually be the corner-trim solution for
siding -- is not designed around two-face corners at all yet. This module
(and shared/corner_detection.py, which orchestrates it against real FreeCAD
geometry) is the reusable building block whichever of those eventually gets
fixed should build on, rather than reinventing corner classification.

quoin_geometry.py re-exports both functions so existing imports
(`from quoin_geometry import classify_dihedral, classify_edge_position`)
keep working unchanged.
"""

__version__ = "1.0.0"


def classify_dihedral(cos_dihed: float, is_convex: bool, tol: float = 0.05) -> str:
    """
    Classify the angle between two adjacent wall faces from the cosine of
    their dihedral angle (cos_dihed = outward_normal_1.dot(outward_normal_2))
    plus a separately-determined convexity sign.

    Two outward normals meeting at a 90-degree angle have cos_dihed == 0
    regardless of whether the corner is convex (a real exterior building
    corner) or concave (an interior reveal, e.g. an inset doorway) -- the
    dot product alone cannot tell them apart, which is why convexity must
    be determined separately (shared/corner_detection.py does this via a
    centroid-vs-plane test) and passed in here rather than derived.

    Args:
        cos_dihed: dot product of the two faces' outward unit normals.
        is_convex: True if the corner is convex (bulges outward, a real
            exterior corner); False if concave (an interior reveal).
        tol: half-width of the tolerance band around 0.0 (the 90-degree
            bands) and around ±1.0 (the coplanar/folded-back bands).

    Returns one of:
        'convex_90'   -- a real, quoin-eligible exterior building corner
        'concave_90'  -- an interior corner; not a quoin corner
        'coplanar'    -- the two faces are (nearly) flush -- not a corner
        'ambiguous'   -- cos_dihed falls in none of the above bands;
                         never guessed, always reported so the caller can
                         flag it for manual review rather than silently
                         skip or misclassify it.
    """
    if abs(cos_dihed - 1.0) < tol:
        return 'coplanar'
    if abs(cos_dihed) < tol:
        return 'convex_90' if is_convex else 'concave_90'
    return 'ambiguous'


def classify_edge_position(coord: float, length: float, tol: float = 0.01) -> str:
    """
    Classify a shared-corner coordinate against one face's own U axis (per
    shared/face_geometry.compute_face_axes) as that face's Left edge
    (u≈0), Right edge (u≈length), or ambiguous.

    Checks both bands before returning either, rather than checking "near
    left" first and returning early: a face narrower than 2*tol has
    overlapping Left/Right bands, and silently preferring whichever check
    happens to run first would misclassify it instead of flagging the
    genuine ambiguity (the Syntactic-Semantic Seam Rule this project
    follows: two conditions that can both match must not be resolved by
    accident of check order).

    Args:
        coord: the corner's position along this face's U axis (0 at this
            face's own bbox-min corner, per compute_face_axes -- NOT
            necessarily the same physical side for every face at a shared
            corner; see shared/corner_detection.py's module docstring).
        length: this face's U-axis length (u_length).
        tol: absolute distance tolerance, same units as coord/length. Not
            a fraction of `length` -- callers should pick a tolerance
            appropriate to the model's scale (e.g. a fraction of the
            mortar joint thickness), since a fixed fraction of `length`
            would let a large wall tolerate a much sloppier corner match
            than a small one.

    Returns 'left', 'right', or 'ambiguous' (including when both bands
    overlap on a very narrow face, or when coord falls in neither band).
    """
    near_left = abs(coord) < tol
    near_right = abs(coord - length) < tol
    if near_left and near_right:
        return 'ambiguous'
    if near_left:
        return 'left'
    if near_right:
        return 'right'
    return 'ambiguous'
