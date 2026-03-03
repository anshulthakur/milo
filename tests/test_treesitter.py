import unittest
from pathlib import Path
from milo.codesift.parsers import Language
from milo.codesift.parsers.treesitter import Treesitter

class TestTreesitter(unittest.TestCase):

    def setUp(self):
        self.test_repo_path = Path('tests/tmp/test_repo').resolve()

    def test_c_parser(self):
        """Tests the C parser with file2.c."""
        c_file = self.test_repo_path / 'file2.c'
        parser = Treesitter.create_treesitter(Language.C)
        with open(c_file, 'rb') as f:
            content = f.read()
        
        parser.parse(content)
        blocks = list(parser.iterate_blocks())
        
        self.assertEqual(len(blocks), 5)
        
        expected_types = [
            'preproc_include',
            'declaration',
            'function_definition',
            'function_definition',
            'function_definition',
        ]
        expected_texts = [
            '#include "file3.h"',
            'int global_variable = 42;',
            '''void function1(int arg1, char *arg2) {
    printf("Function 1 called with %d and %s\n", arg1, arg2);
    for (int i = 0; i < arg1; i++) {
        if (i % 2 == 0) {
            puts("Even");
        } else {
            puts("Odd");
        }
    }
}''',
            '''int function2(void) {
    MyStruct s;
    s.id = 1;
    s.name = "Test";
    printf("Function 2 called with struct: id=%d, name=%s\n", s.id, s.name);
    return inline_function(global_variable);
}''',
            '''int main(int argc, char *argv[]) {
    function1(5, "hello");
    int result = function2();
    printf("Result from function2: %d\n", result);
    return 0;
}'''
        ]

        for i, block in enumerate(blocks):
            self.assertEqual(block.node_type, expected_types[i])
            actual_text = block.source_code.strip().replace('\\n', '\n')
            expected_text = expected_texts[i].strip()
            if actual_text != expected_text:
                print(f"Mismatch in block {i+1}:")
                print(f"Expected: {repr(expected_text)}")
                print(f"Actual:   {repr(actual_text)}")
            self.assertEqual(actual_text, expected_text)

    def test_c_dynamic_entry_points(self):
        # Test for file8.c
        c_file_8 = self.test_repo_path / 'file8.c'
        parser = Treesitter.create_treesitter(Language.C)
        with open(c_file_8, 'rb') as f:
            content = f.read()
        
        parser.parse(content)
        functions = parser.get_definitions('function')
        
        dynamic_entries = parser.get_dynamic_entry_points(parser.tree.root_node)

        # for entry in dynamic_entries:
        #     print(entry.source_code)

        self.assertEqual(len(dynamic_entries), 2)
        entry_point_names = {entry.name for entry in dynamic_entries}
        self.assertIn('my_callback_handler', entry_point_names)
        self.assertIn('another_callback', entry_point_names)
        self.assertNotIn('my_local_var', entry_point_names)

        # Test for file5.c
        c_file_5 = self.test_repo_path / 'file5.c'
        # Re-create parser for clean state if needed, though for this case it's probably fine
        parser = Treesitter.create_treesitter(Language.C)
        with open(c_file_5, 'rb') as f:
            content = f.read()
        
        parser.parse(content)
        functions = parser.get_definitions('function')
        
        dynamic_entries = parser.get_dynamic_entry_points(parser.tree.root_node)
        # for entry in dynamic_entries:
        #     print(entry.source_code)
            
        self.assertEqual(len(dynamic_entries), 1)
        entry_point_names = {entry.name for entry in dynamic_entries}
        self.assertIn('thread_function', entry_point_names)

    def test_python_parser_file1(self):
        """Tests the Python parser with file1.py."""
        py_file = self.test_repo_path / 'file1.py'
        parser = Treesitter.create_treesitter(Language.PYTHON)
        with open(py_file, 'rb') as f:
            content = f.read()
            
        parser.parse(content)
        blocks = list(parser.iterate_blocks())
        
        self.assertEqual(len(blocks), 10)

        expected_types = [
            "import_statement",
            "import_statement",
            "import_statement",
            "expression_statement",
            "function_definition",
            "class_definition",
            "decorated_definition",
            "function_definition",
            "function_definition",
            "if_statement",
        ]

        expected_texts = [
            "import os",
            "import sys",
            "import asyncio",
            'GLOBAL_VAR = "Hello"',
            '''def decorator(func):
    def wrapper(*args, **kwargs):
        print("Decorator before call")
        result = func(*args, **kwargs)
        print("Decorator after call")
        return result
    return wrapper''',
            '''class MyClass:
    def __init__(self, name):
        self.name = name

    def greet(self):
        return f"Hello, {self.name}"''',
            '''@decorator
def my_function(a, b):
    """This is a sample function."""
    list_comp = [i*i for i in range(a, b)]
    return sum(list_comp)''',
            '''async def async_function():
    print("Async function start")
    await asyncio.sleep(1)
    print("Async function end")''',

            '''def generator_function(n):
    for i in range(n):
        yield i''',
        
        '''if __name__ == "__main__":
    instance = MyClass("World")
    print(instance.greet())
    print(my_function(1, 10))
    for i in generator_function(5):
        print(i)
    asyncio.run(async_function())'''
        ]

        for i, block in enumerate(blocks):
            self.assertEqual(block.node_type, expected_types[i])
            actual_text = block.source_code.strip().replace('\\n', '\n')
            expected_text = expected_texts[i].strip()
            if actual_text != expected_text:
                print(f"Mismatch in block {i+1}:")
                print(f"Expected: {repr(expected_text)}")
                print(f"Actual:   {repr(actual_text)}")
            self.assertEqual(actual_text, expected_text)

