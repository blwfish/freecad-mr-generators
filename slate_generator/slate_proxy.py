"""
Slate Tile FeaturePython proxy — parametric slate roof generator for FreeCAD.

Flat rectangular tiles of uniform thickness, laid in staggered courses.
The butt-step shadow at each course comes from the overlap geometry alone
(no wedge taper as in wood shingles).

Change any property in the Properties panel and the tiles regenerate.
"""

import FreeCAD as App
import Part
import math
import sys
from pathlib import Path

VERSION = "1.0.0"

_here = Path(__file__).parent
for _p in (str(_here), str(_here / '_lib')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from slate_geometry import (
    validate_parameters,
    validate_stagger_pattern,
    calculate_layout,
    calculate_stagger_offset,
    get_roof_coordinate_system,
    is_valid_clip_fragment,
)


# ---------------------------------------------------------------------------
# FreeCAD geometry helpers (shared pattern with shingle_proxy.py)
# ---------------------------------------------------------------------------

def _sv(vec, scale):
    """Scale a FreeCAD Vector."""
    return App.Vector(vec.x * scale, vec.y * scale, vec.z * scale)


def _get_face_coordinate_system(face):
    """
    Extract U/V/normal coordinate system from a roof face.
    Returns (origin, u_vec, v_vec, normal, u_length, v_length).
    """
    verts = [(v.Point.x, v.Point.y, v.Point.z) for v in face.Vertexes]
    n = face.normalAt(0.5, 0.5).normalize()
    if n.z < 0:
        n = App.Vector(-n.x, -n.y, -n.z)
    normal_t = (n.x, n.y, n.z)

    cs = get_roof_coordinate_system(verts, normal_t)
    origin = App.Vector(*cs['origin'])
    u_vec  = App.Vector(*cs['u_vec'])
    v_vec  = App.Vector(*cs['v_vec'])
    normal = App.Vector(*cs['normal'])

    # Prefer corner vertex (2 edges) at eave level as origin.
    # Key by rounded coordinates — FreeCAD returns new wrapper objects on
    # each Vertexes iteration, so object identity is not stable across loops.
    def _vkey(v):
        return (round(v.Point.x, 4), round(v.Point.y, 4), round(v.Point.z, 4))

    vertex_edge_count = {}
    for vertex in face.Vertexes:
        count = sum(
            1 for edge in face.Edges
            if (edge.Vertexes[0].Point.distanceToPoint(vertex.Point) < 0.001 or
                edge.Vertexes[1].Point.distanceToPoint(vertex.Point) < 0.001)
        )
        vertex_edge_count[_vkey(vertex)] = count

    eave_z = cs['eave_ridge_info']['eave_z']
    corner_at_eave = [
        v for v in face.Vertexes
        if vertex_edge_count.get(_vkey(v), 0) == 2 and abs(v.Point.z - eave_z) <= 0.1
    ]
    if corner_at_eave:
        origin = min(corner_at_eave, key=lambda v: v.Point.dot(u_vec)).Point

    u_projs = [vtx.Point.sub(origin).dot(u_vec) for vtx in face.Vertexes]
    v_projs = [vtx.Point.sub(origin).dot(v_vec) for vtx in face.Vertexes]
    min_u, min_v = min(u_projs), min(v_projs)
    if min_u < 0 or min_v < 0:
        origin = origin + _sv(u_vec, min_u) + _sv(v_vec, min_v)

    u_length = max(u_projs) - min(u_projs)
    v_length = max(v_projs) - min(v_projs)
    return origin, u_vec, v_vec, normal, u_length, v_length


def _build_clip_volumes(face):
    """Dual-direction extrusion clip volumes from a face."""
    depth = 100.0
    n = face.normalAt(0.5, 0.5)
    if n.Length > 1e-9:
        n.normalize()
    return [face.extrude(n * depth), face.extrude(n * (-depth))]


def _clip_shape(shape, clip_volumes):
    """Clip *shape* against dual clip volumes. Returns clipped solid or None.

    Survival is judged against the shape's own pre-clip volume (see
    is_valid_clip_fragment) rather than a fixed absolute threshold, so a
    razor-thin sliver at a ridge/hip boundary is discarded instead of
    surviving as a stray fragment.
    """
    full_volume = shape.Volume
    for cv in clip_volumes:
        try:
            result = shape.common(cv)
            if result.ShapeType == 'Compound' and len(result.Solids) == 1:
                result = result.Solids[0]
            if is_valid_clip_fragment(result.Volume, full_volume):
                return result
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Tile generation
# ---------------------------------------------------------------------------

def _generate_tiles_for_face(face, params):
    """Generate slate tile solids for one roof face."""
    tile_width   = params['tile_width']
    tile_height  = params['tile_height']
    mat_thick    = params['material_thickness']
    butt_thick   = params['butt_thickness']
    exposure     = params['exposure']
    stagger_pat  = params['stagger_pattern']

    origin, u_vec, v_vec, normal, u_length, v_length = \
        _get_face_coordinate_system(face)

    layout = calculate_layout(u_length, v_length, tile_width, exposure, stagger_pat)
    num_courses     = layout['num_courses']
    tiles_per_course = layout['tiles_per_course']
    max_stagger     = layout['max_stagger']

    try:
        clip_volumes = _build_clip_volumes(face)
    except Exception:
        clip_volumes = None

    rotation_matrix = App.Matrix(
        u_vec.x, v_vec.x, normal.x, 0,
        u_vec.y, v_vec.y, normal.y, 0,
        u_vec.z, v_vec.z, normal.z, 0,
        0, 0, 0, 1,
    )
    rotation = App.Rotation(rotation_matrix)

    shapes = []
    for row in range(num_courses):
        stagger = calculate_stagger_offset(row, stagger_pat, tile_width)
        for col in range(tiles_per_course):
            u = col * tile_width + stagger - max_stagger
            v = row * exposure - exposure  # one course below origin at row=0

            top_pos  = origin + _sv(u_vec, u) + _sv(v_vec, v)
            butt_pos = top_pos + _sv(v_vec, -tile_height)

            if row == 0 or butt_thick <= mat_thick:
                # Starter course or no wedge: flat box
                tile = Part.makeBox(tile_width, tile_height, mat_thick)
            else:
                # Wedge cross-section: thick at butt, tapers to near-zero at head.
                # Local space: X=u_vec, Y=v_vec (up-slope), Z=normal (outward).
                # The butt sits elevated above the tile below; the head rests near
                # the deck so the next tile above can sit on this one's face.
                top_thick = butt_thick * 0.2
                p0 = App.Vector(0, 0, 0)
                p1 = App.Vector(0, 0, butt_thick)
                p2 = App.Vector(0, tile_height, top_thick)
                p3 = App.Vector(0, tile_height, 0)
                profile = Part.Wire([
                    Part.LineSegment(p0, p1).toShape(),
                    Part.LineSegment(p1, p2).toShape(),
                    Part.LineSegment(p2, p3).toShape(),
                    Part.LineSegment(p3, p0).toShape(),
                ])
                tile = Part.Face(profile).extrude(App.Vector(tile_width, 0, 0))

            tile.Placement = App.Placement(butt_pos, rotation)

            if clip_volumes is not None:
                clipped = _clip_shape(tile, clip_volumes)
                if clipped is not None:
                    shapes.append(clipped)
            else:
                shapes.append(tile)

    return shapes


# ---------------------------------------------------------------------------
# FeaturePython proxy
# ---------------------------------------------------------------------------

class SlateProxy:
    """Parametric slate tile object. Change a property → tiles update."""

    Type = "SlateGenerator"

    def __init__(self, obj):
        obj.Proxy = self
        self._setup_properties(obj)

    @staticmethod
    def _setup_properties(obj):
        grp = "Slate"
        if not hasattr(obj, 'Sources'):
            obj.addProperty("App::PropertyLinkSubList", "Sources", grp,
                            "Roof faces to apply slate to")
        if not hasattr(obj, 'TileWidth'):
            obj.addProperty("App::PropertyLength", "TileWidth", grp,
                            "Width of each slate tile")
        if not hasattr(obj, 'TileHeight'):
            obj.addProperty("App::PropertyLength", "TileHeight", grp,
                            "Height (length) of each slate tile")
        if not hasattr(obj, 'MaterialThickness'):
            obj.addProperty("App::PropertyLength", "MaterialThickness", grp,
                            "Slate thickness")
        if not hasattr(obj, 'Exposure'):
            obj.addProperty("App::PropertyLength", "Exposure", grp,
                            "Exposed portion per course")
        if not hasattr(obj, 'ButtThickness'):
            obj.addProperty("App::PropertyLength", "ButtThickness", grp,
                            "Tile thickness at butt edge (0 = auto: 3× MaterialThickness)")
        if not hasattr(obj, 'StaggerPattern'):
            obj.addProperty("App::PropertyEnumeration", "StaggerPattern", grp,
                            "Horizontal stagger pattern")
            obj.StaggerPattern = ['half', 'third', 'none']
        if not hasattr(obj, 'GeneratorVersion'):
            obj.addProperty("App::PropertyString", "GeneratorVersion", grp,
                            "Generator version (read-only)")
            obj.setEditorMode("GeneratorVersion", 1)

    @staticmethod
    def set_defaults(obj, params=None):
        p = params or {}
        obj.TileWidth         = p.get('tile_width',          2.0)
        obj.TileHeight        = p.get('tile_height',          2.5)
        obj.MaterialThickness = p.get('material_thickness',   0.2)
        obj.ButtThickness     = p.get('butt_thickness',       0.0)
        # Exposure close to TileHeight (ratio ~1.14, was 1.2 -> ~2.08) gives
        # single-thickness coverage with just enough overlap for the
        # butt-shadow line -- these tiles sit on an already-solid roof face,
        # so full double-lap (real-slate) coverage isn't needed on the model.
        obj.Exposure          = p.get('exposure',             2.2)
        obj.StaggerPattern    = p.get('stagger_pattern',     'half')
        obj.GeneratorVersion  = VERSION

    def execute(self, obj):
        if not obj.Sources:
            return

        mat_thick  = float(obj.MaterialThickness)
        butt_thick = float(obj.ButtThickness)
        if butt_thick == 0:
            butt_thick = mat_thick * 3

        params = {
            'tile_width':         float(obj.TileWidth),
            'tile_height':        float(obj.TileHeight),
            'material_thickness': mat_thick,
            'butt_thickness':     butt_thick,
            'exposure':           float(obj.Exposure),
            'stagger_pattern':    str(obj.StaggerPattern),
        }

        valid, errors = validate_parameters(
            params['tile_width'], params['tile_height'],
            params['material_thickness'], params['exposure'])
        if not valid:
            App.Console.PrintError(f"SlateGenerator: invalid parameters: {errors}\n")
            return

        valid, msg = validate_stagger_pattern(params['stagger_pattern'])
        if not valid:
            App.Console.PrintError(f"SlateGenerator: {msg}\n")
            return

        all_tiles = []
        for link_obj, sub_names in obj.Sources:
            for sub_name in sub_names:
                if not sub_name.startswith('Face'):
                    continue
                face = link_obj.Shape.getElement(sub_name)
                try:
                    all_tiles.extend(_generate_tiles_for_face(face, params))
                except Exception as e:
                    App.Console.PrintError(
                        f"  {link_obj.Label}.{sub_name}: {e}\n")

        if not all_tiles:
            App.Console.PrintWarning("SlateGenerator: no tiles generated\n")
            return

        obj.Shape = Part.Compound(all_tiles)

    def dumps(self):
        return {"Type": self.Type}

    def loads(self, state):
        if state:
            self.Type = state.get("Type", "SlateGenerator")

    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)


class SlateViewProxy:
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
