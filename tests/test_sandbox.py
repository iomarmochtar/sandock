import unittest
import os
import tempfile
from inspect import cleandoc
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock
from sandock.exceptions import SandboxExecution
from sandock.sandbox import SandboxExec
from sandock.config import MainConfig
from helpers import (
    dummy_main_cfg,
    mock_shell_exec,
    extract_first_call_arg_list,
    BaseTestCase,
)


def sample_cfg_program_dependent_images() -> MainConfig:
    dockerfile_inline = cleandoc(
        """
        FROM python:3.11
        ARG USER=user1
        
        USER $USER
        """
    )

    return dummy_main_cfg(
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
        with mock_shell_exec() as rs:
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

        with mock_shell_exec(
            side_effects=[dict(returncode=0, stdout='[{"Name": "myhome"}]')]
        ) as rs:
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

        side_effects = [
            dict(returncode=1),  # inspect but no volume found
            dict(returncode=0),
        ]
        with mock_shell_exec(side_effects=side_effects) as rs:
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
        with mock_shell_exec() as rs:
            o = self.obj()
            o.ensure_network()
            rs.assert_not_called()

        with mock_shell_exec() as rs:
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

        with mock_shell_exec(
            side_effects=[dict(returncode=0, stdout='[{"Name": "mynet"}]')]
        ) as rs:
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

        side_effects = [
            dict(returncode=1),  # inspect but no network found
            dict(returncode=0),
        ]
        with mock_shell_exec(side_effects=side_effects) as rs:
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
        with mock_shell_exec() as rs:
            o = self.obj()
            o.ensure_custom_image()
            rs.assert_not_called()

    def test_ensure_custom_image_exists(self) -> None:
        cfg = dummy_main_cfg(
            images=dict(custom_pydev=dict(dockerfile_inline="FROM python:3.11")),
            program_kwargs=dict(image="custom_pydev"),
        )

        with mock_shell_exec(
            side_effects=[dict(returncode=0, stdout='[{"Name": "custom_pydev"}]')]
        ) as rs:
            o = self.obj(cfg=cfg)
            o.ensure_custom_image()

            rs.assert_called()
            self.assertEqual(rs.call_count, 1)
            self.assertEqual(
                rs.call_args_list[0].args[0], "docker image inspect custom_pydev"
            )

    @mock.patch.dict(os.environ, dict(HOME="/home/user1"))
    @mock.patch.object(SandboxExec, "custom_image_dockerfile_store")
    def test_ensure_custom_image_escape_homedir(
        self, dockerfile_store: MagicMock
    ) -> None:
        """
        escape home dir alias for dockerFile and context
        """
        cfg = dummy_main_cfg(
            program_kwargs=dict(
                image="pydev:base",
                build=dict(
                    dockerFile="${HOME}/path/to/Dockerfile", context="${HOME}/path/to"
                ),
            )
        )
        shell_mock_side_effects = [
            dict(returncode=1),  # docker image inspect for pydev:base
            dict(returncode=0),  # docker image build for pydev:base
        ]
        with mock_shell_exec(side_effects=shell_mock_side_effects) as rs:
            o = self.obj(cfg=cfg)
            o.ensure_custom_image()

            self.assertListEqual(
                extract_first_call_arg_list(m=rs),
                [
                    "docker image inspect pydev:base",
                    "docker build -t pydev:base -f /home/user1/path/to/Dockerfile /home/user1/path/to",
                ],
            )

    def test_ensure_custom_image_auto_create(self) -> None:
        """
        create the image if not exists, recursively create another image that depends on it
        """
        shell_mock_side_effects = [
            dict(returncode=1),  # docker image inspect for custom_pydev_base
            dict(returncode=0),  # docker image build custom_pydev_base
            dict(returncode=1),  # docker image inspect for custom_pydev
            dict(returncode=0),  # docker image build for custom_pydev
        ]
        with mock_shell_exec(side_effects=shell_mock_side_effects) as rs:
            o = self.obj(cfg=sample_cfg_program_dependent_images())

            with tempfile.TemporaryDirectory() as td:
                docker_file_temp = os.path.join(td, "dockerfile")
                with mock.patch.multiple(
                    tempfile,
                    mkdtemp=mock.Mock(return_value="/tmp/dst"),
                    mktemp=mock.Mock(return_value=docker_file_temp),
                ):
                    o.ensure_custom_image()

                    self.assertListEqual(
                        extract_first_call_arg_list(m=rs),
                        [
                            "docker image inspect custom_pydev_base",
                            f'docker build -t custom_pydev_base -f {docker_file_temp} --build-arg USER="another" --platform=linux/amd64 /tmp/dst',
                            "docker image inspect custom_pydev",
                            f"docker build -t custom_pydev -f {docker_file_temp} --progress=quite --platform=linux/amd64 /tmp/dst",
                        ],
                    )

    @mock.patch.object(SandboxExec, "custom_image_dockerfile_store")
    def test_ensure_custom_image_auto_create_dumped_exists(
        self, dockerfile_store: MagicMock
    ) -> None:
        """
        load the dumped path if it's enabled before create the custom image
        """
        cfg = dummy_main_cfg(
            program_kwargs=dict(
                platform="linux/amd64",
                image="pydev:base",
                build=dict(dockerfile_inline="FROM python:3.9", dump=dict(enable=True)),
            )
        )
        dockerfile_store.return_value = MagicMock(
            exists=MagicMock(return_value=True),
            __str__=MagicMock(return_value="/path/to/dumped/image.tar"),
        )
        shell_mock_side_effects = [
            dict(returncode=1),  # docker image inspect for pydev:base
            dict(returncode=0),  # docker image load -i topath.tar
        ]
        with mock_shell_exec(side_effects=shell_mock_side_effects) as rs:
            o = self.obj(cfg=cfg)

            with tempfile.TemporaryDirectory() as td:
                docker_file_temp = os.path.join(td, "dockerfile")
                with mock.patch.multiple(
                    tempfile,
                    mkdtemp=mock.Mock(return_value="/tmp/dst"),
                    mktemp=mock.Mock(return_value=docker_file_temp),
                ):
                    o.ensure_custom_image()

                    self.assertListEqual(
                        extract_first_call_arg_list(m=rs),
                        [
                            "docker image inspect pydev:base",
                            "docker image load -i /path/to/dumped/image.tar",
                        ],
                    )

    @mock.patch.object(SandboxExec, "custom_image_dockerfile_store")
    def test_ensure_custom_image_auto_create_dumped_not_exists(
        self, dockerfile_store: MagicMock
    ) -> None:
        """
        dumped enabled, but not found, after custom image created then it will create one
        """
        cfg = dummy_main_cfg(
            program_kwargs=dict(
                platform="linux/amd64",
                image="pydev:base",
                build=dict(dockerfile_inline="FROM python:3.9", dump=dict(enable=True)),
            )
        )
        mock_prev_stored_img = MagicMock()
        parent_stored = MagicMock(
            exists=MagicMock(return_value=True),
            glob=MagicMock(return_value=[mock_prev_stored_img]),
        )
        store_path_mock = MagicMock(
            exists=MagicMock(return_value=False),
            __str__=MagicMock(return_value="/path/to/dumped/image.tar"),
        )
        store_path_mock.parent = parent_stored
        dockerfile_store.return_value = store_path_mock

        shell_mock_side_effects = [
            dict(returncode=1),  # docker image inspect for pydev:base
            dict(returncode=0),  # docker build pydev:base
            dict(returncode=0),  # docker image pydev:base --output target.tar
        ]

        # conducting 2 scenarios: delete previous dumped image and vice versa
        with tempfile.TemporaryDirectory() as td:
            docker_file_temp = os.path.join(td, "dockerfile")
            with mock.patch.multiple(
                tempfile,
                mkdtemp=mock.Mock(return_value="/tmp/dst"),
                mktemp=mock.Mock(return_value=docker_file_temp),
            ):
                expected_executed_shell_cmds = [
                    "docker image inspect pydev:base",
                    f"docker build -t pydev:base -f {docker_file_temp} --platform=linux/amd64 /tmp/dst",
                    "docker image save pydev:base --output /path/to/dumped/image.tar",
                ]

                # scenario: use the same file pattern
                with mock_shell_exec(side_effects=shell_mock_side_effects) as rs:
                    o = self.obj(cfg=cfg)
                    o.ensure_custom_image()

                    parent_stored.glob.assert_called_once_with("pydev:base*.tar")
                    mock_prev_stored_img.unlink.assert_called_once()
                    self.assertListEqual(
                        extract_first_call_arg_list(m=rs), expected_executed_shell_cmds
                    )

                mock_prev_stored_img.reset_mock()

                # scenario: use different store file pattern
                with mock_shell_exec(side_effects=shell_mock_side_effects) as rs:
                    cfg.programs["pydev"].build.dump.store = "/use/the/custom/path.tar"
                    o = self.obj(cfg=cfg)
                    o.ensure_custom_image()

                    mock_prev_stored_img.unlink.assert_not_called()
                    self.assertListEqual(
                        extract_first_call_arg_list(m=rs), expected_executed_shell_cmds
                    )

    @mock.patch.dict(os.environ, dict(HOME="/home/sweet_home"))
    def test_custom_image_dockerfile_store(self) -> None:
        cfg = sample_cfg_program_dependent_images()
        img = "custom_pydev_base"
        o = self.obj(cfg=cfg)

        with tempfile.NamedTemporaryFile(mode="w") as fh:
            fh.write(cfg.images[img].dockerfile_inline)
            fh.flush()

            result = o.custom_image_dockerfile_store(
                path=fh.name, image_name=img, build=cfg.images[img]
            )
            self.assertEqual(
                result,
                Path(
                    "/home/sweet_home/"
                    ".sandock_dump_images/"
                    "custom_pydev_base:linux_amd64d31f0d4d7213bdb50291.tar"
                ),
            )

    def test_attach_container(self) -> None:
        with mock_shell_exec() as rs:
            o = self.obj()
            self.assertFalse(
                o.attach_container, msg="non persist program will not attach"
            )

            rs.assert_not_called()

        with mock_shell_exec(
            side_effects=[dict(returncode=1, stderr="Error: No such container: pydev")]
        ) as rs:
            o = self.obj(program_kwargs=dict(persist=dict(enable=True), name="pydev"))

            self.assertFalse(
                o.attach_container, msg="non persist program will not attach"
            )

            self.assertEqual(rs.call_count, 1)
            self.assertEqual(
                rs.call_args_list[0].args[0],
                "docker container inspect pydev",
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
                "docker container inspect pydev",
            )

    def test_attach_container_status_stop_auto_start(self) -> None:

        side_effects = [
            dict(
                returncode=0, stdout='[{"State": {"Status": "exited"}}]'
            ),  # inspect container
            dict(returncode=0),  # start container
        ]
        with mock_shell_exec(side_effects=side_effects) as rs:
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
        with mock_shell_exec(
            side_effects=[
                dict(returncode=0, stdout='[{"State": {"Status": "exited"}}]')
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
                "docker container inspect pydev",
            )

    def test_attach_container_status_start(self) -> None:

        with mock_shell_exec(
            side_effects=[
                dict(returncode=0, stdout='[{"State": {"Status": "running"}}]')
            ]
        ) as rs:  # inspect container
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

        side_effects = [
            dict(returncode=0),  # pre cmd 1
            dict(returncode=0),  # pre cmd 2
            dict(returncode=0),  # docker run
        ]
        with mock_shell_exec(side_effects=side_effects) as rs:
            cfg = dummy_main_cfg(
                program_kwargs=dict(
                    pre_exec_cmds=["whoami", "cd /tmp"],
                    volumes=["namevol:/mnt:ro", "cache_${VOL_DIR}:/cache"],
                )
            )

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

        side_effects = [
            dict(returncode=0),  # pre cmd 1
            dict(returncode=0),  # pre cmd 2
            dict(returncode=0),  # docker run
        ]
        with mock_shell_exec(side_effects=side_effects) as rs:
            cfg = dummy_main_cfg(
                program_kwargs=dict(
                    name="pydev",
                    pre_exec_cmds=["whoami", "cd /tmp"],
                    volumes=["namevol:/mnt:ro", "cache_${VOL_DIR}:/cache"],
                )
            )

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
