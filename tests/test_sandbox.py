import unittest
import os
import tempfile
import subprocess
from inspect import cleandoc
from subprocess import CompletedProcess
from unittest import mock
from sandock.exceptions import SandboxExecution
from sandock.sandbox import SandboxExec
from helpers import dummy_main_cfg, BaseTestCase


class SandboxExecTest(BaseTestCase):
    def obj(self, program_kwargs: dict = {}, **kwargs) -> SandboxExec:
        """
        automatically inject default values
        """
        kwargs = (
            dict(name="pydev", cfg=dummy_main_cfg(program_kwargs=program_kwargs))
            | kwargs
        )

        return SandboxExec(**kwargs)

    def test_init_validations(self) -> None:
        with self.assertRaisesRegex(SandboxExecution, "`ruby33` is not defined"):
            self.obj(name="ruby33")

        with self.assertRaisesRegex(
            SandboxExecution, "name of persist program cannot be overrided"
        ):
            self.obj(
                cfg=dummy_main_cfg(program_kwargs=dict(persist=dict(enable=True))),
                overrides=dict(name="pydev_ov"),
            )

        with self.assertRaisesRegex(
            SandboxExecution,
            "cannot be ran on top of home directory when the program's sandbox mount is enabled",
        ):
            # the default configuration is enable sandbox mount and disallow home directory
            with mock.patch.multiple(
                SandboxExec, current_dir="/home/dir", home_dir="/home/dir"
            ):
                self.obj()

    def test_init_overrides(self) -> None:
        o = self.obj(
            overrides=dict(exec="/bin/bash", no_prop="not_found", name="conda")
        )

        self.assertEqual(o.program.exec, "/bin/bash")
        self.assertEqual(o.program.name, "conda")

    def test_generate_container_name(self) -> None:
        with mock.patch.object(SandboxExec, "current_timestamp", "123.456"):
            self.assertEqual(
                self.obj().generate_container_name(), "sandock-pydev-123.456"
            )

        self.assertEqual(
            self.obj(program_kwargs=dict(name="mysh")).generate_container_name(),
            "mysh",
            msg="set in configuration, will not change",
        )

    def test_exec_path(self) -> None:
        o = self.obj(program_kwargs=dict(aliases=dict(sh="/bin/bash"), exec="sh"))
        self.assertEqual(
            o.exec_path,
            "/bin/bash",
            msg="path of executeable will lookup first to the aliases",
        )

        o = self.obj(program_kwargs=dict(aliases=dict(sh="/bin/bash"), exec="irb"))
        self.assertEqual(
            o.exec_path, "irb", msg="not exists in aliases, returning as is"
        )

    def test_run_container_cmd_defaults(self) -> None:
        """
        with some config defaults
        """

        with mock.patch.multiple(
            SandboxExec,
            current_dir="/path/to/repo",
            home_dir="/home/dir",
            current_timestamp="123.456",
        ):
            o = self.obj()

            self.assertListEqual(
                o.run_container_cmd(),
                [
                    "docker",
                    "run",
                    "--entrypoint",
                    "python3",
                    "--name",
                    "sandock-pydev-123.456",
                    "--rm",
                    "-it",
                    "-v",
                    "/path/to/repo:/sandbox",
                    "--workdir",
                    "/sandbox",
                    "python:3.11",
                ],
            )

    def test_run_container_cmd_extended(self) -> None:
        cfg = dummy_main_cfg(
            program_kwargs=dict(
                name="mypydev",
                persist=dict(enable=True),
                platform="linux/amd64",
                hostname="imah",
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
            SandboxExec,
            current_dir="/path/to/repo",
            home_dir="/home/dir",
            current_uid=1000,
            current_gid=1000,
        ):
            o = self.obj(cfg=cfg, overrides=dict(exec="sh"))

            self.assertListEqual(
                o.run_container_cmd(),
                [
                    "podman",
                    "run",
                    "--entrypoint",
                    "/bin/bash",
                    "--name",
                    "mypydev",
                    "-it",
                    "--platform",
                    "linux/amd64",
                    "--hostname",
                    "imah",
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

    def test_ensure_volume_unmanaged(self) -> None:
        with mock.patch.object(subprocess, "run") as rs:
            """
            if not defined on volumes configuration then just skip it
            """
            o = self.obj()
            o.ensure_volume(name="dynamic_vol")
            rs.assert_not_called()

    def test_ensure_volume_exists(self) -> None:
        """
        volume already exists
        """
        cfg = dummy_main_cfg(
            volumes=dict(myhome=dict()),
        )

        with mock.patch.object(subprocess, "run") as rs:
            rs.side_effect = [
                CompletedProcess(returncode=0, args=[], stdout='[{"Name": "myhome"}]'),
            ]
            o = self.obj(cfg=cfg)
            o.ensure_volume(name="myhome")

            rs.assert_called()
            self.assertEqual(rs.call_count, 1)
            self.assertEqual(
                rs.call_args_list[0].args[0], "docker volume inspect myhome"
            )

    def test_ensure_volume_auto_create(self) -> None:
        """
        mentioned but it's not exist, then auto create it
        """
        cfg = dummy_main_cfg(
            volumes=dict(myhome=dict(labels={"backup.container.mochtar.net": "true"})),
        )

        with mock.patch.object(subprocess, "run") as rs:
            rs.side_effect = [
                CompletedProcess(returncode=1, args=[]),  # inspect but no volume found
                CompletedProcess(returncode=0, args=[]),
            ]
            o = self.obj(cfg=cfg)
            o.ensure_volume(name="myhome")

            rs.assert_called()
            self.assertEqual(rs.call_count, 2)
            self.assertEqual(
                rs.call_args_list[0].args[0], "docker volume inspect myhome"
            )
            self.assertEqual(
                rs.call_args_list[1].args[0],
                "docker volume create --driver=local  --label backup.container.mochtar.net='true' --label created_by.sandock='true' myhome",
            )

    def test_ensure_network_unmanaged(self) -> None:
        """
        if not using the custom network not shell command executed
        """
        with mock.patch.object(subprocess, "run") as rs:
            o = self.obj()
            o.ensure_network()
            rs.assert_not_called()

        with mock.patch.object(subprocess, "run") as rs:
            cfg = dummy_main_cfg(
                networks=dict(another_mynet=dict()),
                program_kwargs=dict(network="mynet"),
            )
            o = self.obj(cfg=cfg)
            o.ensure_network()
            rs.assert_not_called()

    def test_ensure_network_exists(self) -> None:
        """
        network already exists
        """

        cfg = dummy_main_cfg(
            networks=dict(mynet=dict()), program_kwargs=dict(network="mynet")
        )

        with mock.patch.object(subprocess, "run") as rs:
            rs.side_effect = [
                CompletedProcess(returncode=0, args=[], stdout='[{"Name": "mynet"}]'),
            ]
            o = self.obj(cfg=cfg)
            o.ensure_network()

            rs.assert_called()
            self.assertEqual(rs.call_count, 1)
            self.assertEqual(
                rs.call_args_list[0].args[0], "docker network inspect mynet"
            )

    def test_ensure_network_auto_create(self) -> None:
        """
        mentioned but it's not exist, then auto create it
        """
        cfg = dummy_main_cfg(
            networks=dict(mynet=dict()), program_kwargs=dict(network="mynet")
        )

        with mock.patch.object(subprocess, "run") as rs:
            rs.side_effect = [
                CompletedProcess(returncode=1, args=[]),  # inspect but no network found
                CompletedProcess(returncode=0, args=[]),
            ]
            o = self.obj(cfg=cfg)
            o.ensure_network()

            rs.assert_called()
            self.assertEqual(rs.call_count, 2)
            self.assertEqual(
                rs.call_args_list[0].args[0], "docker network inspect mynet"
            )
            self.assertEqual(
                rs.call_args_list[1].args[0],
                "docker network create --driver=bridge  mynet",
            )

    def test_ensure_custom_image_not_defined(self) -> None:
        with mock.patch.object(subprocess, "run") as rs:
            o = self.obj()
            o.ensure_custom_image()
            rs.assert_not_called()

    def test_ensure_custom_image_exists(self) -> None:
        cfg = dummy_main_cfg(
            images=dict(custom_pydev=dict(dockerfile_inline="FROM python:3.11")),
            program_kwargs=dict(image="custom_pydev"),
        )

        with mock.patch.object(subprocess, "run") as rs:
            rs.side_effect = [
                CompletedProcess(
                    returncode=0, args=[], stdout='[{"Name": "custom_pydev"}]'
                ),
            ]
            o = self.obj(cfg=cfg)
            o.ensure_custom_image()

            rs.assert_called()
            self.assertEqual(rs.call_count, 1)
            self.assertEqual(
                rs.call_args_list[0].args[0], "docker image inspect custom_pydev"
            )

    def test_ensure_custom_image_auto_create(self) -> None:
        """
        create the image if not exists, recursively create another image that depends on it
        """
        dockerfile_inline = cleandoc(
            """
            FROM python:3.11
            ARG USER=user1
            
            USER $USER
            """
        )
        cfg = dummy_main_cfg(
            images=dict(
                custom_pydev_base=dict(
                    dockerfile_inline=dockerfile_inline,
                    args=dict(USER="another"),
                ),
                custom_pydev=dict(
                    depends_on="custom_pydev_base",
                    dockerfile_inline="FROM custom_pydev_base",
                    extra_build_args=["--progress=quite"],
                ),
            ),
            program_kwargs=dict(image="custom_pydev", platform="linux/amd64"),
        )

        with mock.patch.object(subprocess, "run") as rs:
            rs.side_effect = [
                CompletedProcess(
                    returncode=1, args=[]
                ),  # docker image inspect for custom_pydev_base
                CompletedProcess(
                    returncode=0, args=[]
                ),  # docker image build custom_pydev_base
                CompletedProcess(
                    returncode=1, args=[]
                ),  # docker image inspect for custom_pydev
                CompletedProcess(
                    returncode=0, args=[]
                ),  # docker image build for custom_pydev
            ]
            o = self.obj(cfg=cfg)

            with tempfile.TemporaryDirectory() as td:
                docker_file_temp = os.path.join(td, "dockerfile")
                with mock.patch.multiple(
                    tempfile,
                    mkdtemp=mock.Mock(return_value="/tmp/dst"),
                    mktemp=mock.Mock(return_value=docker_file_temp),
                ):
                    o.ensure_custom_image()

                    rs.assert_called()
                    self.assertEqual(rs.call_count, 4)
                    self.assertEqual(
                        rs.call_args_list[0].args[0],
                        "docker image inspect custom_pydev_base",
                    )
                    self.assertEqual(
                        rs.call_args_list[1].args[0],
                        f'docker build -t custom_pydev_base -f {docker_file_temp} --build-arg USER="another" --platform=linux/amd64 /tmp/dst',
                    )
                    self.assertEqual(
                        rs.call_args_list[2].args[0],
                        "docker image inspect custom_pydev",
                    )
                    self.assertEqual(
                        rs.call_args_list[3].args[0],
                        f"docker build -t custom_pydev -f {docker_file_temp} --progress=quite --platform=linux/amd64 /tmp/dst",
                    )

    def test_attach_container(self) -> None:
        with mock.patch.object(subprocess, "run") as rs:
            o = self.obj()
            self.assertFalse(
                o.attach_container, msg="non persist program will not attach"
            )

            rs.assert_not_called()

        with mock.patch.object(subprocess, "run") as rs:
            rs.side_effect = [
                CompletedProcess(
                    returncode=1, args=[], stderr="Error: No such container: pydev"
                ),
            ]

            o = self.obj(program_kwargs=dict(persist=dict(enable=True), name="pydev"))

            self.assertFalse(
                o.attach_container, msg="non persist program will not attach"
            )

            self.assertEqual(rs.call_count, 1)
            self.assertEqual(
                rs.call_args_list[0].args[0],
                "docker container inspect pydev",
            )

        with mock.patch.object(subprocess, "run") as rs:
            rs.side_effect = [
                CompletedProcess(returncode=1, args=[], stderr="unexpected error"),
            ]

            o = self.obj(program_kwargs=dict(persist=dict(enable=True), name="pydev"))

            with self.assertRaisesRegex(
                SandboxExecution,
                "error during check container status: unexpected error",
            ):
                o.attach_container

    def test_attach_container_empy_info(self) -> None:

        with mock.patch.object(subprocess, "run") as rs:
            rs.side_effect = [
                CompletedProcess(
                    returncode=0, args=[], stdout="[]"
                ),  # inspect container
            ]

            o = self.obj(program_kwargs=dict(persist=dict(enable=True), name="pydev"))

            self.assertFalse(o.attach_container)
            self.assertEqual(rs.call_count, 1)
            self.assertEqual(
                rs.call_args_list[0].args[0],
                "docker container inspect pydev",
            )

    def test_attach_container_status_stop_auto_start(self) -> None:

        with mock.patch.object(subprocess, "run") as rs:
            rs.side_effect = [
                CompletedProcess(
                    returncode=0, args=[], stdout='[{"State": {"Status": "exited"}}]'
                ),  # inspect container
                CompletedProcess(returncode=0, args=[]),  # start the container
            ]

            o = self.obj(program_kwargs=dict(persist=dict(enable=True), name="pydev"))

            self.assertTrue(o.attach_container)
            self.assertEqual(rs.call_count, 2)
            self.assertEqual(
                rs.call_args_list[0].args[0],
                "docker container inspect pydev",
            )

            self.assertEqual(
                rs.call_args_list[1].args[0],
                "docker container start pydev",
            )

        # auto start disable
        with mock.patch.object(subprocess, "run") as rs:
            rs.side_effect = [
                CompletedProcess(
                    returncode=0, args=[], stdout='[{"State": {"Status": "exited"}}]'
                ),  # inspect container
            ]

            o = self.obj(
                program_kwargs=dict(
                    persist=dict(enable=True, auto_start=False), name="pydev"
                )
            )

            self.assertFalse(o.attach_container)
            self.assertEqual(rs.call_count, 1)
            self.assertEqual(
                rs.call_args_list[0].args[0],
                "docker container inspect pydev",
            )

    def test_attach_container_status_start(self) -> None:

        with mock.patch.object(subprocess, "run") as rs:
            rs.side_effect = [
                CompletedProcess(
                    returncode=0, args=[], stdout='[{"State": {"Status": "running"}}]'
                ),  # inspect container
            ]

            o = self.obj(program_kwargs=dict(persist=dict(enable=True), name="pydev"))

            self.assertTrue(o.attach_container)
            self.assertEqual(rs.call_count, 1)
            self.assertEqual(
                rs.call_args_list[0].args[0],
                "docker container inspect pydev",
            )

    def test_exec_container_cmd(self) -> None:
        self.assertListEqual(
            self.obj(program_kwargs=dict(name="pydev")).exec_container_cmd(),
            ["docker", "exec", "-it", "pydev", "python3"],
        )

    def test_do_docker_run(self) -> None:

        with mock.patch.object(subprocess, "run") as rs:
            cfg = dummy_main_cfg(
                program_kwargs=dict(
                    pre_exec_cmds=["whoami", "cd /tmp"],
                    volumes=["namevol:/mnt:ro", "cache_${VOL_DIR}:/cache"],
                )
            )
            rs.side_effect = [
                CompletedProcess(returncode=0, args=[]),  # pre cmd 1
                CompletedProcess(returncode=0, args=[]),  # pre cmd 2
                CompletedProcess(returncode=0, args=[]),  # docker run
            ]

            # mocks methods and properties
            with mock.patch.multiple(
                SandboxExec,
                current_timestamp="123.456",
                current_dir="/path/to/repo",
                attach_container=False,
                ensure_custom_image=mock.MagicMock(),
                ensure_network=mock.MagicMock(),
                ensure_volume=mock.MagicMock(),
                exec_container_cmd=mock.MagicMock(),
                run_container_cmd=mock.MagicMock(
                    return_value=["docker", "run", "bla", "bla"]
                ),
            ):

                o = self.obj(cfg=cfg)
                o.do(args=["--version"])

                self.assertEqual(o.ensure_custom_image.call_count, 1)
                self.assertEqual(o.ensure_network.call_count, 1)
                self.assertEqual(o.ensure_volume.call_count, 2)
                self.assertEqual(o.exec_container_cmd.call_count, 0)

                # only for the shell command under "do" methods
                rs.assert_called()
                self.assertEqual(rs.call_count, 3)
                self.assertEqual(rs.call_args_list[0].args[0], "whoami")
                self.assertEqual(rs.call_args_list[1].args[0], "cd /tmp")
                self.assertEqual(
                    rs.call_args_list[2].args[0],
                    "docker run bla bla --version",
                )

    def test_do_docker_exec(self) -> None:

        with mock.patch.object(subprocess, "run") as rs:
            cfg = dummy_main_cfg(
                program_kwargs=dict(
                    name="pydev",
                    pre_exec_cmds=["whoami", "cd /tmp"],
                    volumes=["namevol:/mnt:ro", "cache_${VOL_DIR}:/cache"],
                )
            )
            rs.side_effect = [
                CompletedProcess(returncode=0, args=[]),  # pre cmd 1
                CompletedProcess(returncode=0, args=[]),  # pre cmd 2
                CompletedProcess(returncode=0, args=[]),  # docker exec
            ]

            # mocks methods and properties
            with mock.patch.multiple(
                SandboxExec,
                current_dir="/path/to/repo",
                attach_container=True,
                ensure_custom_image=mock.MagicMock(),
                ensure_network=mock.MagicMock(),
                ensure_volume=mock.MagicMock(),
                exec_container_cmd=mock.MagicMock(
                    return_value=["docker", "exec", "bla", "bla"]
                ),
                run_container_cmd=mock.MagicMock(),
            ):

                o = self.obj(cfg=cfg)
                o.do(args=["--version"])

                self.assertEqual(o.ensure_custom_image.call_count, 1)
                self.assertEqual(o.ensure_network.call_count, 1)
                self.assertEqual(o.ensure_volume.call_count, 2)
                self.assertEqual(o.run_container_cmd.call_count, 0)

                # only for the shell command under "do" methods
                rs.assert_called()
                self.assertEqual(rs.call_count, 3)
                self.assertEqual(rs.call_args_list[0].args[0], "whoami")
                self.assertEqual(rs.call_args_list[1].args[0], "cd /tmp")
                self.assertEqual(
                    rs.call_args_list[2].args[0],
                    "docker exec bla bla --version",
                )


if __name__ == "__main__":
    unittest.main()
