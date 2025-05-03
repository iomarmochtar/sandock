import os
import unittest
from re import Pattern
from pathlib import Path
from unittest import mock
from json.decoder import JSONDecodeError
from yaml.parser import ParserError
from inspect import cleandoc
from helpers import fixture_path, BaseTestCase, mock_yaml_module_not_installed
from sandock.exceptions import SandboxExecConfig
from sandock.config import (
    ImageBuild,
    Program,
    ContainerUser,
    PersistContainer,
    Volume,
    Network,
    SandboxMount,
    Configuration,
    Execution,
    MainConfig,
    load_config_file,
    dot_config_finder,
    main_config_finder,
    yaml_decoder,
    json_decoder,
)


class VolumeTest(BaseTestCase):
    def test_defaults(self) -> None:
        o = Volume()

        self.assertEqual(o.driver, "local")
        self.assertEqual(o.driver_opts, {})
        self.assertEqual(o.labels, {})


class NetworkTest(BaseTestCase):
    def test_defaults(self) -> None:
        o = Network()

        self.assertEqual(o.driver, "bridge")
        self.assertEqual(o.driver_opts, {})
        self.assertEqual(o.params, {})


class ImageBuildTest(BaseTestCase):
    def test_defaults(self) -> None:
        o = ImageBuild()

        self.assertIsNone(o.context)
        self.assertIsNone(o.dockerfile_inline)
        self.assertIsNone(o.dockerFile)

    def test_validations(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "cannot set `dockerfile_inline` and `dockerFile` together"
        ):
            ImageBuild(dockerFile="Dockerfile", dockerfile_inline="FROM ubuntu:22.04")


class ContainerUserTest(BaseTestCase):
    def test_defaults(self) -> None:
        o = ContainerUser()

        self.assertEqual(o.uid, 0)
        self.assertEqual(o.gid, 0)
        self.assertFalse(o.keep_id)

    def test_validations(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "cannot enabled on `keep_id` and set custom on `uid` in same time",
        ):
            ContainerUser(keep_id=True, uid=1000)

        with self.assertRaisesRegex(
            ValueError,
            "cannot enabled on `keep_id` and set custom on `gid` in same time",
        ):
            ContainerUser(keep_id=True, gid=1000)


class SandboxMountTest(BaseTestCase):
    def test_defaults(self) -> None:
        o = SandboxMount()

        self.assertTrue(o.enable)
        self.assertFalse(o.read_only)
        self.assertEqual(o.current_dir_mount, "/sandbox")


class PersistContainerTest(BaseTestCase):
    def test_defaults(self) -> None:
        o = PersistContainer()

        self.assertFalse(o.enable)
        self.assertTrue(o.auto_start)


class ConfigurationTest(BaseTestCase):
    def test_post_init(self) -> None:
        o = Configuration(
            current_dir_conf=False,
            current_dir_conf_excludes=["^/to/the/path/.*?/unsecure/.*$"],
            includes=["/to/the/conf"],
        )

        self.assertTrue(isinstance(o.current_dir_conf_excludes[0], Pattern))
        self.assertFalse(o.current_dir_conf)
        self.assertListEqual(o.includes, ["/to/the/conf"])

    @mock.patch.object(Path, "cwd")
    def test_dir_conf(self, path_cwd: mock.MagicMock) -> None:
        # test the order of current directory configuration file
        current_dir = Path("/current/dir")
        path_cwd.return_value = current_dir

        self.assertIsNone(
            Configuration(current_dir_conf=False).dir_conf,
            msg="when the config is disabled",
        )

        check_sequences = [".sandock.yml", ".sandock.yaml", ".sandock.json", ".sandock"]
        for xid in range(len(check_sequences)):
            check_sequence = check_sequences[xid]

            with mock.patch.object(Path, "exists") as path_exists:
                # mock the exists
                path_exists.side_effect = [
                    yid == xid for yid in range(len(check_sequence))
                ]

                o = Configuration()
                self.assertEqual(o.dir_conf, str(current_dir / check_sequence))

    def test_filter_current_dir_config(self) -> None:
        o = Configuration(current_dir_conf_excludes=["^/ignored/for/the/path.*?$"])

        self.assertIsNone(
            o.filter_current_dir_conf("/ignored/for/the/path/here/and/there")
        )
        self.assertEqual(
            o.filter_current_dir_conf("/ignored/for/the/excepted/here/and/there"),
            "/ignored/for/the/excepted/here/and/there",
        )

    def test_expand_configs_includes(self) -> None:
        expected = {
            "execution": {"docker_bin": "podman"},
            "volumes": {"go_cache": {}, "python_vol": {}},
            "programs": {
                "py311": {
                    "image": "python:3.11.12-slim-bullseye",
                    "exec": "python3",
                    "network": "none",
                    "aliases": {"sh": "/bin/bash"},
                },
                "go122": {
                    "image": "golang:1.22.12-bookworm",
                    "exec": "go",
                    "env": {
                        "GOCACHE": "/cache/gocache",
                        "GOMODCACHE": "/cache/gomodcache",
                    },
                    "volumes": ["go_cache:/cache"],
                },
                "mycurrent_dir_progs": {
                    "image": "python:3.11.12-slim-bullseye",
                    "exec": "python",
                    "volumes": ["python_vol:/opt/mount:ro"],
                },
            },
        }
        with mock.patch.object(
            Configuration, "dir_conf", fixture_path("sample_configs", "dir_conf.json")
        ):
            o = Configuration(
                includes=[
                    fixture_path("sample_configs", "ok_simple.json"),
                    fixture_path("sample_configs", "include_config.json"),
                ]
            )

            self.assertDictEqual(o.expand_configs(), expected)


class ExecutionTest(BaseTestCase):
    def test_defaults(self) -> None:
        o = Execution()

        self.assertEqual(o.docker_bin, "docker")
        self.assertEqual(o.container_name_prefix, "sandock-")
        self.assertEqual(o.property_override_prefix_arg, "sandbox-arg-")
        self.assertEqual(o.alias_program_prefix, "")


class ProgramTest(BaseTestCase):
    def obj(self, **kwargs) -> Program:
        kwargs = dict(image="custom_img", exec="/bin/bash") | kwargs

        return Program(**kwargs)

    def test_defaults(self) -> None:
        o = self.obj()

        self.assertTrue(o.interactive, True)
        self.assertFalse(o.allow_home_dir)
        self.assertIsNone(o.name)
        self.assertIsNone(o.network)
        self.assertIsNone(o.hostname)
        self.assertIsNone(o.user)
        self.assertEqual(o.persist, PersistContainer())
        self.assertIsNone(o.build)
        self.assertIsNone(o.workdir)
        self.assertIsNone(o.platform)
        self.assertEqual(o.env, {})
        self.assertEqual(o.aliases, {})
        self.assertEqual(o.volumes, [])
        self.assertEqual(o.ports, [])
        self.assertEqual(o.cap_add, [])
        self.assertEqual(o.cap_drop, [])
        self.assertEqual(o.extra_run_args, [])
        self.assertEqual(o.pre_exec_cmds, [])

    def test_build(self) -> None:
        o = self.obj(build=dict(dockerfile_inline="FROM ubuntu:22.04"))

        self.assertEqual(type(o.build), ImageBuild)
        self.assertEqual(o.build.dockerfile_inline, "FROM ubuntu:22.04")

    def test_user(self) -> None:
        # defaults
        self.assertEqual(
            self.obj(user=dict(keep_id=True)).user,
            ContainerUser(uid=0, gid=0, keep_id=True),
        )

    def test_persist(self) -> None:
        # defaults
        self.assertEqual(
            self.obj(
                persist=dict(
                    enable=True,
                    auto_start=False,
                )
            ).persist,
            PersistContainer(enable=True, auto_start=False),
        )

    def test_sandbox_mount(self) -> None:
        self.assertEqual(
            self.obj(
                sandbox_mount=dict(
                    enable=False,
                    current_dir_mount="/abc",
                )
            ).sandbox_mount,
            SandboxMount(enable=False, current_dir_mount="/abc"),
        )

    def test_validations(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "cannot use workdir with enabled sandbox mount in the same time"
        ):
            self.obj(sandbox_mount=dict(enable=True), workdir="/some/path")


class MainConfigTest(BaseTestCase):
    def obj(self, **kwargs) -> MainConfig:
        # mock the object with default program injected
        kwargs = (
            dict(programs=dict(pydev=Program(image="python:3.11", exec="python3")))
            | kwargs
        )
        return MainConfig(**kwargs)

    def test_defaults(self) -> None:
        o = self.obj()

        self.assertEqual(o.execution, Execution())
        self.assertEqual(o.config, Configuration())
        self.assertEqual(o.volumes, {})
        self.assertEqual(o.images, {})
        self.assertEqual(o.networks, {})

    def test_no_programs_defined(self) -> None:
        with self.assertRaisesRegex(ValueError, "no program configured"):
            MainConfig()

    def test_post_init_expand_configs(self) -> None:
        # test the expanded configuration
        with mock.patch.object(Configuration, "expand_configs") as c_expand_cfgs:
            c_expand_cfgs.return_value = dict(volumes=dict(abc=dict()))

            o = self.obj()
            self.assertEqual(o.volumes["abc"], Volume())

    def test_volumes(self) -> None:
        o = self.obj(volumes=dict(pyvol=dict(labels={"mark.label.com": "setset"})))

        self.assertEqual(
            o.volumes["pyvol"], Volume(labels={"mark.label.com": "setset"})
        )

    def test_programs(self) -> None:
        o = self.obj(
            programs=dict(
                py311=dict(
                    image="python:3.11.12-slim-bullseye",
                    exec="python3",
                    sandbox_mount=dict(enable=False),
                ),
                ruby33=dict(image="ruby:3.3.8-slim-bookworm", exec="ruby"),
            )
        )

        self.assertEqual(len(o.programs), 2)
        self.assertFalse(o.programs["py311"].sandbox_mount.enable)
        self.assertEqual(
            o.programs["ruby33"], Program(image="ruby:3.3.8-slim-bookworm", exec="ruby")
        )

    def test_images(self) -> None:
        o = self.obj(
            images=dict(
                ubuntu_basic=dict(dockerfile_inline="FROM ubuntu:2204\nRUN apt update")
            )
        )

        self.assertEqual(len(o.images), 1)
        self.assertEqual(
            o.images["ubuntu_basic"],
            ImageBuild(dockerfile_inline="FROM ubuntu:2204\nRUN apt update"),
        )

    def test_networks(self) -> None:
        o = self.obj(
            networks=dict(
                net1=dict(
                    driver="default",
                    params=dict(
                        subnet="192.168.0.0/24",
                        gateway="192.168.0.1",
                    ),
                )
            )
        )

        self.assertEqual(len(o.networks), 1)
        self.assertEqual(
            o.networks["net1"],
            Network(
                driver="default",
                params=dict(subnet="192.168.0.0/24", gateway="192.168.0.1"),
            ),
        )


class HelpersTest(BaseTestCase):
    def test_load_config_file(self) -> None:
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

        yaml_config = fixture_path("sample_configs", "ok_simple.yml")
        json_config = fixture_path("sample_configs", "ok_simple.json")
        self.assertEqual(load_config_file(path=yaml_config), expected_config)
        self.assertEqual(load_config_file(path=json_config), expected_config)

    def test_load_config_file_broken(self) -> None:
        with self.assertRaises(JSONDecodeError):
            json_config = fixture_path("sample_configs", "err_config.json")
            load_config_file(path=json_config)

        with self.assertRaises(ParserError):
            config_pth = fixture_path("sample_configs", "err_config.yml")
            load_config_file(path=config_pth)

    @mock_yaml_module_not_installed()
    def test_load_config_yaml_module_not_installed(self) -> None:
        with self.assertRaises(SandboxExecConfig):
            yaml_config = fixture_path("sample_configs", "ok_simple.yml")
            load_config_file(path=yaml_config)

    def test_dot_config_finder(self) -> None:

        some_path = Path("some", "path")
        check_sequences = [".sandock.yml", ".sandock.yaml", ".sandock.json", ".sandock"]
        for xid in range(len(check_sequences)):
            check_sequence = check_sequences[xid]

            with mock.patch.object(Path, "exists") as path_exists:
                # mock the exists
                path_exists.side_effect = [
                    yid == xid for yid in range(len(check_sequence))
                ]

                o = Configuration()
                self.assertEqual(
                    dot_config_finder(directory=some_path), (some_path / check_sequence)
                )

        # none all of them
        with mock.patch.object(Path, "exists") as path_exists:
            path_exists.side_effect = [None for x in range(len(check_sequence) + 1)]
            self.assertIsNone(dot_config_finder(directory=some_path))

    @mock.patch.object(Path, "home")
    def test_main_config_finder(self, path_home: mock.MagicMock) -> None:
        path_home.return_value = Path("/my/home")

        self.assertEqual(
            main_config_finder(explicit_mention="/to/the/path"),
            "/to/the/path",
            msg="1. explicit will be the first",
        )

        with mock.patch.dict(os.environ, dict(SNDK_CFG="/mention/in/env")):
            self.assertEqual(
                main_config_finder(), "/mention/in/env", msg="2. environment variable"
            )

        with mock.patch.object(Path, "exists") as path_exists:
            path_exists.return_value = True
            self.assertEqual(
                main_config_finder(),
                "/my/home/.sandock.yml",
                msg="3. dot config file in home directory",
            )

        with mock.patch("sandock.config.dot_config_finder") as mock_dot_config_finder:
            mock_dot_config_finder.side_effect = [
                None,  # not found in home directory
                Path("/current/directory/.sandock"),
            ]
            self.assertEqual(
                main_config_finder(),
                "/current/directory/.sandock",
                msg="4. found in current directory",
            )

        with mock.patch("sandock.config.dot_config_finder") as mock_dot_config_finder:
            mock_dot_config_finder.return_value = None
            with mock.patch.object(Path, "cwd") as path_cwd:
                path_cwd.return_value = Path("/my/home")

                self.assertIsNone(
                    main_config_finder(),
                    msg="in home directory and no configuration found",
                )

        self.assertIsNone(main_config_finder(), msg="no main configuration found")

    def test_json_decoder(self) -> None:
        self.assertDictEqual(
            json_decoder(content='{"hello": {"this": "is world"}}'),
            {"hello": {"this": "is world"}},
        )

    def test_yaml_decoder(self) -> None:
        self.assertDictEqual(
            yaml_decoder(
                content=cleandoc(
                    """
        hello:
            this: is world
        """
                )
            ),
            {"hello": {"this": "is world"}},
        )

        with mock_yaml_module_not_installed():
            with self.assertRaises(SandboxExecConfig, msg="yaml module not found"):
                yaml_decoder(content="hello: world")


if __name__ == "__main__":
    unittest.main()
