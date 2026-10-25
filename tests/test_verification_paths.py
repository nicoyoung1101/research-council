import tempfile
import unittest
from pathlib import Path
from verification_paths import report_hash


class ReportPathsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        (self.root/'logs').mkdir();(self.root/'logs/a.log').touch();self.h='a'*64
    def tearDown(self):self.tmp.cleanup()
    def parse(self,name):return report_hash('- '+name+' '+self.h,[self.root])
    def test_chinese_zero_byte_annotation_is_not_filename(self):
        self.assertEqual(self.parse('logs/a.log（0 字节）'),(self.root/'logs/a.log',self.h))
        self.assertEqual(self.parse('logs/a.log (0 bytes)'),(self.root/'logs/a.log',self.h))
    def test_quoted_names_can_contain_spaces_and_parentheses(self):
        name='logs/file (中文).log';(self.root/name).touch()
        self.assertEqual(self.parse('`'+name+'`（0 字节）')[0],self.root/name)
    def test_missing_and_ambiguous_paths_are_not_silently_skipped(self):
        with self.assertRaises(ValueError):self.parse('logs/missing.log（0 字节）')
        (self.root/'logs/a.log（0 字节）').touch()
        with self.assertRaises(ValueError):self.parse('logs/a.log（0 字节）')
    def test_traversal_and_symlink_escape_are_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            target=Path(outside)/'secret';target.touch();(self.root/'escape').symlink_to(target)
            for name in ('escape',str(target),'../'+Path(outside).name+'/secret'):
                with self.subTest(name=name),self.assertRaises(ValueError):self.parse(name)
    def test_plain_non_hash_prose_is_not_an_entry(self):
        self.assertIsNone(report_hash('Not a hash entry',[self.root]))
