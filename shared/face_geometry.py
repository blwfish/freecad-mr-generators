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
"""

from typing import Dict, Tuple

__version__ = "1.0.0"

_AXIS_UNIT_VECTORS = {
    'x': (1.0, 0.0, 0.0),
    'y': (0.0, 1.0, 0.0),
    'z': (0.0, 0.0, 1.0),
}


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
        having non-trivial extent).
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
        u_axis, u_length = horiz[0][1], horiz[0][0]
        v_axis = horiz[1][1]
        v_length = horiz[1][0] if horiz[1][0] > 0.001 else u_length
        is_horizontal = True

    return {
        'u_axis': u_axis, 'v_axis': v_axis,
        'u_length': u_length, 'v_length': v_length,
        'is_horizontal': is_horizontal,
    }
