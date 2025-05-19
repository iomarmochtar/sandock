import json
from typing import Any, Optional
from ..shared import KV, ensure_home_dir_special_prefix, log
from ..exceptions import SandboxExecConfig
from collections import OrderedDict
from pathlib import Path

DOT_CONFIG = ".sandock"


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

    # ensure the proper home dir pattern is set
    path = ensure_home_dir_special_prefix(path=path)

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


def build_if_set(o: object, attr: str, cls: Any) -> None:
    """
    helper, if the property is set with dictionary then build it as object with given class
    """
    prop = getattr(o, attr)
    if prop and isinstance(prop, dict):
        setattr(o, attr, cls(**prop))
