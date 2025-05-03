import json
import os
import re
from re import Pattern as RegexPattern
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from pathlib import Path
from .shared import dict_merge, log, KV
from .exceptions import SandboxExecConfig

CONFIG_PATH_ENV = "SNDK_CFG"
DOT_CONFIG = ".sandock"


def build_if_set(o: object, attr: str, cls: Any) -> None:
    """
    helper, if the property is set with dictionary then build it as object with given class
    """
    prop = getattr(o, attr)
    if prop and isinstance(prop, dict):
        setattr(o, attr, cls(**prop))


def json_decoder(content: str) -> KV:
    """
    convert json content to dictionary
    """
    return json.loads(content)  # type: ignore[no-any-return]


def yaml_decoder(content: str) -> KV:
    """
    convert json content to dictionary
    """

    try:
        import yaml
    except ImportError:
        raise SandboxExecConfig(
            "yaml parser module not installed, try to install by following command:\npip install 'sandock[yml-config]'\nor manual module install:\npip install pyyaml"
        )
    raw = yaml.safe_load(content)

    # remove all that startswith x-*
    return {k: v for k, v in raw.items() if not k.startswith("x-")}


# the list of supported formatted configuration, default to json decoder
# ordering is critical here, it also determines what will be look up first
CONFIG_FORMAT_DECODER_MAPS = OrderedDict()
CONFIG_FORMAT_DECODER_MAPS[".yml"] = yaml_decoder
CONFIG_FORMAT_DECODER_MAPS[".yaml"] = yaml_decoder
CONFIG_FORMAT_DECODER_MAPS[".json"] = json_decoder


def read_config(path: str) -> KV:
    """
    read configuration as dict/kv based on it's decoder
    """
    conf_format = Path(path).suffix
    decoder = CONFIG_FORMAT_DECODER_MAPS.get(conf_format, json_decoder)
    with open(path, "r") as fh:
        return decoder(content=fh.read())


def dot_config_finder(directory: Path) -> Optional[Path]:
    """
    the logic behind dot configuration file based on given directory path
    """

    dot_config = directory / DOT_CONFIG
    for dot_format in CONFIG_FORMAT_DECODER_MAPS.keys():
        dot_current_format = dot_config.with_suffix(dot_format)
        log.debug(
            f"[config] dot config finder: searching by format in path {dot_current_format}"
        )
        if dot_current_format.exists():
            return dot_current_format

    log.debug(
        f"[config] dot config finder: searching without format in path {dot_config}"
    )

    return dot_config if dot_config.exists() else None


def main_config_finder(explicit_mention: Optional[str] = None) -> Optional[str]:
    """
    logic in finding configuration file by it's order
    """
    if explicit_mention:
        return explicit_mention

    env_conf = os.environ.get(CONFIG_PATH_ENV, None)
    if env_conf:
        return env_conf

    # dot config check
    dot_config = None
    home_dir = Path.home()
    home_dir_conf = dot_config_finder(directory=home_dir)
    if home_dir_conf:
        dot_config = home_dir_conf

    # last try for current directory
    current_dir = Path.cwd()
    if not dot_config and home_dir != current_dir:
        dot_config = dot_config_finder(directory=current_dir)

    return str(dot_config) if dot_config else None


@dataclass
class Volume(object):
    driver: str = "local"
    driver_opts: Dict[str, str] = field(default_factory=dict)
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class Network(object):
    driver: str = "bridge"
    driver_opts: Dict[str, str] = field(default_factory=dict)
    params: Dict[str, str] = field(default_factory=dict)


@dataclass
class ImageBuild(object):
    context: Optional[str] = None
    dockerfile_inline: Optional[str] = None
    dockerFile: Optional[str] = None
    depends_on: Optional[str] = None
    args: Dict[str, str] = field(default_factory=dict)
    extra_build_args: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.dockerfile_inline and self.dockerFile:
            raise ValueError("cannot set `dockerfile_inline` and `dockerFile` together")


@dataclass
class ContainerUser(object):
    uid: int = 0
    gid: int = 0
    # keep both uid and gid
    keep_id: bool = False

    def __post_init__(self) -> None:
        if self.keep_id and self.uid != 0:
            raise ValueError(
                "cannot enabled on `keep_id` and set custom on `uid` in same time"
            )

        if self.keep_id and self.gid != 0:
            raise ValueError(
                "cannot enabled on `keep_id` and set custom on `gid` in same time"
            )


@dataclass
class SandboxMount(object):
    enable: bool = True
    read_only: bool = False
    current_dir_mount: str = "/sandbox"


@dataclass
class PersistContainer(object):
    enable: bool = False
    auto_start: bool = True


@dataclass
class Program(object):
    image: str
    exec: str
    interactive: bool = True
    allow_home_dir: bool = False
    name: Optional[str] = None
    network: Optional[str] = None
    hostname: Optional[str] = None
    build: Optional[ImageBuild] = None
    user: Optional[ContainerUser] = None
    workdir: Optional[str] = None
    platform: Optional[str] = None
    persist: PersistContainer = field(default_factory=PersistContainer)
    sandbox_mount: SandboxMount = field(default_factory=SandboxMount)
    env: Dict[str, str] = field(default_factory=dict)
    volumes: List[str] = field(default_factory=list)
    ports: List[str] = field(default_factory=list)
    cap_add: List[str] = field(default_factory=list)
    cap_drop: List[str] = field(default_factory=list)
    aliases: Dict[str, str] = field(default_factory=dict)
    extra_run_args: List[str] = field(default_factory=list)
    pre_exec_cmds: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        build_if_set(self, attr="build", cls=ImageBuild)
        build_if_set(self, attr="user", cls=ContainerUser)
        build_if_set(self, attr="persist", cls=PersistContainer)
        build_if_set(self, attr="sandbox_mount", cls=SandboxMount)

        if self.sandbox_mount.enable and self.workdir:
            raise ValueError(
                "cannot use workdir with enabled sandbox mount in the same time"
            )


@dataclass
class Execution(object):
    docker_bin: str = "docker"
    container_name_prefix: str = "sandock-"
    property_override_prefix_arg: str = "sandbox-arg-"
    alias_program_prefix: str = ""


@dataclass
class Configuration(object):
    current_dir_conf: bool = True
    current_dir_conf_excludes: List[RegexPattern] = field(default_factory=list)  # type: ignore[type-arg]
    includes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # convert to the list of regex patterns, intended as a list for next feature comes
        rgx_pattern_props = [
            "current_dir_conf_excludes",
        ]
        for rgx_prop in rgx_pattern_props:
            ptrns = []
            for val in getattr(self, rgx_prop):
                ptrns.append(re.compile(val))

            setattr(self, rgx_prop, ptrns)

    def filter_current_dir_conf(self, location: Path) -> Optional[str]:
        """
        determine whether it's allowed based on exclude pattern list
        """
        fpath = str(location)
        for current_dir_exlude in self.current_dir_conf_excludes:
            if current_dir_exlude.fullmatch(fpath):
                log.debug(
                    f"[config] current directory config `{fpath}` is excluded due match with the list (`{current_dir_exlude}`)"
                )
                return None

        return fpath

    @property
    def dir_conf(self) -> Optional[str]:
        """
        return the path of current directory conf if it's enabled and the file is exists
        """
        if not self.current_dir_conf:
            return None

        current_path = Path.cwd()
        dot_current = dot_config_finder(directory=current_path)
        return (
            self.filter_current_dir_conf(location=dot_current) if dot_current else None
        )

    def expand_configs(self) -> KV:
        """
        list of expanded config
        """
        tobe_merged: KV = {}

        # include list
        for inc in self.includes:
            log.debug(f"[config] read included file {inc}")
            tobe_merged = dict_merge(tobe_merged, read_config(path=inc))

        # dot configuration
        current_dir_config = self.dir_conf
        if current_dir_config:
            log.debug(f"[config] read current configuration dir {current_dir_config}")
            tobe_merged = dict_merge(tobe_merged, read_config(path=current_dir_config))

        return tobe_merged


@dataclass
class MainConfig(object):
    execution: Execution = field(default_factory=Execution)
    config: Configuration = field(default_factory=Configuration)
    programs: Dict[str, Program] = field(default_factory=dict)
    volumes: Dict[str, Volume] = field(default_factory=dict)
    images: Dict[str, ImageBuild] = field(default_factory=dict)
    networks: Dict[str, Network] = field(default_factory=dict)

    def __post_init__(self) -> None:
        build_if_set(self, attr="config", cls=Configuration)
        expanded_configs = self.config.expand_configs()

        build_if_set(self, attr="execution", cls=Execution)

        # configuration that use kv format if the value set as dict
        cls_mapper = dict(
            programs=Program, volumes=Volume, networks=Network, images=ImageBuild
        )

        for name, prop_cls in cls_mapper.items():
            prop_val = getattr(self, name)

            # expand if it's included
            expand_config = expanded_configs.get(name, {})
            if expand_config:
                log.debug(f"[config] expanding config attr {name} ~> {expand_config}")
                prop_val = dict_merge(prop_val, expand_config)

            for k, v in prop_val.items():
                if not isinstance(v, dict):
                    continue

                getattr(self, name)[k] = prop_cls(**v)

        # at least need to define one program
        if not self.programs:
            raise ValueError("no program configured")


def load_config_file(path: str) -> MainConfig:
    """
    a thin wrapper for read configuration file to MainConfig object
    """

    return MainConfig(**read_config(path=path))
