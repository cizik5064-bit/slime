from __future__ import annotations

from typing import Any

from slime.api.catalog import ProjectCatalog
from slime.models import BuildInfo


class FakeClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[str, Any]] = []
        self.closed = False

    def versions(self, project: str) -> list[str]:
        self.calls.append(("versions", project))
        return [f"{self.name}-version"]

    def latest_version(self, project: str) -> str:
        self.calls.append(("latest_version", project))
        return f"{self.name}-latest"

    def builds(self, project: str, version: str) -> list[BuildInfo]:
        self.calls.append(("builds", (project, version)))
        return []

    def build(self, project: str, version: str, build: int) -> BuildInfo:
        self.calls.append(("build", (project, version, build)))
        return BuildInfo(project=project, version=version, build=build)

    def latest_build(
        self, project: str, version: str, *, channel: str = "STABLE"
    ) -> BuildInfo:
        self.calls.append(("latest_build", (project, version, channel)))
        return BuildInfo(project=project, version=version, build=1)

    def close(self) -> None:
        self.closed = True


def make_catalog() -> tuple[ProjectCatalog, FakeClient, FakeClient]:
    paper = FakeClient("paper")
    purpur = FakeClient("purpur")
    return ProjectCatalog(paper, purpur), paper, purpur  # type: ignore[arg-type]


def test_purpur_routes_to_purpur_client() -> None:
    catalog, paper, purpur = make_catalog()
    assert catalog.versions("purpur") == ["purpur-version"]
    assert catalog.latest_version("purpur") == "purpur-latest"
    assert catalog.builds("purpur", "1.21.8") == []
    assert catalog.build("purpur", "1.21.8", 2).build == 2
    assert catalog.latest_build("purpur", "1.21.8").build == 1
    assert purpur.calls
    assert paper.calls == []


def test_paper_family_routes_to_fill_client() -> None:
    catalog, paper, purpur = make_catalog()
    for project in ("paper", "folia", "velocity", "waterfall"):
        catalog.versions(project)
    assert [call[1] for call in paper.calls] == [
        "paper",
        "folia",
        "velocity",
        "waterfall",
    ]
    assert purpur.calls == []


def test_close_closes_both_clients() -> None:
    catalog, paper, purpur = make_catalog()
    catalog.close()
    assert paper.closed is True
    assert purpur.closed is True
