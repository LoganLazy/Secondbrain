import io
import json
import os
import sqlite3
import stat
import tempfile
import unittest
import zipfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from app import backup, config, db, restore


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / 'backend'
        self.data = self.base / 'data'
        self.uploads = self.data / 'uploads'
        self.uploads.mkdir(parents=True)
        self.stack = ExitStack()
        for key, value in {'BASE_DIR':self.base, 'DATA_DIR':self.data, 'UPLOAD_DIR':self.uploads,
                           'SETTINGS_FILE':self.data / 'settings.json', 'INBOX_DIR':self.base / 'inbox'}.items():
            self.stack.enter_context(patch.object(config, key, value))
        self.stack.enter_context(patch.object(config, 'reload'))
        self.old_conn = db._conn
        db._conn = None
        source = self.uploads / 'default' / 'note.txt'
        source.parent.mkdir()
        source.write_text('原始资料', encoding='utf-8')
        db.get().execute('INSERT INTO docs(filename,title,file_hash,file_path,kb_id) VALUES(?,?,?,?,?)',
                         ('note.txt', '资料', 'hash', str(source), 'default'))
        db.get().commit()
        config.SETTINGS_FILE.write_text(json.dumps({'DEEPSEEK_KEY':'backup-secret'}))
        self.archive = backup.create_backup()

    def tearDown(self):
        if db._conn is not None:
            db._conn.close()
        db._conn = self.old_conn
        backup.cleanup_backup(self.archive)
        self.stack.close()
        self.temp.cleanup()

    def preview(self, archive=None):
        with open(archive or self.archive, 'rb') as source:
            return restore.preview_restore(source)

    def close_db(self):
        db._conn.close(); db._conn = None

    def test_preview_no_data_change_and_no_secret_in_response(self):
        result = self.preview()
        self.assertEqual(result['docs'], 1)
        self.assertNotIn('backup-secret', json.dumps(result))
        self.assertFalse(restore.pending_path().exists())
        self.assertEqual(db.get().execute('SELECT COUNT(*) FROM docs').fetchone()[0], 1)

    def settings_archive(self, settings):
        stream = io.BytesIO()
        with zipfile.ZipFile(self.archive) as original, zipfile.ZipFile(stream, 'w') as target:
            manifest = json.loads(original.read('Nebula-Memory/backup-manifest.json'))
            manifest['format'] = 1
            manifest.pop('checksums')
            for name in original.namelist():
                if name.endswith('settings.json'):
                    target.writestr(name, json.dumps(settings))
                elif not name.endswith('backup-manifest.json'):
                    target.writestr(name, original.read(name))
            target.writestr('Nebula-Memory/backup-manifest.json', json.dumps(manifest))
        return stream

    def test_legacy_numeric_configuration_is_normalized_during_preview(self):
        result = restore.preview_restore(self.settings_archive({
            'NET_MODE':'offline', 'FC_MASTER_BOX':'3', 'FC_INTERVALS':'0,1,2,4,7'}))
        staged = json.loads((restore.stage_dir(result['preview_id']) / 'data/settings.json').read_text())
        self.assertIs(type(staged['FC_MASTER_BOX']), int)
        self.assertEqual(staged['NET_MODE'], 'offline')
        self.assertEqual(json.loads(config.SETTINGS_FILE.read_text()), {'DEEPSEEK_KEY':'backup-secret'})

    def test_semantically_invalid_backup_configuration_is_rejected(self):
        for settings in ({'NET_MODE':'invalid'}, {'CHUNK_SIZE':64, 'CHUNK_OVERLAP':80},
                         {'CHAT_BASE_URL':'https://example.test?key=secret'}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                restore.preview_restore(self.settings_archive(settings))
        self.assertEqual(db.get().execute('SELECT COUNT(*) FROM docs').fetchone()[0], 1)

    def test_restore_remaps_paths_preserves_current_config_and_old_data(self):
        result = self.preview()
        db.get().execute("INSERT INTO memories(content) VALUES('new local memory')")
        db.get().commit()
        config.SETTINGS_FILE.write_text(json.dumps({'DEEPSEEK_KEY':'current-secret'}))
        restore.queue_restore(result['preview_id'])
        self.close_db()
        restore.activate_pending()
        row = db.get().execute('SELECT file_path FROM docs').fetchone()
        self.assertEqual(Path(row['file_path']).read_text(), '原始资料')
        self.assertEqual(db.get().execute('SELECT COUNT(*) FROM memories').fetchone()[0], 0)
        self.assertEqual(json.loads(config.SETTINGS_FILE.read_text())['DEEPSEEK_KEY'], 'current-secret')
        report = restore.restore_status()['report']
        old = sqlite3.connect(Path(report['previous_data']) / 'memory.db')
        self.assertEqual(old.execute('SELECT COUNT(*) FROM memories').fetchone()[0], 1)
        old.close()
        self.assertFalse(restore.pending_path().exists())

    def test_opt_in_restore_settings(self):
        result = self.preview()
        config.SETTINGS_FILE.write_text('{}')
        restore.queue_restore(result['preview_id'], True)
        self.close_db()
        restore.activate_pending()
        self.assertEqual(json.loads(config.SETTINGS_FILE.read_text())['DEEPSEEK_KEY'], 'backup-secret')

    def test_restore_keeps_flashcard_source_version_and_review_progress(self):
        db.get().execute('INSERT INTO flashcards(doc_id,q,a,kb_id,source_hash,reviews,wrongs,box,last_result) VALUES(?,?,?,?,?,?,?,?,?)',
                         (1,'question','answer','default','hash',3,1,2,'correct'))
        db.get().commit()
        archive = backup.create_backup()
        try:
            result = self.preview(archive)
            restore.queue_restore(result['preview_id'])
            self.close_db()
            restore.activate_pending()
            row = db.get().execute('SELECT * FROM flashcards').fetchone()
            self.assertEqual(row['source_hash'], 'hash')
            self.assertEqual(row['reviews'], 3)
            self.assertEqual(row['wrongs'], 1)
            self.assertEqual(row['box'], 2)
        finally:
            backup.cleanup_backup(archive)

    def test_interrupted_directory_swap_can_finish_after_restart(self):
        result = self.preview()
        restore.queue_restore(result['preview_id'])
        self.close_db()
        original_replace = os.replace
        def interrupted(source, target):
            if Path(source).name == 'data' and Path(source).parent.name == result['preview_id']:
                raise OSError('simulated power loss')
            return original_replace(source, target)
        with patch.object(restore.os, 'replace', side_effect=interrupted), self.assertRaises(OSError):
            restore.activate_pending()
        (self.data / 'uploads').mkdir(parents=True)
        restore.activate_pending()
        self.assertEqual(db.get().execute('SELECT COUNT(*) FROM docs').fetchone()[0], 1)

    def test_cancel_does_not_replace_data(self):
        result = self.preview()
        restore.queue_restore(result['preview_id'])
        restore.cancel_restore()
        self.assertFalse(restore.pending_path().exists())
        self.assertTrue((self.uploads / 'default' / 'note.txt').is_file())

    def test_tampered_preview_rejected_before_queue(self):
        result = self.preview()
        (restore.stage_dir(result['preview_id']) / 'data' / 'uploads/default/note.txt').write_text('tampered')
        with self.assertRaisesRegex(ValueError, '校验失败'):
            restore.queue_restore(result['preview_id'])
        self.assertFalse(restore.pending_path().exists())

    def test_unsafe_zip_paths_duplicates_and_symlinks_rejected(self):
        for name in ('../outside', '/absolute', 'Nebula-Memory/uploads/../../outside', r'Nebula-Memory\outside', 'C:/outside'):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                archive.writestr(name, 'invalid')
            with self.assertRaises(ValueError):
                restore.preview_restore(stream)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            item = zipfile.ZipInfo('Nebula-Memory/uploads/link.txt')
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(item, '/etc/passwd')
        with self.assertRaises(ValueError):
            restore.preview_restore(stream)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('Nebula-Memory/a', 'a')
            archive.writestr('Nebula-Memory/A', 'b')
        with self.assertRaises(ValueError):
            restore.preview_restore(stream)

    def test_archive_limits_and_invalid_database(self):
        with patch.object(restore, 'MAX_EXPANDED_BYTES', 5), self.assertRaises(ValueError):
            self.preview()
        with patch.object(restore, 'MAX_ARCHIVE_BYTES', 5), self.assertRaises(ValueError):
            self.preview()
        self.assertEqual(db.get().execute('SELECT COUNT(*) FROM docs').fetchone()[0], 1)

    def test_backup_contains_inbox_originals_and_manifest_mapping(self):
        inbox = config.INBOX_DIR / '工作' / '已导入'
        inbox.mkdir(parents=True)
        source = inbox / 'archived.txt'
        source.write_text('自动导入资料')
        db.get().execute('INSERT INTO docs(filename,file_hash,file_path,kb_id) VALUES(?,?,?,?)',
                         ('inbox.txt', 'inbox-hash', str(source), 'default'))
        db.get().commit()
        archive = backup.create_backup()
        try:
            with zipfile.ZipFile(archive) as zipped:
                manifest = json.loads(zipped.read('Nebula-Memory/backup-manifest.json'))
                self.assertEqual(len(manifest['document_files']), 2)
                self.assertEqual(manifest['missing_originals'], [])
        finally:
            backup.cleanup_backup(archive)

    def test_corrupt_database_and_missing_original_rejected(self):
        for corrupt_db in (True, False):
            stream = io.BytesIO()
            with zipfile.ZipFile(self.archive) as original, zipfile.ZipFile(stream, 'w') as target:
                manifest = json.loads(original.read('Nebula-Memory/backup-manifest.json'))
                manifest['format'] = 1
                manifest.pop('checksums')
                for name in original.namelist():
                    if name.endswith('backup-manifest.json'):
                        continue
                    if not corrupt_db and '/uploads/' in name:
                        continue
                    target.writestr(name, b'not a database' if corrupt_db and name.endswith('memory.db') else original.read(name))
                target.writestr('Nebula-Memory/backup-manifest.json', json.dumps(manifest))
            with self.assertRaises((ValueError, sqlite3.DatabaseError)):
                restore.preview_restore(stream)
        self.assertEqual(db.get().execute('SELECT COUNT(*) FROM docs').fetchone()[0], 1)
