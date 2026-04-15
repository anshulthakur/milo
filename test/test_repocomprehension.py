import unittest
import json
import os
import shutil
from pathlib import Path

from milo.agents.repocomprehension import get_repocomprehension_agent
from milo.comprehend.semantic_indexer import SemanticIndexer

class TestRepoComprehensionAgent(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path('/tmp/repo_comprehension_test').resolve()
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir(parents=True)
        self.metadata_path = self.tmp_dir / "metadata.json"
        
        # Create a deterministic mock metadata map
        self.mock_metadata = {
            "lookup": {
                "main": ["main.py::main"], 
                "helper": ["helper.py::helper"]
            },
            "defined_mappings": {
                "main.py::main": {
                    "defined_in": "main.py", 
                    "summary": "Main function.", 
                    "calls": ["helper.py::helper"]
                },
                "helper.py::helper": {
                    "defined_in": "helper.py", 
                    "summary": "Helper function.", 
                    "calls": []
                }
            },
            "third_party_mappings": {},
            "architecture_summaries": {
                "main.py::main": {"summary": "System entry point that calls helper."}
            },
            "file_mappings": {
                "main.py": {"summary": "Main module."},
                "helper.py": {"summary": "Helper module."}
            }
        }
        
        with open(self.metadata_path, 'w') as f:
            json.dump(self.mock_metadata, f)
            
    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
            
    def test_agent_initialization(self):
        agent = get_repocomprehension_agent(str(self.tmp_dir), str(self.metadata_path))
        self.assertEqual(agent.name, "RepoComprehensionAgent")
        self.assertIn("view_architecture", agent.tools)
        self.assertIn("inspect_module", agent.tools)
        self.assertIn("inspect_call_flow", agent.tools)
        self.assertIn("create_file", agent.tools)
        self.assertIn("apply_diff", agent.tools)
        self.assertIn("replace_snippet", agent.tools)
        
    def test_view_architecture_tool(self):
        agent = get_repocomprehension_agent(str(self.tmp_dir), str(self.metadata_path))
        tool = agent.tools["view_architecture"]
        res = tool.func()
        self.assertIn("System entry point that calls helper.", res)
        
    def test_inspect_module_tool(self):
        agent = get_repocomprehension_agent(str(self.tmp_dir), str(self.metadata_path))
        tool = agent.tools["inspect_module"]
        res = tool.func(module_name="main.py")
        self.assertIn("Main module.", res)
        self.assertIn("main.py::main", res)
        self.assertIn("Main function.", res)
        
    def test_inspect_call_flow_tool(self):
        agent = get_repocomprehension_agent(str(self.tmp_dir), str(self.metadata_path))
        tool = agent.tools["inspect_call_flow"]
        res = tool.func(entry_function="main.py::main")
        self.assertIn("main.py::main", res)
        self.assertIn("helper.py::helper", res)
        self.assertIn("Helper function.", res)
        
    def test_replace_snippet_tool(self):
        agent = get_repocomprehension_agent(str(self.tmp_dir), str(self.metadata_path))
        tool = agent.tools["replace_snippet"]
        file_path = self.tmp_dir / "test_replace.txt"
        file_path.write_text("def hello():\n    print('Hello')\n", encoding="utf-8")
        
        res = tool.func(file_path="test_replace.txt", search_text="print('Hello')", replace_text="print('Hello World')")

        self.assertIn("Successfully replaced snippet", res)
        self.assertIn("-    print('Hello')", res)
        self.assertIn("+    print('Hello World')", res)
        self.assertEqual(file_path.read_text(encoding="utf-8"), "def hello():\n    print('Hello World')\n")
        
    def test_create_file_tool(self):
        agent = get_repocomprehension_agent(str(self.tmp_dir), str(self.metadata_path))
        tool = agent.tools["create_file"]
        res = tool.func(file_path="test_create.txt", content="Hello World")
        self.assertIn("Successfully created", res)
        file_path = self.tmp_dir / "test_create.txt"
        self.assertTrue(file_path.exists())
        self.assertEqual(file_path.read_text(encoding="utf-8"), "Hello World")
        
    def test_apply_diff_tool(self):
        agent = get_repocomprehension_agent(str(self.tmp_dir), str(self.metadata_path))
        tool = agent.tools["apply_diff"]
        file_path = self.tmp_dir / "test_patch.txt"
        file_path.write_text("line1\nline2\n", encoding="utf-8")
        
        diff_content = "--- test_patch.txt\n+++ test_patch.txt\n@@ -1,2 +1,2 @@\n line1\n-line2\n+line3\n"
        res = tool.func(file_path="test_patch.txt", diff=diff_content)
        self.assertIn("Successfully applied diff", res)
        self.assertEqual(file_path.read_text(encoding="utf-8"), "line1\nline3\n")

class TestRepoComprehensionE2E(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path('/tmp/repo_comp_e2e').resolve()
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir(parents=True)
        self.repo_path = self.tmp_dir / "repo"
        self.repo_path.mkdir()
        self.repomap_dir = self.tmp_dir / ".milo"
        self.repomap_dir.mkdir()

        helper_file = self.repo_path / "helper.py"
        helper_file.write_text('def get_discount():\n    return 0.1\n', encoding='utf-8')
        
        main_file = self.repo_path / "main.py"
        main_file.write_text('from helper import get_discount\n\ndef main():\n    print(get_discount())\n', encoding='utf-8')

    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    def test_agent_e2e(self):
        print("\n--- Running RepoComprehension E2E ---")
        indexer = SemanticIndexer(str(self.repo_path), str(self.repomap_dir))
        indexer.run()
        
        metadata_path = self.repomap_dir / "metadata.json"
        self.assertTrue(metadata_path.exists())
        
        agent = get_repocomprehension_agent(str(self.repo_path), str(metadata_path))
        response = agent.call("Use your tools to find the architecture entry points and summarize what the system does.")
        
        print(f"\n[E2E] RepoComprehension Agent Response: {response}")
        self.assertIsNotNone(response)
        
        # Ensure that it actually invoked the required tools during its thought process
        # The CompactContextProcessor transforms tool calls into assistant messages with specific content.
        tool_calls = [
            msg for msg in agent.history 
            if msg.get('role') == 'assistant' and '[Tool Call] Name: view_architecture' in msg.get('content', '')
        ]
        self.assertGreaterEqual(len(tool_calls), 1, "Agent should have called 'view_architecture' tool")
        
    def test_agent_e2e_edit(self):
        print("\n--- Running RepoComprehension E2E Edit ---")
        indexer = SemanticIndexer(str(self.repo_path), str(self.repomap_dir))
        indexer.run()
        
        metadata_path = self.repomap_dir / "metadata.json"
        agent = get_repocomprehension_agent(str(self.repo_path), str(metadata_path))
        
        # 1. Instruct LLM to create a new file
        response = agent.call("Use your tools to create a new file named 'new_script.py' with the content 'def hello():\\n    print(\"Hello\")\\n'. Do not do anything else.")
        self.assertIsNotNone(response)
        
        tool_calls_create = [
            msg for msg in agent.history 
            if msg.get('role') == 'assistant' and '[Tool Call] Name: create_file' in msg.get('content', '')
        ]
        self.assertGreaterEqual(len(tool_calls_create), 1, "Agent should have called 'create_file' tool")
        
        new_file_path = self.repo_path / "new_script.py"
        self.assertTrue(new_file_path.exists(), "new_script.py should have been created")
        self.assertIn('print("Hello")', new_file_path.read_text(encoding="utf-8"))
        
        # 2. Instruct LLM to modify the file using a snippet replacement
        response = agent.call("Now modify 'new_script.py' so that the function prints 'Hello World' instead of 'Hello'. Use the replace_snippet tool.")
        
        # Check for replace_snippet call
        tool_calls_replace = [
            msg for msg in agent.history 
            if msg.get('role') == 'assistant' and '[Tool Call] Name: replace_snippet' in msg.get('content', '')
        ]
        self.assertGreaterEqual(len(tool_calls_replace), 1, "Agent should have called 'replace_snippet' tool")
        
        self.assertIn('print("Hello World")', new_file_path.read_text(encoding="utf-8"))

if __name__ == '__main__':
    unittest.main()
