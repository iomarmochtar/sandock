import os
import re
from dataclasses import dataclass, field
from typing import Dict, Optional, Any
from pathlib import Path
from ..shared import dict_merge, log, fetch_prop, flatten_list, KV, CONFIG_PATH_ENV, FETCH_PROP_ENABLE_ENV
from ..exceptions import SandboxExecConfig
from .image import ImageBuild
from .program import Program
from .config import Configuration
from .backup import Backup
from ._helpers import read_config, build_if_set, dot_config_finder

DEFAULT_CUSTOM_EXECUTORS = dict(
    apple_container=dict(
        bin_path="container",
        load_cls="sandock.executors.AppleContainerExec"
    )
)

fetch_prop_re = re.compile(r"^fetch_prop\(([^)]+)\)$")


@dataclass
class Volume(object):
    driver: Optional[str] = None
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
class Executor(object):
    bin_path: Optional[str] = None
    load_cls: Optional[str] = None

    def __post_init__(self) -> None:
        if self.bin_path is None and self.load_cls is None:
            raise ValueError("one of `bin_path` or `load_cls` must be set on executor")


@dataclass
class MainConfig(object):
    execution: Execution = field(default_factory=Execution)
    config: Configuration = field(default_factory=Configuration)
    backup: Backup = field(default_factory=Backup)
    programs: Dict[str, Program] = field(default_factory=dict)
    volumes: Dict[str, Volume] = field(default_factory=dict)
    images: Dict[str, ImageBuild] = field(default_factory=dict)
    networks: Dict[str, Network] = field(default_factory=dict)
    executors: Dict[str, Executor] = field(default_factory=dict)

    def __post_init__(self) -> None:
        build_if_set(self, attr="config", cls=Configuration)
        expanded_configs = self.config.expand_configs()

        build_if_set(self, attr="execution", cls=Execution)
        build_if_set(self, attr="backup", cls=Backup)

        self.executors = dict_merge(self.executors, DEFAULT_CUSTOM_EXECUTORS)
        # configuration that use kv format if the value set as dict
        cls_mapper = dict(
            programs=Program, volumes=Volume, networks=Network, images=ImageBuild,
            executors=Executor
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

        if self.fetch_prop_enable:
            self.resolve_fetch_prop(target=self)

    @property
    def fetch_prop_enable(self) -> bool:
        return os.getenv(FETCH_PROP_ENABLE_ENV) == "yes"

    def resolve_fetch_prop(self, target: Any=None) -> Any:
        if isinstance(target, dict):
            for k, v in target.items():
                target[k] = self.resolve_fetch_prop(v)
            return target

        elif isinstance(target, list):
            return [self.resolve_fetch_prop(i) for i in target]

        elif isinstance(target, str):
            match = fetch_prop_re.match(target.strip())
            if match:
                path = match.group(1).strip()
                return fetch_prop(path=path, obj=self)
            return target

        elif hasattr(target, "__dict__"):
            for attr, val in vars(target).items():
                if not val:
                    continue

                val = self.resolve_fetch_prop(val)
                if isinstance(val, list):
                    val = flatten_list(items=val)

                setattr(target, attr, val)
            return target

        return target


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
