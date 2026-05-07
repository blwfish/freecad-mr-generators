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
import os
import sys
from pathlib import Path
from FreeCAD import Vector

VERSION = "2.0.0"
GENERATOR_NAME = "station_sign_generator"

_here = Path(__file__).parent
for p in (str(_here), str(_here / '_lib')):
    if p not in sys.path:
        sys.path.insert(0, p)

# Default font: C&O station font alongside the macro; fall back to empty (system default)
_DEFAULT_FONT = str(_here / "Station-font-AV-20-219.ttf")
if not os.path.exists(_DEFAULT_FONT):
    _DEFAULT_FONT = str(Path.home() / "Documents" / "FreeCAD-github" / "Station-font-AV-20-219.ttf")

# HO-scale text height: 16" prototype → 1:87 → mm
_TEXT_HEIGHT_HO = (16.0 / 87.0) * 25.4   # ≈ 4.67 mm


# =============================================================================
# Text shape helper
# =============================================================================

def _make_text_shape(text, font_path, height):
    """
    Return a Part compound shape for the given text string.

    Tries Part.makeShapeString first (no document objects created).
    Falls back to a temporary Draft shapestring if that fails.
    """
    path = font_path if (font_path and os.path.exists(font_path)) else ""
    try:
        shape = Part.makeShapeString(text, path, height, 0)
        if shape.isNull():
            raise RuntimeError("makeShapeString returned null shape")
        return shape
    except Exception as e:
        App.Console.PrintWarning(
            f"StationSignProxy: Part.makeShapeString failed ({e}), trying Draft\n")

    # Draft fallback — creates a temp document object then discards it
    try:
        import Draft
        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document for Draft fallback")
        tmp = Draft.make_shapestring(text, path, Size=height)
        doc.recompute()
        shape = tmp.Shape.copy()
        tmp.ViewObject.Visibility = False
        doc.recompute()
        doc.removeObject(tmp.Name)
        return shape
    except Exception as e2:
        raise RuntimeError(f"Cannot create text shape for '{text}': {e2}")


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
    text_shape = _make_text_shape(station_name, font_path, text_height)

    bb = text_shape.BoundBox
    text_w = bb.XLength
    text_h = bb.YLength

    sign_w = 2 * border_thick + 2 * border_gap + text_w
    sign_h = 2 * border_thick + 2 * border_gap + text_h

    bg_thickness  = 2 * mat_thick          # background slab
    border_height = bg_thickness + mat_thick   # top of border layer

    # Background slab
    bg = Part.makeBox(sign_w, sign_h, bg_thickness)

    # Border frame: outer box minus inner cutout
    inner_x = border_thick
    inner_y = border_thick
    inner_w = sign_w - 2 * border_thick
    inner_h = sign_h - 2 * border_thick
    border_outer = Part.makeBox(sign_w, sign_h, mat_thick,
                                Vector(0, 0, bg_thickness))
    border_hole  = Part.makeBox(inner_w, inner_h, mat_thick,
                                Vector(inner_x, inner_y, bg_thickness))
    border = border_outer.cut(border_hole)

    # Raised text: centered within the inner area, placed on top of border
    # Subtract bb.XMin/YMin so positioning is correct if text doesn't start at 0
    text_x = inner_x + (inner_w - text_w) / 2 - bb.XMin
    text_y = inner_y + (inner_h - text_h) / 2 - bb.YMin
    text_z = border_height

    text_solid = text_shape.extrude(Vector(0, 0, mat_thick))
    text_solid.translate(Vector(text_x, text_y, text_z))

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
        obj.FontPath          = p.get('font_path',
                                      _DEFAULT_FONT if os.path.exists(_DEFAULT_FONT) else "")
        obj.TextHeight        = p.get('text_height',        _TEXT_HEIGHT_HO)
        obj.MaterialThickness = p.get('material_thickness', 0.2)
        obj.BorderThickness   = p.get('border_thickness',   0.5)
        obj.BorderGap         = p.get('border_gap',         1.0)
        obj.GeneratorVersion  = VERSION

    def execute(self, obj):
        name = obj.StationName.strip()
        if not name:
            return
        try:
            shape, w, h = generate_sign_shape(
                station_name  = name,
                font_path     = obj.FontPath,
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
