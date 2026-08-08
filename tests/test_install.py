"""
Tests for install.py -- the packaging/installer script (full-review finding
freecad-mr-generators-20260808-a0b9#35: 0% coverage, including new
FreeCAD-version-detection logic added this session with no regression
test).

install.py lives at the repo root, not inside a generator's tests/
directory -- these tests exercise its pure logic (GENERATORS list
consistency, file collection, path-detection heuristics) without actually
copying files or requiring a real FreeCAD install.
"""

import sys
import platform
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import install


class TestGeneratorsList:
    def test_every_entry_has_a_directory(self):
        for gen in install.GENERATORS:
            assert (install.REPO_ROOT / gen).is_dir(), f"{gen} has no directory"

    def test_ashlar_generator_present(self):
        # Regression test: ashlar_generator was missing from this list
        # entirely, so it was never actually installed by anyone running
        # install.py, despite being a real, documented generator.
        assert "ashlar_generator" in install.GENERATORS

    def test_no_duplicate_entries(self):
        assert len(install.GENERATORS) == len(set(install.GENERATORS))


class TestCollectMacros:
    def test_no_duplicate_destination_filenames(self):
        # install.py flattens every *.FCMacro into ONE macro directory --
        # two generators shipping a same-named macro would silently clobber
        # one another at install time.
        macros = install.collect_macros()
        names = [name for _, name in macros]
        assert len(names) == len(set(names)), (
            f"duplicate macro destination filenames: "
            f"{[n for n in names if names.count(n) > 1]}")

    def test_all_source_files_exist(self):
        for src, _name in install.collect_macros():
            assert src.exists(), f"{src} does not exist"

    def test_returns_at_least_one_macro_per_generator_with_a_macro(self):
        # Every generator except quoin_generator (library-only, no macro of
        # its own -- see CLAUDE.md) ships exactly one .FCMacro.
        macros = install.collect_macros()
        found_dirs = {src.parent.name for src, _ in macros}
        for gen in install.GENERATORS:
            has_macro_file = bool(list((install.REPO_ROOT / gen).glob("*.FCMacro")))
            if has_macro_file:
                assert gen in found_dirs, f"{gen} has a .FCMacro but collect_macros() missed it"


class TestCollectLibFiles:
    def test_no_duplicate_destination_filenames(self):
        # install.py flattens shared/*.py and every generator's *.py into
        # ONE module directory (Mod/fc_generators/) -- a same-named module
        # in two source directories would silently clobber one another,
        # exactly the risk explicitly checked by hand when
        # shared/snow_guard_solid_geometry.py was added (deliberately
        # avoiding the name snow_guard_geometry.py, which already exists
        # in snow_guard_generator/). This makes that check a standing
        # regression test instead of a one-time manual verification.
        files = install.collect_lib_files()
        names = [name for _, name in files]
        dupes = sorted({n for n in names if names.count(n) > 1})
        assert not dupes, f"duplicate library destination filenames: {dupes}"

    def test_all_source_files_exist(self):
        for src, _name in install.collect_lib_files():
            assert src.exists(), f"{src} does not exist"

    def test_excludes_test_files(self):
        files = install.collect_lib_files()
        for _src, name in files:
            assert not name.startswith("test_"), f"{name} should not be installed"
            assert name != "conftest.py", "conftest.py should not be installed"

    def test_includes_shared_utilities(self):
        files = install.collect_lib_files()
        names = {name for _, name in files}
        assert "freecad_utils.py" in names
        assert "boundary_assertions.py" in names

    def test_includes_ashlar_geometry(self):
        # Regression test for the same GENERATORS-list bug as above, from
        # the file-collection side.
        files = install.collect_lib_files()
        names = {name for _, name in files}
        assert "ashlar_geometry.py" in names
        assert "ashlar_proxy.py" in names


class TestFindFreecadPathsHeuristic:
    """Exercises _find_freecad_paths_heuristic()'s Darwin branch directly,
    without touching the real filesystem's actual FreeCAD install --
    monkeypatches Path.home() to a temp directory and platform.system()."""

    def _make_versioned_dir(self, base, name, with_macro=True):
        d = base / name
        d.mkdir(parents=True)
        if with_macro:
            (d / "Macro").mkdir()
        return d

    def test_darwin_picks_newest_of_two_versions(self, tmp_path, monkeypatch):
        # Directly exercises the "1.2 -> 26.3 calendar-versioning renumber"
        # scenario this repo's own history was bitten by (see CLAUDE.md /
        # project memory on freecad-mcp's deploy.sh): a naive string sort
        # would rank "v1-1" above "v26-3"; the numeric tuple-key sort must
        # not.
        base = tmp_path / "Library" / "Application Support" / "FreeCAD"
        self._make_versioned_dir(base, "v1-1")
        self._make_versioned_dir(base, "v26-3")
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        # install.py's function reads `platform.system`/`Path.home` via the
        # names imported into its own module namespace.
        monkeypatch.setattr(install.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(install.Path, "home", lambda: tmp_path)

        macro_dir, mod_dir = install._find_freecad_paths_heuristic()
        assert macro_dir == base / "v26-3" / "Macro"
        assert mod_dir == base / "v26-3" / "Mod"

    def test_darwin_picks_newest_of_three_versions_out_of_order(self, tmp_path, monkeypatch):
        base = tmp_path / "Library" / "Application Support" / "FreeCAD"
        self._make_versioned_dir(base, "v1-1")
        self._make_versioned_dir(base, "v2-0")
        self._make_versioned_dir(base, "v26-3")
        monkeypatch.setattr(install.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(install.Path, "home", lambda: tmp_path)

        macro_dir, _mod_dir = install._find_freecad_paths_heuristic()
        assert macro_dir == base / "v26-3" / "Macro"

    def test_darwin_ignores_versioned_dir_without_macro_subdir(self, tmp_path, monkeypatch):
        base = tmp_path / "Library" / "Application Support" / "FreeCAD"
        self._make_versioned_dir(base, "v1-1")
        self._make_versioned_dir(base, "v26-3", with_macro=False)  # no Macro/ yet
        monkeypatch.setattr(install.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(install.Path, "home", lambda: tmp_path)

        macro_dir, _mod_dir = install._find_freecad_paths_heuristic()
        assert macro_dir == base / "v1-1" / "Macro"

    def test_darwin_no_versioned_dirs_falls_back_to_base(self, tmp_path, monkeypatch):
        base = tmp_path / "Library" / "Application Support" / "FreeCAD"
        base.mkdir(parents=True)
        monkeypatch.setattr(install.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(install.Path, "home", lambda: tmp_path)

        macro_dir, mod_dir = install._find_freecad_paths_heuristic()
        assert macro_dir == base / "Macro"
        assert mod_dir == base / "Mod"

    def test_darwin_no_freecad_dir_at_all(self, tmp_path, monkeypatch):
        # Nothing exists yet (first-ever install on this machine) -- must
        # not raise, just return the default base-dir paths.
        monkeypatch.setattr(install.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(install.Path, "home", lambda: tmp_path)

        macro_dir, mod_dir = install._find_freecad_paths_heuristic()
        assert macro_dir == tmp_path / "Library" / "Application Support" / "FreeCAD" / "Macro"
        assert mod_dir == tmp_path / "Library" / "Application Support" / "FreeCAD" / "Mod"

    def test_linux_prefers_local_share_when_it_has_macro_dir(self, tmp_path, monkeypatch):
        local_share = tmp_path / ".local" / "share" / "FreeCAD"
        (local_share / "Macro").mkdir(parents=True)
        monkeypatch.setattr(install.platform, "system", lambda: "Linux")
        monkeypatch.setattr(install.Path, "home", lambda: tmp_path)

        macro_dir, _mod_dir = install._find_freecad_paths_heuristic()
        assert macro_dir == local_share / "Macro"

    def test_linux_no_existing_dirs_defaults_to_local_share(self, tmp_path, monkeypatch):
        monkeypatch.setattr(install.platform, "system", lambda: "Linux")
        monkeypatch.setattr(install.Path, "home", lambda: tmp_path)

        macro_dir, _mod_dir = install._find_freecad_paths_heuristic()
        assert macro_dir == tmp_path / ".local" / "share" / "FreeCAD" / "Macro"


class TestFindFreecadcmd:
    def test_returns_none_when_not_on_path_and_no_known_location(self, monkeypatch):
        monkeypatch.setattr(install.shutil, "which", lambda name: None)
        monkeypatch.setattr(install.platform, "system", lambda: "Linux")
        assert install._find_freecadcmd() is None

    def test_finds_on_path(self, monkeypatch):
        monkeypatch.setattr(install.shutil, "which",
                             lambda name: "/usr/local/bin/FreeCADCmd" if name == "FreeCADCmd" else None)
        assert install._find_freecadcmd() == "/usr/local/bin/FreeCADCmd"
