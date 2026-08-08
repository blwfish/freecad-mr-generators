"""
QuoinProxy — FeaturePython proxy for parametric brick quoin columns.

SUPERSEDED for new walls: as of brick_proxy.py v6.1.0, BrickProxy generates
the real quoin column itself (via quoin_geometry.QuoinGeometry) in the same
cut as the field fill when LeftQuoin/RightQuoin=True — this second pass is
no longer part of the normal workflow. QuoinProxy remains only as a
touch-up path for walls that were already fully bricked without ever
setting LeftQuoin/RightQuoin (see the fragmentation caveat below, which
applies just as much here as it did before).

Applies to two adjacent wall faces that share a corner edge.  When used
alongside BrickProxy (with left_quoin=True on the fill faces), produces
correctly interlocking corner brickwork.

Workflow:
  1. Apply BrickProxy to all wall faces with left_quoin=True on the sides
     that have corners.  This leaves the quoin region un-engraved.
  2. Apply QuoinProxy to the resulting BrickedWall, selecting the corner
     edge.  This engraves the quoin column into both adjacent faces.

Selection: the Corners property accepts, per corner, either:
  - one or more Edge sub-elements (Edge1, etc.) — the two adjacent faces
    are auto-discovered from the edge. Works well on simple, unfragmented
    geometry (e.g. a plain box corner) where the corner is one continuous
    edge. Each edge must be shared between exactly two faces (a
    non-manifold edge signals a problem).
  - exactly two Face sub-elements in one Corners entry — used directly as
    face_a/face_b, no edge lookup. Needed once Source has already been
    through brick/mortar engraving: the true corner edge fragments into
    many short segments whose locally-adjacent faces are tiny brick/mortar
    fragments rather than the whole wall faces this proxy expects.

Face A / Face B convention: the face with the lower numerical index is
treated as Face A (primary: stretcher on even courses).  The other is
Face B (header-return on even courses).  Toggle SwapFaces to reverse if
the pattern appears offset by one course.

The brick parameters (BrickWidth, BrickHeight, BrickDepth, Mortar,
MortarDepth, BondType) must match the values used in BrickProxy so that
mortar joints align across the column/fill boundary.
"""

import FreeCAD as App
import Part
import math
import sys
from pathlib import Path

VERSION = "1.0.0"
GENERATOR_NAME = "quoin_generator"

_here = Path(__file__).parent
for p in (str(_here), str(_here.parent / 'brick_generator')):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import quoin_geometry as _qg
    from quoin_geometry import QuoinGeometry
except ImportError:
    _qg = None
    QuoinGeometry = None

try:
    import brick_geometry as _bg
    from brick_geometry import BrickDef
except ImportError:
    _bg = None
    BrickDef = None


# ---------------------------------------------------------------------------
# Geometry helpers (shared with brick_proxy)
# ---------------------------------------------------------------------------

def _scale(vec, s):
    return App.Vector(vec.x * s, vec.y * s, vec.z * s)


def _get_face_coordinate_system(face):
    """U/V/normal coordinate system for a face (same logic as brick_proxy)."""
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
    normal = face.normalAt((uv[0] + uv[1]) / 2, (uv[2] + uv[3]) / 2)

    z_axis = next((a for a in axes if a[1] == 'z'), None)
    others = [a for a in axes if a[1] != 'z']

    if z_axis and z_axis[0] > 0.001:
        v_vec = z_axis[2]
        v_length = z_axis[0]
        best_u, best_len = None, 0
        for rng, _, vec in others:
            if abs(vec.dot(normal)) < 0.5 and rng > best_len:
                best_u, best_len = vec, rng
        if best_u is None:
            best_u, best_len = others[0][2], others[0][0]
        u_vec = best_u
        u_length = best_len
        is_horizontal = False
    else:
        horiz = [(r, n2, v) for r, n2, v in axes if n2 != 'z']
        horiz.sort(reverse=True)
        if len(horiz) < 2 or horiz[0][0] < 0.001:
            raise ValueError("Face has no meaningful horizontal extent.")
        u_vec = horiz[0][2]
        u_length = horiz[0][0]
        v_vec = horiz[1][2]
        v_length = horiz[1][0] if horiz[1][0] > 0.001 else u_length
        is_horizontal = True

    return origin, u_vec, v_vec, normal, u_length, v_length, is_horizontal


def _snap_origin_to_grid(origin, u_vec, v_vec, brick_width, brick_height, mortar):
    vert_grid = brick_height + mortar
    normal = u_vec.cross(v_vec)
    normal.normalize()
    origin_u = origin.dot(u_vec)
    origin_v = origin.dot(v_vec)
    origin_n = origin.dot(normal)
    snapped_v = round(origin_v / vert_grid) * vert_grid
    return _scale(u_vec, origin_u) + _scale(v_vec, snapped_v) + _scale(normal, origin_n)


def _create_brick_from_def(brick_def, origin, u_vec, v_vec, normal):
    """Build one brick solid from a BrickDef (identical to brick_proxy version)."""
    u, v = brick_def.u, brick_def.v
    w, h, d = brick_def.width, brick_def.height, brick_def.depth

    p0 = origin + _scale(u_vec, u)     + _scale(v_vec, v)
    p1 = origin + _scale(u_vec, u + w) + _scale(v_vec, v)
    p2 = origin + _scale(u_vec, u + w) + _scale(v_vec, v + h)
    p3 = origin + _scale(u_vec, u)     + _scale(v_vec, v + h)
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
    e0, e1, e2, e3, e4, e5, e6, e7, e8, e9, e10, e11 = edges
    faces = [
        Part.Face(Part.Wire([e0, e1, e2, e3])),
        Part.Face(Part.Wire([e4, e5, e6, e7])),
        Part.Face(Part.Wire([e0, e9, e4, e8])),
        Part.Face(Part.Wire([e2, e10, e6, e11])),
        Part.Face(Part.Wire([e3, e8, e7, e11])),
        Part.Face(Part.Wire([e1, e9, e5, e10])),
    ]
    return Part.Solid(Part.Shell(faces))


# ---------------------------------------------------------------------------
# Edge → face discovery
# ---------------------------------------------------------------------------

def _find_adjacent_face_indices(shape, edge, tol=1e-4):
    """
    Return the (at most two) face indices that share the given edge.

    Uses vertex-coordinate matching rather than isSame() to handle OCCT
    topological identity after Boolean operations.
    """
    def vset(e):
        return [v.Point for v in e.Vertexes]

    def close(p1, p2):
        return (p1 - p2).Length < tol

    def edges_match(ea, eb):
        va = vset(ea)
        vb = vset(eb)
        if len(va) != len(vb):
            return False
        # Check both orderings (edge may be reversed)
        fwd = all(close(va[i], vb[i]) for i in range(len(va)))
        rev = all(close(va[i], vb[len(vb) - 1 - i]) for i in range(len(va)))
        return fwd or rev

    result = []
    for fi, face in enumerate(shape.Faces):
        for fe in face.Edges:
            if edges_match(edge, fe):
                result.append(fi)
                break
    return result


# ---------------------------------------------------------------------------
# Quoin mortar grid for one face
# ---------------------------------------------------------------------------

def _create_quoin_mortar_grid(face, quoin_bricks, params):
    """
    Cut quoin column mortar channels into one face.

    quoin_bricks: List[BrickDef] for this face's column.
    Returns the mortar grid solid (face_slab minus quoin bricks).
    """
    origin, u_vec, v_vec, normal, u_length, v_length, is_horizontal = \
        _get_face_coordinate_system(face)

    brick_width  = params['brick_width']
    brick_height = params['brick_height']
    mortar       = params['mortar']
    mortar_depth = params['mortar_depth']

    gen_bh = params['brick_depth'] if is_horizontal else brick_height
    origin = _snap_origin_to_grid(origin, u_vec, v_vec, brick_width, gen_bh, mortar)

    face_slab = face.extrude(_scale(normal, -mortar_depth))

    brick_shapes = [_create_brick_from_def(bd, origin, u_vec, v_vec, normal)
                    for bd in quoin_bricks]
    if not brick_shapes:
        return face_slab

    brick_compound = Part.Compound(brick_shapes)
    try:
        clipped = brick_compound.common(face_slab)
        return face_slab.cut(clipped)
    except Exception as e:
        App.Console.PrintWarning(f"  Quoin clipping failed ({e}), unclipped fallback\n")
        return face_slab.cut(brick_compound)


# ---------------------------------------------------------------------------
# FeaturePython proxy
# ---------------------------------------------------------------------------

class QuoinProxy:
    """
    Parametric quoin column engraving for brick corners.

    Takes an already-bricked wall (BrickedWall output) and engraves the
    alternating quoin column on both sides of each selected corner edge.
    """

    Type = "QuoinedWall"

    BOND_TYPES = ['stretcher', 'english', 'flemish', 'common']

    def __init__(self, obj):
        obj.Proxy = self
        self._setup_properties(obj)

    @staticmethod
    def _setup_properties(obj):
        grp = "Quoin"
        if not hasattr(obj, 'Source'):
            obj.addProperty(
                "App::PropertyLink", "Source", grp,
                "Wall object to engrave quoins on (typically a BrickedWall)")
        if not hasattr(obj, 'Corners'):
            obj.addProperty(
                "App::PropertyLinkSubList", "Corners", grp,
                "Corner edges to treat as quoin corners")
        if not hasattr(obj, 'BondPattern'):
            obj.addProperty(
                "App::PropertyEnumeration", "BondPattern", grp,
                "Brick bond pattern (must match BrickProxy setting)")
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
        if not hasattr(obj, 'MortarDepth'):
            obj.addProperty("App::PropertyLength", "MortarDepth", grp,
                            "Mortar groove engraving depth (mm)")
        if not hasattr(obj, 'SwapFaces'):
            obj.addProperty(
                "App::PropertyBool", "SwapFaces", grp,
                "Swap Face A/B designation (shifts quoin pattern by one course)")
            obj.SwapFaces = False
        if not hasattr(obj, 'GeneratorVersion'):
            obj.addProperty(
                "App::PropertyString", "GeneratorVersion", grp,
                "Generator version (read-only)")
            obj.setEditorMode("GeneratorVersion", 1)

    @staticmethod
    def set_defaults(obj, params=None):
        p = params or {}
        obj.BondPattern   = p.get('bond_type',    'stretcher')
        obj.BrickWidth    = p.get('brick_width',   2.32)
        obj.BrickHeight   = p.get('brick_height',  0.65)
        obj.BrickDepth    = p.get('brick_depth',   1.09)
        obj.Mortar        = p.get('mortar',        0.11)
        obj.MortarDepth   = p.get('mortar_depth',  0.06)
        obj.GeneratorVersion = VERSION

    def execute(self, obj):
        if not obj.Source or not obj.Corners:
            return

        if QuoinGeometry is None:
            App.Console.PrintError(
                "QuoinProxy: quoin_geometry module not found.\n")
            return

        source_obj = obj.Source
        if not hasattr(source_obj, 'Shape'):
            return

        params = {
            'brick_width':  float(obj.BrickWidth),
            'brick_height': float(obj.BrickHeight),
            'brick_depth':  float(obj.BrickDepth),
            'mortar':       float(obj.Mortar),
            'bond_type':    str(obj.BondPattern),
            'mortar_depth': float(obj.MortarDepth),
        }
        swap = bool(obj.SwapFaces)

        working_shape = source_obj.Shape.copy()
        all_mortar_grids = []

        # Collect corner face-pairs from the Corners selection. Two ways to
        # specify a corner:
        #   - one or more Edge sub-elements: the classic path, each edge's
        #     two adjacent faces are auto-discovered via
        #     _find_adjacent_face_indices. Works well on simple, unfragmented
        #     geometry (e.g. a plain box corner).
        #   - exactly two Face sub-elements from one Corners entry: an
        #     explicit face pair, used as-is with no edge lookup. Needed once
        #     the source has already been through brick/mortar engraving —
        #     the true corner edge fragments into many short segments whose
        #     locally-adjacent faces are tiny brick/mortar fragments, not the
        #     whole wall faces _get_face_coordinate_system expects.
        edge_indices = set()
        explicit_face_pairs = []  # list of (fi_a, fi_b) tuples
        for link_obj, sub_names in obj.Corners:
            if link_obj is not source_obj:
                App.Console.PrintWarning(
                    "QuoinProxy: Corners must be selected from the Source object.\n")
                continue
            face_names = [s for s in sub_names if s.startswith('Face')]
            edge_names = [s for s in sub_names if s.startswith('Edge')]
            if face_names and not edge_names:
                if len(face_names) != 2:
                    App.Console.PrintWarning(
                        f"QuoinProxy: explicit face-pair corner needs exactly "
                        f"2 Face sub-elements, got {len(face_names)}: {face_names}.\n")
                    continue
                explicit_face_pairs.append(
                    tuple(int(n[4:]) - 1 for n in face_names))
            else:
                for sub_name in edge_names:
                    edge_indices.add(int(sub_name[4:]) - 1)

        corner_face_pairs = []  # list of (fi_a, fi_b, label) for reporting

        for edge_idx in sorted(edge_indices):
            if edge_idx >= len(working_shape.Edges):
                App.Console.PrintWarning(
                    f"QuoinProxy: edge index {edge_idx} out of range.\n")
                continue

            edge = working_shape.Edges[edge_idx]
            face_indices = _find_adjacent_face_indices(working_shape, edge)

            if len(face_indices) < 2:
                App.Console.PrintWarning(
                    f"QuoinProxy: edge {edge_idx+1} is not shared between "
                    f"two faces (found {len(face_indices)}).\n")
                continue
            if len(face_indices) > 2:
                App.Console.PrintWarning(
                    f"QuoinProxy: edge {edge_idx+1} shared by {len(face_indices)} "
                    f"faces; using first two.\n")

            corner_face_pairs.append(
                (face_indices[0], face_indices[1], f"edge {edge_idx+1}"))

        for fi_a, fi_b in explicit_face_pairs:
            for fi in (fi_a, fi_b):
                if fi >= len(working_shape.Faces):
                    App.Console.PrintWarning(
                        f"QuoinProxy: face index {fi} out of range.\n")
                    break
            else:
                corner_face_pairs.append((fi_a, fi_b, f"faces {fi_a+1}/{fi_b+1}"))

        for fi_a, fi_b, label in corner_face_pairs:
            fi_a, fi_b = sorted((fi_a, fi_b))
            if swap:
                fi_a, fi_b = fi_b, fi_a

            face_a = working_shape.Faces[fi_a]
            face_b = working_shape.Faces[fi_b]

            _, _, _, _, _, v_length_a, _ = _get_face_coordinate_system(face_a)
            _, _, _, _, _, v_length_b, _ = _get_face_coordinate_system(face_b)
            wall_height = max(v_length_a, v_length_b)

            qg = QuoinGeometry(
                wall_height=wall_height,
                brick_width=params['brick_width'],
                brick_height=params['brick_height'],
                brick_depth=params['brick_depth'],
                mortar=params['mortar'],
                bond_type=params['bond_type'],
                skin_depth=params['mortar_depth'],
            )
            result = qg.generate()

            try:
                grid_a = _create_quoin_mortar_grid(
                    face_a, result['face_a_bricks'], params)
                all_mortar_grids.append(grid_a)
            except Exception as e:
                App.Console.PrintError(
                    f"QuoinProxy face_a (Face{fi_a+1}): {e}\n")

            try:
                grid_b = _create_quoin_mortar_grid(
                    face_b, result['face_b_bricks'], params)
                all_mortar_grids.append(grid_b)
            except Exception as e:
                App.Console.PrintError(
                    f"QuoinProxy face_b (Face{fi_b+1}): {e}\n")

        if not all_mortar_grids:
            obj.Shape = working_shape
            return

        mortar_compound = (all_mortar_grids[0] if len(all_mortar_grids) == 1
                           else Part.Compound(all_mortar_grids))
        result_shape = working_shape.cut(mortar_compound)
        if result_shape.isNull():
            App.Console.PrintError("QuoinProxy: boolean cut returned null shape.\n")
            return

        obj.Shape = result_shape
        obj.Placement = source_obj.Placement
        App.Console.PrintMessage(
            f"✓ QuoinedWall updated ({len(corner_face_pairs)} corner(s), "
            f"{params['bond_type']} bond)\n")

    def dumps(self):
        return {"Type": self.Type}

    def loads(self, state):
        if state:
            self.Type = state.get("Type", "QuoinedWall")

    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)


class QuoinViewProxy:
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
