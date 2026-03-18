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
    InputCode,
    update_docstring,
    CommentedCode,
)
from milo.codesift.parsers import Language, Treesitter

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

if __name__ == '__main__':
    unittest.main()
