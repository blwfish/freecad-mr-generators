# freecad-mr-generators

Parametric FreeCAD generators for HO scale model railroad structures. Select faces on a wall or roof, run a macro, adjust properties in the panel.

## Generators

| Macro | What it does |
|---|---|
| `bead_board_generator` | Beadboard trim panels |
| `board_batten_generator` | Board-and-batten siding |
| `brick_generator_macro` | Brick coursing with bond patterns |
| `clapboard_generator` | Clapboard (lap) siding |
| `radial_brick_generator_macro` | Brick on curved/cylindrical surfaces |
| `roof_seam_generator` | Hip caps and valley flashing |
| `shingle_generator` | Wood shingles on roof faces |
| `slate_generator` | Slate tile roofing |
| `smart_trim_generator` | Parametric window/door trim |
| `standing_seam_generator` | Standing-seam metal roofing |
| `station_sign_generator` | Station sign boards |

All generators produce parametric `FeaturePython` objects—change any property in the Properties panel and the geometry regenerates automatically.

## Requirements

- FreeCAD 0.21 or later (tested on weekly builds)
- Python 3.x (bundled with FreeCAD)

## Installation

```bash
git clone https://github.com/blwfish/freecad-mr-generators
cd freecad-mr-generators
python3 install.py
```

Restart FreeCAD. Macros appear in **Tools → Macros**.

### What the installer does

- Copies `*.FCMacro` files to your FreeCAD macro directory
- Copies the Python library to `FreeCAD/Mod/fc_generators/` so imports resolve automatically

### Custom paths

```bash
python3 install.py --macro-dir /path/to/Macro --mod-dir /path/to/Mod
```

### Preview before installing

```bash
python3 install.py --list
```

### Uninstall

```bash
python3 install.py --uninstall
```

## General workflow

1. Open or create a FreeCAD document with geometry
2. Select one or more faces (wall face, roof face, etc.)
3. Run the appropriate macro from **Tools → Macros**
4. The generator object appears—adjust properties in the Properties panel

## Running tests

Tests run without FreeCAD installed:

```bash
pip install pytest
pytest
```

Each generator has tests in its `tests/` subdirectory covering the pure-Python geometry functions.

## License

MIT
