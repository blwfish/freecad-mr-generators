"""
Standing Seam FeaturePython proxy — parametric standing seam roof generator.

Generates vertical metal panels with raised seam ridges running eave-to-ridge.
Each panel is extruded as a single solid along the slope direction; the
face-extrusion clip volumes handle all hip/valley boundary trimming.

Change any property in the Properties panel and panels regenerate.
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

from standing_seam_geometry import (
    validate_parameters,
    calculate_panel_layout,
    generate_panel_profile,
    get_roof_coordinate_system,
)
from freecad_utils import resolve_sources_faces  # noqa: E402


# ---------------------------------------------------------------------------
# FreeCAD geometry helpers
# ---------------------------------------------------------------------------

def _sv(vec, scale):
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
    depth = 100.0
    n = face.normalAt(0.5, 0.5)
    if n.Length > 1e-9:
        n.normalize()
    return [face.extrude(n * depth), face.extrude(n * (-depth))]


def _clip_shape(shape, clip_volumes):
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


# ---------------------------------------------------------------------------
# Panel generation
# ---------------------------------------------------------------------------

def _generate_panels_for_face(face, params):
    """Generate standing seam panel solids for one roof face."""
    panel_width     = params['panel_width']
    seam_height     = params['seam_height']
    seam_width      = params['seam_width']
    panel_thickness = params['panel_thickness']

    origin, u_vec, v_vec, normal, u_length, v_length = \
        _get_face_coordinate_system(face)

    layout   = calculate_panel_layout(u_length, panel_width)
    n_panels = layout['num_panels']
    start_u  = layout['start_u']

    profile_pts = generate_panel_profile(
        panel_width, seam_height, seam_width, panel_thickness)

    try:
        clip_volumes = _build_clip_volumes(face)
    except Exception:
        clip_volumes = None

    extrude_vec = _sv(v_vec, v_length)
    shapes = []

    for i in range(n_panels):
        u_start = start_u + i * panel_width
        # Base point at eave level, left edge of this panel
        base = origin + _sv(u_vec, u_start)

        # Build 3D profile points at the eave (v=0)
        # Each (u_local, z_local) → 3D via: base + u_local*u_vec + z_local*normal
        pts_3d = [
            base + _sv(u_vec, u_loc) + _sv(normal, z_loc)
            for u_loc, z_loc in profile_pts
        ]

        # Close the wire: last point back to first
        try:
            edges = []
            for j in range(len(pts_3d)):
                p_a = pts_3d[j]
                p_b = pts_3d[(j + 1) % len(pts_3d)]
                if p_a.distanceToPoint(p_b) > 1e-6:
                    edges.append(Part.makeLine(p_a, p_b))

            if len(edges) < 3:
                continue

            wire = Part.Wire(edges)
            panel_face = Part.Face(wire)
            panel_solid = panel_face.extrude(extrude_vec)

            if clip_volumes is not None:
                clipped = _clip_shape(panel_solid, clip_volumes)
                if clipped is not None:
                    shapes.append(clipped)
            else:
                shapes.append(panel_solid)

        except Exception as e:
            App.Console.PrintMessage(f"  Panel {i}: {e}\n")

    return shapes


# ---------------------------------------------------------------------------
# FeaturePython proxy
# ---------------------------------------------------------------------------

class StandingSeamProxy:
    """Parametric standing seam object. Change a property → panels update."""

    Type = "StandingSeamGenerator"

    def __init__(self, obj):
        obj.Proxy = self
        self._setup_properties(obj)

    @staticmethod
    def _setup_properties(obj):
        grp = "StandingSeam"
        if not hasattr(obj, 'Sources'):
            obj.addProperty("App::PropertyLinkSubList", "Sources", grp,
                            "Roof faces to apply standing seam to")
        if not hasattr(obj, 'PanelWidth'):
            obj.addProperty("App::PropertyLength", "PanelWidth", grp,
                            "Panel width (centre-to-centre seam spacing)")
        if not hasattr(obj, 'SeamHeight'):
            obj.addProperty("App::PropertyLength", "SeamHeight", grp,
                            "Height of raised seam ridge")
        if not hasattr(obj, 'SeamWidth'):
            obj.addProperty("App::PropertyLength", "SeamWidth", grp,
                            "Width of raised seam ridge")
        if not hasattr(obj, 'PanelThickness'):
            obj.addProperty("App::PropertyLength", "PanelThickness", grp,
                            "Flat panel material thickness")
        if not hasattr(obj, 'GeneratorVersion'):
            obj.addProperty("App::PropertyString", "GeneratorVersion", grp,
                            "Generator version (read-only)")
            obj.setEditorMode("GeneratorVersion", 1)

    @staticmethod
    def set_defaults(obj, params=None):
        p = params or {}
        obj.PanelWidth      = p.get('panel_width',      3.0)
        obj.SeamHeight      = p.get('seam_height',      0.35)
        obj.SeamWidth       = p.get('seam_width',       0.4)
        obj.PanelThickness  = p.get('panel_thickness',  0.15)
        obj.GeneratorVersion = VERSION

    def execute(self, obj):
        if not obj.Sources:
            return

        params = {
            'panel_width':     float(obj.PanelWidth),
            'seam_height':     float(obj.SeamHeight),
            'seam_width':      float(obj.SeamWidth),
            'panel_thickness': float(obj.PanelThickness),
        }

        valid, errors = validate_parameters(
            params['panel_width'], params['seam_height'],
            params['seam_width'],  params['panel_thickness'])
        if not valid:
            App.Console.PrintError(
                f"StandingSeamGenerator: invalid parameters: {errors}\n")
            return

        all_panels = []
        for face, link_obj, sub_name in resolve_sources_faces(obj.Sources, "StandingSeamGenerator"):
            try:
                all_panels.extend(_generate_panels_for_face(face, params))
            except Exception as e:
                App.Console.PrintError(
                    f"  {link_obj.Label}.{sub_name}: {e}\n")

        if not all_panels:
            App.Console.PrintWarning(
                "StandingSeamGenerator: no panels generated\n")
            return

        obj.Shape = Part.Compound(all_panels)

    def dumps(self):
        return {"Type": self.Type}

    def loads(self, state):
        if state:
            self.Type = state.get("Type", "StandingSeamGenerator")

    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)


class StandingSeamViewProxy:
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
