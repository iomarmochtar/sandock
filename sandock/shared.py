import logging
import subprocess
import os
import re
from hashlib import sha256
from typing import Any, Union, Dict, List, Optional


KV = Dict[str, Any]
CONFIG_PATH_ENV = "SNDK_CFG"
SANDBOX_DEBUG_ENV = "SNDK_DEBUG"
FETCH_PROP_ENABLE_ENV = "SNDK_FETCH_PROP"


class LogColorFormatter(logging.Formatter):
    # ref: https://alexandra-zaharia.github.io/posts/make-your-own-custom-color-formatter-with-python-logging/
    grey = "\x1b[38;21m"
    blue = "\x1b[38;5;39m"
    yellow = "\x1b[38;5;226m"
    red = "\x1b[38;5;196m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"

    def __init__(self, fmt: str) -> None:
        super().__init__()
        self.fmt = fmt
        self.FORMATS = {
            logging.DEBUG: self.grey + self.fmt + self.reset,
            logging.INFO: self.blue + self.fmt + self.reset,
            logging.WARNING: self.yellow + self.fmt + self.reset,
            logging.ERROR: self.red + self.fmt + self.reset,
            logging.CRITICAL: self.bold_red + self.fmt + self.reset,
        }

    def format(self, record: Any) -> str:
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


def init_logger(name: str, lvl: Union[int, str] = logging.DEBUG) -> logging.Logger:
    pattern = "%(asctime)s | %(levelname)3s | %(message)s"
    logger = logging.getLogger(name)
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(LogColorFormatter(pattern))
    logger.setLevel(lvl)
    logger.addHandler(handler)

    return logger


log = init_logger(name="sandbox-exec", lvl=logging.INFO)


def run_shell(  # type: ignore[no-untyped-def]
    command: Union[str, List[str]], check_err: bool = True, **cmd_args
) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
    """
    wrapper of shell command execution
    """
    cmd_args = (
        dict(
            shell=True,
            capture_output=True,
            text=True,
        )
        | cmd_args
    )
    if isinstance(command, list):
        # filter for empty elem, this might from the result of inline if-else
        command = " ".join([x for x in command if x])

    log.debug(f"shell cmd: {command}, check_err: {check_err}, cmd_args: {cmd_args}")
    call_cmd = subprocess.run(command, **cmd_args)
    if check_err and call_cmd.returncode != 0:
        msg = f"error in executing command: {command}"
        if call_cmd.stderr:
            msg += f", stderr: {call_cmd.stderr}"
        if call_cmd.stdout:
            msg += f", stdout: {call_cmd.stdout}"
        raise subprocess.CalledProcessError(
            cmd=msg,
            returncode=call_cmd.returncode,
        )
    return call_cmd


def list_remove_element(source: List[str], elem: str) -> List[str]:
    """
    remove the related member and the next to it
    """
    # return as is if not found
    try:
        elem_idx = source.index(elem)
    except ValueError:
        return source

    return source[:elem_idx] + source[elem_idx+2:]


def dict_merge(dict1: KV, dict2: KV) -> KV:
    """
    deep merge between dict1 and dicgt2
    """
    result = dict1.copy()
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = dict_merge(result[key], value)
        else:
            result[key] = value

    return result


home_dir_re = re.compile(r"^(~|\$HOME|\$\{HOME\})")


def ensure_home_dir_special_prefix(path: str) -> str:
    """
    ensure the path that begins with ~, $HOME, ${HOME}
    are converted with the real home directory
    """
    return home_dir_re.sub(os.environ["HOME"], path)


def file_hash(fpath: str, max_chars: Optional[int] = None) -> str:
    """
    calculate SHA256 of given text, default will return as 64 chars but it can be limited
    """
    with open(fpath, "r") as fh:
        hex_digest = sha256(fh.read().encode("utf-8")).hexdigest()

        return hex_digest[:max_chars] if max_chars is not None else hex_digest


def flatten_list(items: List[Any]) -> List[Any]:
    """
    Recursively flatten a nested list into a single list.
    """
    result = []
    for item in items:
        if isinstance(item, list):
            result.extend(flatten_list(item))
        else:
            result.append(item)
    return result


def fetch_prop(path: str, obj: Union[object, List[Any], KV], separator: str=".") -> Any:
    """
    Fetch a nested property from an object or dictionary using the given separator char.
    Supports dicts, lists, and normal Python objects.
    """
    keys = path.split(separator)
    current = obj

    for key in keys:
        if isinstance(current, dict):
            if key not in current:
                raise KeyError(f"Key `{key}` not found in dict at `{path}`")
            current = current[key]
        elif isinstance(current, list):
            try:
                index = int(key)
                current = current[index]
            except (ValueError, IndexError):
                raise KeyError(f"Invalid list index `{key}` in path `{path}`")
        else:
            # Handle Python object
            if not hasattr(current, key):
                raise KeyError(f"Attribute `{key}` not found in object at `{path}`")
            current = getattr(current, key)

    return current
