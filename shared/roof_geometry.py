"""
Roof Geometry Library v1.0.0

Shared pure-Python geometry for all roof-surface generators (shingle, slate,
standing seam, seam caps).  No FreeCAD dependencies — fully testable with pytest.

Extracted from shingle_geometry.py v5.x so that the bug-prone face-orientation
and hip/valley-detection code lives in exactly one place.

Functions
---------
Face geometry
    is_planar
    calculate_face_bounds

Coordinate system (bounding-box method — Z-based, not normal-based)
    find_eave_and_ridge_vertices
    calculate_upslope_direction
    calculate_across_roof_direction
    get_roof_coordinate_system

Hip / valley analysis
    find_coincident_edges
    classify_roof_intersection
    calculate_dihedral_angle
    analyze_roof_intersection

Coursed-tile layout helpers (generic — no slate-specific content)
    is_valid_clip_fragment
    is_top_course_complete
    calculate_fitted_exposure
"""

import math
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Face geometry helpers
# ---------------------------------------------------------------------------

def is_planar(points: List[Tuple[float, float, float]],
              tolerance: float = 0.01) -> bool:
    """Return True if *points* are coplanar within *tolerance* mm."""
    if len(points) < 4:
        return True

    p0 = points[0]
    normal = None
    for i in range(1, len(points) - 1):
        v1 = (points[i][0]-p0[0], points[i][1]-p0[1], points[i][2]-p0[2])
        v2 = (points[i+1][0]-p0[0], points[i+1][1]-p0[1], points[i+1][2]-p0[2])
        n = (
            v1[1]*v2[2] - v1[2]*v2[1],
            v1[2]*v2[0] - v1[0]*v2[2],
            v1[0]*v2[1] - v1[1]*v2[0],
        )
        norm_len = math.sqrt(n[0]**2 + n[1]**2 + n[2]**2)
        if norm_len >= 0.001:
            normal = (n[0]/norm_len, n[1]/norm_len, n[2]/norm_len)
            break

    if normal is None:
        return False

    plane_d = -(normal[0]*p0[0] + normal[1]*p0[1] + normal[2]*p0[2])
    for pt in points:
        dist = abs(normal[0]*pt[0] + normal[1]*pt[1] + normal[2]*pt[2] + plane_d)
        if dist > tolerance:
            return False
    return True


def calculate_face_bounds(points: List[Tuple[float, float, float]]) -> Dict:
    """Return axis-aligned bounding box dict for *points*."""
    if not points:
        raise ValueError("Cannot calculate bounds from empty point list")
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return {
        'x_min': min(xs), 'x_max': max(xs),
        'y_min': min(ys), 'y_max': max(ys),
        'z_min': min(zs), 'z_max': max(zs),
    }


# ---------------------------------------------------------------------------
# Coordinate system — bounding-box (Z-based) method
# ---------------------------------------------------------------------------

def find_eave_and_ridge_vertices(
        vertices: List[Tuple[float, float, float]],
        z_tolerance: float = 0.1) -> Dict:
    """
    Find eave (lowest Z) and ridge (highest Z) vertices of a roof face.

    Uses vertex Z coordinates — not face normals — so the result is
    geometrically unambiguous regardless of how the solid was constructed.

    Returns dict with keys: eave_vertices, ridge_vertices, eave_z, ridge_z,
    eave_center, ridge_center, slope_rise.
    """
    if not vertices:
        raise ValueError("Cannot find eave/ridge from empty vertex list")

    z_coords = [v[2] for v in vertices]
    z_min, z_max = min(z_coords), max(z_coords)

    eave_verts  = [v for v in vertices if abs(v[2] - z_min) <= z_tolerance]
    ridge_verts = [v for v in vertices if abs(v[2] - z_max) <= z_tolerance]

    def _centroid(verts):
        n = len(verts)
        return (sum(v[0] for v in verts)/n,
                sum(v[1] for v in verts)/n,
                sum(v[2] for v in verts)/n)

    return {
        'eave_vertices':  eave_verts,
        'ridge_vertices': ridge_verts,
        'eave_z':         z_min,
        'ridge_z':        z_max,
        'eave_center':    _centroid(eave_verts),
        'ridge_center':   _centroid(ridge_verts),
        'slope_rise':     z_max - z_min,
    }


def calculate_upslope_direction(
        vertices: List[Tuple[float, float, float]],
        z_tolerance: float = 0.1) -> Tuple[float, float, float]:
    """Return unit vector pointing from eave toward ridge (up the slope)."""
    info = find_eave_and_ridge_vertices(vertices, z_tolerance)
    eave, ridge = info['eave_center'], info['ridge_center']
    dx, dy, dz = ridge[0]-eave[0], ridge[1]-eave[1], ridge[2]-eave[2]
    length = math.sqrt(dx*dx + dy*dy + dz*dz)
    if length < 0.001:
        return (0, 0, 1)
    return (dx/length, dy/length, dz/length)


def calculate_across_roof_direction(
        vertices: List[Tuple[float, float, float]],
        upslope: Tuple[float, float, float],
        face_normal: Tuple[float, float, float],
        eave_vertices: Optional[List[Tuple[float, float, float]]] = None,
) -> Tuple[float, float, float]:
    """
    Return unit vector pointing across the roof (parallel to the eave edge).

    Prefers the actual eave-edge direction when two or more eave vertices are
    available; falls back to the cross-product method for degenerate cases.
    """
    if eave_vertices and len(eave_vertices) >= 2:
        max_dist, best_pair = 0.0, (eave_vertices[0], eave_vertices[1])
        for i, v1 in enumerate(eave_vertices):
            for v2 in eave_vertices[i+1:]:
                dx, dy, dz = v2[0]-v1[0], v2[1]-v1[1], v2[2]-v1[2]
                dist = math.sqrt(dx*dx + dy*dy + dz*dz)
                if dist > max_dist:
                    max_dist = dist
                    best_pair = (v1, v2)

        if max_dist > 0.001:
            v1, v2 = best_pair
            ux, uy, uz = v2[0]-v1[0], v2[1]-v1[1], v2[2]-v1[2]
            length = math.sqrt(ux*ux + uy*uy + uz*uz)
            if length > 0.001:
                u = (ux/length, uy/length, uz/length)
                abs_x, abs_y = abs(u[0]), abs(u[1])
                if abs_y >= abs_x:
                    if u[1] < 0:
                        u = (-u[0], -u[1], -u[2])
                else:
                    if u[0] < 0:
                        u = (-u[0], -u[1], -u[2])
                return u

    # Fallback: cross product of normal × upslope
    ux = face_normal[1]*upslope[2] - face_normal[2]*upslope[1]
    uy = face_normal[2]*upslope[0] - face_normal[0]*upslope[2]
    uz = face_normal[0]*upslope[1] - face_normal[1]*upslope[0]
    length = math.sqrt(ux*ux + uy*uy + uz*uz)
    if length < 0.001:
        return (1, 0, 0)
    return (ux/length, uy/length, uz/length)


def get_roof_coordinate_system(
        vertices: List[Tuple[float, float, float]],
        face_normal: Tuple[float, float, float],
        z_tolerance: float = 0.1) -> Dict:
    """
    Build a complete right-handed coordinate system for a roof face.

    Returns dict with keys: origin, u_vec, v_vec, normal, eave_ridge_info.

    u_vec  — across the roof (along eave)
    v_vec  — up the slope (eave → ridge), orthogonalised via N×U
    normal — face outward normal (caller must ensure positive-Z before calling)
    origin — first eave vertex (caller refines to corner with minimum U projection)

    CRITICAL: v_vec is derived as N×U (not raw upslope) so the grid is
    guaranteed orthogonal even on triangular hip faces where the ridge
    vertex is offset along the eave direction.
    """
    if len(vertices) < 3:
        raise ValueError(f"Need at least 3 vertices, got {len(vertices)}")

    eave_ridge = find_eave_and_ridge_vertices(vertices, z_tolerance)
    upslope = calculate_upslope_direction(vertices, z_tolerance)
    u_vec = calculate_across_roof_direction(
        vertices, upslope, face_normal,
        eave_vertices=eave_ridge['eave_vertices'])

    # Orthogonalise V = N × U (guaranteed perpendicular)
    v_vec = (
        face_normal[1]*u_vec[2] - face_normal[2]*u_vec[1],
        face_normal[2]*u_vec[0] - face_normal[0]*u_vec[2],
        face_normal[0]*u_vec[1] - face_normal[1]*u_vec[0],
    )
    v_len = math.sqrt(v_vec[0]**2 + v_vec[1]**2 + v_vec[2]**2)
    v_vec = (v_vec[0]/v_len, v_vec[1]/v_len, v_vec[2]/v_len) if v_len > 0.001 else upslope

    # Ensure V points upslope.
    # On diagonal hip faces the upslope vector can be perpendicular to N×U
    # (dot ≈ 0). Fall back to requiring positive Z in that case — a real roof
    # slope always has a non-negative world-Z component for V.
    dot_up = v_vec[0]*upslope[0] + v_vec[1]*upslope[1] + v_vec[2]*upslope[2]
    if dot_up < 0 or (abs(dot_up) < 0.001 and v_vec[2] < 0):
        v_vec = (-v_vec[0], -v_vec[1], -v_vec[2])

    # Verify handedness: U×V must agree with face_normal
    cross = (
        u_vec[1]*v_vec[2] - u_vec[2]*v_vec[1],
        u_vec[2]*v_vec[0] - u_vec[0]*v_vec[2],
        u_vec[0]*v_vec[1] - u_vec[1]*v_vec[0],
    )
    dot = face_normal[0]*cross[0] + face_normal[1]*cross[1] + face_normal[2]*cross[2]
    if dot < 0:
        u_vec = (-u_vec[0], -u_vec[1], -u_vec[2])

    origin = eave_ridge['eave_vertices'][0] if eave_ridge['eave_vertices'] else vertices[0]

    return {
        'origin':         origin,
        'u_vec':          u_vec,
        'v_vec':          v_vec,
        'normal':         face_normal,
        'eave_ridge_info': eave_ridge,
    }


# ---------------------------------------------------------------------------
# Hip / valley intersection analysis
# ---------------------------------------------------------------------------

def find_coincident_edges(
        face1_edges: List[Tuple[Tuple[float,float,float], Tuple[float,float,float]]],
        face2_edges: List[Tuple[Tuple[float,float,float], Tuple[float,float,float]]],
        tolerance: float = 0.5) -> List[Dict]:
    """Return list of dicts describing edges shared between two faces."""

    def _pts_close(p1, p2):
        dx, dy, dz = p1[0]-p2[0], p1[1]-p2[1], p1[2]-p2[2]
        return math.sqrt(dx*dx+dy*dy+dz*dz) <= tolerance

    def _edges_match(e1, e2):
        return ((_pts_close(e1[0],e2[0]) and _pts_close(e1[1],e2[1])) or
                (_pts_close(e1[0],e2[1]) and _pts_close(e1[1],e2[0])))

    result = []
    for e1 in face1_edges:
        for e2 in face2_edges:
            if _edges_match(e1, e2):
                mid = ((e1[0][0]+e1[1][0])/2,
                       (e1[0][1]+e1[1][1])/2,
                       (e1[0][2]+e1[1][2])/2)
                dx, dy, dz = e1[1][0]-e1[0][0], e1[1][1]-e1[0][1], e1[1][2]-e1[0][2]
                result.append({'edge1': e1, 'edge2': e2, 'midpoint': mid,
                                'length': math.sqrt(dx*dx+dy*dy+dz*dz)})
    return result


def classify_roof_intersection(
        face1_vertices: List[Tuple[float,float,float]],
        face2_vertices: List[Tuple[float,float,float]],
        shared_edge: Tuple[Tuple[float,float,float], Tuple[float,float,float]],
        z_tolerance: float = 0.1) -> Dict:
    """
    Classify an intersection as 'valley', 'ridge', or 'ambiguous'.

    Key insight:
    - Non-shared vertices BELOW shared edge → RIDGE / HIP
    - Non-shared vertices ABOVE shared edge → VALLEY
    """
    edge_z = (shared_edge[0][2] + shared_edge[1][2]) / 2.0

    def _on_edge(vertex, edge, tol):
        for ep in edge:
            dx, dy, dz = vertex[0]-ep[0], vertex[1]-ep[1], vertex[2]-ep[2]
            if math.sqrt(dx*dx+dy*dy+dz*dz) <= tol:
                return True
        return False

    f1_other = [v for v in face1_vertices if not _on_edge(v, shared_edge, z_tolerance*5)]
    f2_other = [v for v in face2_vertices if not _on_edge(v, shared_edge, z_tolerance*5)]

    if not f1_other or not f2_other:
        return {'classification': 'ambiguous', 'shared_edge_z': edge_z,
                'face1_other_z': None, 'face2_other_z': None,
                'confidence': 'low', 'reason': 'Could not identify non-shared vertices'}

    f1z = sum(v[2] for v in f1_other) / len(f1_other)
    f2z = sum(v[2] for v in f2_other) / len(f2_other)

    f1_below = f1z < edge_z - z_tolerance
    f1_above = f1z > edge_z + z_tolerance
    f2_below = f2z < edge_z - z_tolerance
    f2_above = f2z > edge_z + z_tolerance

    if f1_below and f2_below:
        cls, conf = 'ridge', 'high'
    elif f1_above and f2_above:
        cls, conf = 'valley', 'high'
    elif (f1_below and f2_above) or (f1_above and f2_below):
        cls, conf = 'ambiguous', 'low'
    else:
        cls, conf = 'ambiguous', 'medium'

    return {'classification': cls, 'shared_edge_z': edge_z,
            'face1_other_z': f1z, 'face2_other_z': f2z, 'confidence': conf}


def calculate_dihedral_angle(
        face1_normal: Tuple[float,float,float],
        face2_normal: Tuple[float,float,float]) -> Dict:
    """Return dihedral angle info between two face normals."""
    dot = max(-1.0, min(1.0,
        face1_normal[0]*face2_normal[0] +
        face1_normal[1]*face2_normal[1] +
        face1_normal[2]*face2_normal[2]))
    angle_rad = math.acos(dot)
    angle_deg = math.degrees(angle_rad)
    return {
        'angle_degrees':      angle_deg,
        'angle_radians':      angle_rad,
        'trim_angle_degrees': angle_deg / 2.0,
    }


def analyze_roof_intersection(
        face1_vertices, face1_normal, face1_edges,
        face2_vertices, face2_normal, face2_edges,
        tolerance: float = 0.5) -> Dict:
    """
    Full pipeline: find shared edge → classify hip/valley → compute dihedral angle.

    Returns dict with has_shared_edge, shared_edges, classification,
    classification_details, dihedral_angle, trim_recommendation.
    """
    shared = find_coincident_edges(face1_edges, face2_edges, tolerance)

    if not shared:
        return {'has_shared_edge': False, 'shared_edges': [],
                'classification': 'none', 'dihedral_angle': None,
                'trim_recommendation': 'Faces do not share an edge'}

    longest = max(shared, key=lambda e: e['length'])
    cls = classify_roof_intersection(
        face1_vertices, face2_vertices, longest['edge1'], tolerance)
    dihedral = calculate_dihedral_angle(face1_normal, face2_normal)

    if cls['classification'] == 'valley':
        rec = f"VALLEY: Cut at {dihedral['trim_angle_degrees']:.1f}° from each side"
    elif cls['classification'] == 'ridge':
        rec = f"RIDGE/HIP: Cut at {dihedral['trim_angle_degrees']:.1f}° from each side"
    else:
        rec = f"AMBIGUOUS: Dihedral {dihedral['angle_degrees']:.1f}°, verify visually"

    return {
        'has_shared_edge':       True,
        'shared_edges':          shared,
        'classification':        cls['classification'],
        'classification_details': cls,
        'dihedral_angle':        dihedral,
        'trim_recommendation':   rec,
    }


# ---------------------------------------------------------------------------
# Coursed-tile layout helpers (generic — no slate-specific content)
#
# Originally developed in slate_generator/slate_geometry.py (2026-07-29, in
# response to a real production bug); relocated here because they apply to
# any coursed roof-surface generator (shingle, slate, slate-seam caps,
# standing seam) that overlaps discrete elements along an axis and must
# clip/rack them against a hard boundary. slate_generator/slate_geometry.py
# re-exports these unchanged rather than duplicating them.
# ---------------------------------------------------------------------------

def is_valid_clip_fragment(fragment_volume: float, full_volume: float,
                            min_fraction: float = 0.05) -> bool:
    """Decide whether a clipped tile fragment is real geometry or a
    razor-thin sliver that should be discarded.

    A proxy typically over-generates courses (e.g. +3 beyond what's
    needed) to guarantee full ridge/hip coverage, then clips each tile
    against a boundary. A fixed absolute volume threshold (e.g. `> 0.001`)
    doesn't scale with tile size: on a real hip roof (2026-07-29) it let
    0.02 mm^3 slivers survive as stray fragments -- about 1% of a 1.8 mm^3
    full tile -- visible as a spurious extra edge right at the ridge/hip
    line. Scaling the threshold to a fraction of the *same tile's own
    pre-clip volume* stays correct at any tile size.

    full_volume <= 0 is degenerate (a null/zero-volume source shape) and
    always returns False -- there's no meaningful fraction of nothing.
    """
    if full_volume <= 0:
        return False
    return fragment_volume > full_volume * min_fraction


def is_top_course_complete(course_head_v: float, face_v_length: float) -> bool:
    """Return True if a course's head (its upper, up-slope edge, at
    V=course_head_v in the face's own coordinate system) sits at or below
    the face's own top edge (the ridge/hip line, at V=face_v_length) --
    i.e. this course needs no clipping at the top boundary at all.

    False means the ridge/hip line cuts through this course somewhere
    between its butt and head, producing a partial fragment there --
    anywhere from a normal-looking partial course down to the razor-thin
    sliver is_valid_clip_fragment exists to catch. Used by an optional
    "hide incomplete top course" proxy property to skip such a course
    entirely (never generate it) rather than generate-then-clip-then-maybe-discard.
    """
    return course_head_v <= face_v_length


def calculate_fitted_exposure(face_v_length: float, nominal_exposure: float) -> float:
    """Adjust exposure so an integer number of courses exactly spans
    face_v_length, instead of leaving a remainder that produces either a
    gap (hide-incomplete-course) or a clipped partial/sliver fragment at
    the ridge/hip line.

    This mirrors how a slater "racks" a course run: exposure (equivalently
    headlap/overlap, since overlap = tile_height - exposure for a fixed
    tile_height) is nudged uniformly across every course rather than
    leaving one oddly-sized course at the top. For a face with many
    courses the adjustment is a small fraction of nominal_exposure; for a
    face with very few courses it can be a much larger fraction (a
    2-course run has at most +/-25% to work with) -- that's an inherent
    property of racking with few courses, not a bug, and matches the
    constraint a real installer would face too.

    Rounds to the NEAREST whole course count (ties round to even, per
    Python's round()) rather than always up or down -- a real slater
    picks whichever nearby count gives the smaller deviation from the
    nominal exposure, and it's equally normal to end up very slightly
    tighter or very slightly looser than asked for.

    Degenerate inputs (nominal_exposure <= 0, face_v_length <= 0) return
    nominal_exposure unchanged -- there's no meaningful "fit" to compute,
    and returning the input keeps the caller's existing
    validation/error path in control rather than this function silently
    producing a nonsensical result.
    """
    if nominal_exposure <= 0 or face_v_length <= 0:
        return nominal_exposure

    num_courses = round(face_v_length / nominal_exposure)
    if num_courses < 1:
        num_courses = 1

    return face_v_length / num_courses
