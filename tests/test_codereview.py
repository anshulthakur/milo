import os
import unittest
from pathlib import Path
from milo.codereview import review_path

class TestCodeReview(unittest.TestCase):

    def setUp(self):
        self.test_repo_path = Path('tests/tmp/test_repo').resolve()

    def test_review_path(self):
        # Test with a directory
        file_list = review_path([str(self.test_repo_path)])
        expected_files = [
            str(self.test_repo_path / 'file1.py'),
            str(self.test_repo_path / 'file2.c'),
            str(self.test_repo_path / 'file3.h'),
            str(self.test_repo_path / 'subdir' / 'file6.py'),
        ]
        self.assertCountEqual(file_list, expected_files)

    def test_review_path_with_files(self):
        # Test with a mix of files and directories
        paths = [
            str(self.test_repo_path / 'file1.py'),
            str(self.test_repo_path / 'subdir'),
            str(self.test_repo_path / 'file4.txt'), # unsupported
        ]
        file_list = review_path(paths)
        expected_files = [
            str(self.test_repo_path / 'file1.py'),
            str(self.test_repo_path / 'subdir' / 'file6.py'),
        ]
        self.assertCountEqual(file_list, expected_files)

    def test_review_path_unsupported(self):
        # Test with only unsupported files
        paths = [str(self.test_repo_path / 'file4.txt')]
        file_list = review_path(paths)
        self.assertEqual(len(file_list), 0)

if __name__ == '__main__':
    unittest.main()
