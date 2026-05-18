# freecad-mr-generators — Claude project notes

Parametric FreeCAD generator macros + FeaturePython proxies for HO-scale
structures (bricks, clapboards, shingles, etc.).  Each generator splits cleanly:

- `<generator>_geometry.py` — pure-Python math, no FreeCAD imports, importable
  in pytest
- `<generator>_proxy.py` — FeaturePython proxy that consumes geometry output
  and builds OCCT solids via `Part`
- `<generator>_generator.FCMacro` — the user-facing macro
- `tests/test_*.py` — pytest suite that exercises `*_geometry.py` only

Shared utilities live in `shared/` (roof coordinate system, boundary
assertions, FreeCAD helpers).

## Testing rule: parametric edge cases + downstream invariants

A full repo audit (May 2026) found that **5% of existing tests are
downstream-consumer-aware** — the other 95% verify "the geometry function
returned the right numbers" without asking "what does OCCT *do* with those
numbers?"  This gap is how the Flemish-bond / clapboard / board-batten /
bead-board crash family hid in plain sight for months: the geometry math
was arithmetically correct, but the produced positions had brick boundary
faces coincident with the face_slab boundary, which segfaults OCCT's BRep
Boolean builder.

When you add or modify tests for any `*_geometry.py` function, apply both
rules below.  When in doubt, model new tests on `TestBoundaryOverflow` in
`brick_generator/tests/test_brick_geometry.py` and the helpers in
`shared/boundary_assertions.py`.

### Rule 1 — Parameterize across edge-case parameter families, not round numbers

Round numbers (W=50, brick_width=2.32) sit comfortably in the middle of
every internal threshold and never trigger boundary-coincidence math.
For any function whose body contains:

- A `ceil(W / unit) + N` count calculation
- A `for test_n in range(K)` loop that breaks on a threshold (e.g. min_closer)
- A `(W - K * unit) / 2` closer/remainder computation
- A `round(x / grid) * grid` snap-to-grid
- A `min(x, boundary)` or `max(x, boundary)` clip

…you must include a `@pytest.mark.parametrize` test with **at least these
parameter families** for the inputs:

1. **Exact integer multiples** of unit size — `W = N * unit` for several N.
   This is the case that produces zero closers / zero remainders / face
   coincidence.
2. **Single-unit minimum** — the smallest input that fits exactly one unit
   plus required mortar/gap.  Forces the count-calculation lower bound.
3. **Threshold values** for any `if x < threshold` comparison inside the
   function — one test at the value, one just below, one just above.
4. **Loop-cap maximum** — for `for test_n in range(K)` loops, an input
   wide enough to force the loop to run to K (catches off-by-one in
   the loop's "last valid value" tracking).
5. **At least one parameter set drawn from real model use**, separate
   from the implementation's example values.  The implementation's example
   values were used during *development*; the bug hides in the corners.

The `pytest.approx(50, abs=0.01)` pattern is **not enough**.  A 0.01mm
tolerance catches gross arithmetic errors but accepts 1µm coincidence —
which is exactly what OCCT segfaults on.  When checking values near a
boundary, use exact arithmetic and `abs=1e-6`.

### Rule 2 — Assert downstream-consumer invariants

Add at least one test per generator that asserts a property OCCT requires
of the geometry it will consume.  The bug family this catches: any code
path where the pure-Python output is mathematically correct but
topologically dangerous for the consumer.

Use the shared helpers in `shared/boundary_assertions.py`:

- `assert_overflows_boundary(elements, lo, hi, get_extent, …)` — for
  *tiling* fill patterns (bricks, boards, clapboard courses) where the
  union of placed elements must strictly overflow both boundaries.
- `assert_no_boundary_coincidence(elements, lo, hi, get_extent, …)` — for
  *sparse* placement (bead-board gaps, panel seams) where elements don't
  tile but no individual edge may coincide with the boundary.

Known OCCT failure modes worth a regression test wherever they're
reachable:

| OCCT operation                          | Failure mode                                  | Test it with                                  |
| ---                                     | ---                                           | ---                                           |
| `shape.common(slab)`, `shape.cut(slab)` | coincident boundary faces → segfault          | `assert_overflows_boundary` / `_no_boundary_coincidence` |
| `Part.Solid(Part.Shell(faces))`         | zero-width edge in `faces` → segfault         | Assert all element widths/heights/depths > eps |
| `Part.Compound([…]).fuse(other)`        | zero-area face anywhere → undefined behaviour | Assert each placed solid has non-zero area    |
| `face.extrude(vec)`                     | zero-length vector → null shape silently      | Assert extrude vector magnitude > eps         |

If a `*_proxy.py` function performs the OCCT call inline (not via the
geometry module), extract enough of the position math into a pure-Python
helper that the invariant can be tested.  Two existing examples follow
this pattern:

- `clapboard_geometry.calculate_course_v_positions` — extracted from
  `clapboard_proxy._make_course` so the boundary overflow invariant is
  testable without FreeCAD.
- `bead_board_geometry.calculate_gap_positions` — accepts optional
  `h_min` / `h_max` so the same invariant can be checked at the gap level.

### Pre-commit checklist — before any PR touching `*_geometry.py`

```
[ ] Parameterized test covers exact-integer-multiple input?
[ ] Parameterized test covers single-unit-minimum input?
[ ] Threshold values inside the function have at/below/above coverage?
[ ] At least one parameter set NOT from the implementation's example values?
[ ] If output feeds an OCCT Boolean: assert_overflows_boundary or
    assert_no_boundary_coincidence is in the test file?
[ ] If output feeds Part.Solid: zero-dimension guard in tests?
[ ] New `pytest.approx(…)` calls use abs=1e-6 (not 0.01) near boundaries?
```

If a checklist box would naturally be N/A for the function under test
(e.g. it returns a count, not positions), say so explicitly in the PR
description rather than skipping silently.  "Didn't think about it" is
the failure mode this rule exists to prevent.

## Environment notes

- FreeCAD MCP socket: auto-discovered via `~/.cache/freecad-mcp/instances/`
  (v5.8.0+); fall back to `select_freecad_instance(socket_path=…)` only
  if discovery fails.
- AICopilot module deployed via `freecad-mcp/deploy.sh` to
  `/Volumes/Files/claude/FreeCAD-prefs/v1-2/Mod/AICopilot/`.
- Clear `__pycache__/` after deploy — rsync preserves source mtimes, so
  stale `.pyc` files can shadow updated `.py` files.
