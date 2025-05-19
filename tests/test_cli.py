import unittest
import subprocess
import logging
import os
from datetime import datetime
from unittest import mock
from unittest.mock import MagicMock, patch, PropertyMock
from argparse import ArgumentParser
from contextlib import contextmanager
from argparse import Namespace
from unittest import mock
from helpers import (
    dummy_main_cfg,
    dummy_program_cfg,
    temp_enable_debug,
    fixture_path,
    BaseTestCase,
)
from typing import Iterator, List, Optional, Tuple
from sandock.config import MainConfig
from sandock.shared import log
from sandock.exceptions import (
    SandboxExecution,
    SandboxExecConfig,
    SandboxVolumeExec,
)
from sandock.cli import (
    BaseCommand,
    CmdList,
    CmdAlias,
    CmdRun,
    CmdVolume,
    main as cli_main,
)
from sandock.volume import VolumeMgr, BackupSnapshot
from helpers import mock_shell_exec


class SkeltonCmdTest(BaseTestCase):
    cls: BaseCommand

    def _output_list(self, o: BaseCommand) -> List[str]:
        return [x[0][0] for x in o.output.call_args_list]

    @contextmanager
    def obj(
        self, args: Namespace, cfg: Optional[MainConfig] = None, **kwargs
    ) -> Iterator[BaseCommand]:
        if not cfg:
            cfg = dummy_main_cfg()

        with mock.patch.multiple(
            self.cls, _read_config=mock.Mock(return_value=cfg), **kwargs
        ):
            o = self.cls(args=args)
            o.output = mock.Mock()

            yield o


class BaseCommandTest(SkeltonCmdTest):
    cls = BaseCommand

    @mock.patch.dict(os.environ, dict(SNDK_CFG="/pointed/by/env"))
    def test_config_prioriting_explicit(self) -> None:
        # prioriting the mentioned
        with self.obj(args=Namespace(config="/path/to/config")) as o:
            self.assertEqual(o.config_path, "/path/to/config")

    def test_read_config_not_found(self) -> None:
        cfg_path = fixture_path("sample_configs", "not_found.yml")
        with self.assertRaisesRegex(
            SandboxExecConfig, f"main configuration is not found \(`{cfg_path}`\)"
        ):
            args = Namespace(config=cfg_path)
            self.cls(args=args)

    def test_read_config(self) -> None:
        args = Namespace(config=fixture_path("sample_configs", "ok_simple.yml"))
        o: BaseCommand = self.cls(args=args)
        expected_config = MainConfig(
            execution=dict(docker_bin="podman"),
            volumes=dict(go_cache={}),
            programs=dict(
                py311=dict(
                    image="python:3.11.12-slim-bullseye",
                    exec="python3",
                    network="host",
                    aliases=dict(sh="/bin/bash"),
                ),
                go122=dict(
                    image="golang:1.22.12-bookworm",
                    exec="go",
                    env=dict(GOCACHE="/cache/gocache", GOMODCACHE="/cache/gomodcache"),
                    volumes=["go_cache:/cache"],
                ),
            ),
        )
        self.assertEqual(o.config, expected_config)

    @mock.patch.object(BaseCommand, "config_path", None)
    def test_read_config_cannot_be_found(self) -> None:
        args = Namespace(config=None)
        with self.assertRaisesRegex(
            SandboxExecConfig, "no main configuration can be read"
        ):
            o = BaseCommand(args=args)

    def test_read_config_not_exists(self) -> None:
        args = Namespace(config=fixture_path("this", "is", "not", "exists"))
        with self.assertRaisesRegex(
            SandboxExecConfig, "main configuration is not found"
        ):
            o = BaseCommand(args=args)


class CmdListTest(SkeltonCmdTest):
    cls = CmdList

    def test_main(self) -> None:
        # print all available programs
        cfg = dummy_main_cfg(
            programs=dict(pydev=dummy_program_cfg(), pydev2=dummy_program_cfg())
        )
        with self.obj(cfg=cfg, args=Namespace()) as o:
            o.main()

            self.assertListEqual(self._output_list(o), ["pydev", "pydev2"])


class CmdAliasTest(SkeltonCmdTest):
    cls = CmdAlias

    def test_main(self) -> None:
        cfg = dummy_main_cfg(
            programs=dict(
                pydev=dummy_program_cfg(aliases=dict(sh="/bin/bash")),
                pydev2=dummy_program_cfg(),
            )
        )

        with self.obj(
            cfg=cfg, args=Namespace(expand=False), executor="sandbox-exec"
        ) as o:
            o.main()

            self.assertListEqual(
                self._output_list(o),
                [
                    'alias pydev="sandbox-exec run pydev"',
                    'alias pydev2="sandbox-exec run pydev2"',
                ],
            )

        with self.obj(
            cfg=cfg, args=Namespace(expand=True), executor="sandbox-exec"
        ) as o:
            o.main()

            self.assertListEqual(
                self._output_list(o),
                [
                    'alias pydev="sandbox-exec run pydev"',
                    'alias pydev-sh="sandbox-exec run pydev --sandbox-arg-exec=sh"',
                    'alias pydev2="sandbox-exec run pydev2"',
                ],
            )


class CmdRunTest(SkeltonCmdTest):
    cls = CmdRun

    @mock.patch("sandock.cli.SandboxExec")
    def test_main(self, sandbox_exec_mock: MagicMock) -> None:
        remote = MagicMock()
        sandbox_exec_mock.return_value = remote

        provided_args = ["--sandbox-arg-hostname=change_host", "--version"]
        with self.obj(
            args=Namespace(program="pydev", program_args=provided_args),
        ) as o:
            o.main()

            self.assertDictEqual(
                sandbox_exec_mock.call_args[1]["overrides"],
                dict(hostname="change_host", allow_home_dir=False),
            )
            remote.do.assert_called_once()
            self.assertListEqual(
                remote.do.call_args[1]["args"],
                ["--version"],
                msg="the forwarded argument to container's program",
            )

    def test_overrides_properties_kv(self) -> None:
        with self.obj(
            args=Namespace(program="pydev"),
        ) as o:
            result = o.override_properties(
                args=["--sandbox-arg-env=DEBUG=true", "--sandbox-arg-env=APP_ENV=dev"]
            )

            expected_env = dict(DEBUG="true", APP_ENV="dev")
            ov_props = dict(allow_home_dir=False, env=expected_env)
            self.assertDictEqual(result, ov_props)

        with self.obj(
            args=Namespace(program="pydev"),
        ) as o:

            # wrongly formatted key value provided
            with mock.patch("sys.exit") as sys_exit:
                result = o.override_properties(args=["--sandbox-arg-env=NOVALUE"])

                self.assertEqual(sys_exit.call_args.args[0], 2, msg="with exit code 2")

    @mock.patch("sys.exit")
    @mock.patch.object(ArgumentParser, "print_help")
    def test_overrides_properties_print_help(
        self, argparse_print_help: MagicMock, sys_exit: MagicMock
    ) -> None:
        # print help if provided with sandbox arg help arams
        with self.obj(
            args=Namespace(program="pydev"),
        ) as o:
            o.override_properties(args=["--sandbox-arg-help"])

            argparse_print_help.assert_called_once()
            sys_exit.assert_called_once_with(0)


class CmdVolumeTest(SkeltonCmdTest):
    cls = CmdVolume

    @contextmanager
    def obj_volmgr_backup(self, **kwargs) -> Iterator[Tuple[CmdVolume, MagicMock]]:
        # mock backup property on VolumeMgr, this only to shorten some repetitive
        with patch.object(
            VolumeMgr, "backup", new_callable=PropertyMock
        ) as mock_backup_prop:
            mock_backup_mgr = MagicMock()
            mock_backup_prop.return_value = mock_backup_mgr

            # not expecting there is a password prompt for backup password
            kwargs.setdefault("cfg", dummy_main_cfg(backup=dict(no_password=True)))

            with self.obj(**kwargs) as o:
                yield (o, mock_backup_mgr)

    @patch.object(VolumeMgr, "created_by_sandock", new_callable=PropertyMock)
    def test_volume_list(self, mock_create_by_sandock: PropertyMock) -> None:
        mock_create_by_sandock.return_value = [dict(Name="vol1"), dict(Name="vol2")]

        with self.obj(args=Namespace(volume_action="list")) as o:
            o.main()

            self.assertEqual(o.output.call_count, 2)
            self.assertListEqual(self._output_list(o), ["vol1", "vol2"])

    def test_backup_snapshot(self) -> None:
        args = Namespace(
            volume_action="backup", backup_action="snapshot", vol=None, all=False
        )

        with self.obj_volmgr_backup(args=args) as (o, mock_backup_mgr):
            dummy_backuptime = datetime.now()
            dummy_backuptime_format = dummy_backuptime.strftime("%Y-%m-%d %H:%M:%S")
            mock_backup_mgr.snapshot_list.return_value = [
                BackupSnapshot(
                    id="snap123",
                    backup_time=dummy_backuptime,
                    path="/source_vol_abc1",
                    bytes=72168670,
                ),
                BackupSnapshot(
                    id="snap124",
                    backup_time=dummy_backuptime,
                    path="/source_vol_abc2",
                    bytes=72168670,
                ),
            ]
            o.main()

            mock_backup_mgr.snapshot_list.assert_called_once_with(
                specific_volname=None, show_all=False
            )
            self.assertEqual(o.output.call_count, 2)
            self.assertListEqual(
                self._output_list(o),
                [
                    f"id: snap123 - date: {dummy_backuptime_format} (UTC) - size: 68.83 MB - vol: abc1",
                    f"id: snap124 - date: {dummy_backuptime_format} (UTC) - size: 68.83 MB - vol: abc2",
                ],
            )

    def test_backup_restored(self) -> None:
        args = Namespace(
            volume_action="backup",
            backup_action="restore",
            snapshot_id="123abc",
            vol="target_vol",
            force=True,
            exclude=["this", "that"],
            overwrite="always",
        )

        with self.obj_volmgr_backup(args=args) as (o, mock_backup_mgr):
            backup_snapshot = BackupSnapshot(
                id="123abc",
                backup_time=datetime.now(),
                bytes=1024 * 2,
                path="/source_vol_abc1",
            )
            mock_backup_mgr.get_snapshot_by.return_value = backup_snapshot
            o.main()

            mock_backup_mgr.get_snapshot_by.asert_called_once_with(
                id="123abc", must_exists=True
            )
            mock_backup_mgr.restore.asert_called_once_with(
                snapshot=backup_snapshot,
                target_volume="target_vol",
                force=True,
                excludes=["this", "that"],
                overwrite="always",
            )

    def test_backup_create_combined_targets(self) -> None:
        args = Namespace(
            volume_action="backup", target="target_vol", backup_action=None, all=True
        )

        with self.obj_volmgr_backup(args=args) as (o, mock_backup_mgr):
            with self.assertRaisesRegex(
                SandboxVolumeExec,
                "cannot combine specific target with all volume option",
            ):
                o.main()

            mock_backup_mgr.assert_not_called()

    def test_backup_create_no_targets(self) -> None:
        args = Namespace(
            volume_action="backup", backup_action=None, target=None, all=False
        )

        with self.obj_volmgr_backup(args=args) as (o, mock_backup_mgr):
            with self.assertRaisesRegex(
                SandboxVolumeExec, "you must set explicitly volume backup target"
            ):
                o.main()

            mock_backup_mgr.assert_not_called()

    @patch.object(VolumeMgr, "vol_exists")
    def test_backup_specific_volume(self, mock_vol_exist: MagicMock) -> None:
        args = Namespace(
            volume_action="backup",
            backup_action=None,
            exclude=None,
            target="vol1",
            all=False,
        )

        with self.obj_volmgr_backup(args=args) as (o, mock_backup_mgr):
            mock_vol_exist.return_value = False
            with self.assertRaisesRegex(
                SandboxVolumeExec, "volume by name `vol1` is not exists"
            ):
                o.main()

            mock_vol_exist.assert_called_once_with(name="vol1")
            mock_backup_mgr.assert_not_called()

        mock_vol_exist.reset_mock()
        with self.obj_volmgr_backup(args=args) as (o, mock_backup_mgr):
            mock_vol_exist.return_value = True
            o.main()

            mock_vol_exist.assert_called_once_with(name="vol1")
            mock_backup_mgr.create.assert_called_once_with(
                targets=["vol1"], excludes=[]
            )

    @patch.object(VolumeMgr, "volume_list")
    def test_backup_all_volume(self, mock_volume_list: MagicMock) -> None:
        args = Namespace(
            volume_action="backup",
            backup_action=None,
            exclude=None,
            target=None,
            all=True,
        )

        # no target label set
        mock_volume_list.reset_mock()
        with self.obj_volmgr_backup(args=args) as (o, mock_backup_mgr):
            with self.assertRaisesRegex(
                SandboxVolumeExec,
                "empty volume label filter for backup target, set it on .backup.volume.labels",
            ):
                o.main()

            mock_volume_list.assert_not_called()
            mock_backup_mgr.assert_not_called()

        cfg_backup_label = dummy_main_cfg(
            backup=dict(no_password=True, volume_labels={"backup.this": "true"})
        )
        with self.obj_volmgr_backup(args=args, cfg=cfg_backup_label) as (
            o,
            mock_backup_mgr,
        ):
            mock_volume_list.return_value = [
                dict(Name="vol1"),
                dict(Name="vol2"),
            ]
            o.main()

            mock_volume_list.assert_called_once()
            mock_backup_mgr.create.assert_called_once_with(
                targets=["vol1", "vol2"], excludes=[]
            )

        # no targets availabe
        mock_volume_list.reset_mock()
        with self.obj_volmgr_backup(args=args, cfg=cfg_backup_label) as (
            o,
            mock_backup_mgr,
        ):
            mock_volume_list.return_value = []
            o.main()

            mock_volume_list.assert_called_once()
            mock_backup_mgr.assert_not_called()

    def test_backup_restic(self) -> None:
        args = Namespace(
            volume_action="backup",
            backup_action="restic",
            restic_params=["list", "index"],
            extra_run_args="-v somevol:/mounthere:ro",
        )

        with self.obj_volmgr_backup(args=args) as (o, mock_backup_mgr):
            with mock_shell_exec() as msh:
                o.main()

                msh.assert_called_once()
                mock_backup_mgr.restic_run_cmd.assert_called_once_with(
                    extra_docker_params=["-v somevol:/mounthere:ro"],
                    restic_args=["list", "index"],
                )


class MainTest(unittest.TestCase):
    def test_subcommand_not_found(self) -> None:
        with self.assertRaises(SystemExit):
            cli_main(args=["subnotexists"])

    @mock.patch("sandock.cli.CmdList")
    def test_enable_debug(self, mock_cmd_list: MagicMock) -> None:
        cmd_list_remote = MagicMock()
        mock_cmd_list.return_value = cmd_list_remote

        with mock.patch.object(log, "setLevel") as log_set_level:
            cli_main(args=["--debug", "list"])

            log_set_level.assert_called_once_with(logging.DEBUG)
            cmd_list_remote.main.assert_called_once()

    @mock.patch("sys.exit")
    @mock.patch("sandock.cli.CmdList")
    def test_err_debug_enable_shell_exec(
        self, mock_cmd_list: MagicMock, sys_exit: MagicMock
    ) -> None:
        # if debug disabled, hide the verbosed exception and forward the error code
        cmd_list_remote = MagicMock()
        cmd_list_remote.main.side_effect = subprocess.CalledProcessError(
            returncode=2, stderr="error ocurred", cmd="error"
        )
        mock_cmd_list.return_value = cmd_list_remote

        cli_main(args=["list"])
        sys_exit.assert_called_once_with(2)

    @mock.patch("sys.exit")
    @mock.patch("sandock.cli.CmdList")
    def test_err_debug_enable_shell_exec(
        self, mock_cmd_list: MagicMock, sys_exit: MagicMock
    ) -> None:
        # if debug enabled, all of the shell error execution will be re raised
        cmd_list_remote = MagicMock()
        cmd_list_remote.main.side_effect = subprocess.CalledProcessError(
            returncode=2, stderr="error ocurred", cmd="error"
        )
        mock_cmd_list.return_value = cmd_list_remote

        with temp_enable_debug():
            with self.assertRaisesRegex(
                subprocess.CalledProcessError,
                "Command 'error' returned non-zero exit status 2",
            ):
                cli_main(args=["list"])

            sys_exit.assert_not_called()

    @mock.patch("sys.exit")
    @mock.patch("sandock.cli.CmdList")
    def test_err_known_exception(
        self, mock_cmd_list: MagicMock, sys_exit: MagicMock
    ) -> None:
        # if debug disabled, hide the verbosed of known exceptions
        cmd_list_remote = MagicMock()
        cmd_list_remote.main.side_effect = SandboxExecution("a known err")

        mock_cmd_list.return_value = cmd_list_remote

        cli_main(args=["list"])
        sys_exit.assert_called_once_with(1)

    @mock.patch("sys.exit")
    @mock.patch("sandock.cli.CmdList")
    def test_err_debug_known_exception(
        self, mock_cmd_list: MagicMock, sys_exit: MagicMock
    ) -> None:
        # if debug disabled, hide the verbosed of known exceptions
        cmd_list_remote = MagicMock()
        cmd_list_remote.main.side_effect = SandboxExecution("a known err")

        mock_cmd_list.return_value = cmd_list_remote

        with temp_enable_debug():
            with self.assertRaisesRegex(
                SandboxExecution,
                "a known err",
            ):
                cli_main(args=["list"])

            sys_exit.assert_not_called()


if __name__ == "__name__":
    unittest.main()
