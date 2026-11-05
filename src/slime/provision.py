"""Server provisioning: resolve a build, download the jar, write config."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass

from .api.catalog import ProjectCatalog
from .config import Config
from .errors import ServerError
from .java import JavaManager
from .models import (
    BuildInfo,
    Project,
    Server,
    required_java_major,
    validate_java_major,
    validate_memory,
    validate_port,
    validate_server_name,
)
from .properties import ensure_server_properties, write_eula
from .rcon import ensure_rcon_config
from .store import ServerStore
from .utils.downloads import download_file

ProvisionProgress = Callable[[str, int, int | None], None]


@dataclass(slots=True)
class CreateRequest:
    """Everything needed to create a server."""

    name: str
    project: Project | str
    version: str = ""
    build: int | None = None
    channel: str = "STABLE"
    memory_mb: int | None = None
    port: int | None = None
    java_major: int | None = None
    accept_eula: bool = False
    motd: str | None = None


class Provisioner:
    """Creates new server directories from download API builds."""

    def __init__(
        self,
        config: Config,
        store: ServerStore,
        catalog: ProjectCatalog,
        java_manager: JavaManager | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.catalog = catalog
        self.java_manager = java_manager

    def create(
        self,
        request: CreateRequest,
        *,
        progress: ProvisionProgress | None = None,
    ) -> Server:
        name = validate_server_name(request.name)
        project = Project.parse(request.project)
        if self.store.exists(name):
            raise ServerError(
                f"Server '{name}' already exists.",
                hint="Choose another name, or run `slime server info " + name + "`.",
            )

        version = request.version.strip()
        if not version:
            version = self.catalog.latest_version(project.value)

        build = self._resolve_build(project, version, request.build, request.channel)
        download = build.server_download

        memory_mb = validate_memory(
            request.memory_mb
            if request.memory_mb is not None
            else self.config.settings.default_memory_mb
        )
        port = validate_port(
            request.port if request.port is not None else self.config.settings.default_port
        )
        java_major = validate_java_major(
            request.java_major
            if request.java_major is not None
            else required_java_major(project, version)
        )

        server = Server(
            name=name,
            project=project,
            minecraft_version=version,
            build=build.build,
            java_major=java_major,
            memory_mb=memory_mb,
            port=port,
            eula_accepted=bool(request.accept_eula),
        )

        directory = self.store.path(name)
        preexisting = directory.exists()
        created_directory = False
        try:
            directory = self.store.create_directory(name)
            created_directory = not preexisting

            if progress:
                progress("Downloading server jar", 0, download.size)

            def on_download(done: int, total: int | None) -> None:
                if progress:
                    progress("Downloading server jar", done, total)

            download_file(
                download.url,
                directory / server.jar_file,
                sha256=download.sha256,
                size=download.size,
                user_agent=self.config.settings.user_agent,
                timeout=max(self.config.settings.request_timeout, 60.0),
                progress=on_download,
            )

            if not project.is_proxy:
                ensure_server_properties(
                    directory / "server.properties",
                    port=port,
                    motd=request.motd or f"{name} - powered by Slime",
                )
                ensure_rcon_config(directory, port)
                write_eula(directory / "eula.txt", accepted=server.eula_accepted)
            else:
                # Proxies generate their own config on first start. Drop a note
                # so users know where to look.
                (directory / "SLIME_PROXY.txt").write_text(
                    f"{project.display_name} generates its configuration on first start.\n"
                    "Edit velocity.toml / waterfall.yml, then run the server again.\n"
                    f"Configured port (informational): {port}\n",
                    encoding="utf-8",
                )

            self.store.save(server)
            if progress:
                progress("Server created", 1, 1)
            return server
        except Exception:
            if created_directory:
                shutil.rmtree(directory, ignore_errors=True)
            raise

    def _resolve_build(
        self,
        project: Project,
        version: str,
        build: int | None,
        channel: str,
    ) -> BuildInfo:
        if build is not None:
            return self.catalog.build(project.value, version, build)
        return self.catalog.latest_build(project.value, version, channel=channel)
