"""
StationSignProxy — FeaturePython proxy for parametric station signs.

Change StationName in the Properties panel and the sign rebuilds automatically,
scaling width and height to fit the new text exactly.

No face selection needed — the sign is fully self-contained.

Layout (looking from above):
    [border_thick][border_gap][text][border_gap][border_thick]

Z layers:
    0              → bg_thickness   : background slab  (2 × MaterialThickness)
    bg_thickness   → border_height  : border frame      (1 × MaterialThickness)
    border_height  → top            : raised text        (1 × MaterialThickness)

This module must be importable by FreeCAD (installed alongside the macro).
"""

import FreeCAD as App
import Part
import sys
from pathlib import Path
from FreeCAD import Vector

VERSION = "2.1.1"
GENERATOR_NAME = "station_sign_generator"

_here = Path(__file__).parent
for p in (str(_here), str(_here / '_lib')):
    if p not in sys.path:
        sys.path.insert(0, p)

from freecad_utils import resolve_font_path, find_first_existing_path  # noqa: E402
from station_sign_geometry import (
    group_wire_bboxes_into_islands,
    calculate_sign_layout,
)  # noqa: E402

# Default font: C&O station font alongside the macro; fall back to empty (system default)
_FONT_CANDIDATES = [
    str(_here / "Station-font-AV-20-219.ttf"),
    str(Path.home() / "Documents" / "FreeCAD-github" / "Station-font-AV-20-219.ttf"),
]
_DEFAULT_FONT = find_first_existing_path(_FONT_CANDIDATES)

# This generator was designed around a specific prototype font that isn't
# free/bundled -- unlike label_generator's system-font fallbacks, "any
# font will do" isn't really true for period-correct C&O lettering, so a
# silent substitution is actively misleading rather than just imprecise.
# Printed once at load (below), and again from execute() the first time
# generation actually needs the font and it's still missing -- covers a
# session where nothing triggered the load-time warning's visibility
# (e.g. loaded before the user was looking at the console). _font_help_
# shown_in_execute then suppresses further repeats: once the user has
# seen it during this session's execute() calls, reprinting it on every
# single recompute is just noise, not reinforcement (full-review finding
# freecad-mr-generators-20260808-a0b9#42).
_font_help_shown_in_execute = False

_FONT_HELP = (
    "StationSignProxy: the C&O prototype font 'Station-font-AV-20-219.ttf' "
    "was not found. This font is NOT included with this generator -- it's "
    "sold by the Chesapeake & Ohio Historical Society (COHS, cohs.org) for "
    "a nominal fee (~$9 as of 2026).\n"
    "  To use the real C&O lettering: buy/download the font from COHS and "
    "place the .ttf file at either of:\n"
    f"      {_FONT_CANDIDATES[0]}\n"
    f"      {_FONT_CANDIDATES[1]}\n"
    "  To use a substitute instead: set the FontPath property on your "
    "StationSign object to any .ttf font file you already have -- the "
    "sign will generate correctly, just without period-correct lettering.\n"
    "  Without either, sign generation may fail or fall back to whatever "
    "system default font FreeCAD finds."
)

if not _DEFAULT_FONT:
    App.Console.PrintWarning(_FONT_HELP + "\n")

# HO-scale text height: 16" prototype → 1:87 → mm
_TEXT_HEIGHT_HO = (16.0 / 87.0) * 25.4   # ≈ 4.67 mm


# =============================================================================
# Text shape helper
# =============================================================================

def _make_text_faces(text, font_path, height):
    """
    Return (faces, bbox) for the given text string at the given height.

    faces: list of Part.Face objects (one per glyph, holes handled by Part.Face)
    bbox:  BoundBox of Part.makeCompound(faces)

    Uses Part.makeWireString — the correct Part-module API.
    Part.makeShapeString was never a real Part function; it only appeared to work
    via a Draft fallback that silently created and discarded document objects.

    *font_path* must already be resolved (see resolve_font_path()) -- this
    function does not re-check existence.
    """
    try:
        wire_lists = Part.makeWireString(text, font_path, height, 0)
    except Exception as exc:
        raise RuntimeError(f"Cannot create text wires for '{text}': {exc}") from exc

    if not wire_lists:
        raise RuntimeError(f"makeWireString returned empty result for '{text}'")

    faces = []
    for char_wires in wire_lists:
        faces.extend(_wires_to_faces(char_wires))

    if not faces:
        raise RuntimeError(f"No valid glyph faces for '{text}' — check font path")

    bbox = Part.makeCompound(faces).BoundBox
    return faces, bbox


def _wires_to_faces(char_wires):
    """
    Convert the wire list for one glyph to one or more Part.Face objects.

    Handles disconnected glyph parts (dot of 'i', 'j', etc.) by using
    bounding-box containment (station_sign_geometry.
    group_wire_bboxes_into_islands, extracted 2026-08-08 -- full-review
    finding #29) to distinguish holes from separate islands.
    """
    if not char_wires:
        return []
    if len(char_wires) == 1:
        try:
            f = Part.Face(char_wires)
            return [f] if not f.isNull() else []
        except Exception:
            return []

    bboxes = [(w.BoundBox.XMin, w.BoundBox.XMax, w.BoundBox.YMin, w.BoundBox.YMax)
              for w in char_wires]
    groups = group_wire_bboxes_into_islands(bboxes)

    faces = []
    for group_indices in groups:
        group = [char_wires[i] for i in group_indices]
        try:
            f = Part.Face(group)
            if not f.isNull():
                faces.append(f)
        except Exception:
            pass

    return faces


# =============================================================================
# Sign geometry builder
# =============================================================================

def generate_sign_shape(station_name, font_path, text_height,
                        mat_thick, border_thick, border_gap):
    """
    Build the fused station sign solid.

    Returns (shape, sign_width, sign_height).

    sign_width  = 2*border_thick + 2*border_gap + measured_text_width
    sign_height = 2*border_thick + 2*border_gap + measured_text_height
    """
    text_faces, bb = _make_text_faces(station_name, font_path, text_height)

    # Delegates to station_sign_geometry.calculate_sign_layout() (extracted
    # 2026-08-08 -- full-review finding #29) so the sizing math is
    # pytest-testable without FreeCAD.
    layout = calculate_sign_layout(
        text_w=bb.XLength, text_h=bb.YLength,
        text_xmin=bb.XMin, text_ymin=bb.YMin,
        mat_thick=mat_thick, border_thick=border_thick, border_gap=border_gap)
    sign_w = layout['sign_w']
    sign_h = layout['sign_h']
    bg_thickness = layout['bg_thickness']
    border_height = layout['border_height']
    inner_x = layout['inner_x']
    inner_y = layout['inner_y']
    inner_w = layout['inner_w']
    inner_h = layout['inner_h']
    text_x = layout['text_x']
    text_y = layout['text_y']
    text_z = layout['text_z']

    # Background slab
    bg = Part.makeBox(sign_w, sign_h, bg_thickness)

    # Border frame: outer box minus inner cutout
    border_outer = Part.makeBox(sign_w, sign_h, mat_thick,
                                Vector(0, 0, bg_thickness))
    border_hole  = Part.makeBox(inner_w, inner_h, mat_thick,
                                Vector(inner_x, inner_y, bg_thickness))
    border = border_outer.cut(border_hole)

    # Raised text: centered within the inner area, placed on top of border
    glyph_solids = []
    for face in text_faces:
        s = face.extrude(Vector(0, 0, mat_thick))
        s.translate(Vector(text_x, text_y, text_z))
        glyph_solids.append(s)
    text_solid = Part.makeCompound(glyph_solids)

    # Fuse all layers
    try:
        result = bg.fuse(border).fuse(text_solid)
    except Exception as e:
        App.Console.PrintWarning(
            f"StationSignProxy: fuse failed ({e}), using compound\n")
        result = Part.makeCompound([bg, border, text_solid])

    return result, sign_w, sign_h


# =============================================================================
# FeaturePython proxy
# =============================================================================

class StationSignProxy:
    """Parametric station sign. Change StationName → sign rebuilds to fit."""

    Type = "StationSign"

    def __init__(self, obj):
        obj.Proxy = self
        self._setup_properties(obj)

    @staticmethod
    def _setup_properties(obj):
        grp = "StationSign"
        if not hasattr(obj, 'StationName'):
            obj.addProperty("App::PropertyString", "StationName", grp,
                            "Text displayed on the sign")
        if not hasattr(obj, 'FontPath'):
            obj.addProperty("App::PropertyFile", "FontPath", grp,
                            "Path to the sign font file (.ttf)")
        if not hasattr(obj, 'TextHeight'):
            obj.addProperty("App::PropertyLength", "TextHeight", grp,
                            "Text height (mm)")
        if not hasattr(obj, 'MaterialThickness'):
            obj.addProperty("App::PropertyLength", "MaterialThickness", grp,
                            "Layer thickness for 3D printing (mm)")
        if not hasattr(obj, 'BorderThickness'):
            obj.addProperty("App::PropertyLength", "BorderThickness", grp,
                            "Border frame width (mm)")
        if not hasattr(obj, 'BorderGap'):
            obj.addProperty("App::PropertyLength", "BorderGap", grp,
                            "Gap between border inner edge and text (mm)")
        if not hasattr(obj, 'GeneratorVersion'):
            obj.addProperty("App::PropertyString", "GeneratorVersion", grp,
                            "Generator version (read-only)")
            obj.setEditorMode("GeneratorVersion", 1)

    @staticmethod
    def set_defaults(obj, params=None):
        p = params or {}
        obj.StationName       = p.get('station_name',       "Default")
        obj.FontPath          = p.get('font_path', _DEFAULT_FONT)
        obj.TextHeight        = p.get('text_height',        _TEXT_HEIGHT_HO)
        obj.MaterialThickness = p.get('material_thickness', 0.2)
        obj.BorderThickness   = p.get('border_thickness',   0.5)
        obj.BorderGap         = p.get('border_gap',         1.0)
        obj.GeneratorVersion  = VERSION

    def execute(self, obj):
        name = obj.StationName.strip()
        if not name:
            return
        font_path = resolve_font_path(str(obj.FontPath), "StationSignProxy")
        if not font_path:
            global _font_help_shown_in_execute
            if not _font_help_shown_in_execute:
                # Reinforces the load-time warning at the moment generation
                # actually needs the font -- a user who skipped past that
                # message still gets told why their sign looks wrong (or
                # didn't generate). Shown once per session from here, not
                # on every recompute -- see _FONT_HELP's own comment.
                App.Console.PrintWarning(_FONT_HELP + "\n")
                _font_help_shown_in_execute = True
        had_shape = obj.Shape is not None and not obj.Shape.isNull()
        try:
            shape, w, h = generate_sign_shape(
                station_name  = name,
                font_path     = font_path,
                text_height   = float(obj.TextHeight),
                mat_thick     = float(obj.MaterialThickness),
                border_thick  = float(obj.BorderThickness),
                border_gap    = float(obj.BorderGap),
            )
            obj.Shape = shape
            App.Console.PrintMessage(
                f"  ✓ StationSign '{name}' → {w:.2f} × {h:.2f} mm\n")
        except Exception as e:
            App.Console.PrintError(f"StationSignProxy '{name}': {e}\n")
            if not had_shape:
                # No prior successful Shape to fall back to -- see
                # label_proxy.py's execute() for the full rationale
                # (full-review finding #31, 2026-08-08). Re-raising lets
                # FreeCAD's own recompute error handling mark the object
                # visibly instead of leaving it silently invisible.
                raise

    def dumps(self):
        return {"Type": self.Type}

    def loads(self, state):
        if state:
            self.Type = state.get("Type", "StationSign")

    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)


class StationSignViewProxy:
    def __init__(self, vobj):
        vobj.Proxy = self

    def getIcon(self):
        return ":/icons/Draft_ShapeString.svg"

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
