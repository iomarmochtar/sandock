
from unittest import mock
from sandock.executors import AppleContainerExec
from sandock.exceptions import SandboxExecution
from test_sandbox import SandboxExecTest
from helpers import (
    dummy_main_cfg,
    mock_shell_exec
)

# majority of the behaviours are same
class AppleContainerExecTest(SandboxExecTest):
    default_executor: str = "container"
    exec_cls: object = AppleContainerExec


    def test_attach_container_status_start(self) -> None:

        with mock_shell_exec(
            side_effects=[
                dict(returncode=0, stdout='[{"status": "running"}]')
            ]
        ) as rs:  # inspect container
            o = self.obj(program_kwargs=dict(persist=dict(enable=True), name="pydev"))

            self.assertTrue(o.attach_container)
            self.assertEqual(rs.call_count, 1)
            self.assertEqual(
                rs.call_args_list[0].args[0],
                "container inspect pydev",
            )

    def test_attach_container_status_stop_auto_start(self) -> None:

        side_effects = [
            dict(
                returncode=0, stdout='[{"status": "stopped"}]'
            ),  # inspect container
            dict(returncode=0),  # start container
        ]
        with mock_shell_exec(side_effects=side_effects) as rs:
            o = self.obj(program_kwargs=dict(persist=dict(enable=True), name="pydev"))

            self.assertTrue(o.attach_container)
            self.assertEqual(rs.call_count, 2)
            self.assertEqual(
                rs.call_args_list[0].args[0],
                f"{self.default_executor} inspect pydev",
            )

            self.assertEqual(
                rs.call_args_list[1].args[0],
                f"{self.default_executor} start pydev",
            )

        # auto start disable
        with mock_shell_exec(
            side_effects=[
                dict(returncode=0, stdout='[{"status": "stopped"}]')
            ]
        ) as rs:  # inspect container
            o = self.obj(
                program_kwargs=dict(
                    persist=dict(enable=True, auto_start=False), name="pydev"
                )
            )

            self.assertFalse(o.attach_container)
            self.assertEqual(rs.call_count, 1)
            self.assertEqual(
                rs.call_args_list[0].args[0],
                f"{self.default_executor} inspect pydev",
            )

    def test_attach_container(self) -> None:
        with mock_shell_exec() as rs:
            o = self.obj()
            self.assertFalse(
                o.attach_container, msg="non persist program will not attach"
            )

            rs.assert_not_called()

        # apple's container return empty list json when container not exists
        with mock_shell_exec(
            side_effects=[dict(returncode=0, stdout="[]")]
        ) as rs:
            o = self.obj(program_kwargs=dict(persist=dict(enable=True), name="pydev"))

            self.assertFalse(
                o.attach_container, msg="non persist program will not attach"
            )

            self.assertEqual(rs.call_count, 1)
            self.assertEqual(
                rs.call_args_list[0].args[0],
                f"{self.default_executor} inspect pydev",
            )

        with mock_shell_exec(
            side_effects=[dict(returncode=1, stderr="unexpected error")]
        ) as rs:
            o = self.obj(program_kwargs=dict(persist=dict(enable=True), name="pydev"))

            with self.assertRaisesRegex(
                SandboxExecution,
                "error during check container status: unexpected error",
            ):
                o.attach_container

    def test_attach_container_empy_info(self) -> None:

        with mock_shell_exec(
            side_effects=[dict(returncode=0, stdout="[]")]
        ) as rs:  # inspect container
            o = self.obj(program_kwargs=dict(persist=dict(enable=True), name="pydev"))

            self.assertFalse(o.attach_container)
            self.assertEqual(rs.call_count, 1)
            self.assertEqual(
                rs.call_args_list[0].args[0],
                f"{self.default_executor} inspect pydev",
            )

    def test_run_container_cmd_extended(self) -> None:
        cfg = dummy_main_cfg(
            program_kwargs=dict(
                name="mypydev",
                persist=dict(enable=True),
                platform="linux/amd64",
                hostname="imah",
                executor="apple_container",
                network="host",
                user=dict(keep_id=True),
                aliases=dict(sh="/bin/bash"),
                sandbox_mount=dict(read_only=True),
                volumes=[
                    "output_${VOL_DIR}:/output",
                    "~/share_to_container:/shared:ro",
                ],
                env=dict(PYTHON_PATH="/shared"),
                extra_run_args=["--env-file=~/common_container_envs"],
            ),
            execution=dict(docker_bin="podman"),
        )

        with mock.patch.multiple(
            AppleContainerExec,
            current_dir="/path/to/repo",
            home_dir="/home/dir",
            current_uid=1000,
            current_gid=1000,
        ):
            o = self.obj(cfg=cfg)

            self.assertListEqual(
                o.run_container_cmd(),
                [
                    "container",
                    "run",
                    "--entrypoint",
                    "python3",
                    "--name",
                    "mypydev",
                    "-it",
                    "--platform",
                    "linux/amd64",
                    "--network",
                    "host",
                    "-u",
                    "1000:1000",
                    "-v",
                    "output_path_to_repo:/output",
                    "-v",
                    "~/share_to_container:/shared:ro",
                    "-v",
                    "/path/to/repo:/sandbox:ro",
                    "--workdir",
                    "/sandbox",
                    "-e PYTHON_PATH='/shared'",
                    "--env-file=~/common_container_envs",
                    "python:3.11",
                ],
            )

    def test_run_container_cmd_set_executor(self) -> None:
        """
        skipped: no way to custom the binary path/name 
        """

    def test_docker_bin_executor_not_defined(self) -> None:
        """
        skipped: the bin_path is hard coded on the defined class
        """