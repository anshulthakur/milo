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
            self.assertEqual(block.type, expected_types[i])
            actual_text = block.text.decode('utf-8').strip().replace('\\n', '\n')
            expected_text = expected_texts[i].strip()
            if actual_text != expected_text:
                print(f"Mismatch in block {i+1}:")
                print(f"Expected: {repr(expected_text)}")
                print(f"Actual:   {repr(actual_text)}")
            self.assertEqual(actual_text, expected_text)

    def test_python_parser_file1(self):
        """Tests the Python parser with file1.py."""
        py_file = self.test_repo_path / 'file1.py'
        parser = Treesitter.create_treesitter(Language.PYTHON)
        with open(py_file, 'rb') as f:
            content = f.read()
            
        parser.parse(content)
        blocks = list(parser.iterate_blocks())
        
        self.assertEqual(len(blocks), 10)

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
            actual_text = block.text.decode('utf-8').strip()
            expected_text = expected_texts[i].strip()
            if actual_text != expected_text:
                print(f"Mismatch in block {i+1}:")
                print(f"Expected: {repr(expected_text)}")
                print(f"Actual:   {repr(actual_text)}")
            self.assertEqual(actual_text, expected_text)


    def test_python_parser_file6(self):
        """Tests the Python parser with subdir/file6.py."""
        py_file = self.test_repo_path / 'subdir' / 'file6.py'
        parser = Treesitter.create_treesitter(Language.PYTHON)
        with open(py_file, 'rb') as f:
            content = f.read()
            
        parser.parse(content)
        blocks = list(parser.iterate_blocks())
        
        self.assertEqual(len(blocks), 7)

        expected_texts = [
            "from collections import namedtuple",
            "Point = namedtuple('Point', ['x', 'y'])",
            '''class AnotherClass(object):
    """Another class with a static method."""
    class_var = 10

    def __init__(self, x, y):
        self.p = Point(x, y)

    @staticmethod
    def static_method():
        return "This is a static method."

    def __repr__(self):
        return f"AnotherClass(x={self.p.x}, y={self.p.y})"''',
            '''def another_function(items):
    """A function with a filter and map."""
    evens = filter(lambda x: x % 2 == 0, items)
    squared = map(lambda x: x * x, evens)
    return list(squared)''',
            'gen_exp = (x for x in range(10) if x % 3 == 0)',
            '''def main():
    ac = AnotherClass(1, 2)
    print(ac)
    print(AnotherClass.static_method())
    numbers = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    print(another_function(numbers))
    for val in gen_exp:
        print(f"Generator expression value: {val}")''', 
            """if __name__ == '__main__':
    main()"""
        ]

        for i, block in enumerate(blocks):
            actual_text = block.text.decode('utf-8').strip()
            expected_text = expected_texts[i].strip()
            if actual_text != expected_text:
                print(f"Mismatch in block {i+1}:")
                print(f"Expected: {repr(expected_text)}")
                print(f"Actual:   {repr(actual_text)}")
            self.assertEqual(actual_text, expected_text)


    def test_c_header_parser(self):
        """Tests the C parser with file3.h."""
        c_header_file = self.test_repo_path / 'file3.h'
        parser = Treesitter.create_treesitter(Language.C)
        with open(c_header_file, 'rb') as f:
            content = f.read()
        
        parser.parse(content)
        
        blocks = list(parser.iterate_blocks())
        
        self.assertEqual(len(blocks), 11)
        
        expected_types = [
            'preproc_def',
            'preproc_include',
            'preproc_include',
            'preproc_def',
            'type_definition',
            'type_definition',
            'declaration',
            'struct_specifier',
            'declaration',
            'declaration',
            'function_definition',
        ]
        expected_texts = [
            '#define FILE3_H',
            '#include <stdio.h>',
            '#include <stdlib.h>',
            '#define MAX_VALUE 100',
            '''typedef struct {
    int id;
    char* name;
} MyStruct;''',
            '''typedef struct __attribute__((__packed__)) {
    char c;
    int i;
} PackedStruct;''',
            'extern int global_variable;',
            '''struct test_struct {
    char a;
    int b;
}''',
            'void function1(int arg1, char *arg2);',
            'int function2(void);',
            '''static inline int inline_function(int x) {
    return x * x;
}''',
        ]

        for i, block in enumerate(blocks):
            self.assertEqual(block.type, expected_types[i])
            actual_text = block.text.decode('utf-8').strip()
            expected_text = expected_texts[i].strip()
            if actual_text != expected_text:
                print(f"Mismatch in block {i+1} (header):")
                print(f"Expected: {repr(expected_text)}")
                print(f"Actual:   {repr(actual_text)}")
            self.assertEqual(actual_text, expected_text)


if __name__ == '__main__':
    unittest.main()
