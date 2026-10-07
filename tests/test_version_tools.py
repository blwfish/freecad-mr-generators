"""Tests for tools/check_version_bump.py (the commit-msg version-bump check)."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check_version_bump as cvb  # noqa: E402


class TestParseVersion:
    @pytest.mark.parametrize("text,expected", [
        ('VERSION = "6.0.1"\n', (6, 0, 1)),
        ("VERSION = '1.2'\n", (1, 2)),
        ('x = 1\nVERSION   =   "10.20.30"\n', (10, 20, 30)),
        ('', None),
        (None, None),
        ('# VERSION = "1.0.0"\n', None),            # commented out
        ('    VERSION = "1.0.0"\n', None),          # indented: not module-level
        ('VERSION = "1.0.0-beta"\n', None),         # non-numeric suffix: not parsed
        ('GeneratorVersion = "1.0.0"\n', None),
    ])
    def test_cases(self, text, expected):
        assert cvb.parse_version(text) == expected

    def test_compares_numerically_not_lexically(self):
        assert cvb.parse_version('VERSION = "6.0.10"') > cvb.parse_version('VERSION = "6.0.9"')


class TestIsCodeFile:
    @pytest.mark.parametrize("path,gen,expected", [
        ("shingle_generator/shingle_proxy.py", "shingle_generator", True),
        ("shingle_generator/shingle_generator.FCMacro", "shingle_generator", True),
        ("shingle_generator/tests/test_x.py", "shingle_generator", False),
        ("shingle_generator/sub/tests/test_x.py", "shingle_generator", False),
        ("shingle_generator/README.md", "shingle_generator", False),
        ("shingle_generator/__pycache__/x.py", "shingle_generator", False),
        ("slate_generator/slate_proxy.py", "shingle_generator", False),
        ("shared/freecad_utils.py", "shingle_generator", False),
        ("shingle_generator", "shingle_generator", False),
    ])
    def test_cases(self, path, gen, expected):
        assert cvb.is_code_file(path, gen) is expected


P = "shingle_generator/shingle_proxy.py"
G = "shingle_generator/shingle_geometry.py"


class TestGeneratorsMissingBump:
    def test_code_change_without_bump_is_flagged(self):
        r = cvb.generators_missing_bump([G], {P: (6, 0, 0)}, {P: (6, 0, 0)})
        assert "shingle_generator" in r and "still 6.0.0" in r["shingle_generator"]

    def test_bump_alongside_code_change_passes(self):
        assert cvb.generators_missing_bump([G, P], {P: (6, 0, 0)}, {P: (6, 0, 1)}) == {}

    @pytest.mark.parametrize("new,flagged", [
        ((6, 0, 0), True),     # at: equal is NOT a bump
        ((6, 0, 1), False),    # above
        ((5, 9, 9), True),     # below: a downgrade
    ])
    def test_equal_up_down_boundary(self, new, flagged):
        r = cvb.generators_missing_bump([G], {P: (6, 0, 0)}, {P: new})
        assert bool(r) is flagged

    def test_downgrade_message_says_down(self):
        r = cvb.generators_missing_bump([G], {P: (6, 0, 0)}, {P: (5, 0, 0)})
        assert "DOWN" in r["shingle_generator"]

    def test_tests_only_change_needs_no_bump(self):
        assert cvb.generators_missing_bump(
            ["shingle_generator/tests/test_a.py"], {P: (6, 0, 0)}, {P: (6, 0, 0)}) == {}

    def test_doc_only_change_needs_no_bump(self):
        assert cvb.generators_missing_bump(
            ["shingle_generator/NOTES.md"], {P: (6, 0, 0)}, {P: (6, 0, 0)}) == {}

    def test_macro_only_change_is_code(self):
        r = cvb.generators_missing_bump(
            ["shingle_generator/shingle_generator.FCMacro"], {P: (6, 0, 0)}, {P: (6, 0, 0)})
        assert "shingle_generator" in r

    def test_shared_only_change_is_not_checked(self):
        assert cvb.generators_missing_bump(
            ["shared/freecad_utils.py"], {P: (6, 0, 0)}, {P: (6, 0, 0)}) == {}

    def test_new_generator_is_exempt(self):
        # proxy absent at HEAD (None) -> brand-new generator
        assert cvb.generators_missing_bump([P, G], {P: None}, {P: (1, 0, 0)}) == {}
        assert cvb.generators_missing_bump([P, G], {}, {P: (1, 0, 0)}) == {}

    def test_generator_without_any_version_reports_nothing_to_bump(self):
        r = cvb.generators_missing_bump([G], {P: None}, {P: None})
        assert r == {}      # indistinguishable from "new": exempt, not a crash

    def test_each_generator_judged_independently(self):
        slate_p = "slate_generator/slate_proxy.py"
        r = cvb.generators_missing_bump(
            [G, "slate_generator/slate_geometry.py", P],
            {P: (6, 0, 0), slate_p: (1, 0, 0)}, {P: (6, 0, 1), slate_p: (1, 0, 0)})
        assert list(r) == ["slate_generator"]

    def test_any_proxy_bumped_satisfies(self):
        p2 = "shingle_generator/other_proxy.py"
        assert cvb.generators_missing_bump(
            [G], {P: (1, 0, 0), p2: (2, 0, 0)}, {P: (1, 0, 0), p2: (2, 0, 1)}) == {}


class TestOverrideTrailer:
    @pytest.mark.parametrize("msg,expected", [
        ("fix\n\nNo-Version-Bump: macro header sync\n", True),
        ("fix\n\nNo-Version-Bump:   spaced reason\n", True),
        ("fix\n\nNo-Version-Bump:\n", False),                 # empty reason
        ("fix\n\nNo-Version-Bump:   \n", False),              # whitespace-only reason
        ("fix\n\n# No-Version-Bump: commented\n", False),     # git comment line
        ("fix mentions No-Version-Bump: in prose\n", False),  # not at line start
        ("fix\n", False),
    ])
    def test_cases(self, msg, expected):
        assert cvb.has_override(msg) is expected


# -- end to end, in a throwaway repo ------------------------------------------

def _run(*cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    _run("git", "init", "-q", cwd=tmp_path)
    _run("git", "config", "user.email", "t@t", cwd=tmp_path)
    _run("git", "config", "user.name", "t", cwd=tmp_path)
    gen = tmp_path / "foo_generator"
    gen.mkdir()
    (gen / "foo_proxy.py").write_text('VERSION = "1.0.0"\n')
    (gen / "foo_geometry.py").write_text("x = 1\n")
    _run("git", "add", "-A", cwd=tmp_path)
    _run("git", "commit", "-q", "-m", "init", cwd=tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _msg(tmp_path, text="change\n"):
    f = tmp_path / "MSG"
    f.write_text(text)
    return str(f)


class TestEndToEnd:
    def test_code_change_without_bump_fails(self, repo, capsys):
        (repo / "foo_generator/foo_geometry.py").write_text("x = 2\n")
        _run("git", "add", "-A", cwd=repo)
        assert cvb.main(["--commit-msg", _msg(repo)]) == 1
        assert "foo_generator" in capsys.readouterr().err

    def test_code_change_with_bump_passes(self, repo):
        (repo / "foo_generator/foo_geometry.py").write_text("x = 2\n")
        (repo / "foo_generator/foo_proxy.py").write_text('VERSION = "1.0.1"\n')
        _run("git", "add", "-A", cwd=repo)
        assert cvb.main(["--commit-msg", _msg(repo)]) == 0

    def test_trailer_overrides(self, repo):
        (repo / "foo_generator/foo_geometry.py").write_text("x = 2\n")
        _run("git", "add", "-A", cwd=repo)
        assert cvb.main(["--commit-msg", _msg(repo, "c\n\nNo-Version-Bump: comment only\n")]) == 0

    def test_tests_only_commit_passes(self, repo):
        (repo / "foo_generator/tests").mkdir()
        (repo / "foo_generator/tests/test_a.py").write_text("pass\n")
        _run("git", "add", "-A", cwd=repo)
        assert cvb.main(["--commit-msg", _msg(repo)]) == 0

    def test_unstaged_changes_are_ignored(self, repo):
        (repo / "foo_generator/foo_geometry.py").write_text("x = 2\n")   # not staged
        assert cvb.main(["--commit-msg", _msg(repo)]) == 0

    def test_new_generator_passes(self, repo):
        new = repo / "bar_generator"
        new.mkdir()
        (new / "bar_proxy.py").write_text('VERSION = "1.0.0"\n')
        (new / "bar_geometry.py").write_text("y = 1\n")
        _run("git", "add", "-A", cwd=repo)
        assert cvb.main(["--commit-msg", _msg(repo)]) == 0

    def test_downgrade_fails(self, repo):
        (repo / "foo_generator/foo_proxy.py").write_text('VERSION = "0.9.0"\n')
        (repo / "foo_generator/foo_geometry.py").write_text("x = 2\n")
        _run("git", "add", "-A", cwd=repo)
        assert cvb.main(["--commit-msg", _msg(repo)]) == 1

    def test_merge_commit_is_skipped(self, repo):
        (repo / "foo_generator/foo_geometry.py").write_text("x = 2\n")
        _run("git", "add", "-A", cwd=repo)
        (repo / ".git/MERGE_HEAD").write_text(
            subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                           text=True, check=True).stdout)
        assert cvb.main(["--commit-msg", _msg(repo)]) == 0
