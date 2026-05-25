"""Tests for label_geometry.py.

Testing rules applied (per CLAUDE.md):
  - At/below/above for every numeric threshold
  - Exact-multiple / zero-remainder / near-zero cases
  - Downstream-consumer invariants: matrix orthonormality, translation fidelity
  - At least one parameter set drawn from real intended use (3D-print label)
"""

import math
import pytest

from label_geometry import (
    orthonormal_frame,
    rotate_in_plane,
    compute_font_size,
    build_frame_matrix,
    _dot,
    _cross,
    _normalize,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def approx_tuple(t, expected, abs=1e-9):
    for a, b in zip(t, expected):
        assert a == pytest.approx(b, abs=abs), f"{t} ≠ {expected}"


def is_unit(v, tol=1e-9):
    return abs(math.sqrt(sum(x*x for x in v)) - 1.0) < tol


def is_orthogonal(a, b, tol=1e-9):
    return abs(_dot(a, b)) < tol


def is_right_handed(x, y, z, tol=1e-9):
    """x × y should equal z (up to tol)."""
    cross = _cross(x, y)
    return all(abs(cross[i] - z[i]) < tol for i in range(3))


# ---------------------------------------------------------------------------
# orthonormal_frame
# ---------------------------------------------------------------------------

class TestOrthonormalFrame:
    @pytest.mark.parametrize("normal", [
        (0.0, 0.0, 1.0),   # +Z — axis-aligned
        (0.0, 0.0, -1.0),  # -Z
        (1.0, 0.0, 0.0),   # +X
        (0.0, 1.0, 0.0),   # +Y
        (-1.0, 0.0, 0.0),  # -X
    ])
    def test_axis_aligned_normals(self, normal):
        x, y = orthonormal_frame(normal)
        assert is_unit(x), f"x_axis not unit for normal={normal}"
        assert is_unit(y), f"y_axis not unit for normal={normal}"
        assert is_orthogonal(x, y), f"x, y not orthogonal for normal={normal}"
        assert is_orthogonal(x, normal), f"x, normal not orthogonal for normal={normal}"
        assert is_orthogonal(y, normal), f"y, normal not orthogonal for normal={normal}"

    def test_diagonal_normal(self):
        """45-degree normal — the least-parallel-axis selection should still work."""
        s = 1.0 / math.sqrt(3)
        normal = (s, s, s)
        x, y = orthonormal_frame(normal)
        assert is_unit(x)
        assert is_unit(y)
        assert is_orthogonal(x, y)
        assert is_orthogonal(x, normal)
        assert is_right_handed(x, y, normal)

    @pytest.mark.parametrize("normal", [
        (0.0, 0.0, 1.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
    ])
    def test_right_handed_frame(self, normal):
        x, y = orthonormal_frame(normal)
        assert is_right_handed(x, y, normal), \
            f"Frame is not right-handed for normal={normal}"

    def test_rejects_non_unit_normal(self):
        with pytest.raises(ValueError, match="unit vector"):
            orthonormal_frame((1.0, 1.0, 0.0))  # length = sqrt(2)

    def test_rejects_zero_vector(self):
        with pytest.raises(ValueError, match="unit vector"):
            orthonormal_frame((0.0, 0.0, 0.0))

    def test_near_axis_boundary(self):
        """Normal almost exactly along Z — should not degenerate."""
        eps = 1e-7
        n = _normalize((eps, eps, 1.0))
        x, y = orthonormal_frame(n)
        assert is_unit(x, tol=1e-6)
        assert is_unit(y, tol=1e-6)

    def test_real_model_face_normal(self):
        """Typical HO-scale building wall face normal (slightly off-vertical)."""
        n = _normalize((0.0, -1.0, 0.0))  # south-facing vertical wall
        x, y = orthonormal_frame(n)
        assert is_unit(x)
        assert is_unit(y)
        assert is_orthogonal(x, n)


# ---------------------------------------------------------------------------
# rotate_in_plane
# ---------------------------------------------------------------------------

class TestRotateInPlane:
    def test_zero_rotation(self):
        x = (1.0, 0.0, 0.0)
        y = (0.0, 1.0, 0.0)
        nx, ny = rotate_in_plane(x, y, 0.0)
        approx_tuple(nx, x)
        approx_tuple(ny, y)

    def test_90_degree_rotation(self):
        """Rotate 90° CCW: X→Y, Y→-X."""
        x = (1.0, 0.0, 0.0)
        y = (0.0, 1.0, 0.0)
        nx, ny = rotate_in_plane(x, y, 90.0)
        approx_tuple(nx, (0.0, 1.0, 0.0))
        approx_tuple(ny, (-1.0, 0.0, 0.0))

    def test_180_degree_rotation(self):
        x = (1.0, 0.0, 0.0)
        y = (0.0, 1.0, 0.0)
        nx, ny = rotate_in_plane(x, y, 180.0)
        approx_tuple(nx, (-1.0, 0.0, 0.0))
        approx_tuple(ny, (0.0, -1.0, 0.0))

    def test_270_degree_rotation(self):
        """270° CCW = 90° CW: X→-Y, Y→X."""
        x = (1.0, 0.0, 0.0)
        y = (0.0, 1.0, 0.0)
        nx, ny = rotate_in_plane(x, y, 270.0)
        approx_tuple(nx, (0.0, -1.0, 0.0))
        approx_tuple(ny, (1.0, 0.0, 0.0))

    def test_orthonormality_preserved(self):
        """Arbitrary rotation must keep the pair orthonormal."""
        x = (1.0, 0.0, 0.0)
        y = (0.0, 1.0, 0.0)
        for angle in (15.0, 37.0, 90.0, 135.0, 200.0):
            nx, ny = rotate_in_plane(x, y, angle)
            assert is_unit(nx, tol=1e-9), f"nx not unit at {angle}°"
            assert is_unit(ny, tol=1e-9), f"ny not unit at {angle}°"
            assert is_orthogonal(nx, ny, tol=1e-9), f"nx,ny not orthogonal at {angle}°"

    def test_3d_axes(self):
        """Works in 3D face planes too."""
        n = _normalize((0.0, -1.0, 0.0))
        x, y = orthonormal_frame(n)
        nx, ny = rotate_in_plane(x, y, 45.0)
        assert is_unit(nx, tol=1e-9)
        assert is_unit(ny, tol=1e-9)
        assert is_orthogonal(nx, ny, tol=1e-9)
        assert is_orthogonal(nx, n, tol=1e-9)


# ---------------------------------------------------------------------------
# compute_font_size
# ---------------------------------------------------------------------------

class TestComputeFontSize:
    # --- Basic scaling ---

    def test_width_limited(self):
        """Text wider than tall → width constrains the size."""
        # text 5×1 at size 1, face 10×10, no padding
        size = compute_font_size(5.0, 1.0, 10.0, 10.0, 0.0)
        assert size == pytest.approx(2.0, abs=1e-9)

    def test_height_limited(self):
        """Text taller than wide → height constrains the size."""
        size = compute_font_size(1.0, 5.0, 10.0, 10.0, 0.0)
        assert size == pytest.approx(2.0, abs=1e-9)

    def test_square_text_square_face_no_padding(self):
        size = compute_font_size(1.0, 1.0, 8.0, 8.0, 0.0)
        assert size == pytest.approx(8.0, abs=1e-9)

    # --- Padding thresholds ---

    def test_padding_zero(self):
        size = compute_font_size(2.0, 1.0, 10.0, 5.0, 0.0)
        assert size == pytest.approx(5.0, abs=1e-9)  # min(10/2, 5/1) = 5

    def test_padding_just_below_half_face_width(self):
        """padding=4.999 on a face_w=10 → usable_w=0.002 (positive, valid)."""
        size = compute_font_size(1.0, 0.001, 10.0, 10.0, 4.999)
        assert size > 0

    def test_padding_exactly_half_face_width_raises(self):
        """padding=5.0 on face_w=10 → usable_w=0 → ValueError."""
        with pytest.raises(ValueError, match="too small"):
            compute_font_size(1.0, 1.0, 10.0, 10.0, 5.0)

    def test_padding_above_half_face_width_raises(self):
        with pytest.raises(ValueError, match="too small"):
            compute_font_size(1.0, 1.0, 10.0, 10.0, 5.001)

    def test_padding_just_below_half_face_height_raises(self):
        """Padding too large for height but OK for width."""
        with pytest.raises(ValueError, match="too small"):
            compute_font_size(1.0, 1.0, 100.0, 10.0, 5.0)

    # --- Text dimension edge cases ---

    def test_very_wide_text_minimal_height(self):
        """Extremely wide text: height drives the size to something tiny."""
        size = compute_font_size(100.0, 0.1, 10.0, 10.0, 0.0)
        assert size == pytest.approx(0.1, abs=1e-9)  # min(10/100, 10/0.1)=0.1

    def test_text_w_zero_raises(self):
        with pytest.raises(ValueError, match="positive"):
            compute_font_size(0.0, 1.0, 10.0, 10.0, 0.0)

    def test_text_h_zero_raises(self):
        with pytest.raises(ValueError, match="positive"):
            compute_font_size(1.0, 0.0, 10.0, 10.0, 0.0)

    def test_text_w_negative_raises(self):
        with pytest.raises(ValueError, match="positive"):
            compute_font_size(-1.0, 1.0, 10.0, 10.0, 0.0)

    # --- Real-model parameter set ---

    def test_real_label_3mm_high_face(self):
        """
        Real use-case: 3mm-high face (edge label on a 1.6mm-thick wall).
        Text "A" at size=1 is roughly 0.7×0.7 mm in Arial Bold.
        With padding=0.5mm each side: usable = 3mm - 1mm = 2mm.
        Expected: font_size ≈ 2/0.7 ≈ 2.86.
        """
        text_w, text_h = 0.7, 0.7
        face_w, face_h = 30.0, 3.0
        padding = 0.5
        size = compute_font_size(text_w, text_h, face_w, face_h, padding)
        # height-limited: (3 - 2*0.5) / 0.7 = 2/0.7 ≈ 2.857
        assert size == pytest.approx(2.0 / 0.7, abs=1e-6)
        # Verify the computed size actually fits
        assert text_w * size <= face_w - 2 * padding + 1e-9
        assert text_h * size <= face_h - 2 * padding + 1e-9


# ---------------------------------------------------------------------------
# build_frame_matrix
# ---------------------------------------------------------------------------

class TestBuildFrameMatrix:

    def _apply(self, rows, local_pt):
        """Multiply 4×4 matrix by a local point (x,y,z) → world (x,y,z)."""
        x, y, z = local_pt
        wx = rows[0][0]*x + rows[0][1]*y + rows[0][2]*z + rows[0][3]
        wy = rows[1][0]*x + rows[1][1]*y + rows[1][2]*z + rows[1][3]
        wz = rows[2][0]*x + rows[2][1]*y + rows[2][2]*z + rows[2][3]
        return (wx, wy, wz)

    def test_local_z_maps_to_normal(self):
        """Local +Z should map to the face normal (translation-free part)."""
        normal = (0.0, 0.0, 1.0)
        center = (5.0, 5.0, 2.0)
        x_ax, _ = orthonormal_frame(normal)
        rows = build_frame_matrix(center, normal, x_ax, 0.0)
        # Local (0,0,1) in world = center + normal
        world = self._apply(rows, (0.0, 0.0, 1.0))
        approx_tuple(world, (center[0] + normal[0],
                             center[1] + normal[1],
                             center[2] + normal[2]))

    def test_local_origin_maps_to_center(self):
        center = (3.0, -4.0, 7.0)
        normal = (0.0, 1.0, 0.0)
        x_ax, _ = orthonormal_frame(normal)
        rows = build_frame_matrix(center, normal, x_ax, 0.0)
        world = self._apply(rows, (0.0, 0.0, 0.0))
        approx_tuple(world, center)

    def test_rotation_matrix_is_orthonormal(self):
        """Columns 0-2 of the rotation part should be orthonormal."""
        normal = _normalize((1.0, 1.0, 0.0))
        center = (0.0, 0.0, 0.0)
        x_ax, _ = orthonormal_frame(normal)
        rows = build_frame_matrix(center, normal, x_ax, 37.0)
        cols = [tuple(rows[r][c] for r in range(3)) for c in range(3)]
        for i, col in enumerate(cols):
            assert is_unit(col, tol=1e-9), f"column {i} not unit"
        for i in range(3):
            for j in range(i + 1, 3):
                assert is_orthogonal(cols[i], cols[j], tol=1e-9), \
                    f"columns {i} and {j} not orthogonal"

    def test_column3_is_normal(self):
        """Third rotation column (index 2) must equal the face normal."""
        normal = (0.0, 0.0, 1.0)
        center = (0.0, 0.0, 0.0)
        x_ax, _ = orthonormal_frame(normal)
        rows = build_frame_matrix(center, normal, x_ax, 0.0)
        col2 = tuple(rows[r][2] for r in range(3))
        approx_tuple(col2, normal)

    def test_zero_rotation_identity_axes(self):
        """For +Z normal, 0° rotation: local X should map to the x_axis."""
        normal = (0.0, 0.0, 1.0)
        center = (0.0, 0.0, 0.0)
        x_ax, _ = orthonormal_frame(normal)
        rows = build_frame_matrix(center, normal, x_ax, 0.0)
        world = self._apply(rows, (1.0, 0.0, 0.0))
        approx_tuple(world, (x_ax[0], x_ax[1], x_ax[2]))

    @pytest.mark.parametrize("angle", [0.0, 90.0, 180.0, 270.0, 45.0, -30.0])
    def test_rotation_preserves_orthonormality(self, angle):
        normal = (0.0, 0.0, 1.0)
        center = (0.0, 0.0, 0.0)
        x_ax, _ = orthonormal_frame(normal)
        rows = build_frame_matrix(center, normal, x_ax, angle)
        cols = [tuple(rows[r][c] for r in range(3)) for c in range(3)]
        for col in cols:
            assert is_unit(col, tol=1e-9)

    def test_90_degree_rotation_swaps_axes(self):
        """90° rotation maps local X → y_axis and local Y → -x_axis."""
        normal = (0.0, 0.0, 1.0)
        center = (0.0, 0.0, 0.0)
        x_ax, y_ax = orthonormal_frame(normal)
        rows = build_frame_matrix(center, normal, x_ax, 90.0)
        # Local X in world: should equal y_ax
        wx = self._apply(rows, (1.0, 0.0, 0.0))
        approx_tuple(wx, y_ax)
        # Local Y in world: should equal -x_ax
        wy = self._apply(rows, (0.0, 1.0, 0.0))
        approx_tuple(wy, (-x_ax[0], -x_ax[1], -x_ax[2]))

    def test_real_wall_face(self):
        """South-facing vertical wall: normal=(0,-1,0), center on the face."""
        normal = (0.0, -1.0, 0.0)
        center = (50.0, 0.0, 25.0)   # mid-point of a 100×50mm wall
        x_ax, _ = orthonormal_frame(normal)
        rows = build_frame_matrix(center, normal, x_ax, 0.0)
        # Local origin → face center
        world = self._apply(rows, (0.0, 0.0, 0.0))
        approx_tuple(world, center)
        # Local +Z → front of face (outward normal direction from center)
        world_z = self._apply(rows, (0.0, 0.0, 1.0))
        expected = (center[0] + normal[0], center[1] + normal[1], center[2] + normal[2])
        approx_tuple(world_z, expected)

    def test_last_row_is_0001(self):
        """Bottom row of the matrix must be [0, 0, 0, 1]."""
        normal = (1.0, 0.0, 0.0)
        center = (0.0, 0.0, 0.0)
        x_ax, _ = orthonormal_frame(normal)
        rows = build_frame_matrix(center, normal, x_ax, 15.0)
        assert rows[3] == [0.0, 0.0, 0.0, 1.0]
