"""
AshlarProxy — FeaturePython proxy for parametric ashlar stone wall generation.

Generates a standalone wall object: textured stone faces extruded into solids,
a mortar sheet with stone cutouts, and a backing box.  Designed for STL export
and resin printing.

Change any property in the panel and the wall regenerates.  Properties can be
bound to spreadsheets or VarSets via expressions (right-click → Set expression).

This module must be importable by FreeCAD (installed alongside the macro).
"""

import FreeCAD as App
import Part
from FreeCAD import Base
import sys
from pathlib import Path

VERSION = "1.0.0"

_here = Path(__file__).parent
for _p in (str(_here), str(_here / '_lib')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ashlar_geometry import (
    generate_stone_surface,
    compute_stone_positions,
    compute_wall_dimensions,
    _NUMPY_SCIPY_OK,
    _IMPORT_ERROR,
)

# Previously this file re-checked scipy importability independently
# (`try: from scipy.spatial import Delaunay ... except ImportError:`) --
# dead code, since `from ashlar_geometry import (...)` above would have
# already raised ImportError and aborted this whole module before that
# check could ever run, back when ashlar_geometry.py imported numpy/
# scipy unconditionally at its own module level. Now that
# ashlar_geometry.py defers and reports that failure itself (v1.0.1,
# 2026-08-08), this file just reads its single source of truth instead
# of maintaining a second, easily-diverging copy of the same check.
_SCIPY_OK = _NUMPY_SCIPY_OK

if not _SCIPY_OK:
    App.Console.PrintWarning(
        f"ashlar_proxy: numpy/scipy not available ({_IMPORT_ERROR}) -- "
        "AshlarWall objects can be created but will not generate geometry "
        "until these are installed in FreeCAD's own Python environment. "
        "Every other generator in this repo works without them.\n"
    )


# =============================================================================
# Stone geometry builder
# =============================================================================

def _build_stone_solid(x_off, y_off, points_2d, z_values, simplices,
                        extrude_depth):
    """
    Convert triangulated surface data to a FreeCAD solid.

    Strategy: build a triangulated shell from the displaced front surface,
    then extrude it backward by extrude_depth.  This is fast and produces
    clean geometry for STL export.

    Returns a Part.Shape (solid or shell fallback), or None on failure.
    """
    fc_pts = [Base.Vector(float(points_2d[i, 0] + x_off),
                          float(points_2d[i, 1] + y_off),
                          float(z_values[i]))
              for i in range(len(points_2d))]

    faces = []
    for s in simplices:
        try:
            tri = Part.makePolygon([fc_pts[s[0]], fc_pts[s[1]], fc_pts[s[2]],
                                    fc_pts[s[0]]])
            faces.append(Part.Face(tri))
        except Part.OCCError:
            pass

    if not faces:
        return None

    try:
        shell = Part.Shell(faces)
        solid = shell.extrude(Base.Vector(0, 0, -extrude_depth))
        return solid
    except Part.OCCError:
        try:
            return Part.Shell(faces)
        except Part.OCCError:
            return Part.Compound(faces) if faces else None


def _build_mortar_sheet(wall_width, wall_height, stones):
    """Flat mortar sheet with rectangular holes for each stone."""
    mortar_z = -0.1
    base = Part.makeBox(wall_width, wall_height, 0.2)
    base.translate(Base.Vector(0, 0, mortar_z - 0.1))

    cutouts = []
    for s in stones:
        cut = Part.makeBox(s['width'], s['height'], 0.6)
        cut.translate(Base.Vector(s['x'], s['y'], mortar_z - 0.3))
        cutouts.append(cut)

    if cutouts:
        try:
            if len(cutouts) > 1:
                compound_cut = cutouts[0].fuse(cutouts[1:])
            else:
                compound_cut = cutouts[0]
            base = base.cut(compound_cut)
        except Part.OCCError:
            pass

    return base


# =============================================================================
# FeaturePython proxy
# =============================================================================

class AshlarProxy:

    def __init__(self, obj):
        obj.Proxy = self
        self._add_properties(obj)

    def _add_properties(self, obj):
        g = "Ashlar Wall"

        obj.addProperty("App::PropertyInteger", "NCols", g,
                        "Number of stone columns").NCols = 4
        obj.addProperty("App::PropertyInteger", "NRows", g,
                        "Number of stone rows").NRows = 3

        obj.addProperty("App::PropertyFloat", "StoneWidth", g,
                        "Stone width (mm)").StoneWidth = 7.0
        obj.addProperty("App::PropertyFloat", "StoneHeight", g,
                        "Stone height (mm)").StoneHeight = 5.25
        obj.addProperty("App::PropertyFloat", "JointWidth", g,
                        "Mortar joint width (mm)").JointWidth = 0.3
        obj.addProperty("App::PropertyFloat", "StoneDepth", g,
                        "Stone depth / wall thickness (mm)").StoneDepth = 2.0

        g2 = "Surface Texture"
        obj.addProperty("App::PropertyFloat", "AvgSpacing", g2,
                        "Mesh point spacing (mm) — smaller = more detail, slower"
                        ).AvgSpacing = 0.25
        obj.addProperty("App::PropertyFloat", "Randomness", g2,
                        "Grid point jitter factor (0–1)").Randomness = 0.6
        obj.addProperty("App::PropertyFloat", "DisplacementMin", g2,
                        "Minimum Z displacement (mm)").DisplacementMin = -0.8
        obj.addProperty("App::PropertyFloat", "DisplacementMax", g2,
                        "Maximum Z displacement (mm)").DisplacementMax = 0.8
        obj.addProperty("App::PropertyFloat", "ZOffset", g2,
                        "Forward offset so deepest recesses stay above Z=0"
                        ).ZOffset = 1.0
        obj.addProperty("App::PropertyInteger", "NFractures", g2,
                        "Number of fracture planes").NFractures = 3
        obj.addProperty("App::PropertyFloat", "EdgeTaper", g2,
                        "Distance (mm) over which displacement tapers to zero"
                        " at stone edge").EdgeTaper = 1.5
        obj.addProperty("App::PropertyInteger", "Seed", g2,
                        "Base random seed — change for a different stone pattern"
                        ).Seed = 42

    def execute(self, obj):
        if not _SCIPY_OK:
            # Full explanation + fix instructions already printed once at
            # module load; this reinforces it at the moment generation
            # actually needed numpy/scipy, for anyone who missed that.
            App.Console.PrintError(
                f"AshlarProxy: numpy/scipy not available ({_IMPORT_ERROR}) "
                "-- cannot generate geometry. See the warning printed when "
                "this generator loaded for how to fix.\n"
            )
            return

        stones = compute_stone_positions(
            obj.NCols, obj.NRows,
            obj.StoneWidth, obj.StoneHeight, obj.JointWidth,
        )
        dims = compute_wall_dimensions(
            obj.NCols, obj.NRows,
            obj.StoneWidth, obj.StoneHeight, obj.JointWidth,
        )

        extrude_depth = obj.StoneDepth + obj.ZOffset + 0.5

        shapes = []
        for s in stones:
            try:
                pts2d, z_vals, simplices = generate_stone_surface(
                    s['width'], s['height'],
                    avg_spacing=obj.AvgSpacing,
                    randomness=obj.Randomness,
                    displacement_range=(obj.DisplacementMin, obj.DisplacementMax),
                    n_fractures=obj.NFractures,
                    edge_taper=obj.EdgeTaper,
                    z_offset=obj.ZOffset,
                    seed=s['seed'] + obj.Seed,
                )
                stone_shape = _build_stone_solid(
                    s['x'], s['y'], pts2d, z_vals, simplices, extrude_depth,
                )
                if stone_shape is not None:
                    shapes.append(stone_shape)
            except Exception as exc:
                App.Console.PrintWarning(
                    f"AshlarProxy: stone [{s['row']},{s['col']}] failed: {exc}\n"
                )

        try:
            mortar = _build_mortar_sheet(dims['width'], dims['height'], stones)
            shapes.append(mortar)
        except Part.OCCError as exc:
            App.Console.PrintWarning(f"AshlarProxy: mortar sheet failed: {exc}\n")

        try:
            backing = Part.makeBox(dims['width'], dims['height'], 1.5)
            backing.translate(Base.Vector(0, 0, -(obj.StoneDepth + obj.ZOffset)))
            shapes.append(backing)
        except Part.OCCError as exc:
            App.Console.PrintWarning(f"AshlarProxy: backing box failed: {exc}\n")

        if shapes:
            obj.Shape = Part.Compound(shapes)
        else:
            App.Console.PrintError("AshlarProxy: no geometry produced.\n")

    def onChanged(self, obj, prop):
        pass


class AshlarViewProxy:

    def __init__(self, vobj):
        vobj.Proxy = self

    def getIcon(self):
        return ""

    def attach(self, vobj):
        pass

    def updateData(self, fp, prop):
        pass

    def onChanged(self, vp, prop):
        pass


# =============================================================================
# Factory
# =============================================================================

def make_ashlar_wall(doc=None):
    """Create an AshlarWall FeaturePython object in the active document."""
    if doc is None:
        doc = App.ActiveDocument
    if doc is None:
        doc = App.newDocument("AshlarWall")

    obj = doc.addObject("Part::FeaturePython", "AshlarWall")
    AshlarProxy(obj)
    if obj.ViewObject:
        AshlarViewProxy(obj.ViewObject)

    doc.recompute()
    return obj
