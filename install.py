#!/usr/bin/env python3
"""
install.py — Install freecad-mr-generators into FreeCAD.

What it does:
  • Copies *.FCMacro files → FreeCAD user macro directory
  • Copies all Python library files → FreeCAD/Mod/fc_generators/
    (FreeCAD auto-adds this to sys.path, so macros just do `import clapboard_proxy`)

Usage:
    python3 install.py              # auto-detect paths
    python3 install.py --list       # show what would be installed
    python3 install.py --uninstall  # remove installed files
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
MOD_NAME = "fc_generators"

GENERATORS = [
    "ashlar_generator",
    "bead_board_generator",
    "board_batten_generator",
    "brick_generator",
    "clapboard_generator",
    "label_generator",
    "quoin_generator",
    "radial_brick_generator",
    "roof_seam_generator",
    "shingle_generator",
    "slate_generator",
    "slate_seam_generator",
    "smart_trim_generator",
    "snow_guard_generator",
    "standing_seam_generator",
    "standing_seam_snow_guard_generator",
    "station_sign_generator",
]

SHARED_DIR = REPO_ROOT / "shared"


def _find_freecadcmd():
    """Locate the FreeCADCmd binary, if present. Checked first on PATH,
    then a couple of common per-platform install locations. Returns None
    if not found — callers must fall back to the directory-scan heuristic."""
    on_path = shutil.which("FreeCADCmd") or shutil.which("freecadcmd")
    if on_path:
        return on_path

    system = platform.system()
    candidates = []
    if system == "Darwin":
        candidates.append("/Applications/FreeCAD.app/Contents/Resources/bin/FreeCADCmd")
    elif system == "Windows":
        import glob
        for base in (r"C:\Program Files\FreeCAD*", r"C:\Program Files (x86)\FreeCAD*"):
            candidates.extend(glob.glob(str(Path(base) / "bin" / "FreeCADCmd.exe")))
    elif system == "Linux":
        candidates.extend(["/usr/bin/FreeCADCmd", "/usr/local/bin/FreeCADCmd"])

    for c in candidates:
        if Path(c).exists():
            return c
    return None


def _find_freecad_paths_via_freecadcmd():
    """Ask FreeCAD itself where its user Macro/Mod directories are, via its
    own getUserMacroDir()/getUserAppDataDir() APIs. This is immune to any
    future change in how FreeCAD names its version-stamped user-data
    directory (e.g. the 1.2 -> 26.3 calendar-versioning renumber) —
    freecad-mcp's deploy tooling adopted the same approach after getting
    bit by exactly that renumber. Returns (macro_dir, mod_dir) or None."""
    binary = _find_freecadcmd()
    if not binary:
        return None

    script = (
        "import FreeCAD, os, json; "
        "print(json.dumps({"
        "'macro': FreeCAD.getUserMacroDir(), "
        "'mod': os.path.join(FreeCAD.getUserAppDataDir(), 'Mod')}))"
    )
    try:
        result = subprocess.run(
            [binary, "-c", script],
            capture_output=True, text=True, timeout=30,
        )
        # FreeCAD's own startup banner/warnings can precede our JSON on
        # stdout, so parse only the last non-blank line.
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        if not lines:
            return None
        data = json.loads(lines[-1])
        return Path(data["macro"]), Path(data["mod"])
    except (subprocess.SubprocessError, OSError, ValueError, KeyError):
        return None


def find_freecad_paths():
    """Return (macro_dir, mod_dir). Prefers asking FreeCAD itself (works
    for any FreeCAD version, including future ones); falls back to a
    per-platform directory-scan heuristic if FreeCADCmd isn't found."""
    via_freecad = _find_freecad_paths_via_freecadcmd()
    if via_freecad:
        return via_freecad
    return _find_freecad_paths_heuristic()


def _find_freecad_paths_heuristic():
    """Best-effort path guess when FreeCADCmd isn't available to ask
    directly. Kept as a fallback, not the primary method — see
    find_freecad_paths()."""
    system = platform.system()
    home = Path.home()

    if system == "Darwin":
        base = home / "Library" / "Application Support" / "FreeCAD"
        # Collect versioned subdirs (v<major>-<minor> pattern) that have a
        # Macro directory, and pick the newest by version number.
        def _ver_key(p):
            parts = p.name.lstrip('v').split('-')
            try:
                return tuple(int(x) for x in parts)
            except ValueError:
                return (0,)

        versioned = sorted(
            [d for d in base.iterdir() if d.is_dir() and d.name.startswith('v')
             and (d / "Macro").exists()],
            key=_ver_key,
            reverse=True,
        ) if base.exists() else []

        if versioned:
            return versioned[0] / "Macro", versioned[0] / "Mod"
        if (base / "Macro").exists():
            return base / "Macro", base / "Mod"
        # Nothing exists yet — default to the base dir
        return base / "Macro", base / "Mod"

    if system == "Linux":
        for candidate in [
            home / ".local" / "share" / "FreeCAD",
            home / ".FreeCAD",
        ]:
            if (candidate / "Macro").exists():
                return candidate / "Macro", candidate / "Mod"
        return home / ".local" / "share" / "FreeCAD" / "Macro", \
               home / ".local" / "share" / "FreeCAD" / "Mod"

    if system == "Windows":
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        base = appdata / "FreeCAD"
        return base / "Macro", base / "Mod"

    print(f"Unknown platform: {system}")
    sys.exit(1)


def collect_macros():
    """Return list of (src_path, dest_filename) for all FCMacro files."""
    macros = []
    for gen in GENERATORS:
        gen_dir = REPO_ROOT / gen
        for f in sorted(gen_dir.glob("*.FCMacro")):
            macros.append((f, f.name))
    return macros


def collect_lib_files():
    """Return list of (src_path, dest_filename) for all Python library files."""
    files = []
    # Shared utilities
    for f in sorted(SHARED_DIR.glob("*.py")):
        files.append((f, f.name))
    # Per-generator geometry and proxy files
    for gen in GENERATORS:
        gen_dir = REPO_ROOT / gen
        for f in sorted(gen_dir.glob("*.py")):
            if f.name.startswith("test_") or f.stem == "conftest":
                continue
            files.append((f, f.name))
    return files


def _check_ashlar_dependencies():
    """ashlar_generator is the one generator in this repo that needs
    numpy/scipy (Delaunay-triangulated stone texture — see
    ashlar_generator/ashlar_geometry.py's module docstring for why that
    wasn't reimplemented in pure Python). Every other generator works
    with zero extra dependencies. Print a copy-pasteable fix if they're
    missing from FreeCAD's own Python — this installer doesn't run pip
    on the user's behalf, it just makes the gap loud instead of letting
    it surface later as a raw ModuleNotFoundError inside FreeCAD."""
    binary = _find_freecadcmd()
    if not binary:
        print(
            "\nNote: could not locate FreeCADCmd to check for numpy/scipy "
            "(needed only by ashlar_generator). If you use ashlar_generator "
            "and it reports missing numpy/scipy, install them into FreeCAD's "
            "own Python environment (not your system Python)."
        )
        return

    try:
        result = subprocess.run(
            [binary, "-c", "import numpy, scipy"],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        return

    if result.returncode != 0:
        print(
            "\nNote: ashlar_generator needs numpy and scipy, which are not "
            "installed in FreeCAD's Python environment. Every other generator "
            "in this repo works without them. To fix, run:\n"
            f"    {binary} -m pip install numpy scipy"
        )


def install(macro_dir: Path, mod_dir: Path, dry_run: bool = False):
    fc_gen_dir = mod_dir / MOD_NAME

    print(f"Macro directory : {macro_dir}")
    print(f"Module directory: {fc_gen_dir}")
    print()

    macros = collect_macros()
    lib_files = collect_lib_files()

    if not dry_run:
        macro_dir.mkdir(parents=True, exist_ok=True)
        fc_gen_dir.mkdir(parents=True, exist_ok=True)

        # Write FreeCAD Init.py so the module directory is added to sys.path
        init_py = fc_gen_dir / "Init.py"
        init_py.write_text('# freecad-mr-generators library — auto-added to sys.path by FreeCAD\n')

    print(f"Installing {len(macros)} macros:")
    for src, name in macros:
        dest = macro_dir / name
        print(f"  {src.parent.name}/{name} → {dest}")
        if not dry_run:
            shutil.copy2(src, dest)

    print(f"\nInstalling {len(lib_files)} library files:")
    for src, name in lib_files:
        dest = fc_gen_dir / name
        print(f"  {src.parent.name}/{name} → {dest}")
        if not dry_run:
            shutil.copy2(src, dest)

    if not dry_run:
        print(f"\nDone. Run macros from Tools → Macros (no FreeCAD restart needed).")
        _check_ashlar_dependencies()


def uninstall(macro_dir: Path, mod_dir: Path):
    fc_gen_dir = mod_dir / MOD_NAME

    removed = 0
    for _, name in collect_macros():
        f = macro_dir / name
        if f.exists():
            f.unlink()
            print(f"Removed: {f}")
            removed += 1

    if fc_gen_dir.exists():
        shutil.rmtree(fc_gen_dir)
        print(f"Removed: {fc_gen_dir}")
        removed += 1

    print(f"\n{removed} items removed.")


def main():
    parser = argparse.ArgumentParser(description="Install freecad-mr-generators")
    parser.add_argument("--list", action="store_true", help="Show what would be installed")
    parser.add_argument("--uninstall", action="store_true", help="Remove installed files")
    parser.add_argument("--macro-dir", help="Override macro directory path")
    parser.add_argument("--mod-dir", help="Override FreeCAD Mod directory path")
    args = parser.parse_args()

    macro_dir, mod_dir = find_freecad_paths()
    if args.macro_dir:
        macro_dir = Path(args.macro_dir)
    if args.mod_dir:
        mod_dir = Path(args.mod_dir)

    if args.uninstall:
        uninstall(macro_dir, mod_dir)
    else:
        install(macro_dir, mod_dir, dry_run=args.list)


if __name__ == "__main__":
    main()
