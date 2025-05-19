import json
import re
from getpass import getpass
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Union
from datetime import datetime
from .exceptions import SandboxVolumeExec, SandboxVolumeNotFound
from .config import MainConfig
from .config.backup import Backup as BackupCfg
from .sandbox import VOL_LABEL_CREATED_BY
from .shared import run_shell, log, KV, ensure_home_dir_special_prefix

BACKUP_MOUNT = "/backup_repo"
RESTORE_MOUNT_PREFIX = "/restore_vol_"
SOURCE_MOUNT_PREFIX = "/source_vol_"
BACKUP_IGNORE_REF_FILENAME = ".sandock_backup_ignore"

source_mount_prefix_re = re.compile(rf"^{SOURCE_MOUNT_PREFIX}")


def bytes_to_readable(num_bytes: float, decimal_places: int = 2) -> str:
    # convert bytes to humand readable
    units = ["B", "KB", "MB", "GB", "TB", "PB", "EB"]
    index = 0
    while num_bytes >= 1024 and index < len(units) - 1:
        num_bytes /= 1024.0
        index += 1

    return f"{num_bytes:.{decimal_places}f} {units[index]}"


@dataclass
class BackupSnapshot(object):
    id: str
    backup_time: datetime
    path: str
    bytes: int

    @property
    def vol_name(self) -> str:
        return source_mount_prefix_re.sub("", self.path)

    @property
    def size(self) -> str:
        # human readable size
        return bytes_to_readable(num_bytes=self.bytes)

    @classmethod
    def from_raw(self, data: KV) -> "BackupSnapshot":
        return self(
            id=data["short_id"],
            path=data["paths"][0],
            bytes=data["summary"]["total_bytes_processed"],
            backup_time=datetime.strptime(data["time"][:26], "%Y-%m-%dT%H:%M:%S.%f"),
        )


class VolumeMgr(object):
    cfg: MainConfig

    def __init__(self, cfg: MainConfig):
        self.cfg = cfg

    def volume_list(self, label_filters: KV = {}) -> List[KV]:
        # get the volume list that created by sandock
        volume_list_cmd = [
            self.cfg.execution.docker_bin,
            "volume",
            "ls",
            "--format=json",
        ]

        volume_list_cmd.extend(
            [f"--filter=label={k}='{v}'" for k, v in label_filters.items()]
        )

        exec_result = run_shell(command=volume_list_cmd)
        return [json.loads(line) for line in exec_result.stdout.split()]

    @property
    def created_by_sandock(self) -> List[KV]:
        # get the volume list that created by sandock

        return self.volume_list(label_filters={VOL_LABEL_CREATED_BY: "true"})

    def file_exists_in_vol(
        self, name: str, path: str, container: str = "docker.io/library/ubuntu:22.04"
    ) -> bool:
        # check if the mentioned path exists in specific volume ?
        check_file_cmd = [
            self.cfg.execution.docker_bin,
            "run",
            "-it",
            "--rm",
            "--entrypoint=test",
            f"-v {name}:/check_vol",
            container,
            "-f",
            f"/check_vol/{path}",
        ]
        result = run_shell(command=check_file_cmd, check_err=False)
        return result.returncode == 0

    def vol_exists(self, name: str) -> bool:
        # check if the mentioned volume exists ?
        vol_inspect_cmd = [
            self.cfg.execution.docker_bin,
            "volume",
            "inspect",
            f"'{name}'",
            "--format=json",
        ]

        cmd_out = run_shell(command=vol_inspect_cmd, check_err=False)

        if cmd_out.returncode == 0:
            vol_info = json.loads(cmd_out.stdout)
            log.debug(f"[vol] exists, info ~> {vol_info}")
            return True

        log.debug(f"vol by name {name} is not exists, err: {cmd_out.stderr}")
        return False

    @property
    def backup(self) -> "BackupMgr":
        return BackupMgr(vol_mgr=self)


class BackupMgr(object):
    vol_mgr: VolumeMgr
    # this only used once
    _backup_password: Optional[str] = None

    def __init__(self, vol_mgr: VolumeMgr):
        self.vol_mgr = vol_mgr
        if not self.cfg.no_password:
            self._backup_password = getpass("backup password: ")

    @property
    def cfg(self) -> BackupCfg:
        # backup related configuration
        return self.vol_mgr.cfg.backup

    @property
    def backup_dir(self) -> str:
        # return backup directory, escaping any home directory pattern
        return ensure_home_dir_special_prefix(path=self.cfg.path.default)

    @property
    def backup_config(self) -> Path:
        # returning restic config file inside repository, as the key indicator for some action (check initialized, etc)
        return Path(self.backup_dir, "config")

    def restic_run_cmd(
        self, extra_docker_params: List[str] = [], restic_args: List[str] = []
    ) -> List[str]:
        # compose restric command execution in container
        cmd = (
            [
                self.vol_mgr.cfg.execution.docker_bin,
                "run",
                "-it",
                "--rm",
                "--hostname=sandock",
                "--entrypoint=restic",
                f"-v {self.backup_dir}:{BACKUP_MOUNT}",
            ]
            + extra_docker_params
            + (
                [f"-e RESTIC_PASSWORD='{self._backup_password}'"]
                if self._backup_password is not None
                else []
            )
            + [self.cfg.restic.image]
            + [
                f"--repo={BACKUP_MOUNT}",
                f"--compression={self.cfg.restic.compression}",
                "--no-cache",
            ]
            + (["--insecure-no-password"] if self.cfg.no_password else [])
            + self.cfg.restic.extra_args
            + restic_args
        )

        return cmd

    def ensure_restic_repository(self) -> None:
        # ensuring restic repository (backup folder) has been initialized
        if self.backup_config.exists():
            log.debug(
                f"backup config binary is exists ({self.backup_config}), means it already initialized"
            )
            return

        log.warning(
            f"backup repository ({self.backup_dir}) is not initialized, running initialization"
        )

        init_repo_cmd = self.restic_run_cmd(restic_args=["init"])
        run_shell(command=init_repo_cmd, capture_output=False)

    def to_backup_path(self, vol_name: str) -> str:
        # returning the form of path name inside restic container
        return f"{SOURCE_MOUNT_PREFIX}{vol_name}"

    def create(self, targets: List[str], excludes: List[str] = []) -> None:
        # backup one or more volume target
        self.ensure_restic_repository()
        for target_vol in targets:
            if target_vol in self.cfg.volume_excludes:
                log.warning(
                    f"skipping backup for volume `{target_vol}`, listed in config exclude list"
                )
                continue

            if target_vol in excludes:
                log.warning(
                    f"skipping backup for volume `{target_vol}`, listed explicitly"
                )
                continue

            log.info(f"begin volume backup `{target_vol}`")
            backup_ignore_exists = False
            if self.vol_mgr.file_exists_in_vol(
                name=target_vol,
                path=BACKUP_IGNORE_REF_FILENAME,
                container=self.cfg.restic.image,
            ):
                log.debug(
                    f"backup ignore file ({BACKUP_IGNORE_REF_FILENAME}) in volume {target_vol}"
                )
                backup_ignore_exists = True

            source_mountpoint = self.to_backup_path(vol_name=target_vol)
            backup_cmd = self.restic_run_cmd(
                extra_docker_params=[f"-v {target_vol}:{source_mountpoint}:ro"],
                restic_args=[
                    "backup",
                    (
                        "--skip-if-unchanged"
                        if self.cfg.restic.no_snapshot_unless_changed
                        else ""
                    ),
                    "--group-by=paths",
                    (
                        f"--exclude-file={source_mountpoint}/{BACKUP_IGNORE_REF_FILENAME}"
                        if backup_ignore_exists
                        else ""
                    ),
                    source_mountpoint,
                ],
            )

            run_shell(command=backup_cmd, capture_output=False)

    def snapshot_list(
        self, specific_volname: Optional[str] = None, show_all: bool = False
    ) -> List[BackupSnapshot]:
        if not self.backup_config.exists():
            raise SandboxVolumeExec(
                f"backup repository ({self.backup_dir}) is not initialized"
            )

        snapshot_list_cmd = self.restic_run_cmd(restic_args=["snapshots", "--json"])
        if specific_volname:
            snapshot_list_cmd.append(
                f"--path={self.to_backup_path(vol_name=specific_volname)}"
            )

        if not show_all:
            snapshot_list_cmd.append("--latest=1")

        snapshots = json.loads(run_shell(command=snapshot_list_cmd).stdout)
        return [BackupSnapshot.from_raw(data=s) for s in snapshots]

    def get_snapshot_by(self, id: str) -> BackupSnapshot:
        snapshot_byid_cmd = self.restic_run_cmd(restic_args=["snapshots", id, "--json"])
        snapshot_byid_output = run_shell(command=snapshot_byid_cmd).stdout
        if "no matching ID found for prefix" in snapshot_byid_output:
            log.debug(f"snapshot by ID `{id}` is not found ~> {snapshot_byid_output}")
            raise SandboxVolumeNotFound(f"backup snapshot by id `{id}` is not found")

        return BackupSnapshot.from_raw(data=json.loads(snapshot_byid_output)[0])

    def restore(
        self,
        snapshot: Union[str, BackupSnapshot],
        target_volume: str,
        force: bool = False,
        excludes: List[str] = [],
        overwrite: Optional[str] = None,
    ) -> None:
        # restore backup result (snapshot) to a specific volume
        if not force and self.vol_mgr.vol_exists(name=target_volume):
            raise SandboxVolumeExec(
                f"volume by name `{target_volume}` is already exists, try to set force parameter to enforce it"
            )

        if isinstance(snapshot, str):
            snapshot = self.get_snapshot_by(id=snapshot)

        restore_mount_point = f"{RESTORE_MOUNT_PREFIX}{target_volume}"
        restore_cmd = self.restic_run_cmd(
            extra_docker_params=[f"-v {target_volume}:{restore_mount_point}"],
            restic_args=[
                "restore",
                f"{snapshot.id}:{snapshot.path}",
                f"--target={restore_mount_point}",
            ],
        )
        restore_cmd.extend([f"--exclude={ex}" for ex in excludes])

        if overwrite:
            restore_cmd.append(f"--overwrite={overwrite}")

        # TODO: check restore result
        run_shell(command=restore_cmd)

        log.info(f"backup snapshot by id {snapshot.id} ({snapshot.vol_name}) restored")
