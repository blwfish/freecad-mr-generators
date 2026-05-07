"""
RadialBrickProxy — FeaturePython proxy for parametric radial brick generation.

Change any property in the panel and the brick skin regenerates automatically.
Face references stored as PropertyLinkSubList so they survive save/reload.

Generates running-bond brick patterns on cylindrical and conical surfaces.
Primary use cases: smokestacks, water towers, silos, grain elevators.

This module must be importable by FreeCAD (installed alongside the macro).
"""

import FreeCAD as App
import Part
import math
import sys
from pathlib import Path

VERSION = "2.0.0"
GENERATOR_NAME = "radial_brick_generator"

_here = Path(__file__).parent
for p in (str(_here), str(_here / '_lib')):
    if p not in sys.path:
        sys.path.insert(0, p)

from radial_brick_geometry import RadialBrickGeometry, RadialBrickDef


# =============================================================================
# Face analysis helpers
# =============================================================================

def _face_normal_at_center(face):
    ur, vr = face.ParameterRange[:2], face.ParameterRange[2:]
    return face.normalAt((ur[0] + ur[1]) / 2, (vr[0] + vr[1]) / 2)


def analyze_cylindrical_face(face):
    """
    Analyze a cylindrical or conical face and return geometry info dict.

    Returns dict with keys:
        type, axis, center, z_min, z_max,
        radius_at_z_min, radius_at_z_max, is_concave
    Raises ValueError for unsupported surface types.
    """
    surface = face.Surface
    st = surface.TypeId

    if st == 'Part::GeomCylinder':
        return _analyze_cylinder(face, surface)
    elif st == 'Part::GeomCone':
        return _analyze_cone(face, surface)
    elif st == 'Part::GeomPlane':
        raise ValueError(
            "Selected face is planar. Use brick_generator for flat walls. "
            "radial_brick_proxy requires cylindrical or conical surfaces."
        )
    else:
        raise ValueError(
            f"Surface type '{st}' not supported. "
            "Requires Part::GeomCylinder or Part::GeomCone."
        )


def _analyze_cylinder(face, surface):
    axis   = surface.Axis
    center = surface.Center
    radius = surface.Radius
    bbox   = face.BoundBox

    # Warn if axis far from vertical
    z_axis = App.Vector(0, 0, 1)
    ang = math.degrees(axis.getAngle(z_axis))
    if ang > 90:
        ang = 180 - ang
    if ang > 15:
        App.Console.PrintWarning(
            f"RadialBrickProxy: cylinder axis is {ang:.1f}° from vertical\n")

    # Concavity: normal pointing toward axis → concave
    u, v = (face.ParameterRange[0] + face.ParameterRange[1]) / 2, \
           (face.ParameterRange[2] + face.ParameterRange[3]) / 2
    try:
        normal = face.normalAt(u, v)
        point  = face.valueAt(u, v)
        radial = point - center
        radial = radial - axis * radial.dot(axis)
        radial.normalize()
        is_concave = normal.dot(radial) < 0
    except Exception:
        is_concave = False

    return {
        'type':            'cylinder',
        'axis':            axis,
        'center':          center,
        'z_min':           bbox.ZMin,
        'z_max':           bbox.ZMax,
        'radius_at_z_min': radius,
        'radius_at_z_max': radius,
        'is_concave':      is_concave,
    }


def _analyze_cone(face, surface):
    axis       = surface.Axis
    apex       = surface.Apex
    semi_angle = surface.SemiAngle  # radians
    bbox       = face.BoundBox
    z_min, z_max = bbox.ZMin, bbox.ZMax

    z_axis = App.Vector(0, 0, 1)
    ang = math.degrees(axis.getAngle(z_axis))
    if ang > 90:
        ang = 180 - ang
    if ang > 15:
        App.Console.PrintWarning(
            f"RadialBrickProxy: cone axis is {ang:.1f}° from vertical\n")

    apex_z = apex.z
    if axis.z < 0:
        dist_min = apex_z - z_min
        dist_max = apex_z - z_max
    else:
        dist_min = z_min - apex_z
        dist_max = z_max - apex_z

    radius_at_z_min = abs(dist_min * math.tan(semi_angle))
    radius_at_z_max = abs(dist_max * math.tan(semi_angle))

    u, v = (face.ParameterRange[0] + face.ParameterRange[1]) / 2, \
           (face.ParameterRange[2] + face.ParameterRange[3]) / 2
    try:
        normal = face.normalAt(u, v)
        point  = face.valueAt(u, v)
        radial = point - apex
        radial = radial - axis * radial.dot(axis)
        is_concave = (radial.Length > 0.001 and normal.dot(radial / radial.Length) < 0)
    except Exception:
        is_concave = False

    return {
        'type':            'cone',
        'axis':            axis,
        'center':          apex,
        'z_min':           z_min,
        'z_max':           z_max,
        'radius_at_z_min': radius_at_z_min,
        'radius_at_z_max': radius_at_z_max,
        'is_concave':      is_concave,
    }


# =============================================================================
# Brick solid builder
# =============================================================================

def create_brick_solid(brick, rbg):
    """Build a wedge-shaped FreeCAD solid from a RadialBrickDef."""
    vertices = rbg.get_brick_vertices(brick)
    pts = [App.Vector(v[0], v[1], v[2]) for v in vertices]

    # Vertices: 0-3 bottom face, 4-7 top face
    # Each face: inner-start, inner-end, outer-end, outer-start
    try:
        e_b = [Part.makeLine(pts[i], pts[(i+1) % 4]) for i in range(4)]
        e_t = [Part.makeLine(pts[4+i], pts[4+(i+1) % 4]) for i in range(4)]
        e_v = [Part.makeLine(pts[i], pts[4+i]) for i in range(4)]

        f_bottom = Part.Face(Part.Wire(e_b))
        f_top    = Part.Face(Part.Wire(e_t))
        f_inner  = Part.Face(Part.Wire([e_b[0], e_v[1], e_t[0], e_v[0]]))
        f_outer  = Part.Face(Part.Wire([e_b[2], e_v[3], e_t[2], e_v[2]]))
        f_start  = Part.Face(Part.Wire([e_b[3], e_v[0], e_t[3], e_v[3]]))
        f_end    = Part.Face(Part.Wire([e_b[1], e_v[2], e_t[1], e_v[1]]))

        shell = Part.Shell([f_bottom, f_top, f_inner, f_outer, f_start, f_end])
        return Part.Solid(shell)
    except Exception as e:
        App.Console.PrintWarning(f"  Brick solid failed: {e}\n")
        return None


# =============================================================================
# Core generation
# =============================================================================

def generate_radial_bricks(face, brick_length=2.32, brick_height=0.65,
                            material_thickness=0.3, mortar_thickness=0.11):
    """
    Generate a running-bond brick skin for one cylindrical/conical face.

    Returns a Part.Compound of brick solids.

    brick_length:       length along circumference (mm)
    brick_height:       height along Z axis (mm)
    material_thickness: radial skin depth — used for brick thickness (mm)
    mortar_thickness:   mortar joint thickness (mm)
    """
    info = analyze_cylindrical_face(face)

    # Offset radius inward by half skin so bricks straddle the surface
    half = material_thickness / 2.0
    rbg = RadialBrickGeometry(
        z_min=info['z_min'],
        z_max=info['z_max'],
        radius_at_z_min=info['radius_at_z_min'] - half,
        radius_at_z_max=info['radius_at_z_max'] - half,
        brick_length=brick_length,
        brick_height=brick_height,
        brick_thickness=material_thickness,
        mortar_thickness=mortar_thickness,
        is_concave=False,   # always project outward (we already offset inward)
        bond_offset=0.5,
    )

    result   = rbg.generate()
    bricks   = result['bricks']
    metadata = result['metadata']
    App.Console.PrintMessage(
        f"  courses={metadata['num_courses']}, "
        f"bricks={metadata['total_bricks']}\n"
    )

    shapes = []
    for i, brick in enumerate(bricks):
        s = create_brick_solid(brick, rbg)
        if s is not None:
            shapes.append(s)
        if (i + 1) % 500 == 0:
            App.Console.PrintMessage(f"    {i+1}/{len(bricks)} bricks...\n")

    if not shapes:
        raise RuntimeError("No brick solids created!")

    # Translate if the cylinder center is not at origin
    cx, cy = info['center'].x, info['center'].y
    if abs(cx) > 1e-6 or abs(cy) > 1e-6:
        offset = App.Vector(cx, cy, 0)
        shapes = [s.translated(offset) for s in shapes]

    return Part.Compound(shapes)


# =============================================================================
# FeaturePython proxy
# =============================================================================

class RadialBrickProxy:
    """Parametric radial brick skin. Change a property → shape updates."""

    Type = "RadialBrick"

    def __init__(self, obj):
        obj.Proxy = self
        self._setup_properties(obj)

    @staticmethod
    def _setup_properties(obj):
        grp = "RadialBrick"
        if not hasattr(obj, 'Sources'):
            obj.addProperty(
                "App::PropertyLinkSubList", "Sources", grp,
                "Cylindrical/conical faces to apply brick pattern to")
        if not hasattr(obj, 'BrickLength'):
            obj.addProperty("App::PropertyLength", "BrickLength", grp,
                            "Brick length along circumference (mm)")
        if not hasattr(obj, 'BrickHeight'):
            obj.addProperty("App::PropertyLength", "BrickHeight", grp,
                            "Brick height along Z axis (mm)")
        if not hasattr(obj, 'MaterialThickness'):
            obj.addProperty("App::PropertyLength", "MaterialThickness", grp,
                            "Radial skin depth / brick thickness (mm)")
        if not hasattr(obj, 'MortarThickness'):
            obj.addProperty("App::PropertyLength", "MortarThickness", grp,
                            "Mortar joint thickness (mm)")
        if not hasattr(obj, 'GeneratorVersion'):
            obj.addProperty("App::PropertyString", "GeneratorVersion", grp,
                            "Generator version (read-only)")
            obj.setEditorMode("GeneratorVersion", 1)

    @staticmethod
    def set_defaults(obj, params=None):
        p = params or {}
        obj.BrickLength       = p.get('brick_length',       2.32)
        obj.BrickHeight       = p.get('brick_height',       0.65)
        obj.MaterialThickness = p.get('material_thickness', 0.3)
        obj.MortarThickness   = p.get('mortar_thickness',   0.11)
        obj.GeneratorVersion  = VERSION

    def execute(self, obj):
        if not obj.Sources:
            return

        bl = float(obj.BrickLength)
        bh = float(obj.BrickHeight)
        mt = float(obj.MaterialThickness)
        mo = float(obj.MortarThickness)

        compounds = []
        for link_obj, sub_names in obj.Sources:
            if not hasattr(link_obj, 'Shape'):
                continue
            for sub_name in sub_names:
                if not sub_name.startswith('Face'):
                    continue
                try:
                    face = link_obj.Shape.getElement(sub_name)
                    compound = generate_radial_bricks(face, bl, bh, mt, mo)
                    compounds.append(compound)
                    App.Console.PrintMessage(
                        f"  ✓ {link_obj.Label}/{sub_name}\n")
                except Exception as e:
                    App.Console.PrintError(
                        f"RadialBrickProxy: {link_obj.Label}/{sub_name}: {e}\n")

        if not compounds:
            return
        obj.Shape = (compounds[0] if len(compounds) == 1
                     else Part.Compound(compounds))

    def dumps(self):
        return {"Type": self.Type}

    def loads(self, state):
        if state:
            self.Type = state.get("Type", "RadialBrick")

    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)


class RadialBrickViewProxy:
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
