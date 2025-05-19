import os
from dataclasses import dataclass, field
from typing import Dict, Optional
from pathlib import Path
from ..shared import dict_merge, log, KV, CONFIG_PATH_ENV
from ..exceptions import SandboxExecConfig
from .image import ImageBuild
from .program import Program
from .config import Configuration
from .backup import Backup
from ._helpers import read_config, build_if_set, dot_config_finder


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
class Execution(object):
    docker_bin: str = "docker"
    container_name_prefix: str = "sandock-"
    property_override_prefix_arg: str = "sandbox-arg-"
    alias_program_prefix: str = ""


@dataclass
class MainConfig(object):
    execution: Execution = field(default_factory=Execution)
    config: Configuration = field(default_factory=Configuration)
    backup: Backup = field(default_factory=Backup)
    programs: Dict[str, Program] = field(default_factory=dict)
    volumes: Dict[str, Volume] = field(default_factory=dict)
    images: Dict[str, ImageBuild] = field(default_factory=dict)
    networks: Dict[str, Network] = field(default_factory=dict)

    def __post_init__(self) -> None:
        build_if_set(self, attr="config", cls=Configuration)
        expanded_configs = self.config.expand_configs()

        build_if_set(self, attr="execution", cls=Execution)
        build_if_set(self, attr="backup", cls=Backup)

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

                # extend to another declaration, the direct declaration will be the top priority
                extends: KV = {}
                for extend_key in v.pop("extends", []):
                    extend_props = prop_val.get(extend_key)
                    if not extend_props:
                        raise SandboxExecConfig(
                            f"no config found to be extended by key `{extend_key}`"
                        )

                    # if it's already as object, take the raw config that still in KV
                    if hasattr(extend_props, "_raw"):
                        extend_props = extend_props._raw

                    extends = dict_merge(extends, extend_props)

                if extends:
                    v = dict_merge(extends, v)

                config_obj = prop_cls(**v)
                config_obj._raw = v
                getattr(self, name)[k] = config_obj

        # at least need to define one program
        if not self.programs:
            raise ValueError("no program configured")


def load_config_file(path: str) -> MainConfig:
    """
    a thin wrapper for read configuration file to MainConfig object
    """

    return MainConfig(**read_config(path=path))


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
