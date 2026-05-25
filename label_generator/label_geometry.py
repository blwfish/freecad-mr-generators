"""label_geometry.py — Pure-Python placement and sizing helpers for the label generator.

No FreeCAD imports. All vectors are plain (x, y, z) tuples.
"""

import math


# ---------------------------------------------------------------------------
# Internal vector helpers
# ---------------------------------------------------------------------------

def _dot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


def _cross(a, b):
    return (
        a[1]*b[2] - a[2]*b[1],
        a[2]*b[0] - a[0]*b[2],
        a[0]*b[1] - a[1]*b[0],
    )


def _normalize(v):
    length = math.sqrt(_dot(v, v))
    if length < 1e-12:
        raise ValueError(f"Cannot normalize zero-length vector {v}")
    return (v[0]/length, v[1]/length, v[2]/length)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def orthonormal_frame(normal):
    """
    Return (x_axis, y_axis) as (x, y, z) tuples forming a right-handed
    orthonormal frame with the given unit normal as the Z axis.

    Selects the reference vector to cross against normal as the standard basis
    vector least parallel to normal, minimising numerical error.
    """
    nx, ny, nz = normal
    norm_len = math.sqrt(nx*nx + ny*ny + nz*nz)
    if abs(norm_len - 1.0) > 1e-6:
        raise ValueError(f"normal must be a unit vector; got |normal|={norm_len:.8f}")

    abs_n = (abs(nx), abs(ny), abs(nz))
    if abs_n[0] <= abs_n[1] and abs_n[0] <= abs_n[2]:
        ref = (1.0, 0.0, 0.0)
    elif abs_n[1] <= abs_n[2]:
        ref = (0.0, 1.0, 0.0)
    else:
        ref = (0.0, 0.0, 1.0)

    x_axis = _normalize(_cross(ref, normal))
    y_axis = _normalize(_cross(normal, x_axis))
    return x_axis, y_axis


def rotate_in_plane(x_axis, y_axis, angle_deg):
    """
    Rotate (x_axis, y_axis) by angle_deg degrees CCW around the face normal
    (i.e. within the face plane).

    Returns (new_x_axis, new_y_axis) as (x, y, z) tuples.
    """
    cos_a = math.cos(math.radians(angle_deg))
    sin_a = math.sin(math.radians(angle_deg))
    new_x = (
        cos_a * x_axis[0] + sin_a * y_axis[0],
        cos_a * x_axis[1] + sin_a * y_axis[1],
        cos_a * x_axis[2] + sin_a * y_axis[2],
    )
    new_y = (
        -sin_a * x_axis[0] + cos_a * y_axis[0],
        -sin_a * x_axis[1] + cos_a * y_axis[1],
        -sin_a * x_axis[2] + cos_a * y_axis[2],
    )
    return new_x, new_y


def compute_font_size(text_w, text_h, face_w, face_h, padding):
    """
    Return the largest font size (as a scale from unit-size text) that fits
    text of (text_w, text_h) within (face_w - 2*padding) × (face_h - 2*padding).

    text_w, text_h: text bounding-box dimensions at font_size=1 (mm)
    face_w, face_h: face dimensions (mm)
    padding:        margin deducted from each side (mm); total removal = 2*padding per axis

    Raises ValueError if the usable area is non-positive.
    """
    if text_w <= 0 or text_h <= 0:
        raise ValueError(f"text dimensions must be positive; got ({text_w}, {text_h})")
    usable_w = face_w - 2.0 * padding
    usable_h = face_h - 2.0 * padding
    if usable_w <= 0.0:
        raise ValueError(
            f"face width {face_w} too small for padding {padding} per side "
            f"(usable_w={usable_w:.6f})"
        )
    if usable_h <= 0.0:
        raise ValueError(
            f"face height {face_h} too small for padding {padding} per side "
            f"(usable_h={usable_h:.6f})"
        )
    return min(usable_w / text_w, usable_h / text_h)


def build_frame_matrix(center_xyz, normal_xyz, x_axis_xyz, rotation_deg):
    """
    Return a 4×4 placement matrix as a list of 4 rows (each a list of 4 floats)
    that maps local XYZ (text in XY plane, extruded in +Z) to world space.

    center_xyz:   (x, y, z) — face center in world coords (translation column)
    normal_xyz:   (x, y, z) — face outward unit normal  (local +Z maps here)
    x_axis_xyz:   (x, y, z) — face u-direction (unit)  (local +X before rotation)
    rotation_deg: float — extra CCW rotation around normal in face plane

    The returned matrix is in row-major order:
        row[i][j] == FreeCAD Matrix A{i+1}{j+1}

    Columns of the rotation sub-matrix are the images of the local basis vectors
    in world space:
        col 0 → rotated x_axis  (local +X)
        col 1 → rotated y_axis  (local +Y)
        col 2 → normal          (local +Z)
        col 3 → center          (translation)
    """
    y_axis = _normalize(_cross(normal_xyz, x_axis_xyz))
    x_ax, y_ax = rotate_in_plane(x_axis_xyz, y_axis, rotation_deg)
    nx, ny, nz = normal_xyz
    tx, ty, tz = center_xyz
    return [
        [x_ax[0], y_ax[0], nx, tx],
        [x_ax[1], y_ax[1], ny, ty],
        [x_ax[2], y_ax[2], nz, tz],
        [0.0,     0.0,     0.0, 1.0],
    ]
