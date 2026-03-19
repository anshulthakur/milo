import os
import json
import unittest
import shutil
import subprocess
from git import Repo
from unittest.mock import MagicMock, patch
from pathlib import Path
from milo.documentation.documentation import (
    insert_docstring_python,
    insert_docstring_c,
    sanitize_docstring_python,
    locate_node_by_name,
    InputCode,
    update_docstring,
    CommentedCode,
    run_comb
)
from milo.codesift.parsers import Language, Treesitter
from milo.utils.vcs import LocalGitProvider, FileSystemProvider

class TestDocstringManipulation(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path('/tmp/doc_tests').resolve()
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

    def test_input_code_model_fields(self):
        """Test that InputCode model accepts file_path."""
        input_obj = InputCode(language="python", method="def foo(): pass", file_path="src/foo.py")
        self.assertEqual(input_obj.file_path, "src/foo.py")
        
        # Test optionality
        input_obj_none = InputCode(language="python", method="def foo(): pass")
        self.assertIsNone(input_obj_none.file_path)

class TestDocstringManipulationGit(TestDocstringManipulation):
    def setUp(self):
        self.tmp_dir = Path('/tmp/doc_tests_git').resolve()
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(['git', 'init'], cwd=str(self.tmp_dir), stdout=subprocess.DEVNULL)

class TestCombCoverageMocked(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path('/tmp/comb_coverage').resolve()
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir(parents=True)

        # 1. Setup Git directory
        self.repo_dir = self.tmp_dir / "repo"
        self.repo_dir.mkdir()
        self.repo = Repo.init(self.repo_dir)
        with self.repo.config_writer() as cw:
            cw.set_value("user", "name", "Test User").release()
            cw.set_value("user", "email", "test@example.com").release()

        self.app1 = self.repo_dir / "app1.py"
        self.app1.write_text("def func1(): pass\n")
        self.app2 = self.repo_dir / "app2.py"
        self.app2.write_text("def func2(): pass\n")
        
        self.repo.index.add(["app1.py", "app2.py"])
        self.repo.index.commit("Initial commit")

        # 2. Setup Non-Git directory
        self.nogit_dir = self.tmp_dir / "nogit"
        self.nogit_dir.mkdir()
        self.script1 = self.nogit_dir / "script1.py"
        self.script1.write_text("def func3(): pass\n")
        self.script2 = self.nogit_dir / "script2.py"
        self.script2.write_text("def func4(): pass\n")

    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    def _setup_mock(self, mock_get_agent):
        mock_agent = MagicMock()
        mock_get_agent.return_value = mock_agent
        def side_effect(payload):
            input_data = json.loads(payload)
            code = input_data["method"]
            import re
            match = re.search(r'def\s+(\w+)', code)
            method_name = match.group(1) if match else "unknown"
            return CommentedCode(method_name=method_name, documentation='\"\"\"Mock Doc\"\"\"').model_dump_json()
        mock_agent.call.side_effect = side_effect
        return mock_agent

    @patch('milo.documentation.documentation.get_documentation_agent')
    def test_case_1_subset_git(self, mock_get_agent):
        mock_agent = self._setup_mock(mock_get_agent)
        file_manager = LocalGitProvider(str(self.repo_dir))
        run_comb(file_manager=file_manager, repo_root=str(self.repo_dir), files=[str(self.app1)])
        self.assertEqual(mock_agent.call.call_count, 1)
        self.assertIn("Mock Doc", self.app1.read_text())
        self.assertNotIn("Mock Doc", self.app2.read_text())

    @patch('milo.documentation.documentation.get_documentation_agent')
    def test_case_2_entire_git(self, mock_get_agent):
        mock_agent = self._setup_mock(mock_get_agent)
        file_manager = LocalGitProvider(str(self.repo_dir))
        run_comb(file_manager=file_manager, repo_root=str(self.repo_dir), files=[str(self.app1), str(self.app2)])
        self.assertEqual(mock_agent.call.call_count, 2)
        self.assertIn("Mock Doc", self.app1.read_text())
        self.assertIn("Mock Doc", self.app2.read_text())

    @patch('milo.documentation.documentation.get_documentation_agent')
    def test_case_3_staged_changes_git(self, mock_get_agent):
        mock_agent = self._setup_mock(mock_get_agent)
        self.app2.write_text("def func2():\n    print('changed')\n")
        self.repo.index.add(["app2.py"])
        file_manager = LocalGitProvider(str(self.repo_dir))
        changed_files = file_manager.get_changed_files(str(self.repo_dir))
        run_comb(file_manager=file_manager, repo_root=str(self.repo_dir), files=changed_files)
        self.assertEqual(mock_agent.call.call_count, 1)
        self.assertNotIn("Mock Doc", self.app1.read_text())
        self.assertIn("Mock Doc", self.app2.read_text())

    @patch('milo.documentation.documentation.get_documentation_agent')
    def test_case_4_all_nogit(self, mock_get_agent):
        mock_agent = self._setup_mock(mock_get_agent)
        file_manager = FileSystemProvider(str(self.nogit_dir))
        run_comb(file_manager=file_manager, repo_root=str(self.nogit_dir), files=[str(self.script1), str(self.script2)])
        self.assertEqual(mock_agent.call.call_count, 2)
        self.assertIn("Mock Doc", self.script1.read_text())
        self.assertIn("Mock Doc", self.script2.read_text())

    @patch('milo.documentation.documentation.get_documentation_agent')
    def test_case_5_subset_nogit(self, mock_get_agent):
        mock_agent = self._setup_mock(mock_get_agent)
        file_manager = FileSystemProvider(str(self.nogit_dir))
        run_comb(file_manager=file_manager, repo_root=str(self.nogit_dir), files=[str(self.script1)])
        self.assertEqual(mock_agent.call.call_count, 1)
        self.assertIn("Mock Doc", self.script1.read_text())
        self.assertNotIn("Mock Doc", self.script2.read_text())

if __name__ == '__main__':
    unittest.main()
