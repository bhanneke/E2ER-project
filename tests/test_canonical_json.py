# ruff: noqa: E501  (the site's JavaScript is copied verbatim)
"""The dossier's canonical JSON is byte for byte what e2er.org computes.

A dossier's address is the SHA-256 of its canonical JSON, and the site checks
every address it receives. Python's ``json.dumps(sort_keys=True)`` disagreed
with the site's JavaScript on floats (``1.0`` / ``1``, ``1e-05`` /
``0.00001``, ``1e16``, ``-0.0``), on integers beyond 2^53, on NaN and Infinity,
and on the order of keys outside the Basic Multilingual Plane. ``canonical``
now writes RFC 8785 (JCS) exactly as the site does, and refuses what has no
canonical form.

The four dossiers already published on e2er.org (fetched from
``GET https://e2er.org/api/v1/dossiers/<short>`` on 2026-10-01) must keep
their addresses.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from src.core.dossier import CanonicalError, canonical, dossier_id

LIVE = Path(__file__).parent / "fixtures" / "live_dossiers"

# The site's two functions, copied verbatim: integrity-core.mjs (RFC 8785, refuses
# what has no canonical form; the one publish runs) and common.ts / dossier.mjs
# (the plain form the dossier page and the build scripts run).
JS = r"""
class CanonicalError extends Error {}
function canonical(x, at = '$') {
  if (Array.isArray(x)) return '[' + x.map((v, i) => canonical(v, `${at}[${i}]`)).join(',') + ']';
  if (x === null) return 'null';
  switch (typeof x) {
    case 'object': {
      const o = x;
      return '{' + Object.keys(o).sort().filter((k) => o[k] !== undefined).map((k) => JSON.stringify(k) + ':' + canonical(o[k], `${at}.${k}`)).join(',') + '}';
    }
    case 'number':
      if (!Number.isFinite(x)) throw new CanonicalError(`${at} is ${x}.`);
      if (Number.isInteger(x) && !Number.isSafeInteger(x)) throw new CanonicalError(`${at} is ${x}`);
      return JSON.stringify(x);
    case 'string':
    case 'boolean':
      return JSON.stringify(x);
    default:
      throw new CanonicalError(`${at} is ${typeof x}`);
  }
}
function plain(x) {
  if (Array.isArray(x)) return '[' + x.map(plain).join(',') + ']';
  if (x && typeof x === 'object') return '{' + Object.keys(x).sort().filter((k) => x[k] !== undefined).map((k) => JSON.stringify(k) + ':' + plain(x[k])).join(',') + '}';
  return JSON.stringify(x);
}
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = {};
for (const [name, wire] of Object.entries(cases)) {
  let doc;
  try { doc = JSON.parse(wire); } catch (e) { out[name] = {refused: true, plain: null}; continue; }
  let c = null, refused = false;
  try { c = canonical(doc); } catch (e) { refused = true; }
  out[name] = {refused, canonical: c, plain: plain(doc)};
}
process.stdout.write(JSON.stringify(out));
"""

TRICKY: dict[str, object] = {
    "ascii": {"b": 1, "a": [True, None, "x"]},
    "unicode_raw": {"t": "Müller – “quoted” 中文 😀"},
    "control_chars": {"t": "a\u0000b\u001fc\u007fd\tline\n\r\b\f"},
    "u2028": {"t": "x y z"},
    "key_sort_bmp_vs_astral": {"\uff01": 1, "\U0001f600": 2, "\ue000": 3},
    "key_sort_case": {"B": 1, "a": 2, "_": 3, "é": 4, "": 5},
    # raw keys are sorted, not their escaped form ('a"' is written a\\" but sorts as a")
    "key_sort_escaped": {'a"': 1, "a": 2, "a\u0001": 3, "a!": 4, "a\\": 5, "a\n": 6},
    "float_1.0": {"temperature": 1.0},
    "float_1e-05": {"x": 1e-05},
    "float_1e-07": {"x": 1e-7},
    "float_2.5e-06": {"x": 2.5e-6},
    "float_0.1+0.2": {"x": 0.1 + 0.2},
    "float_1e16": {"x": 1e16},
    "float_1e21": {"x": 1e21},
    "float_1e15": {"x": 1e15},
    "float_1.5": {"x": 1.5},
    "float_123456.789": {"x": 123456.789},
    "float_tiny": {"x": 5e-324},
    "float_huge_frac": {"x": 1.7976931348623157e308 / 1e300},
    "float_neg": {"x": -0.000123, "y": -12.5, "z": -1e-9},
    "float_round": {"x": 0.0136, "y": 4.2, "z": 19.2, "w": 1573.89},
    "neg_zero": {"x": -0.0},
    "int_max_safe": {"x": 2**53 - 1, "y": -(2**53 - 1)},
    "bigint_2_53p1": {"x": 2**53 + 1},
    "bigint_2_64": {"x": 2**64},
    "nan": {"x": float("nan")},
    "inf": {"x": float("inf")},
    "neg_inf": {"x": float("-inf")},
    "nested_empty": {"a": {}, "b": [], "c": ""},
    "html_breakout": {"t": "</script><script>alert(1)</script>"},
    "slash": {"t": 'a/b\\c"d'},
    "nfc_nfd": {"x": "é", "y": "é"},
    "deep": {"a": [{"b": [{"c": [1.0, 2.5, {"d": None}]}]}]},
}


def test_the_four_published_dossiers_keep_their_addresses():
    found = sorted(LIVE.glob("*.json"))
    assert len(found) == 4
    for f in found:
        doc = json.loads(f.read_text(encoding="utf-8"))
        assert dossier_id(doc).removeprefix("sha256:").startswith(f.stem), f.name


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (1.0, "1"),
        (1e-05, "0.00001"),
        (1e-7, "1e-7"),
        (-0.0, "0"),
        (1e15, "1000000000000000"),
        (0.1 + 0.2, "0.30000000000000004"),
        (123456.789, "123456.789"),
        (1.23e-18, "1.23e-18"),
        (2**53 - 1, "9007199254740991"),
        # U+1F600 is D83D DE00 in UTF-16, so it sorts before U+FF01 (code-point order says the opposite)
        ({"\uff01": 2, "\U0001f600": 1}, '{"\U0001f600":1,"\uff01":2}'),
    ],
)
def test_numbers_and_keys_are_written_as_javascript_writes_them(value, text):
    assert canonical(value) == text


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), 2**53 + 1, 1e16, 1e21, -(2**60), {1: "x"}, {"x": {1, 2}}]
)
def test_values_without_a_canonical_form_are_refused_with_a_clear_error(value):
    with pytest.raises(CanonicalError) as e:
        canonical({"run": {"value": value}})
    assert "$.run.value" in str(e.value) or "key" in str(e.value)


def test_a_lone_surrogate_is_refused():
    with pytest.raises(CanonicalError):
        canonical({"t": "\ud800"})


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_python_and_the_sites_javascript_agree_on_tricky_documents():
    docs = dict(TRICKY)
    for f in sorted(LIVE.glob("*.json")):
        docs[f"live_{f.stem}"] = json.loads(f.read_text(encoding="utf-8"))
    # What travels to the site is JSON text; Python's own document is what it hashes.
    wire = {name: json.dumps(doc, ensure_ascii=False) for name, doc in docs.items()}
    res = subprocess.run(["node", "-e", JS], input=json.dumps(wire), capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    js = json.loads(res.stdout)
    for name, doc in docs.items():
        try:
            py = canonical(doc)
        except CanonicalError:
            py = None
        if js[name]["refused"]:
            assert py is None, f"{name}: the site refuses it, Python wrote {py!r}"
            continue
        assert py == js[name]["canonical"], name
        # For a document the site accepts, its plain form (dossier page, build scripts) is the same text.
        assert py == js[name]["plain"], name


def test_refusals_match_the_site():
    """NaN, Infinity and unsafe integers: the site refuses them, so must e2er (before sending)."""
    for name in ("nan", "inf", "neg_inf", "bigint_2_53p1", "bigint_2_64", "float_1e16", "float_1e21"):
        with pytest.raises(CanonicalError):
            canonical(TRICKY[name])
    assert not math.isnan(json.loads(canonical(TRICKY["float_1.0"]))["temperature"])
