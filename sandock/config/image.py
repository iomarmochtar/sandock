from dataclasses import dataclass, field
from typing import List, Optional, Dict


@dataclass
class ImageBuild(object):
    context: Optional[str] = None
    dockerfile_inline: Optional[str] = None
    dockerFile: Optional[str] = None
    depends_on: Optional[str] = None
    args: Dict[str, str] = field(default_factory=dict)
    extra_build_args: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.dockerfile_inline and self.dockerFile:
            raise ValueError("cannot set `dockerfile_inline` and `dockerFile` together")
