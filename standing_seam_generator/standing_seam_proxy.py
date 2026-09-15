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
    is_valid_clip_fragment,
    DEFAULT_PANEL_WIDTH,
    DEFAULT_SEAM_WIDTH,
    DEFAULT_SEAM_HEIGHT,
)
from freecad_utils import resolve_sources_faces, get_roof_face_coordinate_system  # noqa: E402


# ---------------------------------------------------------------------------
# FreeCAD geometry helpers
# ---------------------------------------------------------------------------

def _sv(vec, scale):
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


def _build_clip_volumes(face):
    depth = 100.0
    n = face.normalAt(0.5, 0.5)
    if n.Length > 1e-9:
        n.normalize()
    return [face.extrude(n * depth), face.extrude(n * (-depth))]


def _clip_shape(shape, clip_volumes):
    """Clip *shape* against dual clip volumes. Returns clipped solid or None.

    Survival is judged against the shape's own pre-clip volume (see
    is_valid_clip_fragment) rather than a fixed absolute threshold. A fixed
    threshold doesn't scale with panel size -- shared/roof_geometry.py's
    own docstring documents a real production incident where it let 0.02
    mm^3 slivers survive as stray fragments (~1% of a 1.8mm^3 tile) on a
    hip roof. slate_proxy.py and slate_seam_proxy.py were both updated to
    the fraction-based fix; this file previously wasn't (full-review
    finding #10, 2026-08-08).
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
        obj.PanelWidth      = p.get('panel_width',      DEFAULT_PANEL_WIDTH)
        obj.SeamHeight      = p.get('seam_height',      DEFAULT_SEAM_HEIGHT)
        obj.SeamWidth       = p.get('seam_width',       DEFAULT_SEAM_WIDTH)
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
