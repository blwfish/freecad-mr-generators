"""
corner_detection.py — FreeCAD-coupled orchestration for auto-discovering
which pairs of wall faces on a base solid form real 90-degree building
corners, and which edge (Left/Right) of each face the corner falls on.

Originally built (2026-09-13) under quoin_generator/ for BrickProxy's
LeftQuoin/RightQuoin, then relocated here the same day: this is generic
two-face-corner infrastructure, not brick/quoin-specific.
clapboard_generator/bead_board_generator have their own unaddressed corner
problem (their independently-generated skins overlap at real building
corners with no miter -- clapboard_geometry.py's is_building_corner()
exists but is dead code, never called from the proxy), and
smart_trim_generator -- the generator that would eventually be the
corner-trim solution for siding -- isn't designed around two-face corners
at all yet (it only detects corners within one face's own boundary
polygon). Whichever of those eventually gets fixed should build on this
module rather than reinventing corner classification.

Two things this module does NOT do, on purpose:

1. It never guesses. A candidate pair whose dihedral angle or edge
   position falls outside the documented tolerance bands is reported in
   the 'ambiguous' list with a reason, never silently classified one way
   or the other (see corner_geometry.classify_dihedral /
   classify_edge_position, which this module is a thin FreeCAD-facing
   wrapper around).

2. It never assigns which face is "Primary" at a corner. Per
   quoin_geometry.py's own docstring (its Primary/Secondary convention
   predates and motivated this module), Primary/Secondary is an
   arbitrary, non-derivable modeler's choice -- there is no geometric
   fact that makes one face "more primary" than the other. assign_primary()
   below applies one simple, documented, override-able convention (lower
   face index wins) rather than pretending this is computed.

IMPORTANT — Left/Right assignment is NOT symmetric around a building's
perimeter. Which edge of a face is "Left" (u=0) depends only on that
face's own bounding-box-minimum corner in the global frame (see
face_geometry.compute_face_axes), never on which way its normal points
or on any "walk around the building" convention. Worked example (the
equipment-hut-demo.FCStd building this module was built against, 2026-09):

    South wall (Face5, normal -Y): u_vec=+X, origin.x=XMin
      -> the SW corner (meets the west wall) lands at u=0 (Left)
      -> the SE corner (meets the south door pier) lands at u=length (Right)
    West wall (Face6, normal -X): u_vec=+Y, origin.y=YMin
      -> the SW corner (meets the south wall) ALSO lands at u=0 (Left)
      -> the NW corner (meets the north wall) lands at u=length (Right)

So the SW corner is Left/Left on its two faces, not Left/Right as a naive
"adjacent walls take opposite roles" assumption would predict -- and the
north door pier's one real corner (meeting the north wall) lands on its
*right* edge only, which is exactly the case that motivated relaxing
BrickGeometry's right_quoin constraint (see brick_geometry.py's 5.2.0
changelog entry). Never assume a pairing type (Left/Left, Right/Right, or
Left/Right) without computing it per-face.
"""

from typing import Dict, List

import FreeCAD as App

VERSION = "1.1.0"

from freecad_utils import find_shared_edge  # noqa: E402
from corner_geometry import classify_dihedral, classify_edge_position  # noqa: E402
from face_geometry import compute_face_axes  # noqa: E402

_AXIS_VECTORS = {
    'x': App.Vector(1, 0, 0),
    'y': App.Vector(0, 1, 0),
    'z': App.Vector(0, 0, 1),
}


def _outward_normal(face):
    uv = face.ParameterRange
    return face.normalAt((uv[0] + uv[1]) / 2, (uv[2] + uv[3]) / 2)


def _face_u_axis(face):
    """(origin, u_vec, u_length) for face, via face_geometry.compute_face_axes."""
    outer_wire = face.OuterWire
    bbox = outer_wire.BoundBox
    origin = App.Vector(bbox.XMin, bbox.YMin, bbox.ZMin)

    pts = [v.Point for v in outer_wire.Vertexes]
    x_range = max(p.x for p in pts) - min(p.x for p in pts)
    y_range = max(p.y for p in pts) - min(p.y for p in pts)
    z_range = max(p.z for p in pts) - min(p.z for p in pts)

    normal = _outward_normal(face)
    axes = compute_face_axes(x_range, y_range, z_range,
                              (normal.x, normal.y, normal.z))
    return origin, _AXIS_VECTORS[axes['u_axis']], axes['u_length']


def find_corners(shape, face_indices: List[int],
                  angle_tol: float = 0.05,
                  edge_tol: float = 0.01,
                  edge_search_tol: float = 0.1) -> Dict:
    """
    Discover real 90-degree building corners among the given candidate
    faces of `shape`, and classify which edge (Left/Right) of each face
    the corner falls on.

    Args:
        shape: a Part.Shape (e.g. doc.getObject("Cut001").Shape) whose
            .Faces the indices in face_indices refer to.
        face_indices: 0-based indices into shape.Faces to consider as
            candidate wall faces. Only pairs within this set are checked
            (O(n^2) in len(face_indices), which is always small for a
            building's exterior walls).
        angle_tol: passed to corner_geometry.classify_dihedral.
        edge_tol: passed to corner_geometry.classify_edge_position -- an
            absolute distance, not a fraction of wall length; pick a value
            appropriate to the model's scale (e.g. a fraction of the
            mortar joint thickness).
        edge_search_tol: passed to freecad_utils.find_shared_edge for
            detecting whether two faces share an edge at all.

    Returns:
        {'corners': [...], 'ambiguous': [...]}

        Each entry in 'corners':
            {'face_a': int, 'face_b': int, 'edge': Part.Edge,
             'face_a_edge': 'left'|'right', 'face_b_edge': 'left'|'right'}
        face_a_edge/face_b_edge are determined independently per face --
        see this module's docstring for why they are NOT assumed symmetric.
        No 'primary' field: see assign_primary().

        Each entry in 'ambiguous':
            {'face_a': int, 'face_b': int, 'reason': str}
        Pairs that share an edge but couldn't be confidently classified
        (angle or edge-position ambiguity, or a convexity-check
        disagreement -- see below). Never silently dropped or guessed.

    A pair with no shared edge at all is simply not adjacent -- it is
    omitted from both lists, not reported as ambiguous.
    """
    faces = {i: shape.Faces[i] for i in face_indices}
    corners: List[Dict] = []
    ambiguous: List[Dict] = []

    # Dedupe: a duplicate index would otherwise compare a face to itself,
    # trivially "sharing" every edge with itself and classifying as
    # coplanar -- silently dropped rather than surfaced as the caller
    # error it actually is. Deduplicating is a safe normalization (not a
    # guess): two positions naming the same face carry no extra
    # information to guess between.
    indices = sorted(set(face_indices))
    for pos_a in range(len(indices)):
        for pos_b in range(pos_a + 1, len(indices)):
            i, j = indices[pos_a], indices[pos_b]
            face_i, face_j = faces[i], faces[j]

            edge = find_shared_edge(face_i, face_j, tol=edge_search_tol)
            if edge is None:
                continue

            n_i = _outward_normal(face_i)
            n_j = _outward_normal(face_j)
            cos_dihed = n_i.dot(n_j)

            # Convexity: is the OTHER face's centroid on the outward
            # (convex) or inward (concave) side of THIS face's plane?
            # Computed independently from each face's own normal; a real,
            # well-formed 90-degree corner between two planar faces must
            # agree both ways -- disagreement means degenerate/non-planar
            # geometry, reported as ambiguous rather than picking one
            # arbitrarily.
            c_i, c_j = face_i.CenterOfMass, face_j.CenterOfMass
            convex_via_i = (c_j - c_i).dot(n_i) < 0
            convex_via_j = (c_i - c_j).dot(n_j) < 0
            if convex_via_i != convex_via_j:
                ambiguous.append({
                    'face_a': i, 'face_b': j,
                    'reason': ('convexity check disagreed between the two '
                               'faces (non-planar or degenerate geometry?)'),
                })
                continue

            classification = classify_dihedral(cos_dihed, convex_via_i, tol=angle_tol)
            if classification == 'ambiguous':
                ambiguous.append({
                    'face_a': i, 'face_b': j,
                    'reason': f'dihedral angle ambiguous (cos_dihed={cos_dihed:.4f})',
                })
                continue
            if classification != 'convex_90':
                # 'concave_90' (interior reveal) or 'coplanar' -- adjacent,
                # but not a quoin corner.
                continue

            mid = (edge.Vertexes[0].Point + edge.Vertexes[-1].Point) * 0.5

            def edge_position(face):
                origin, u_vec, u_length = _face_u_axis(face)
                coord = (mid - origin).dot(u_vec)
                return classify_edge_position(coord, u_length, tol=edge_tol)

            pos_i, pos_j = edge_position(face_i), edge_position(face_j)
            if pos_i == 'ambiguous' or pos_j == 'ambiguous':
                ambiguous.append({
                    'face_a': i, 'face_b': j,
                    'reason': (f'edge-position ambiguous for at least one '
                               f'face (face_a={pos_i}, face_b={pos_j})'),
                })
                continue

            corners.append({
                'face_a': i, 'face_b': j, 'edge': edge,
                'face_a_edge': pos_i, 'face_b_edge': pos_j,
            })

    return {'corners': corners, 'ambiguous': ambiguous}


def assign_primary(corners: List[Dict]) -> List[Dict]:
    """
    Assign a Primary/Secondary role to each corner's two faces.

    Primary/Secondary is not a derivable geometric fact (see this module's
    and quoin_geometry.py's docstrings) -- it's a mutual-exclusivity
    constraint the underlying QuoinGeometry needs satisfied, arbitrarily.
    This applies one simple, documented convention (the lower face index
    is Primary) so callers get a usable default; override per-corner if a
    different choice is wanted.

    Returns a new list of dicts, each input corner dict plus
    'face_a_primary': bool (True iff face_a is the lower index, hence
    Primary; face_b_primary is always the opposite).
    """
    result = []
    for c in corners:
        c = dict(c)
        c['face_a_primary'] = c['face_a'] < c['face_b']
        result.append(c)
    return result
