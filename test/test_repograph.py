import unittest
import os
import json
import shutil
from pathlib import Path
from milo.codesift.repograph import create_repograph
from milo.codesift.repobrowser import load_repo_graph, get_contextual_neighbors, fetch_source_snippet

class TestRepograph(unittest.TestCase):

    @classmethod
    def create_test_files(cls, repo_path: Path):
        repo_path.mkdir(parents=True, exist_ok=True)
        
        # FILE1_PY
        (repo_path / "file1.py").write_text("""import os
import sys
import asyncio

GLOBAL_VAR = "Hello"

def decorator(func):
    def wrapper(*args, **kwargs):
        print("Decorator before call")
        result = func(*args, **kwargs)
        print("Decorator after call")
        return result
    return wrapper

class MyClass:
    def __init__(self, name):
        self.name = name

    def greet(self):
        return f"Hello, {self.name}"

@decorator
def my_function(a, b):
    \"\"\"This is a sample function.\"\"\"
    list_comp = [i*i for i in range(a, b)]
    return sum(list_comp)

async def async_function():
    print("Async function start")
    await asyncio.sleep(1)
    print("Async function end")

def generator_function(n):
    for i in range(n):
        yield i

if __name__ == "__main__":
    instance = MyClass("World")
    print(instance.greet())
    print(my_function(1, 10))
    for i in generator_function(5):
        print(i)
    asyncio.run(async_function())""", encoding='utf-8')

        # FILE2_C
        (repo_path / "file2.c").write_text("""#include "file3.h"

int global_variable = 42;

void function1(int arg1, char *arg2) {
    printf("Function 1 called with %d and %s\\n", arg1, arg2);
    for (int i = 0; i < arg1; i++) {
        if (i % 2 == 0) {
            puts("Even");
        } else {
            puts("Odd");
        }
    }
}

int function2(void) {
    MyStruct s;
    s.id = 1;
    s.name = "Test";
    printf("Function 2 called with struct: id=%d, name=%s\\n", s.id, s.name);
    return inline_function(global_variable);
}

int main(int argc, char *argv[]) {
    function1(5, "hello");
    int result = function2();
    printf("Result from function2: %d\\n", result);
    return 0;
}""", encoding='utf-8')

        # FILE3_H
        (repo_path / "file3.h").write_text("""#ifndef FILE3_H
#define FILE3_H

#include <stdio.h>

typedef struct {
    int id;
    char *name;
} MyStruct;

static inline int inline_function(int x) {
    return x * 2;
}

#endif""", encoding='utf-8')

        # FILE5_C
        (repo_path / "file5.c").write_text("""#include <pthread.h>
#include <stdio.h>

void *thread_function(void *arg) {
    printf("Inside thread\\n");
    return NULL;
}

int main() {
    pthread_t thread_id;
    pthread_create(&thread_id, NULL, thread_function, NULL);
    pthread_join(thread_id, NULL);
    return 0;
}""", encoding='utf-8')

        # FILE8_C
        (repo_path / "file8.c").write_text("""#include <stdio.h>

typedef void (*callback_t)(void);

void register_callback(callback_t cb) {
    cb();
}

void my_callback_handler(void) {
    printf("Callback 1\\n");
}

void another_callback(void) {
    printf("Callback 2\\n");
}

int main() {
    register_callback(my_callback_handler);
    register_callback(another_callback);
    return 0;
}""", encoding='utf-8')

        # FILE6_PY
        subdir = repo_path / "subdir"
        subdir.mkdir(exist_ok=True)
        (subdir / "file6.py").write_text("""
def another_function():
    print("Another function")

class AnotherClass:
    def __init__(self):
        pass
    def __repr__(self):
        return "AnotherClass"

def main():
    another_function()

if __name__ == "__main__":
    main()
""", encoding='utf-8')

    @classmethod
    def setUpClass(cls):
        cls.test_repo_path = Path('/tmp/test_repo').resolve()
        cls.save_path = Path('/tmp/test_repograph').resolve()
        cls.save_path.mkdir(exist_ok=True)
        if cls.test_repo_path.exists():
            shutil.rmtree(cls.test_repo_path)
        cls.create_test_files(cls.test_repo_path)
        
        create_repograph(str(cls.test_repo_path), save_path=str(cls.save_path))
        cls.G, cls.metadata = load_repo_graph(str(cls.save_path / "metadata.json"))

    @classmethod
    def tearDownClass(cls):
        # if cls.save_path.exists():
        #     shutil.rmtree(cls.save_path)
        # if cls.test_repo_path.exists():
        #     shutil.rmtree(cls.test_repo_path)
        pass
    
    def test_create_repograph_for_c(self):
        # C assertions
        self.assertIn("file2.c::function1", self.metadata["defined_mappings"])
        self.assertIn("file2.c::function2", self.metadata["defined_mappings"])
        self.assertIn("file2.c::main", self.metadata["defined_mappings"])
        self.assertEqual(self.metadata["defined_mappings"]["file2.c::main"]["calls"], ["file2.c::function1", "file2.c::function2"])
        self.assertEqual(self.metadata["defined_mappings"]["file2.c::function2"]["calls"], ["file3.h::inline_function"])

    def test_repograph_dynamic_calls(self):
        self.assertIn('file8.c::my_callback_handler', self.metadata["defined_mappings"])
        self.assertIn('file8.c::another_callback', self.metadata["defined_mappings"])
        self.assertIn('file8.c::register_callback', self.metadata["defined_mappings"])
        self.assertIn('file8.c::main', self.metadata["defined_mappings"])

        main_calls = self.metadata["defined_mappings"]['file8.c::main']['calls']
        self.assertIn('file8.c::register_callback', main_calls)

        register_calls = self.metadata["defined_mappings"]['file8.c::register_callback']['calls']
        self.assertIn('file8.c::my_callback_handler', register_calls)
        self.assertIn('file8.c::another_callback', register_calls)

        self.assertTrue(self.metadata["defined_mappings"]['file8.c::my_callback_handler']['is_dynamic_entry_point'])
        self.assertTrue(self.metadata["defined_mappings"]['file8.c::another_callback']['is_dynamic_entry_point'])

        # Assertions for file5.c
        self.assertIn('file5.c::thread_function', self.metadata["defined_mappings"])
        self.assertTrue(self.metadata["defined_mappings"]['file5.c::thread_function']['is_dynamic_entry_point'])


    def test_create_repograph_for_python(self):
        # Python assertions
        self.assertIn("file1.py::my_function", self.metadata["defined_mappings"])
        self.assertIn("file1.py::MyClass.greet", self.metadata["defined_mappings"])
        self.assertIn("subdir/file6.py::another_function", self.metadata["defined_mappings"])

    def test_get_callees(self):
        # In file2.c, main calls function1 and function2
        callees = list(self.G.successors("file2.c::main"))
        self.assertIn("file2.c::function1", callees)
        self.assertIn("file2.c::function2", callees)

    def test_get_callers(self):
        # In file2.c, function1 is called by main
        callers = list(self.G.predecessors("file2.c::function1"))
        self.assertIn("file2.c::main", callers)

    def test_fetch_function_body(self):
        body = fetch_source_snippet("file1.py::my_function", self.G, self.metadata, repo_path=str(self.test_repo_path))
        self.assertEqual(body.strip(), '''def my_function(a, b):
    """This is a sample function."""
    list_comp = [i*i for i in range(a, b)]
    return sum(list_comp)''')

    def test_get_contextual_neighbors(self):
        # main calls function1 and function2. function2 calls inline_function.
        # neighbors of function2 should be main (caller) and inline_function (callee)
        neighbors = get_contextual_neighbors(self.G, "file2.c::function2", self.metadata, depth=1)
        self.assertIn("file2.c::main", neighbors)
        self.assertIn("file3.h::inline_function", neighbors)

    def test_lookup_short_method_names(self):
        """
        Test that class methods are indexed by their short name (without class prefix)
        to support tool usage where agents might not know the class name.
        """
        lookup = self.metadata["lookup"]
        # 'greet' is a method of MyClass in file1.py (file1.py::MyClass.greet)
        # It should be indexed under 'greet' as well as 'MyClass.greet'
        self.assertIn("greet", lookup)
        self.assertIn("file1.py::MyClass.greet", lookup["greet"])
        
        # Verify 'MyClass.greet' is also a key
        self.assertIn("MyClass.greet", lookup)

if __name__ == '__main__':
    unittest.main()
