# Full Review — freecad-mr-generators (whole project)

Pass ID: `freecad-mr-generators-20260808-a0b9`
Date: 2026-08-08
Scope: entire project (17 generators + shared/), partitioned into 3 groups for Phase 1/1.5 tractability: Siding/Trim/Label, Masonry/Shared, Roof. This is the third review pass on this repo — the first (2026-05-18) and second (2026-06-11) covered ashlar/shingle/brick/clapboard/bead_board/radial_brick; the third (2026-08-08, earlier this session) covered board_batten/label/quoin/roof_seam/shared/slate/slate_seam/smart_trim/snow_guard/standing_seam/standing_seam_snow_guard/station_sign. This pass is the first to cover the *whole* project in one sweep, specifically to catch gaps that fell between the first two passes' scopes (notably brick_generator's dual-quoin corner-merge, added after the 06-11 pass and never in scope for 08-08's pass).

## Summary

| Pass        | Critical | High | Med | Low | Status |
|-------------|----------|------|-----|-----|--------|
| Code review | 2 | 18 | 6 | 5 | ✓ ran (3 partitions × 5 angles) |
| Interface   | 0 | 1  | 0 | 1 | ✓ ran (fixed N=2, whole project) |
| Inventory   | 0 | 0  | 4 | 1 | ✓ ran (combined pass, 5 candidate files — see note) |
| Test review | 0 | 1  | 2 | 1 | ✓ ran |
| Coverage    | — | —  | 1 | — | ✓ ran (floor-check only) |
| **Total**   | **2** | **20** | **13** | **8** | 43 findings |

(Recomputed by counting each finding's `[phase]` tag directly in the body, per this review's own rule against incremental tallying — an earlier draft of this table had arithmetic errors.)

**Inventory scope note:** this repo's real external-data-ingestion surface is thin (local font-file existence checks and FreeCAD-spreadsheet cell reads, not APIs/DBs/queues). Rather than running the skill's full per-module N=3-Haiku pattern across 5 thinly-populated candidate files, I ran one combined 3-Haiku pass across all 5 together, then a single Sonnet severity re-pass. This is a disclosed proportionality choice (small, homogeneous surface area), not a silent cut — flagging per the Scope-Pressure Policy's spirit even though it's below the ~8-item threshold that would formally require it.

**Where each non-code-review pass earned its keep** (found something Phase 1 didn't, or independently corroborated a Phase 1 finding with new evidence):
- Interface check found `shared/freecad_utils.py`'s `commit_result()` is entirely dead code (zero real callers) — new.
- Interface check independently re-derived the `shingle_generator.FCMacro`/`shingle_proxy.py` fork from a pure boundary-consistency angle, plus found the macro also vendors its own `find_spreadsheet()` — a second concrete instance of the same fork.
- Test review **live-verified a surviving mutant** by actually mutating `brick_geometry.py:189`'s `<`→`<=` and rerunning the full suite — the test that claims to guard this boundary exercises a different, duplicated loop entirely. This is exactly the class of gap a "does a parity/boundary test exist" question alone would miss.
- Test review found `roof_seam_generator/tests/` exists as an empty directory — a stronger, more specific signal than "no tests" (someone intended to test it and never did).
- Inventory found the same-day Sources-consolidation fix (`492aa87`) missed `shingle_proxy.py` even though it's a structurally identical `obj.Sources` consumer to the 8 files it did fix — corroborated independently by both Phase 1 and Phase 2 finders.

---

## Critical

- [code] `radial_brick_generator/radial_brick_geometry.py:95` — `num_courses = max(1, int(self.surface_height / self.course_spacing))` floor-truncates with no downstream OCCT clip against the source face (unlike flat `brick_generator/brick_geometry.py`, which deliberately over-generates via `ceil(...)+2` and relies on clipping). Verified numerically by two independent review angles with matching results: `surface_height=30, course_spacing=0.76` → last brick top at 29.53mm, a 0.47mm gap (~72% of one course) left visibly bare at the top of every smokestack/silo/tower this generator produces. Triggers on nearly any realistic (non-exact-multiple) input — not a corner case. `[freecad-mr-generators-20260808-a0b9#01]`

- [code] `shingle_generator/shingle_generator.FCMacro` (entire ~950-line file) vs `shingle_generator/shingle_proxy.py` — two completely independent, non-interoperating implementations of the same generator. The macro never imports `ShingleProxy`/`ShingleViewProxy` and instead runs its own legacy pipeline building static `Part::Feature` objects, not the parametric `Part::FeaturePython` with a live `Sources` property that `shingle_proxy.py` defines. The macro is the *documented, default* entry point (README, unmarked as deprecated) — the parametric object type the rest of the codebase assumes for `shingle_generator` is never actually created by the supported workflow. Confirmed independently by the Phase-1 code review and both Phase-1.5 interface passes. Every High-severity shingle finding below is a direct downstream consequence of this split. `[freecad-mr-generators-20260808-a0b9#02]`

## High

- [code] `clapboard_generator/clapboard_proxy.py` (~lines 243-268) never imports or calls `clapboard_geometry.calculate_course_v_positions`, which adds an extra course and force-overflows both wall boundaries; the proxy's inline copy has neither, only a tight 1e-3mm coincidence snap. Found independently by all 5 review angles with matching concrete numeric examples (e.g. grid-snap rounding a wall boundary up leaves a real ~1.4mm strip of bare wall with no course covering it, no error). Gable trimming clips to the exact face boundary, so the shortfall becomes a visible model defect, not just a topological near-miss. `[...#03]`

- [code] `bead_board_generator/bead_board_proxy.py` (~lines 121-140) inlines its own bead/gap-position math instead of calling `bead_board_geometry.calculate_bead_positions`/`calculate_gap_positions`, which are TOPO_EPS-hardened against an OCCT segfault. No parity test exists. Per this repo's own CLAUDE.md rule, absence of a parity test for inlined geometry math is High by policy regardless of current numeric agreement. `[...#04]`

- [code] Neither `bead_board_proxy.py` nor `clapboard_proxy.py` calls its geometry module's `validate_parameters()` (siblings `board_batten_proxy.py`/`smart_trim_proxy.py` both do). `bead_gap >= bead_spacing` and `clapboard_thickness > clapboard_height` both reach OCCT with zero diagnostic. `[...#05]`

- [code] `board_batten_proxy.py`, `bead_board_proxy.py`, `clapboard_proxy.py`'s `vert_axis == 'y'` branch (used for horizontal/shallow-sloped faces — floors, porch decks, low-pitch roofs) hardcodes the face's constant coordinate to literal `0` instead of deriving it from `bbox`, unlike the sibling `vert_axis=='z'` branch in the same files. For any such face not coincidentally at that axis value, the generated skin is built completely detached from the real face; `board_batten`/`bead_board`'s `if trimmed.Volume > 0.001: fused = trimmed` guard then silently keeps the untrimmed, mispositioned shape on failure. `[...#06]`

- [code] `label_generator/label_proxy.py`'s `_FONT_CANDIDATES` (~lines 37-44) lists only macOS absolute paths; when none exist, `None` is assigned directly to the `FontPath` property with no fallback, producing an opaque "file not found: None" failure. A related prior finding was marked `wontfix` under a "single-user macOS-only personal tool" rationale that is now stale given this repo's stated open-source intent. `[...#07]`

- [code] `brick_generator/brick_geometry.py:139-149` — `_quoin_fill_end()` is dead code (confirmed via grep, only referenced by its own isolated unit test); the live right-quoin boundary math is a structurally different formula inline in `_generate_flemish_bond`. Two sources of truth, only one on the path OCCT actually consumes — the existing test gives false confidence. `[...#08]`

- [code] `brick_generator/brick_proxy.py:236-289` (`_resolve_quoin_flags`) plus the four new per-face `*QuoinPrimaryFaces`/`*QuoinSecondaryFaces` override properties (~245 new lines, commit `34b12c6`) have zero test coverage of any kind — no pytest, no FreeCADCmd integration test. The commit's "live-verified in FreeCAD" claim is a one-time manual check, not a regression guard; the module docstring's promise that existing documents with empty override lists stay "unaffected" is unverified. `[...#09]`

- [code] `shared/freecad_utils.py:379,397` (`_closest_candidate`) hardcodes `normalAt(0.5, 0.5)` instead of deriving the midpoint from `face.ParameterRange` the way `brick_proxy.py`'s own `_get_face_coordinate_system` correctly does elsewhere in this codebase. Misfires (or silently degrades to a zero-normal fallback) on non-planar/BSpline faces — exactly the kind this function's caller, `resolve_base_face`, exists to disambiguate. `[...#10]`

- [code] `brick_generator/brick_proxy.py` — no test asserts the merged quoin+fill brick population (`all_bricks + quoin_defs`, as actually fed to `.common()`/`.cut()`) strictly overflows the wall boundary, the exact OCCT-coincident-face-segfault invariant this repo's own CLAUDE.md Rule 2 requires. Existing tests check quoin-vs-fill non-overlap and zero-width bricks, not this downstream invariant. Corroborated independently by Test Review (see Medium `#37`). `[...#11]`

- [code] `shingle_generator/shingle_proxy.py:127` (`_clip_shape`) still uses the fixed `Volume > 0.001` survival threshold; siblings `slate_proxy.py`/`slate_seam_proxy.py`/`standing_seam_proxy.py` were all fixed to the fraction-based `is_valid_clip_fragment` after a documented real sliver-survival incident on a hip roof. `shingle_proxy.py` doesn't import the fix at all. `[...#12]`

- [code] `shingle_generator/shingle_proxy.py:376-379` — `execute()` calls `link_obj.Shape.getElement(sub_name)` outside its `try/except`, the exact bug a same-day commit (`492aa87`) fixed by name across 8 sibling proxies. `shingle_proxy.py` is a structurally identical `obj.Sources` consumer and was missed. `[...#13]`

- [code] `shingle_generator/shingle_generator.FCMacro:277,285` — the macro's own vendored `_get_face_coordinate_system` keys a `vertex_edge_count` dict by a raw FreeCAD `Vertex` wrapper object instead of a rounded-coordinate tuple — the exact bug a commit (`560ef1d`) fixed in 5 of 6 sibling copies. This is the unfixed 6th copy, live on the documented default workflow. `[...#14]`

- [code] `roof_seam_generator/roof_seam_proxy.py`'s `generate_hip_caps` — the **default** `hip_style='shingle'` path — divides by `d_raw.Length`/`local_x.Length` with no zero-length guard; two sibling functions in the same file (`generate_slate_hip_caps`, `generate_metal_hip_strip`) both have this guard. Unhandled `ZeroDivisionError` on degenerate hip/ridge geometry, on the default path. `[...#15]`

- [code] `roof_seam_generator/roof_seam_proxy.py`'s `classify_seam` falls back to `'hip'` on an `'ambiguous'` classification (PrintWarning only). `slate_seam_generator/slate_seam_geometry.py`'s `resolve_cap_eligibility`, written 10 days earlier against the identical shared classifier, explicitly *rejects* `'ambiguous'` with a documented rationale ("would risk silently capping an actual valley the one time this branch fires for real"). Two consumers of the same classifier reached opposite, unreconciled safety conclusions on the identical edge case. **Note:** one of the two Phase-1.5 interface reviewers judged this "deliberate and documented, not accidental drift" — I disagree with that read for the final severity call: each file's *own* choice was locally deliberate, but nothing establishes the two choices were cross-checked against each other, which is exactly the "each side individually reasonable, no mechanism enforces agreement" pattern this review's severity calibration says to rate High regardless. `[...#16]`

- [code] `slate_generator/slate_proxy.py:201` — `if row == 0 or butt_thick <= mat_thick:` silently substitutes `mat_thick` for the user's `ButtThickness` with no console message whenever the threshold holds; the property panel shows one value while the built geometry reflects another. `[...#17]`

- [code] `shingle_generator/shingle_generator.FCMacro:193-208` (`get_params_from_spreadsheet`) — bare `except:` swallows a malformed `float()` parse, silently drops the parameter, and misreports it to the user as "(default)" with no indication a real spreadsheet value was rejected. Corroborated independently by 3/3 Phase-2 inventory finders. `[...#18]`

- [code] `roof_seam_generator` has no `*_geometry.py` module at all and no `tests/` contents (directory exists, empty — confirmed by Test Review). Every sibling generator extracts threshold/loop math into a tested pure-Python module; this one inlines hip-cap, slate-hip-cap, metal-strip, and valley-flashing math directly in the proxy with zero test coverage, despite containing the `exposure<=0` guard whose own comment says getting it wrong hangs FreeCAD's GUI thread forever (a live incident this session) plus multiple other threshold/degenerate-guard patterns. `[...#19]`

- [code] `snow_guard_generator/snow_guard_proxy.py`'s `_build_guard_solid` and `standing_seam_snow_guard_generator/standing_seam_snow_guard_proxy.py`'s `_build_guard_solid` are duplicated near-verbatim; the latter's docstring explicitly asserts "identical" construction, but no test enforces that claim and the math was never extracted to either `*_geometry.py` module. `[...#20]`

- [interface] `shingle_generator/shingle_generator.FCMacro:135-169` vendors its own independent `find_spreadsheet()`, duplicating `shared/freecad_utils.py:748-821`'s implementation nearly identically — one more concrete instance of the FCMacro/proxy fork (`#02`), corroborated by 3/3 Phase-2 inventory finders. `[...#21]`

- [test] `brick_generator/brick_geometry.py:189` — **confirmed surviving mutant**, live-verified: mutating `while closer_width < min_closer` to `<=` and rerunning the full 114-test brick suite left every test passing. The test whose docstring claims to guard this exact boundary (`test_flemish_closer_at_min_closer_boundary`) actually exercises a different, independently-duplicated loop in the flemish-bond path, not this one. `[...#22]`

## Medium

- [code] `brick_generator/brick_proxy.py:224-233` (`_face_index_set`, new) and `:622` (pre-existing) both reimplement raw `int(sub_name[4:]) - 1` index arithmetic with no try/except, outside `execute()`'s main try block — unswept by the same-day Sources-consolidation fix (different consumer shape, not a drop-in swap). A malformed/extended `sub_name` (e.g. FreeCAD 1.0+ TNP-style names) would raise uncaught rather than following the graceful per-face error path used elsewhere. `[...#23]`
- [code] `ashlar_generator/ashlar_proxy.py` — no minimum-value validation on `NCols`/`NRows`/`StoneWidth`/etc.; `NCols<=0` drives a negative wall width into `Part.makeBox`, only guarded by a broad `except Part.OCCError` that wouldn't catch silent normalization. `[...#24]`
- [code] `brick_generator/brick_generator_macro.FCMacro:40,52-53` — only `sel[0]` is used; faces ctrl-selected on additional objects are silently dropped with no warning, unlike the sibling radial-brick macro. `[...#25]`
- [code] `quoin_generator/tests/test_quoin_geometry.py`'s `TestFillStartParity` covers only the left-quoin case; `mirror_to_right_edge()` (right-quoin) has no parity test against its comparison target — itself dead code (`#08`), so this test's practical protective value is lower than a true live-vs-live gap; currently numerically consistent but unpinned. `[...#26]`
- [code] `roof_seam_proxy.py`'s `classify_seam` docstring/commit message mislabels the shared classifier as "the dihedral-angle classifier" when it's a pure Z-average heuristic — dihedral angle is computed separately and never feeds the hip/valley decision, only display text. Relevant context for `#16`. `[...#27]`
- [code] `bead_board_proxy.py`/`clapboard_proxy.py` hand-roll their own `obj.Sources`→`Face` resolution loop instead of the shared `resolve_sources_faces()` helper; verified currently correctly-shaped (not among the instances the original consolidation fix found broken) — flagged as maintenance-drift risk, not a live defect. `[...#28]`
- [inventory] `shared/freecad_utils.py`'s `find_spreadsheet()` (and the macro's duplicate, `#21`) silently falls through when a Link's target `TypeId` doesn't match `Spreadsheet::Sheet` — indistinguishable from "no spreadsheet found." `[...#29]`
- [inventory] `shingle_generator.FCMacro`'s spreadsheet parameter reading has no found/skipped/unparseable accounting across its ~10 recognized cell names — compounds `#18`. `[...#30]`
- [inventory] `shared/freecad_utils.py`'s `resolve_font_path()` only checks `os.path.exists()`, not that the target is a valid font file — surfaces as an opaque `Part.makeWireString()` error rather than a clear message at resolution time. `[...#31]`
- [inventory] `shingle_generator.FCMacro`'s `shingleStaggerPattern` spreadsheet value is accepted as any string with no closed-set validation before storage; whether a downstream check actually rejects a typo is unconfirmed. `[...#32]`
- [test] `brick_generator/brick_geometry.py:508` — the flemish-bond closer-width boundary test's "exact boundary" input lands at `0.22000000000000028` instead of `0.22` (float precision), so `>=` vs `>` can't actually be discriminated there either — live-verified alongside `#22`. `[...#33]`
- [test] `brick_generator`'s dual-quoin test classes never call `assert_overflows_boundary`/`assert_no_boundary_coincidence` against the merged quoin+fill population that `brick_proxy._create_mortar_grid` actually feeds to OCCT — the test-coverage restatement of `#11`. `[...#34]`
- [coverage] `install.py` — 0% coverage. Argparse/subprocess-heavy installer logic, including this session's new FreeCADCmd path-detection fallback chain and numpy/scipy dependency check — manually verified via `--list` this session but has no automated regression test. `[...#35]`

## Low / Nit

- [code] `brick_generator/brick_geometry.py`'s `_calculate_course_layout` narrow-wall fallback (`closer_width` clamped to 0 when `n_bricks==1`) is undocumented, unlike flemish's documented equivalent; relies on the existing OCCT-clip safety net. `[...#36]`
- [code] `brick_proxy.py:48-54` docstring describes `quoin_proxy.py` as still existing ("touch-up path") — deleted by a later same-day commit, never updated. `[...#37]`
- [code] `brick_proxy.py:535` `LeftQuoin` tooltip uses stale "reservation" terminology from the deleted two-pass design. `[...#38]`
- [code] `brick_generator/brick_geometry.py:2` vs `:15` vs `:19` — module docstring version fields disagree with each other (5.0.2/5.0.1/5.0.2). `[...#39]`
- [code] `shingle_generator/shingle_geometry.py`'s `should_clip_shingles` has an untested threshold but is confirmed dead code (zero callers) — latent, not live. `[...#40]`
- [interface] `shared/freecad_utils.py`'s `commit_result()` is dead code — zero real callers repo-wide, only a dead import in `shingle_generator.FCMacro`. `[...#41]`
- [inventory] `station_sign_generator/station_sign_proxy.py` prints the same `_FONT_HELP` warning twice (module load + `execute()`) with no suppression — cosmetic console-noise duplication. `[...#42]`
- [test] `brick_generator`'s `_calculate_course_layout` — two clamp branches (`n_bricks<1`, `closer_width<0`) uncovered per the coverage report. `[...#43]`

---

**Test Stats** — pass:980 fail:0 mutants:2/2 surviving tautology:0

**Where interface/inventory/test earned their keep, restated:** the surviving-mutant finding (`#22`) and the empty `roof_seam_generator/tests/` directory (`#19`) are things a pure code-review pass would not have surfaced — both required actually running the suite/mutating code rather than reading it. The `shingle_generator.FCMacro`'s independent `find_spreadsheet()` (`#21`) and the Sources-`getElement()`-outside-try (`#13`) were each caught by two structurally different passes (code review and interface/inventory) independently, which is exactly the kind of convergent signal this review's design is meant to produce.

---

## Final Disposition

All 43 findings fixed. Final suite after all fixes: **1094 passed, 2 skipped** (up from 980 at the start of the pass).

**Commit `6dfad6c` — Critical (2 findings), plus 5 High findings closed as direct consequences:**
`#01` (radial_brick undercoverage, fixed via `ceil(...)+1`), `#02` (`shingle_generator.FCMacro`/`shingle_proxy.py` fork — macro rewritten to the standard proxy-based pattern used by every other generator), `#12` (`shingle_proxy._clip_shape` fraction-based threshold), `#13` (`shingle_proxy` `resolve_sources_faces` wiring), `#14` (moot — the macro's own vendored vertex-dict bug no longer exists), `#18` (moot — the macro's bare-except spreadsheet reader removed), `#21` (moot — the macro's duplicate `find_spreadsheet()` removed).

**Commit `d6a63bc` — High (20 findings):**
`#03`–`#11`, `#15`–`#17`, `#19`, `#20`, `#22` fixed directly. `#27` (classify_seam docstring) and `#34` (dual-quoin merged-boundary test) closed as side effects of `#16` and `#11` respectively. `#33` (flemish boundary-test float-precision gap) fixed as a direct extension of the `#22` mutation-testing work.

**Commit `2729a8d` — Medium (13 findings):**
`#23`–`#26`, `#28`, `#29`, `#31`, `#35` fixed directly. `#27` and `#34` already closed above. `#30` and `#32` became moot (both lived in code the Critical-tier macro rewrite removed entirely).

**Commit `c9d3d00` — Low (8 findings), fixed on a follow-up request ("no good reason not to fix the lows too"):**
`#36`/`#43` (undocumented + untested narrow-wall clamp in `_calculate_course_layout` — documented and given `TestCalculateCourseLayoutNarrowWallClamps`), `#37`/`#38` (stale `quoin_proxy.py`-era docstring/tooltip text in `brick_proxy.py`), `#39` (brick_geometry.py version-header drift), `#40` (`should_clip_shingles`/`calculate_shingle_clip_volume` — deleted as confirmed dead code rather than tested), `#41` (`commit_result()` — deleted as confirmed dead code, `shared/freecad_utils.py` bumped to v1.6.0), `#42` (station_sign's `_FONT_HELP` warning — suppressed to fire once per session from `execute()` instead of every recompute; live-verified via FreeCADCmd: 3 recomputes → 1 warning, was 3).
