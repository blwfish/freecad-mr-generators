"""
BrickProxy — FeaturePython proxy for parametric brick engraving.

Change any property in the panel and the brickwork regenerates.
Face references stored as PropertyLinkSubList so they survive save/reload.

ARCHITECTURAL CHANGE from v5.x:
  The old macro modified the source wall in-place (destructive).
  This proxy takes a COPY of the source shape, applies recess + engrave to it,
  and sets obj.Shape to the result.  The source object is unchanged.
  Hide the source wall and use the parametric BrickedWall output instead.

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
  is still around only as a touch-up path for pre-existing walls that were
  fully bricked without ever setting LeftQuoin/RightQuoin.)

This module must be importable by FreeCAD (installed alongside the macro).
"""

import FreeCAD as App
import Part
import math
import sys
from pathlib import Path

VERSION = "6.2.0"
GENERATOR_NAME = "brick_generator"

_here = Path(__file__).parent
for p in (str(_here), str(_here / '_lib'), str(_here.parent / 'quoin_generator')):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import brick_geometry as _bg
    from brick_geometry import BrickGeometry, BrickDef
except ImportError:
    _bg = None
    BrickGeometry = None
    BrickDef = None

try:
    from quoin_geometry import QuoinGeometry, mirror_to_right_edge
except ImportError:
    QuoinGeometry = None
    mirror_to_right_edge = None


# =============================================================================
# Geometry helpers (trimmed from brick_generator_macro.FCMacro)
# =============================================================================

def _scale(vec, s):
    return App.Vector(vec.x * s, vec.y * s, vec.z * s)


def _get_face_coordinate_system(face):
    """
    Establish U/V/normal coordinate system for a face.
    Returns (origin, u_vec, v_vec, normal, u_length, v_length, is_horizontal).
    """
    outer_wire = face.OuterWire
    bbox = outer_wire.BoundBox
    origin = App.Vector(bbox.XMin, bbox.YMin, bbox.ZMin)

    pts = [v.Point for v in outer_wire.Vertexes]
    x_range = max(p.x for p in pts) - min(p.x for p in pts)
    y_range = max(p.y for p in pts) - min(p.y for p in pts)
    z_range = max(p.z for p in pts) - min(p.z for p in pts)

    axes = sorted([
        (x_range, 'x', App.Vector(1, 0, 0)),
        (y_range, 'y', App.Vector(0, 1, 0)),
        (z_range, 'z', App.Vector(0, 0, 1)),
    ], reverse=True)

    uv = face.ParameterRange
    normal = face.normalAt((uv[0]+uv[1])/2, (uv[2]+uv[3])/2)

    z_axis  = next((a for a in axes if a[1] == 'z'), None)
    others  = [a for a in axes if a[1] != 'z']

    if z_axis and z_axis[0] > 0.001:
        v_vec    = z_axis[2]
        v_length = z_axis[0]
        best_u, best_len = None, 0
        for rng, _, vec in others:
            if abs(vec.dot(normal)) < 0.5 and rng > best_len:
                best_u, best_len = vec, rng
        if best_u is None:
            best_u, best_len = others[0][2], others[0][0]
        u_vec    = best_u
        u_length = best_len
        is_horizontal = False
    else:
        horiz = [(r, n2, v) for r, n2, v in axes if n2 != 'z']
        horiz.sort(reverse=True)
        if len(horiz) < 2 or horiz[0][0] < 0.001:
            raise ValueError("Face has no meaningful horizontal extent.")
        u_vec    = horiz[0][2]
        u_length = horiz[0][0]
        v_vec    = horiz[1][2]
        v_length = horiz[1][0] if horiz[1][0] > 0.001 else u_length
        is_horizontal = True

    return origin, u_vec, v_vec, normal, u_length, v_length, is_horizontal


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


def _create_brick_from_def(brick_def, origin, u_vec, v_vec, normal):
    """Build one brick solid from a BrickDef."""
    u, v = brick_def.u, brick_def.v
    w, h, d = brick_def.width, brick_def.height, brick_def.depth

    p0 = origin + _scale(u_vec, u)   + _scale(v_vec, v)
    p1 = origin + _scale(u_vec, u+w) + _scale(v_vec, v)
    p2 = origin + _scale(u_vec, u+w) + _scale(v_vec, v+h)
    p3 = origin + _scale(u_vec, u)   + _scale(v_vec, v+h)
    p4 = p0 + _scale(normal, -d)
    p5 = p1 + _scale(normal, -d)
    p6 = p2 + _scale(normal, -d)
    p7 = p3 + _scale(normal, -d)

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


def _face_index_set(link_sub_list, link_obj):
    """Face indices (0-based) referencing link_obj within a PropertyLinkSubList."""
    indices = set()
    for entry_obj, sub_names in link_sub_list:
        if entry_obj is not link_obj:
            continue
        for sub_name in sub_names:
            if sub_name.startswith('Face'):
                indices.add(int(sub_name[4:]) - 1)
    return indices


def _resolve_quoin_flags(obj, link_obj):
    """
    Build a face_idx -> (left_quoin, left_quoin_primary, right_quoin,
    right_quoin_primary) resolver, honoring the four per-face override
    properties ahead of the plain object-level LeftQuoin/RightQuoin/*Primary
    booleans. A face not present in any override list falls back to the
    plain booleans unchanged — this keeps every pre-existing document
    (which has empty override lists) behaving exactly as before.
    """
    left_primary    = _face_index_set(getattr(obj, 'LeftQuoinPrimaryFaces', []), link_obj)
    left_secondary  = _face_index_set(getattr(obj, 'LeftQuoinSecondaryFaces', []), link_obj)
    right_primary   = _face_index_set(getattr(obj, 'RightQuoinPrimaryFaces', []), link_obj)
    right_secondary = _face_index_set(getattr(obj, 'RightQuoinSecondaryFaces', []), link_obj)

    for side, primary_set, secondary_set in (
        ('Left', left_primary, left_secondary),
        ('Right', right_primary, right_secondary),
    ):
        both = primary_set & secondary_set
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
        if face_idx in left_primary or face_idx in left_secondary:
            left_quoin, left_primary_flag = True, (face_idx in left_primary)
        else:
            left_quoin, left_primary_flag = default_left_quoin, default_left_primary
        if face_idx in right_primary or face_idx in right_secondary:
            right_quoin, right_primary_flag = True, (face_idx in right_primary)
        else:
            right_quoin, right_primary_flag = default_right_quoin, default_right_primary
        return left_quoin, left_primary_flag, right_quoin, right_primary_flag

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
        for bd in result['bricks']:
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
                    quoin_defs.append(BrickDef(
                        index=len(quoin_defs),
                        u=bd.u + seg_start, v=bd.v,
                        course=bd.course, brick_type=bd.brick_type,
                        width=bd.width, height=bd.height, depth=bd.depth,
                    ))
            if seg_right_quoin:
                side = qresult['face_a_bricks'] if right_quoin_primary else qresult['face_b_bricks']
                for bd in mirror_to_right_edge(side, span=seg_w):
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
    brick_shapes = [_create_brick_from_def(bd, origin, u_vec, v_vec, normal)
                    for bd in all_bricks + quoin_defs]
    if not brick_shapes:
        return face_slab  # no bricks → full slab (all mortar)

    brick_compound = Part.Compound(brick_shapes)

    # mortar_grid = face_slab - (bricks clipped to face_slab)
    try:
        clipped = brick_compound.common(face_slab)
        return face_slab.cut(clipped)
    except Exception as clip_err:
        App.Console.PrintWarning(f"  Brick clipping failed ({clip_err}), unclipped fallback\n")
        return face_slab.cut(brick_compound)


# =============================================================================
# Shape-based recess (non-destructive, operates on a shape copy)
# =============================================================================

def _recess_shape(shape, face_indices, skin_depth):
    """
    Apply face recess to a shape.
    Returns (modified_shape, new_face_indices).
    Falls back to (original_shape, face_indices) if any step fails.
    """
    if skin_depth <= 0:
        return shape, face_indices

    recess_solids = []
    sigs = []
    for idx in face_indices:
        if idx >= len(shape.Faces):
            continue
        face = shape.Faces[idx]
        normal = face.normalAt(0, 0)
        centroid = face.CenterOfMass
        area = face.Area
        sigs.append((idx, normal, centroid, area))
        outer_wire = face.OuterWire
        solid_face = Part.Face(outer_wire)
        recess_solids.append(solid_face.extrude(_scale(normal, -skin_depth)))

    if not recess_solids:
        return shape, face_indices

    combined = recess_solids[0] if len(recess_solids) == 1 else recess_solids[0].fuse(recess_solids[1:])
    try:
        new_shape = shape.cut(combined)
        if new_shape.isNull():
            return shape, face_indices
    except Exception as e:
        App.Console.PrintWarning(f"  Recess cut failed: {e}\n")
        return shape, face_indices

    # Re-identify recessed faces by expected centroid (shifted inward by skin_depth)
    claimed = set()
    new_face_indices = []
    for orig_idx, orig_normal, orig_centroid, orig_area in sigs:
        expected = orig_centroid + _scale(orig_normal, -skin_depth)
        best_idx, best_score = orig_idx, float('inf')
        for i, f in enumerate(new_shape.Faces):
            if i in claimed:
                continue
            if f.normalAt(0, 0).dot(orig_normal) < 0.99:
                continue
            area_diff = abs(f.Area - orig_area) / max(orig_area, 0.001)
            if area_diff > 0.10:
                continue
            score = expected.distanceToPoint(f.CenterOfMass) + area_diff * 10.0
            if score < best_score:
                best_score = score
                best_idx = i
        claimed.add(best_idx)
        new_face_indices.append(best_idx)

    return new_shape, new_face_indices


# =============================================================================
# FeaturePython proxy
# =============================================================================

class BrickProxy:
    """
    Parametric brick engraving.  Change a property → brickwork updates.

    Output is a copy of the source wall with mortar engraved; the source
    object is not modified.  Hide the source and use BrickedWall instead.
    """

    Type = "BrickedWall"

    BOND_TYPES = ['stretcher', 'english', 'flemish', 'common']

    def __init__(self, obj):
        obj.Proxy = self
        self._setup_properties(obj)

    @staticmethod
    def _setup_properties(obj):
        grp = "Brick"
        if not hasattr(obj, 'Sources'):
            obj.addProperty(
                "App::PropertyLinkSubList", "Sources", grp,
                "Wall faces to engrave brickwork on")
        if not hasattr(obj, 'BondPattern'):
            obj.addProperty(
                "App::PropertyEnumeration", "BondPattern", grp,
                "Brick bond pattern")
            obj.BondPattern = ['stretcher', 'english', 'flemish', 'common']
        if not hasattr(obj, 'BrickWidth'):
            obj.addProperty("App::PropertyLength", "BrickWidth", grp,
                            "Brick width (stretcher face, mm)")
        if not hasattr(obj, 'BrickHeight'):
            obj.addProperty("App::PropertyLength", "BrickHeight", grp,
                            "Brick height (mm)")
        if not hasattr(obj, 'BrickDepth'):
            obj.addProperty("App::PropertyLength", "BrickDepth", grp,
                            "Brick depth / header length (mm)")
        if not hasattr(obj, 'Mortar'):
            obj.addProperty("App::PropertyLength", "Mortar", grp,
                            "Mortar joint thickness (mm)")
        if not hasattr(obj, 'SkinDepth'):
            obj.addProperty("App::PropertyLength", "SkinDepth", grp,
                            "Face recess depth = brick skin thickness (mm)")
        if not hasattr(obj, 'MortarDepth'):
            obj.addProperty("App::PropertyLength", "MortarDepth", grp,
                            "Mortar groove engraving depth (mm)")
        if not hasattr(obj, 'CommonBondCount'):
            obj.addProperty("App::PropertyInteger", "CommonBondCount", grp,
                            "Stretcher courses between header courses (common bond)")
        if not hasattr(obj, 'LeftQuoin'):
            obj.addProperty("App::PropertyBool", "LeftQuoin", grp,
                            "Engrave a real interlocking quoin column at the "
                            "left edge (u=0) in this same pass; field fill "
                            "starts after it. Set independently on each of "
                            "the two faces meeting at the corner (must share "
                            "matching brick params + opposite Primary). "
                            "Supported on all bond types; english/common "
                            "bond header courses do not yet respect the "
                            "reservation (see brick_geometry docstring).")
            obj.LeftQuoin = False
        if not hasattr(obj, 'LeftQuoinPrimary'):
            obj.addProperty("App::PropertyBool", "LeftQuoinPrimary", grp,
                            "Left quoin Face A/B designation: True = stretcher "
                            "quoin on even courses, False = header-return. "
                            "Exactly one of the two faces at a corner should "
                            "be True. Ignored when LeftQuoin=False.")
            obj.LeftQuoinPrimary = True
        if not hasattr(obj, 'RightQuoin'):
            obj.addProperty("App::PropertyBool", "RightQuoin", grp,
                            "A second real quoin column at the right edge "
                            "(u=u_length), for a wall spanning two quoin "
                            "corners. Requires LeftQuoin=True and flemish "
                            "bond.")
            obj.RightQuoin = False
        if not hasattr(obj, 'RightQuoinPrimary'):
            obj.addProperty("App::PropertyBool", "RightQuoinPrimary", grp,
                            "Right quoin Face A/B designation, same convention "
                            "as LeftQuoinPrimary. Ignored when RightQuoin=False.")
            obj.RightQuoinPrimary = True
        if not hasattr(obj, 'LeftQuoinPrimaryFaces'):
            obj.addProperty(
                "App::PropertyLinkSubList", "LeftQuoinPrimaryFaces", grp,
                "Per-face override for a multi-face Sources list: these "
                "faces get a LEFT quoin (u=0) as the PRIMARY side, regardless "
                "of LeftQuoin/LeftQuoinPrimary above. Needed when different "
                "faces in the same BrickedWall meet different corners and "
                "must take opposite roles. A face not listed in any of the "
                "four *QuoinFaces override lists falls back to the plain "
                "LeftQuoin/RightQuoin/*Primary booleans.")
        if not hasattr(obj, 'LeftQuoinSecondaryFaces'):
            obj.addProperty(
                "App::PropertyLinkSubList", "LeftQuoinSecondaryFaces", grp,
                "Per-face override: these faces get a LEFT quoin (u=0) as "
                "the SECONDARY side. See LeftQuoinPrimaryFaces.")
        if not hasattr(obj, 'RightQuoinPrimaryFaces'):
            obj.addProperty(
                "App::PropertyLinkSubList", "RightQuoinPrimaryFaces", grp,
                "Per-face override: these faces get a RIGHT quoin "
                "(u=u_length) as the PRIMARY side. See LeftQuoinPrimaryFaces.")
        if not hasattr(obj, 'RightQuoinSecondaryFaces'):
            obj.addProperty(
                "App::PropertyLinkSubList", "RightQuoinSecondaryFaces", grp,
                "Per-face override: these faces get a RIGHT quoin "
                "(u=u_length) as the SECONDARY side. See LeftQuoinPrimaryFaces.")
        if not hasattr(obj, 'GeneratorVersion'):
            obj.addProperty(
                "App::PropertyString", "GeneratorVersion", grp,
                "Generator version (read-only)")
            obj.setEditorMode("GeneratorVersion", 1)

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
        obj.GeneratorVersion = VERSION

    def execute(self, obj):
        if not obj.Sources:
            return

        if BrickGeometry is None:
            App.Console.PrintError(
                "BrickProxy: brick_geometry module not found — "
                "install brick_geometry.py in the _lib directory.\n")
            return

        # Collect (face_index, link_obj) pairs; all faces must be on same object
        source_map = {}  # obj_name → (link_obj, [face_idx, ...])
        for link_obj, sub_names in obj.Sources:
            if not hasattr(link_obj, 'Shape'):
                continue
            for sub_name in sub_names:
                if not sub_name.startswith('Face'):
                    continue
                face_idx = int(sub_name[4:]) - 1
                key = link_obj.Name
                if key not in source_map:
                    source_map[key] = (link_obj, [])
                source_map[key][1].append(face_idx)

        if not source_map:
            return
        if len(source_map) > 1:
            App.Console.PrintError(
                "BrickProxy: all selected faces must be from the same object.\n")
            return

        link_obj, orig_face_indices = list(source_map.values())[0]
        resolve_quoin = _resolve_quoin_flags(obj, link_obj)

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
            # Work on a copy of the source shape (non-destructive)
            working_shape = link_obj.Shape.copy()

            # Step 1: Recess selected faces. _recess_shape returns new indices
            # in the same order as orig_face_indices, so new_face_indices[i]
            # is where orig_face_indices[i] ended up — quoin overrides are
            # keyed by the ORIGINAL index (as referenced in Sources / the
            # *QuoinFaces properties), so both are needed together below.
            skin_depth = params['material_thickness']
            working_shape, new_face_indices = _recess_shape(
                working_shape, orig_face_indices, skin_depth)

            # Step 2: Build mortar grids for each face, with per-face quoin
            # flags resolved from the *QuoinFaces override properties (falling
            # back to the plain LeftQuoin/RightQuoin/*Primary booleans).
            mortar_grids = []
            for orig_idx, idx in zip(orig_face_indices, new_face_indices):
                if idx >= len(working_shape.Faces):
                    continue
                face = working_shape.Faces[idx]
                left_quoin, left_quoin_primary, right_quoin, right_quoin_primary = \
                    resolve_quoin(orig_idx)
                face_params = dict(params)
                face_params['left_quoin']          = left_quoin
                face_params['left_quoin_primary']  = left_quoin_primary
                face_params['right_quoin']         = right_quoin
                face_params['right_quoin_primary'] = right_quoin_primary
                try:
                    grid = _create_mortar_grid(face, face_params)
                    mortar_grids.append(grid)
                except Exception as e:
                    App.Console.PrintError(f"  BrickProxy face {idx}: {e}\n")

            if not mortar_grids:
                # No grids generated — just output the recessed shape
                obj.Shape = working_shape
                return

            # Step 3: Cut mortar grids from working shape
            if len(mortar_grids) == 1:
                mortar_compound = mortar_grids[0]
            else:
                mortar_compound = Part.Compound(mortar_grids)

            result = working_shape.cut(mortar_compound)
            if result.isNull():
                App.Console.PrintError("BrickProxy: boolean cut returned null shape\n")
                return

            obj.Shape = result
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


class BrickViewProxy:
    """Minimal view provider."""

    def __init__(self, vobj):
        vobj.Proxy = self

    def getIcon(self):
        return ":/icons/Part_Box.svg"

    def attach(self, vobj):
        self.Object = vobj.Object

    def updateData(self, obj, prop):
        pass

    def onChanged(self, vobj, prop):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        pass

    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)
