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
import os
import platform
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
MOD_NAME = "fc_generators"

GENERATORS = [
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
    "smart_trim_generator",
    "standing_seam_generator",
    "station_sign_generator",
]

SHARED_DIR = REPO_ROOT / "shared"


def find_freecad_paths():
    """Return (macro_dir, mod_dir) for the current platform."""
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
