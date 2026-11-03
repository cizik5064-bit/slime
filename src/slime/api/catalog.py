"""Project-aware download API facade.

Paper, Folia, Velocity and Waterfall come from the PaperMC Fill API, while
Purpur has its own API. Callers pass a project id and the catalog picks the
right client, so provisioning and CLI code do not need project-specific
branches.
"""

from __future__ import annotations

from ..models import BuildInfo, Project
from .papermc import PaperMCClient
from .purpur import PurpurClient


class ProjectCatalog:
    """Route ``versions``/``builds`` calls to the correct download API."""

    def __init__(self, papermc: PaperMCClient, purpur: PurpurClient) -> None:
        self.papermc = papermc
        self.purpur = purpur

    def _client(self, project: str | Project) -> PaperMCClient | PurpurClient:
        if Project.parse(project) is Project.PURPUR:
            return self.purpur
        return self.papermc

    def close(self) -> None:
        self.papermc.close()
        self.purpur.close()

    def versions(self, project: str | Project) -> list[str]:
        return self._client(project).versions(project.value if isinstance(project, Project) else project)

    def latest_version(self, project: str | Project) -> str:
        return self._client(project).latest_version(
            project.value if isinstance(project, Project) else project
        )

    def builds(self, project: str | Project, version: str) -> list[BuildInfo]:
        return self._client(project).builds(
            project.value if isinstance(project, Project) else project, version
        )

    def build(self, project: str | Project, version: str, build: int) -> BuildInfo:
        return self._client(project).build(
            project.value if isinstance(project, Project) else project, version, build
        )

    def latest_build(
        self,
        project: str | Project,
        version: str,
        *,
        channel: str = "STABLE",
    ) -> BuildInfo:
        return self._client(project).latest_build(
            project.value if isinstance(project, Project) else project,
            version,
            channel=channel,
        )
