import re
from re import Pattern as RegexPattern
from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path
from ..shared import log, dict_merge, KV
from ._helpers import dot_config_finder, read_config


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
