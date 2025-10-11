import unittest
import tempfile
import sys
import os
from unittest import mock
from inspect import cleandoc
from subprocess import CalledProcessError
from sandock import shared
from helpers import dummy_main_cfg, BaseTestCase


class RunShellTest(BaseTestCase):
    def test_capture_stdout_stderr_in_check_err(self) -> None:
        """
        default check_err in true
        """
        test_script = cleandoc(
            """
        import sys

        sys.stdout.write("this is stdout")
        sys.stderr.write("this is stdout")
        sys.exit(2)
        """
        )
        with tempfile.NamedTemporaryFile(mode="w") as fh:
            fh.write(test_script)
            fh.seek(0)

            expected_err = r"error in executing command:.*?stderr: this is stdout, stdout: this is stdout"
            with self.assertRaisesRegex(CalledProcessError, expected_err):
                shared.run_shell(command=f"{sys.executable} {fh.name}")

    def test_capture_err_msg(self) -> None:
        result = shared.run_shell(command="notnotfound", check_err=False)
        self.assertEqual(result.returncode, 127)
        self.assertEqual(result.stdout, "")
        self.assertRegex(result.stderr, r"notnotfound.*?not found")

    def test_piped_command(self) -> None:
        result = shared.run_shell(command="echo 'lazy fox' | sed 's/lazy/smart/g'")
        self.assertEqual(result.stdout, "smart fox\n")

    @mock.patch.dict(os.environ, dict(HOME="/home/sweet_home"))
    def test_ensure_home_dir_special_prefix(self) -> None:
        self.assertEqual(
            shared.ensure_home_dir_special_prefix(path="~/path/to.yml"),
            "/home/sweet_home/path/to.yml",
        )

        self.assertEqual(
            shared.ensure_home_dir_special_prefix(path="$HOME/path/to.yml"),
            "/home/sweet_home/path/to.yml",
        )

        self.assertEqual(
            shared.ensure_home_dir_special_prefix(path="${HOME}/path/to.yml"),
            "/home/sweet_home/path/to.yml",
        )

class UtilitiesTest(BaseTestCase):
    sample_dict = {
        "satu": {
            "sub1_satu": "hello",
            "sub2_satu": "word",
        },
        "dua": [
            "elem1",
            "elem2",
        ]
    }

    sample_obj = dummy_main_cfg(program_kwargs=dict(
        volumes=[
            "temp1:/opt/temp1",
            "temp2:/opt/temp2",
        ]
    ))

    def test_flatten_list(self) -> None:
        l1 = [
            "first:top",
            "first:bottom",
            [
                "sub1:top",
                "sub1:bottom"
            ]
        ]

        l2 = [
            "second:top",
            l1,
            "second:bottom"
        ]

        self.assertListEqual(shared.flatten_list(l2), [
            "second:top",
            "first:top",
            "first:bottom",
            "sub1:top",
            "sub1:bottom",
            "second:bottom"
        ])

    def test_fetch_prop_dict(self) -> None:
        self.assertEqual(
            shared.fetch_prop(path="satu.sub1_satu", obj=self.sample_dict),
            "hello",
            msg="fetch value"
        )

        with self.assertRaisesRegex(
            KeyError, "Key `sub1_not_exists` not found in dict at `satu.sub1_not_exists`",
            msg="key not found"):
            shared.fetch_prop(path="satu.sub1_not_exists", obj=self.sample_dict)
            

    def test_fetch_prop_list(self) -> None:
        self.assertEqual(
            shared.fetch_prop(path="dua.1", obj=self.sample_dict),
            "elem2",
            msg="fetch list"
        )

        with self.assertRaisesRegex(
            KeyError, "Invalid list index `10` in path `dua.10`",
            msg="index not found"):
            shared.fetch_prop(path="dua.10", obj=self.sample_dict)
    
    def test_fetch_prop_obj(self) -> None:
        self.assertEqual(
            shared.fetch_prop(path="programs.pydev.image", obj=self.sample_obj),
            "python:3.11",
        )

        self.assertListEqual(
            shared.fetch_prop(path="programs.pydev.volumes", obj=self.sample_obj),
            [
                "temp1:/opt/temp1",
                "temp2:/opt/temp2",
            ]
        )

        with self.assertRaisesRegex(
            KeyError, "Attribute `not_exists` not found in object at `programs.pydev.not_exists`"):
            shared.fetch_prop(path="programs.pydev.not_exists", obj=self.sample_obj)

if __name__ == "__main__":
    unittest.main()
