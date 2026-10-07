#!/usr/bin/env python3
"""
commit-msg check: a commit that changes a generator's code must also bump that
generator's VERSION (the `VERSION = "x.y.z"` constant in `<gen>/*_proxy.py`).

Why: the proxy VERSION is what the Report view prints and what is stored in
each object's GeneratorVersion property, so it is the only way to tell which
build produced a given model.  Fixes were landing without a bump (shingle's
chamfer fix, 2026-10-06; the 09-15 review pass across several generators), so
the number stopped meaning anything.

What counts as a code change in `<gen>/`: any *.py or *.FCMacro outside
`<gen>/tests/`.  Changes to shared/ are NOT checked here: they affect many
generators and have no single version to bump.

A bump must INCREASE the version in at least one of the generator's proxies.
A brand-new generator (no files in HEAD) is exempt.

Override for commits that genuinely need no bump (comment-only, a macro header
sync, ...): add a trailer line to the commit message --

    No-Version-Bump: <non-empty reason>

Usage (normally via .githooks/commit-msg):
    check_version_bump.py --commit-msg <path-to-message-file>
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

VERSION_RE = re.compile(r'^VERSION\s*=\s*["\'](\d+(?:\.\d+)*)["\']', re.MULTILINE)
TRAILER_RE = re.compile(r'^No-Version-Bump:\s*(\S.*)$', re.MULTILINE)


def parse_version(text):
    """Return the VERSION tuple declared in `text`, or None if absent."""
    m = VERSION_RE.search(text or "")
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def fmt(v):
    return ".".join(str(p) for p in v) if v else "(none)"


def is_code_file(path, gen):
    """True for a generator's own code: *.py / *.FCMacro outside tests/."""
    parts = Path(path).parts
    if len(parts) < 2 or parts[0] != gen or "tests" in parts[1:-1]:
        return False
    return parts[-1].endswith((".py", ".FCMacro")) and "__pycache__" not in parts


def generators_missing_bump(changed, old_versions, new_versions):
    """Pure core.

    changed:       paths changed in the commit (any status, deletions included)
    old_versions:  {proxy_path: VERSION tuple or None} at HEAD
    new_versions:  {proxy_path: VERSION tuple or None} in the commit
    Returns {generator: reason} for each generator that changed code without
    a version increase.
    """
    gens = sorted({Path(p).parts[0] for p in changed
                   if len(Path(p).parts) > 1 and Path(p).parts[0].endswith("_generator")})
    problems = {}
    for gen in gens:
        if not any(is_code_file(p, gen) for p in changed):
            continue
        proxies = sorted(p for p in set(old_versions) | set(new_versions)
                         if Path(p).parts[0] == gen)
        if not any(old_versions.get(p) for p in proxies):
            continue          # no proxy version at HEAD: new generator, exempt
        bumped = unchanged = False
        for p in proxies:
            old, new = old_versions.get(p), new_versions.get(p)
            if old is None or new is None:
                continue
            if new > old:
                bumped = True
            elif new < old:
                problems[gen] = f"VERSION went DOWN in {p}: {fmt(old)} -> {fmt(new)}"
                break
            else:
                unchanged = True
        if gen in problems or bumped:
            continue
        cur = next((fmt(v) for p in proxies if (v := old_versions.get(p))), "?")
        problems[gen] = (f"code changed but VERSION is still {cur} "
                         f"(bump it in {gen}/*_proxy.py)") if unchanged else \
                        "code changed but no proxy VERSION found to bump"
    return problems


def has_override(message):
    return TRAILER_RE.search(message) is not None


# -- git layer ----------------------------------------------------------------

def _git(*args, check=True):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check)


def _show(ref_path):
    r = _git("show", ref_path, check=False)
    return r.stdout if r.returncode == 0 else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--commit-msg", required=True, help="path to the commit message file")
    args = ap.parse_args(argv)

    if _git("rev-parse", "-q", "--verify", "MERGE_HEAD", check=False).returncode == 0:
        return 0              # merge commit: diff against HEAD is not "this commit's code"
    message = Path(args.commit_msg).read_text(encoding="utf-8", errors="replace")
    if has_override(message):
        print("check_version_bump: No-Version-Bump trailer present, skipping.")
        return 0

    status = _git("diff", "--cached", "--name-status", "-z", "--no-renames").stdout.split("\0")
    changed = [status[i + 1] for i in range(0, len(status) - 1, 2)]
    gens = {Path(p).parts[0] for p in changed if len(Path(p).parts) > 1
            and Path(p).parts[0].endswith("_generator")}
    old, new = {}, {}
    for gen in gens:
        tracked = set(_git("ls-tree", "-r", "--name-only", "HEAD", gen + "/").stdout.split("\n"))
        staged = set(_git("ls-files", gen + "/").stdout.split("\n"))
        for p in sorted(x for x in tracked | staged if x.endswith("_proxy.py")):
            old[p] = parse_version(_show(f"HEAD:{p}"))
            new[p] = parse_version(_show(f":{p}"))

    problems = generators_missing_bump(changed, old, new)
    if not problems:
        return 0
    print("check_version_bump: generator code changed without a version bump:", file=sys.stderr)
    for gen, reason in problems.items():
        print(f"  {gen}: {reason}", file=sys.stderr)
    print("\nBump VERSION (patch for a fix, minor for a feature) and add a changelog line,\n"
          "or, if this commit truly needs no bump, add a commit-message trailer:\n"
          "    No-Version-Bump: <reason>", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
