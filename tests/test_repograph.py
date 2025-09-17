import unittest
import os
import json
from pathlib import Path
from milo.codesift.repograph import create_repograph

class TestRepograph(unittest.TestCase):

    def setUp(self):
        self.test_repo_path = Path('tests/tmp/test_repo').resolve()
        self.save_path = Path('tests/tmp/test_repograph').resolve()
        self.save_path.mkdir(exist_ok=True)

    def tearDown(self):
        # for f in self.save_path.glob("*"):
        #     os.remove(f)
        # os.rmdir(self.save_path)
        pass

    def test_create_repograph_for_c(self):
        create_repograph(str(self.test_repo_path), save_path=str(self.save_path))
        with open(self.save_path / "metadata.json", "r") as f:
            metadata = json.load(f)

        # C assertions
        self.assertIn("file2.c::function1", metadata["defined_mappings"])
        self.assertIn("file2.c::function2", metadata["defined_mappings"])
        self.assertIn("file2.c::main", metadata["defined_mappings"])
        self.assertEqual(metadata["defined_mappings"]["file2.c::main"]["calls"], ["file2.c::function1", "file2.c::function2"])
        self.assertEqual(metadata["defined_mappings"]["file2.c::function2"]["calls"], ["file3.h::inline_function"])

    def test_create_repograph_for_python(self):
        create_repograph(str(self.test_repo_path), save_path=str(self.save_path))
        with open(self.save_path / "metadata.json", "r") as f:
            metadata = json.load(f)

        # Python assertions
        self.assertIn("file1.py::my_function", metadata["defined_mappings"])
        self.assertIn("file1.py::MyClass.greet", metadata["defined_mappings"])
        self.assertIn("subdir/file6.py::another_function", metadata["defined_mappings"])

    def test_create_repograph_for_c_python(self):
        create_repograph(str(self.test_repo_path), save_path=str(self.save_path))
        with open(self.save_path / "metadata.json", "r") as f:
            metadata = json.load(f)

        # C assertions
        self.assertIn("file2.c::function1", metadata["defined_mappings"])
        self.assertIn("file2.c::function2", metadata["defined_mappings"])
        self.assertIn("file2.c::main", metadata["defined_mappings"])
        self.assertEqual(metadata["defined_mappings"]["file2.c::main"]["calls"], ["file2.c::function1", "file2.c::function2"])
        self.assertEqual(metadata["defined_mappings"]["file2.c::function2"]["calls"], ["file3.h::inline_function"])

        # Python assertions
        self.assertIn("file1.py::my_function", metadata["defined_mappings"])
        self.assertIn("file1.py::MyClass.greet", metadata["defined_mappings"])
        self.assertIn("subdir/file6.py::another_function", metadata["defined_mappings"])

if __name__ == '__main__':
    unittest.main()
