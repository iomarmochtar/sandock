import unittest
import os
import sys
import logging
from unittest import mock
from contextlib import contextmanager
from typing import Iterator
from sandock.shared import log
from sandock.config import MainConfig, Program
from sandock.cli import SANDBOX_DEBUG_ENV
from sandock.config import CONFIG_PATH_ENV


def enable_debug() -> None:
    log.setLevel(logging.DEBUG)


@contextmanager
def temp_enable_debug() -> Iterator[None]:
    prev_level = log.level
    enable_debug()
    yield

    log.setLevel(prev_level)


@contextmanager
def mock_yaml_module_not_installed() -> Iterator[None]:
    with mock.patch.dict(sys.modules, dict(yaml=None)):
        yield


def fixture_path(*adds) -> str:
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(tests_dir, "fixtures", *adds)


def dummy_program_cfg(**kwargs) -> Program:
    kwargs = dict(image="python:3.11", exec="python3") | kwargs
    return Program(**kwargs)


def dummy_main_cfg(program_kwargs: dict = {}, **kwargs) -> MainConfig:
    """
    generate sample main configuration with only set the mandatory one
    """
    kwargs.setdefault("programs", dict(pydev=dummy_program_cfg(**program_kwargs)))

    return MainConfig(**kwargs)


class BaseTestCase(unittest.TestCase):

    def setUp(self) -> None:
        # cleanup any env that used in app logic
        for env_var in [SANDBOX_DEBUG_ENV, CONFIG_PATH_ENV]:
            os.environ.pop(env_var, None)
