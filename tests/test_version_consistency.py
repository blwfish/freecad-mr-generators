"""Each generator's macro header version must match its proxy's VERSION.

The proxy `VERSION` constant is the single source of truth (printed in the
Report view, stored in GeneratorVersion).  The macro's docstring header
("... for FreeCAD v6.0.1") is a hand-typed copy; this fails when they drift,
which had already happened in six generators.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VERSION_RE = re.compile(r'^VERSION\s*=\s*["\'](\d+(?:\.\d+)*)["\']', re.MULTILINE)
HEADER_RE = re.compile(r'\bv(\d+(?:\.\d+)+)\b')


def _cases():
    out = []
    for gen in sorted(ROOT.glob("*_generator")):
        proxies = [p for p in gen.glob("*_proxy.py") if VERSION_RE.search(p.read_text())]
        macros = list(gen.glob("*.FCMacro"))
        if len(proxies) != 1 or len(macros) != 1:
            continue
        head = "\n".join(macros[0].read_text().splitlines()[:6])
        m = HEADER_RE.search(head)
        if not m:
            continue                      # macro has no version header to check
        out.append((gen.name, VERSION_RE.search(proxies[0].read_text()).group(1), m.group(1)))
    return out


def test_found_generators_to_check():
    assert len(_cases()) >= 10, "expected most generators to carry a macro header version"


@pytest.mark.parametrize("gen,proxy_version,macro_header", _cases(),
                         ids=[c[0] for c in _cases()])
def test_macro_header_matches_proxy_version(gen, proxy_version, macro_header):
    assert macro_header == proxy_version, (
        f"{gen}: macro header says v{macro_header} but {gen}/*_proxy.py "
        f"VERSION is {proxy_version}; update the macro's docstring header")
