# freecad-mr-generators — Claude project notes

Parametric FreeCAD generator macros + FeaturePython proxies for HO-scale
structures (bricks, clapboards, shingles, etc.).  Each generator splits cleanly:

- `<generator>_geometry.py` — pure-Python math, no FreeCAD imports, importable
  in pytest
- `<generator>_proxy.py` — FeaturePython proxy that consumes geometry output
  and builds OCCT solids via `Part`
- `<generator>_generator.FCMacro` — the user-facing macro
- `tests/test_*.py` — pytest suite that exercises `*_geometry.py` under plain
  `python3 -m pytest`; `*_proxy.py` logic that's genuinely worth covering
  (not every proxy needs this) can also get real FreeCAD-backed tests — see
  "Testing FreeCAD-dependent proxy code" below.

Shared utilities live in `shared/` (roof coordinate system, boundary
assertions, FreeCAD helpers).

## Testing FreeCAD-dependent proxy code

Don't assume `*_proxy.py` logic is untestable just because it needs
`FreeCAD`/`Part` — a plain `python3 -m pytest` run can't import those (no
GUI Python has them on sys.path), but FreeCAD ships a headless console
binary, `FreeCADCmd`, that can: real document creation, real OCCT geometry,
no display needed. Its pixi environment already has `pytest` installed.
Confirmed working 2026-08-08 while closing a coverage gap in
`shared/freecad_utils.py`'s face-unwrapping logic (previously untested
854-line `roof_seam_proxy.py` code) — see
`shared/tests/test_freecad_utils_integration.py` for a real example (13
tests: legacy BaseObject/ShingleSkin/naming conventions, the modern
`Sources` convention, depth-limit cutoff, end-to-end shared-edge
resolution) and `shared/tests/run_freecad_tests.py` for the runner.

How it works: `FreeCADCmd /abs/path/to/script.py` runs the script through
FreeCAD's own embedded Python (currently 3.11, pixi-managed at
`FC-clone/.pixi/envs/default/`) — `import FreeCAD`/`import Part` just work,
and since `pytest` is already in that environment, the script can simply
call `pytest.main([...])` itself (FreeCADCmd has no `-m pytest` flag; it
only runs a single script). Two gotchas that cost real debugging time:
- **Use an absolute path for the script argument.** A relative path
  silently no-ops (FreeCAD exits 0 with zero output, no error) rather than
  failing loudly.
- **Don't gate the runner on `if __name__ == "__main__":`.** FreeCADCmd
  does not set `__name__` to `"__main__"` for the script it runs, so that
  guard silently skips the entire script the same way — exit 0, no output,
  no error. Execute top-level, unconditionally.

To keep these tests from ever crashing a plain `python3 -m pytest` run
(forcing FreeCAD's `.so` onto a mismatched system Python `import` can
segfault rather than raise, confirmed 2026-08-08), guard the whole test
file with `App = pytest.importorskip("FreeCAD")` at module level — this
skips the entire file as one unit under plain pytest (no `FreeCAD` on
sys.path → clean `ModuleNotFoundError` → skip) and runs for real under
`FreeCADCmd`.

Use this for proxy logic that's complex enough to have hidden real bugs
(like the face-unwrapping case) — not a blanket mandate to add FreeCAD
integration tests to every proxy file; most are simple enough that manual
live verification (per the brick/quoin and slate-seam sessions this same
day) remains proportionate.

## Testing rule: proxy/geometry parity

Every `*_proxy.py` that inlines arithmetic from the corresponding
`*_geometry.py` — rather than calling the geometry function directly —
**must have a parity test** that runs both formulas against the same
inputs and asserts they agree.

Why this is High severity, not Low: the test suite can only exercise
`*_geometry.py` (no FreeCAD in pytest).  If the proxy inlines a
divergent copy of the same formula, all geometry tests stay green while
the proxy silently places elements incorrectly.  The divergence is
structurally invisible to CI — "both sides look correct in isolation"
is exactly the condition that lets it hide.

The parity test pattern: compute the expected value two ways — once via
the geometry function, once by directly transcribing the proxy's inline
formula — and assert they are equal.  This creates a coupling point that
breaks as soon as either side drifts.  Model on
`TestShinglePositionProxyParity` in
`shingle_generator/tests/test_shingle_geometry.py`.

When reviewing: the *absence* of a parity test for any proxy that inlines
geometry math is a High finding, not a gap to defer.

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
- AICopilot module deployed via `freecad-mcp/deploy.sh` to whichever
  `FreeCAD-prefs/v<major>-<minor>/Mod/AICopilot/` matches the running
  FreeCAD's version — `deploy.sh` auto-detects this (newest versioned
  dir with a `Mod/` subdir), so don't hardcode a specific `vN-M` path;
  it goes stale the next time FreeCAD's version bumps (bit us for weeks
  after the 1.2 → 26.3 renumbering: every deploy silently landed in the
  no-longer-read `v1-2`, 2026-07-29).
- Clear `__pycache__/` after deploy — rsync preserves source mtimes, so
  stale `.pyc` files can shadow updated `.py` files.
- After `install.py`, a long-running FreeCAD process can still serve stale
  code even with `__pycache__/` cleared and the right file on disk — if a
  library module (e.g. `quoin_geometry.py`) was already `import`ed earlier
  in that session, Python's `sys.modules` cache holds the old module object
  and a fresh `import` is a no-op. `reload_modules` (the MCP tool) only
  reloads AICopilot's own registered handler modules, not these generator
  library files. Fix: from `execute_python`, `sys.modules.pop(name, None)`
  for every affected module *before* re-importing (or just restart FreeCAD).
  Confirmed 2026-08-07: `brick_proxy.py`'s `try/except ImportError` around
  `from quoin_geometry import ...` silently degraded to `None` this way,
  with no visible error, after editing `quoin_geometry.py` mid-session.

## Tool-use rule: don't use view_control(operation="screenshot")

It captures the whole physical display via macOS `screencapture`, not
FreeCAD's window specifically. Since the user has to bring another app
(often Claude/the terminal) to the front to type to Claude, FreeCAD is
essentially never the frontmost/visible window when the capture actually
fires — it's also possible FreeCAD is on a different display/Space
entirely. In practice this means the screenshot is essentially always
useless (confirmed 2026-07-29: repeatedly captured the desktop wallpaper
or whatever app was in front instead of FreeCAD). Don't reach for it for
visual verification. If a real fix lands (targeting FreeCAD's window ID
via `screencapture -l` instead of the whole display), this note should be
revisited — but until then, skip it and ask the user to look at FreeCAD
directly, or verify via other means (object listings, property reads).

## Tool-use rule: prefer the primary MCP tool over execute_python

Don't use `execute_python` as a substitute for a dedicated MCP tool method
that already does the job (e.g. `Part.extrude()` via raw Python instead of
the `part_operations`/`partdesign_operations` extrude operation). The
primary methods carry validation, error handling, and thread-safety
guarantees (GUI-thread dispatch, etc.) that ad-hoc `execute_python` calls
don't.

- If a primary method exists for what you're doing, use it.
- If one doesn't exist but the operation is a real, recurring need (not a
  one-off), that's a signal to consider *adding* a primary method to
  freecad-mcp rather than reaching for `execute_python` as the permanent
  path.
- `execute_python` is for genuine one-offs and debugging (e.g. inspecting
  state, printing something to the Python console) — cases where a
  dedicated method shouldn't exist because the need is inherently ad hoc.
