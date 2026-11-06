import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.backup import cleanup_backup, create_backup


class BackupTests(unittest.TestCase):
    def test_backup_contains_consistent_database_originals_and_manifest(self):
        with tempfile.TemporaryDirectory() as source:
            source_path = Path(source)
            uploads = source_path / "uploads"
            uploads.mkdir()
            (uploads / "note.txt").write_text("knowledge", encoding="utf-8")
            settings = source_path / "settings.json"
            settings.write_text('{"DEEPSEEK_KEY":"secret"}', encoding="utf-8")
            conn = sqlite3.connect(":memory:")
            conn.execute("CREATE TABLE docs(id INTEGER, title TEXT)")
            conn.execute("INSERT INTO docs VALUES(1, 'test')")
            conn.commit()
            with (
                patch("app.backup.config.UPLOAD_DIR", uploads),
                patch("app.backup.config.SETTINGS_FILE", settings),
                patch("app.backup.db.get", return_value=conn),
            ):
                archive = create_backup()
            try:
                with zipfile.ZipFile(archive) as zf:
                    names = set(zf.namelist())
                    self.assertIn("Nebula-Memory/memory.db", names)
                    self.assertIn("Nebula-Memory/uploads/note.txt", names)
                    self.assertIn("Nebula-Memory/settings.json", names)
                    manifest = json.loads(
                        zf.read("Nebula-Memory/backup-manifest.json")
                    )
                    self.assertEqual(manifest["product"], "Nebula Memory")
                    self.assertFalse(manifest["vectors_included"])
            finally:
                cleanup_backup(archive)
                conn.close()


if __name__ == "__main__":
    unittest.main()
