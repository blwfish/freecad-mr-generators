# freecad-mr-generators

Parametric FreeCAD generators for model railroad structure detailing. Select faces on a wall or roof in FreeCAD, run a macro, and the generator applies realistic surface detail—shingles, clapboard siding, brick coursing, metal roofing, and more—as a live parametric object. Change any property in the Properties panel and the geometry regenerates instantly.

## Contents

- [How it works](#how-it-works)
- [Generators](#generators)
- [Requirements and platform notes](#requirements-and-platform-notes)
- [Installation](#installation)
- [Workflow](#workflow)
- [Generator reference](#generator-reference)
- [Scales](#scales)
- [Contributing](#contributing)

---

## How it works

These generators operate on **faces**—the flat or curved surfaces of a solid in your FreeCAD model. You select one or more faces (click a surface while holding Ctrl to add more), run a macro, and the generator creates a new parametric object sitting on top of those faces.

The key property of every generator is that it is **non-destructive**: your original wall or roof geometry is untouched. The generator output is a separate object you can hide, export, or delete independently.

All dimensions are in **millimetres**, at the real-world prototype scale you are working in. See [Scales](#scales) for how to adapt to your scale.

---

## Generators

| Macro | Surface | What it produces |
|---|---|---|
| `bead_board_generator` | wall faces | Beadboard panelling — vertical boards with recessed bead grooves |
| `board_batten_generator` | wall faces | Board-and-batten siding — wide vertical boards with narrow battens over the joints |
| `brick_generator_macro` | wall faces | Brick coursing engraved into the wall — stretcher, English, Flemish, or common bond |
| `clapboard_generator` | wall faces | Clapboard (lap) siding — horizontal overlapping boards |
| `radial_brick_generator_macro` | cylindrical/conical faces | Brick coursing on curved surfaces (silos, towers, round bays) |
| `roof_seam_generator` | two adjacent roof faces | Hip caps and valley flashing at the seam between two roof planes |
| `shingle_generator` | roof faces | Wood shingles with butt-edge taper and stagger |
| `slate_generator` | roof faces | Flat slate tiles with course overlap and stagger |
| `smart_trim_generator` | wall faces | Window and door trim — rectangular or beveled profile |
| `standing_seam_generator` | roof faces | Standing-seam metal roofing panels |
| `station_sign_generator` | *(none)* | Raised-letter station sign board for 3D printing |

---

## Requirements and platform notes

- **FreeCAD 1.0 or later.** Tested primarily on weekly development builds. The generators use the FeaturePython parametric object system.
- **Python 3.x**, bundled with FreeCAD—no separate install needed.

**Platform:** Developed and tested on macOS. The installer detects macOS, Linux, and Windows paths, and the generators themselves use only standard FreeCAD APIs, so they should work on any platform FreeCAD runs on. That said, Linux and Windows are untested. If you run into platform-specific issues, please open an issue or submit a PR.

---

## Installation

```bash
git clone https://github.com/blwfish/freecad-mr-generators
cd freecad-mr-generators
python3 install.py
```

Restart FreeCAD. Macros appear in **Tools → Macros**.

**What the installer does:**
- Copies `*.FCMacro` files to your FreeCAD user macro directory
- Copies the Python library to `FreeCAD/Mod/fc_generators/`, which FreeCAD adds to its Python path automatically on startup

**Preview before installing:**
```bash
python3 install.py --list
```

**Override paths** (if FreeCAD is installed non-standardly):
```bash
python3 install.py --macro-dir /path/to/Macro --mod-dir /path/to/Mod
```

**Uninstall:**
```bash
python3 install.py --uninstall
```

---

## Workflow

The general pattern is the same for every generator:

1. **Build your structure** in FreeCAD—walls, roof planes, etc. Exact geometry; the generators work from whatever faces you give them.
2. **Select faces.** Click a face in the 3D view. Hold **Ctrl** and click more faces to add them to the selection. For most siding generators, all selected faces should be from the same wall solid. For `roof_seam_generator`, select exactly two adjacent faces that share a ridge or valley edge.
3. **Run the macro.** Open **Tools → Macros**, select the generator, click **Execute**.
4. **Adjust properties.** The generator object appears in the model tree. Click it to see its properties in the Properties panel (bottom-left). Change any value and press Enter—the geometry regenerates immediately.
5. **Hide the original** if you want a clean view, or keep it visible for reference.

### Tips

- If the result looks wrong (shingles inside the roof, trim facing inward), the face normal may be inverted. Check with **Part → Check Geometry** or try selecting the face from a different angle.
- For `smart_trim_generator`, use **SkipBottom** to suppress trim along the foundation line, and **PerimeterOnly** to ignore internal construction joints that shouldn't get trim.
- The `roof_seam_generator` requires exactly two faces. Run it once per hip or valley seam.

---

## Generator reference

All dimensions default to approximate HO scale values. See [Scales](#scales).

### Siding generators

These all follow the same pattern: select one or more wall faces, run the macro.

#### Clapboard

Horizontal overlapping boards, wider at the bottom edge than the top.

| Property | Default | What it controls |
|---|---|---|
| `ClapboardHeight` | — | Exposed reveal per course (mm) |
| `ClapboardThickness` | — | Material thickness at the thick (bottom) edge (mm) |

#### Board and Batten

Vertical wide boards with narrow batten strips covering the joints.

| Property | Default | What it controls |
|---|---|---|
| `BoardWidth` | — | Width of each vertical board (mm) |
| `BattenWidth` | — | Width of each batten strip (mm) |
| `BoardThickness` | — | Board material thickness (mm) |
| `BattenProjection` | — | How far battens project above the board face (mm) |

#### Bead Board

Vertical boards with small half-round grooves—typically used for porch ceilings and interior trim panels.

| Property | Default | What it controls |
|---|---|---|
| `BeadSpacing` | — | Centre-to-centre spacing between grooves (mm) |
| `BeadDepth` | — | Groove depth above the face (mm) |
| `BeadGap` | — | Width of each groove (mm) |

---

### Brick generators

#### Brick

Engraves brick coursing into a flat wall face. The original wall surface is indented to create mortar joints; bricks are the raised surface between them.

| Property | Default | What it controls |
|---|---|---|
| `BondPattern` | `stretcher` | `stretcher`, `english`, `flemish`, `common` |
| `BrickWidth` | — | Stretcher face width (mm) |
| `BrickHeight` | — | Brick height (mm) |
| `BrickDepth` | — | Header length / brick depth (mm) |
| `Mortar` | — | Mortar joint thickness (mm) |
| `SkinDepth` | — | Total engraving depth (mm) |
| `MortarDepth` | — | Additional groove depth for mortar joints (mm) |
| `CommonBondCount` | 6 | Stretcher courses between header courses (common bond only) |

#### Radial Brick

Same idea as `brick_generator`, but for cylindrical or conical faces. Brick lengths are automatically adjusted for the curvature at each course.

| Property | Default | What it controls |
|---|---|---|
| `BrickLength` | — | Nominal brick length along the circumference (mm) |
| `BrickHeight` | — | Brick height along the Z axis (mm) |
| `MaterialThickness` | — | Radial skin depth (mm) |
| `MortarThickness` | — | Mortar joint thickness (mm) |

---

### Roof generators

Select one or more roof faces, then run the macro.

#### Shingle

Wood shingle courses from eave to ridge. Shingles have a tapered (wedge) cross-section so each butt edge casts a visible shadow line.

| Property | Default | What it controls |
|---|---|---|
| `ShingleWidth` | — | Width of each shingle (mm) |
| `ShingleHeight` | — | Length (eave-to-tip) of each shingle (mm) |
| `Exposure` | — | Exposed portion per course (mm) |
| `MaterialThickness` | — | Sheet material thickness (mm) |
| `StaggerPattern` | `half` | `half`, `third`, or `none` |
| `WedgeThickness` | 0 | Butt-edge wedge height; 0 = auto (3× material) |
| `Chamfer` | 0 | V-groove between shingles; 0 = auto (1.5× material) |

#### Slate

Flat rectangular tile courses. Unlike shingles, slate tiles have uniform thickness; the overlap creates the shadow line.

| Property | Default | What it controls |
|---|---|---|
| `TileWidth` | — | Width of each tile (mm) |
| `TileHeight` | — | Length of each tile (mm) |
| `MaterialThickness` | — | Tile thickness (mm) |
| `Exposure` | — | Exposed portion per course (mm) |
| `StaggerPattern` | `half` | `half`, `third`, or `none` |

#### Standing Seam

Metal roofing panels with a raised L-profile seam running eave to ridge.

| Property | Default | What it controls |
|---|---|---|
| `PanelWidth` | — | Centre-to-centre seam spacing (mm) |
| `SeamHeight` | — | Raised seam ridge height (mm) |
| `SeamWidth` | — | Width of raised seam ridge (mm) |
| `PanelThickness` | — | Flat panel material thickness (mm) |

#### Roof Seam (hip caps and valley flashing)

Covers the joint between two adjacent roof planes. Select **exactly two faces** that share the hip or valley edge.

| Property | Default | What it controls |
|---|---|---|
| `HipStyle` | `shingle` | `shingle` (wood), `slate` (flat tiles), `metal` (continuous strip) |
| `ShingleHeight` | — | Cap unit length along the seam (mm) |
| `MaterialThickness` | — | Material thickness (mm) |
| `ShingleExposure` | — | Spacing between caps (mm) |
| `HipCapWidth` | 0 | Total cap width; 0 = auto (2× shingle width) |
| `AngleDepth` | 0.2 | Taper ratio 0–1 (thickness reduction at covered end) |
| `ValleyFlashingWidth` | 0 | Valley flashing width; 0 = auto (8× material thickness) |

---

### Trim generator

#### Smart Trim

Runs a trim profile along the perimeter edges of a wall face—typically used around window and door openings.

| Property | Default | What it controls |
|---|---|---|
| `TrimWidth` | — | Trim width perpendicular to the wall (mm) |
| `TrimHeight` | — | Trim height parallel to the wall surface (mm) |
| `TrimStyle` | `rectangular` | `rectangular` or `beveled` |
| `BevelSize` | — | Bevel chamfer size (beveled style only) (mm) |
| `SkipBottom` | true | Suppress trim on the bottom (foundation) edge |
| `PerimeterOnly` | true | Skip internal construction joints |
| `Flip` | false | Flip trim to the opposite side of the face |
| `OnlyEdge` | 0 | Trim only edge N (0 = all edges) |

---

### Station Sign

Produces a raised-letter station sign for 3D printing. No face selection required—the sign is a self-contained object.

| Property | Default | What it controls |
|---|---|---|
| `StationName` | — | Text to display |
| `FontPath` | — | Path to a `.ttf` font file |
| `TextHeight` | — | Letter height (mm) |
| `MaterialThickness` | — | Layer thickness for printing (mm) |
| `BorderThickness` | — | Frame border width (mm) |
| `BorderGap` | — | Gap between border and text (mm) |

---

## Scales

All default property values are set for HO scale (1:87), which is what the author models in. The generators themselves have no knowledge of scale—every dimension is just a number in millimetres. To use them at a different scale, divide the HO default by 87 and multiply by your scale denominator, or simply enter your own values directly.

For example, N scale (1:160) clapboard with a 12" prototype reveal:

- Prototype: 12 inches = 304.8 mm
- N scale: 304.8 / 160 = **1.9 mm**

The geometry will be correct for any scale you feed it.

---

## Contributing

Pull requests are welcome.

- **Bug fixes:** A clear description and a reproducible test case (or an existing test that now passes) is sufficient.
- **New generators or substantial changes to geometry logic:** Tests are required. The test suite covers the pure-Python geometry layer and runs without FreeCAD installed (`pytest` from the repo root). See any existing `tests/` directory for the pattern.
- **FreeCAD-dependent code** (proxy objects, macro entry points): these can't be covered by the automated suite—a description of manual testing performed is appreciated.
- **Platform testing:** Reports of success or failure on Linux and Windows are very welcome.

The author developed these on macOS and uses them for personal modelling projects. There is no guarantee of rapid response to issues or PRs, but contributions that follow the pattern above will be considered.

### Running tests

```bash
pip install pytest
pytest
```

341 tests, no FreeCAD required.
