import unittest
import networkx as nx
import os
import shutil
import subprocess
from pathlib import Path
from milo.codesift.repograph import create_repograph
from milo.codesift.repobrowser import CallFlowAnalyzer, load_repo_graph, resolve_function_name, fetch_source_snippet, lookaround_source_snippet

class TestCallFlowAnalyzer(unittest.TestCase):
    
    def create_test_files(self, repo_path):
        path = Path(repo_path)
        path.mkdir(parents=True, exist_ok=True)
        
        # Use same file content logic as test_repograph
        (path / "file1.py").write_text("""import os
import sys
import asyncio

GLOBAL_VAR = "Hello"

def decorator(func):
    def wrapper(*args, **kwargs):
        # This is a python comment
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

def multiline_doc_func():
    \"\"\"
    This is a
    multiline docstring.
    \"\"\"
    fake_doc = \"\"\"This should not be stripped\"\"\"
    return fake_doc

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

        (path / "file2.c").write_text("""#include "file3.h"

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

void function3(void) {
    /*
     * This is a
     * multiline
     * C comment
     */
    printf("function3\\n");
}

int main(int argc, char *argv[]) {
    // This is a C comment
    function1(5, "hello");
    int result = function2();
    printf("Result from function2: %d\\n", result);
    return 0;
}""", encoding='utf-8')

        (path / "file3.h").write_text("""#ifndef FILE3_H
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

        (path / "file5.c").write_text("""#include <pthread.h>
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

        (path / "file8.c").write_text("""#include <stdio.h>

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

        subdir = path / "subdir"
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

    def setUp(self):
        """Set up a sample graph for testing by parsing the test_repo."""
        self.base_tmp = Path("/tmp").resolve()
        self.test_repo_path = self.base_tmp / "test_repo"
        self.output_path = self.base_tmp / "test_repobrowser_output"
        
        if self.test_repo_path.exists():
            shutil.rmtree(self.test_repo_path)
        self.create_test_files(self.test_repo_path)

        if self.output_path.exists():
            shutil.rmtree(self.output_path)
        self.output_path.mkdir(parents=True, exist_ok=True)

        create_repograph(str(self.test_repo_path), save_path=str(self.output_path))
        
        self.G, _ = load_repo_graph(json_path=str(self.output_path / "metadata.json"))
        self.analyzer = CallFlowAnalyzer(self.G)

    def tearDown(self):
        """Clean up generated files."""
        if self.output_path.exists():
            shutil.rmtree(self.output_path)
        if self.test_repo_path.exists():
            shutil.rmtree(self.test_repo_path)

    def test_find_entry_points(self):
        """Test that entry points (nodes with in-degree 0) are found correctly."""
        entry_points = self.analyzer.find_entry_points()
        
        expected_entry_points = [
            'file1.py::MyClass.__init__',
            'file1.py::MyClass.greet',
            'file1.py::async_function',
            'file1.py::decorator',
            'file1.py::generator_function',
            'file1.py::multiline_doc_func',
            'file1.py::my_function',
            'file1.py::wrapper',
            'file2.c::function3',
            'file2.c::main',
            'file5.c::main',
            'file5.c::thread_function',
            'file8.c::another_callback',
            'file8.c::main',
            'file8.c::my_callback_handler',
            'subdir/file6.py::AnotherClass.__init__',
            'subdir/file6.py::AnotherClass.__repr__',
            'subdir/file6.py::main'
        ]
        
        self.assertCountEqual(entry_points, expected_entry_points)

    def test_find_dynamic_entry_points(self):
        """Test that dynamic entry points (e.g., from pthread_create) are found."""
        entry_points = self.analyzer.find_entry_points()
        self.assertIn('file5.c::thread_function', entry_points)
    def test_get_all_call_flows(self):
        """Test getting all call flows from all entry points."""
        all_flows = self.analyzer.get_all_call_flows()

        # Test flow for file2.c::main
        main_c_flow = all_flows.get('file2.c::main')
        expected_main_c_flow = [
            ['file2.c::main', 'file2.c::function2', 'file3.h::inline_function'], 
            ['file2.c::main', 'file2.c::function1']
        ]
        # The order of flows is not guaranteed, so we compare them as sets of tuples
        self.assertCountEqual([tuple(p) for p in main_c_flow], [tuple(p) for p in expected_main_c_flow])

        # Test flow for subdir/file6.py::main
        main_py_flow = all_flows.get('subdir/file6.py::main')
        self.assertTrue(any('subdir/file6.py::another_function' in path for path in main_py_flow))

class TestRepoBrowserResolution(TestCallFlowAnalyzer):
    """
    Tests for name resolution and snippet fetching with file hints.
    Inherits setup from TestCallFlowAnalyzer to reuse file creation logic.
    """
    
    def test_resolve_function_name_exact(self):
        # Exact fully qualified name should always resolve
        res = resolve_function_name("file1.py::my_function", {"lookup": self.G.graph["lookup"]})
        self.assertEqual(res, "file1.py::my_function")

    def test_resolve_function_name_short(self):
        # Short name unique in the repo
        res = resolve_function_name("my_function", {"lookup": self.G.graph["lookup"]})
        self.assertEqual(res, "file1.py::my_function")

    def test_resolve_function_name_method_short(self):
        # Method name without class prefix (indexed by new repograph logic)
        res = resolve_function_name("greet", {"lookup": self.G.graph["lookup"]})
        self.assertEqual(res, "file1.py::MyClass.greet")

    def test_resolve_function_name_with_hint(self):
        # Ambiguous name handling (simulated or real)
        # 'main' exists in file2.c, file5.c, file8.c, subdir/file6.py
        
        # Without hint, it should be ambiguous (return None)
        res = resolve_function_name("main", {"lookup": self.G.graph["lookup"]})
        self.assertIsNone(res)
        
        # With hint, it should resolve to the specific file
        res_c = resolve_function_name("main", {"lookup": self.G.graph["lookup"]}, file_hint="file2.c")
        self.assertEqual(res_c, "file2.c::main")
        
        res_py = resolve_function_name("main", {"lookup": self.G.graph["lookup"]}, file_hint="subdir/file6.py")
        self.assertEqual(res_py, "subdir/file6.py::main")

    def test_fetch_source_with_hint(self):
        # Verify fetch_source_snippet passes the hint through
        snippet = fetch_source_snippet("main", self.G, self.G.graph, repo_path=str(self.test_repo_path), file_hint="file2.c")
        self.assertIn('function1(5, "hello");', snippet)
        self.assertNotIn('pthread_create', snippet)

    def test_strip_comments_in_snippets(self):
        # Test fetch_source_snippet defaults to stripping comments
        py_snippet = fetch_source_snippet("decorator", self.G, self.G.graph, repo_path=str(self.test_repo_path))
        self.assertNotIn("# This is a python comment", py_snippet)
        
        py_snippet_doc = fetch_source_snippet("my_function", self.G, self.G.graph, repo_path=str(self.test_repo_path))
        self.assertNotIn("This is a sample function.", py_snippet_doc)
        
        c_snippet = fetch_source_snippet("main", self.G, self.G.graph, repo_path=str(self.test_repo_path), file_hint="file2.c")
        self.assertNotIn("// This is a C comment", c_snippet)
        
        # Test fetch_source_snippet with strip_comments=False
        py_snippet_kept = fetch_source_snippet("decorator", self.G, self.G.graph, repo_path=str(self.test_repo_path), strip_comments=False)
        self.assertIn("# This is a python comment", py_snippet_kept)
        
        py_snippet_doc_kept = fetch_source_snippet("my_function", self.G, self.G.graph, repo_path=str(self.test_repo_path), strip_comments=False)
        self.assertIn("This is a sample function.", py_snippet_doc_kept)
        
        c_snippet_kept = fetch_source_snippet("main", self.G, self.G.graph, repo_path=str(self.test_repo_path), file_hint="file2.c", strip_comments=False)
        self.assertIn("// This is a C comment", c_snippet_kept)
        
        # Test multiline docstring and skipped docstring in Python
        py_snippet_multi = fetch_source_snippet("multiline_doc_func", self.G, self.G.graph, repo_path=str(self.test_repo_path))
        self.assertNotIn("multiline docstring", py_snippet_multi)
        self.assertIn("This should not be stripped", py_snippet_multi)
        
        # Test multiline C comment
        c_snippet_multi = fetch_source_snippet("function3", self.G, self.G.graph, repo_path=str(self.test_repo_path), file_hint="file2.c")
        self.assertNotIn("multiline", c_snippet_multi)
        self.assertNotIn("C comment", c_snippet_multi)
        self.assertIn("printf", c_snippet_multi)
        
        # With strip_comments=False
        py_snippet_multi_kept = fetch_source_snippet("multiline_doc_func", self.G, self.G.graph, repo_path=str(self.test_repo_path), strip_comments=False)
        self.assertIn("multiline docstring", py_snippet_multi_kept)
        
        c_snippet_multi_kept = fetch_source_snippet("function3", self.G, self.G.graph, repo_path=str(self.test_repo_path), file_hint="file2.c", strip_comments=False)
        self.assertIn("multiline", c_snippet_multi_kept)
        
        # Test lookaround_source_snippet defaults to stripping comments
        py_lookaround = lookaround_source_snippet("decorator", self.G, metadata=self.G.graph, context_lines=5, repo_path=str(self.test_repo_path))
        self.assertNotIn("# This is a python comment", py_lookaround)
        
        py_lookaround_doc = lookaround_source_snippet("my_function", self.G, metadata=self.G.graph, context_lines=5, repo_path=str(self.test_repo_path))
        self.assertNotIn("This is a sample function.", py_lookaround_doc)
        
        c_lookaround = lookaround_source_snippet("main", self.G, metadata=self.G.graph, context_lines=5, repo_path=str(self.test_repo_path), file_hint="file2.c")
        self.assertNotIn("// This is a C comment", c_lookaround)
        
        # Test lookaround_source_snippet with strip_comments=False
        py_lookaround_kept = lookaround_source_snippet("decorator", self.G, metadata=self.G.graph, context_lines=5, repo_path=str(self.test_repo_path), strip_comments=False)
        self.assertIn("# This is a python comment", py_lookaround_kept)
        
        py_lookaround_doc_kept = lookaround_source_snippet("my_function", self.G, metadata=self.G.graph, context_lines=5, repo_path=str(self.test_repo_path), strip_comments=False)
        self.assertIn("This is a sample function.", py_lookaround_doc_kept)
        
        c_lookaround_kept = lookaround_source_snippet("main", self.G, metadata=self.G.graph, context_lines=5, repo_path=str(self.test_repo_path), file_hint="file2.c", strip_comments=False)
        self.assertIn("// This is a C comment", c_lookaround_kept)

        # Test lookaround multiline / skipped
        py_lookaround_multi = lookaround_source_snippet("multiline_doc_func", self.G, metadata=self.G.graph, context_lines=5, repo_path=str(self.test_repo_path))
        self.assertNotIn("multiline docstring", py_lookaround_multi)
        self.assertIn("This should not be stripped", py_lookaround_multi)

        c_lookaround_multi = lookaround_source_snippet("function3", self.G, metadata=self.G.graph, context_lines=5, repo_path=str(self.test_repo_path), file_hint="file2.c")
        self.assertNotIn("multiline", c_lookaround_multi)
        self.assertNotIn("C comment", c_lookaround_multi)

        py_lookaround_multi_kept = lookaround_source_snippet("multiline_doc_func", self.G, metadata=self.G.graph, context_lines=5, repo_path=str(self.test_repo_path), strip_comments=False)
        self.assertIn("multiline docstring", py_lookaround_multi_kept)

        c_lookaround_multi_kept = lookaround_source_snippet("function3", self.G, metadata=self.G.graph, context_lines=5, repo_path=str(self.test_repo_path), file_hint="file2.c", strip_comments=False)
        self.assertIn("multiline", c_lookaround_multi_kept)

class TestCallFlowAnalyzerGit(TestCallFlowAnalyzer):
    def setUp(self):
        self.base_tmp = Path("/tmp").resolve()
        self.test_repo_path = self.base_tmp / "test_repo_browser_git"
        self.output_path = self.base_tmp / "test_repobrowser_output_git"
        
        if self.test_repo_path.exists():
            shutil.rmtree(self.test_repo_path)
        self.create_test_files(self.test_repo_path)

        subprocess.check_call(['git', 'init'], cwd=str(self.test_repo_path), stdout=subprocess.DEVNULL)
        subprocess.check_call(['git', 'config', 'user.email', 'test@example.com'], cwd=str(self.test_repo_path), stdout=subprocess.DEVNULL)
        subprocess.check_call(['git', 'config', 'user.name', 'Test User'], cwd=str(self.test_repo_path), stdout=subprocess.DEVNULL)
        subprocess.check_call(['git', 'add', '.'], cwd=str(self.test_repo_path), stdout=subprocess.DEVNULL)
        subprocess.check_call(['git', 'commit', '-m', 'Initial commit'], cwd=str(self.test_repo_path), stdout=subprocess.DEVNULL)

        if self.output_path.exists():
            shutil.rmtree(self.output_path)
        self.output_path.mkdir(parents=True, exist_ok=True)

        create_repograph(str(self.test_repo_path), save_path=str(self.output_path))
        
        self.G, _ = load_repo_graph(json_path=str(self.output_path / "metadata.json"))
        self.analyzer = CallFlowAnalyzer(self.G)

class TestRepoBrowserResolutionGit(TestRepoBrowserResolution, TestCallFlowAnalyzerGit):
    pass

if __name__ == '__main__':
    unittest.main()