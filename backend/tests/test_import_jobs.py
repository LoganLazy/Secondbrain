import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from app.import_jobs import ImportJobs


class ImportJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'jobs.db'
        self.calls = []
        def process(item, kb, progress):
            self.calls.append((item['file'], kb))
            progress('parsing')
            return {'id':1, 'title':item['file']}
        self.process = process
        self.jobs = ImportJobs(self.path, self.process)

    def tearDown(self):
        self.jobs.close()
        self.temp.cleanup()

    def wait(self):
        self.jobs._thread.join(4)
        self.assertFalse(self.jobs._running)

    def test_results_persist_and_kbs_are_isolated(self):
        job = self.jobs.create('kb_a', [{'file':'a.txt','path':'/private/a.txt'}])
        self.wait()
        self.assertEqual(self.jobs.list('kb_b'), [])
        self.assertNotIn('path', self.jobs.list('kb_a')[0]['items'][0])
        with self.assertRaises(ValueError):
            self.jobs.control(job['id'], 'kb_b', 'retry')
        self.jobs.close()
        self.jobs = ImportJobs(self.path, self.process)
        self.assertEqual(self.jobs.list('kb_a')[0]['state'], 'completed')

    def test_stop_resume_and_restart_recovery(self):
        entered, release = threading.Event(), threading.Event()
        def slow(item, kb, progress):
            entered.set(); release.wait(3)
            return self.process(item, kb, progress)
        self.jobs.close()
        self.jobs = ImportJobs(self.path, slow)
        job = self.jobs.create('default', [{'file':str(i),'path':str(i)} for i in range(3)])
        self.assertTrue(entered.wait(2))
        self.jobs.control(job['id'], 'default', 'stop')
        release.set(); self.wait()
        self.assertEqual(self.jobs.list('default')[0]['done'], 1)
        self.assertEqual(self.jobs.list('default')[0]['state'], 'stopped')
        self.jobs.close()
        with sqlite3.connect(self.path) as conn:
            conn.execute("UPDATE jobs SET state='running'")
        self.jobs = ImportJobs(self.path, self.process)
        self.assertEqual(self.jobs.list('default')[0]['state'], 'interrupted')
        self.assertEqual(len(self.calls), 1)
        self.jobs.control(job['id'], 'default', 'resume'); self.wait()
        self.assertEqual(self.jobs.list('default')[0]['done'], 3)
        self.assertEqual(len(self.calls), 3)

    def test_failed_files_retry_without_successful_files(self):
        failed_once = set()
        def flaky(item, kb, progress):
            if item['file'] == 'bad' and not failed_once:
                failed_once.add('bad')
                raise ValueError('parse failed')
            return self.process(item, kb, progress)
        self.jobs.close()
        self.jobs = ImportJobs(self.path, flaky)
        job = self.jobs.create('kb', [{'file':'good','path':'g'}, {'file':'bad','path':'b'}])
        self.wait()
        retried = self.jobs.control(job['id'], 'kb', 'retry')
        self.wait()
        self.assertNotEqual(retried['id'], job['id'])
        self.assertEqual(self.jobs.list('kb')[0]['total'], 1)
        self.assertEqual(self.calls, [('good','kb'),('bad','kb')])
