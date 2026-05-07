"""
ClapboardProxy — FeaturePython proxy for parametric clapboard siding.

Change any property in the panel and the siding regenerates automatically.
Face references stored as PropertyLinkSubList so they survive save/reload.

This module must be importable by FreeCAD (installed alongside the macro).
"""

import FreeCAD as App
import Part
import math
import sys
from pathlib import Path

VERSION = "7.0.0"
GENERATOR_NAME = "clapboard_generator"
CLAPBOARD_TRIM_OFFSET = 0.05  # mm — clapboard bottom inboard of trim edge


# =============================================================================
# Geometry helpers (formerly inline in clapboard_generator.FCMacro)
# =============================================================================

def _check_for_degenerate_edges(wire):
    return [(i, e.Length) for i, e in enumerate(wire.Edges) if e.Length < 0.001]


def _check_for_duplicate_edges(wire):
    edges = wire.Edges
    dupes = []
    tol = 0.001
    for i in range(len(edges)):
        for j in range(i + 1, len(edges)):
            e1, e2 = edges[i], edges[j]
            s1 = e1.valueAt(e1.FirstParameter)
            t1 = e1.valueAt(e1.LastParameter)
            s2 = e2.valueAt(e2.FirstParameter)
            t2 = e2.valueAt(e2.LastParameter)
            if ((s1.distanceToPoint(s2) < tol and t1.distanceToPoint(t2) < tol) or
                    (s1.distanceToPoint(t2) < tol and t1.distanceToPoint(s2) < tol)):
                dupes.append((i, j))
    return dupes


def _validate_wire(wire, name="Wire"):
    degen = _check_for_degenerate_edges(wire)
    if degen:
        msgs = [f"  Edge {i}: length={l:.6f}mm" for i, l in degen]
        raise ValueError(f"{name} has degenerate edge(s):\n" + "\n".join(msgs))
    dupes = _check_for_duplicate_edges(wire)
    if dupes:
        msgs = [f"  Edges {i} and {j}" for i, j in dupes]
        raise ValueError(f"{name} has duplicate edge(s):\n" + "\n".join(msgs))


def _get_face_wires(face):
    wires = face.Wires
    if not wires:
        raise ValueError("Face has no wires!")
    outer = max(wires, key=lambda w: abs(Part.Face(w).Area))
    holes = [w for w in wires if w is not outer]
    if not outer.isClosed():
        raise ValueError("Outer wire is not closed!")
    _validate_wire(outer, "Outer wire")
    for i, hw in enumerate(holes):
        if not hw.isClosed():
            raise ValueError(f"Hole wire {i} not closed!")
        _validate_wire(hw, f"Hole wire {i}")
    return outer, holes


def _face_normal(face):
    ur, vr = face.ParameterRange[:2], face.ParameterRange[2:]
    return face.normalAt((ur[0] + ur[1]) / 2, (vr[0] + vr[1]) / 2)


def _detect_orientation(bbox):
    """Return (vertical_axis, horizontal_axis, plane_normal) strings."""
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


def _snap_to_grid(bbox, height, vert_axis):
    vmin = bbox.ZMin if vert_axis == 'z' else bbox.YMin
    return round(vmin / height) * height


def _find_gable_edges(wire, vert_axis, angle_tol=5.0):
    vd = App.Vector(0, 0, 1) if vert_axis == 'z' else App.Vector(0, 1, 0)
    gable = []
    for edge in wire.Edges:
        if edge.Length < 0.01:
            continue
        try:
            d = edge.tangentAt(edge.FirstParameter)
            d.normalize()
            angle = math.degrees(math.acos(min(1.0, abs(d.dot(vd)))))
            if angle > angle_tol:
                gable.append(edge)
        except Exception:
            pass
    return gable


def _find_bay_boundaries(outer_wire, horiz_axis, vert_axis, gap_threshold=0.0005):
    vd = App.Vector(0, 0, 1) if vert_axis == 'z' else App.Vector(0, 1, 0)
    angle_tol = 5.0
    vert_edges = []
    for edge in outer_wire.Edges:
        if edge.Length < 0.01:
            continue
        try:
            d = edge.tangentAt(edge.FirstParameter)
            d.normalize()
            angle = math.degrees(math.acos(min(1.0, abs(d.dot(vd)))))
            if angle < angle_tol:
                start = edge.valueAt(edge.FirstParameter)
                h_pos = start.x if horiz_axis == 'x' else start.y
                vert_edges.append(h_pos)
        except Exception:
            continue
    vert_edges.sort()
    return [
        (vert_edges[i] + vert_edges[i + 1]) / 2
        for i in range(len(vert_edges) - 1)
        if vert_edges[i + 1] - vert_edges[i] > gap_threshold
    ]


def _make_course(vert_pos, bbox, height, thickness, vert_axis, horiz_axis, normal,
                 bay_boundaries=None):
    """Build one clapboard course (or segmented pieces at bay boundaries)."""
    actual_thick = thickness - CLAPBOARD_TRIM_OFFSET
    thin = 0.01
    boundaries = sorted(bay_boundaries or [])

    if horiz_axis == 'x':
        h_min_all = bbox.XMin - 0.1
        h_max_all = bbox.XMax + 0.1
    else:
        h_min_all = bbox.YMin - 0.1
        h_max_all = bbox.YMax + 0.1

    segs = []
    prev = h_min_all
    for b in boundaries:
        if b > prev + 0.001:
            segs.append((prev, b))
        prev = b
    if prev < h_max_all - 0.001:
        segs.append((prev, h_max_all))
    if not segs:
        segs = [(h_min_all, h_max_all)]

    pieces = []
    for h_min, h_max in segs:
        if vert_axis == 'z':
            v_bot = vert_pos
            v_top = min(vert_pos + height, bbox.ZMax + 0.1)
            if v_bot >= bbox.ZMax:
                continue
            if horiz_axis == 'x':
                by = bbox.YMin
                to = actual_thick if normal.y > 0 else -actual_thick
                no = thin if normal.y > 0 else -thin
                ow = Part.makePolygon([
                    App.Vector(h_min, by + to, v_bot), App.Vector(h_max, by + to, v_bot),
                    App.Vector(h_max, by + no, v_top), App.Vector(h_min, by + no, v_top),
                    App.Vector(h_min, by + to, v_bot),
                ])
                iw = Part.makePolygon([
                    App.Vector(h_min, by, v_bot), App.Vector(h_max, by, v_bot),
                    App.Vector(h_max, by, v_top), App.Vector(h_min, by, v_top),
                    App.Vector(h_min, by, v_bot),
                ])
            else:
                bx = bbox.XMin
                to = actual_thick if normal.x > 0 else -actual_thick
                no = thin if normal.x > 0 else -thin
                ow = Part.makePolygon([
                    App.Vector(bx + to, h_min, v_bot), App.Vector(bx + to, h_max, v_bot),
                    App.Vector(bx + no, h_max, v_top), App.Vector(bx + no, h_min, v_top),
                    App.Vector(bx + to, h_min, v_bot),
                ])
                iw = Part.makePolygon([
                    App.Vector(bx, h_min, v_bot), App.Vector(bx, h_max, v_bot),
                    App.Vector(bx, h_max, v_top), App.Vector(bx, h_min, v_top),
                    App.Vector(bx, h_min, v_bot),
                ])
        else:  # vert_axis == 'y'
            v_bot = vert_pos
            v_top = min(vert_pos + height, bbox.YMax + 0.1)
            if v_bot >= bbox.YMax:
                continue
            bz = 0
            to = actual_thick if normal.z > 0 else -actual_thick
            no = thin if normal.z > 0 else -thin
            ow = Part.makePolygon([
                App.Vector(h_min, v_bot, bz + to), App.Vector(h_max, v_bot, bz + to),
                App.Vector(h_max, v_top, bz + no), App.Vector(h_min, v_top, bz + no),
                App.Vector(h_min, v_bot, bz + to),
            ])
            iw = Part.makePolygon([
                App.Vector(h_min, v_bot, bz), App.Vector(h_max, v_bot, bz),
                App.Vector(h_max, v_top, bz), App.Vector(h_min, v_top, bz),
                App.Vector(h_min, v_bot, bz),
            ])
        pieces.append(Part.makeLoft([iw, ow], True))

    if not pieces:
        return None
    return pieces[0] if len(pieces) == 1 else pieces[0].fuse(pieces[1:])


def generate_clapboard_skin(face, clapboard_height=0.8, clapboard_thickness=0.2):
    """
    Generate clapboard siding for one face.
    Returns the clapboard skin shape (does not modify source object).
    """
    outer_wire, hole_wires = _get_face_wires(face)
    bbox = face.BoundBox
    vert_axis, horiz_axis, _ = _detect_orientation(bbox)
    normal = _face_normal(face)
    bay_bounds = _find_bay_boundaries(outer_wire, horiz_axis, vert_axis)

    wall_h = (bbox.ZMax - bbox.ZMin) if vert_axis == 'z' else (bbox.YMax - bbox.YMin)
    vert_min = _snap_to_grid(bbox, clapboard_height, vert_axis)
    num_courses = int(math.ceil(wall_h / clapboard_height))

    parts = []
    for i in range(num_courses):
        overlap = 0.01 if i > 0 else 0
        vert_pos = vert_min + i * clapboard_height - overlap
        try:
            cb = _make_course(vert_pos, bbox, clapboard_height, clapboard_thickness,
                              vert_axis, horiz_axis, normal, bay_bounds)
            if cb:
                parts.append(cb)
        except Exception as e:
            App.Console.PrintWarning(f"  Clapboard course {i}: {e}\n")

    if not parts:
        raise RuntimeError("No clapboard courses created!")

    fused = parts[0] if len(parts) == 1 else parts[0].fuse(parts[1:])

    # Gable trimming
    gable_edges = _find_gable_edges(outer_wire, vert_axis)
    if gable_edges:
        try:
            gs_out = face.extrude(normal * clapboard_thickness * 3)
            gs_in = face.extrude(normal * -(clapboard_thickness * 2))
            fused = fused.common(gs_out.fuse(gs_in))
        except Exception as e:
            App.Console.PrintWarning(f"  Gable cut failed: {e}\n")

    # Hole cutouts (windows/doors)
    for i, hw in enumerate(hole_wires):
        try:
            hf = Part.Face(hw)
            fused = fused.cut(
                hf.extrude(normal * clapboard_thickness * 2).fuse(
                    hf.extrude(normal * -(clapboard_thickness * 3))))
        except Exception as e:
            App.Console.PrintWarning(f"  Hole {i}: {e}\n")

    return fused


# =============================================================================
# FeaturePython proxy
# =============================================================================

class ClapboardProxy:
    """Parametric clapboard siding.  Change a property → shape updates."""

    Type = "Clapboard"

    def __init__(self, obj):
        obj.Proxy = self
        self._setup_properties(obj)

    @staticmethod
    def _setup_properties(obj):
        grp = "Clapboard"
        if not hasattr(obj, 'Sources'):
            obj.addProperty(
                "App::PropertyLinkSubList", "Sources", grp,
                "Wall faces to apply clapboard siding to")
        if not hasattr(obj, 'ClapboardHeight'):
            obj.addProperty(
                "App::PropertyLength", "ClapboardHeight", grp,
                "Clapboard reveal height (mm)")
        if not hasattr(obj, 'ClapboardThickness'):
            obj.addProperty(
                "App::PropertyLength", "ClapboardThickness", grp,
                "Clapboard material thickness (mm)")
        if not hasattr(obj, 'GeneratorVersion'):
            obj.addProperty(
                "App::PropertyString", "GeneratorVersion", grp,
                "Generator version (read-only)")
            obj.setEditorMode("GeneratorVersion", 1)

    @staticmethod
    def set_defaults(obj, params=None):
        p = params or {}
        obj.ClapboardHeight = p.get('clapboard_height', 0.8)
        obj.ClapboardThickness = p.get('clapboard_thickness', 0.2)
        obj.GeneratorVersion = VERSION

    def execute(self, obj):
        if not obj.Sources:
            return

        h = float(obj.ClapboardHeight)
        t = float(obj.ClapboardThickness)

        skins = []
        for link_obj, sub_names in obj.Sources:
            if not hasattr(link_obj, 'Shape'):
                continue
            for sub_name in sub_names:
                if not sub_name.startswith('Face'):
                    continue
                try:
                    face = link_obj.Shape.getElement(sub_name)
                    skin = generate_clapboard_skin(face, h, t)
                    skins.append(skin)
                    App.Console.PrintMessage(
                        f"  ✓ {link_obj.Label}/{sub_name}\n")
                except Exception as e:
                    App.Console.PrintError(
                        f"ClapboardProxy: {link_obj.Label}/{sub_name}: {e}\n")

        if not skins:
            return

        obj.Shape = skins[0] if len(skins) == 1 else Part.Compound(skins)

    def dumps(self):
        return {"Type": self.Type}

    def loads(self, state):
        if state:
            self.Type = state.get("Type", "Clapboard")

    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)


class ClapboardViewProxy:
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
