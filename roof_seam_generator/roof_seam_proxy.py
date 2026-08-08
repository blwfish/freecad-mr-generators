"""
RoofSeamProxy — FeaturePython proxy for parametric hip cap / valley flashing.

Change any property in the panel and the seam geometry regenerates.
Face references stored as PropertyLinkSubList so they survive save/reload.

This module must be importable by FreeCAD (installed alongside the macro).

Version History:
- 5.1.0: find_shared_edge/resolve_shared_edge/_closest_base_face moved to
         shared/freecad_utils.py (consolidating a vendored duplicate in
         slate_seam_proxy.py) and extended to recognize the Sources
         PropertyLinkSubList convention (shingle_proxy's current output,
         and this repo's modern standard generally) alongside the legacy
         BaseObject/ShingledRoof_/ShingleSkin_ convention from
         shingle_generator's old macro-only workflow, which this module
         previously only recognized. Selecting faces from a *current*
         ShingleProxy output never got unwrapped to the real roof panel
         before this fix.
- 5.0.0: (unversioned history prior to this entry)
"""

import FreeCAD as App
import Part
import math
import sys
from pathlib import Path

VERSION = "5.1.0"
GENERATOR_NAME = "roof_seam_generator"

_here = Path(__file__).parent
for p in (str(_here), str(_here / '_lib'), str(_here.parent / 'shared')):
    if p not in sys.path:
        sys.path.insert(0, p)

from freecad_utils import find_shared_edge, resolve_shared_edge, resolve_sources_faces  # noqa: E402
from roof_geometry import classify_roof_intersection  # noqa: E402
from roof_seam_geometry import (  # noqa: E402
    validate_exposure,
    calculate_cap_positions,
    calculate_hip_cap_profile,
)


# =============================================================================
# Geometry helpers
# =============================================================================

def _face_normal_at_center(face):
    uv = face.ParameterRange
    return face.normalAt((uv[0] + uv[1]) / 2, (uv[2] + uv[3]) / 2)


def _make_rotation_matrix(x_axis, y_axis, z_axis):
    return App.Matrix(
        x_axis.x, y_axis.x, z_axis.x, 0,
        x_axis.y, y_axis.y, z_axis.y, 0,
        x_axis.z, y_axis.z, z_axis.z, 0,
        0, 0, 0, 1,
    )



def classify_seam(face1, face2, shared_edge):
    """Classify seam as 'hip' or 'valley'.

    Delegates to shared/roof_geometry.classify_roof_intersection() -- a
    pure Z-coordinate-average heuristic (NOT dihedral-angle-based, despite
    an earlier version of this docstring's claim -- dihedral angle is
    computed separately by calculate_dihedral_angle() and never feeds this
    classification decision, only human-readable text elsewhere) that
    slate_generator, standing_seam_generator, and slate_seam_generator all
    already use, instead of an independently-maintained duplicate with no
    'ambiguous' outcome of its own.

    Raises RuntimeError on the shared classifier's own 'ambiguous' result
    instead of silently defaulting to 'hip'. This previously defaulted to
    'hip' with only a PrintWarning -- but slate_seam_generator's
    resolve_cap_eligibility(), written against the SAME shared classifier,
    explicitly rejects 'ambiguous' rather than risk silently capping an
    actual valley the one time this branch fires for real. Two consumers
    of the same classifier had reached opposite, unreconciled decisions on
    the identical edge case (full-review finding
    freecad-mr-generators-20260808-a0b9#16) -- raising here matches the
    more conservative of the two and surfaces the ambiguity to the user
    (via execute()'s existing try/except -> PrintError) instead of
    guessing.
    """
    face1_verts = [(v.Point.x, v.Point.y, v.Point.z) for v in face1.Vertexes]
    face2_verts = [(v.Point.x, v.Point.y, v.Point.z) for v in face2.Vertexes]
    e0, e1 = shared_edge.Vertexes[0].Point, shared_edge.Vertexes[-1].Point
    shared_edge_tuple = ((e0.x, e0.y, e0.z), (e1.x, e1.y, e1.z))

    result = classify_roof_intersection(face1_verts, face2_verts, shared_edge_tuple)
    classification = result['classification']
    if classification == 'ridge':
        return 'hip'
    if classification == 'valley':
        return 'valley'
    raise RuntimeError(
        f"Seam classification ambiguous "
        f"({result.get('reason', 'unknown')}) -- cannot safely determine "
        f"hip vs valley for this face pair. Select two faces with a "
        f"clearer roof intersection, or check the faces for degenerate "
        f"geometry.")


# =============================================================================
# Hip cap generation
# =============================================================================

def generate_hip_caps(shared_edge, face1, face2, params):
    """
    Generate cap shingles straddling the hip/ridge edge.
    Returns (shapes_list, cut_blocks_list).

    Key change from v3.x: uses Part.Face(wire).extrude() directly instead of
    creating temporary Part::Extrusion document objects (cleaner, works in execute()).
    """
    cap_width   = params.get('hipCapWidth', params.get('shingleWidth', 3.5) * 2.0)
    cap_height  = params.get('shingleHeight', 2.0)
    mat_thick   = params.get('materialThickness', 0.25)
    exposure    = params.get('shingleExposure', 1.5)
    angle_depth = params.get('angleDepth', 0.2)
    half_width  = cap_width / 2.0

    validate_exposure(exposure, "generate_hip_caps")

    # Edge geometry — orient eave (low Z) → apex (high Z)
    v0, v1 = shared_edge.Vertexes[0].Point, shared_edge.Vertexes[-1].Point
    start_pt, end_pt = (v0, v1) if v0.z <= v1.z else (v1, v0)
    edge_vec = end_pt - start_pt
    edge_len = edge_vec.Length
    edge_dir = edge_vec * (1.0 / edge_len)

    n1 = _face_normal_at_center(face1)
    n2 = _face_normal_at_center(face2)
    n1_out = n1 * -1.0 if n1.z < 0 else App.Vector(n1.x, n1.y, n1.z)
    n2_out = n2 * -1.0 if n2.z < 0 else App.Vector(n2.x, n2.y, n2.z)
    seam_mid = (start_pt + end_pt) * 0.5

    def compute_d(n_out, face_centroid):
        d_raw = n_out.cross(edge_dir)
        if d_raw.Length < 1e-9:
            # Degenerate: this face's normal is parallel to the shared
            # edge. generate_slate_hip_caps/generate_metal_hip_strip in
            # this same file both guard the analogous local_x computation
            # this way; generate_hip_caps (the default hip_style='shingle'
            # path) previously didn't, raising an unhandled
            # ZeroDivisionError instead of a clear, catchable error
            # (full-review finding freecad-mr-generators-20260808-a0b9#15).
            raise ValueError(
                "Cannot compute hip cap wing direction: a face normal is "
                "parallel to the shared edge (degenerate hip geometry)")
        d = d_raw * (1.0 / d_raw.Length)
        if (face_centroid - seam_mid).dot(d) < 0:
            d = d * -1.0
        return d

    d1 = compute_d(n1_out, face1.CenterOfMass)
    d2 = compute_d(n2_out, face2.CenterOfMass)

    bisector = n1_out + n2_out
    if bisector.Length < 1e-9:
        raise ValueError(
            "Cannot compute hip cap bisector: face normals are near-opposite "
            "(nearly coplanar faces meeting at a near-180 degree angle)")
    bisector = bisector * (1.0 / bisector.Length)

    local_x = edge_dir.cross(bisector)
    if local_x.Length < 1e-9:
        local_x = App.Vector(1, 0, 0)
    else:
        local_x = local_x * (1.0 / local_x.Length)
    local_z = bisector

    cos_dihed = n1_out.dot(n2_out)
    profile = calculate_hip_cap_profile(half_width, mat_thick, cos_dihed, angle_depth)
    bl_2d, bc_2d, br_2d = profile['bl_2d'], profile['bc_2d'], profile['br_2d']
    tl_2d, tc1_2d, tc2_2d, tr_2d = profile['tl_2d'], profile['tc1_2d'], profile['tc2_2d'], profile['tr_2d']
    dome_mid_2d = profile['dome_mid_2d']
    taper = profile['taper']

    def to_3d(x2d, z2d, pt):
        return pt + local_x * x2d + local_z * z2d

    def _make_cap_wire(pt):
        bl3  = to_3d(*bl_2d,       pt)
        bc3  = to_3d(*bc_2d,       pt)
        br3  = to_3d(*br_2d,       pt)
        tr3  = to_3d(*tr_2d,       pt)
        tc23 = to_3d(*tc2_2d,      pt)
        tc13 = to_3d(*tc1_2d,      pt)
        tl3  = to_3d(*tl_2d,       pt)
        am3  = to_3d(*dome_mid_2d, pt)
        return Part.Wire([
            Part.makeLine(bl3, bc3),
            Part.makeLine(bc3, br3),
            Part.makeLine(br3, tr3),
            Part.makeLine(tr3, tc23),
            Part.Arc(tc23, am3, tc13).toShape(),
            Part.makeLine(tc13, tl3),
            Part.makeLine(tl3, bl3),
        ])

    def _make_one_cap(pt):
        wire = _make_cap_wire(pt)
        # Direct extrusion — avoids creating temp doc objects
        cap_shape = Part.Face(wire).extrude(edge_dir * cap_height)

        if taper < 1e-6:
            return cap_shape

        eps = taper * 0.01
        rtop = to_3d(tc1_2d[0], tc1_2d[1], pt)
        w0 = rtop + local_z * eps
        w1 = rtop + edge_dir * cap_height + local_z * eps
        w2 = rtop + edge_dir * cap_height - local_z * taper

        wedge_wire = Part.Wire([
            Part.makeLine(w0, w1), Part.makeLine(w1, w2), Part.makeLine(w2, w0),
        ])
        wedge_L = Part.Face(wedge_wire).extrude(d1 * (half_width + mat_thick * 2.0))

        def _mirror_face(face_shape, plane_pt, plane_normal):
            verts = []
            for v in face_shape.Vertexes:
                p = v.Point
                d = (p - plane_pt).dot(plane_normal)
                verts.append(p - plane_normal * (2.0 * d))
            mw = Part.Wire([
                Part.makeLine(verts[0], verts[1]),
                Part.makeLine(verts[1], verts[2]),
                Part.makeLine(verts[2], verts[0]),
            ])
            return Part.Face(mw).extrude(d2 * (half_width + mat_thick * 2.0))

        wedge_R = _mirror_face(Part.Face(wedge_wire), pt, local_x)

        try:
            cap_shape = cap_shape.cut(wedge_L)
        except Exception:
            pass
        try:
            cap_shape = cap_shape.cut(wedge_R)
        except Exception:
            pass

        if len(cap_shape.Solids) > 1:
            cap_shape = max(cap_shape.Solids, key=lambda s: s.Volume)

        return cap_shape

    # Cutting blocks at eave/gable boundaries
    cut_blocks = []
    try:
        shared_verts = [v.Point for v in shared_edge.Vertexes]
        block_size = 200.0

        def _is_shared_edge(edge, tol2=0.5):
            ev = [v.Point for v in edge.Vertexes]
            if len(ev) < 2:
                return False
            matched = sum(1 for sv in shared_verts if min(sv.distanceToPoint(v) for v in ev) <= tol2)
            if matched == len(shared_verts):
                return True
            e_mid = (ev[0] + ev[-1]) * 0.5
            s_dir = shared_verts[-1] - shared_verts[0]
            s_len = s_dir.Length
            if s_len < 1e-9:
                return False
            s_dir = s_dir * (1.0 / s_len)
            offset = e_mid - shared_verts[0]
            perp = offset - s_dir * offset.dot(s_dir)
            if perp.Length < tol2:
                e_dir2 = ev[-1] - ev[0]
                if e_dir2.Length > 1e-9:
                    if e_dir2.cross(s_dir).Length / e_dir2.Length < 0.05:
                        return True
            return False

        def _touches_shared_endpoint(edge, tol2=0.5):
            return any(ev.Point.distanceToPoint(sp) < tol2
                       for ev in edge.Vertexes for sp in shared_verts)

        def _make_cut_block(edge, face):
            e_dir2 = edge.Vertexes[-1].Point - edge.Vertexes[0].Point
            e_dir2 = e_dir2 * (1.0 / e_dir2.Length)
            n = _face_normal_at_center(face)
            perp = n.cross(e_dir2)
            if perp.Length < 1e-9:
                return None
            perp = perp * (1.0 / perp.Length)
            to_center = face.CenterOfMass - edge.Vertexes[0].Point
            if to_center.dot(perp) > 0:
                perp = perp * -1.0
            e_mid = (edge.Vertexes[0].Point + edge.Vertexes[-1].Point) * 0.5
            ax1, ax2 = e_dir2, n
            p1 = e_mid - ax1 * block_size - ax2 * block_size
            p2 = e_mid + ax1 * block_size - ax2 * block_size
            p3 = e_mid + ax1 * block_size + ax2 * block_size
            p4 = e_mid - ax1 * block_size + ax2 * block_size
            wire = Part.Wire([
                Part.makeLine(p1, p2), Part.makeLine(p2, p3),
                Part.makeLine(p3, p4), Part.makeLine(p4, p1),
            ])
            return Part.Face(wire).extrude(perp * block_size)

        skipped = 0
        for face in [face1, face2]:
            for edge in face.Edges:
                if _is_shared_edge(edge):
                    continue
                if not _touches_shared_endpoint(edge):
                    skipped += 1
                    continue
                blk = _make_cut_block(edge, face)
                if blk and blk.Volume > 1e-6:
                    cut_blocks.append(blk)

        App.Console.PrintMessage(
            f"  Built {len(cut_blocks)} cutting blocks "
            f"(skipped {skipped} interior edges)\n")
    except Exception as e:
        App.Console.PrintMessage(f"  Cut block build failed: {e}\n")

    # Generate cap shingles
    shapes = []
    fail_count = 0
    for t in calculate_cap_positions(edge_len, exposure):
        pt = start_pt + edge_dir * t
        try:
            cap = _make_one_cap(pt)
            if cap.Solids:
                shapes.append(cap.Solids[0] if len(cap.Solids) == 1 else cap)
            elif cap.Volume > 1e-6:
                shapes.append(cap)
        except Exception:
            fail_count += 1

    if fail_count:
        App.Console.PrintMessage(f"  {fail_count} caps failed\n")

    # Continuous dome strip
    try:
        tc1_3d = to_3d(*tc1_2d, start_pt)
        tc2_3d = to_3d(*tc2_2d, start_pt)
        am_3d  = to_3d(*dome_mid_2d, start_pt)
        dome_wire = Part.Wire([
            Part.Arc(tc2_3d, am_3d, tc1_3d).toShape(),
            Part.makeLine(tc1_3d, tc2_3d),
        ])
        dome_strip = Part.Face(dome_wire).extrude(edge_dir * edge_len)
        if dome_strip.Volume > 1e-6:
            shapes.append(dome_strip)
    except Exception as e:
        App.Console.PrintMessage(f"  Dome strip failed: {e}\n")

    App.Console.PrintMessage(f"  Generated {len(shapes)} pieces (caps + dome)\n")
    return shapes, cut_blocks


# =============================================================================
# Slate hip cap generation
# =============================================================================

def generate_slate_hip_caps(shared_edge, face1, face2, params):
    """
    Generate flat rectangular slate tiles straddling the hip/ridge edge.

    Each tile is a flat box of cap_width × cap_height × mat_thick, placed
    perpendicular to the edge and centred on the bisector plane.  Tiles butt
    against each other along the edge (exposure controls spacing).

    Returns (shapes_list, cut_blocks_list).
    """
    cap_width  = params.get('hipCapWidth', params.get('tileWidth', 2.0) * 2.0)
    cap_height = params.get('shingleHeight', 2.5)   # length of each cap along edge
    mat_thick  = params.get('materialThickness', 0.3)
    exposure   = params.get('shingleExposure', cap_height)  # spacing along edge

    validate_exposure(exposure, "generate_slate_hip_caps")

    v0, v1 = shared_edge.Vertexes[0].Point, shared_edge.Vertexes[-1].Point
    start_pt, end_pt = (v0, v1) if v0.z <= v1.z else (v1, v0)
    edge_vec = end_pt - start_pt
    edge_len = edge_vec.Length
    edge_dir = edge_vec * (1.0 / edge_len)

    n1 = _face_normal_at_center(face1)
    n2 = _face_normal_at_center(face2)
    n1_out = n1 * -1.0 if n1.z < 0 else App.Vector(n1.x, n1.y, n1.z)
    n2_out = n2 * -1.0 if n2.z < 0 else App.Vector(n2.x, n2.y, n2.z)

    bisector_raw = n1_out + n2_out
    bisector = bisector_raw * (1.0 / bisector_raw.Length)

    local_x = edge_dir.cross(bisector)
    if local_x.Length < 1e-9:
        local_x = App.Vector(1, 0, 0)
    else:
        local_x = local_x * (1.0 / local_x.Length)
    local_z = bisector

    half_w = cap_width / 2.0

    shapes = []
    for t in calculate_cap_positions(edge_len, exposure):
        pt = start_pt + edge_dir * t
        # Flat rectangle centred on the ridge, lying in the bisector plane
        p0 = pt - local_x * half_w
        p1 = pt + local_x * half_w
        p2 = pt + local_x * half_w + local_z * mat_thick
        p3 = pt - local_x * half_w + local_z * mat_thick
        try:
            wire = Part.Wire([
                Part.makeLine(p0, p1), Part.makeLine(p1, p2),
                Part.makeLine(p2, p3), Part.makeLine(p3, p0),
            ])
            cap = Part.Face(wire).extrude(edge_dir * min(cap_height, edge_len - t))
            if cap.Volume > 1e-6:
                shapes.append(cap)
        except Exception:
            pass

    App.Console.PrintMessage(f"  Generated {len(shapes)} slate hip tiles\n")
    return shapes, []


# =============================================================================
# Metal hip strip generation
# =============================================================================

def generate_metal_hip_strip(shared_edge, face1, face2, params):
    """
    Generate a single continuous metal strip straddling the hip/ridge edge.

    Used for standing seam roofs.  The strip is a flat box of
    cap_width × edge_length × mat_thick, centred on the bisector plane.

    Returns (shapes_list, cut_blocks_list).
    """
    cap_width = params.get('hipCapWidth', params.get('panelWidth', 3.0) * 2.0)
    mat_thick = params.get('materialThickness', 0.15)

    v0, v1 = shared_edge.Vertexes[0].Point, shared_edge.Vertexes[-1].Point
    start_pt, end_pt = (v0, v1) if v0.z <= v1.z else (v1, v0)
    edge_vec = end_pt - start_pt
    edge_len = edge_vec.Length
    edge_dir = edge_vec * (1.0 / edge_len)

    n1 = _face_normal_at_center(face1)
    n2 = _face_normal_at_center(face2)
    n1_out = n1 * -1.0 if n1.z < 0 else App.Vector(n1.x, n1.y, n1.z)
    n2_out = n2 * -1.0 if n2.z < 0 else App.Vector(n2.x, n2.y, n2.z)

    bisector_raw = n1_out + n2_out
    bisector = bisector_raw * (1.0 / bisector_raw.Length)

    local_x = edge_dir.cross(bisector)
    if local_x.Length < 1e-9:
        local_x = App.Vector(1, 0, 0)
    else:
        local_x = local_x * (1.0 / local_x.Length)
    local_z = bisector

    half_w = cap_width / 2.0
    p0 = start_pt - local_x * half_w
    p1 = start_pt + local_x * half_w
    p2 = start_pt + local_x * half_w + local_z * mat_thick
    p3 = start_pt - local_x * half_w + local_z * mat_thick

    try:
        wire = Part.Wire([
            Part.makeLine(p0, p1), Part.makeLine(p1, p2),
            Part.makeLine(p2, p3), Part.makeLine(p3, p0),
        ])
        strip = Part.Face(wire).extrude(edge_dir * edge_len)
        App.Console.PrintMessage(
            f"  Metal hip strip: {cap_width:.2f} × {edge_len:.2f} × {mat_thick:.2f} mm\n")
        return [strip], []
    except Exception as e:
        App.Console.PrintMessage(f"  Metal hip strip failed: {e}\n")
        return [], []


# =============================================================================
# Valley flashing generation
# =============================================================================

def generate_valley_flashing(shared_edge, face1, face2, params):
    """Generate a flat flashing strip along the valley edge."""
    mat_thick   = params.get('materialThickness', 0.25)
    flash_width = params.get('valleyFlashingWidth', mat_thick * 8.0)

    start_pt = shared_edge.Vertexes[0].Point
    end_pt   = shared_edge.Vertexes[-1].Point
    edge_vec = end_pt - start_pt
    edge_len = edge_vec.Length
    edge_dir = edge_vec * (1.0 / edge_len)

    # Normalize both face normals to a consistent outward (+Z) orientation
    # before summing, matching generate_hip_caps/generate_metal_hip_strip
    # in this same file -- this function previously used raw normals, so a
    # locally-inverted Face.Orientation flag (a real, previously-confirmed
    # failure mode on Part::MultiFuse outputs, see freecad_utils.score_
    # face_match's docstring) could silently misplace the flashing (full-
    # review finding #20, 2026-08-08).
    n1 = _face_normal_at_center(face1)
    n2 = _face_normal_at_center(face2)
    n1_out = n1 * -1.0 if n1.z < 0 else App.Vector(n1.x, n1.y, n1.z)
    n2_out = n2 * -1.0 if n2.z < 0 else App.Vector(n2.x, n2.y, n2.z)
    bisector_raw = n1_out + n2_out
    if bisector_raw.Length < 1e-9:
        raise ValueError(
            "Cannot compute valley flashing bisector: face normals are "
            "near-opposite (nearly coplanar faces meeting at a near-180 "
            "degree angle)")
    bisector = bisector_raw * (1.0 / bisector_raw.Length)

    wd_raw = edge_dir.cross(bisector)
    if wd_raw.Length < 1e-9:
        raise ValueError(
            "Cannot compute valley flashing width direction: the shared "
            "edge is parallel to the bisector plane's normal")
    width_dir = wd_raw * (1.0 / wd_raw.Length)

    corner = start_pt - width_dir * (flash_width / 2.0)
    rotation = App.Rotation(_make_rotation_matrix(width_dir, edge_dir, bisector))
    strip = Part.makeBox(flash_width, edge_len, mat_thick)
    strip.Placement = App.Placement(corner, rotation)

    App.Console.PrintMessage(
        f"  Valley flashing: {flash_width:.2f} × {edge_len:.2f} × {mat_thick:.2f} mm\n")
    return [strip]


# =============================================================================
# Combined generation (called from execute)
# =============================================================================

def generate_seam(face1, obj1, face2, obj2, params, doc=None):
    """
    Full seam generation pipeline:
    1. Find shared edge (unwrap ShingledRoof if needed)
    2. Classify hip vs valley
    3. Generate and post-process shapes
    Returns (result_shape, seam_type) or raises on failure.
    """
    shared_edge, face1, obj1, face2, obj2 = resolve_shared_edge(
        face1, obj1, face2, obj2, doc=doc)

    if shared_edge is None:
        raise RuntimeError(
            "No shared edge found between the two faces (or their BaseObjects).\n"
            "Select two adjacent roof faces sharing an edge.")

    App.Console.PrintMessage(
        f"  Shared edge: {shared_edge.Length:.2f} mm\n")

    seam_type = classify_seam(face1, face2, shared_edge)
    App.Console.PrintMessage(f"  Seam type: {seam_type.upper()}\n")

    hip_style = params.get('hipStyle', 'shingle')

    if seam_type == 'hip':
        if hip_style == 'slate':
            shapes, cut_blocks = generate_slate_hip_caps(shared_edge, face1, face2, params)
        elif hip_style == 'metal':
            shapes, cut_blocks = generate_metal_hip_strip(shared_edge, face1, face2, params)
        else:
            shapes, cut_blocks = generate_hip_caps(shared_edge, face1, face2, params)
    else:
        shapes = generate_valley_flashing(shared_edge, face1, face2, params)
        cut_blocks = []

    if not shapes:
        raise RuntimeError("No geometry generated.")

    # Fuse all pieces
    fused = shapes[0]
    for s in shapes[1:]:
        fused = fused.fuse(s)
    try:
        fused = fused.removeSplitter()
    except Exception:
        pass

    # Apply cutting blocks
    if cut_blocks:
        for blk in cut_blocks:
            try:
                result = fused.cut(blk)
                solids = [s for s in result.Solids if s.Volume > 1e-6]
                if solids:
                    fused = solids[0]
                    for s in solids[1:]:
                        fused = fused.fuse(s)
            except Exception:
                pass

    return fused, seam_type


# =============================================================================
# FeaturePython proxy
# =============================================================================

class RoofSeamProxy:
    """Parametric roof seam (hip cap or valley flashing). Change a property → updates."""

    Type = "RoofSeam"

    def __init__(self, obj):
        obj.Proxy = self
        self._setup_properties(obj)

    @staticmethod
    def _setup_properties(obj):
        grp = "RoofSeam"
        if not hasattr(obj, 'Sources'):
            obj.addProperty(
                "App::PropertyLinkSubList", "Sources", grp,
                "Exactly two adjacent roof faces")
        if not hasattr(obj, 'ShingleHeight'):
            obj.addProperty(
                "App::PropertyLength", "ShingleHeight", grp,
                "Cap length along seam (mm)")
        if not hasattr(obj, 'MaterialThickness'):
            obj.addProperty(
                "App::PropertyLength", "MaterialThickness", grp,
                "Material thickness (mm)")
        if not hasattr(obj, 'ShingleExposure'):
            obj.addProperty(
                "App::PropertyLength", "ShingleExposure", grp,
                "Spacing between hip caps (mm)")
        if not hasattr(obj, 'HipCapWidth'):
            obj.addProperty(
                "App::PropertyLength", "HipCapWidth", grp,
                "Total cap width across seam (0 = auto: a fixed per-style "
                "default x2 -- 7.0mm shingle, 4.0mm slate, 6.0mm metal -- "
                "NOT derived from the adjacent roof faces' actual material "
                "width)")
        if not hasattr(obj, 'AngleDepth'):
            obj.addProperty(
                "App::PropertyFloat", "AngleDepth", grp,
                "Taper ratio 0–1 (0.2 = 20% thickness reduction at covered end)")
        if not hasattr(obj, 'ValleyFlashingWidth'):
            obj.addProperty(
                "App::PropertyLength", "ValleyFlashingWidth", grp,
                "Valley flashing width (0 = auto = materialThickness × 8)")
        if not hasattr(obj, 'HipStyle'):
            obj.addProperty(
                "App::PropertyEnumeration", "HipStyle", grp,
                "Hip cap style: shingle (wood), slate (flat tiles), metal (continuous strip)")
            obj.HipStyle = ['shingle', 'slate', 'metal']
        if not hasattr(obj, 'SeamType'):
            obj.addProperty(
                "App::PropertyString", "SeamType", grp,
                "Detected seam type: hip or valley (read-only)")
            obj.setEditorMode("SeamType", 1)
        if not hasattr(obj, 'GeneratorVersion'):
            obj.addProperty(
                "App::PropertyString", "GeneratorVersion", grp,
                "Generator version (read-only)")
            obj.setEditorMode("GeneratorVersion", 1)

    @staticmethod
    def set_defaults(obj, params=None):
        p = params or {}
        obj.ShingleHeight      = p.get('shingleHeight',      2.0)
        obj.MaterialThickness  = p.get('materialThickness',  0.25)
        obj.ShingleExposure    = p.get('shingleExposure',    1.5)
        obj.HipCapWidth        = p.get('hipCapWidth',        0.0)   # 0 = auto
        obj.HipStyle           = p.get('hipStyle',           'shingle')
        obj.AngleDepth         = p.get('angleDepth',         0.2)
        obj.ValleyFlashingWidth = p.get('valleyFlashingWidth', 0.0)  # 0 = auto
        obj.SeamType           = ''
        obj.GeneratorVersion   = VERSION

    def execute(self, obj):
        if not obj.Sources:
            return

        # Flatten Sources → (face, link_obj) pairs
        face_entries = [(face, link_obj) for face, link_obj, _sub_name
                         in resolve_sources_faces(obj.Sources, "RoofSeamProxy")]

        if len(face_entries) != 2:
            App.Console.PrintError(
                f"RoofSeamProxy: need exactly 2 faces, got {len(face_entries)}\n")
            return

        face1, obj1 = face_entries[0]
        face2, obj2 = face_entries[1]

        # Build params dict from properties
        cap_width  = float(obj.HipCapWidth)
        flash_w    = float(obj.ValleyFlashingWidth)
        mat_thick  = float(obj.MaterialThickness)
        params = {
            'shingleHeight':      float(obj.ShingleHeight),
            'materialThickness':  mat_thick,
            'shingleExposure':    float(obj.ShingleExposure),
            'angleDepth':         float(obj.AngleDepth),
            'hipStyle':           str(obj.HipStyle) if hasattr(obj, 'HipStyle') else 'shingle',
        }
        if cap_width > 0:
            params['hipCapWidth'] = cap_width
        # else: 0 = auto -- generate_hip_caps/generate_slate_hip_caps/
        # generate_metal_hip_strip each fall back to their own fixed
        # per-style literal default x2 (7.0/4.0/6.0mm). This proxy never
        # populates a 'shingleWidth'/'tileWidth'/'panelWidth' params key
        # from the adjacent roof faces' actual material, so despite the
        # naming, "auto" does NOT scale to real shingle/tile/panel width
        # (full-review finding #12, 2026-08-08 -- see HipCapWidth's own
        # tooltip, corrected to match this actual behavior).
        if flash_w > 0:
            params['valleyFlashingWidth'] = flash_w

        try:
            doc = obj.Document
            result_shape, seam_type = generate_seam(
                face1, obj1, face2, obj2, params, doc=doc)
            obj.Shape = result_shape
            obj.SeamType = seam_type
            App.Console.PrintMessage(
                f"✓ RoofSeam ({seam_type}) updated\n")
        except Exception as e:
            App.Console.PrintError(f"RoofSeamProxy execute error: {e}\n")

    def dumps(self):
        return {"Type": self.Type}

    def loads(self, state):
        if state:
            self.Type = state.get("Type", "RoofSeam")

    def __getstate__(self):
        return self.dumps()

    def __setstate__(self, state):
        self.loads(state)


class RoofSeamViewProxy:
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
