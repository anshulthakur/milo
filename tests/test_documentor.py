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

class TestDocstringManipulation(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path('tests/tmp/doc_tests').resolve()
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    def test_sanitize_docstring_python(self):
        # Test wrapping
        self.assertEqual(sanitize_docstring_python('foo'), '"""\nfoo\n"""')
        # Test existing quotes
        self.assertEqual(sanitize_docstring_python('"""foo"""'), '"""foo"""')
        self.assertEqual(sanitize_docstring_python("'''foo'''"), "'''foo'''")
        # Test extraction
        self.assertEqual(sanitize_docstring_python('prefix """inner""" suffix'), '"""inner"""')

    def test_locate_node_by_name(self):
        code = """
def my_func():
    pass
"""
        parser = Treesitter.create_treesitter(Language.PYTHON)
        parser.parse(code.encode('utf-8'))
        nodes = list(parser.iterate_blocks())
        
        # Test finding function
        node = locate_node_by_name(nodes, "my_func", "function_definition")
        self.assertIsNotNone(node)
        self.assertEqual(node.name, "my_func")
        
        # Test type mismatch
        node = locate_node_by_name(nodes, "my_func", "class_definition")
        self.assertIsNone(node)

    def test_insert_docstring_python(self):
        code = """
def my_func(a, b):
    print("Hello")
    return a + b
"""
        filename = self.tmp_dir / "test.py"
        filename.write_text(code, encoding='utf-8')
        
        parser = Treesitter.create_treesitter(Language.PYTHON)
        parser.parse(code.encode('utf-8'))
        
        # Find the function node
        nodes = list(parser.iterate_blocks())
        func_node = locate_node_by_name(nodes, "my_func", "function_definition")
        self.assertIsNotNone(func_node)
        
        docstring = "Adds two numbers."
        new_code = insert_docstring_python(code, parser, func_node, docstring)
        
        # Expected: Docstring inserted at the beginning of the body with correct indentation
        expected_code = """
def my_func(a, b):
    \"\"\"Adds two numbers.\"\"\"
    print("Hello")
    return a + b
"""
        self.assertEqual(new_code.strip(), expected_code.strip())

    def test_insert_docstring_c(self):
        code = """
int add(int a, int b) {
    return a + b;
}
"""
        filename = self.tmp_dir / "test.c"
        filename.write_text(code, encoding='utf-8')
        
        parser = Treesitter.create_treesitter(Language.C)
        parser.parse(code.encode('utf-8'))
        
        # Find the function node (assuming iterate_blocks works for C as per other tests)
        nodes = list(parser.iterate_blocks())
        func_node = locate_node_by_name(nodes, "add", "function_definition")
        self.assertIsNotNone(func_node)
        
        docstring = "/** Adds two numbers */"
        new_code = insert_docstring_c(code, parser, func_node, docstring)
        
        expected_code = """
/** Adds two numbers */
int add(int a, int b) {
    return a + b;
}
"""
        self.assertEqual(new_code.strip(), expected_code.strip())

    def test_update_docstring_python(self):
        code = """
def my_func():
    \"\"\"Old docstring.\"\"\"
    pass
"""
        filename = self.tmp_dir / "test_update.py"
        filename.write_text(code, encoding='utf-8')
        
        # Parse to get the node
        parser = Treesitter.create_treesitter(Language.PYTHON)
        parser.parse(code.encode('utf-8'))
        nodes = list(parser.iterate_blocks())
        func_node = locate_node_by_name(nodes, "my_func", "function_definition")
        self.assertIsNotNone(func_node)
        
        # Update docstring
        new_comment = CommentedCode(method_name="my_func", documentation="New docstring.")
        update_docstring(str(filename), Language.PYTHON, func_node, new_comment)
        
        new_content = filename.read_text(encoding='utf-8')
        
        # Verify old docstring is gone and new one is present and formatted
        self.assertNotIn("Old docstring", new_content)
        self.assertIn('"""\n    New docstring.\n    """', new_content)

    def test_update_docstring_c(self):
        code = """
/** Old docstring */
void my_func() {
}
"""
        filename = self.tmp_dir / "test_update.c"
        filename.write_text(code, encoding='utf-8')
        
        parser = Treesitter.create_treesitter(Language.C)
        parser.parse(code.encode('utf-8'))
        nodes = list(parser.iterate_blocks())
        func_node = locate_node_by_name(nodes, "my_func", "function_definition")
        self.assertIsNotNone(func_node)
        
        new_comment = CommentedCode(method_name="my_func", documentation="/** New docstring */")
        update_docstring(str(filename), Language.C, func_node, new_comment)
        
        new_content = filename.read_text(encoding='utf-8')
        self.assertIn("/** New docstring */", new_content)
        self.assertNotIn("Old docstring", new_content)

class TestCombIntegration(unittest.TestCase):

    def setUp(self):
        self.tmp_root = Path('tests/tmp/comb_tests').resolve()
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
        self.file_py_repo.write_text('def hello():\n    print("hello world")', encoding='utf-8')

        # File 2: C in Repo (Documented)
        self.file_c_repo = self.repo_path / "math.c"
        self.file_c_repo.write_text('/** Existing Doc */\nint add(int a, int b) {\n    return a + b;\n}', encoding='utf-8')

        # Setup No Git Folder
        self.no_git_path = self.tmp_root / "nogit"
        self.no_git_path.mkdir()

        # File 3: Python no git (Undocumented)
        self.file_py_nogit = self.no_git_path / "utils.py"
        self.file_py_nogit.write_text('class Utils:\n    def do_something(self):\n        pass', encoding='utf-8')

    def tearDown(self):
        # if self.tmp_root.exists():
        #     shutil.rmtree(self.tmp_root)
        pass

    def test_comb_git_repo(self):
        """Test commenting on a git repo (multiple files)."""
        files = [str(self.file_py_repo), str(self.file_c_repo)]
        run_comb(repo_root=str(self.repo_path), repo_name="repo", files=files)
        
        self.assertIn('Docstring from Agent', self.file_py_repo.read_text(encoding='utf-8'))
        
        # c_content = self.file_c_repo.read_text(encoding='utf-8')
        # self.assertIn('Docstring from Agent', c_content)
        # self.assertNotIn('Existing Doc', c_content)

    @patch('milo.documentation.documentation.get_documentation_agent')
    @patch('milo.documentation.documentation.create_repograph')
    def test_comb_single_file_in_git(self, mock_create_repograph, mock_get_agent):
        """Test commenting on a single file within a git repo."""
        mock_agent = MagicMock()
        mock_get_agent.return_value = mock_agent
        mock_agent.call.return_value = '{"method_name": "any", "documentation": "Docstring from Agent"}'

        files = [str(self.file_py_repo)]
        run_comb(repo_root=str(self.repo_path), repo_name="repo", files=files)

        mock_create_repograph.assert_called()
        self.assertTrue(mock_agent.call.called)
        self.assertIn('Docstring from Agent', self.file_py_repo.read_text(encoding='utf-8'))
        # Ensure other file in repo is NOT touched
        self.assertNotIn('Docstring from Agent', self.file_c_repo.read_text(encoding='utf-8'))

    @patch('milo.documentation.documentation.get_documentation_agent')
    @patch('milo.documentation.documentation.create_repograph')
    def test_comb_no_git(self, mock_create_repograph, mock_get_agent):
        """Test commenting on files not in a git repo."""
        mock_agent = MagicMock()
        mock_get_agent.return_value = mock_agent
        mock_agent.call.return_value = '{"method_name": "any", "documentation": "Docstring from Agent"}'

        files = [str(self.file_py_nogit)]
        run_comb(repo_root=None, repo_name=None, files=files)

        mock_create_repograph.assert_not_called()
        self.assertTrue(mock_agent.call.called)
        self.assertIn('Docstring from Agent', self.file_py_nogit.read_text(encoding='utf-8'))

if __name__ == '__main__':
    unittest.main()
