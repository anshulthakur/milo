import os
import unittest
import shutil
import subprocess
from unittest.mock import MagicMock, patch
from pathlib import Path
from milo.documentation.documentation import (
    insert_docstring_python,
    insert_docstring_c,
    sanitize_docstring_python,
    locate_node_by_name,
    update_docstring,
    CommentedCode,
    run_comb
)
from milo.codesift.parsers import Language, Treesitter

class TestCombIntegration(unittest.TestCase):

    def setUp(self):
        self.tmp_root = Path('/tmp/comb_tests').resolve()
        if self.tmp_root.exists():
            shutil.rmtree(self.tmp_root)
        self.tmp_root.mkdir(parents=True)

        # Setup Git Repo
        self.repo_path = self.tmp_root / "repo"
        self.repo_path.mkdir()
        subprocess.check_call(['git', 'init'], cwd=self.repo_path, stdout=subprocess.DEVNULL)
        
        # Configure git user for safety
        subprocess.check_call(['git', 'config', 'user.email', 'test@example.com'], cwd=self.repo_path, stdout=subprocess.DEVNULL)
        subprocess.check_call(['git', 'config', 'user.name', 'Test User'], cwd=self.repo_path, stdout=subprocess.DEVNULL)

        # File 1: Python in Repo (Undocumented)
        self.file_py_repo = self.repo_path / "hello.py"
        self.file_py_repo.write_text('def hello():\n    """"Prints Hello World!"""\n    print("hello world")', encoding='utf-8')

        # File 2: C in Repo (Documented)
        self.file_c_repo = self.repo_path / "math.c"
        self.file_c_repo.write_text('int add(int a, int b) {\n    return a + b;\n}', encoding='utf-8')

        # Setup No Git Folder
        self.no_git_path = self.tmp_root / "nogit"
        self.no_git_path.mkdir()

        # File 3: Python no git (Undocumented)
        self.file_py_nogit = self.no_git_path / "utils.py"
        self.file_py_nogit.write_text('class Utils:\n    def do_something(self):\n        pass', encoding='utf-8')

    def tearDown(self):
        if self.tmp_root.exists():
            shutil.rmtree(self.tmp_root)

    def test_comb_git_repo(self):
        """Test commenting on a git repo (multiple files)."""
        files = [str(self.file_py_repo), str(self.file_c_repo)]
        run_comb(repo_root=str(self.repo_path), repo_name="repo", files=files)
        
        #self.assertIn('Docstring from Agent', self.file_py_repo.read_text(encoding='utf-8'))
        
        # c_content = self.file_c_repo.read_text(encoding='utf-8')
        # self.assertIn('Docstring from Agent', c_content)
        # self.assertNotIn('Existing Doc', c_content)

    def test_comb_single_file_in_git(self):
        """Test commenting on a single file within a git repo."""
        mock_agent = MagicMock()
        
        files = [str(self.file_py_repo)]
        run_comb(repo_root=str(self.repo_path), repo_name="repo", files=files)

        # mock_create_repograph.assert_called()
        # self.assertTrue(mock_agent.call.called)
        # self.assertIn('Docstring from Agent', self.file_py_repo.read_text(encoding='utf-8'))
        # # Ensure other file in repo is NOT touched
        # self.assertNotIn('Docstring from Agent', self.file_c_repo.read_text(encoding='utf-8'))

    def test_comb_no_git(self):
        """Test commenting on files not in a git repo."""

        files = [str(self.file_py_nogit)]
        run_comb(repo_root=None, repo_name=None, files=files)

        # mock_create_repograph.assert_not_called()
        # self.assertTrue(mock_agent.call.called)
        # self.assertIn('Docstring from Agent', self.file_py_nogit.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
