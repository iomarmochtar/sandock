from unittest import main as unittest_main, TestCase
from sandock.config.backup import Backup, Restic, BackupPath


class TestConfigBackupRestic(TestCase):
    def test_defaults(self) -> None:
        o = Restic()
        self.assertEqual(o.image, "restic/restic:0.18.0")
        self.assertEqual(o.compression, "auto")
        self.assertTrue(o.no_snapshot_unless_changed)
        self.assertListEqual(o.extra_args, [])

    def test_validations(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "unknown compression `unknown` the valid option are auto, off, max",
        ):
            Restic(compression="unknown")


class TestConfigBackupBackupPath(TestCase):
    def test_defaults(self) -> None:
        o = BackupPath()
        self.assertEqual(o.default, "${HOME}/.sandock_vol_backup")


class TestBackup(TestCase):
    def test_defaults(self) -> None:
        o = Backup()
        self.assertIsInstance(o.restic, Restic)
        self.assertIsInstance(o.path, BackupPath)
        self.assertFalse(o.no_password)
        self.assertDictEqual(o.volume_labels, {})
        self.assertListEqual(o.volume_excludes, [])

    def test_props_object_maps(self) -> None:
        o = Backup(restic=dict(compression="max"), path=dict(default="/another/path"))
        self.assertEqual(o.restic.compression, "max")
        self.assertEqual(o.path.default, "/another/path")


if __name__ == "__main__":
    unittest_main()
