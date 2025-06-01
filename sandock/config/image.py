from dataclasses import dataclass, field
from typing import List, Optional, Dict
from ._helpers import build_if_set

DEFAULT_DUMP_IMAGE_STORE = (
    "${HOME}/.sandock_dump_images/${image}:${platform}${hash}.tar"
)


@dataclass
class ImageDump(object):
    enable: bool = False
    cleanup_prev: bool = True
    store: str = DEFAULT_DUMP_IMAGE_STORE


@dataclass
class ImageBuild(object):
    context: Optional[str] = None
    dockerfile_inline: Optional[str] = None
    dockerFile: Optional[str] = None
    depends_on: Optional[str] = None
    args: Dict[str, str] = field(default_factory=dict)
    extra_build_args: List[str] = field(default_factory=list)
    dump: ImageDump = field(default_factory=ImageDump)

    def __post_init__(self) -> None:
        if self.dockerfile_inline and self.dockerFile:
            raise ValueError("cannot set `dockerfile_inline` and `dockerFile` together")

        build_if_set(self, attr="dump", cls=ImageDump)
