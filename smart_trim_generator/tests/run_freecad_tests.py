"""
Runner for the FreeCAD-dependent test files in this directory (currently
just test_trim_geometry_integration.py) -- the ones guarded by
`pytest.importorskip("FreeCAD")` and silently skipped under a plain
`python3 -m pytest` run.

FreeCADCmd doesn't support `-m pytest` (it runs a single script through
its own embedded interpreter), so this script just calls pytest.main()
itself, from inside that interpreter, where `FreeCAD`/`Part` are already
importable and pytest is already installed (FreeCAD's pixi environment).

Usage, from the repo root:

    /path/to/FC-clone/build/release/bin/FreeCADCmd smart_trim_generator/tests/run_freecad_tests.py

The FreeCADCmd path is a local build; adjust to wherever your FreeCAD
binary lives. Any pytest CLI args after the script path are passed
through, e.g. add `-k test_miter` at the end to filter.

See shared/tests/run_freecad_tests.py -- this mirrors that file, and its
own comment explains why there is deliberately no
`if __name__ == "__main__":` guard here (FreeCADCmd doesn't set __name__
to "__main__" for the script it runs; that guard would silently skip this
whole file).
"""

import sys
import os
import pytest

_here = os.path.dirname(os.path.abspath(__file__))
extra_args = sys.argv[1:]
# -o addopts= clears pytest.ini's `addopts = --cov=...` (added 2026-08-08
# when pytest-cov was wired in) -- pytest-cov isn't installed under
# FreeCAD's own bundled Python, so inheriting that addopts makes pytest
# reject --cov as an unrecognized argument before collection even starts.
sys.exit(pytest.main(["-v", "-o", "addopts=", _here] + extra_args))
