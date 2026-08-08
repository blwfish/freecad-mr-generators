"""
Runner for the FreeCAD-dependent test files in this directory (currently
just test_freecad_utils_integration.py) -- the ones guarded by
`pytest.importorskip("FreeCAD")` and silently skipped under a plain
`python3 -m pytest` run.

FreeCADCmd doesn't support `-m pytest` (it runs a single script through
its own embedded interpreter), so this script just calls pytest.main()
itself, from inside that interpreter, where `FreeCAD`/`Part` are already
importable and pytest is already installed (FreeCAD's pixi environment).

Usage, from the repo root:

    /path/to/FC-clone/build/release/bin/FreeCADCmd shared/tests/run_freecad_tests.py

The FreeCADCmd path is a local build; adjust to wherever your FreeCAD
binary lives. Any pytest CLI args after the script path are passed
through, e.g. add `-k test_sources` at the end to filter.
"""

import sys
import os
import pytest

# No `if __name__ == "__main__":` guard here -- FreeCADCmd executes the
# script it's given without setting __name__ to "__main__" (confirmed
# 2026-08-08: that guard silently skipped this entire file, exiting 0
# with zero pytest output and no error). This script is only ever meant
# to be run directly, never imported, so unconditional top-level
# execution is correct here.

_here = os.path.dirname(os.path.abspath(__file__))
extra_args = sys.argv[1:]
sys.exit(pytest.main(["-v", _here] + extra_args))
