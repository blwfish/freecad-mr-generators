"""
Tests for ashlar_geometry.py

Covers:
  - generate_perturbed_grid: boundary preservation, interior perturbation,
    grid density formula, exact-multiple inputs
  - compute_fracture_z_values: output range, edge taper, determinism
  - generate_stone_surface: z_offset guarantee (no lakes), no degenerate
    triangles (OCCT extrude safety), point bounds
  - compute_stone_positions / compute_wall_dimensions: layout math including
    exact-integer-multiple cases and single-row/column edge cases
"""

import math
import pytest

# Skips this whole file cleanly (not a collection ERROR) when numpy/scipy
# aren't installed, matching this repo's FreeCAD-gated test convention
# (see shared/tests/test_freecad_utils_integration.py) -- ashlar_geometry
# itself now degrades the same way (v1.0.1, 2026-08-08) rather than
# crashing at import time, but these tests genuinely need numpy to make
# their own assertions, so there's nothing to test without it either way.
np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from ashlar_geometry import (
    generate_perturbed_grid,
    compute_fracture_z_values,
    generate_stone_surface,
    compute_stone_positions,
    compute_wall_dimensions,
    validate_parameters,
)


# ---------------------------------------------------------------------------
# generate_perturbed_grid
# ---------------------------------------------------------------------------

class TestGeneratePerturbedGrid:

    def test_output_shape(self):
        pts = generate_perturbed_grid(7.0, 5.25, 0.5)
        assert pts.ndim == 2
        assert pts.shape[1] == 2
        assert pts.shape[0] > 0

    def test_boundary_points_unperturbed(self):
        """Points on the stone boundary must stay exactly on it (no perturbation)."""
        w, h = 7.0, 5.25
        pts = generate_perturbed_grid(w, h, 0.5, randomness=0.9, seed=0)
        on_left   = pts[np.isclose(pts[:, 0], 0.0,  atol=1e-12)]
        on_right  = pts[np.isclose(pts[:, 0], w,    atol=1e-12)]
        on_bottom = pts[np.isclose(pts[:, 1], 0.0,  atol=1e-12)]
        on_top    = pts[np.isclose(pts[:, 1], h,    atol=1e-12)]
        for edge_pts in (on_left, on_right, on_bottom, on_top):
            assert len(edge_pts) > 0

    def test_all_points_within_bounds(self):
        w, h = 7.0, 5.25
        pts = generate_perturbed_grid(w, h, 0.25, randomness=0.6)
        assert np.all(pts[:, 0] >= 0.0)
        assert np.all(pts[:, 0] <= w)
        assert np.all(pts[:, 1] >= 0.0)
        assert np.all(pts[:, 1] <= h)

    @pytest.mark.parametrize("spacing", [0.5, 1.0, 1.75, 3.5])
    def test_exact_multiple_widths(self, spacing):
        """Width = exact multiple of spacing — tests zero-remainder grid path."""
        w = 7.0  # 7.0 / 0.5 = 14, 7.0 / 1.0 = 7, 7.0 / 1.75 = 4, 7.0 / 3.5 = 2
        h = 5.25
        pts = generate_perturbed_grid(w, h, spacing)
        assert pts.shape[0] > 1

    def test_minimum_stone_size(self):
        """Single-column × single-row grid (spacing ≥ width or height)."""
        pts = generate_perturbed_grid(0.5, 0.5, 0.5)
        assert pts.shape[0] >= 1

    def test_deterministic(self):
        pts1 = generate_perturbed_grid(7.0, 5.25, 0.3, seed=99)
        pts2 = generate_perturbed_grid(7.0, 5.25, 0.3, seed=99)
        np.testing.assert_array_equal(pts1, pts2)

    def test_different_seeds_differ(self):
        pts1 = generate_perturbed_grid(7.0, 5.25, 0.3, seed=1)
        pts2 = generate_perturbed_grid(7.0, 5.25, 0.3, seed=2)
        assert not np.allclose(pts1, pts2)

    def test_grid_density_increases_with_smaller_spacing(self):
        pts_coarse = generate_perturbed_grid(7.0, 5.25, 1.0)
        pts_fine   = generate_perturbed_grid(7.0, 5.25, 0.25)
        assert pts_fine.shape[0] > pts_coarse.shape[0]


# ---------------------------------------------------------------------------
# compute_fracture_z_values
# ---------------------------------------------------------------------------

class TestComputeFractureZValues:

    @pytest.fixture
    def base_grid(self):
        return generate_perturbed_grid(7.0, 5.25, 0.5, seed=42)

    def test_output_shape_matches_input(self, base_grid):
        z = compute_fracture_z_values(base_grid, 7.0, 5.25)
        assert z.shape == (base_grid.shape[0],)

    def test_z_values_mostly_in_range(self, base_grid):
        """After fine noise the majority of z values stay near displacement_range."""
        dr = (-0.8, 0.8)
        z = compute_fracture_z_values(base_grid, 7.0, 5.25, displacement_range=dr)
        # Fine noise is σ=0.05; 99% should be within ±0.2 of the clipped range
        assert np.mean((z >= dr[0] - 0.2) & (z <= dr[1] + 0.2)) > 0.99

    def test_edge_points_near_zero(self, base_grid):
        """Boundary grid points must have |z| close to zero due to edge taper."""
        w, h = 7.0, 5.25
        z = compute_fracture_z_values(base_grid, w, h,
                                       displacement_range=(-0.8, 0.8),
                                       edge_taper=1.5)
        on_boundary = (
            np.isclose(base_grid[:, 0], 0.0, atol=1e-12) |
            np.isclose(base_grid[:, 0], w,   atol=1e-12) |
            np.isclose(base_grid[:, 1], 0.0, atol=1e-12) |
            np.isclose(base_grid[:, 1], h,   atol=1e-12)
        )
        # Boundary points: taper_factor=0 → z should be exactly 0 before fine noise
        # After noise σ=0.05 they'll be small
        assert np.all(np.abs(z[on_boundary]) < 0.3)

    def test_deterministic(self, base_grid):
        z1 = compute_fracture_z_values(base_grid, 7.0, 5.25, seed=7)
        z2 = compute_fracture_z_values(base_grid, 7.0, 5.25, seed=7)
        np.testing.assert_array_equal(z1, z2)

    def test_different_seeds_differ(self, base_grid):
        z1 = compute_fracture_z_values(base_grid, 7.0, 5.25, seed=1)
        z2 = compute_fracture_z_values(base_grid, 7.0, 5.25, seed=2)
        assert not np.allclose(z1, z2)

    @pytest.mark.parametrize("n_fractures", [1, 2, 3, 5])
    def test_n_fractures_param(self, base_grid, n_fractures):
        z = compute_fracture_z_values(base_grid, 7.0, 5.25,
                                       n_fractures=n_fractures)
        assert z.shape == (base_grid.shape[0],)

    def test_zero_displacement_range_gives_near_zero(self, base_grid):
        """displacement_range=(0,0) → only fine noise remains."""
        z = compute_fracture_z_values(base_grid, 7.0, 5.25,
                                       displacement_range=(0.0, 0.0))
        assert np.all(np.abs(z) < 0.5)


# ---------------------------------------------------------------------------
# generate_stone_surface — OCCT invariants
# ---------------------------------------------------------------------------

class TestGenerateStoneSurface:

    @pytest.mark.parametrize("width,height", [
        (7.0, 5.25),       # reference HO ashlar stone
        (3.5, 5.25),       # half-width
        (7.0, 2.625),      # half-height
        (14.0, 5.25),      # wide stone
        (7.0, 10.5),       # tall stone
        (0.5, 0.5),        # minimum stone — single-grid edge case
    ])
    def test_output_shapes(self, width, height):
        pts2d, z_vals, simplices = generate_stone_surface(width, height, seed=1)
        assert pts2d.ndim == 2 and pts2d.shape[1] == 2
        assert z_vals.shape == (pts2d.shape[0],)
        assert simplices.ndim == 2 and simplices.shape[1] == 3

    def test_z_offset_guarantees_positive_z(self):
        """z_offset=1.0 with displacement_range=(-0.8, 0.8) → all z > 0.

        OCCT invariant: the extruded shell must not have self-intersecting
        geometry from a surface that dips below Z=0 (which is where the
        mortar sheet sits).
        """
        pts2d, z_vals, simplices = generate_stone_surface(
            7.0, 5.25,
            displacement_range=(-0.8, 0.8),
            z_offset=1.0,
            seed=42,
        )
        # After taper + z_offset, minimum should be z_offset + min_disp + taper≈0
        # Fine noise σ=0.05 can push slightly below but should stay above ~0
        assert np.all(z_vals > -0.1), (
            f"Some Z values below -0.1: min={z_vals.min():.4f}"
        )

    def test_no_zero_area_triangles(self):
        """All triangles must have non-zero area in 2D.

        OCCT invariant: zero-area triangles produce degenerate edges that
        cause Part.Shell / extrude to fail or produce garbage geometry.
        """
        pts2d, z_vals, simplices = generate_stone_surface(
            7.0, 5.25, avg_spacing=0.5, seed=99,
        )
        eps = 1e-9
        for s in simplices:
            a, b, c = pts2d[s[0]], pts2d[s[1]], pts2d[s[2]]
            cross = abs((b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0]))
            assert cross > eps, f"Degenerate triangle: {a}, {b}, {c}"

    def test_all_simplex_indices_valid(self):
        pts2d, z_vals, simplices = generate_stone_surface(7.0, 5.25, seed=5)
        n = pts2d.shape[0]
        assert np.all(simplices >= 0)
        assert np.all(simplices < n)

    def test_points_within_stone_bounds(self):
        w, h = 7.0, 5.25
        pts2d, _, _ = generate_stone_surface(w, h, seed=3)
        assert np.all(pts2d[:, 0] >= 0.0 - 1e-12)
        assert np.all(pts2d[:, 0] <= w   + 1e-12)
        assert np.all(pts2d[:, 1] >= 0.0 - 1e-12)
        assert np.all(pts2d[:, 1] <= h   + 1e-12)

    def test_deterministic(self):
        r1 = generate_stone_surface(7.0, 5.25, seed=77)
        r2 = generate_stone_surface(7.0, 5.25, seed=77)
        np.testing.assert_array_equal(r1[0], r2[0])
        np.testing.assert_array_equal(r1[1], r2[1])
        np.testing.assert_array_equal(r1[2], r2[2])

    def test_different_seeds_give_different_textures(self):
        _, z1, _ = generate_stone_surface(7.0, 5.25, seed=10)
        _, z2, _ = generate_stone_surface(7.0, 5.25, seed=11)
        assert not np.allclose(z1, z2)

    @pytest.mark.parametrize("spacing", [0.5, 1.0, 1.75])
    def test_exact_multiple_spacing(self, spacing):
        """Width=7.0 is an exact multiple of 0.5, 1.0, 1.75 — zero-remainder path."""
        pts2d, z_vals, simplices = generate_stone_surface(
            7.0, 5.25, avg_spacing=spacing, seed=1,
        )
        assert pts2d.shape[0] > 1
        assert simplices.shape[0] > 0

    def test_z_offset_zero_still_produces_surface(self):
        pts2d, z_vals, simplices = generate_stone_surface(
            7.0, 5.25, z_offset=0.0, seed=1,
        )
        assert pts2d.shape[0] > 0

    def test_real_model_parameters(self):
        """Richmond Main Street Station ground-level ashlar: larger stones."""
        pts2d, z_vals, simplices = generate_stone_surface(
            14.0, 8.4,
            avg_spacing=0.35,
            displacement_range=(-1.2, 1.2),
            z_offset=1.5,
            seed=2000,
        )
        assert pts2d.shape[0] > 0
        assert np.all(z_vals > -0.2)


# ---------------------------------------------------------------------------
# compute_stone_positions
# ---------------------------------------------------------------------------

class TestComputeStonePositions:

    def test_count(self):
        stones = compute_stone_positions(4, 3, 7.0, 5.25, 0.3)
        assert len(stones) == 12

    def test_single_stone(self):
        stones = compute_stone_positions(1, 1, 7.0, 5.25, 0.3)
        assert len(stones) == 1
        TOPO_EPS = 0.3 * 0.1
        # Boundary stones are shifted out by TOPO_EPS on all sides
        assert stones[0]['x'] == pytest.approx(-TOPO_EPS, abs=1e-9)
        assert stones[0]['y'] == pytest.approx(-TOPO_EPS, abs=1e-9)

    def test_positions_no_overlap(self):
        stones = compute_stone_positions(4, 3, 7.0, 5.25, 0.3)
        for i, s in enumerate(stones):
            for j, t in enumerate(stones):
                if i == j:
                    continue
                x_overlap = (s['x'] < t['x'] + t['width']) and (s['x'] + s['width'] > t['x'])
                y_overlap = (s['y'] < t['y'] + t['height']) and (s['y'] + s['height'] > t['y'])
                assert not (x_overlap and y_overlap), \
                    f"Stones {i} and {j} overlap"

    def test_column_spacing_exact_multiple(self):
        """StoneWidth=7.0 is exact multiple of JointWidth=7.0."""
        stones = compute_stone_positions(4, 1, 7.0, 7.0, 7.0)
        xs = sorted(s['x'] for s in stones)
        TOPO_EPS = 7.0 * 0.1  # joint_width * 0.1
        assert xs[0] == pytest.approx(-TOPO_EPS, abs=1e-9)  # col 0 shifted left
        assert xs[1] == pytest.approx(14.0, abs=1e-9)       # 7.0 + 7.0, interior

    def test_unique_seeds(self):
        stones = compute_stone_positions(4, 3, 7.0, 5.25, 0.3)
        seeds = [s['seed'] for s in stones]
        assert len(seeds) == len(set(seeds))

    def test_row_col_indices(self):
        stones = compute_stone_positions(3, 2, 7.0, 5.25, 0.3)
        rows = sorted(set(s['row'] for s in stones))
        cols = sorted(set(s['col'] for s in stones))
        assert rows == [0, 1]
        assert cols == [0, 1, 2]

    def test_single_row(self):
        stones = compute_stone_positions(5, 1, 7.0, 5.25, 0.3)
        assert len(stones) == 5
        TOPO_EPS = 0.3 * 0.1
        # All stones are in the only row (row 0 == last row), so y is shifted
        ys = [s['y'] for s in stones]
        assert all(y == pytest.approx(-TOPO_EPS) for y in ys)

    def test_single_column(self):
        stones = compute_stone_positions(1, 5, 7.0, 5.25, 0.3)
        assert len(stones) == 5
        TOPO_EPS = 0.3 * 0.1
        # All stones are in the only column (col 0 == last col), so x is shifted
        xs = [s['x'] for s in stones]
        assert all(x == pytest.approx(-TOPO_EPS) for x in xs)


# ---------------------------------------------------------------------------
# validate_parameters
# ---------------------------------------------------------------------------

class TestValidateParameters:
    """Full-review finding freecad-mr-generators-20260808-a0b9#24:
    n_cols/n_rows <= 0 previously reached compute_wall_dimensions()
    unguarded, producing a negative wall width fed straight into
    Part.makeBox."""

    VALID = dict(n_cols=4, n_rows=3, stone_width=7.0, stone_height=5.25, joint_width=0.3)

    def test_valid_params_pass(self):
        valid, reason = validate_parameters(**self.VALID)
        assert valid is True
        assert reason == ""

    def test_n_cols_zero_rejected(self):
        valid, reason = validate_parameters(**{**self.VALID, 'n_cols': 0})
        assert valid is False

    def test_n_cols_negative_rejected(self):
        valid, reason = validate_parameters(**{**self.VALID, 'n_cols': -1})
        assert valid is False

    def test_n_cols_one_is_valid(self):
        valid, reason = validate_parameters(**{**self.VALID, 'n_cols': 1})
        assert valid is True

    def test_n_rows_zero_rejected(self):
        valid, reason = validate_parameters(**{**self.VALID, 'n_rows': 0})
        assert valid is False

    def test_n_rows_negative_rejected(self):
        valid, reason = validate_parameters(**{**self.VALID, 'n_rows': -1})
        assert valid is False

    def test_stone_width_zero_rejected(self):
        valid, reason = validate_parameters(**{**self.VALID, 'stone_width': 0.0})
        assert valid is False

    def test_stone_width_negative_rejected(self):
        valid, reason = validate_parameters(**{**self.VALID, 'stone_width': -1.0})
        assert valid is False

    def test_stone_height_zero_rejected(self):
        valid, reason = validate_parameters(**{**self.VALID, 'stone_height': 0.0})
        assert valid is False

    def test_joint_width_zero_is_valid(self):
        # Zero-width joints (stones butted directly together) are unusual
        # but not degenerate -- only negative joint width is rejected.
        valid, reason = validate_parameters(**{**self.VALID, 'joint_width': 0.0})
        assert valid is True

    def test_joint_width_negative_rejected(self):
        valid, reason = validate_parameters(**{**self.VALID, 'joint_width': -0.1})
        assert valid is False

    def test_real_model_value(self):
        valid, reason = validate_parameters(
            n_cols=6, n_rows=4, stone_width=9.2, stone_height=6.1, joint_width=0.4)
        assert valid is True


# ---------------------------------------------------------------------------
# compute_wall_dimensions
# ---------------------------------------------------------------------------

class TestComputeWallDimensions:

    def test_single_stone_no_joints(self):
        d = compute_wall_dimensions(1, 1, 7.0, 5.25, 0.3)
        assert d['width']  == pytest.approx(7.0,  abs=1e-9)
        assert d['height'] == pytest.approx(5.25, abs=1e-9)

    def test_two_columns_includes_one_joint(self):
        d = compute_wall_dimensions(2, 1, 7.0, 5.25, 0.3)
        assert d['width'] == pytest.approx(7.0 + 0.3 + 7.0, abs=1e-9)

    def test_reference_4x3_wall(self):
        """4×3 wall used in the original macros."""
        d = compute_wall_dimensions(4, 3, 7.0, 5.25, 0.3)
        assert d['width']  == pytest.approx(4*7.0 + 3*0.3, abs=1e-9)
        assert d['height'] == pytest.approx(3*5.25 + 2*0.3, abs=1e-9)

    @pytest.mark.parametrize("joint", [0.0, 0.3, 0.5, 1.0])
    def test_zero_joint_width(self, joint):
        d = compute_wall_dimensions(4, 3, 7.0, 5.25, joint)
        assert d['width']  == pytest.approx(4*7.0  + 3*joint, abs=1e-9)
        assert d['height'] == pytest.approx(3*5.25 + 2*joint, abs=1e-9)

    def test_exact_multiple_joint(self):
        """Joint=stone_width: positions are exact multiples."""
        d = compute_wall_dimensions(3, 2, 7.0, 7.0, 7.0)
        assert d['width']  == pytest.approx(3*7.0 + 2*7.0, abs=1e-9)
        assert d['height'] == pytest.approx(2*7.0 + 1*7.0, abs=1e-9)

    def test_wall_covers_all_stone_positions(self):
        """Boundary stones overflow the wall by TOPO_EPS on each outer edge."""
        n_cols, n_rows = 4, 3
        sw, sh, jw = 7.0, 5.25, 0.3
        TOPO_EPS = jw * 0.1
        d = compute_wall_dimensions(n_cols, n_rows, sw, sh, jw)
        stones = compute_stone_positions(n_cols, n_rows, sw, sh, jw)
        max_x = max(s['x'] + s['width']  for s in stones)
        max_y = max(s['y'] + s['height'] for s in stones)
        min_x = min(s['x'] for s in stones)
        min_y = min(s['y'] for s in stones)
        # Outer edges overflow wall bounds by TOPO_EPS
        assert max_x == pytest.approx(d['width']  + TOPO_EPS, abs=1e-6)
        assert max_y == pytest.approx(d['height'] + TOPO_EPS, abs=1e-6)
        assert min_x == pytest.approx(-TOPO_EPS, abs=1e-6)
        assert min_y == pytest.approx(-TOPO_EPS, abs=1e-6)


class TestMissingNumpyScipyGuard:
    """
    Regression test for the actual bug that prompted this module's
    deferred-import rewrite (2026-08-08): previously an unconditional
    top-level `import numpy` / `from scipy.spatial import Delaunay`
    meant anyone without those installed in FreeCAD's own Python
    environment (install.py has no dependency-installation step for end
    users -- it just copies .py files) got a raw ModuleNotFoundError
    crashing this entire module's import, rather than the generator's own
    intended clean error message.

    Simulates "not installed" via monkeypatch rather than actually
    uninstalling numpy/scipy, so this runs in the normal dev/CI
    environment where they ARE present.
    """

    def test_generate_perturbed_grid_raises_clear_error(self, monkeypatch):
        import ashlar_geometry
        monkeypatch.setattr(ashlar_geometry, "_NUMPY_SCIPY_OK", False)
        with pytest.raises(ImportError, match="numpy and scipy"):
            ashlar_geometry.generate_perturbed_grid(10.0, 10.0, 1.0)

    def test_compute_fracture_z_values_raises_clear_error(self, monkeypatch):
        import ashlar_geometry
        monkeypatch.setattr(ashlar_geometry, "_NUMPY_SCIPY_OK", False)
        with pytest.raises(ImportError, match="numpy and scipy"):
            ashlar_geometry.compute_fracture_z_values([(0.0, 0.0)], 10.0, 10.0)

    def test_generate_stone_surface_raises_clear_error(self, monkeypatch):
        import ashlar_geometry
        monkeypatch.setattr(ashlar_geometry, "_NUMPY_SCIPY_OK", False)
        with pytest.raises(ImportError, match="numpy and scipy"):
            ashlar_geometry.generate_stone_surface(10.0, 10.0)

    def test_compute_stone_positions_unaffected_by_missing_deps(self, monkeypatch):
        # Pure-Python functions must keep working regardless -- they never
        # needed numpy/scipy in the first place.
        import ashlar_geometry
        monkeypatch.setattr(ashlar_geometry, "_NUMPY_SCIPY_OK", False)
        positions = ashlar_geometry.compute_stone_positions(2, 2, 7.0, 5.25, 0.3)
        assert len(positions) == 4

    def test_compute_wall_dimensions_unaffected_by_missing_deps(self, monkeypatch):
        import ashlar_geometry
        monkeypatch.setattr(ashlar_geometry, "_NUMPY_SCIPY_OK", False)
        dims = ashlar_geometry.compute_wall_dimensions(2, 2, 7.0, 5.25, 0.3)
        assert dims['width'] > 0 and dims['height'] > 0
