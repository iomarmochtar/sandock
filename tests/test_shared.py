import unittest
import tempfile
import sys
import os
from unittest import mock
from inspect import cleandoc
from subprocess import CalledProcessError
from sandock import shared
from helpers import BaseTestCase


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


if __name__ == "__main__":
    unittest.main()
