"""
Ashlar Geometry Library v1.0.1

Pure Python geometry functions for ashlar stone surface generation.
No FreeCAD imports — importable by pytest.

The approach: for each stone, generate a perturbed regular grid of 2D
points, apply fracture-plane Z displacement to simulate quarried stone
texture, then Delaunay-triangulate the result.  The proxy extrudes the
resulting triangulated shell backward to produce a printable solid.

Requires: numpy, scipy -- unlike every other generator in this repo,
which is deliberately dependency-free (see e.g. clapboard_geometry.py's
"No FreeCAD dependencies" convention). Reimplementing perturbed-grid
math and Delaunay triangulation in pure Python was considered and
rejected: numpy's vectorized array math is straightforward to replace,
but a hand-rolled Delaunay triangulation is a well-known source of
numerical-robustness bugs (degenerate/collinear point handling
especially) that isn't worth the risk for what scipy already solves
correctly. Instead, the import is deferred and failure is reported
clearly rather than crashing this module (and therefore ashlar_proxy.py,
which imports it) at load time with a raw traceback -- see
_require_numpy_scipy() below (v1.0.1, 2026-08-08).

Version History:
- 1.0.1: numpy/scipy import failure no longer crashes this module at
         import time (previously an unconditional top-level import --
         since install.py just copies .py files with no dependency
         installation step for end users, anyone without numpy/scipy in
         their FreeCAD's Python environment got a raw ModuleNotFoundError
         instead of this generator's own intended "scipy not available"
         message, which itself was dead code: ashlar_proxy.py's `from
         ashlar_geometry import ...` failed before that check could ever
         run).
- 1.0.0: Initial release
"""

from __future__ import annotations

from typing import List, Tuple

try:
    import numpy as np
    from scipy.spatial import Delaunay
    _NUMPY_SCIPY_OK = True
    _IMPORT_ERROR = None
except ImportError as _exc:
    np = None
    Delaunay = None
    _NUMPY_SCIPY_OK = False
    _IMPORT_ERROR = _exc

VERSION = "1.0.1"


def _require_numpy_scipy():
    """Raise a clear, actionable ImportError if numpy/scipy aren't
    available, instead of letting a bare `np.something` AttributeError
    (np is None) surface deep inside a function's body."""
    if not _NUMPY_SCIPY_OK:
        raise ImportError(
            "ashlar_generator requires numpy and scipy, which are not "
            f"installed in this Python environment ({_IMPORT_ERROR}). "
            "Every other generator in this repo works without them -- "
            "only ashlar_generator's Delaunay-triangulated stone texture "
            "needs them. To fix: install them into the SAME Python "
            "environment FreeCAD itself uses (not your system Python) -- "
            "e.g. `<path to FreeCAD's own python> -m pip install numpy "
            "scipy`, or via FreeCAD's own package/addon manager if it "
            "offers one for your platform."
        )


def generate_perturbed_grid(
    width: float,
    height: float,
    avg_spacing: float,
    randomness: float = 0.3,
    seed: int = 42,
) -> np.ndarray:
    """
    Regular grid with boundary-preserving interior perturbation.

    Boundary points stay exactly on the boundary so edge taper works
    correctly and the rectangular stone outline is preserved.

    Returns np.ndarray shape (N, 2).
    """
    _require_numpy_scipy()
    rng = np.random.default_rng(seed)
    nx = int(width / avg_spacing) + 1
    ny = int(height / avg_spacing) + 1

    x = np.linspace(0, width, nx)
    y = np.linspace(0, height, ny)
    xx, yy = np.meshgrid(x, y)

    points_x = xx.flatten().copy()
    points_y = yy.flatten().copy()

    is_boundary = (
        (points_x == 0.0) | (points_x == width) |
        (points_y == 0.0) | (points_y == height)
    )
    n_interior = int((~is_boundary).sum())
    max_p = avg_spacing * randomness * 0.5
    perturb = rng.uniform(-max_p, max_p, (n_interior, 2))
    points_x[~is_boundary] += perturb[:, 0]
    points_y[~is_boundary] += perturb[:, 1]

    return np.column_stack([points_x, points_y])


def compute_fracture_z_values(
    points_2d: np.ndarray,
    width: float,
    height: float,
    displacement_range: Tuple[float, float] = (0.0, 0.8),
    n_fractures: int = 3,
    edge_taper: float = 1.5,
    seed: int = 42,
) -> np.ndarray:
    """
    Fracture-plane Z displacement for each 2D grid point.

    Uses n_fractures random planes with tanh transitions to simulate
    quarried stone texture.  Edge taper brings displacement to zero at
    stone boundaries so adjacent stones fit cleanly (no gaps or overhangs
    at the joint line).

    Fine Gaussian noise adds sub-millimetre surface roughness.

    Returns np.ndarray shape (N,).
    """
    _require_numpy_scipy()
    rng = np.random.default_rng(seed)
    n_points = len(points_2d)
    min_z, max_z = displacement_range

    scale = max(width, height) / 4.0

    planes = []
    for _ in range(n_fractures):
        angle = rng.uniform(0, 2 * np.pi)
        planes.append({
            'normal': np.array([np.cos(angle), np.sin(angle)]),
            'center': np.array([width / 2.0, height / 2.0]),
            'offset': rng.uniform(-width / 4.0, width / 4.0),
            'z_tilt': rng.uniform(min_z, max_z),
        })

    z_values = np.zeros(n_points)
    for p in planes:
        dist = (points_2d - p['center']) @ p['normal'] - p['offset']
        z_values += p['z_tilt'] * np.tanh(dist / scale)
    z_values /= n_fractures

    # Normalise to fill displacement_range
    z_values -= z_values.mean()
    current_range = z_values.max() - z_values.min()
    if current_range > 0:
        z_values *= (max_z - min_z) / current_range
    z_values += (min_z + max_z) / 2.0
    z_values = np.clip(z_values, min_z, max_z)

    z_values += rng.normal(0, 0.05, n_points)

    # Edge taper to zero at stone boundary
    dist_from_edge = np.minimum(
        np.minimum(points_2d[:, 0], width - points_2d[:, 0]),
        np.minimum(points_2d[:, 1], height - points_2d[:, 1]),
    )
    taper = np.clip(dist_from_edge / edge_taper, 0.0, 1.0)
    return z_values * taper


def generate_stone_surface(
    width: float,
    height: float,
    avg_spacing: float = 0.25,
    randomness: float = 0.6,
    displacement_range: Tuple[float, float] = (-0.8, 0.8),
    n_fractures: int = 3,
    edge_taper: float = 1.5,
    z_offset: float = 1.0,
    seed: int = 42,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Triangulated stone surface ready for proxy conversion.

    z_offset shifts the entire surface forward so even the deepest
    recesses are above Z=0, preventing hollow lakes that would trap
    resin during printing and simplifying the backing-box geometry.

    Returns (points_2d, z_values, simplices):
      points_2d  — (N, 2)  2D mesh points within [0,width] x [0,height]
      z_values   — (N,)    Z = fracture displacement + z_offset
      simplices  — (M, 3)  Delaunay triangle vertex indices
    """
    _require_numpy_scipy()
    points_2d = generate_perturbed_grid(width, height, avg_spacing, randomness, seed)
    z_raw = compute_fracture_z_values(
        points_2d, width, height, displacement_range, n_fractures, edge_taper,
        seed=seed + 1000,
    )
    z_values = z_raw + z_offset
    simplices = Delaunay(points_2d).simplices
    return points_2d, z_values, simplices


def validate_parameters(n_cols: int, n_rows: int, stone_width: float,
                         stone_height: float, joint_width: float) -> Tuple[bool, str]:
    """Reject dimensions that would produce degenerate/negative geometry.

    n_cols/n_rows <= 0 previously reached compute_wall_dimensions()
    unguarded -- e.g. n_cols=0 makes width = 0*stone_width +
    (0-1)*joint_width = -joint_width, a negative wall width flowing
    straight into Part.makeBox with only a broad `except Part.OCCError`
    to catch it (full-review finding
    freecad-mr-generators-20260808-a0b9#24).

    Returns (True, "") if valid, else (False, reason).
    """
    if n_cols <= 0:
        return False, f"NCols must be >= 1, got {n_cols}"
    if n_rows <= 0:
        return False, f"NRows must be >= 1, got {n_rows}"
    if stone_width <= 0:
        return False, f"StoneWidth must be > 0, got {stone_width}"
    if stone_height <= 0:
        return False, f"StoneHeight must be > 0, got {stone_height}"
    if joint_width < 0:
        return False, f"JointWidth must be >= 0, got {joint_width}"
    return True, ""


def compute_stone_positions(
    n_cols: int,
    n_rows: int,
    stone_width: float,
    stone_height: float,
    joint_width: float,
) -> List[dict]:
    """
    Grid layout for all stones in the wall.

    Each entry has: row, col, x, y, width, height, seed.
    Seeds are deterministic from position so the wall is reproducible.
    """
    # TOPO_EPS: push boundary stones slightly outside the wall edges so OCCT
    # Boolean ops (base.cut(stones)) never see coincident coplanar faces.
    TOPO_EPS = joint_width * 0.1

    stones = []
    for row in range(n_rows):
        for col in range(n_cols):
            x = col * (stone_width + joint_width)
            y = row * (stone_height + joint_width)
            w = stone_width
            h = stone_height

            if col == 0:
                x -= TOPO_EPS
                w += TOPO_EPS
            if col == n_cols - 1:
                w += TOPO_EPS
            if row == 0:
                y -= TOPO_EPS
                h += TOPO_EPS
            if row == n_rows - 1:
                h += TOPO_EPS

            stones.append({
                'row': row,
                'col': col,
                'x': x,
                'y': y,
                'width': w,
                'height': h,
                'seed': 2000 + (row * n_cols + col) * 10,
            })
    return stones


def compute_wall_dimensions(
    n_cols: int,
    n_rows: int,
    stone_width: float,
    stone_height: float,
    joint_width: float,
) -> dict:
    """Overall wall width and height (outer boundary including joints)."""
    return {
        'width': n_cols * stone_width + (n_cols - 1) * joint_width,
        'height': n_rows * stone_height + (n_rows - 1) * joint_width,
    }
