"""
face_geometry.py — pure derivation of a planar face's own U/V coordinate
axes from its bounding-box extents and normal.

Extracted from brick_generator/brick_geometry.py (added there 2026-09-13 as
compute_face_axes(), itself extracted from brick_proxy.py's
_get_face_coordinate_system()) into shared/ so this logic is positioned as
generic infrastructure: shared/corner_detection.py's two-face-corner
auto-discovery needs the exact same axis derivation, and it isn't
brick-specific -- any generator that needs to know "which edge of this
face is U=0" (clapboard, bead_board, a future smart_trim redesign) can use
it directly instead of reimplementing or importing through brick_geometry.

brick_geometry.py re-exports compute_face_axes so existing imports
(`from brick_geometry import compute_face_axes`, and brick_proxy.py's
`_bg.compute_face_axes` module-attribute access) keep working unchanged.

select_widen_edge()/widen_offset_sign() (added 2026-09-14) are the pure
half of BrickProxy's corner-seam-gap fix ("Part 8"): each independently-
built wall skin is offset outward along its OWN face normal, so at a real
90-degree corner two such skins move apart in different 3D directions and
leave a visible gap. The fix widens one wall's own boundary wire outward
by its skin depth at the corner edge (the Primary side only) before that
wall's skin is built -- these two functions decide WHICH wire edge is the
widen target and WHICH direction to move it, kept FreeCAD-type-free so the
decision logic is pytest-testable without FreeCAD; the actual
Part.Vertex/Part.makePolygon wire surgery lives in brick_proxy.py's
_widen_face_boundary(), which consumes these.
"""

from typing import Dict, List, Sequence, Tuple

__version__ = "1.2.0"

_AXIS_UNIT_VECTORS = {
    'x': (1.0, 0.0, 0.0),
    'y': (0.0, 1.0, 0.0),
    'z': (0.0, 0.0, 1.0),
}

# ---------------------------------------------------------------------------
# Disconnected-glyph-island bbox containment
# ---------------------------------------------------------------------------
#
# Moved here from station_sign_generator/station_sign_geometry.py (full-
# review finding freecad-mr-generators-20260915-e612#06): this logic
# groups 2D wire outlines into (outer, [holes...]) islands by bounding-box
# containment -- the way a glyph like 'i' or 'j' (a stem plus a separate
# dot) or a glyph with a true hole (like 'o' or 'e') needs to be
# interpreted for Part.Face construction. It is generic text/glyph
# infrastructure, not station-sign-specific -- label_generator needed the
# exact same algorithm and had drifted into an independent, untested,
# FreeCAD-only inline copy (label_proxy.py's old _wires_to_faces) that
# reproduced a bug already fixed once here. station_sign_geometry.py
# re-exports both names so its own existing imports/tests keep working
# unchanged.

BBox = Tuple[float, float, float, float]  # (xmin, xmax, ymin, ymax)


def bbox_contains(outer: BBox, inner: BBox, eps: float = 1e-6) -> bool:
    """
    Return True if *inner* is contained within *outer*, to within *eps*.

    *eps* is a tolerance in both directions (an inner bbox extending
    infinitesimally past outer's edge, within eps, still counts as
    contained) -- matches Part.Wire.BoundBox comparisons where floating-
    point glyph coordinates rarely land on an exact boundary.
    """
    o_xmin, o_xmax, o_ymin, o_ymax = outer
    i_xmin, i_xmax, i_ymin, i_ymax = inner
    return (i_xmin >= o_xmin - eps and i_xmax <= o_xmax + eps and
            i_ymin >= o_ymin - eps and i_ymax <= o_ymax + eps)


def group_wire_bboxes_into_islands(bboxes: Sequence[BBox],
                                    eps: float = 1e-6) -> List[List[int]]:
    """
    Group wire indices into (outer, [holes...]) islands by bounding-box
    containment, the way a glyph like 'i' or 'j' (a stem plus a separate
    dot) or a glyph with a true hole (like 'o' or 'e') needs to be
    interpreted: bboxes with no containing parent are "outer" wires; every
    bbox contained within an outer wire's bbox joins that outer wire's
    group (so Part.Face(group) treats it as a hole, not a separate face).

    Returns a list of groups, each group a list of indices into *bboxes*
    with the outer wire's index first. A bbox that is both an "outer" wire
    (nothing contains it) and not contained by anything starts its own
    singleton group if it has no contained children.

    Degenerate inputs:
    - Fewer than 2 bboxes: every non-empty input is its own single-element
      group (there's nothing for it to contain or be contained by).
    - A single bbox: same as above, returns [[0]] (or [] for empty input).
    """
    n = len(bboxes)
    if n == 0:
        return []
    if n == 1:
        return [[0]]

    # When two bboxes mutually contain each other (equal or near-equal
    # within eps -- e.g. two differently-shaped glyph-outline wires that
    # coincidentally share a bounding box), the naive "j contains i -> i
    # is not outer" rule marks BOTH of them non-outer (each sees the other
    # as its container). Neither then starts a group, and since only an
    # outer wire can start a group, neither is ever added as a hole to
    # anything else either -- both silently vanish from the output with no
    # error. Break the tie deterministically by index so exactly one of a
    # mutually-containing pair stays "outer" (the lower index) and the
    # other becomes its hole, instead of both cancelling out to nothing.
    is_outer = [True] * n
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if not bbox_contains(bboxes[j], bboxes[i], eps):
                continue
            if bbox_contains(bboxes[i], bboxes[j], eps) and i < j:
                continue
            is_outer[i] = False
            break

    used = [False] * n
    groups = []
    for i in range(n):
        if not is_outer[i] or used[i]:
            continue
        used[i] = True
        group = [i]
        for j in range(n):
            if not used[j] and not is_outer[j] and bbox_contains(bboxes[i], bboxes[j], eps):
                group.append(j)
                used[j] = True
        groups.append(group)

    return groups


def compute_face_axes(x_range: float, y_range: float, z_range: float,
                       normal: Tuple[float, float, float]) -> Dict:
    """
    Pure-math derivation of a face's own U/V coordinate system: given a
    face's outer-wire bounding-box extents along the three global axes and
    its normal, determine which global axis is U (horizontal-along-wall)
    and which is V (course height), plus their lengths, and whether the
    face is "horizontal" (a floor/roof deck, where the usual vertical-V
    wall convention doesn't apply).

    U and V are always exactly one of the global axes ('x', 'y', or 'z')
    in its positive direction -- never negated to align with the normal,
    and never chosen by a winding rule. This means which physical edge of
    a face is U=0 depends only on that face's own bounding-box minimum
    corner in the global frame, NOT on which way its normal points: two
    faces with opposite outward normals but the same footprint get the
    same U=0 edge. This is the fact shared/corner_detection.py relies on,
    and it is NOT symmetric around a building's perimeter -- see that
    module's docstring for a worked example (adjacent walls can land on
    the same side, e.g. both "left," rather than opposite sides).

    Args:
        x_range, y_range, z_range: the face's outer-wire bounding-box
            extent along each global axis (always >= 0).
        normal: the face's outward normal as an (x, y, z) tuple.

    Returns:
        {'u_axis': 'x'|'y'|'z', 'v_axis': 'x'|'y'|'z',
         'u_length': float, 'v_length': float, 'is_horizontal': bool}

    Raises:
        ValueError: the face has no meaningful horizontal extent (a
        horizontal face — floor/roof deck — with fewer than two axes
        having non-trivial extent), or is a degenerate sliver (one
        horizontal axis has extent but the other is ~0) — this never
        silently substitutes u_length for a missing v_length.
    """
    axes = sorted([(x_range, 'x'), (y_range, 'y'), (z_range, 'z')], reverse=True)

    z_axis = next((a for a in axes if a[1] == 'z'), None)
    others = [a for a in axes if a[1] != 'z']

    if z_axis and z_axis[0] > 0.001:
        v_axis, v_length = 'z', z_axis[0]
        best_axis, best_len = None, 0.0
        for rng, name in others:
            nx, ny, nz = _AXIS_UNIT_VECTORS[name]
            dot = abs(nx * normal[0] + ny * normal[1] + nz * normal[2])
            if dot < 0.5 and rng > best_len:
                best_axis, best_len = name, rng
        if best_axis is None:
            best_axis, best_len = others[0][1], others[0][0]
        u_axis, u_length = best_axis, best_len
        is_horizontal = False
    else:
        horiz = [(r, n) for r, n in axes if n != 'z']
        horiz.sort(reverse=True)
        if len(horiz) < 2 or horiz[0][0] < 0.001:
            raise ValueError("Face has no meaningful horizontal extent.")
        if horiz[1][0] < 0.001:
            raise ValueError(
                f"Face is a degenerate sliver: {horiz[0][1]}_range="
                f"{horiz[0][0]!r} but {horiz[1][1]}_range={horiz[1][0]!r} "
                f"has no meaningful extent.")
        u_axis, u_length = horiz[0][1], horiz[0][0]
        v_axis, v_length = horiz[1][1], horiz[1][0]
        is_horizontal = True

    return {
        'u_axis': u_axis, 'v_axis': v_axis,
        'u_length': u_length, 'v_length': v_length,
        'is_horizontal': is_horizontal,
    }


def select_widen_edge(candidates: List[Tuple], side: str, tol: float = 1e-6):
    """
    Given a face's V-parallel wire edges (candidates for a corner-seam
    widen target), select the one at the U extreme named by `side`.

    Args:
        candidates: list of (identifier, u_coordinate) pairs, one per
            V-parallel wire edge on the face's OuterWire. `identifier` is
            opaque to this function -- the caller's own way of looking the
            edge back up (e.g. an index into an ordered edge/vertex list)
            -- it is only ever returned, never inspected or compared.
        side: 'left' selects the minimum-u candidate (the u=0 boundary
            edge); 'right' selects the maximum-u candidate (the
            u=u_length boundary edge).
        tol: candidates within `tol` of the extreme are considered tied.

    Returns:
        The `identifier` of the selected candidate.

    Raises:
        ValueError: `side` is not 'left'/'right'; `candidates` is empty
            (no V-parallel edge exists on this wire -- nothing to widen);
            or more than one candidate ties for the extreme within `tol`.
            The tie case matters concretely: a door/window bay notch whose
            own edge happens to sit at the same u-extreme as the wall's
            real corner edge would otherwise be picked arbitrarily,
            silently widening the wrong edge or corrupting the opening.
            Never guessed -- surfaced to the caller instead.
    """
    if side not in ('left', 'right'):
        raise ValueError(f"side must be 'left' or 'right', got {side!r}")
    if not candidates:
        raise ValueError(
            "No V-parallel wire edge found -- cannot widen a boundary "
            "that doesn't exist on this face")

    us = [u for _, u in candidates]
    extreme = min(us) if side == 'left' else max(us)
    matches = [ident for ident, u in candidates if abs(u - extreme) <= tol]
    if len(matches) != 1:
        raise ValueError(
            f"Ambiguous {side} widen target: {len(matches)} V-parallel "
            f"wire edges tie at u={extreme!r} (within tol={tol}) -- "
            f"refusing to guess which one is the real corner edge")
    return matches[0]


def widen_offset_sign(side: str) -> float:
    """
    Sign to apply along u_vec when widening a face's boundary on `side`.

    'left' (the u=0 edge) extends outward in the negative-u direction
    (returns -1.0, moving the edge to u<0); 'right' (the u=u_length edge)
    extends outward in the positive-u direction (returns +1.0, moving the
    edge to u>u_length). This is widen-only -- no shrink use case exists
    anywhere in this codebase -- so callers multiply this by a positive
    delta, never a negative one.

    Raises:
        ValueError: `side` is not 'left' or 'right'.
    """
    if side == 'left':
        return -1.0
    if side == 'right':
        return 1.0
    raise ValueError(f"side must be 'left' or 'right', got {side!r}")
