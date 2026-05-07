"""
BeadBoardProxy — FeaturePython proxy for parametric bead board trim.

Change any property in the panel and the bead board regenerates automatically.
Face references stored as PropertyLinkSubList so they survive save/reload.

Bead board: vertical groove/gap pattern extruded proud of the wall face.
Each bead is a narrow gap flanked by flush boards, giving vertical shadow lines.

This module must be importable by FreeCAD (installed alongside the macro).
"""

import FreeCAD as App
import Part
import math
import sys
from pathlib import Path

VERSION = "2.0.0"
GENERATOR_NAME = "bead_board_generator"

_here = Path(__file__).parent
for p in (str(_here), str(_here / '_lib')):
    if p not in sys.path:
        sys.path.insert(0, p)


# =============================================================================
# Geometry helpers
# =============================================================================

def _face_wires(face):
    wires = face.Wires
    if not wires:
        raise ValueError("Face has no wires!")
    outer = max(wires, key=lambda w: abs(Part.Face(w).Area))
    holes = [w for w in wires if w is not outer]
    if not outer.isClosed():
        raise ValueError("Outer wire is not closed!")
    return outer, holes


def _face_normal(face):
    ur, vr = face.ParameterRange[:2], face.ParameterRange[2:]
    return face.normalAt((ur[0] + ur[1]) / 2, (vr[0] + vr[1]) / 2)


def _detect_orientation(bbox):
    xe = bbox.XMax - bbox.XMin
    ye = bbox.YMax - bbox.YMin
    ze = bbox.ZMax - bbox.ZMin
    tol = 0.1
    if xe < tol:
        return 'z', 'y', 'x'
    if ye < tol:
        return 'z', 'x', 'y'
    if ze < tol:
        return 'y', 'x', 'z'
    if ze >= ye and ze >= xe:
        return ('z', 'x', 'y') if xe > ye else ('z', 'y', 'x')
    return 'y', 'x', 'z'


def _make_gap(gap_start, gap_end, v_min, v_max, depth, horiz_axis, vert_axis, bbox, normal):
    """Extrude a rectangular gap outward from the wall face."""
    if vert_axis == 'z':
        if horiz_axis == 'x':
            by = bbox.YMin
            off = depth if normal.y > 0 else -depth
            w = Part.makePolygon([
                App.Vector(gap_start, by, v_min), App.Vector(gap_end, by, v_min),
                App.Vector(gap_end, by, v_max), App.Vector(gap_start, by, v_max),
                App.Vector(gap_start, by, v_min),
            ])
            return Part.Face(w).extrude(App.Vector(0, off, 0))
        else:
            bx = bbox.XMin
            off = depth if normal.x > 0 else -depth
            w = Part.makePolygon([
                App.Vector(bx, gap_start, v_min), App.Vector(bx, gap_end, v_min),
                App.Vector(bx, gap_end, v_max), App.Vector(bx, gap_start, v_max),
                App.Vector(bx, gap_start, v_min),
            ])
            return Part.Face(w).extrude(App.Vector(off, 0, 0))
    else:  # vert_axis == 'y'
        off = depth if normal.z > 0 else -depth
        w = Part.makePolygon([
            App.Vector(gap_start, v_min, 0), App.Vector(gap_end, v_min, 0),
            App.Vector(gap_end, v_max, 0), App.Vector(gap_start, v_max, 0),
            App.Vector(gap_start, v_min, 0),
        ])
        return Part.Face(w).extrude(App.Vector(0, 0, off))


def generate_bead_board_skin(face, bead_spacing=101.6, bead_depth=0.20, bead_gap=0.20):
    """
    Generate bead board trim for one face.
    Returns additive skin shape (gap solids to be merged with the wall, or used as overlay).

    bead_spacing: distance between bead centers (mm)
    bead_depth:   extrusion depth of gap above face (mm)
    bead_gap:     width of each gap (mm)
    """
    outer_wire, hole_wires = _face_wires(face)
    bbox = face.BoundBox
    vert_axis, horiz_axis, _ = _detect_orientation(bbox)
    normal = _face_normal(face)

    if horiz_axis == 'x':
        h_min, h_max = bbox.XMin, bbox.XMax
    else:
        h_min, h_max = bbox.YMin, bbox.YMax

    if vert_axis == 'z':
        v_min = bbox.ZMin - 0.1
        v_max = bbox.ZMax + 0.1
    else:
        v_min = bbox.YMin - 0.1
        v_max = bbox.YMax + 0.1

    half_gap = bead_gap / 2
    num_beads = int(math.ceil((h_max - h_min) / bead_spacing))
    bead_centers = [h_min + i * bead_spacing for i in range(num_beads)
                    if h_min + i * bead_spacing < h_max]

    gaps = []
    for i, center in enumerate(bead_centers):
        try:
            g = _make_gap(center - half_gap, center + half_gap,
                          v_min, v_max, bead_depth,
                          horiz_axis, vert_axis, bbox, normal)
            gaps.append(g)
        except Exception as e:
            App.Console.PrintWarning(f"  Gap {i}: {e}\n")

    if not gaps:
        raise RuntimeError("No gaps created!")

    fused = gaps[0] if len(gaps) == 1 else gaps[0].fuse(gaps[1:])

    # Trim to face boundary
    try:
        clip_out = face.extrude(normal * (bead_depth + 1.0))
        clip_in  = face.extrude(normal * -1.0)
        trimmed  = fused.common(clip_out.fuse(clip_in))
        if trimmed.Volume > 0.001:
            fused = trimmed
    except Exception as e:
        App.Console.PrintWarning(f"  Trim failed: {e}\n")

    # Cut holes
    for i, hw in enumerate(hole_wires):
        try:
            hf = Part.Face(hw)
            hv = hf.extrude(normal * (bead_depth + 1.0)).fuse(
                 hf.extrude(normal * -1.0))
            fused = fused.cut(hv)
        except Exception as e:
            App.Console.PrintWarning(f"  Hole {i}: {e}\n")

    return fused


# =============================================================================
# FeaturePython proxy
# =============================================================================

class BeadBoardProxy:
    """Parametric bead board trim. Change a property → shape updates."""

    Type = "BeadBoard"

    def __init__(self, obj):
        obj.Proxy = self
        self._setup_properties(obj)

    @staticmethod
    def _setup_properties(obj):
        grp = "BeadBoard"
        if not hasattr(obj, 'Sources'):
            obj.addProperty(
                "App::PropertyLinkSubList", "Sources", grp,
                "Wall faces to apply bead board trim to")
        if not hasattr(obj, 'BeadSpacing'):
            obj.addProperty("App::PropertyLength", "BeadSpacing", grp,
                            "Center-to-center spacing between beads (mm)")
        if not hasattr(obj, 'BeadDepth'):
            obj.addProperty("App::PropertyLength", "BeadDepth", grp,
                            "Depth each gap is extruded above the face (mm)")
        if not hasattr(obj, 'BeadGap'):
            obj.addProperty("App::PropertyLength", "BeadGap", grp,
                            "Width of each gap/groove (mm)")
        if not hasattr(obj, 'GeneratorVersion'):
            obj.addProperty("App::PropertyString", "GeneratorVersion", grp,
                            "Generator version (read-only)")
            obj.setEditorMode("GeneratorVersion", 1)

    @staticmethod
    def set_defaults(obj, params=None):
        p = params or {}
        obj.BeadSpacing      = p.get('bead_spacing', 101.6)
        obj.BeadDepth        = p.get('bead_depth',   0.20)
        obj.BeadGap          = p.get('bead_gap',     0.20)
        obj.GeneratorVersion = VERSION

    def execute(self, obj):
        if not obj.Sources:
            return

        spacing = float(obj.BeadSpacing)
        depth   = float(obj.BeadDepth)
        gap     = float(obj.BeadGap)

        skins = []
        for link_obj, sub_names in obj.Sources:
            if not hasattr(link_obj, 'Shape'):
                continue
            for sub_name in sub_names:
                if not sub_name.startswith('Face'):
                    continue
                try:
                    face = link_obj.Shape.getElement(sub_name)
                    skin = generate_bead_board_skin(face, spacing, depth, gap)
                    skins.append(skin)
                    App.Console.PrintMessage(f"  ✓ {link_obj.Label}/{sub_name}\n")
                except Exception as e:
                    App.Console.PrintError(
                        f"BeadBoardProxy: {link_obj.Label}/{sub_name}: {e}\n")

        if not skins:
            return
        obj.Shape = skins[0] if len(skins) == 1 else Part.Compound(skins)

    def dumps(self):
        return {"Type": self.Type}

    def loads(self, state):
        if state:
            self.Type = state.get("Type", "BeadBoard")

    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)


class BeadBoardViewProxy:
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
