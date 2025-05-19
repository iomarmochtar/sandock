from dataclasses import dataclass, field
from typing import List, Optional, Dict
from .image import ImageBuild
from ._helpers import build_if_set


@dataclass
class SandboxMount(object):
    enable: bool = True
    read_only: bool = False
    current_dir_mount: str = "/sandbox"


@dataclass
class PersistContainer(object):
    enable: bool = False
    auto_start: bool = True


@dataclass
class ContainerUser(object):
    uid: int = 0
    gid: int = 0
    # keep both uid and gid
    keep_id: bool = False

    def __post_init__(self) -> None:
        if self.keep_id and self.uid != 0:
            raise ValueError(
                "cannot enabled on `keep_id` and set custom on `uid` in same time"
            )

        if self.keep_id and self.gid != 0:
            raise ValueError(
                "cannot enabled on `keep_id` and set custom on `gid` in same time"
            )


@dataclass
class Program(object):
    image: str
    exec: str
    interactive: bool = True
    allow_home_dir: bool = False
    name: Optional[str] = None
    network: Optional[str] = None
    hostname: Optional[str] = None
    build: Optional[ImageBuild] = None
    user: Optional[ContainerUser] = None
    workdir: Optional[str] = None
    platform: Optional[str] = None
    persist: PersistContainer = field(default_factory=PersistContainer)
    sandbox_mount: SandboxMount = field(default_factory=SandboxMount)
    env: Dict[str, str] = field(default_factory=dict)
    volumes: List[str] = field(default_factory=list)
    ports: List[str] = field(default_factory=list)
    cap_add: List[str] = field(default_factory=list)
    cap_drop: List[str] = field(default_factory=list)
    aliases: Dict[str, str] = field(default_factory=dict)
    extra_run_args: List[str] = field(default_factory=list)
    pre_exec_cmds: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        build_if_set(self, attr="build", cls=ImageBuild)
        build_if_set(self, attr="user", cls=ContainerUser)
        build_if_set(self, attr="persist", cls=PersistContainer)
        build_if_set(self, attr="sandbox_mount", cls=SandboxMount)

        if self.sandbox_mount.enable and self.workdir:
            raise ValueError(
                "cannot use workdir with enabled sandbox mount in the same time"
            )
