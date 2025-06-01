import logging
import subprocess
import os
import re
from hashlib import sha256
from typing import Any, Union, Dict, List, Optional


KV = Dict[str, Any]
CONFIG_PATH_ENV = "SNDK_CFG"
SANDBOX_DEBUG_ENV = "SNDK_DEBUG"


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
        command = " ".join(command)

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
