import json
from pathlib import Path
import tempfile
import unittest
from desktop.migrate_data import migrate, manifest
from desktop.build_app import FILES


class DesktopDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=self.root/'original';self.source.mkdir()
        (self.source/'state.json').write_text(json.dumps({'sessions':[{'id':'keep','notes':'保留研究笔记'}]},ensure_ascii=False))
        (self.source/'jobs').mkdir()
        (self.source/'jobs'/'job.json').write_text(json.dumps({'status':'complete'}))
        self.dest=self.root/'Application Support'/'Research Council'
        self.backup=self.root/'backup'
    def tearDown(self):self.tmp.cleanup()
    def test_migration_keeps_exact_backup_and_legacy_path(self):
        before=manifest(self.source);result=migrate(self.source,self.dest,self.backup)
        self.assertEqual(result['status'],'migrated');self.assertEqual(manifest(self.dest),before);self.assertEqual(manifest(self.backup),before)
        self.assertTrue(self.source.is_symlink());self.assertEqual(self.source.resolve(),self.dest.resolve())
        (self.source/'notes.md').write_text('New note');self.assertEqual((self.dest/'notes.md').read_text(),'New note')
        self.assertFalse((self.backup/'notes.md').exists())
        self.assertEqual(migrate(self.source,self.dest,self.backup)['status'],'already_migrated')
    def test_existing_destination_is_never_overwritten(self):
        self.dest.mkdir(parents=True);(self.dest/'own.txt').write_text('KEEP')
        with self.assertRaises(ValueError):migrate(self.source,self.dest,self.backup)
        self.assertFalse(self.source.is_symlink());self.assertEqual((self.dest/'own.txt').read_text(),'KEEP')
    def test_running_job_prevents_migration(self):
        (self.source/'jobs'/'job.json').write_text(json.dumps({'status':'running'}))
        with self.assertRaises(ValueError):migrate(self.source,self.dest,self.backup)
        self.assertFalse(self.dest.exists());self.assertTrue(self.source.is_dir())
    def test_workspace_symlinks_are_preserved_without_copying_external_data(self):
        external=self.root/'outside';external.mkdir();(external/'private').write_text('outside')
        (self.source/'linked-workspace').symlink_to(external,target_is_directory=True)
        migrate(self.source,self.dest,self.backup)
        self.assertTrue((self.dest/'linked-workspace').is_symlink());self.assertEqual((external/'private').read_text(),'outside')
    def test_bundle_allowlist_excludes_private_state_and_tests(self):
        self.assertIn('execution-approval.js', FILES)
        self.assertIn('execution_progress.py', FILES)
        self.assertIn('conversation-scroll.js', FILES)
        for name in FILES:
            self.assertFalse(any(x in name for x in ('.research-council','auth.json','.env','tests/','work/')))
            self.assertTrue((Path(__file__).resolve().parents[1]/name).is_file())
        for module in ('native_cli.py','orchestration.py','gemini_guard.py','dynamic-runtime.js'):
            self.assertIn(module,FILES)

if __name__=='__main__':unittest.main()
