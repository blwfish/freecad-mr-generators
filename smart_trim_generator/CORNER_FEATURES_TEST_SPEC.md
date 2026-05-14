# Spec: tests for `EqualizeCorners` + `ConvexCornerFill`

**Status:** drafted 2026-04-23, lives on parked branch `claude/tender-davinci`.
**Target:** `automation/generators/smart_trim/` v1.7.0 corner features.
**Estimated effort:** 3–5 hours including visual validation in FreeCAD.

---

## Goal

Add test coverage for the new corner-handling code in the WIP commit on
`claude/tender-davinci`. Without it, the smart_trim v1.5 → v1.7 features
(`EqualizeCorners`, `ConvexCornerFill`) ship untested, and any regression
will only be caught visually on the next time the user generates trim on
a multi-face wall.

## What's untested

The WIP commit adds five FreeCAD-dependent functions and two pure-math
helpers — none have tests today.

### In `trim_geometry.py`

1. **`clip_solid_at_plane(solid, plane_point, plane_normal, keep_direction, cut_size)`**
   Cuts a solid with a half-space defined by a plane. Used in Pass A
   (corner equalisation). Returns clipped solid or original on failure.

2. **`create_building_corner_fill(corner_start, corner_end, normal_A, normal_B, profile_width)`**
   Builds the parallelogram-prism fill at an exterior building corner.
   Returns Solid or `None` on degenerate input.

### In `smart_trim_proxy.py`

3. **`_get_face_vertical_edges(face, perimeter_only=True, vertical_axis='z')`**
   Returns vertical (optionally perimeter-only) edges of a face.

4. **`_find_shared_corner_edges(edges_A, edges_B, tolerance=0.5)`**
   Finds geometrically-coincident edges between two faces (the corner line).
   Returns list of `(start, end, tang_A, tang_B)` tuples, sorted by Z.

5. **`_neg_binormal(tangent, face_normal)`**
   Computes `-(t × n)` normalised — the in-surface direction trim extends
   from an edge. Pure vector math; returns `None` on degenerate inputs.

### Integration: `generate_trim()` corner-pass loop

The loop that detects perpendicular face pairs, finds their shared edge,
runs Pass A (clip) + Pass B (fill). Skips when `flip` or `only_edge` debug
modes are active, or with <2 faces.

## Where the tests go

This codebase has **two test conventions**:

- `test_trim_geometry.py` (top-level) — custom `TestResults` runner;
  works standalone or inside FreeCAD; tests FreeCAD-dependent functions
  using real `Part` objects.
- `tests/test_smart_trim_geometry.py` — pytest-based; tests pure-Python
  utilities (vector math, edge classification).

The new functions are mostly FreeCAD-dependent → **add to `test_trim_geometry.py`**.
The exception is `_neg_binormal` (pure vector math) which can use either,
but keeping it next to the corner integration tests is more discoverable.

## Test plan

### Pure-math (low-cost, run-anywhere) — 4 cases

`_neg_binormal(tangent, face_normal)`:

1. `_neg_binormal((1,0,0), (0,1,0))` → `(0,0,-1)` (right-handed cross,
   then negated)
2. `_neg_binormal((0,1,0), (0,0,1))` → `(0,0,-1)`-ish wait reset —
   `t=(0,1,0)`, `n=(0,0,1)`, `t×n=(1,0,0)`, neg=`(-1,0,0)`. Verify.
3. `_neg_binormal(t, n)` where `t == n` (degenerate) → `None`
4. `_neg_binormal((1,0,0), (1,0,0))` (parallel) → `None`

### `clip_solid_at_plane` — 5 cases

Build a 10×10×10 box, clip with various plane positions:

1. **Plane through middle, keep_direction=+X** → result volume ≈ 500 (half).
2. **Plane through middle, keep_direction=-X** → result volume ≈ 500
   (the other half).
3. **Plane outside the solid, keep_direction toward solid** → original
   solid returned (no cut).
4. **Plane outside, keep_direction away from solid** → empty result;
   per implementation, returns the original solid on `result.Solids` empty.
   Verify the documented graceful-fallback behaviour.
5. **Diagonal plane** (e.g. normal `(1,1,0)/√2`) → result is a wedge.
   Verify volume ≈ 500 ± a small tolerance.

### `create_building_corner_fill` — 5 cases

1. **Standard exterior corner**: `start=(0,0,0)`, `end=(0,0,10)`,
   `normal_A=(1,0,0)`, `normal_B=(0,1,0)`, `width=2.0` → solid with
   volume = 2.0 × 2.0 × 10 = 40.0.
2. **Wider profile**: `width=5.0` → volume = 250.0.
3. **Coplanar normals (degenerate)**: `normal_A=(1,0,0)`, `normal_B=(1,0,0)`
   → `None`.
4. **Anti-parallel normals**: `normal_A=(1,0,0)`, `normal_B=(-1,0,0)`
   → `None` (cross product is zero).
5. **Zero-length corner line**: `start == end` → `None`.

### `_find_shared_corner_edges` — 4 cases

Build two unit-square faces in different planes; manufacture edges and
verify pairing logic:

1. **Two faces sharing one edge** (perpendicular walls): expect 1 shared
   edge, returned as `(start, end, tang_A, tang_B)` with `start.z <= end.z`.
2. **Edges in opposite winding order** (face B's edge starts at face A's
   end): still detected — order-independent matching.
3. **Edges nearly-but-not-quite coincident** (>tolerance apart): not
   matched. Verify default `tolerance=0.5` cutoff.
4. **Two faces with no shared edges**: returns `[]`.

### `_get_face_vertical_edges` — 3 cases

1. **Square wall face** (4 edges, 2 vertical): returns 2 edges with
   `perimeter_only=True`.
2. **Same face, `perimeter_only=False`**: returns same 2 vertical edges
   (no internal edges in this fixture).
3. **Triangular gable face** (no vertical edges): returns `[]`.

### Integration tests for `generate_trim` corner passes — 3 cases

These need a small fixture FCStd or programmatically-built compound:

1. **Two perpendicular wall faces sharing one edge**, `EqualizeCorners=True`,
   `ConvexCornerFill=True` → output compound contains:
   - Trim pieces from both walls
   - Exactly 1 fill prism with the expected `TrimWidth × TrimWidth × edge_length`
     volume
2. **Same fixture, `ConvexCornerFill=False`** → no fill prism added.
3. **Two PARALLEL wall faces** (non-corner) → corner pass skips
   (`abs(dot) > 0.85`), no clipping, no fill. Output has the same trim
   volume as without the corner-handling code.

### Visual validation (mandatory before merge)

Programmatic tests confirm volumes and counts but not visual correctness.
Before landing on main:

1. Open or build a simple rectangular box model in FreeCAD
2. Apply smart_trim to all 4 vertical wall faces
3. With `EqualizeCorners=True` + `ConvexCornerFill=True`: zoom in on each
   of the 4 vertical building corners. Confirm:
   - No gap at the corner (fill is present)
   - Both walls' trim shows equal visible width on either side of the corner
   - No double-thickness or overlap regions
4. Toggle each property off independently; confirm the visual change
   matches expectation
5. Repeat on a hexagonal floor plan to verify non-90° corners (the
   `dot > 0.85` cutoff is at ~32° from perpendicular — verify hexagon's
   60°-from-perp corners still get treated)
6. Repeat on an L-shape with one internal corner (concave) — confirm
   the corner-pass logic doesn't try to "fill" an internal corner (which
   would produce overlapping geometry)

## Acceptance criteria

- All 24 new programmatic test cases pass (4 + 5 + 5 + 4 + 3 + 3)
- `test_trim_geometry.py` runs cleanly both standalone and inside FreeCAD
- Visual validation steps 1–6 confirmed on at least 3 distinct building
  shapes
- `smart_trim/README.md` updated with v1.7.0 changelog entries documenting
  the two new properties
- `version_check.py` (or wherever the version is asserted) updated to 1.7.0

## Open questions

1. **Concave corner behaviour**: the corner-pass loop treats all
   perpendicular pairs identically. Is the convex-fill code safe on
   concave (internal) corners, or does it need an explicit guard? The
   internal corner has `create_internal_corner_fill` doing something
   different — confirm the two paths don't fight.

2. **Tolerance tuning**: `_find_shared_corner_edges(tolerance=0.5)` —
   is 0.5 mm the right number for FreeCAD's internal precision? On a
   model where two walls were generated independently and snap-aligned,
   the actual edge-vertex coincidence may be tighter or looser than that.
   Worth a sanity check against real Photo Parts station models.

3. **Equal-width clipping symmetry**: when wall A is much shorter than
   wall B, does Pass A produce visually-equal trim widths or is the
   "centerline" actually halfway along A's edge? Spec assumes the latter
   is correct; verify with a long+short wall pair.

## When you resume

```bash
cd /Volumes/Files/claude/FreeCAD-github/automation/.claude/worktrees/tender-davinci

# Put the WIP code back in the working tree:
git reset HEAD~

# Now smart_trim_proxy.py / trim_geometry.py have the corner code as
# uncommitted changes. Develop the tests, then commit the implementation
# and tests as proper feature commits (split if useful).
```

The spec lives in this directory so it travels with the branch.
