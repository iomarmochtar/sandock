import os
import json
import tempfile
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from .config import MainConfig, Program
from .shared import log, run_shell
from .exceptions import SandboxExecution

VOL_LABEL_CREATED_BY = "created_by.sandock"
VOL_SANDBOX_DIR_SUFFIX_NAME = "sandock-dir-"
VOL_DIR_SUBS = "${VOL_DIR}"
CONTAINER_STATE_RUNNING = "running"
special_char_re = re.compile(r"\W+")


class SandboxExec(object):
    cfg: MainConfig
    program_name: str
    program: Program
    interactive: bool
    container_name: str

    def __init__(
        self, name: str, cfg: MainConfig, overrides: Dict[str, Any] = {}
    ) -> None:
        self.cfg = cfg
        self.name = name
        program = self.cfg.programs.get(name)
        if not program:
            raise SandboxExecution(f"`{name}` is not defined")

        # persist container cannot be renamed in preventing unexpected behaviour
        # (eg: need gc the stopped one with different name)
        if program.persist.enable and "name" in overrides:
            raise SandboxExecution("name of persist program cannot be overrided")

        # apply program's attribute overrides
        for k, v in overrides.items():
            if not hasattr(program, k):
                log.warning(f"program doesn't has property {k}")
                continue

            log.debug(f"overriding value {v} in property {k}")
            setattr(program, k, v)
        self.program = program

        # prevent if it's run on homedir, we don't want unintended breach except their aware
        if (
            self.program.sandbox_mount.enable
            and not self.program.allow_home_dir
            and self.current_dir == self.home_dir
        ):
            raise SandboxExecution(
                "cannot be ran on top of home directory when the program's sandbox mount is enabled"
            )

        self.container_name = self.generate_container_name()

    @property
    def docker_bin(self) -> str:
        return self.cfg.execution.docker_bin

    @property
    def current_timestamp(self) -> float:
        return datetime.now().timestamp()

    def generate_container_name(self) -> str:
        if self.program.name:
            return self.program.name

        generated_name = f"{self.cfg.execution.container_name_prefix}{self.name}"
        # don't give timestampt if it's persist
        if not self.program.persist.enable:
            generated_name += f"-{self.current_timestamp}"
        return generated_name

    @property
    def home_dir(self) -> Optional[str]:
        return os.environ.get("HOME")

    @property
    def current_dir(self) -> str:
        return os.getcwd()

    @property
    def exec_path(self) -> str:
        """
        grab the alias first
        """
        pe = self.program.exec
        return self.program.aliases.get(pe, pe)

    def run_container_cmd(self) -> List[str]:
        """
        docker run command builder
        """
        command = [
            self.docker_bin,
            "run",
            "--entrypoint",
            self.exec_path,
            "--name",
            self.container_name,
        ]

        if not self.program.persist.enable:
            command.append("--rm")

        if self.program.interactive:
            command.append("-it")

        if self.program.platform:
            command.extend(["--platform", self.program.platform])

        if self.program.hostname:
            command.extend(["--hostname", self.program.hostname])

        if self.program.network:
            command.extend(["--network", self.program.network])

        user = self.program.user
        if user:
            uid = self.current_uid if user.keep_id else user.uid
            gid = self.current_gid if user.keep_id else user.gid
            command.extend(["-u", f"{uid}:{gid}"])

        workdir = self.program.workdir
        volumes = self.program.volumes
        if self.program.sandbox_mount.enable:
            # when sandbox mount enable, set the default workdir to it
            workdir = self.program.sandbox_mount.current_dir_mount
            sandbox_mount = (
                f"{self.current_dir}:{self.program.sandbox_mount.current_dir_mount}"
            )
            if self.program.sandbox_mount.read_only:
                sandbox_mount += ":ro"

            volumes.append(sandbox_mount)

        for v in volumes:
            if VOL_DIR_SUBS in v:
                log.debug("[vol] volume dir identified, subs the var")
                v = v.replace(
                    VOL_DIR_SUBS, special_char_re.sub("_", self.current_dir[1:])
                )
            command.extend(["-v", v])

        if workdir:
            command.extend(["--workdir", workdir])

        command.extend([f"-e {k}='{v}'" for k, v in self.program.env.items()])
        command.extend([f"-p {p}" for p in self.program.ports])
        command.extend([f"--cap-add={c}" for c in self.program.cap_add])
        command.extend([f"--cap-drop={c}" for c in self.program.cap_drop])
        command.extend(self.program.extra_run_args)
        command.append(self.program.image)

        return command

    @property
    def current_uid(self) -> int:
        return os.getuid()

    @property
    def current_gid(self) -> int:
        return os.getgid()

    def ensure_volume(self, name: str) -> None:
        """
        ensure the volume created as expected based on configuration if exists
        """
        log.debug(f"[vol] check volume by name {name} in configuration")
        vol = self.cfg.volumes.get(name)
        if not vol:
            log.debug(f"[vol] {name} not exists in config")
            return

        inspect_vol = run_shell(
            f"{self.docker_bin} volume inspect {name}", check_err=False
        )
        # vol exists
        if inspect_vol.returncode == 0:
            vol_info = json.loads(inspect_vol.stdout)
            log.debug(f"[vol] exists, info ~> {vol_info}")
            return

        log.info(f"[vol] creating vol {name}")
        # mandatory label
        if VOL_LABEL_CREATED_BY not in vol.labels:
            vol.labels[VOL_LABEL_CREATED_BY] = "true"

        vol_ops = " ".join([f"--opt {k}={v}" for k, v in vol.driver_opts.items()])
        vol_labels = " ".join([f"--label {k}='{v}'" for k, v in vol.labels.items()])
        vol_create_cmd = (
            f"{self.docker_bin} volume create "
            f"--driver={vol.driver} {vol_ops} {vol_labels}"
            f" {name}"
        )
        run_shell(vol_create_cmd, capture_output=False)

    def ensure_network(self) -> None:
        net_name = self.program.network
        if not net_name:
            return

        log.debug(f"[net] ensuring network by name `{net_name}` in configuration")
        network = self.cfg.networks.get(net_name)
        if not network:
            log.debug(
                f"[net] network by name {net_name} is not managed in configuration"
            )
            return

        inspect_net = run_shell(
            f"{self.docker_bin} network inspect {net_name}", check_err=False
        )
        if inspect_net.returncode == 0:
            net_info = json.loads(inspect_net.stdout)
            log.debug(f"[net] exists, info ~> {net_info}")
            return

        log.info(f"[net] creating net {net_name}")

        net_params = " ".join([f"--{k}={v}" for k, v in network.params.items()])
        net_driver_opts = " ".join(
            [f"--opt {k}={v}" for k, v in network.driver_opts.items()]
        )
        net_create_cmd = (
            f"{self.docker_bin} network create "
            f"--driver={network.driver} {net_params} {net_driver_opts}"
            f"{net_name}"
        )
        run_shell(net_create_cmd, capture_output=False)

    def ensure_custom_image(self, image_name: Optional[str] = None) -> None:
        """
        if it's intended to use custom image
        """
        image_name = image_name or self.program.image
        build_image = self.cfg.images.get(image_name) or self.program.build
        if not build_image:
            return

        # recursively check for any dependent before build
        if build_image.depends_on:
            log.debug(f"found image depends on {build_image.depends_on}")
            self.ensure_custom_image(image_name=build_image.depends_on)

        inspect_img = run_shell(
            f"{self.docker_bin} image inspect {image_name}", check_err=False
        )

        if inspect_img.returncode == 0:
            img_info = json.loads(inspect_img.stdout)
            log.debug(f"[img] exists, info ~> {img_info}")
            return

        log.info(f"[img] creating image {image_name}")
        working_dir = build_image.context
        if not working_dir:
            # if context not set then create the temporary one
            log.debug("[img] context was not set, create the temporary dir")
            working_dir = tempfile.mkdtemp()

        docker_file_path = build_image.dockerFile
        if not docker_file_path and build_image.dockerfile_inline:
            log.debug(
                "[img] docker file not defined, create the temporary one from `dockerfile_inline`"
            )
            docker_file_path = tempfile.mktemp()
            with open(docker_file_path, "w") as fh:
                fh.write(
                    build_image.dockerfile_inline.replace(
                        "{CURRENT_GID}", str(self.current_gid)
                    ).replace("{CURRENT_UID}", str(self.current_uid))
                )

        img_create_cmd = f"{self.docker_bin} build -t {image_name}"
        if docker_file_path:
            img_create_cmd += f" -f {docker_file_path}"

        for k_arg, v_arg in build_image.args.items():
            img_create_cmd += f' --build-arg {k_arg}="{v_arg}"'

        if build_image.extra_build_args:
            img_create_cmd += f' {" ".join(build_image.extra_build_args)}'

        if self.program.platform:
            img_create_cmd += f" --platform={self.program.platform}"

        img_create_cmd += f" {working_dir}"
        run_shell(img_create_cmd, capture_output=False)

        # garbage collect
        if (
            build_image.dockerfile_inline
            and docker_file_path is not None
            and os.path.isfile(docker_file_path)
        ):
            os.remove(docker_file_path)

    @property
    def attach_container(self) -> bool:
        """
        determine whether attaching to existsing container ?
        """
        if not self.program.persist.enable:
            return False

        cmd = f"{self.docker_bin} container inspect {self.container_name}"
        inspect_result = run_shell(cmd, check_err=False)
        if inspect_result.returncode != 0:
            # it might be the uncreated container
            err_msg = str(inspect_result.stderr)
            if "no such container" in err_msg.lower():
                return False

            # the known message if container not found, other than that just raise it
            raise SandboxExecution(f"error during check container status: {err_msg}")

        container_info = json.loads(inspect_result.stdout)
        if len(container_info) < 1:
            log.warning(
                f"empty container info status during inspection ~> {container_info}"
            )
            return False

        is_running: bool = (
            container_info[0].get("State", {}).get("Status") == CONTAINER_STATE_RUNNING
        )
        if not is_running and self.program.persist.auto_start:
            log.warning("persist container is down, starting container")
            run_shell(
                f"{self.docker_bin} container start {self.container_name}",
                capture_output=False,
            )

            # just attach to it after start
            return True

        return is_running

    def exec_container_cmd(self) -> List[str]:
        cmd = [self.docker_bin, "exec"]

        if self.program.interactive:
            cmd.append("-it")

        cmd.extend([self.container_name, self.exec_path])
        return cmd

    def do(self, args: List[str] = []) -> None:
        """
        main flows
        """
        for pre_exec in self.program.pre_exec_cmds:
            log.debug(f"[pre_exec] running shell command ~> {pre_exec}")
            run_shell(pre_exec)

        # ensure container dependencies are created
        self.ensure_custom_image()
        self.ensure_network()
        for extra_mount in self.program.volumes:
            vol = extra_mount.split(":")[0]
            self.ensure_volume(name=vol)

        run_container_cmd = (
            self.exec_container_cmd()
            if self.attach_container
            else self.run_container_cmd()
        )
        run_container_cmd.extend(args)

        log.debug(f"starting container cmd ~> {run_container_cmd}")
        run_shell(command=" ".join(run_container_cmd), capture_output=False)
