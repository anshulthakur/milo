import unittest
import networkx as nx
import os
import shutil
from milo.codesift.repograph import create_repograph
from milo.codesift.repobrowser import CallFlowAnalyzer, load_repo_graph

class TestCallFlowAnalyzer(unittest.TestCase):

    def setUp(self):
        """Set up a sample graph for testing by parsing the test_repo."""
        self.test_repo_path = "/home/anshul/devops/milo/tests/tmp/test_repo"
        self.output_path = "/home/anshul/devops/milo/tests/tmp/test_repobrowser_output"
        
        if os.path.exists(self.output_path):
            shutil.rmtree(self.output_path)
        os.makedirs(self.output_path)

        create_repograph(self.test_repo_path, save_path=self.output_path)
        
        self.G, _ = load_repo_graph(json_path=os.path.join(self.output_path, "metadata.json"))
        self.analyzer = CallFlowAnalyzer(self.G)

    def tearDown(self):
        """Clean up generated files."""
        if os.path.exists(self.output_path):
            shutil.rmtree(self.output_path)

    def test_find_entry_points(self):
        """Test that entry points (nodes with in-degree 0) are found correctly."""
        entry_points = self.analyzer.find_entry_points()
        
        expected_entry_points = [
            'file2.c::main',
            'file1.py::wrapper',
            'file1.py::MyClass.__init__',
            'file1.py::async_function',
            'file1.py::decorator',
            'file1.py::my_function',
            'file1.py::MyClass.greet',
            'file1.py::generator_function',
            'subdir/file6.py::AnotherClass.__init__',
            'subdir/file6.py::AnotherClass.__repr__',
            'subdir/file6.py::main',
            'file5.c::thread_function'
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

if __name__ == '__main__':
    unittest.main()