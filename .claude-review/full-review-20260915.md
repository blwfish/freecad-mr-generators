# Full Review — freecad-mr-generators (entire repository)

**Pass ID:** `freecad-mr-generators-20260915-e612`
**Scope:** entire repository — 17 generators (ashlar, bead_board, board_batten, brick, clapboard, label, quoin, radial_brick, roof_seam, shingle, slate, slate_seam, smart_trim, snow_guard, standing_seam, standing_seam_snow_guard, station_sign), `shared/`, `tests/`, `install.py`
**Date:** 2026-09-15
**Prior full-project pass:** `freecad-mr-generators-20260808-a0b9` (43 findings, all resolved) — 5 bug-fix commits landed since then (brick quoin boundary, roof hip-line classification, slate wedge-tile stub, slate-seam cap clearance, ReverseQuoinSides)

## Summary

| Pass        | Critical | High | Med | Low | Status |
|-------------|----------|------|-----|-----|--------|
| Code review (9 angles) | 2 | 7 | 8 | 12 | ✓ ran |
| Interface   | 0 | 2 | 1 | 0 | ✓ ran |
| Inventory (4 modules) | 0 | 1 | 6 | 26 | ✓ ran |
| Test review | 1 | 3 | 1 | 0 | ✓ ran |
| Coverage    | — | — | 0 | — | ✓ ran (81% overall, no 0%-coverage files) |

Raw per-phase severity re-pass total (each phase's own count, before cross-phase merging): **3 Critical, 13 High, 16 Medium, 38 Low (70 raw findings)**. Several of these were independently discovered by more than one phase — see "Cross-phase corroboration" below — and are merged into a single write-up below rather than listed twice. **After merging, the report body and the review ledger below track 43 distinct findings: 3 Critical, 11 High, 12 Medium, 17 Low.** (The table above intentionally still shows each phase's own raw count — that is what demonstrates each phase's independent yield — but it is a different number from the deduped total that everything else in this document, and the ledger, uses.)

Full test suite: **1248 passed, 7 skipped, 0 failed** (at review time; see "Fix Status" at the end of this document for the post-fix count).

---

## Critical

- **[code]** `ashlar_generator/ashlar_geometry.py:156` — `z_values /= n_fractures`. `NFractures` is an unvalidated, UI-reachable `PropertyInteger` (one decrement from the default of 3). `NFractures=0` triggers a silent numpy divide-by-zero producing NaN across the **entire** stone surface array (not just a boundary strip), feeding directly into `Part.makePolygon`/`Part.Face` in `_build_stone_solid`. [`freecad-mr-generators-20260915-e612#01`]

- **[code]** `ashlar_generator/ashlar_geometry.py:252` — `TOPO_EPS = joint_width * 0.1` evaluates to exactly `0.0` when `JointWidth == 0`, which the codebase's **own tests** (`test_joint_width_zero_is_valid`) explicitly declare legal. `TOPO_EPS == 0` makes the boundary-overflow nudge a no-op, so boundary stone faces land exactly coincident with the wall boundary and feed straight into `ashlar_proxy.py:117`'s `base.cut(compound_cut)` — precisely the OCCT coincident-boundary-face crash class this repo's own CLAUDE.md documents. `test_wall_covers_all_stone_positions` never exercises `joint_width=0.0`. [`freecad-mr-generators-20260915-e612#02`]

- **[test]** `brick_generator/brick_geometry.py:442` — `num_courses = math.ceil(v_length / course_spacing_v) + 2`. Manually mutating `+2` → `+1` **survives the entire 261-test brick suite unchanged**. Root cause: `TestBoundaryOverflow` — this repo's own CLAUDE.md-cited canonical example of good boundary testing — only asserts the overflow invariant on the **U** (horizontal, per-course) axis; the analogous **V** (vertical, course-count) axis is never checked. This is the exact OCCT-coincidence risk class the file's own docstring warns about, hiding on the one axis the "model" test doesn't cover. [`freecad-mr-generators-20260915-e612#03`]

## High

- **[code]** `ashlar_generator/ashlar_geometry.py:173` — `taper = np.clip(dist_from_edge/edge_taper, 0, 1)`. `EdgeTaper` is an unvalidated `PropertyFloat`; `EdgeTaper=0` divides by zero, producing NaN at every boundary grid point, guarded only by a bare `except Part.OCCError: pass` — boundary triangles silently vanish instead of raising. [`...#04`]

- **[code]** `clapboard_generator/clapboard_geometry.py:275-297` + `clapboard_proxy.py:18,158` — parameter validation never checks `ClapboardThickness` against the proxy-side `CLAPBOARD_TRIM_OFFSET` (0.05mm). The **default** thickness is 0.2mm — only 4x the danger threshold, a plausible fat-finger. A thickness in (0, 0.05) makes `actual_thick` negative, silently flipping the outer-wire offset direction (clapboard recessed into the wall instead of projecting outward), with no exception raised. [`...#05`]

- **[code]** `label_generator/label_proxy.py:92-118` — a byte-for-byte re-implementation of a mutual-bounding-box-containment bug: when two glyph-contour wires have equal/near-equal bounding boxes, **both are silently dropped** (neither is ever classified as "outer"). Confirmed by direct execution. This is the exact failure mode `station_sign_generator/station_sign_geometry.py`'s own docstring says was fixed by *extracting* this logic out of a proxy in 2026-08-08 specifically because inline FreeCAD-wire logic had "zero verification of any kind" — `label_proxy.py` still has that pre-fix pattern, with zero test coverage of any kind (no `label_geometry.py` counterpart exists to even write a test against). The related, lower-risk instance of the same root-cause function is `station_sign_generator/station_sign_geometry.py:68-88` — rated **Medium** rather than High because that module has real (if incomplete) test coverage of the containment logic; fixing it there does not fix `label_proxy.py`'s independent copy. [`...#06`, sub-finding `...#06b` for the station_sign instance]

- **[code]** TOPO_EPS / boundary-nudge concept independently re-derived 6+ times with no shared mechanism and divergent magnitudes: `slate_geometry.py:141`, `board_batten_geometry.py:189`, `ashlar_geometry.py:252`, `brick_geometry.py:250-259` (the best instance — a named, documented "single source of truth," but only within `brick_generator/`), `clapboard_geometry.py:197`, `bead_board_geometry.py:164`, `slate_seam_geometry.py:274-287` (a 6th, structurally different over-generate-and-clip tactic). Confirmed live anti-pattern: `quoin_generator/quoin_geometry.py:58` already does `from brick_geometry import BrickDef` in the *same file*, yet re-derives its own `_TOPO_EPS_FACTOR = 0.1` at line 60 instead of importing `brick_geometry.topo_eps()` — the author had the fix one import away and didn't take it. No shared mechanism enforces any of these stay in sync. [`...#07`]

- **[code]** Degenerate/duplicate-edge validation (`check_for_degenerate_edges`/`check_for_duplicate_edges`, duplicated near-identically in `clapboard_geometry.py:23-51`, `board_batten_geometry.py:227-260`, `bead_board_geometry.py:209-260`) exists and is pytest-covered, but **`board_batten_proxy.py` and `bead_board_proxy.py` never call it or any equivalent** — confirmed via grep, zero references. The validation exists to guard exactly the OCCT-crash class this repo's CLAUDE.md flags as historically causative, and it silently never runs for 2 of the 3 sibling generators that share this wire-construction pattern. [`...#08`]

- **[code+test]** `brick_generator/brick_proxy.py:645-646` inlines `course_spacing_v = gen_bh + mortar; num_courses = ceil(v_length/course_spacing_v)+2` — textually identical to `BrickGeometry.__init__`'s own `self.course_spacing_v`/`self.num_courses` (`brick_geometry.py:439,442`), which is already computed and available nearby. Currently equivalent only because the call site happens to pass matching arguments; no test asserts the two stay in sync. Independently found by both the code-review pass and the test-review pass, in the most actively-developed generator in the repo (5 of the last 5 commits touch brick/quoin logic). [`...#09`]

- **[code+interface]** `clapboard_proxy.py:89`, `board_batten_proxy.py:51`, `bead_board_proxy.py:54` — `_detect_orientation()` is an independent inline copy of the sibling `*_geometry.py`'s `detect_face_orientation()`, but uses strict `<` at the 0.1mm tolerance boundary where the geometry module uses `<=`. **Execution-confirmed** by the interface-check pass: `x_extent=0.1, y_extent=0.05` produces the *opposite* axis classification between the two implementations. No parity test exists for the proxy side in any of the three. The interface-check pass notes the specific trigger is a razor-thin, effectively-unreachable value for real OCCT bounding boxes — but this repo's own CLAUDE.md rule is explicit that "the absence of a parity test for any proxy that inlines geometry math is a High finding, not a gap to defer," independent of how often the divergence actually fires. [`...#10`]

- **[interface]** `_get_face_coordinate_system()` duplicated near-verbatim across 5 proxies (`shingle_proxy.py:46`, `slate_proxy.py:46`, `snow_guard_proxy.py:47`, `standing_seam_proxy.py:45`, `standing_seam_snow_guard_proxy.py:62`) rather than living in `shared/`. This function's name collides with the genuinely-shared `shared/freecad_utils.get_face_coordinate_system()` that `brick_proxy.py` already correctly delegates to (documented 2026-09-14 consolidation) — a naming trap for future readers. Cosmetic drift has already started (`shingle_proxy.py` uses `_scale_vector`, the other four use `_sv`). *Note: the code-review pass's own severity re-pass initially rated this Medium ("core math already centralized, only the adapter is duplicated"). The interface-check pass's independent re-pass rated it High, applying this project's explicit calibration rule that a boundary "consistent by convention with no catching mechanism" rates High regardless of current agreement. We report High here as the better-justified reading of the skill's own stated rule — flagging the disagreement for transparency rather than silently picking one.* [`...#11`]

- **[test]** `clapboard_generator/clapboard_geometry.py:247-250` and `261-269` — two independent boundary-safety mechanisms (an in-loop `topo_eps` snap and a post-loop unconditional overflow guarantee). Disabling **either one alone** leaves all 39 tests in the suite passing — including `test_post_loop_guarantee_is_load_bearing`, whose own docstring explicitly (and, it turns out, falsely) claims "removing the block would leave OCCT exposed." That claim only holds when *both* mechanisms are removed together. Each individually is an unattributed surviving mutant. [`...#12`]

- **[test]** `bead_board_generator/bead_board_geometry.py:194-201` — the `abs(...) < topo_eps` boundary-coincidence snap (4 occurrences). Flipping all four `<` to `<=` survives the full 35-test suite, including a *dedicated* mutation-guard test (`test_snap_fires_at_exact_topo_eps_from_boundary`) whose docstring explicitly claims to pin this exact distinction. Root cause: floating-point — the test computes `gap_start = (topo_eps + half_gap) - half_gap`, expecting exactly `topo_eps` (0.001), but actually gets `0.0010000000000000009` (strictly *above* topo_eps under either operator), so the mutation is never exercised. **This test itself violates this repo's own Threshold-Boundary Testing Rule** ("use exact arithmetic and `abs=1e-6`... near a boundary"). [`...#13`]

- **[test]** No `assert_overflows_boundary`/`assert_no_boundary_coincidence` test coverage exists for `shingle_generator`, `slate_generator`, or `standing_seam_generator`, despite all three tiling a bounded face and feeding the result into `shape.common(cv)` — the exact OCCT operation this repo's CLAUDE.md table flags as segfault-risk on coincident boundaries (`shingle_geometry.py:134,150` → `shingle_proxy.py:136`; `slate_geometry.py:158,168` → `slate_proxy.py:117`; `standing_seam_geometry.py:108` → `standing_seam_proxy.py:118`). Not independently verified whether `roof_seam`, `ashlar`, `radial_brick`, `quoin`, `smart_trim`, `station_sign`, or `label` have the same gap (out of this pass's spot-check scope). [`...#14`]

## Medium

- **[code]** `station_sign_generator/station_sign_geometry.py:68-88` — the root-cause, tested-but-incompletely version of `#06`'s mutual-bbox-containment bug. Confirmed live by direct execution. Rated Medium rather than High because a real (if incomplete) test file exists for the containment logic — the gap is a missing edge-case parametrization, not an invisible-to-CI duplicate. [`...#15`]

- **[interface]** `install.py:28` (`GENERATORS` list) — the existing regression test (a pin for a past incident where `ashlar_generator` was silently omitted from install) only checks one direction: every *listed* entry has a directory. No test checks the reverse — every on-disk generator directory is present in the list. Confirmed the list currently matches all 17 directories exactly (no live mismatch today); the gap only bites on the rare, discrete event of adding a new generator, and the failure mode (macro absent from FreeCAD's menu) is loud and self-evident rather than silent wrong output. [`...#16`]

- **[code]** Same-file duplication of a ~20-line hip-edge local-coordinate-frame computation, 3x within `roof_seam_generator/roof_seam_proxy.py` (`generate_hip_caps:136-181`, `generate_slate_hip_caps:390-411`, `generate_metal_hip_strip:452-473`). No cross-testability gap (all three copies live in one already-tested-as-a-unit proxy file), so it's a real reuse/maintenance-cost finding rather than a boundary-agreement risk. [`...#17`]

- **[code]** `_face_normal`/`_face_normal_at_center` one-liner duplicated across 6 proxies (`clapboard_proxy.py:84`, `board_batten_proxy.py:46`, `bead_board_proxy.py:49`, `radial_brick_proxy.py:34`, `roof_seam_proxy.py:50`, `slate_seam_proxy.py:85`) **and already exists 3x inline inside `shared/freecad_utils.py` itself** (the file meant to be the single source of truth). Low intrinsic divergence risk (trivial formula) but a real "reapply the fix 9x" cost. [`...#18`]

- **[code]** `shared/corner_detection.py` (whole 222-line module) has zero callers anywhere in production code — confirmed via grep — yet `brick_proxy.py:87,787-788` narrates its "automatic corner-pairing" in comments as if it were live, active behavior. Rated above plain dead code because the misleading comments are a documentation-accuracy hazard: a future engineer could reason about behavior that doesn't actually run. [`...#19`]

- **[code]** `smart_trim_generator/smart_trim_proxy.py:70-71,152-153` — `_get_document_centroid(doc)` (an O(document-objects) loop computing `CenterOfMass` for every solid) is called twice per selected face, despite being invariant across the whole `execute()` call — up to 2×N×M redundant mass-property computations. `execute()` is the main FreeCAD recompute path, re-run on every property tweak during interactive design. [`...#20`]

- **[code]** `smart_trim_generator/trim_geometry.py:573` (`cut_size=200.0`) and `roof_seam_generator/roof_seam_proxy.py:264` (`block_size=200.0`) — hardcoded "big enough" half-space/cutting-block extents, not derived from the actual solid's `BoundBox` and with no self-check that the constant actually dominates the geometry being cut. Failure mode is silent wrong geometry (an incomplete cut), not a crash; 200mm model-space (~17.4m at HO 1:87 scale) is plausibly exceeded by larger prototype structures in this repo's own domain. [`...#21`, `...#22`]

- **[inventory]** `shared/freecad_utils.py:789-807` (`resolve_font_path`) — no file-readability or integrity check; a file that exists, has the right extension, but is unreadable or corrupted bypasses this function's own stated purpose (distinguishing *why* no usable font was found) and fails opaquely later inside `Part.makeWireString`. Real exposure: 2 live call sites (`label_proxy.py`, `station_sign_proxy.py`). Rare in practice (local desktop font files) but the mechanism is live. [`...#23`]

- **[inventory]** `install.py:174,189` — `glob()` over each `GENERATORS`-list directory has no existence/error check; a missing or misspelled generator directory is silently dropped from the install with zero indication, though the script still reports success. Self-limiting (the user notices a missing macro in FreeCAD's Tools menu fairly quickly). [`...#24`]

- **[inventory]** `install.py:184` — `SHARED_DIR.glob("*.py")` silently returns empty if `shared/` doesn't exist. Higher potential stakes than `#24` (would cascade into multiple broken generators) but the trigger condition (repo genuinely missing `shared/`) is very unlikely outside an already-broken checkout. [`...#25`]

- **[inventory]** `label_proxy.py:79,115` / `station_sign_proxy.py:139-140,153-154` — bare `except Exception:` around `Part.Face()` construction in the glyph-to-face conversion path, with zero logging of which character/wire failed. Rarer trigger than the mutual-bbox bug above, but when it fires there is no console trace at all. [`...#26`]

## Low

*(38 findings — grouped by theme; individual file:line detail available in the phase-notes appendix on request. IDs `...#27` through `...#64`.)*

- **Dead code** (10 findings) — `shared/freecad_utils.py:152,204,240` (3 fully unreferenced public functions, even by tests); `smart_trim_generator/trim_geometry.py:200` (`filter_corners_for_trim`, dead but currently-safe duplicate — `CornerType` has exactly 3 members so no live divergence is possible today); `shingle_generator/shingle_geometry.py` (6 dead functions — the one dangerous case, `calculate_shingle_position`, already has a dedicated parity test, `TestShinglePositionProxyParity`, so this drift is known and tested-around, not hidden); `clapboard_generator/clapboard_geometry.py`, `board_batten_generator/board_batten_geometry.py`, `bead_board_generator/bead_board_geometry.py` (an identical set of 3 dead "starter kit" helpers copy-pasted across all three sibling generators, none ever wired up); `shared/freecad_utils.py:815-900` (`find_spreadsheet` — confirmed zero callers anywhere including its own tests, more orphaned than initially believed; unclear if meant to be wired up); stale comments citing the already-deleted `quoin_proxy.py` in 4 locations.

- **Structural boilerplate duplication** (2 findings) — 16x near-identical `XxxViewProxy` class (~300 duplicated lines, no shared base/factory); 134x repeated `if not hasattr(obj,'X'): obj.addProperty(...)` block across 15 proxy files, no shared helper. Pure style — no logic to diverge.

- **Efficiency, low-stakes** (3 findings) — `brick_proxy.py`'s 3x-per-face `_get_face_coordinate_system()` recomputation is a *deliberate* correctness-coupling choice per its own comment (verified, not a bug — not worth "fixing" at the cost of the coupling guarantee it buys); `label_proxy.py:232-240`'s double glyph tessellation in the auto-fit path (bounded to once per recompute, short strings); `roof_seam_proxy.py`'s `1e-6` literal repeated 6x with no named constant (style nit, not a semantic-drift risk).

- **Docstring/comment accuracy** (1 finding) — `clapboard_geometry.py:222-224` docstring claims a strict `<` guarantee the implementation delivers as `≤`; confirmed to carry no live risk (the epsilon involved is 1000x larger than the invariant-checker's own default tolerance).

- **Inventory diagnosability nits** (22 findings, across `install.py`, `shared/freecad_utils.py`, `label_proxy.py`, `station_sign_proxy.py`) — subprocess stderr never logged; JSON-parse heuristics with no schema validation (but existing broad exception handlers already catch the failure modes); batch loops (`install.py` copy/uninstall) that crash loudly with a full traceback on first failure rather than continuing silently — this was independently reported two different ways by different finder passes and was resolved by direct verification to be "loud crash," not "silent continue"; error messages that omit the font path actually attempted; a hardcoded user-specific home-directory font path in `station_sign_proxy.py` that turned out, on inspection, to already have deliberate, well-documented fallback guidance printed to the user (not a blind hardcode); `find_first_existing_path()` using `os.path.exists()` where its sibling `resolve_font_path()` uses `os.path.isfile()` — a real inconsistency, but traced through both live call sites and confirmed non-exploitable today (both callers always re-gate through the stricter function before the value reaches `Part.makeWireString`).

---

## Cross-phase corroboration

These findings were independently surfaced by more than one review pass — the strongest signal in this run that something is real, not noise:

- **`_detect_orientation` `<`/`<=` divergence** (`#10`) — found independently by the code-review pass (angles 6 and 12) *and* the interface-check pass, which additionally supplied a concrete execution-verified counterexample.
- **`_get_face_coordinate_system` 5x duplication** (`#11`) — found independently by the code-review pass (angle 6) and the interface-check pass; the two passes disagreed on severity (Medium vs. High) — resolved in favor of High per the skill's own stated calibration rule (see finding text).
- **`brick_proxy.py` inlined `course_spacing_v`/`num_courses`** (`#09`) — found independently by the code-review pass and the test-review pass.
- **Mutual-bbox-containment silent glyph loss** (`#06`/`#06b`/`#15`) — found independently by the code-review pass (general-correctness and CLAUDE.md-compliance angles both, from different angles: one found the live bug, the other found the duplicated-untested-pattern).
- **`TOPO_EPS` divergence family** (`#07`) — found independently by two code-review angles (reuse and altitude) *and* concretely instantiated as a live bug by a third (general correctness, the ashlar `joint_width=0` case, `#02`).
- **Degenerate/duplicate-edge validation never called** (`#08`) — found independently by the code-review pass (CLAUDE.md-compliance angle) and corroborated by the test-review pass's parity-gap check on the sibling `clapboard_proxy.py` case.

None of the four passes came up empty — interface, inventory, and test review each surfaced findings the code-review pass's nine angles did not (the interface pass's execution-verified orientation bug; the entire inventory pass's diagnosability/portability findings in `install.py` and the font-resolution helpers; the test pass's three surviving mutants, none of which the code-review angles' manual reading caught).

## Test Stats

`pass:1248 fail:0 mutants:0/3-killed(all 3 attempted mutations survived) tautology:0`

## Coverage

Coverage run: 81% overall. Coverage is a floor-check only — nonzero coverage does not indicate the tests assert anything meaningful; see the surviving-mutant findings above for that. No files at literal 0% coverage (all `*_proxy.py` are structurally excluded from measurement by `.coveragerc`, by design, since plain pytest cannot import FreeCAD). Lowest-covered measured files: `smart_trim_generator/trim_geometry.py` (14%), `install.py` (41%).

---

## Fix Status (post-review)

At the user's request, Critical, High, and Medium findings were fixed in this session, committed as three separate commits (one per severity tier), each listing the specific findings it closes:

| Tier | Fixed | Deferred | Commit |
|------|-------|----------|--------|
| Critical | 3/3 | 0 | `09f64de` |
| High | 10/11 | 1 (`#14`) | `5571cca` |
| Medium | 12/12 | 0 | `6191ab2` |
| Low | 0/17 | 17 | — (out of requested scope) |

**Deferred, not fixed:**
- **`#07`** (TOPO_EPS family) — the specific named anti-pattern (`quoin_geometry.py` ignoring its own already-imported `brick_geometry.topo_eps()`) is fixed. The broader cross-generator consolidation (slate/board_batten/clapboard/bead_board/ashlar/slate_seam each independently re-deriving a boundary-nudge constant) was judged too large and risky to attempt safely without live FreeCAD verification in this session — logged as remaining follow-up work, not silently dropped.
- **`#14`** (missing boundary-coincidence test coverage for shingle/slate/standing_seam) — closing this properly requires first extracting each proxy's inlined position math into its geometry module, a larger refactor than "add a test."
- **`#19`** (`corner_detection.py` dead code) — the misleading comments describing it as live are fixed; the module itself remains unwired (deleting it or wiring it in is a design decision, not requested).
- All 17 Low findings — out of the requested fix scope for this pass.

**Verification caveats:** every FreeCAD-dependent proxy change (`*_proxy.py` files) could not be executed against real FreeCAD in this session — `FreeCADCmd` was unavailable (confirmed absent, not assumed). These changes were verified by: AST syntax checks on every edited file; direct diff against a previously-working sibling implementation before consolidating (for the 5x/6x/3x duplication fixes, confirming functional equivalence rather than assuming it); and, where a pure-Python path existed (validation logic, boundary-position math, the bbox-containment algorithm), live execution and mutation testing. All pure-Python test suites pass: **1295 passed, 7 skipped, 0 failed** (up from the review-time 1248 passed — the +47 are new regression/parity/mutation-guard tests added alongside the fixes).

Full diffs are in commits `09f64de`, `5571cca`, `6191ab2` on branch `dev`. See `.claude-review/ledger.jsonl` for the structured, per-finding disposition record.
