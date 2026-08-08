# Agent Installation Guide

This file is for AI agents assisting users with installation. If you are a human, see [README.md](README.md) instead.

## What install.py does

`install.py` performs two operations:

1. **Copies `*.FCMacro` files** to the user's FreeCAD macro directory
2. **Copies all Python library files** (geometry, proxy, shared utilities) to `FreeCAD/Mod/fc_generators/`, and writes a `Init.py` so FreeCAD adds that directory to `sys.path` automatically on startup

No path manipulation inside the macros is needed—FreeCAD's module-loading mechanism handles it.

Path detection asks FreeCAD itself where its user directories are (via `FreeCADCmd`) when it can find that binary, so it stays correct across any future FreeCAD version-numbering change; it falls back to a directory-scan heuristic only if `FreeCADCmd` isn't found.

## Requirements

- **FreeCAD 1.1.x** (current stable) or a current weekly dev build (calendar-versioned, e.g. `26.3+`). Path detection and the generators themselves work with either.
- **Python 3**, bundled with FreeCAD—no separate install needed for the generators themselves.
- One generator, `ashlar_generator`, additionally needs **numpy and scipy** installed in FreeCAD's own Python environment (see Step 3 below). Every other generator needs nothing beyond FreeCAD itself.

## Installation steps for an agent

### Step 1: Get the code

Most users are not set up with git — prefer downloading the packaged release over cloning.

```bash
# Preferred: download the latest release (no git needed)
gh release download --repo blwfish/freecad-mr-generators --archive=zip --dir /path/to/extract
cd /path/to/extract && unzip -q *.zip && cd freecad-mr-generators-*

# Alternative, if the user is already a contributor or `gh` isn't available:
git clone https://github.com/blwfish/freecad-mr-generators /path/to/local/copy
cd /path/to/local/copy
```

Either path produces the same repo layout — `install.py` doesn't care which one you used.

### Step 2: Run the installer

```bash
python3 install.py

# Verify (dry run, no changes)
python3 install.py --list
```

The installer auto-detects the FreeCAD paths for macOS, Linux, and Windows.

### macOS paths (typical)
| Destination | Path |
|---|---|
| Macros | `~/Library/Application Support/FreeCAD/<version>/Macro/` |
| Library | `~/Library/Application Support/FreeCAD/<version>/Mod/fc_generators/` |

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

`<version>` is whatever FreeCAD itself reports (e.g. `v1-1`, `v26-3`) — don't hardcode a specific one; it changes between releases and the installer resolves it dynamically.

### Step 3: Check for ashlar_generator's numpy/scipy dependency

`install.py`'s output ends with a note if `ashlar_generator`'s dependencies aren't present in FreeCAD's own Python. It looks like:

```
Note: ashlar_generator needs numpy and scipy, which are not
installed in FreeCAD's Python environment. Every other generator
in this repo works without them. To fix, run:
    <path-to-FreeCADCmd> -m pip install numpy scipy
```

If you see that note, run the exact command it printed — installer already resolved the correct FreeCAD-owned Python for you, so don't substitute the system Python or guess a path yourself. Skip this step if the note doesn't appear, or if the user has no interest in `ashlar_generator` specifically (every other generator works regardless).

If `install.py` couldn't locate `FreeCADCmd` at all (a different note appears instead), and the user does want `ashlar_generator`, ask them for their FreeCAD install location or find it yourself, then run `<that path> -m pip install numpy scipy`.

### Overriding paths

If the user's FreeCAD is in a non-standard location:

```bash
python3 install.py --macro-dir /path/to/Macro --mod-dir /path/to/Mod
```

### Uninstall

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

---

## Optional: also install the FreeCAD MCP server

If you're reading this file, you're an AI agent with tool access — which makes you a natural fit for [freecad-mcp](https://github.com/blwfish/freecad-mcp), a companion project (same author, separate repo) that lets *you* drive FreeCAD directly: create objects, run these generator macros, inspect geometry, read the report view, instead of only being able to tell the user what to click.

**Disclose before installing, don't just do it.** Tell the user in one sentence that you're about to set this up and why — e.g. "I'll also install the FreeCAD MCP server so I can drive FreeCAD directly for you — say no if you'd rather I skip it." If they decline, skip this whole section: the generators above install and work completely without it. If they change their mind later, it's a normal uninstall (see freecad-mcp's own docs) — nothing in this repo depends on the MCP server being present.

**Full instructions:** follow [freecad-mcp's own AGENT-INSTALL.md](https://github.com/blwfish/freecad-mcp/blob/main/AGENT-INSTALL.md) — Prerequisites through Verify Installation. Don't duplicate those steps here; that file is the source of truth and can change independently of this one.

**What it involves, so you can set expectations up front:** a second `git clone` of `freecad-mcp`, copying its `AICopilot` addon into FreeCAD's `Mod` folder (same version-detection caveat as above — ask FreeCAD, don't hardcode the versioned path), installing the MCP bridge (`pip3 install mcp mcp-events` into *your own* environment's Python, not FreeCAD's), and registering the server with your own MCP client config. A few minutes, no FreeCAD restart required beyond what's already needed for the generators above.
