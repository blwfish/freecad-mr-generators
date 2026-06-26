"""
Shingle FeaturePython proxy — parametric shingle generator for FreeCAD.

Change any property in the panel and the shingles regenerate automatically.
Face references are stored as PropertyLinkSubList so they survive save/reload.
Properties can be bound to spreadsheets or VarSets via expressions (right-click
→ Set expression).

This module must be importable by FreeCAD (lives on sys.path via Macro dir).
"""

import FreeCAD as App
import Part
import math
import sys
from pathlib import Path

VERSION = "6.0.0"

# Ensure geometry library is importable (same directory)
_here = Path(__file__).parent
for p in (str(_here), str(_here / '_lib')):
    if p not in sys.path:
        sys.path.insert(0, p)

from shingle_geometry import (
    validate_parameters,
    validate_stagger_pattern,
    calculate_layout,
    calculate_stagger_offset,
    get_roof_coordinate_system,
)


# =============================================================================
# Helpers (face coordinate system, clipping)
# =============================================================================

def _scale_vector(vec, scale):
    """Scale a FreeCAD Vector by a scalar."""
    return App.Vector(vec.x * scale, vec.y * scale, vec.z * scale)


def _get_face_coordinate_system(face):
    """
    Extract coordinate system from a planar roof face using bounding-box method.

    Returns (origin, u_vec, v_vec, normal, u_length, v_length).
    """
    vertices_tuples = [(v.Point.x, v.Point.y, v.Point.z) for v in face.Vertexes]

    fc_normal = face.normalAt(0.5, 0.5).normalize()
    # Ensure outward normal (positive Z for non-vertical roof faces)
    if fc_normal.z < 0:
        fc_normal = App.Vector(-fc_normal.x, -fc_normal.y, -fc_normal.z)
    normal_tuple = (fc_normal.x, fc_normal.y, fc_normal.z)

    coord_sys = get_roof_coordinate_system(vertices_tuples, normal_tuple)

    origin = App.Vector(*coord_sys['origin'])
    u_vec = App.Vector(*coord_sys['u_vec'])
    v_vec = App.Vector(*coord_sys['v_vec'])
    normal = App.Vector(*coord_sys['normal'])

    # Prefer corner vertex (2 edges meeting) at eave level as origin
    vertices = face.Vertexes
    edges = face.Edges

    # Key by rounded coordinates — FreeCAD returns new wrapper objects on
    # each Vertexes access, so object identity is not stable across loops.
    def _vkey(v):
        return (round(v.Point.x, 4), round(v.Point.y, 4), round(v.Point.z, 4))

    vertex_edge_count = {}
    for vertex in vertices:
        count = 0
        for edge in edges:
            v1 = edge.Vertexes[0].Point
            v2 = edge.Vertexes[1].Point
            if (v1.distanceToPoint(vertex.Point) < 0.001
                    or v2.distanceToPoint(vertex.Point) < 0.001):
                count += 1
        vertex_edge_count[_vkey(vertex)] = count

    eave_z = coord_sys['eave_ridge_info']['eave_z']
    z_tolerance = 0.1
    corner_vertices_at_eave = [
        v for v in vertices
        if vertex_edge_count.get(_vkey(v), 0) == 2 and abs(v.Point.z - eave_z) <= z_tolerance
    ]
    if corner_vertices_at_eave:
        origin = min(corner_vertices_at_eave,
                     key=lambda v: v.Point.dot(u_vec)).Point

    # Calculate face extents by projecting all vertices onto U and V
    u_projs = [vtx.Point.sub(origin).dot(u_vec) for vtx in face.Vertexes]
    v_projs = [vtx.Point.sub(origin).dot(v_vec) for vtx in face.Vertexes]

    min_u, min_v = min(u_projs), min(v_projs)
    if min_u < 0 or min_v < 0:
        origin = origin + _scale_vector(u_vec, min_u) + _scale_vector(v_vec, min_v)

    u_length = max(u_projs) - min(u_projs)
    v_length = max(v_projs) - min(v_projs)

    return origin, u_vec, v_vec, normal, u_length, v_length


def _build_clip_volumes(face):
    """Create dual-direction extrusion clip volumes from a face."""
    extrusion_depth = 100.0
    topo_normal = face.normalAt(0.5, 0.5)
    if topo_normal.Length > 1e-9:
        topo_normal.normalize()
    clip_pos = face.extrude(topo_normal * extrusion_depth)
    clip_neg = face.extrude(topo_normal * (-extrusion_depth))
    return [clip_pos, clip_neg]


def _clip_shape(shape, clip_volumes):
    """Clip a shape against dual clip volumes. Returns clipped shape or None."""
    for cv in clip_volumes:
        try:
            result = shape.common(cv)
            if result.ShapeType == 'Compound' and len(result.Solids) == 1:
                result = result.Solids[0]
            if result.Volume > 0.001:
                return result
        except Exception:
            continue
    return None


# =============================================================================
# Shingle generation (from face + params dict)
# =============================================================================

def _generate_shingles_for_face(face, params):
    """Generate shingle shapes for a single face. Returns list of Solids."""
    shingle_width = params['shingle_width']
    shingle_height = params['shingle_height']
    material_thickness = params['material_thickness']
    exposure = params['shingle_exposure']
    stagger_pattern = params['stagger_pattern']
    wedge_thickness = params['wedge_thickness']
    chamfer = params['chamfer']

    origin, u_vec, v_vec, normal, u_length, v_length = \
        _get_face_coordinate_system(face)

    layout = calculate_layout(u_length, v_length, shingle_width,
                              exposure, stagger_pattern)
    num_courses = layout['num_courses']
    shingles_per_course = layout['shingles_per_course']
    max_stagger = layout['max_stagger']

    # Build clip volumes
    try:
        clip_volumes = _build_clip_volumes(face)
    except Exception:
        clip_volumes = None

    # Build rotation matrix (right-handed, det=+1)
    rotation_matrix = App.Matrix(
        u_vec.x, v_vec.x, normal.x, 0,
        u_vec.y, v_vec.y, normal.y, 0,
        u_vec.z, v_vec.z, normal.z, 0,
        0, 0, 0, 1
    )
    final_rotation = App.Rotation(rotation_matrix)

    shingle_shapes = []

    for row in range(num_courses):
        stagger = calculate_stagger_offset(row, stagger_pattern, shingle_width)

        for col in range(shingles_per_course):
            u = col * shingle_width + stagger - max_stagger
            v = row * exposure - exposure

            top_position = (origin
                            + _scale_vector(u_vec, u)
                            + _scale_vector(v_vec, v))

            if row == 0:
                # Starter course: rectangular box
                shingle_shape = Part.makeBox(shingle_width, exposure,
                                             material_thickness)
                butt_position = top_position + _scale_vector(v_vec, -exposure)
            else:
                # Tapered trapezoidal cross-section
                top_thick = wedge_thickness * 0.2
                p0 = App.Vector(0, 0, 0)
                p1 = App.Vector(0, 0, wedge_thickness)
                p2 = App.Vector(0, shingle_height, top_thick)
                p3 = App.Vector(0, shingle_height, 0)

                profile_wire = Part.Wire([
                    Part.LineSegment(p0, p1).toShape(),
                    Part.LineSegment(p1, p2).toShape(),
                    Part.LineSegment(p2, p3).toShape(),
                    Part.LineSegment(p3, p0).toShape(),
                ])
                profile_face = Part.Face(profile_wire)
                shingle_shape = profile_face.extrude(
                    App.Vector(shingle_width, 0, 0))
                butt_position = top_position + _scale_vector(v_vec,
                                                             -shingle_height)

            # Chamfer one vertical edge
            if chamfer > 0:
                try:
                    bb = shingle_shape.BoundBox
                    best_edge = None
                    best_score = -1
                    for edge in shingle_shape.Edges:
                        verts = edge.Vertexes
                        if len(verts) != 2:
                            continue
                        v0, v1 = verts[0].Point, verts[1].Point
                        avg_x = (v0.x + v1.x) / 2.0
                        avg_z = (v0.z + v1.z) / 2.0
                        score = avg_x / bb.XLength + avg_z / bb.ZLength
                        dy = abs(v1.y - v0.y)
                        if dy > edge.Length * 0.9 and score > best_score:
                            best_score = score
                            best_edge = edge
                    if best_edge is not None:
                        chamfered = shingle_shape.makeChamfer(chamfer,
                                                              [best_edge])
                        if (chamfered.ShapeType == 'Compound'
                                and len(chamfered.Solids) == 1):
                            shingle_shape = chamfered.Solids[0]
                        else:
                            shingle_shape = chamfered
                except Exception:
                    pass

            shingle_shape.Placement = App.Placement(butt_position,
                                                    final_rotation)

            # Clip to face boundary
            if clip_volumes is not None:
                clipped = _clip_shape(shingle_shape, clip_volumes)
                if clipped is not None:
                    shingle_shapes.append(clipped)
            else:
                shingle_shapes.append(shingle_shape)

    return shingle_shapes


# =============================================================================
# FeaturePython proxy
# =============================================================================

class ShingleProxy:
    """Parametric shingle object. Change a property -> shingles update."""

    Type = "ShingleGenerator"

    def __init__(self, obj):
        obj.Proxy = self
        self._setup_properties(obj)

    # -- property setup -------------------------------------------------------

    @staticmethod
    def _setup_properties(obj):
        grp = "Shingle"

        if not hasattr(obj, 'Sources'):
            obj.addProperty(
                "App::PropertyLinkSubList", "Sources", grp,
                "Roof faces to apply shingles to")

        if not hasattr(obj, 'ShingleWidth'):
            obj.addProperty(
                "App::PropertyLength", "ShingleWidth", grp,
                "Width of each shingle")
        if not hasattr(obj, 'ShingleHeight'):
            obj.addProperty(
                "App::PropertyLength", "ShingleHeight", grp,
                "Height (length) of each shingle")
        if not hasattr(obj, 'MaterialThickness'):
            obj.addProperty(
                "App::PropertyLength", "MaterialThickness", grp,
                "Material sheet thickness")
        if not hasattr(obj, 'Exposure'):
            obj.addProperty(
                "App::PropertyLength", "Exposure", grp,
                "Exposed portion per course")

        if not hasattr(obj, 'StaggerPattern'):
            obj.addProperty(
                "App::PropertyEnumeration", "StaggerPattern", grp,
                "Horizontal stagger pattern")
            obj.StaggerPattern = ['half', 'third', 'none']

        if not hasattr(obj, 'WedgeThickness'):
            obj.addProperty(
                "App::PropertyLength", "WedgeThickness", grp,
                "Butt-edge wedge thickness (0 = auto: 3x material)")
        if not hasattr(obj, 'Chamfer'):
            obj.addProperty(
                "App::PropertyLength", "Chamfer", grp,
                "V-groove chamfer at shingle edge (0 = auto: 1.5x material)")

        if not hasattr(obj, 'GeneratorVersion'):
            obj.addProperty(
                "App::PropertyString", "GeneratorVersion", grp,
                "Generator version (read-only)")
            obj.setEditorMode("GeneratorVersion", 1)

    # -- defaults -------------------------------------------------------------

    @staticmethod
    def set_defaults(obj, params=None):
        """Apply parameter values to the object's properties."""
        if params is None:
            params = {}
        obj.ShingleWidth = params.get('shingle_width', 3.5)
        obj.ShingleHeight = params.get('shingle_height', 2.0)
        obj.MaterialThickness = params.get('material_thickness', 0.25)
        obj.Exposure = params.get('shingle_exposure', 1.5)
        obj.StaggerPattern = params.get('stagger_pattern', 'half')
        obj.WedgeThickness = params.get('wedge_thickness', 0.0)
        obj.Chamfer = params.get('chamfer', 0.0)
        obj.GeneratorVersion = VERSION

    # -- execute (called on recompute) ----------------------------------------

    def execute(self, obj):
        if not obj.Sources:
            return

        # Resolve auto values
        mat_thick = float(obj.MaterialThickness)
        wedge = float(obj.WedgeThickness)
        if wedge == 0:
            wedge = mat_thick * 3
        chamfer = float(obj.Chamfer)
        if chamfer == 0:
            chamfer = mat_thick * 1.5

        params = {
            'shingle_width':      float(obj.ShingleWidth),
            'shingle_height':     float(obj.ShingleHeight),
            'material_thickness': mat_thick,
            'shingle_exposure':   float(obj.Exposure),
            'stagger_pattern':    str(obj.StaggerPattern),
            'wedge_thickness':    wedge,
            'chamfer':            chamfer,
        }

        # Validate
        valid, errors = validate_parameters(
            params['shingle_width'], params['shingle_height'],
            params['material_thickness'], params['shingle_exposure'])
        if not valid:
            App.Console.PrintError(
                f"ShingleGenerator: invalid parameters: {errors}\n")
            return

        valid, msg = validate_stagger_pattern(params['stagger_pattern'])
        if not valid:
            App.Console.PrintError(f"ShingleGenerator: {msg}\n")
            return

        # Resolve LinkSubList -> faces
        all_shingles = []
        for link_obj, sub_names in obj.Sources:
            for sub_name in sub_names:
                if not sub_name.startswith("Face"):
                    continue
                face = link_obj.Shape.getElement(sub_name)
                try:
                    pieces = _generate_shingles_for_face(face, params)
                    all_shingles.extend(pieces)
                except Exception as e:
                    App.Console.PrintError(
                        f"  {link_obj.Label}.{sub_name}: {e}\n")

        if not all_shingles:
            App.Console.PrintWarning("ShingleGenerator: no shingles generated\n")
            return

        obj.Shape = Part.Compound(all_shingles)

    # -- serialisation --------------------------------------------------------

    def dumps(self):
        return {"Type": self.Type}

    def loads(self, state):
        if state:
            self.Type = state.get("Type", "ShingleGenerator")

    # Legacy names (FreeCAD < 0.21.2)
    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)


class ShingleViewProxy:
    """View provider — icon and default colour."""

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
