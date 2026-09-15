"""
Snow Guard FeaturePython proxy — parametric snow guard (ice/snow stop)
generator for FreeCAD.

Places a staggered grid of pad-and-fin snow guards across a roof face.
Unlike the coursed-tile generators in this repo (slate, clapboard), snow
guards are a SPARSE placement, not a tiling fill pattern -- each guard is
a small discrete solid with no boolean clip against the face boundary.

Slate roofs only for now; shingle and standing-seam attachment styles are
deferred to future generators.

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

from snow_guard_geometry import (
    validate_parameters,
    validate_margins_cover_footprint,
    calculate_grid_positions,
)
from freecad_utils import resolve_sources_faces, get_roof_face_coordinate_system  # noqa: E402
from snow_guard_solid_geometry import calculate_fin_position


# ---------------------------------------------------------------------------
# FreeCAD geometry helpers (shared pattern with slate_proxy.py)
# ---------------------------------------------------------------------------

def _sv(vec, scale):
    """Scale a FreeCAD Vector."""
    return App.Vector(vec.x * scale, vec.y * scale, vec.z * scale)


def _get_face_coordinate_system(face):
    """
    Extract U/V/normal coordinate system from a roof face.
    Returns (origin, u_vec, v_vec, normal, u_length, v_length).

    Full-review finding freecad-mr-generators-20260915-e612#11: thin
    wrapper around shared/freecad_utils.get_roof_face_coordinate_system,
    the single source of truth for this logic -- previously an
    independent copy-pasted-near-verbatim implementation here and in four
    sibling roof-facing proxies, with no shared function and no parity
    test.
    """
    return get_roof_face_coordinate_system(face)


# ---------------------------------------------------------------------------
# Guard solid
# ---------------------------------------------------------------------------

def _build_guard_solid(pad_width, pad_length, pad_thickness,
                        fin_height, fin_base_width, fin_thickness):
    """Build one snow guard: a flat mounting pad with a triangular-prism
    fin fused on top, centered on the pad. Local space: x=u (across-slope,
    pad_width), y=v (up-slope, pad_length), z=normal (pad_thickness, then
    fin rises further in +z). The pad's origin corner is (0,0,0).

    Deliberately a simple primitive shape (box + extruded triangle, no
    lofts/sweeps) -- lower OCCT risk than a sculpted profile, per this
    generator's design decision.

    The fin-centering math (fin_x0/fin_y0) comes from
    shared/snow_guard_solid_geometry.calculate_fin_position, shared with
    standing_seam_snow_guard_proxy.py's near-identical
    _build_guard_solid so the two constructions can't silently diverge
    (full-review finding #20, 2026-08-08).
    """
    pad = Part.makeBox(pad_width, pad_length, pad_thickness)

    fin_x0, fin_y0 = calculate_fin_position(
        pad_width, pad_length, fin_base_width, fin_thickness)
    p0 = App.Vector(0, fin_y0, pad_thickness)
    p1 = App.Vector(0, fin_y0 + fin_base_width, pad_thickness)
    p2 = App.Vector(0, fin_y0 + fin_base_width / 2.0, pad_thickness + fin_height)
    profile = Part.Wire([
        Part.LineSegment(p0, p1).toShape(),
        Part.LineSegment(p1, p2).toShape(),
        Part.LineSegment(p2, p0).toShape(),
    ])
    fin = Part.Face(profile).extrude(App.Vector(fin_thickness, 0, 0))

    fin.translate(App.Vector(fin_x0, 0, 0))

    return pad.fuse(fin)


# ---------------------------------------------------------------------------
# Grid generation
# ---------------------------------------------------------------------------

def _generate_guards(face, params):
    """Generate placed snow guard solids for one roof face.

    Assumes a roughly rectangular face, same simplification the other
    roof-surface generators in this repo (slate, clapboard) already make
    via their own u_length/v_length bounding projection.
    """
    origin, u_vec, v_vec, normal, u_length, v_length = \
        _get_face_coordinate_system(face)

    positions = calculate_grid_positions(
        u_length, v_length,
        params['num_rows'], params['first_row_offset'], params['row_spacing'],
        params['guards_per_row'], params['edge_margin'], params['v_margin'],
        params['stagger_rows'])

    base_guard = _build_guard_solid(
        params['pad_width'], params['pad_length'], params['pad_thickness'],
        params['fin_height'], params['fin_base_width'], params['fin_thickness'])

    rotation_matrix = App.Matrix(
        u_vec.x, v_vec.x, normal.x, 0,
        u_vec.y, v_vec.y, normal.y, 0,
        u_vec.z, v_vec.z, normal.z, 0,
        0, 0, 0, 1,
    )
    rotation = App.Rotation(rotation_matrix)

    half_pad_u = params['pad_width'] / 2.0
    half_pad_v = params['pad_length'] / 2.0

    shapes = []
    for row_index, u, v in positions:
        corner_pos = origin + _sv(u_vec, u - half_pad_u) + _sv(v_vec, v - half_pad_v)
        guard = base_guard.copy()
        guard.Placement = App.Placement(corner_pos, rotation)
        shapes.append(guard)

    return shapes


# ---------------------------------------------------------------------------
# FeaturePython proxy
# ---------------------------------------------------------------------------

class SnowGuardProxy:
    """Parametric snow guard grid. Change a property → guards update."""

    Type = "SnowGuardGenerator"

    def __init__(self, obj):
        obj.Proxy = self
        self._setup_properties(obj)

    @staticmethod
    def _setup_properties(obj):
        grp = "SnowGuard"
        if not hasattr(obj, 'Sources'):
            obj.addProperty("App::PropertyLinkSubList", "Sources", grp,
                            "Roof faces to place snow guards on")
        if not hasattr(obj, 'NumRows'):
            obj.addProperty("App::PropertyInteger", "NumRows", grp,
                            "Number of guard rows, up-slope from the eave")
        if not hasattr(obj, 'GuardsPerRow'):
            obj.addProperty("App::PropertyInteger", "GuardsPerRow", grp,
                            "Number of guards across each row")
        if not hasattr(obj, 'FirstRowOffset'):
            obj.addProperty("App::PropertyLength", "FirstRowOffset", grp,
                            "Distance from the eave to the first row")
        if not hasattr(obj, 'RowSpacing'):
            obj.addProperty("App::PropertyLength", "RowSpacing", grp,
                            "Up-slope spacing between rows")
        if not hasattr(obj, 'EdgeMargin'):
            obj.addProperty("App::PropertyLength", "EdgeMargin", grp,
                            "Minimum clearance from the rake edges")
        if not hasattr(obj, 'VMargin'):
            obj.addProperty("App::PropertyLength", "VMargin", grp,
                            "Minimum clearance from the eave and ridge/hip line")
        if not hasattr(obj, 'StaggerRows'):
            obj.addProperty("App::PropertyBool", "StaggerRows", grp,
                            "Offset alternating rows by half the guard "
                            "spacing (zigzag pattern)")
        if not hasattr(obj, 'PadWidth'):
            obj.addProperty("App::PropertyLength", "PadWidth", grp,
                            "Mounting pad width (across-slope)")
        if not hasattr(obj, 'PadLength'):
            obj.addProperty("App::PropertyLength", "PadLength", grp,
                            "Mounting pad length (up-slope)")
        if not hasattr(obj, 'PadThickness'):
            obj.addProperty("App::PropertyLength", "PadThickness", grp,
                            "Mounting pad thickness")
        if not hasattr(obj, 'FinHeight'):
            obj.addProperty("App::PropertyLength", "FinHeight", grp,
                            "Fin height above the pad")
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
        obj.NumRows         = p.get('num_rows',          2)
        obj.GuardsPerRow    = p.get('guards_per_row',     6)
        obj.FirstRowOffset  = p.get('first_row_offset',   3.0)
        obj.RowSpacing      = p.get('row_spacing',        4.0)
        obj.EdgeMargin      = p.get('edge_margin',        3.0)
        obj.VMargin         = p.get('v_margin',           2.0)
        obj.StaggerRows     = p.get('stagger_rows',       True)
        obj.PadWidth        = p.get('pad_width',          1.2)
        obj.PadLength       = p.get('pad_length',         1.2)
        obj.PadThickness    = p.get('pad_thickness',      0.15)
        obj.FinHeight       = p.get('fin_height',         1.0)
        obj.FinBaseWidth    = p.get('fin_base_width',     0.8)
        obj.FinThickness    = p.get('fin_thickness',      0.6)
        obj.GeneratorVersion = VERSION

    def execute(self, obj):
        if not obj.Sources:
            return

        params = {
            'num_rows':         int(obj.NumRows),
            'guards_per_row':   int(obj.GuardsPerRow),
            'first_row_offset': float(obj.FirstRowOffset),
            'row_spacing':      float(obj.RowSpacing),
            'edge_margin':      float(obj.EdgeMargin),
            'v_margin':         float(obj.VMargin),
            'stagger_rows':     bool(obj.StaggerRows),
            'pad_width':        float(obj.PadWidth),
            'pad_length':       float(obj.PadLength),
            'pad_thickness':    float(obj.PadThickness),
            'fin_height':       float(obj.FinHeight),
            'fin_base_width':   float(obj.FinBaseWidth),
            'fin_thickness':    float(obj.FinThickness),
        }

        valid, errors = validate_parameters(
            params['pad_width'], params['pad_length'], params['pad_thickness'],
            params['fin_height'], params['fin_base_width'], params['fin_thickness'])
        if not valid:
            App.Console.PrintError(f"SnowGuardGenerator: invalid parameters: {errors}\n")
            return

        valid, errors = validate_margins_cover_footprint(
            params['edge_margin'], params['v_margin'],
            params['pad_width'], params['pad_length'])
        if not valid:
            App.Console.PrintError(f"SnowGuardGenerator: invalid margins: {errors}\n")
            return

        all_guards = []
        for face, link_obj, sub_name in resolve_sources_faces(obj.Sources, "SnowGuardGenerator"):
            try:
                all_guards.extend(_generate_guards(face, params))
            except Exception as e:
                App.Console.PrintError(
                    f"  {link_obj.Label}.{sub_name}: {e}\n")

        if not all_guards:
            App.Console.PrintWarning("SnowGuardGenerator: no guards generated\n")
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
            self.Type = state.get("Type", "SnowGuardGenerator")

    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)


class SnowGuardViewProxy:
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
