"""
LabelProxy — FeaturePython proxy that places raised (or inset) text on a face.

Text is generated in the face's local coordinate system:
  - local XY = face plane
  - local +Z = face outward normal  (positive Height → raised; negative → inset)

Properties set by the macro at creation time (effectively read-only after):
  FaceCenter, FaceNormal, FaceXAxis, FaceWidth, FaceHeight

User-editable properties:
  Text, FontPath, FontSize (0 = auto-fit to face), Height, Padding, Rotation
"""

import FreeCAD as App
import Part
import sys
import math
from pathlib import Path
from FreeCAD import Vector, Matrix

_here = Path(__file__).parent
for p in (str(_here), str(_here / '_lib')):
    if p not in sys.path:
        sys.path.insert(0, p)

from label_geometry import compute_font_size, build_frame_matrix
from freecad_utils import resolve_font_path, find_first_existing_path  # noqa: E402

VERSION = "1.0.0"
GENERATOR_NAME = "label_generator"

# ---------------------------------------------------------------------------
# Font discovery
# ---------------------------------------------------------------------------

_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Geneva.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]

_DEFAULT_FONT = find_first_existing_path(_FONT_CANDIDATES)


# ---------------------------------------------------------------------------
# Text shape helper
# ---------------------------------------------------------------------------

def _wires_to_faces(char_wires):
    """
    Convert the wire list for one glyph to one or more Part.Face objects.

    Part.makeWireString returns all wires for a character flat: outer contour(s)
    plus any counter wires (holes).  Part.Face([outer, hole, ...]) handles
    the outer+hole case correctly, but fails for glyphs like 'i' or 'j' whose
    dot is a *disconnected island*, not a hole.

    Strategy: use bounding-box containment to group wires.  A wire whose
    bounding box fits entirely inside another wire's bounding box is treated as
    a hole of that outer wire.  Wires that are not contained in any other wire
    are outer contours and each seed a new face group.
    """
    if not char_wires:
        return []
    if len(char_wires) == 1:
        try:
            f = Part.Face(char_wires)
            return [f] if not f.isNull() else []
        except Exception:
            return []

    eps = 1e-6
    bbs = [w.BoundBox for w in char_wires]

    def contains(outer_bb, inner_bb):
        return (inner_bb.XMin >= outer_bb.XMin - eps and
                inner_bb.XMax <= outer_bb.XMax + eps and
                inner_bb.YMin >= outer_bb.YMin - eps and
                inner_bb.YMax <= outer_bb.YMax + eps)

    # A wire is "outer" if no other wire's bbox contains it
    n = len(char_wires)
    is_outer = [True] * n
    for i in range(n):
        for j in range(n):
            if i != j and contains(bbs[j], bbs[i]):
                is_outer[i] = False
                break

    used = [False] * n
    faces = []
    for i in range(n):
        if not is_outer[i] or used[i]:
            continue
        used[i] = True
        group = [char_wires[i]]
        for j in range(n):
            if not used[j] and not is_outer[j] and contains(bbs[i], bbs[j]):
                group.append(char_wires[j])
                used[j] = True
        try:
            f = Part.Face(group)
            if not f.isNull():
                faces.append(f)
        except Exception:
            pass

    return faces


def _make_text_faces(text, font_path, size):
    """
    Return (faces, bbox) where faces is a list of Part.Face objects for the
    given text at the given size, and bbox is the BoundBox of their compound.

    Uses Part.makeWireString (the Part-module API).  Disconnected glyph parts
    (dot of 'i', 'j', etc.) are correctly handled as separate faces rather
    than incorrectly treated as holes.

    *font_path* must already be resolved (see resolve_font_path()) -- this
    function does not re-check existence, so an unresolved caller-supplied
    path would silently pass through to Part.makeWireString here a second
    time with no diagnostic, undoing the point of resolving it once.
    """
    try:
        wire_lists = Part.makeWireString(text, font_path, size, 0)
    except Exception as exc:
        raise RuntimeError(f"Cannot create text wires for {text!r}: {exc}") from exc

    if not wire_lists:
        raise RuntimeError(f"makeWireString returned empty result for {text!r}")

    faces = []
    for char_wires in wire_lists:
        faces.extend(_wires_to_faces(char_wires))

    if not faces:
        raise RuntimeError(f"No valid glyph faces for {text!r} — check font path")

    bbox = Part.makeCompound(faces).BoundBox
    return faces, bbox


# ---------------------------------------------------------------------------
# FeaturePython proxy
# ---------------------------------------------------------------------------

class LabelProxy:
    """Parametric raised-text label placed on a face."""

    Type = "Label"

    def __init__(self, obj):
        obj.Proxy = self
        self._setup_properties(obj)

    @staticmethod
    def _setup_properties(obj):
        grp = "Label"
        frm = "FaceFrame"

        def add(ptype, name, group, tip):
            if not hasattr(obj, name):
                obj.addProperty(ptype, name, group, tip)

        add("App::PropertyString",  "Text",       grp, "Text to emboss/raise on the face")
        add("App::PropertyFile",    "FontPath",   grp, "Path to font file (.ttf)")
        add("App::PropertyFloat",   "FontSize",   grp, "Font size in mm (0 = auto-fit to face)")
        add("App::PropertyLength",  "Height",     grp, "Extrusion height in mm (negative → inset)")
        add("App::PropertyLength",  "Padding",    grp, "Margin from face edge before fitting text (mm)")
        add("App::PropertyAngle",   "Rotation",   grp, "Rotation around face normal (degrees)")

        add("App::PropertyVector",  "FaceCenter", frm, "Face centre in world coordinates")
        add("App::PropertyVector",  "FaceNormal", frm, "Face outward unit normal")
        add("App::PropertyVector",  "FaceXAxis",  frm, "Face u-direction (unit vector)")
        add("App::PropertyFloat",   "FaceWidth",  frm, "Face extent in u direction (mm)")
        add("App::PropertyFloat",   "FaceHeight", frm, "Face extent in v direction (mm)")

        add("App::PropertyString",  "GeneratorVersion", grp, "Generator version (read-only)")

        if hasattr(obj, "GeneratorVersion"):
            obj.setEditorMode("GeneratorVersion", 1)
        # Face frame properties are read-only in the editor after creation
        for prop in ("FaceCenter", "FaceNormal", "FaceXAxis", "FaceWidth", "FaceHeight"):
            if hasattr(obj, prop):
                obj.setEditorMode(prop, 1)

    @staticmethod
    def set_defaults(obj, text="Label", font_path=None):
        obj.Text             = text
        obj.FontPath         = font_path if font_path is not None else _DEFAULT_FONT
        obj.FontSize         = 0.0       # 0 = auto
        obj.Height           = 0.3
        obj.Padding          = 1.0
        obj.Rotation         = 0.0
        obj.GeneratorVersion = VERSION

    def execute(self, obj):
        text = obj.Text.strip()
        if not text:
            return

        height   = float(obj.Height)
        padding  = float(obj.Padding)
        rotation = float(obj.Rotation)   # degrees (App::PropertyAngle stores degrees)
        font_path = resolve_font_path(str(obj.FontPath), "LabelProxy")
        font_size = float(obj.FontSize)
        face_w    = float(obj.FaceWidth)
        face_h    = float(obj.FaceHeight)

        center = (obj.FaceCenter.x, obj.FaceCenter.y, obj.FaceCenter.z)
        normal = (obj.FaceNormal.x, obj.FaceNormal.y, obj.FaceNormal.z)
        x_axis = (obj.FaceXAxis.x,  obj.FaceXAxis.y,  obj.FaceXAxis.z)

        try:
            if font_size == 0.0:
                _, bb_ref = _make_text_faces(text, font_path, 1.0)
                if bb_ref.XLength <= 0 or bb_ref.YLength <= 0:
                    raise RuntimeError("Text shape has zero bounding box at size 1")
                font_size = compute_font_size(
                    bb_ref.XLength, bb_ref.YLength, face_w, face_h, padding
                )

            faces, bb = _make_text_faces(text, font_path, font_size)

            # Centre at local origin then extrude each glyph face.
            #
            # Extrude the label slightly into the parent surface so a Boolean
            # Union (Part → Boolean → Union) can actually fuse the two solids.
            # OCCT's Boolean Fuse will not merge solids whose faces are merely
            # coincident-coplanar; without overlap the result degenerates to a
            # Compound of two disjoint solids.  A 0.01 mm overlap is far below
            # any printable resolution but enough for OCCT to register a real
            # volumetric intersection.
            offset_x = -(bb.XMin + bb.XLength / 2.0)
            offset_y = -(bb.YMin + bb.YLength / 2.0)
            overlap = 0.01 if height >= 0 else -0.01   # mm into the face
            extrude_z = height + overlap
            base_z    = -overlap
            solids = []
            for face in faces:
                solid = face.extrude(Vector(0.0, 0.0, extrude_z))
                solid.translate(Vector(offset_x, offset_y, base_z))
                solids.append(solid)

            compound = Part.makeCompound(solids)

            # Bake world transform into the shape geometry using transformGeometry.
            # transformShape sets a TopoDS_Location which FreeCAD extracts into
            # obj.Placement on assignment, triggering a second recompute and an
            # unpredictable shape position.  transformGeometry returns a new shape
            # with actual vertex coordinates moved to world space; obj.Placement
            # stays identity and no second recompute is triggered.
            rows = build_frame_matrix(center, normal, x_axis, rotation)
            m = Matrix()
            m.A11, m.A12, m.A13, m.A14 = rows[0]
            m.A21, m.A22, m.A23, m.A24 = rows[1]
            m.A31, m.A32, m.A33, m.A34 = rows[2]
            m.A41, m.A42, m.A43, m.A44 = rows[3]
            compound = compound.transformGeometry(m)

            obj.Shape = compound

            App.Console.PrintMessage(
                f"  ✓ Label '{text}' @ size={font_size:.3f} mm  height={height:.3f} mm\n"
            )
        except Exception as exc:
            App.Console.PrintError(f"LabelProxy '{text}': {exc}\n")

    def dumps(self):
        return {"Type": self.Type}

    def loads(self, state):
        if state:
            self.Type = state.get("Type", "Label")

    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)


class LabelViewProxy:
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
