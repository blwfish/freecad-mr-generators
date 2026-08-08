"""
Standing-Seam Snow Guard FeaturePython proxy — parametric snow-guard
generator for standing-seam metal roofs.

Unlike snow_guard_generator (slate/shingle: a surface-mounted pad placed
anywhere in a free u/v grid), this generator clamps guards onto the real
seam ribs a standing_seam_generator would produce with the same
PanelWidth/SeamWidth/SeamHeight -- guard u-positions are therefore fixed
by rib phase, not a free grid, and every SeamStride'th rib gets a guard.

Like slate_seam_generator's independence from SlateTiles, this generator
re-derives rib positions from the raw roof face + panel parameters rather
than introspecting an existing StandingSeamPanels object -- Sources
should be the same faces StandingSeamPanels was built from, with
matching PanelWidth/SeamWidth/SeamHeight.

Change any property in the Properties panel and the guards regenerate.
"""

import FreeCAD as App
import Part
import sys
from pathlib import Path

VERSION = "1.0.0"

_here = Path(__file__).parent
for _p in (str(_here), str(_here / '_lib')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from standing_seam_snow_guard_geometry import (
    validate_parameters,
    validate_margins_cover_footprint,
    calculate_seam_guard_positions,
)
from roof_geometry import get_roof_coordinate_system
from freecad_utils import resolve_sources_faces  # noqa: E402
# Panel/seam defaults MUST match standing_seam_proxy.py's -- this module's
# rib centerlines are independently re-derived from an assumed panel/seam
# layout rather than reading the real one (see standing_seam_snow_guard_
# geometry.calculate_rib_u_positions), so a snow guard only lands on the
# real seam ribs if both proxies agree. Previously copy-pasted literals
# with no shared source of truth (full-review finding #13, 2026-08-08).
from standing_seam_geometry import (
    DEFAULT_PANEL_WIDTH,
    DEFAULT_SEAM_WIDTH,
    DEFAULT_SEAM_HEIGHT,
)  # noqa: E402
from snow_guard_solid_geometry import calculate_fin_position


# ---------------------------------------------------------------------------
# FreeCAD geometry helpers (shared pattern with snow_guard_proxy.py)
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


# ---------------------------------------------------------------------------
# Guard solid
# ---------------------------------------------------------------------------

def _build_guard_solid(clamp_width, clamp_length, clamp_thickness,
                        fin_height, fin_base_width, fin_thickness):
    """Build one snow guard clamp: a flat pad with a triangular-prism fin
    fused on top, centered on the pad. Local space: x=u (across-slope,
    clamp_width), y=v (up-slope, clamp_length), z=normal (clamp_thickness,
    then fin rises further in +z). The pad's origin corner is (0,0,0).

    Identical box+extruded-triangle construction to snow_guard_proxy.py's
    _build_guard_solid (renamed clamp_* params) -- no boolean operation
    against the seam rib is needed at all: this generator never fuses or
    clips a guard against the roof/seam geometry, it only places an
    independent solid in 3D space (see module docstring), so there is no
    OCCT coincidence risk from the guard's footprint overlapping the
    rib's (unrelated) solid.

    The fin-centering math (fin_x0/fin_y0) is not just "identical by
    construction" -- both this function and snow_guard_proxy.py's call
    the same shared/snow_guard_solid_geometry.calculate_fin_position, so
    the two can no longer silently diverge (full-review finding #20,
    2026-08-08; see shared/tests/test_snow_guard_solid_geometry.py).
    """
    pad = Part.makeBox(clamp_width, clamp_length, clamp_thickness)

    fin_x0, fin_y0 = calculate_fin_position(
        clamp_width, clamp_length, fin_base_width, fin_thickness)
    p0 = App.Vector(0, fin_y0, clamp_thickness)
    p1 = App.Vector(0, fin_y0 + fin_base_width, clamp_thickness)
    p2 = App.Vector(0, fin_y0 + fin_base_width / 2.0, clamp_thickness + fin_height)
    profile = Part.Wire([
        Part.LineSegment(p0, p1).toShape(),
        Part.LineSegment(p1, p2).toShape(),
        Part.LineSegment(p2, p0).toShape(),
    ])
    fin = Part.Face(profile).extrude(App.Vector(fin_thickness, 0, 0))

    fin.translate(App.Vector(fin_x0, 0, 0))

    return pad.fuse(fin)


# ---------------------------------------------------------------------------
# Seam guard generation
# ---------------------------------------------------------------------------

def _generate_seam_guards(face, params):
    """Generate placed snow guard clamp solids for one roof face.

    Assumes a roughly rectangular face and that the face's real seam
    ribs (from a standing_seam_generator run with matching PanelWidth/
    SeamWidth/SeamHeight) start flush with this face's own u=0 origin --
    see calculate_rib_u_positions' docstring for the phase derivation.
    """
    origin, u_vec, v_vec, normal, u_length, v_length = \
        _get_face_coordinate_system(face)

    positions = calculate_seam_guard_positions(
        u_length, v_length,
        params['panel_width'], params['seam_width'], params['seam_stride'],
        params['num_rows'], params['first_row_offset'], params['row_spacing'],
        params['edge_margin'], params['v_margin'])

    base_guard = _build_guard_solid(
        params['clamp_width'], params['clamp_length'], params['clamp_thickness'],
        params['fin_height'], params['fin_base_width'], params['fin_thickness'])

    rotation_matrix = App.Matrix(
        u_vec.x, v_vec.x, normal.x, 0,
        u_vec.y, v_vec.y, normal.y, 0,
        u_vec.z, v_vec.z, normal.z, 0,
        0, 0, 0, 1,
    )
    rotation = App.Rotation(rotation_matrix)

    half_clamp_u = params['clamp_width'] / 2.0
    half_clamp_v = params['clamp_length'] / 2.0
    seam_height = params['seam_height']

    shapes = []
    for row_index, u, v in positions:
        corner_pos = (origin
                      + _sv(u_vec, u - half_clamp_u)
                      + _sv(v_vec, v - half_clamp_v)
                      + _sv(normal, seam_height))
        guard = base_guard.copy()
        guard.Placement = App.Placement(corner_pos, rotation)
        shapes.append(guard)

    return shapes


# ---------------------------------------------------------------------------
# FeaturePython proxy
# ---------------------------------------------------------------------------

class StandingSeamSnowGuardProxy:
    """Parametric standing-seam snow guard grid. Change a property →
    guards update."""

    Type = "StandingSeamSnowGuardGenerator"

    def __init__(self, obj):
        obj.Proxy = self
        self._setup_properties(obj)

    @staticmethod
    def _setup_properties(obj):
        grp = "StandingSeamSnowGuard"
        if not hasattr(obj, 'Sources'):
            obj.addProperty("App::PropertyLinkSubList", "Sources", grp,
                            "Standing-seam roof faces to place snow guards on")
        if not hasattr(obj, 'PanelWidth'):
            obj.addProperty("App::PropertyLength", "PanelWidth", grp,
                            "Must match the StandingSeamPanels PanelWidth "
                            "used on these faces")
        if not hasattr(obj, 'SeamWidth'):
            obj.addProperty("App::PropertyLength", "SeamWidth", grp,
                            "Must match the StandingSeamPanels SeamWidth "
                            "used on these faces")
        if not hasattr(obj, 'SeamHeight'):
            obj.addProperty("App::PropertyLength", "SeamHeight", grp,
                            "Must match the StandingSeamPanels SeamHeight "
                            "used on these faces")
        if not hasattr(obj, 'SeamStride'):
            obj.addProperty("App::PropertyInteger", "SeamStride", grp,
                            "Guard every Nth seam rib (1 = every rib)")
        if not hasattr(obj, 'NumRows'):
            obj.addProperty("App::PropertyInteger", "NumRows", grp,
                            "Number of guard rows, up-slope from the eave")
        if not hasattr(obj, 'FirstRowOffset'):
            obj.addProperty("App::PropertyLength", "FirstRowOffset", grp,
                            "Distance from the eave to the first row")
        if not hasattr(obj, 'RowSpacing'):
            obj.addProperty("App::PropertyLength", "RowSpacing", grp,
                            "Up-slope spacing between rows")
        if not hasattr(obj, 'EdgeMargin'):
            obj.addProperty("App::PropertyLength", "EdgeMargin", grp,
                            "Minimum clearance from the rake edges when "
                            "selecting which ribs are eligible for a guard")
        if not hasattr(obj, 'VMargin'):
            obj.addProperty("App::PropertyLength", "VMargin", grp,
                            "Minimum clearance from the eave and ridge/hip line")
        if not hasattr(obj, 'ClampWidth'):
            obj.addProperty("App::PropertyLength", "ClampWidth", grp,
                            "Clamp footprint width (across-slope) -- must "
                            "be less than PanelWidth")
        if not hasattr(obj, 'ClampLength'):
            obj.addProperty("App::PropertyLength", "ClampLength", grp,
                            "Clamp footprint length (up-slope)")
        if not hasattr(obj, 'ClampThickness'):
            obj.addProperty("App::PropertyLength", "ClampThickness", grp,
                            "Clamp thickness")
        if not hasattr(obj, 'FinHeight'):
            obj.addProperty("App::PropertyLength", "FinHeight", grp,
                            "Fin height above the clamp")
        if not hasattr(obj, 'FinBaseWidth'):
            obj.addProperty("App::PropertyLength", "FinBaseWidth", grp,
                            "Fin base footprint, up-slope direction")
        if not hasattr(obj, 'FinThickness'):
            obj.addProperty("App::PropertyLength", "FinThickness", grp,
                            "Fin thickness, across-slope direction")
        if not hasattr(obj, 'GeneratorVersion'):
            obj.addProperty("App::PropertyString", "GeneratorVersion", grp,
                            "Generator version (read-only)")
            obj.setEditorMode("GeneratorVersion", 1)

    @staticmethod
    def set_defaults(obj, params=None):
        p = params or {}
        # PanelWidth/SeamWidth/SeamHeight import standing_seam_geometry's
        # DEFAULT_* constants (not a local copy) so a guard lands on a real
        # rib out of the box and stays that way if those defaults change.
        obj.PanelWidth       = p.get('panel_width',        DEFAULT_PANEL_WIDTH)
        obj.SeamWidth        = p.get('seam_width',         DEFAULT_SEAM_WIDTH)
        obj.SeamHeight       = p.get('seam_height',        DEFAULT_SEAM_HEIGHT)
        obj.SeamStride       = p.get('seam_stride',        3)
        obj.NumRows          = p.get('num_rows',           2)
        obj.FirstRowOffset   = p.get('first_row_offset',   3.0)
        obj.RowSpacing       = p.get('row_spacing',        4.0)
        obj.EdgeMargin       = p.get('edge_margin',        3.0)
        obj.VMargin          = p.get('v_margin',           2.0)
        obj.ClampWidth       = p.get('clamp_width',        1.0)
        obj.ClampLength      = p.get('clamp_length',       1.2)
        obj.ClampThickness   = p.get('clamp_thickness',    0.15)
        obj.FinHeight        = p.get('fin_height',         1.0)
        obj.FinBaseWidth     = p.get('fin_base_width',     0.8)
        obj.FinThickness     = p.get('fin_thickness',      0.6)
        obj.GeneratorVersion = VERSION

    def execute(self, obj):
        if not obj.Sources:
            return

        params = {
            'panel_width':       float(obj.PanelWidth),
            'seam_width':        float(obj.SeamWidth),
            'seam_height':       float(obj.SeamHeight),
            'seam_stride':       int(obj.SeamStride),
            'num_rows':          int(obj.NumRows),
            'first_row_offset':  float(obj.FirstRowOffset),
            'row_spacing':       float(obj.RowSpacing),
            'edge_margin':       float(obj.EdgeMargin),
            'v_margin':          float(obj.VMargin),
            'clamp_width':       float(obj.ClampWidth),
            'clamp_length':      float(obj.ClampLength),
            'clamp_thickness':   float(obj.ClampThickness),
            'fin_height':        float(obj.FinHeight),
            'fin_base_width':    float(obj.FinBaseWidth),
            'fin_thickness':     float(obj.FinThickness),
        }

        valid, errors = validate_parameters(
            params['clamp_width'], params['clamp_length'], params['clamp_thickness'],
            params['fin_height'], params['fin_base_width'], params['fin_thickness'],
            params['panel_width'])
        if not valid:
            App.Console.PrintError(
                f"StandingSeamSnowGuardGenerator: invalid parameters: {errors}\n")
            return

        valid, errors = validate_margins_cover_footprint(
            params['edge_margin'], params['v_margin'],
            params['clamp_width'], params['clamp_length'])
        if not valid:
            App.Console.PrintError(
                f"StandingSeamSnowGuardGenerator: invalid margins: {errors}\n")
            return

        all_guards = []
        for face, link_obj, sub_name in resolve_sources_faces(obj.Sources, "StandingSeamSnowGuardGenerator"):
            try:
                all_guards.extend(_generate_seam_guards(face, params))
            except Exception as e:
                App.Console.PrintError(
                    f"  {link_obj.Label}.{sub_name}: {e}\n")

        if not all_guards:
            App.Console.PrintWarning(
                "StandingSeamSnowGuardGenerator: no guards generated\n")
            return

        obj.Shape = Part.Compound(all_guards)

    def onDocumentRestored(self, obj):
        """Backfill any properties added since this object was saved --
        _setup_properties' hasattr guards make it safe to call again on an
        object that already has some/all of these properties."""
        self._setup_properties(obj)

    def dumps(self):
        return {"Type": self.Type}

    def loads(self, state):
        if state:
            self.Type = state.get("Type", "StandingSeamSnowGuardGenerator")

    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)


class StandingSeamSnowGuardViewProxy:
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
