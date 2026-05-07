# Agent Installation Guide

This file is for AI agents assisting users with installation. If you are a human, see [README.md](README.md) instead.

## What install.py does

`install.py` performs two operations:

1. **Copies `*.FCMacro` files** to the user's FreeCAD macro directory
2. **Copies all Python library files** (geometry, proxy, shared utilities) to `FreeCAD/Mod/fc_generators/`, and writes a `Init.py` so FreeCAD adds that directory to `sys.path` automatically on startup

No path manipulation inside the macros is needed—FreeCAD's module-loading mechanism handles it.

## Installation steps for an agent

```bash
# 1. Clone the repo (if not already present)
git clone https://github.com/blwfish/freecad-mr-generators /path/to/local/copy

# 2. Run the installer
cd /path/to/local/copy
python3 install.py

# 3. Verify (dry run)
python3 install.py --list
```

The installer auto-detects the FreeCAD paths for macOS, Linux, and Windows.

### macOS paths (typical)
| Destination | Path |
|---|---|
| Macros | `~/Library/Application Support/FreeCAD/v1-2/Macro/` |
| Library | `~/Library/Application Support/FreeCAD/v1-2/Mod/fc_generators/` |

### Linux paths (typical)
| Destination | Path |
|---|---|
| Macros | `~/.local/share/FreeCAD/Macro/` |
| Library | `~/.local/share/FreeCAD/Mod/fc_generators/` |

### Windows paths (typical)
| Destination | Path |
|---|---|
| Macros | `%APPDATA%\FreeCAD\Macro\` |
| Library | `%APPDATA%\FreeCAD\Mod\fc_generators\` |

## Overriding paths

If the user's FreeCAD is in a non-standard location:

```bash
python3 install.py --macro-dir /path/to/Macro --mod-dir /path/to/Mod
```

## Uninstall

```bash
python3 install.py --uninstall
```

This removes all installed macros and deletes the `fc_generators/` module directory entirely.

## After installation

Tell the user to restart FreeCAD. The macros then appear in **Tools → Macros** under their plain names (e.g. `clapboard_generator.FCMacro`).

## Verifying the install worked

From the FreeCAD Python console:
```python
import fc_generators  # should not raise ImportError
```

Or check that `Mod/fc_generators/Init.py` exists.
