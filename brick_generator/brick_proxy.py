"""
BrickProxy — FeaturePython proxy for parametric brick engraving.

Change any property in the panel and the brickwork regenerates.
Face references stored as PropertyLinkSubList so they survive save/reload.

ARCHITECTURAL CHANGE in v7.0.0 (breaking):
  Through v6.x, this proxy copied the ENTIRE source shape, cut a recess
  INTO it, and engraved mortar into that recess -- obj.Shape was a modified
  copy of the whole wall (or whole building, if Sources pointed at a solid
  with real volume), meant to replace the source (hide the source, show
  BrickedWall instead). This broke composability: two independent
  BrickedWall objects sourcing different faces of the same solid each
  produced a FULL duplicate copy of that solid's entire volume, since
  "copy the input shape" copies the whole thing regardless of how many
  faces are actually being bricked -- showing several such objects at once
  produced overlapping duplicate buildings, not one coherent building with
  several different brick treatments (found 2026-09-13 trying to give
  different walls different bond patterns).

  v7.0.0 instead builds a thin brick SKIN per Sources face, proud of (in
  front of) the original surface by SkinDepth, with mortar carved
  MortarDepth back into that skin's own thickness -- the same "applied
  siding on a visible wall" model clapboard_proxy.py/bead_board_proxy.py
  already use. obj.Shape is now just the skin (or a Part.Compound of one
  skin per Sources face), never a copy of the wall/building it sits on.

  User-facing consequence: **keep the source wall VISIBLE**, not hidden --
  the skin sits on top of it, it doesn't replace it. This inverts the
  pre-7.0.0 workflow.

  Independent BrickedWall objects (one per wall, each its own bond
  pattern) now compose correctly via simple side-by-side display, exactly
  like independent ClapboardWall/BeadBoard objects already do -- no
  chaining one BrickedWall's Sources onto another's output needed.

QUOIN CORNERS (LeftQuoin / RightQuoin):
  Set LeftQuoin=True (and RightQuoin=True for a wall spanning two corners)
  on a face BEFORE generating it — the real interlocking corner column is
  computed via quoin_geometry.QuoinGeometry and merged directly into that
  face's own mortar cut, in the same pass as the field fill. There is no
  separate quoin-engraving step or object to run afterward.

  Two ways to assign LeftQuoin/RightQuoin, matching two different modeling
  habits:

  1. One BrickedWall per face (LeftQuoin/LeftQuoinPrimary as plain object
     properties). Each face at a corner is generated independently — you do
     not need both faces selected together, and they can be generated in
     either order or in separate sessions. The two sides interlock
     correctly as long as BrickWidth/Height/Depth/Mortar/BondPattern match
     on both faces (set by hand; there is no live link between the two
     BrickedWall objects) and exactly one has LeftQuoinPrimary=True.

  2. One BrickedWall covering multiple faces at once (e.g. all four walls
     of a building selected into a single Sources list, as this project's
     models typically do). A single LeftQuoin/LeftQuoinPrimary pair can't
     express "this face is primary at its left corner but secondary at its
     right corner" for more than one face — so use the four per-face
     override properties instead: LeftQuoinPrimaryFaces,
     LeftQuoinSecondaryFaces, RightQuoinPrimaryFaces,
     RightQuoinSecondaryFaces. Put a Sources face into whichever override
     list matches its role at that corner; a face absent from all four
     falls back to the plain LeftQuoin/RightQuoin/*Primary booleans
     unchanged (so existing documents with empty override lists are
     unaffected).

  Either way, QuoinGeometry needs no reference to the sibling face's actual
  geometry — only wall height, brick dimensions, and which side is primary,
  all known before the sibling face is generated.

  (v6.0/v6.1 predecessor: LeftQuoin used to leave a blank flush-recessed
  "reservation" column for a separate QuoinProxy pass to engrave later —
  see quoin_generator/. That two-pass design is superseded: it required a
  second full-shape OCCT boolean cut against the whole (by-then heavily
  fragmented) BrickedWall even in the correctly-planned case. quoin_proxy.py
  and quoin_generator.FCMacro have since been deleted entirely — a scan of
  every .FCStd document found zero real use of the two-pass touch-up path
  they provided, and this single-pass design is now the only quoin
  mechanism. quoin_generator/quoin_geometry.py remains: this module still
  imports QuoinGeometry/mirror_to_right_edge from it directly.)

REVERSE QUOIN SIDES (v7.4.0):
  LeftQuoin/RightQuoin are defined by compute_face_axes' u-axis (u=0 is
  whichever end has the lower coordinate along the face's dominant
  bounding-box axis) -- deliberately independent of which way the face's
  normal points, since shared/corner_detection.py's automatic
  corner-pairing logic is WRITTEN to require that independence (note:
  corner_detection.py itself has no callers anywhere in this repo as of
  the 2026-09-15 full review -- this convention is a forward-looking
  design constraint for that not-yet-wired-in consolidation, not a live
  dependency today; brick_proxy.py's own corner handling currently goes
  through the manual LeftQuoin/RightQuoin override properties below
  instead). The practical consequence, confirmed live on a real building:
  "left"/"right" do NOT consistently match your own left/right hand when
  standing outside facing a given wall -- it flips per-face depending on
  that wall's own facing direction (one wall of a corner matched, the
  adjacent wall at 90 degrees was exactly backwards).

  ReverseQuoinSides (default False) swaps LeftQuoin<->RightQuoin and
  LeftQuoinPrimary<->RightQuoinPrimary for one face, applied in execute()
  right after resolve_quoin() -- after every other property (including the
  per-face *QuoinFaces overrides) is already resolved, so every downstream
  consumer (widen, mortar grid, corner-return joints) sees an
  already-consistent pair and needed no changes. Matches the same pattern
  as Part::Extrusion's own Reversed checkbox: flip a boolean rather than
  reworking the underlying axis convention.

CORNER RETURN-FACE JOINTS (v7.3.0):
  v7.1.0's corner-widen fix closed the 3D gap between two walls' skins by
  extending the Primary wall's own front (u/v) face outward -- but the
  widened extension's own PERPENDICULAR side (the endcap of the extruded
  skin) was never touched by anything: _create_mortar_grid only engraves
  the front face. Confirmed live via screenshot: this endcap reads as a
  single flat, unmortared strip -- a smooth "raised corner" -- even though
  the extension's own front face already shows correct quoin coursing.

  Fix: _cut_corner_return_joints() cuts a thin mortar-width notch into the
  return face at every course boundary (same course positions the front
  face uses, via the identical _get_face_coordinate_system/
  _snap_origin_to_grid calls), so the return reads as coursed instead of
  solid -- matching how a real quoin's return face shows joints wrapping
  around the corner. Only runs when this face was actually widened; a
  no-op for every plain (non-corner) face.

MORTAR-GRID PERFORMANCE FIX (v7.2.0):
  `_create_mortar_grid` used to clip every brick to face_slab via a boolean
  intersection (Part.Shape.common()) before the final cut. Measured: 801.6
  seconds for one 756-brick wall's mortar cut alone -- boolean intersection
  is by far OCCT's most expensive operation at this shape count, confirmed
  both by direct measurement and independently by domain experience. Since
  every brick's position is exact, known arithmetic, the same "clip to the
  boundary" question has a pure-Python answer: brick_geometry.py's new
  clamp_brick_to_segment() shrinks each overflowing brick's numbers to its
  own segment's real bounds (nudged slightly inward, never exactly onto
  the boundary, for the same coincident-face-avoidance reason TOPO_EPS
  exists) before any OCCT solid is built. The final mortar cut is now a
  plain face_slab.cut(brick_compound) with no .common() call at any brick
  count -- measured at 2.9 seconds for the same 756-brick wall. No change
  to brick_geometry.py's course-generation output; only how the resulting
  overflow gets clipped downstream.

CORNER SEAM GAP FIX (v7.1.0):
  v7.0.0's independent per-face skins each offset outward along their OWN
  face normal. At a real 90-degree corner, two adjacent walls' normals are
  perpendicular, so their independently-offset skins move apart in
  different 3D directions instead of toward each other, leaving a visible
  gap/step between them (confirmed live via render).

  Fix: at a quoin edge where THIS face is the Primary side (LeftQuoin +
  LeftQuoinPrimary, or RightQuoin + RightQuoinPrimary), this face's own
  boundary is widened outward by SkinDepth before the skin is built (see
  _widen_face_boundary()) -- enough to reach the neighboring wall's own
  proud skin at an axis-aligned 90-degree corner. The Secondary side is
  left untouched, so there's no double-coverage between the two walls'
  volumes. Everything downstream (_offset_face, _create_mortar_grid,
  BrickGeometry) needs no changes: it just sees a wider face and lays
  bricks out from the new, extended edge.

This module must be importable by FreeCAD (installed alongside the macro).
"""

import FreeCAD as App
import Part
import math
import sys
from pathlib import Path

VERSION = "7.4.0"
GENERATOR_NAME = "brick_generator"

_here = Path(__file__).parent
for p in (str(_here), str(_here / '_lib'), str(_here.parent / 'quoin_generator')):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import brick_geometry as _bg
    from brick_geometry import (
        BrickGeometry, BrickDef,
        face_index_set, find_dual_listed_faces, resolve_quoin_flags_for_face,
        topo_eps, clamp_brick_to_segment,
    )
except ImportError:
    _bg = None
    BrickGeometry = None
    BrickDef = None

try:
    from quoin_geometry import QuoinGeometry, mirror_to_right_edge
except ImportError:
    QuoinGeometry = None
    mirror_to_right_edge = None

try:
    import face_geometry
except ImportError:
    face_geometry = None

from freecad_utils import (
    resolve_sources_faces, get_face_coordinate_system, GenericViewProxy,
    add_property,
)


# =============================================================================
# Geometry helpers (trimmed from brick_generator_macro.FCMacro)
# =============================================================================

def _scale(vec, s):
    return App.Vector(vec.x * s, vec.y * s, vec.z * s)


def _offset_face(face, normal, offset):
    """
    Translate a planar face's outer wire by `offset` along `normal` and
    rebuild a Face from it -- a plain translation, not a boolean cut.

    Replaces the old (pre-7.0.0) _recess_shape()'s "cut a recess volume out
    of the whole shape, then re-identify the recessed face by centroid/
    normal/area matching" -- unnecessary for a planar face, whose translated
    position is trivially computable, and cheaper/more robust than an OCCT
    cut + heuristic re-identification.
    """
    wire = face.OuterWire.copy()
    wire.translate(_scale(normal, offset))
    return Part.Face(wire)


def _widen_face_boundary(face, u_vec, v_vec, side, delta, angle_tol=5.0, edge_tol=0.01):
    """
    Return a Face whose OuterWire matches `face`'s, except the specific
    wire edge running parallel to v_vec at the U extreme named by `side`
    ('left' = minimum U, 'right' = maximum U) has its two endpoints
    translated outward along u_vec by `delta`.

    Used at a real building corner (LeftQuoin/RightQuoin set together with
    the matching *Primary flag -- see execute()) so the proud skin built
    from the returned face (via _offset_face) reaches the neighboring
    wall's own skin instead of stopping short at the real edge and leaving
    a visible gap. See this module's ARCHITECTURAL CHANGE docstring note
    above and the project's corner-fix design ("Part 8") for the full
    root-cause explanation: each wall's skin is offset along its OWN face
    normal, so at a 90-degree corner the two proud skins move apart in
    different 3D directions and never actually meet.

    Only the identified edge's two vertices move; every other vertex is
    left untouched. The wire is rebuilt from scratch via Part.makePolygon
    from the full ordered vertex list (via OuterWire.OrderedVertexes,
    confirmed empirically -- not assumed -- to give true wire-traversal
    order regardless of any individual edge's own Orientation flag, unlike
    edge.Vertexes[0]/[-1] which does NOT respect wire-traversal direction
    for a 'Reversed' edge, as boolean-cut-derived faces commonly have)
    rather than edited in place, so there's no dangling-vertex mismatch
    between the moved edge and its unmoved neighbors.

    Raises:
        ValueError: the wire isn't closed or well-formed; no V-parallel
        edge exists to widen; the widen target is ambiguous (see
        face_geometry.select_widen_edge); or the widened result is an
        invalid (e.g. self-intersecting) face -- checked via Face.isValid()
        on the REBUILT FACE, not the wire (confirmed empirically: a
        self-intersecting wire's own .isValid() still returns True; only
        the resulting Face catches it).
    """
    if face_geometry is None:
        raise ValueError("face_geometry module not found -- cannot widen face boundary")

    outer_wire = face.OuterWire
    if not outer_wire.isClosed():
        raise ValueError("Face outer wire is not closed -- cannot widen it")

    ordered_edges = outer_wire.OrderedEdges
    ordered_points = [v.Point for v in outer_wire.OrderedVertexes]
    n = len(ordered_points)
    if n < 3 or len(ordered_edges) != n:
        raise ValueError(
            f"Outer wire has {len(ordered_edges)} edges and {n} ordered "
            f"vertices -- not a simple closed polygon, refusing to widen it")

    candidates = []
    for i, edge in enumerate(ordered_edges):
        if edge.Length < 0.01:
            continue
        try:
            d = edge.tangentAt(edge.FirstParameter)
            d.normalize()
        except Exception:
            continue
        angle = math.degrees(math.acos(min(1.0, abs(d.dot(v_vec)))))
        if angle < angle_tol:
            candidates.append((i, ordered_points[i].dot(u_vec)))

    edge_idx = face_geometry.select_widen_edge(candidates, side, tol=edge_tol)

    offset_vec = _scale(u_vec, face_geometry.widen_offset_sign(side) * delta)
    j = (edge_idx + 1) % n
    new_points = list(ordered_points)
    new_points[edge_idx] = new_points[edge_idx] + offset_vec
    new_points[j] = new_points[j] + offset_vec

    new_wire = Part.makePolygon(new_points + [new_points[0]])
    new_face = Part.Face(new_wire)
    if not new_face.isValid():
        raise ValueError(
            f"Widening the {side} boundary by {delta} produced an invalid "
            f"(likely self-intersecting) face -- check SkinDepth against "
            f"this face's own U extent")
    return new_face


def _get_face_coordinate_system(face):
    """
    Establish U/V/normal coordinate system for a face.
    Returns (origin, u_vec, v_vec, normal, u_length, v_length, is_horizontal).

    Thin local alias for freecad_utils.get_face_coordinate_system(), kept
    so this module's existing call sites don't need to change. That shared
    function is the single source of truth for this extraction --
    previously duplicated independently here and in corner_detection.py's
    _outward_normal()/_face_u_axis() (2026-09-14 consolidation).
    """
    return get_face_coordinate_system(face)


def _snap_origin_to_grid(origin, u_vec, v_vec, brick_width, brick_height, mortar):
    """Snap V (course height) to global grid for course alignment across faces."""
    vert_grid = brick_height + mortar
    normal = u_vec.cross(v_vec)
    normal.normalize()
    origin_u = origin.dot(u_vec)
    origin_v = origin.dot(v_vec)
    origin_n = origin.dot(normal)
    snapped_v = round(origin_v / vert_grid) * vert_grid
    return _scale(u_vec, origin_u) + _scale(v_vec, snapped_v) + _scale(normal, origin_n)


def _find_bay_boundaries(outer_wire, u_vec, v_vec, gap_threshold=0.0005, max_gap=0.02):
    """Find vertical gaps (bay boundaries) in outer wire."""
    tol = 5.0
    vert_edges = []
    for edge in outer_wire.Edges:
        if edge.Length < 0.01:
            continue
        try:
            d = edge.tangentAt(edge.FirstParameter)
            d.normalize()
            angle = math.degrees(math.acos(min(1.0, abs(d.dot(v_vec)))))
            if angle < tol:
                start = edge.valueAt(edge.FirstParameter)
                vert_edges.append(start.dot(u_vec))
        except Exception:
            continue
    vert_edges.sort()
    return [
        (vert_edges[i] + vert_edges[i+1]) / 2
        for i in range(len(vert_edges) - 1)
        if gap_threshold < (vert_edges[i+1] - vert_edges[i]) < max_gap
    ]


def _make_oriented_box(origin, u_vec, v_vec, normal, u0, u1, v0, v1, n0, n1):
    """
    Build a box in an arbitrary u/v/normal coordinate system: spans
    [u0, u1] x [v0, v1] x [n0, n1] (the last measured along `normal`).

    Shared by _create_brick_from_def (n0=0, n1=-brick_def.depth -- a brick
    is one-sided, recessed into the material) and
    _corner_return_joint_boxes (n spans the skin's full front-to-back
    thickness, since a return-face joint needs to be visible from the
    front proud surface all the way back to the embed depth).
    """
    def pt(u, v, n):
        return origin + _scale(u_vec, u) + _scale(v_vec, v) + _scale(normal, n)

    p0, p1, p2, p3 = pt(u0, v0, n0), pt(u1, v0, n0), pt(u1, v1, n0), pt(u0, v1, n0)
    p4, p5, p6, p7 = pt(u0, v0, n1), pt(u1, v0, n1), pt(u1, v1, n1), pt(u0, v1, n1)

    edges = [
        Part.Edge(Part.LineSegment(p0, p1).toShape()),
        Part.Edge(Part.LineSegment(p1, p2).toShape()),
        Part.Edge(Part.LineSegment(p2, p3).toShape()),
        Part.Edge(Part.LineSegment(p3, p0).toShape()),
        Part.Edge(Part.LineSegment(p4, p5).toShape()),
        Part.Edge(Part.LineSegment(p5, p6).toShape()),
        Part.Edge(Part.LineSegment(p6, p7).toShape()),
        Part.Edge(Part.LineSegment(p7, p4).toShape()),
        Part.Edge(Part.LineSegment(p0, p4).toShape()),
        Part.Edge(Part.LineSegment(p1, p5).toShape()),
        Part.Edge(Part.LineSegment(p2, p6).toShape()),
        Part.Edge(Part.LineSegment(p3, p7).toShape()),
    ]
    e0,e1,e2,e3,e4,e5,e6,e7,e8,e9,e10,e11 = edges
    faces = [
        Part.Face(Part.Wire([e0, e1, e2, e3])),
        Part.Face(Part.Wire([e4, e5, e6, e7])),
        Part.Face(Part.Wire([e0, e9, e4, e8])),
        Part.Face(Part.Wire([e2, e10, e6, e11])),
        Part.Face(Part.Wire([e3, e8, e7, e11])),
        Part.Face(Part.Wire([e1, e9, e5, e10])),
    ]
    return Part.Solid(Part.Shell(faces))


def _create_brick_from_def(brick_def, origin, u_vec, v_vec, normal):
    """Build one brick solid from a BrickDef."""
    bd = brick_def
    return _make_oriented_box(
        origin, u_vec, v_vec, normal,
        bd.u, bd.u + bd.width, bd.v, bd.v + bd.height, 0.0, -bd.depth)


def _resolve_quoin_flags(obj, link_obj):
    """
    Build a face_idx -> (left_quoin, left_quoin_primary, right_quoin,
    right_quoin_primary) resolver, honoring the four per-face override
    properties ahead of the plain object-level LeftQuoin/RightQuoin/*Primary
    booleans. A face not present in any override list falls back to the
    plain booleans unchanged — this keeps every pre-existing document
    (which has empty override lists) behaving exactly as before.

    The actual index/flag resolution logic lives in brick_geometry.py
    (face_index_set/find_dual_listed_faces/resolve_quoin_flags_for_face) --
    pure Python, pytest-testable without FreeCAD (full-review finding
    freecad-mr-generators-20260808-a0b9#09). This function is the thin
    FreeCAD-facing wrapper: reading the object's properties and printing
    the dual-listed-face warning.
    """
    left_primary    = face_index_set(getattr(obj, 'LeftQuoinPrimaryFaces', []), link_obj)
    left_secondary  = face_index_set(getattr(obj, 'LeftQuoinSecondaryFaces', []), link_obj)
    right_primary   = face_index_set(getattr(obj, 'RightQuoinPrimaryFaces', []), link_obj)
    right_secondary = face_index_set(getattr(obj, 'RightQuoinSecondaryFaces', []), link_obj)

    for side, primary_set, secondary_set in (
        ('Left', left_primary, left_secondary),
        ('Right', right_primary, right_secondary),
    ):
        both = find_dual_listed_faces(primary_set, secondary_set)
        if both:
            App.Console.PrintWarning(
                f"BrickProxy: Face(s) {sorted(i + 1 for i in both)} listed in "
                f"both {side}QuoinPrimaryFaces and {side}QuoinSecondaryFaces; "
                f"treating as Primary.\n")

    default_left_quoin     = bool(getattr(obj, 'LeftQuoin', False))
    default_left_primary   = bool(getattr(obj, 'LeftQuoinPrimary', True))
    default_right_quoin    = bool(getattr(obj, 'RightQuoin', False))
    default_right_primary  = bool(getattr(obj, 'RightQuoinPrimary', True))

    def resolve(face_idx):
        return resolve_quoin_flags_for_face(
            face_idx, left_primary, left_secondary, right_primary, right_secondary,
            default_left_quoin, default_left_primary,
            default_right_quoin, default_right_primary)

    return resolve


def _create_mortar_grid(face, params):
    """
    Create the mortar grid for one face: face_slab minus brick shapes.
    This is what gets cut from the wall to leave engraved mortar lines.
    """
    if BrickGeometry is None:
        raise ImportError("brick_geometry module not available")

    origin, u_vec, v_vec, normal, u_length, v_length, is_horizontal = \
        _get_face_coordinate_system(face)

    brick_width  = params['brick_width']
    brick_height = params['brick_height']
    brick_depth  = params['brick_depth']
    mortar       = params['mortar']
    bond_type    = params['bond_type']
    cbc          = int(params['common_bond_count'])
    mortar_depth = params['mortar_depth']

    # Horizontal face: swap height/depth
    gen_bh = brick_depth  if is_horizontal else brick_height
    gen_bd = brick_height if is_horizontal else brick_depth

    origin = _snap_origin_to_grid(origin, u_vec, v_vec, brick_width, gen_bh, mortar)

    outer_wire = face.OuterWire
    bay_bounds = _find_bay_boundaries(outer_wire, u_vec, v_vec)

    # Generate brick defs (possibly segmented at bay boundaries)
    segs = []
    prev = 0.0
    for b in sorted(bay_bounds):
        if b > prev + 0.001:
            segs.append((prev, b))
        prev = b
    if prev < u_length - 0.001:
        segs.append((prev, u_length))
    if not segs:
        segs = [(0.0, u_length)]

    # Quoin treatment applies to the true left/right edges of the whole face
    # (u=0 / u=u_length), not to every bay-boundary segment — only the first
    # segment can have a left quoin, only the last can have a right quoin.
    left_quoin  = bool(params.get('left_quoin', False))
    right_quoin = bool(params.get('right_quoin', False))
    left_quoin_primary  = bool(params.get('left_quoin_primary', True))
    right_quoin_primary = bool(params.get('right_quoin_primary', True))

    all_bricks = []
    # Real quoin-column bricks, computed by QuoinGeometry and merged directly
    # into the field-brick list before the single cut below — the corner
    # column is carved in the same pass as the field fill, not reserved now
    # and engraved later by a second QuoinProxy boolean against the whole
    # (by-then heavily-fragmented) wall shape. QuoinGeometry is a pure
    # function of wall height / brick dims / which side is primary, so this
    # face's half of the corner needs no reference to the adjacent face —
    # the two interlock as long as brick params match and exactly one side
    # is primary.
    quoin_defs = []
    for seg_start, seg_end in segs:
        seg_w = seg_end - seg_start
        seg_left_quoin  = left_quoin and (seg_start == segs[0][0])
        seg_right_quoin = right_quoin and (seg_end == segs[-1][1])
        bg = BrickGeometry(
            u_length=seg_w, v_length=v_length,
            brick_width=brick_width, brick_height=gen_bh, brick_depth=gen_bd,
            mortar=mortar, bond_type=bond_type, common_bond_count=cbc,
            skin_depth=mortar_depth,
            left_quoin=seg_left_quoin, left_quoin_primary=left_quoin_primary,
            right_quoin=seg_right_quoin, right_quoin_primary=right_quoin_primary,
        )
        result = bg.generate()
        # Clamp each brick to this segment's own [0, seg_w] x [0, v_length]
        # in LOCAL coordinates, before the += seg_start offset below --
        # BrickGeometry deliberately lets bricks overflow a real edge
        # (TOPO_EPS, the +2-course V overflow, stretcher's plain-path
        # overflow) on the assumption something will clip them back before
        # the final OCCT cut; clamp_brick_to_segment does that clip
        # analytically (no OCCT boolean intersection needed -- see its
        # docstring and brick_geometry.py's 6.1.0 changelog for why this
        # replaced a previous Part.Shape.common()-based clip that measured
        # 801s for one 756-brick wall). Segment-local bounds specifically
        # (not the whole face's global u_length) so a bay-adjacent
        # segment's own overflow clips to ITS OWN boundary, not the far
        # edge of the whole face.
        eps = topo_eps(mortar)
        for bd in result['bricks']:
            bd = clamp_brick_to_segment(bd, seg_w, v_length, eps)
            if bd is None:
                # Zero overlap with this segment -- one of BrickGeometry's
                # own deliberate over-generation buffers (the +2-course V
                # overflow, stretcher bond's plain-tiling loop tail), not
                # a real brick. Nothing to clip; drop it.
                continue
            all_bricks.append(BrickDef(
                index=len(all_bricks),
                u=bd.u + seg_start, v=bd.v,
                course=bd.course, brick_type=bd.brick_type,
                width=bd.width, height=bd.height, depth=bd.depth,
            ))
        if seg_left_quoin or seg_right_quoin:
            if QuoinGeometry is None:
                raise ImportError(
                    "quoin_geometry module not found — cannot generate the "
                    "LeftQuoin/RightQuoin corner column.")
            qg = QuoinGeometry(
                wall_height=v_length, brick_width=brick_width,
                brick_height=gen_bh, brick_depth=gen_bd, mortar=mortar,
                bond_type=bond_type, skin_depth=mortar_depth,
            )
            qresult = qg.generate()
            if seg_left_quoin:
                side = qresult['face_a_bricks'] if left_quoin_primary else qresult['face_b_bricks']
                for bd in side:
                    bd = clamp_brick_to_segment(bd, seg_w, v_length, eps)
                    if bd is None:
                        continue
                    quoin_defs.append(BrickDef(
                        index=len(quoin_defs),
                        u=bd.u + seg_start, v=bd.v,
                        course=bd.course, brick_type=bd.brick_type,
                        width=bd.width, height=bd.height, depth=bd.depth,
                    ))
            if seg_right_quoin:
                side = qresult['face_a_bricks'] if right_quoin_primary else qresult['face_b_bricks']
                for bd in mirror_to_right_edge(side, span=seg_w):
                    bd = clamp_brick_to_segment(bd, seg_w, v_length, eps)
                    if bd is None:
                        continue
                    quoin_defs.append(BrickDef(
                        index=len(quoin_defs),
                        u=bd.u + seg_start, v=bd.v,
                        course=bd.course, brick_type=bd.brick_type,
                        width=bd.width, height=bd.height, depth=bd.depth,
                    ))

    # Face slab (extruded inward by mortar_depth)
    face_slab = face.extrude(_scale(normal, -mortar_depth))

    # Brick shapes — field bricks plus real quoin-column bricks, all
    # excluded from the mortar cut below (see quoin_defs comment above).
    # Every brick is already clamped to its own segment's real bounds
    # above, so no brick can extend past face_slab -- the cut below needs
    # no preceding boolean-intersection clip (Part.Shape.common()) at any
    # brick count. See brick_geometry.py's clamp_brick_to_segment and its
    # 6.1.0 changelog entry for the full rationale/measurement.
    brick_shapes = [_create_brick_from_def(bd, origin, u_vec, v_vec, normal)
                    for bd in all_bricks + quoin_defs]
    if not brick_shapes:
        return face_slab  # no bricks → full slab (all mortar)

    return face_slab.cut(Part.Compound(brick_shapes))


def _cut_corner_return_joints(shape, outer_face, params, embed_offset,
                               skin_depth, widen_left, widen_right):
    """
    Cut mortar-joint grooves into the RETURN (endcap) face(s) that Part 8's
    corner-widen fix exposes at a real building corner.

    _widen_face_boundary() extends the Primary wall's own boundary outward
    by skin_depth so its proud FRONT face reaches the neighboring wall's
    proud surface, closing the corner gap -- but the widened extension's
    own PERPENDICULAR side (the endcap of the extruded skin, facing the
    same direction as the neighboring wall's front face) is a single flat
    plane with nothing cut into it: _create_mortar_grid only ever engraves
    the front (u/v) face, never a side. Confirmed live via screenshot: this
    reads as a smooth, unmortared "raised corner" block instead of coursing
    wrapping around the corner the way real quoin masonry does — even
    though the extension's own FRONT face already carries correct quoin
    brick/mortar engraving from the ordinary _create_mortar_grid pass.

    Fix: cut a thin (mortar_depth-wide) notch into the return face at every
    course boundary, spanning the skin's full front-to-back thickness, so
    the return reads as coursed instead of solid. Course positions are
    derived via the SAME _get_face_coordinate_system/_snap_origin_to_grid
    calls _create_mortar_grid uses internally (same inputs, same pure
    functions) so the two can never drift apart -- the return face's joints
    always line up with the front face's own course lines.

    No-op (returns `shape` unchanged) when neither side was widened.
    """
    if not (widen_left or widen_right):
        return shape

    origin, u_vec, v_vec, normal, u_length, v_length, is_horizontal = \
        _get_face_coordinate_system(outer_face)
    brick_width  = params['brick_width']
    brick_height = params['brick_height']
    brick_depth  = params['brick_depth']
    mortar       = params['mortar']
    mortar_depth = params['mortar_depth']
    gen_bh = brick_depth if is_horizontal else brick_height
    origin = _snap_origin_to_grid(origin, u_vec, v_vec, brick_width, gen_bh, mortar)

    # Full-review finding freecad-mr-generators-20260915-e612#09: this used
    # to inline `course_spacing_v = gen_bh + mortar; num_courses =
    # ceil(v_length/course_spacing_v)+2` as a second, hand-copied formula
    # -- textually identical to BrickGeometry.__init__'s own
    # self.course_spacing_v/self.num_courses, but with no structural link
    # between them (only coincidentally equivalent because the call sites
    # happened to pass matching arguments). A throwaway BrickGeometry
    # instance (u_length is unused by the v-axis attributes read below)
    # now reads the SAME __init__ code path the front-face mortar grid
    # pass already uses, so a future change to either formula can't
    # silently desync the return-face joint cuts from the front-face
    # coursing -- there is no longer a second formula to drift.
    course_geom = BrickGeometry(
        u_length=1.0, v_length=v_length,
        brick_width=brick_width, brick_height=gen_bh, brick_depth=brick_depth,
        mortar=mortar, bond_type=params['bond_type'],
    )
    course_spacing_v = course_geom.course_spacing_v
    num_courses = course_geom.num_courses

    sides = []
    if widen_left:
        sides.append((0.0, mortar_depth))
    if widen_right:
        sides.append((u_length - mortar_depth, u_length))

    # `origin` (from outer_face, the PROUD offset face) sits at n=0 with
    # skin_solid's material extending in the NEGATIVE normal direction back
    # to the embedded face -- the same front-is-zero, material-is-negative
    # convention _create_brick_from_def uses (n0=0, n1=-depth). A small
    # margin on both ends guarantees the box fully spans skin_solid's own
    # front-to-back thickness rather than merely touching it.
    margin = embed_offset
    n_front = margin
    n_back = -(skin_depth + embed_offset + margin)

    joint_boxes = []
    for u0, u1 in sides:
        for course in range(num_courses):
            joint_v0 = course * course_spacing_v + gen_bh
            if joint_v0 >= v_length:
                break
            joint_v1 = joint_v0 + mortar
            joint_boxes.append(_make_oriented_box(
                origin, u_vec, v_vec, normal,
                u0, u1, joint_v0, joint_v1, n_back, n_front))

    if not joint_boxes:
        return shape
    return shape.cut(Part.Compound(joint_boxes))


# =============================================================================
# FeaturePython proxy
# =============================================================================

class BrickProxy:
    """
    Parametric brick skin.  Change a property → brickwork regenerates.

    Output is a thin brick skin (or one per Sources face, compounded)
    applied proud of the source wall's surface; the source object is not
    modified and should stay VISIBLE underneath (see module docstring's
    v7.0.0 ARCHITECTURAL CHANGE note).
    """

    Type = "BrickedWall"

    BOND_TYPES = ['stretcher', 'english', 'flemish', 'common']

    def __init__(self, obj):
        obj.Proxy = self
        self._setup_properties(obj)

    @staticmethod
    def _setup_properties(obj):
        grp = "Brick"
        add_property(obj, "App::PropertyLinkSubList", 'Sources', grp,
            "Wall faces to engrave brickwork on")
        add_property(obj, "App::PropertyEnumeration", 'BondPattern', grp,
            "Brick bond pattern", default=['stretcher', 'english', 'flemish', 'common'])
        add_property(obj, "App::PropertyLength", 'BrickWidth', grp,
            "Brick width (stretcher face, mm)")
        add_property(obj, "App::PropertyLength", 'BrickHeight', grp, "Brick height (mm)")
        add_property(obj, "App::PropertyLength", 'BrickDepth', grp,
            "Brick depth / header length (mm)")
        add_property(obj, "App::PropertyLength", 'Mortar', grp, "Mortar joint thickness (mm)")
        add_property(
            obj,
            "App::PropertyLength",
            'SkinDepth',
            grp,
            "Brick skin thickness, proud of the source "
                            "face's surface (mm)")
        add_property(obj, "App::PropertyLength", 'MortarDepth', grp,
            "Mortar groove engraving depth (mm)")
        add_property(obj, "App::PropertyInteger", 'CommonBondCount', grp,
            "Stretcher courses between header courses (common bond)")
        add_property(
            obj,
            "App::PropertyBool",
            'LeftQuoin',
            grp,
            "Engrave a real interlocking quoin column at the "
                            "left edge (u=0) in this same pass; field fill "
                            "starts after it. Set independently on each of "
                            "the two faces meeting at the corner (must share "
                            "matching brick params + opposite Primary). "
                            "Supported on all bond types, including header "
                            "courses (english/common bond's header courses "
                            "respect the quoin boundary as of "
                            "brick_geometry.py v6.3.0).",
            default=False)
        add_property(
            obj,
            "App::PropertyBool",
            'LeftQuoinPrimary',
            grp,
            "Left quoin Face A/B designation: True = stretcher "
                            "quoin on even courses, False = header-return. "
                            "Exactly one of the two faces at a corner should "
                            "be True. Ignored when LeftQuoin=False.",
            default=True)
        add_property(
            obj,
            "App::PropertyBool",
            'RightQuoin',
            grp,
            "A real quoin column at the right edge "
                            "(u=u_length). Works standalone (LeftQuoin=False) "
                            "on any bond type. Combined with LeftQuoin=True "
                            "(a wall spanning two quoin corners) is "
                            "flemish-only.",
            default=False)
        add_property(
            obj,
            "App::PropertyBool",
            'RightQuoinPrimary',
            grp,
            "Right quoin Face A/B designation, same convention "
                            "as LeftQuoinPrimary. Ignored when RightQuoin=False.",
            default=True)
        add_property(
            obj,
            "App::PropertyBool",
            'ReverseQuoinSides',
            grp,
            "Swap which physical edge LeftQuoin/RightQuoin refer to on "
                "this face. LeftQuoin/RightQuoin are defined by the face's "
                "own bounding-box axis (u=0 is always whichever end has the "
                "lower coordinate along that axis) -- entirely independent "
                "of which way the face's normal points, so 'left'/'right' "
                "do NOT reliably match your left/right hand when standing "
                "outside the building facing this wall; it flips per-face "
                "depending on which way that wall happens to face "
                "(confirmed 2026-09-14: on a real 2-wall corner, one wall's "
                "Right matched outside-facing-right, the adjacent wall's "
                "Right was outside-facing-LEFT). Toggle this on any face "
                "where the label feels backwards, matching Part::Extrusion's "
                "own Reversed checkbox -- it swaps LeftQuoin<->RightQuoin "
                "and LeftQuoinPrimary<->RightQuoinPrimary for THIS face "
                "only, after every other property is resolved, so it needs "
                "no changes anywhere else (compute_face_axes' U-axis "
                "convention -- the one corner_detection.py's own "
                "auto-corner-pairing logic is written to require staying "
                "normal-independent, though that module has no callers "
                "yet -- is untouched).",
            default=False)
        add_property(
            obj,
            "App::PropertyLinkSubList",
            'LeftQuoinPrimaryFaces',
            grp,
            "Per-face override for a multi-face Sources list: these "
                "faces get a LEFT quoin (u=0) as the PRIMARY side, regardless "
                "of LeftQuoin/LeftQuoinPrimary above. Needed when different "
                "faces in the same BrickedWall meet different corners and "
                "must take opposite roles. A face not listed in any of the "
                "four *QuoinFaces override lists falls back to the plain "
                "LeftQuoin/RightQuoin/*Primary booleans.")
        add_property(
            obj,
            "App::PropertyLinkSubList",
            'LeftQuoinSecondaryFaces',
            grp,
            "Per-face override: these faces get a LEFT quoin (u=0) as "
                "the SECONDARY side. See LeftQuoinPrimaryFaces.")
        add_property(
            obj,
            "App::PropertyLinkSubList",
            'RightQuoinPrimaryFaces',
            grp,
            "Per-face override: these faces get a RIGHT quoin "
                "(u=u_length) as the PRIMARY side. See LeftQuoinPrimaryFaces.")
        add_property(
            obj,
            "App::PropertyLinkSubList",
            'RightQuoinSecondaryFaces',
            grp,
            "Per-face override: these faces get a RIGHT quoin "
                "(u=u_length) as the SECONDARY side. See LeftQuoinPrimaryFaces.")
        add_property(obj, "App::PropertyString", 'GeneratorVersion', grp,
            "Generator version (read-only)", editor_mode=1)

    @staticmethod
    def set_defaults(obj, params=None):
        p = params or {}
        obj.BondPattern      = p.get('bond_type',          'stretcher')
        obj.BrickWidth       = p.get('brick_width',         2.32)
        obj.BrickHeight      = p.get('brick_height',        0.65)
        obj.BrickDepth       = p.get('brick_depth',         1.09)
        obj.Mortar           = p.get('mortar',              0.11)
        obj.SkinDepth        = p.get('material_thickness',  0.3)
        obj.MortarDepth      = p.get('mortar_depth',        0.06)
        obj.CommonBondCount  = int(p.get('common_bond_count', 5))
        obj.LeftQuoin         = bool(p.get('left_quoin',          False))
        obj.LeftQuoinPrimary  = bool(p.get('left_quoin_primary',  True))
        obj.RightQuoin        = bool(p.get('right_quoin',         False))
        obj.RightQuoinPrimary = bool(p.get('right_quoin_primary', True))
        obj.ReverseQuoinSides = bool(p.get('reverse_quoin_sides', False))
        obj.GeneratorVersion = VERSION

    def execute(self, obj):
        if not obj.Sources:
            return

        if BrickGeometry is None:
            App.Console.PrintError(
                "BrickProxy: brick_geometry module not found — "
                "install brick_geometry.py in the _lib directory.\n")
            return

        # Resolve Sources -> Face objects via the same TNP-aware helper
        # (getElement() inside a per-entry try/except) every other proxy in
        # this repo uses -- brick_proxy.py and radial_brick_proxy.py were
        # the only two hand-rolling this (brick via raw int(sub_name[4:])-1
        # string parsing that never called getElement() at all), which is
        # what let a stale Sources entry corrupt into an unresolvable
        # "?FaceN" reference instead of being skipped cleanly (surfaced
        # 2026-09-13 chasing a per-wall bond-pattern bug).
        resolved = resolve_sources_faces(obj.Sources, "BrickProxy")
        if not resolved:
            return

        link_names = {owner.Name for _, owner, _ in resolved}
        if len(link_names) > 1:
            App.Console.PrintError(
                "BrickProxy: all selected faces must be from the same object.\n")
            return

        link_obj = resolved[0][1]

        # _resolve_quoin_flags is keyed by the face's plain integer index
        # into link_obj.Shape.Faces (matching the *QuoinFaces override
        # properties' own index scheme) -- derive it by identity match
        # against the just-resolved Face rather than re-parsing sub_name,
        # so a face resolved via a genuine TNP-tracked extended name still
        # yields the correct current index.
        link_faces = list(link_obj.Shape.Faces)
        orig_face_indices = []
        for face, _owner, sub_name in resolved:
            idx = next((i for i, f in enumerate(link_faces) if f.isSame(face)), None)
            if idx is None:
                App.Console.PrintWarning(
                    f"BrickProxy: resolved face {sub_name!r} on "
                    f"{link_obj.Label} not found in its current Shape -- "
                    f"skipping\n")
                continue
            orig_face_indices.append(idx)

        if not orig_face_indices:
            return

        params = {
            'brick_width':        float(obj.BrickWidth),
            'brick_height':       float(obj.BrickHeight),
            'brick_depth':        float(obj.BrickDepth),
            'mortar':             float(obj.Mortar),
            'bond_type':          str(obj.BondPattern),
            'common_bond_count':  int(obj.CommonBondCount),
            'material_thickness': float(obj.SkinDepth),
            'mortar_depth':       float(obj.MortarDepth),
        }

        try:
            # _resolve_quoin_flags (via face_index_set) can raise ValueError
            # on a malformed "FaceX" name in the *QuoinFaces override
            # properties -- moved inside this try so that's caught by the
            # existing handler below instead of crashing execute()
            # uncaught (full-review finding
            # freecad-mr-generators-20260808-a0b9#23).
            resolve_quoin = _resolve_quoin_flags(obj, link_obj)

            skin_depth = params['material_thickness']
            # v7.0.0: no working-shape copy, no recess-then-cut-the-whole-
            # shape -- each face becomes its own thin skin, proud of the
            # original surface by skin_depth, never a modified copy of
            # link_obj's shape (see module docstring's ARCHITECTURAL
            # CHANGE note for why: copying the whole input shape per
            # BrickedWall object made independent per-wall objects
            # duplicate the entire source volume instead of composing).
            # A small embed offset (matching quoin_geometry's
            # _TOPO_EPS_FACTOR convention of scaling with mortar) lets the
            # skin's back face overlap slightly into the source wall
            # rather than sit exactly coincident with it.
            embed_offset = params['mortar'] * 0.1

            skins = []
            for orig_idx in orig_face_indices:
                if orig_idx >= len(link_faces):
                    continue
                face = link_faces[orig_idx]
                normal = face.normalAt(0, 0)
                left_quoin, left_quoin_primary, right_quoin, right_quoin_primary = \
                    resolve_quoin(orig_idx)
                if bool(getattr(obj, 'ReverseQuoinSides', False)):
                    # See ReverseQuoinSides' own docstring for why this
                    # exists: LeftQuoin/RightQuoin are u-axis labels, not
                    # compass/outside-facing ones, and which one matches
                    # your left/right hand flips per face depending on
                    # which way that face happens to point. Swapping here,
                    # after resolve_quoin() has already applied any
                    # per-face override, means every downstream consumer
                    # (widen, mortar grid, corner-return joints) sees an
                    # already-consistent pair and needs no changes at all.
                    left_quoin, right_quoin = right_quoin, left_quoin
                    left_quoin_primary, right_quoin_primary = \
                        right_quoin_primary, left_quoin_primary
                face_params = dict(params)
                face_params['left_quoin']          = left_quoin
                face_params['left_quoin_primary']  = left_quoin_primary
                face_params['right_quoin']         = right_quoin
                face_params['right_quoin_primary'] = right_quoin_primary
                try:
                    # Part 8 corner-seam-gap fix: at a real corner, widen
                    # THIS face's own boundary outward by skin_depth on
                    # whichever side is both a quoin edge AND this face's
                    # Primary side -- the existing LeftQuoin/RightQuoin +
                    # *Primary properties already encode "real corner
                    # here" + "am I the side that should visually cover
                    # it" (the same Primary/Secondary convention
                    # quoin_geometry.py uses to pick which brick type wins
                    # each course). Only the Primary side widens, so
                    # there's no double-coverage with the untouched
                    # Secondary wall. Everything downstream (_offset_face,
                    # _create_mortar_grid, BrickGeometry) is unchanged --
                    # it just sees a wider face and lays bricks out from
                    # its new, extended edge.
                    widen_left = left_quoin and left_quoin_primary
                    widen_right = right_quoin and right_quoin_primary
                    if widen_left or widen_right:
                        _, u_vec, v_vec, _, _, _, _ = _get_face_coordinate_system(face)
                        if widen_left:
                            face = _widen_face_boundary(face, u_vec, v_vec, 'left', skin_depth)
                        if widen_right:
                            face = _widen_face_boundary(face, u_vec, v_vec, 'right', skin_depth)

                    outer_face = _offset_face(face, normal, skin_depth)
                    mortar_grid = _create_mortar_grid(outer_face, face_params)

                    embedded_face = _offset_face(face, normal, -embed_offset)
                    skin_solid = embedded_face.extrude(
                        _scale(normal, skin_depth + embed_offset))

                    face_result = skin_solid.cut(mortar_grid)
                    # Part 8 follow-up: at a widened corner, also cut
                    # course-boundary mortar joints into the extension's
                    # own return (endcap) face, which _create_mortar_grid
                    # never touches -- see _cut_corner_return_joints'
                    # docstring for the full "raised corner" symptom this
                    # fixes. No-op when neither side was widened.
                    face_result = _cut_corner_return_joints(
                        face_result, outer_face, face_params, embed_offset,
                        skin_depth, widen_left, widen_right)

                    skins.append(face_result)
                except Exception as e:
                    App.Console.PrintError(f"  BrickProxy face {orig_idx}: {e}\n")

            if not skins:
                return

            obj.Shape = skins[0] if len(skins) == 1 else Part.Compound(skins)
            obj.Placement = link_obj.Placement
            App.Console.PrintMessage(
                f"✓ BrickedWall updated ({len(orig_face_indices)} face(s), "
                f"{params['bond_type']} bond)\n")

        except Exception as e:
            App.Console.PrintError(f"BrickProxy execute error: {e}\n")
            import traceback
            traceback.print_exc()

    def dumps(self):
        return {"Type": self.Type}

    def loads(self, state):
        if state:
            self.Type = state.get("Type", "BrickedWall")

    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)


class BrickViewProxy(GenericViewProxy):
    ICON = ":/icons/Part_Box.svg"
