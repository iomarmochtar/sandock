from typing import List, Dict
from dataclasses import dataclass, field
from ._helpers import build_if_set

KNOWN_COMPRESSION = ["auto", "off", "max"]


@dataclass
class Restic(object):
    image: str = "restic/restic:0.18.0"
    compression: str = "auto"
    no_snapshot_unless_changed: bool = True
    extra_args: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.compression not in KNOWN_COMPRESSION:
            raise ValueError(
                f"unknown compression `{self.compression}` the valid option are {', '.join(KNOWN_COMPRESSION)}"
            )


@dataclass
class BackupPath(object):
    default: str = "${HOME}/.sandock_vol_backup"
    # TODO: path maps to backup repo based on label


@dataclass
class Backup(object):
    restic: Restic = field(default_factory=Restic)
    path: BackupPath = field(default_factory=BackupPath)
    no_password: bool = False
    volume_labels: Dict[str, str] = field(default_factory=dict)
    volume_excludes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        build_if_set(self, attr="restic", cls=Restic)
        build_if_set(self, attr="path", cls=BackupPath)
