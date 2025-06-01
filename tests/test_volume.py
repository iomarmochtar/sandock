import os
import unittest
import json
from pathlib import Path
from typing import List
from inspect import cleandoc
from unittest import TestCase, mock
from unittest.mock import MagicMock, PropertyMock, patch
from datetime import datetime
from sandock.exceptions import SandboxVolumeExec, SandboxVolumeNotFound
from sandock.volume import (
    BackupSnapshot,
    BackupMgr,
    VolumeMgr,
)
from helpers import dummy_main_cfg, mock_shell_exec


restic_snapshot_output = '{"short_id":"123abc","paths":["/source_vol_abc_vol"],"summary":{"total_bytes_processed":72168670},"time":"2025-03-10T02:16:48.567374338Z"}'
# representing the above snapshot output
sample_snapshot_obj = BackupSnapshot.from_raw(data=json.loads(restic_snapshot_output))
restic_snapshots_output = f"[{restic_snapshot_output}]"


class TestBackupSnapshot(TestCase):
    def test_properties(self) -> None:
        o = BackupSnapshot(
            id="5d3ca8bf",
            backup_time=datetime.now(),
            path="/source_vol_go_cache",
            bytes=72168670,
        )

        self.assertEqual(o.vol_name, "go_cache")
        self.assertEqual(o.size, "68.83 MB")

    def test_from_raw(self) -> None:
        raw_data = dict(
            short_id="5d3ca8bf",
            paths=["/source_vol_mysh_profile"],
            summary=dict(total_bytes_processed=72168670),
            time="2025-03-10T02:16:48.567374338Z",
        )

        o = BackupSnapshot.from_raw(data=raw_data)
        self.assertEqual(o.vol_name, "mysh_profile")
        self.assertEqual(o.path, "/source_vol_mysh_profile")
        self.assertEqual(o.id, "5d3ca8bf")
        self.assertEqual(o.bytes, 72168670)
        self.assertEqual(o.size, "68.83 MB")


class TestVolumeManager(TestCase):

    def obj(self, **kwargs) -> VolumeMgr:
        kwargs = dict(cfg=dummy_main_cfg()) | kwargs
        return VolumeMgr(**kwargs)

    def test_volume_list(self) -> None:
        with mock_shell_exec() as mock_sh:
            mock_sh.return_value.stdout = cleandoc(
                """
            {"Name":"vol_one"}
            {"Name":"vol_two"}
            """
            )
            self.assertEqual(
                self.obj().volume_list(label_filters=dict(label1="ok", label2="ok")),
                [{"Name": "vol_one"}, {"Name": "vol_two"}],
            )
            mock_sh.assert_called_once()
            self.assertEqual(
                mock_sh.call_args_list[0].args[0],
                "docker volume ls --format=json --filter=label=label1='ok' --filter=label=label2='ok'",
            )
    
    @patch.object(VolumeMgr, "volume_list")
    def test_created_by_sandock(self, mock_volume_list: MagicMock) -> None:
        o = self.obj()
        o.created_by_sandock
        mock_volume_list.assert_called_once_with(label_filters={"created_by.sandock": "true"})

    def test_vol_exists(self) -> None:
        o = self.obj()
        se = [
            dict(returncode=0, stdout='[{"Name":"vol_1"}]'),
            dict(
                returncode=1,
                stderr="[]\nError response from daemon: get myhome : no such volume",
            ),
        ]
        with mock_shell_exec(side_effects=se) as mock_sh:
            self.assertTrue(
                o.vol_exists(name="vol_1"),
                msg="volume exists if it's returning with code 0",
            )
            self.assertFalse(
                o.vol_exists(name="vol_23"),
                msg="other than code 0 treat as volume not exists",
            )

            self.assertEqual(mock_sh.call_count, 2)

    def test_file_exists_in_vol(self) -> None:
        gen_expected_cmd = lambda vol_name: (
            f"docker run -it --rm --entrypoint=test -v {vol_name}:/check_vol docker.io/library/ubuntu:22.04 -f /check_vol/check.txt"
        )
        o = self.obj()
        se = [
            dict(returncode=0),  # vol1 found
            dict(returncode=1),  # vol2 not found
        ]

        with mock_shell_exec(side_effects=se) as mock_sh:
            self.assertTrue(
                o.file_exists_in_vol(name="vol_1", path="check.txt"),
            )
            self.assertFalse(
                o.file_exists_in_vol(name="vol_2", path="check.txt"),
                msg="other than code 0 treat as volume not exists",
            )

            self.assertEqual(mock_sh.call_count, 2)
            self.assertListEqual(
                [x[0][0] for x in mock_sh.call_args_list],
                [gen_expected_cmd(x) for x in ["vol_1", "vol_2"]],
            )

    def test_backup(self) -> None:
        # set with no password to preventing password prompt
        cfg = dummy_main_cfg(backup=dict(no_password=True))
        self.assertIsInstance(self.obj(cfg=cfg).backup, BackupMgr)


class TestBackupMgr(TestCase):
    maxDiff = 10_000

    def obj(self, **backup_conf_kwargs) -> BackupMgr:
        # set password default to disable in preventing password prompt during the test
        kwargs = dict(
            cfg=dummy_main_cfg(backup=dict(no_password=True) | backup_conf_kwargs)
        )
        return BackupMgr(vol_mgr=VolumeMgr(**kwargs))

    @patch("sandock.volume.getpass")
    def test_init_backup_password_prompt(self, mock_getpass: MagicMock) -> None:
        mock_getpass.return_value = "s3cret souce"
        # default configuration is set by backup password required
        o = self.obj(no_password=False)
        mock_getpass.assert_called_once()
        self.assertEqual(o._backup_password, "s3cret souce")

        mock_getpass.reset_mock()
        o = self.obj(no_password=True)
        self.assertIsNone(o._backup_password)
        mock_getpass.assert_not_called()

    def test_backup_dir(self) -> None:
        with mock.patch.dict(os.environ, dict(HOME="/home/user1")):
            self.assertEqual(
                self.obj().backup_dir,
                "/home/user1/.sandock_vol_backup",
                msg="default backup directory supported by using home directory character",
            )
            self.assertEqual(
                self.obj(path=dict(default="~/another/path")).backup_dir,
                "/home/user1/another/path",
                msg="using another home directory pattern",
            )
            self.assertEqual(
                self.obj(path=dict(default="/another/path")).backup_dir,
                "/another/path",
                msg="direct pointing to specific path",
            )

    def test_restic_run_cmd_no_password(self) -> None:
        backup_conf = dict(path=dict(default="/another/path"), no_password=True)
        self.assertListEqual(
            self.obj(**backup_conf).restic_run_cmd(restic_args=["init"]),
            [
                "docker",
                "run",
                "-it",
                "--rm",
                "--hostname=sandock",
                "--entrypoint=restic",
                "-v /another/path:/backup_repo",
                "restic/restic:0.18.0",
                "--repo=/backup_repo",
                "--compression=auto",
                "--no-cache",
                "--insecure-no-password",
                "init",
            ],
            msg="no password provided",
        )

    @patch("sandock.volume.getpass")
    def test_restic_run_cmd_set_password(self, mock_getpass: mock.MagicMock) -> None:
        mock_getpass.return_value = "s3cret"
        backup_conf = dict(path=dict(default="/another/path"), no_password=False)
        self.assertListEqual(
            self.obj(**backup_conf).restic_run_cmd(restic_args=["init"]),
            [
                "docker",
                "run",
                "-it",
                "--rm",
                "--hostname=sandock",
                "--entrypoint=restic",
                "-v /another/path:/backup_repo",
                "-e RESTIC_PASSWORD='s3cret'",
                "restic/restic:0.18.0",
                "--repo=/backup_repo",
                "--compression=auto",
                "--no-cache",
                "init",
            ],
            msg="password will be provided by env var to restic container",
        )

        mock_getpass.assert_called_once()

    def test_ensure_restic_repository(self) -> None:
        # backup repository exists
        with mock_shell_exec() as wsh:
            o = self.obj()
            with mock.patch.object(Path, "exists") as mock_path_exists:
                mock_path_exists.return_value = True
                o.ensure_restic_repository()
                wsh.assert_not_called()

        # initialized backup repository when it's not exists
        with mock_shell_exec() as wsh:
            o = self.obj()
            with mock.patch.object(Path, "exists") as mock_path_exists:
                with mock.patch.object(o, "restic_run_cmd") as mock_restic_run_cmd:
                    mock_path_exists.return_value = False
                    o.ensure_restic_repository()

                    mock_restic_run_cmd.assert_called_once_with(restic_args=["init"])
                    wsh.assert_called_once()

    @patch.object(BackupMgr, "ensure_restic_repository")
    @patch.object(VolumeMgr, "file_exists_in_vol")
    @patch.dict(os.environ, dict(HOME="/home/user1"))
    def test_create(
        self, mock_file_exists_in_vol: MagicMock, m_ensure_restic_repo: MagicMock
    ) -> None:
        def gen_expected_cmd(vol_name: str, exclude_params: List[str] = []) -> str:
            mount_source = f"/source_vol_{vol_name}"
            return (
                f"docker run -it --rm --hostname=sandock "
                "--entrypoint=restic -v /home/user1/.sandock_vol_backup:/backup_repo "
                f"-v {vol_name}:{mount_source}:ro restic/restic:0.18.0 --repo=/backup_repo "
                f"--compression=auto --no-cache --insecure-no-password backup "
                f'--skip-if-unchanged --group-by=paths {("" if not vol_name in exclude_params else f"--exclude-file={mount_source}/.sandock_backup_ignore")} '
                f"{mount_source}"
            )

        mock_file_exists_in_vol.side_effect = [
            False,  # vol1
            True,  # vol2
            False,  # vol3
        ]

        with mock_shell_exec() as msh:
            o = self.obj(volume_excludes=["vol_excluded_config1"])
            o.create(
                targets=[
                    "vol1",
                    "vol2",
                    "vol_excluded1",
                    "vol3",
                    "vol_excluded_config1",
                ],
                excludes=["vol_excluded1"],
            )

            m_ensure_restic_repo.assert_called_once()
            self.assertEqual(msh.call_count, 3)

            self.assertListEqual(
                [x[0][0] for x in msh.call_args_list],
                [
                    gen_expected_cmd(x, exclude_params=["vol2"])
                    for x in ["vol1", "vol2", "vol3"]
                ],
                msg="only vol2 that will set by param exclude file",
            )

    @patch.object(BackupMgr, "restic_run_cmd")
    @patch.object(BackupMgr, "backup_config", new_callable=PropertyMock)
    @patch.dict(os.environ, dict(HOME="/home/user1"))
    def test_snapshot_list(
        self, mock_path_exists: PropertyMock, mock_restic_run_cmd: mock.MagicMock
    ) -> None:
        path_mock = MagicMock()
        mock_path_exists.return_value = path_mock

        with self.assertRaisesRegex(
            SandboxVolumeExec,
            "backup repository \(/home\/user1\/\.sandock_vol_backup\) is not initialized",
        ):
            path_mock.exists.return_value = False
            self.obj().snapshot_list()

        # next on the backup repository is exists
        path_mock.exists.return_value = True

        # all volume name with only the latest snapshot
        with mock_shell_exec() as msh:
            msh.return_value.stdout = restic_snapshots_output
            mock_restic_run_cmd.return_value = ["restic", "cmd"]
            self.assertListEqual(self.obj().snapshot_list(), [sample_snapshot_obj])

            msh.assert_called_once()
            self.assertEqual(msh.call_args[0][0], "restic cmd --latest=1")
            mock_restic_run_cmd.assert_called_once_with(
                restic_args=["snapshots", "--json"]
            )

        # specific volume name with shown all snapshots
        mock_restic_run_cmd.reset_mock()
        with mock_shell_exec() as msh:
            msh.return_value.stdout = restic_snapshots_output
            mock_restic_run_cmd.return_value = ["restic", "cmd"]
            self.assertListEqual(
                self.obj().snapshot_list(specific_volname="abc_vol", show_all=True),
                [sample_snapshot_obj],
            )

            msh.assert_called_once()
            self.assertEqual(
                msh.call_args[0][0], "restic cmd --path=/source_vol_abc_vol"
            )
            mock_restic_run_cmd.assert_called_once_with(
                restic_args=["snapshots", "--json"]
            )

    @patch.object(BackupMgr, "restic_run_cmd")
    def test_get_snapshot_by(self, mock_restic_run_cmd: mock.MagicMock) -> None:
        restic_not_found_snapshot = "no matching ID found for prefix 123abc"
        with mock_shell_exec() as msh:
            msh.return_value.stdout = restic_not_found_snapshot
            with self.assertRaises(SandboxVolumeNotFound):
                self.assertIsNone(self.obj().get_snapshot_by(id="123abc"))

            mock_restic_run_cmd.assert_called_once_with(
                restic_args=["snapshots", "123abc", "--json"]
            )
            msh.assert_called_once()

        mock_restic_run_cmd.reset_mock()
        # snapshot found
        with mock_shell_exec() as msh:
            msh.return_value.stdout = restic_snapshots_output

            self.assertEqual(
                self.obj().get_snapshot_by(id="123abc"),
                sample_snapshot_obj,
                msg="returning backup snapshot object",
            )
            mock_restic_run_cmd.assert_called_once_with(
                restic_args=["snapshots", "123abc", "--json"]
            )
            msh.assert_called_once()

    @patch.object(VolumeMgr, "vol_exists")
    def test_restore_volume_exists_not_force(self, mock_vol_exists: MagicMock) -> None:
        # not forced (default) and volume is exists
        with self.assertRaisesRegex(
            SandboxVolumeExec,
            "volume by name `target_vol` is already exists, try to set force parameter to enforce it",
        ):
            mock_vol_exists.return_value = True
            self.obj().restore(snapshot="backup_snapshot_1", target_volume="target_vol")

    @patch.object(BackupMgr, "restic_run_cmd")
    @patch.object(BackupMgr, "get_snapshot_by")
    def test_restore_volume_not_exists(
        self, mock_get_snapshot_by: MagicMock, mock_restic_run_cmd: MagicMock
    ) -> None:

        with mock_shell_exec() as msh:
            mock_get_snapshot_by.return_value = sample_snapshot_obj
            mock_restic_run_cmd.return_value = ["restic_cmd"]
            self.obj().restore(
                force=True,
                snapshot="backup_snapshot_1",
                target_volume="target_vol",
                excludes=["expath1", "expath2"],
                overwrite="always",
            )

            msh.called_once()
            self.assertEqual(
                msh.call_args[0][0],
                "restic_cmd --exclude=expath1 --exclude=expath2 --overwrite=always",
            )
            mock_get_snapshot_by.assert_called_once_with(id="backup_snapshot_1")
            mock_restic_run_cmd.assert_called_once_with(
                extra_docker_params=["-v target_vol:/restore_vol_target_vol"],
                restic_args=[
                    "restore",
                    "123abc:/source_vol_abc_vol",
                    "--target=/restore_vol_target_vol",
                ],
            )


if __name__ == "__main__":
    unittest.main()
