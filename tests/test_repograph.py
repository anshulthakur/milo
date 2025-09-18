import unittest
import os
import json
from pathlib import Path
from milo.codesift.repograph import create_repograph
from milo.codesift.repobrowser import load_repo_graph, get_contextual_neighbors, fetch_source_snippet

class TestRepograph(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_repo_path = Path('tests/tmp/test_repo').resolve()
        cls.save_path = Path('tests/tmp/test_repograph').resolve()
        cls.save_path.mkdir(exist_ok=True)
        create_repograph(str(cls.test_repo_path), save_path=str(cls.save_path))
        cls.G, cls.metadata = load_repo_graph(str(cls.save_path / "metadata.json"))

    def test_create_repograph_for_c(self):
        # C assertions
        self.assertIn("file2.c::function1", self.metadata["defined_mappings"])
        self.assertIn("file2.c::function2", self.metadata["defined_mappings"])
        self.assertIn("file2.c::main", self.metadata["defined_mappings"])
        self.assertEqual(self.metadata["defined_mappings"]["file2.c::main"]["calls"], ["file2.c::function1", "file2.c::function2"])
        self.assertEqual(self.metadata["defined_mappings"]["file2.c::function2"]["calls"], ["file3.h::inline_function"])

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

if __name__ == '__main__':
    unittest.main()