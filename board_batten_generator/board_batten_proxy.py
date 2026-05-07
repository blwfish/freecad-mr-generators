"""
BoardBattenProxy — FeaturePython proxy for parametric board-and-batten siding.

Change any property in the panel and the siding regenerates automatically.
Face references stored as PropertyLinkSubList so they survive save/reload.

This module must be importable by FreeCAD (installed alongside the macro).
"""

import FreeCAD as App
import Part
import math
import sys
from pathlib import Path

VERSION = "2.0.0"
GENERATOR_NAME = "board_batten_generator"

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


def _make_rect_solid(h_start, h_end, v_min, v_max, thickness, offset_dir,
                     horiz_axis, vert_axis, bbox, normal):
    """Extrude a rectangular face along the wall normal."""
    if vert_axis == 'z':
        if horiz_axis == 'x':
            by = bbox.YMin
            off = thickness if normal.y > 0 else -thickness
            w = Part.makePolygon([
                App.Vector(h_start, by, v_min), App.Vector(h_end, by, v_min),
                App.Vector(h_end, by, v_max), App.Vector(h_start, by, v_max),
                App.Vector(h_start, by, v_min),
            ])
            return Part.Face(w).extrude(App.Vector(0, off, 0))
        else:
            bx = bbox.XMin
            off = thickness if normal.x > 0 else -thickness
            w = Part.makePolygon([
                App.Vector(bx, h_start, v_min), App.Vector(bx, h_end, v_min),
                App.Vector(bx, h_end, v_max), App.Vector(bx, h_start, v_max),
                App.Vector(bx, h_start, v_min),
            ])
            return Part.Face(w).extrude(App.Vector(off, 0, 0))
    else:  # vert_axis == 'y'
        off = thickness if normal.z > 0 else -thickness
        w = Part.makePolygon([
            App.Vector(h_start, v_min, 0), App.Vector(h_end, v_min, 0),
            App.Vector(h_end, v_max, 0), App.Vector(h_start, v_max, 0),
            App.Vector(h_start, v_min, 0),
        ])
        return Part.Face(w).extrude(App.Vector(0, 0, off))


def generate_board_batten_skin(face, board_width=7.0, batten_width=0.6,
                               board_thickness=0.2, batten_projection=0.12):
    """Generate board-and-batten siding for one face. Returns additive skin shape."""
    outer_wire, hole_wires = _face_wires(face)
    bbox = face.BoundBox
    vert_axis, horiz_axis, _ = _detect_orientation(bbox)
    normal = _face_normal(face)
    total_thick = board_thickness + batten_projection

    if horiz_axis == 'x':
        h_min = bbox.XMin - 0.1
        h_max = bbox.XMax + 0.1
    else:
        h_min = bbox.YMin - 0.1
        h_max = bbox.YMax + 0.1

    if vert_axis == 'z':
        v_min = bbox.ZMin - 0.1
        v_max = bbox.ZMax + 0.1
    else:
        v_min = bbox.YMin - 0.1
        v_max = bbox.YMax + 0.1

    num_boards = int(math.ceil((h_max - h_min) / board_width))

    # Boards
    boards = []
    for i in range(num_boards):
        h_s = h_min + i * board_width
        h_e = h_s + board_width
        try:
            boards.append(_make_rect_solid(h_s, h_e, v_min, v_max,
                                           board_thickness, None,
                                           horiz_axis, vert_axis, bbox, normal))
        except Exception as e:
            App.Console.PrintWarning(f"  Board {i}: {e}\n")

    if not boards:
        raise RuntimeError("No boards created!")

    # Battens at seams
    battens = []
    for i in range(num_boards - 1):
        h_seam = h_min + (i + 1) * board_width
        h_s = h_seam - batten_width / 2
        h_e = h_seam + batten_width / 2
        try:
            battens.append(_make_rect_solid(h_s, h_e, v_min, v_max,
                                            total_thick, None,
                                            horiz_axis, vert_axis, bbox, normal))
        except Exception as e:
            App.Console.PrintWarning(f"  Batten {i}: {e}\n")

    # Combine
    fused = boards[0] if len(boards) == 1 else boards[0].fuse(boards[1:])
    if battens:
        fused_b = battens[0] if len(battens) == 1 else battens[0].fuse(battens[1:])
        fused = fused.fuse(fused_b)

    # Trim to face boundary (handles gable/diagonal edges)
    try:
        clip_out = face.extrude(normal * (total_thick + 1.0))
        clip_in  = face.extrude(normal * -(board_thickness + 1.0))
        fused = fused.common(clip_out.fuse(clip_in))
    except Exception as e:
        App.Console.PrintWarning(f"  Trim failed: {e}\n")

    # Cut holes (windows/doors)
    for i, hw in enumerate(hole_wires):
        try:
            hf = Part.Face(hw)
            hv = hf.extrude(normal * (total_thick + 1.0)).fuse(
                 hf.extrude(normal * -(board_thickness + 1.0)))
            fused = fused.cut(hv)
        except Exception as e:
            App.Console.PrintWarning(f"  Hole {i}: {e}\n")

    return fused


# =============================================================================
# FeaturePython proxy
# =============================================================================

class BoardBattenProxy:
    """Parametric board-and-batten siding. Change a property → shape updates."""

    Type = "BoardBatten"

    def __init__(self, obj):
        obj.Proxy = self
        self._setup_properties(obj)

    @staticmethod
    def _setup_properties(obj):
        grp = "BoardBatten"
        if not hasattr(obj, 'Sources'):
            obj.addProperty(
                "App::PropertyLinkSubList", "Sources", grp,
                "Wall faces to apply board-and-batten siding to")
        if not hasattr(obj, 'BoardWidth'):
            obj.addProperty("App::PropertyLength", "BoardWidth", grp,
                            "Width of each vertical board (mm)")
        if not hasattr(obj, 'BattenWidth'):
            obj.addProperty("App::PropertyLength", "BattenWidth", grp,
                            "Width of each batten strip (mm)")
        if not hasattr(obj, 'BoardThickness'):
            obj.addProperty("App::PropertyLength", "BoardThickness", grp,
                            "Board material thickness (mm)")
        if not hasattr(obj, 'BattenProjection'):
            obj.addProperty("App::PropertyLength", "BattenProjection", grp,
                            "How far battens project above the boards (mm)")
        if not hasattr(obj, 'GeneratorVersion'):
            obj.addProperty("App::PropertyString", "GeneratorVersion", grp,
                            "Generator version (read-only)")
            obj.setEditorMode("GeneratorVersion", 1)

    @staticmethod
    def set_defaults(obj, params=None):
        p = params or {}
        obj.BoardWidth       = p.get('board_width',       7.0)
        obj.BattenWidth      = p.get('batten_width',      0.6)
        obj.BoardThickness   = p.get('board_thickness',   0.2)
        obj.BattenProjection = p.get('batten_projection', 0.12)
        obj.GeneratorVersion = VERSION

    def execute(self, obj):
        if not obj.Sources:
            return

        bw  = float(obj.BoardWidth)
        baw = float(obj.BattenWidth)
        bt  = float(obj.BoardThickness)
        bp  = float(obj.BattenProjection)

        skins = []
        for link_obj, sub_names in obj.Sources:
            if not hasattr(link_obj, 'Shape'):
                continue
            for sub_name in sub_names:
                if not sub_name.startswith('Face'):
                    continue
                try:
                    face = link_obj.Shape.getElement(sub_name)
                    skin = generate_board_batten_skin(face, bw, baw, bt, bp)
                    skins.append(skin)
                    App.Console.PrintMessage(f"  ✓ {link_obj.Label}/{sub_name}\n")
                except Exception as e:
                    App.Console.PrintError(
                        f"BoardBattenProxy: {link_obj.Label}/{sub_name}: {e}\n")

        if not skins:
            return
        obj.Shape = skins[0] if len(skins) == 1 else Part.Compound(skins)

    def dumps(self):
        return {"Type": self.Type}

    def loads(self, state):
        if state:
            self.Type = state.get("Type", "BoardBatten")

    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)


class BoardBattenViewProxy:
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
