"""Generate a shields.io endpoint badge for the test coverage report.

CI runs this after pytest has produced ``coverage.xml`` and publishes the
resulting JSON on the ``badges`` branch. The README points shields.io at that
file, so the coverage badge does not depend on an external service account.
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def coverage_percent(report: Path) -> float:
    """Return line coverage from a Cobertura-style ``coverage.xml`` file."""
    root = ET.parse(report).getroot()
    line_rate = root.get("line-rate")
    if line_rate is None:
        message = f"{report} has no line-rate attribute"
        raise ValueError(message)
    return round(float(line_rate) * 100, 1)


def badge_color(percent: float) -> str:
    if percent >= 90:
        return "brightgreen"
    if percent >= 80:
        return "green"
    if percent >= 70:
        return "yellowgreen"
    if percent >= 60:
        return "yellow"
    if percent >= 50:
        return "orange"
    return "red"


def render_badge(percent: float) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "label": "coverage",
        "message": f"{percent:.0f}%",
        "color": badge_color(percent),
    }


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 2:
        print("usage: coverage_badge.py <coverage.xml> <output.json>", file=sys.stderr)
        return 2
    report = Path(arguments[0])
    output = Path(arguments[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(render_badge(coverage_percent(report))) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
