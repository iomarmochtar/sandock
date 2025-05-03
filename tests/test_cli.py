import unittest
import subprocess
import logging
import os
import sys
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
from typing import Iterator, List
from sandock.config import MainConfig, CONFIG_PATH_ENV
from sandock.shared import log
from sandock.exceptions import (
    SandboxExecution,
    SandboxBaseException,
    SandboxExecConfig,
)
from sandock.cli import (
    BaseCommand,
    CmdList,
    CmdAlias,
    CmdRun,
    main as cli_main,
    SANDBOX_DEBUG_ENV,
)


class SkeltonCmdTest(BaseTestCase):
    cls: BaseCommand

    def _output_list(self, o: BaseCommand) -> List[str]:
        return [x[0][0] for x in o.output.call_args_list]

    @contextmanager
    def obj(self, cfg: MainConfig, args: Namespace, **kwargs) -> Iterator[BaseCommand]:
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
        with self.obj(
            cfg=dummy_main_cfg(), args=Namespace(config="/path/to/config")
        ) as o:
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
    def test_main(self, sandbox_exec_mock: mock.MagicMock) -> None:
        remote = mock.MagicMock()
        sandbox_exec_mock.return_value = remote

        provided_args = ["--sandbox-arg-hostname=change_host", "--version"]
        with self.obj(
            cfg=dummy_main_cfg(),
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
            cfg=dummy_main_cfg(),
            args=Namespace(program="pydev"),
        ) as o:
            result = o.override_properties(
                args=["--sandbox-arg-env=DEBUG=true", "--sandbox-arg-env=APP_ENV=dev"]
            )

            expected_env = dict(DEBUG="true", APP_ENV="dev")
            ov_props = dict(allow_home_dir=False, env=expected_env)
            self.assertDictEqual(result, ov_props)

        with self.obj(
            cfg=dummy_main_cfg(),
            args=Namespace(program="pydev"),
        ) as o:

            # wrongly formatted key value provided
            with mock.patch("sys.exit") as sys_exit:
                result = o.override_properties(args=["--sandbox-arg-env=NOVALUE"])

                self.assertEqual(sys_exit.call_args.args[0], 2, msg="with exit code 2")

    @mock.patch("sys.exit")
    @mock.patch.object(ArgumentParser, "print_help")
    def test_overrides_properties_print_help(
        self, argparse_print_help: mock.MagicMock, sys_exit: mock.MagicMock
    ) -> None:
        # print help if provided with sandbox arg help arams
        with self.obj(
            cfg=dummy_main_cfg(),
            args=Namespace(program="pydev"),
        ) as o:
            o.override_properties(args=["--sandbox-arg-help"])

            argparse_print_help.assert_called_once()
            sys_exit.assert_called_once_with(0)

    @mock.patch("sys.exit")
    @mock.patch("sandock.cli.SandboxExec")
    def test_main_shell_err(
        self, sandbox_exec_mock: mock.MagicMock, sys_exit: mock.MagicMock
    ) -> None:
        remote = mock.MagicMock()
        sandbox_exec_mock.return_value = remote

        with self.obj(
            cfg=dummy_main_cfg(),
            args=Namespace(program="pydev", program_args=[]),
        ) as o:
            remote.do.side_effect = subprocess.CalledProcessError(
                returncode=2, stderr="error ocurred", cmd="error"
            )
            o.main()

            sys_exit.assert_called_once_with(2)

    @mock.patch("sys.exit")
    @mock.patch("sandock.cli.SandboxExec")
    def test_main_shell_err_debug_enable(
        self, sandbox_exec_mock: mock.MagicMock, sys_exit: mock.MagicMock
    ) -> None:
        # reraise the error if debug mode enabled
        remote = mock.MagicMock()
        sandbox_exec_mock.return_value = remote

        with self.obj(
            cfg=dummy_main_cfg(),
            args=Namespace(program="pydev", program_args=[]),
        ) as o:
            remote.do.side_effect = subprocess.CalledProcessError(
                returncode=2, stderr="error ocurred", cmd="error"
            )
            with temp_enable_debug():
                with self.assertRaisesRegex(
                    subprocess.CalledProcessError,
                    "Command 'error' returned non-zero exit status 2",
                ):
                    o.main()

                sys_exit.assert_not_called()

    @mock.patch("sys.exit")
    @mock.patch("sandock.cli.SandboxExec")
    def test_main_captured_err(
        self, sandbox_exec_mock: mock.MagicMock, sys_exit: mock.MagicMock
    ) -> None:
        remote = mock.MagicMock()
        sandbox_exec_mock.return_value = remote

        with self.obj(
            cfg=dummy_main_cfg(),
            args=Namespace(program="pydev", program_args=[]),
        ) as o:
            remote.do.side_effect = SandboxExecution("raised exception")
            o.main()

            sys_exit.assert_called_once_with(1)

    @mock.patch("sys.exit")
    @mock.patch("sandock.cli.SandboxExec")
    def test_main_captured_err_debug_enable(
        self, sandbox_exec_mock: mock.MagicMock, sys_exit: mock.MagicMock
    ) -> None:
        # reraise the error if debug mode enabled once error occured
        remote = mock.MagicMock()
        sandbox_exec_mock.return_value = remote

        with self.obj(
            cfg=dummy_main_cfg(),
            args=Namespace(program="pydev", program_args=[]),
        ) as o:
            remote.do.side_effect = SandboxExecution("raised exception")
            with temp_enable_debug():
                with self.assertRaisesRegex(SandboxBaseException, "raised exception"):
                    o.main()

                    sys_exit.assert_called_once_with(1)


class MainTest(unittest.TestCase):
    def test_subcommand_not_found(self) -> None:
        with self.assertRaises(SystemExit):
            cli_main(args=["subnotexists"])

    @mock.patch("sandock.cli.CmdList")
    def test_enable_debug(self, mock_cmd_list: mock.MagicMock) -> None:
        cmd_list_remote = mock.MagicMock()
        mock_cmd_list.return_value = cmd_list_remote

        with mock.patch.object(log, "setLevel") as log_set_level:
            cli_main(args=["--debug", "list"])

            log_set_level.assert_called_once_with(logging.DEBUG)
            cmd_list_remote.main.assert_called_once()


if __name__ == "__name__":
    unittest.main()
