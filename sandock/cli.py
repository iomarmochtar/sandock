import os
import sys
import logging
import subprocess
from typing import List, Tuple, Dict, Any, Optional
from argparse import ArgumentParser, Namespace, REMAINDER, ArgumentTypeError
from importlib.metadata import metadata
from .config import MainConfig, load_config_file, main_config_finder
from .shared import log, SANDBOX_DEBUG_ENV, CONFIG_PATH_ENV, run_shell
from .sandbox import SandboxExec
from .volume import VolumeMgr
from .exceptions import SandboxBaseException, SandboxExecConfig, SandboxVolumeExec
from ._version import __version__, __build_hash__


def parse_arg_key_value(s: str) -> Tuple[str, str]:
    if "=" not in s:
        raise ArgumentTypeError(f"Invalid format: '{s}', expected KEY=VALUE")

    key, value = s.split("=", 1)
    return key, value


class BaseCommand(object):
    args: Namespace
    config: MainConfig
    description: str = ""

    def __init__(self, args: Namespace):
        self.args = args
        self.config = self._read_config()

    def output(self, msg: str) -> None:
        """
        a wrapper for any output to user (stdout), also as the easier way in test side
        """
        sys.stdout.write(f"{msg}\n")

    def override_arg(self, dashed: bool = True, name: str = "") -> str:
        """
        generate the override argument
        """
        prefix = self.config.execution.property_override_prefix_arg
        prefix = f"--{prefix}" if dashed else prefix
        return f"{prefix}{name}"

    @property
    def config_path(self) -> Optional[str]:
        """
        get main configuration path
        """
        return main_config_finder(explicit_mention=self.args.config)

    def _read_config(self) -> MainConfig:
        """
        read main configuration path file as conf object
        """
        config_path = self.config_path
        if config_path is None:
            raise SandboxExecConfig("no main configuration can be read")

        if not os.path.isfile(config_path):
            raise SandboxExecConfig(
                f"main configuration is not found (`{config_path}`)"
            )

        return load_config_file(path=config_path)

    @staticmethod
    def register_arguments(parser: ArgumentParser) -> None:
        pass

    def main(self) -> None:
        """
        main execution, should be extended
        """


class CmdList(BaseCommand):
    description = "list available sandboxed program, the name also added with a prefix name if configured"

    def main(self) -> None:
        for prog_name in self.config.programs.keys():
            self.output(prog_name)


class CmdAlias(BaseCommand):
    description = "print the list of alias as a shortcut to ran the programs, this should be added in shell profile configuration"

    @property
    def executor(self) -> str:
        """
        return executor name
        """
        return sys.argv[0]

    @staticmethod
    def register_arguments(parser: ArgumentParser) -> None:
        parser.add_argument(
            "--expand", help="include with aliases", action="store_true", default=False
        )

        parser.add_argument(
            "program_args",
            nargs=REMAINDER,
            help="program argument that will be forwarded",
        )

    def main(self) -> None:
        for prog_name, prog_cfg in self.config.programs.items():
            alias_key = f"{self.config.execution.alias_program_prefix}{prog_name}"
            alias_value = f"{self.executor} run {prog_name}"
            main_line = f'alias {alias_key}="{alias_value}"'
            self.output(main_line)
            if not self.args.expand:
                continue

            for alias_cmd in prog_cfg.aliases.keys():
                alias_exec_line = f'alias {alias_key}-{alias_cmd}="{alias_value} {self.override_arg(name="exec")}={alias_cmd}"'
                self.output(alias_exec_line)


class CmdVolume(BaseCommand):
    description = "manage container volumes"

    @staticmethod
    def register_arguments(parser: ArgumentParser) -> None:
        subs = parser.add_subparsers(
            title="volume action", dest="volume_action", required=True
        )

        # list
        subs.add_parser("list", help="list all volume that created by sandock")

        # backup subcmd
        backup_sub = subs.add_parser("backup", help="backup related command")
        # the default action is to create a backup
        backup_sub.add_argument(
            "-a",
            "--all",
            help="backup all volumes based mentioned labels in configuration",
            action="store_true",
            default=False,
        )
        backup_sub.add_argument(
            "--target", help="specific volume name that will be set as target backup"
        )
        backup_sub.add_argument(
            "-e", "--exclude", action="append", help="explicit exclude volume to backup"
        )
        backup_parser = backup_sub.add_subparsers(dest="backup_action")

        # backup - snapshot
        snapshot_sub = backup_parser.add_parser(
            "snapshot",
            help="show all existing backup snapshot, by default it's only shown the latest one",
        )
        snapshot_sub.add_argument(
            "--all",
            help="show all snapshots",
            action="store_true",
            default=False,
        )
        snapshot_sub.add_argument(
            "--vol",
            help="only show snapshot the specific volume backup",
            default=None,
        )

        # backup - restore
        restore_sub = backup_parser.add_parser(
            "restore", help="backup - volume restore command"
        )
        restore_sub.add_argument(
            "-i",
            "--snapshot-id",
            help="snapshot ID that will be restored",
            required=True,
        )
        restore_sub.add_argument(
            "--vol",
            help="target volume name that will be restored, if not exists then it will create the new one",
            required=True,
        )
        restore_sub.add_argument(
            "-f",
            "--force",
            help="force execution even the target volume is already exists, will be ran overrides action",
            action="store_true",
            default=False,
        )
        restore_sub.add_argument(
            "--exclude", action="append", help="exclude path to be restored"
        )
        restore_sub.add_argument(
            "--overwrite",
            help="set overwrite behaviour",
            default="never",
            choices=["always", "if-changed", "if-newer", "never"],
        )

        # backup - restic
        restic_sub = backup_parser.add_parser(
            "restic",
            help="backup - restic, direct restic command execution. use with cautions !!!",
        )
        restic_sub.add_argument(
            "--extra-run-args",
            help="additional docker run arguments, eg: mounting the volume etc.",
        )
        restic_sub.add_argument(
            "restic_params", nargs=REMAINDER, help="the forwarded arguments/params"
        )

    def run_backup(self, vol_mgr: VolumeMgr) -> None:
        # snapshot handler
        if self.args.backup_action == "snapshot":
            datetime_format = "%Y-%m-%d %H:%M:%S"
            for snapshot in vol_mgr.backup.snapshot_list(
                specific_volname=self.args.vol, show_all=self.args.all
            ):
                self.output(
                    f"id: {snapshot.id} - date: {snapshot.backup_time.strftime(datetime_format)} (UTC) - size: {snapshot.size} - vol: {snapshot.vol_name}"
                )

            return

        # restore handler
        if self.args.backup_action == "restore":
            backup_mgr = vol_mgr.backup
            snapshot = backup_mgr.get_snapshot_by(id=self.args.snapshot_id)
            backup_mgr.restore(
                snapshot=snapshot,
                target_volume=self.args.vol,
                force=self.args.force,
                excludes=self.args.exclude or [],
                overwrite=self.args.overwrite,
            )
            return

        # direct restic handler
        if self.args.backup_action == "restic":
            docker_params = []
            if self.args.extra_run_args:
                docker_params.append(self.args.extra_run_args)

            run_shell(
                command=vol_mgr.backup.restic_run_cmd(
                    extra_docker_params=docker_params,
                    restic_args=self.args.restic_params,
                ),
                capture_output=False,
            )
            return

        # create backup handler
        if self.args.target and self.args.all:
            raise SandboxVolumeExec(
                "cannot combine specific target with all volume option"
            )

        if not self.args.target and not self.args.all:
            raise SandboxVolumeExec("you must set explicitly volume backup target")

        targets = []
        if self.args.target:
            if not vol_mgr.vol_exists(name=self.args.target):
                raise SandboxVolumeExec(
                    f"volume by name `{self.args.target}` is not exists"
                )

            targets = [self.args.target]
        # if not specific then all volumes as configured
        else:
            vol_backup_labels = self.config.backup.volume_labels
            if not vol_backup_labels:
                raise SandboxVolumeExec(
                    "empty volume label filter for backup target, set it on .backup.volume.labels"
                )

            targets = [
                vol_info["Name"]
                for vol_info in vol_mgr.volume_list(label_filters=vol_backup_labels)
            ]

        if not targets:
            log.warning("no any volume backup target available")
            return

        vol_mgr.backup.create(targets=targets, excludes=self.args.exclude or [])

    def main(self) -> None:
        vol_mgr = VolumeMgr(cfg=self.config)

        sub_cmd = self.args.volume_action
        if sub_cmd == "list":
            for vol_info in vol_mgr.created_by_sandock:
                log.debug(f"volume info ~> {vol_info}")
                self.output(vol_info["Name"])

        elif sub_cmd == "backup":
            self.run_backup(vol_mgr=vol_mgr)


class CmdRun(BaseCommand):
    description = "run program"

    @property
    def overrides_args(self) -> ArgumentParser:
        oparser = ArgumentParser(description="overriding parameters")

        oparser.add_argument(
            self.override_arg(name="name"), default=None, help="override container name"
        )

        oparser.add_argument(
            self.override_arg(name="exec"), default=None, help="override exec"
        )

        oparser.add_argument(
            self.override_arg(name="hostname"), default=None, help="override hostname"
        )

        oparser.add_argument(
            self.override_arg(name="network"), default=None, help="override network"
        )

        oparser.add_argument(
            self.override_arg(name="allow-home-dir"),
            action="store_true",
            default=False,
            help="override allow home directory mount on auto mount current directory",
        )

        oparser.add_argument(
            self.override_arg(name="env"),
            action="append",
            type=parse_arg_key_value,
            help="set environment in KEY=VALUE format",
        )

        oparser.add_argument(
            self.override_arg(name="help"),
            action="store_true",
            default=False,
            help="show help",
        )

        return oparser

    @staticmethod
    def register_arguments(parser: ArgumentParser) -> None:
        parser.add_argument(
            "program",
        )

        parser.add_argument(
            "program_args",
            nargs=REMAINDER,
            help="arguments that will be forwarded, excluded for the override args",
        )

    def override_properties(self, args: List[str]) -> Dict[str, Any]:
        """
        convert the override argument to Program's property
        """
        result = {}
        kv_args = ["env"]
        ov_args = self.overrides_args
        for k, v in vars(ov_args.parse_args(args)).items():
            if v is None:
                continue
            arg_name = k.replace(self.override_arg(dashed=False).replace("-", "_"), "")
            if arg_name == "help":
                if v is True:
                    ov_args.print_help()
                    sys.exit(0)

                continue

            # convert to dict
            if arg_name in kv_args:
                v = dict(v or [])

            result[arg_name] = v
        return result

    @property
    def remainder_args(self) -> Tuple[List[str], Dict[str, str]]:
        """
        capture argument that will be forwarded to program and read for sandbox-exec
        """
        program_args = []
        snbx_args = []
        for remainder in self.args.program_args:
            if remainder.startswith(self.override_arg()):
                snbx_args.append(remainder)
                continue

            program_args.append(remainder)

        return (program_args, self.override_properties(args=snbx_args))

    def main(self) -> None:
        program_args, overrides = self.remainder_args
        log.debug(f"overrides args ~> {overrides}")
        snbx = SandboxExec(name=self.args.program, cfg=self.config, overrides=overrides)
        snbx.do(args=program_args)


def reraise_if_debug(e: Exception) -> None:
    """
    raise the exception if currently in debug mode
    """
    if log.level == logging.DEBUG:
        raise e


def main(args: Optional[List[str]] = None) -> None:
    meta = metadata("sandock")
    cmds = dict(list=CmdList, alias=CmdAlias, run=CmdRun, volume=CmdVolume)
    parser = ArgumentParser(
        description="A wrapper in running command inside container sandboxed environment",
        epilog=f"Author: {meta['author']} <{meta['author-email']}>",
    )
    parser.add_argument(
        "-c",
        "--config",
        help=f"path of configuration file, this can be overrided by env name `{CONFIG_PATH_ENV}`",
        default=None,
    )
    parser.add_argument(
        "-d",
        "--debug",
        help=f"enable debug mode, can be configured from env var `{SANDBOX_DEBUG_ENV}` by value `true`",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__} (build {__build_hash__})",
    )
    subs = parser.add_subparsers(title="commands", dest="subparser")
    # register sub-commands
    for sub_name, sub_cls in cmds.items():
        sub = subs.add_parser(sub_name, description=sub_cls.description)
        sub_cls.register_arguments(parser=sub)
    parsed_args = parser.parse_args(args=args)

    if parsed_args.debug or os.environ.get(SANDBOX_DEBUG_ENV) == "true":
        log.setLevel(logging.DEBUG)

    # only registered subcommand can be executed
    exec_cls = cmds.get(parsed_args.subparser)
    if not exec_cls:
        return parser.print_help()

    # remove the python stack trace noise on non 0 exit, except in debug mode
    try:
        exec_cls(args=parsed_args).main()
    except subprocess.CalledProcessError as e:
        reraise_if_debug(e=e)

        log.error(f"exit code {e.returncode}, see the details in debug mode")
        sys.exit(e.returncode)

    except SandboxBaseException as e:
        reraise_if_debug(e=e)

        log.error(f"{e}, see the details in debug mode")
        sys.exit(1)
