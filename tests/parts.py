"""The suite in parts, for the release workflow's parallel test jobs (``E2ER_TEST_PART=2/4``).

Whole test files go to a part, so a module's fixtures and its order stay as in one run. Each
file weighs what it took last time (``tests/test_durations.json``, seconds per file); a file not
in it weighs its number of tests times the average seconds per test. The heaviest file goes first
to the lightest part. Every collected test is in exactly one part, whatever the durations say:
stale durations only make the parts less even.

Refresh the durations after adding slow tests (docs/RELEASING.md):

    pytest tests/ -m "not e2e" --junitxml=/tmp/junit.xml
    python -m tests.parts /tmp/junit.xml
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

DURATIONS = Path(__file__).with_name("test_durations.json")


def parse_part(spec: str) -> tuple[int, int]:
    """``"2/4"`` -> (2, 4); refuses anything but 1 <= part <= parts."""
    try:
        a, b = (int(x) for x in spec.split("/"))
    except ValueError as e:
        raise ValueError(f"E2ER_TEST_PART must look like 2/4, not {spec!r}") from e
    if not 1 <= a <= b:
        raise ValueError(f"E2ER_TEST_PART {spec!r}: the part must be between 1 and {b}")
    return a, b


def load_durations(path: Path = DURATIONS) -> dict[str, float]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): float(v) for k, v in data.items()} if isinstance(data, dict) else {}


def assign(files: dict[str, int], parts: int, durations: dict[str, float]) -> list[list[str]]:
    """Files (name -> number of tests) split into ``parts`` lists of about equal weight."""
    known = [(durations[f], n) for f, n in files.items() if f in durations]
    per_test = sum(d for d, _ in known) / max(1, sum(n for _, n in known)) if known else 1.0
    weight = {f: durations.get(f, n * per_test) for f, n in files.items()}
    load = [0.0] * parts
    out: list[list[str]] = [[] for _ in range(parts)]
    for f in sorted(files, key=lambda f: (-weight[f], f)):
        k = min(range(parts), key=lambda k: (load[k], k))
        out[k].append(f)
        load[k] += weight[f]
    return out


def from_junit(xml_path: Path) -> dict[str, float]:
    """Seconds per test file from a JUnit XML report (``pytest --junitxml``)."""
    totals: dict[str, float] = defaultdict(float)
    for case in ET.parse(xml_path).iter("testcase"):
        cls = case.get("classname") or ""
        # classname is "tests.test_x" or "tests.test_x.TestClass"
        mod = cls.split(".")
        while mod and not mod[-1].startswith("test_"):
            mod.pop()
        if not mod:
            continue
        totals["/".join(mod) + ".py"] += float(case.get("time") or 0)
    return {k: round(v, 2) for k, v in sorted(totals.items())}


if __name__ == "__main__":
    got = from_junit(Path(sys.argv[1]))
    DURATIONS.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(got)} files, {sum(got.values()):.0f} s -> {DURATIONS}")
