import unittest
from unittest.mock import patch, MagicMock
import json
import os
import shutil
from pathlib import Path
import networkx as nx

from milo.agents.function_summarizer_agent import FunctionSummarizerAgent
from milo.agents.module_summarizer_agent import ModuleSummarizerAgent
from milo.agents.architecture_summarizer_agent import ArchitectureSummarizerAgent
from milo.comprehend.semantic_indexer import SemanticIndexer
from milo.comprehend.browser import list_directory, tree_directory

class TestFunctionSummarizerAgent(unittest.TestCase):
    @patch('milo.agents.baseagent.OpenAI')
    def test_summarize_success(self, mock_openai):
        """
        Verifies that the agent correctly parses the expected JSON schema and
        strictly assigns the `miloagent` system prompt constraints.
        """
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        
        # Setup mock response
        mock_message = MagicMock()
        mock_message.content = '```json\n{"summary": "This is a factual test summary."}\n```'
        mock_message.tool_calls = None
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=mock_message)]
        mock_client.chat.completions.create.return_value = mock_response
        
        agent = FunctionSummarizerAgent()
        summary = agent.summarize(
            func_name="test_func",
            source_code="def test_func():\n    return True",
            callee_summaries={"helper": "Does something helpful."}
        )
        
        self.assertEqual(summary, "This is a factual test summary.")
        
        # Verify the call arguments and system prompt constraints
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        
        messages = call_kwargs['messages']
        self.assertTrue(
            any(m['role'] == 'system' and 'strictly factual code documentation assistant' in m['content'] for m in messages),
            "System prompt enforcing factual summarization is missing."
        )
        
        # Check user prompt formatting
        user_msg = next(m for m in messages if m['role'] == 'user')
        self.assertIn("Function: test_func", user_msg['content'])
        self.assertIn("helper: Does something helpful.", user_msg['content'])
        
        # Ensure it targets the generic miloagent model
        self.assertEqual(call_kwargs['model'], 'miloagent')


class TestModuleSummarizerAgent(unittest.TestCase):
    @patch('milo.agents.baseagent.OpenAI')
    def test_summarize_success(self, mock_openai):
        """
        Verifies that the agent correctly parses the expected JSON schema for module summaries.
        """
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        
        mock_message = MagicMock()
        mock_message.content = '```json\n{"summary": "This module does XYZ."}\n```'
        mock_message.tool_calls = None
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=mock_message)]
        mock_client.chat.completions.create.return_value = mock_response
        
        agent = ModuleSummarizerAgent()
        summary = agent.summarize(
            file_path="utils.py",
            function_summaries={"helper": "Does something helpful."}
        )
        
        self.assertEqual(summary, "This module does XYZ.")
        
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        user_msg = next(m for m in call_kwargs['messages'] if m['role'] == 'user')
        self.assertIn("File: utils.py", user_msg['content'])


class TestArchitectureSummarizerAgent(unittest.TestCase):
    @patch('milo.agents.baseagent.OpenAI')
    def test_summarize_flow_success(self, mock_openai):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        
        mock_message = MagicMock()
        mock_message.content = '```json\n{"summary": "This flow starts at main and calculates totals."}\n```'
        mock_message.tool_calls = None
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=mock_message)]
        mock_client.chat.completions.create.return_value = mock_response
        
        agent = ArchitectureSummarizerAgent()
        summary = agent.summarize_flow(
            entry_point="main.py::main",
            touched_modules=["main.py", "helper.py"],
            module_summaries={
                "main.py": "This module handles price calculation.",
                "helper.py": "This module provides discount logic."
            }
        )
        
        self.assertEqual(summary, "This flow starts at main and calculates totals.")
        
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        user_msg = next(m for m in call_kwargs['messages'] if m['role'] == 'user')
        self.assertIn("Entry Point: `main.py::main`", user_msg['content'])
        self.assertIn("- main.py: This module handles price calculation.", user_msg['content'])


class TestSemanticIndexer(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path('/tmp/semantic_indexer_test').resolve()
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir(parents=True)
        self.repo_path = self.tmp_dir / "repo"
        self.repo_path.mkdir()
        self.repomap_dir = self.tmp_dir / ".milo"
        self.repomap_dir.mkdir()

    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    @patch('milo.comprehend.semantic_indexer.ArchitectureSummarizerAgent')
    @patch('milo.comprehend.semantic_indexer.ModuleSummarizerAgent')
    @patch('milo.comprehend.semantic_indexer.get_repository')
    @patch('milo.comprehend.semantic_indexer.FunctionSummarizerAgent')
    @patch('milo.comprehend.semantic_indexer.RepoGraph')
    def test_indexer_topological_sort(self, mock_repo_graph_cls, mock_agent_cls, mock_get_repo, mock_module_agent_cls, mock_arch_agent_cls):
        """
        Ensures the indexer runs a reverse topological sort, processing leaf nodes first
        so that callers receive the summaries of their callees as context.
        """
        mock_agent = MagicMock()
        mock_agent.summarize.side_effect = ["Summary for C", "Summary for B", "Summary for A"]
        mock_agent_cls.return_value = mock_agent

        # Dependency Graph: A calls B, B calls C
        G = nx.DiGraph() # file_path is needed for layer 2+
        G.add_node("C", label="C", calls=[], is_third_party=False, defined_in="c.py")
        G.add_node("B", label="B", calls=["C"], is_third_party=False, defined_in="b.py")
        G.add_node("A", label="A", calls=["B"], is_third_party=False, defined_in="a.py")
        G.add_edge("A", "B")
        G.add_edge("B", "C")
        
        mock_rg = MagicMock()
        mock_rg.graph = G
        mock_rg.metadata = {"defined_mappings": {"A": {}, "B": {}, "C": {}}}
        mock_rg.fetch_source_snippet.return_value = "def dummy(): pass"
        mock_repo_graph_cls.return_value = mock_rg

        indexer = SemanticIndexer(str(self.repo_path), str(self.repomap_dir))
        indexer._run_layer1() # Only test layer 1 here

        # The topological sort (reversed) should process leaves first: C -> B -> A
        self.assertEqual(mock_agent.summarize.call_count, 3)
        calls = mock_agent.summarize.call_args_list
        
        self.assertEqual(calls[0][0][0], "C")
        self.assertEqual(calls[1][0][0], "B")
        self.assertEqual(calls[2][0][0], "A")

        # Check that B received C's summary as context
        self.assertEqual(calls[1][0][2], {"C": "Summary for C"})
        # Check that A received B's summary as context
        self.assertEqual(calls[2][0][2], {"B": "Summary for B"})


class TestBrowser(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path('/tmp/browser_test').resolve()
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir(parents=True)
        
        # Create a simple file structure
        (self.tmp_dir / "file1.txt").touch()
        dir1 = self.tmp_dir / "dir1"
        dir1.mkdir()
        (dir1 / "file2.txt").touch()
        
    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
            
    def test_list_directory(self):
        res = list_directory(str(self.tmp_dir))
        self.assertIn("dir1/", res)
        self.assertIn("file1.txt", res)
        
        # Path traversal check
        res_trav = list_directory(str(self.tmp_dir), "../some_other_dir")
        self.assertTrue(res_trav.startswith("Error: Cannot access paths outside"))
        
    def test_tree_directory(self):
        res = tree_directory(str(self.tmp_dir))
        self.assertTrue("browser_test" in res)
        self.assertIn("├── dir1", res)
        self.assertIn("│   └── file2.txt", res)
        self.assertIn("└── file1.txt", res)
        
        # Path traversal check
        res_trav = tree_directory(str(self.tmp_dir), "../some_other_dir")
        self.assertTrue(res_trav.startswith("Error: Cannot access paths outside"))

class TestSemanticIndexerE2E(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path('/tmp/semantic_indexer_e2e').resolve()
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir(parents=True)
        self.repo_path = self.tmp_dir / "repo"
        self.repo_path.mkdir()
        self.repomap_dir = self.tmp_dir / ".milo"
        self.repomap_dir.mkdir()

    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    def test_indexer_e2e_no_mocks(self):
        """
        Exploratory end-to-end test for SemanticIndexer without mocks.
        Creates a simple repo, runs the indexer, and verifies that
        the LLM (miloagent) successfully generates function summaries.
        """
        # 1. Create sample Python files
        helper_file = self.repo_path / "helper.py"
        helper_file.write_text('def get_discount():\n    """Returns a fixed 10% discount."""\n    return 0.1\n', encoding='utf-8')
        
        main_file = self.repo_path / "main.py"
        main_file.write_text('from helper import get_discount\n\ndef calculate_total(price):\n    """Calculates the total price after applying the discount."""\n    return price * (1 - get_discount())\n\ndef main():\n    """Main entry point."""\n    print(calculate_total(100))\n', encoding='utf-8')
        
        # 2. Run SemanticIndexer (this builds the RepoGraph and calls the LLM)
        print("\n--- Running SemanticIndexer E2E (Real LLM) ---")
        indexer = SemanticIndexer(str(self.repo_path), str(self.repomap_dir))
        indexer.run()
        
        # 3. Verify metadata.json was updated with summaries
        metadata_file = self.repomap_dir / "metadata.json"
        self.assertTrue(metadata_file.exists(), "metadata.json was not created.")
        
        with open(metadata_file, "r", encoding="utf-8") as f:
            metadata = json.load(f)
            
        defined_mappings = metadata.get("defined_mappings", {})
        
        # Ensure both functions exist and have a summary generated
        helper_key = "helper.py::get_discount"
        main_key = "main.py::calculate_total" # main() is also indexed
        
        self.assertIn(helper_key, defined_mappings)
        self.assertIn(main_key, defined_mappings)
        
        helper_summary = defined_mappings[helper_key].get("summary", "")
        main_summary = defined_mappings[main_key].get("summary", "")
        
        print(f"\n[E2E] {helper_key} Summary: {helper_summary}")
        print(f"[E2E] {main_key} Summary: {main_summary}")
        
        self.assertGreater(len(helper_summary), 0, "Summary for get_discount should not be empty")
        self.assertGreater(len(main_summary), 0, "Summary for calculate_total should not be empty")

        # 4. Verify Layer 2 file-level summaries
        file_mappings = metadata.get("file_mappings", {})
        self.assertIn("helper.py", file_mappings)
        self.assertIn("main.py", file_mappings)
        
        helper_file_summary = file_mappings["helper.py"].get("summary", "")
        main_file_summary = file_mappings["main.py"].get("summary", "")
        
        print(f"\n[E2E] helper.py Module Summary: {helper_file_summary}")
        print(f"[E2E] main.py Module Summary: {main_file_summary}")
        
        self.assertGreater(len(helper_file_summary), 0, "Module summary for helper.py should not be empty")
        self.assertGreater(len(main_file_summary), 0, "Module summary for main.py should not be empty")
        
        # 5. Verify Layer 3 architecture summaries
        arch_summaries = metadata.get("architecture_summaries", {})
        self.assertIn("main.py::main", arch_summaries)

        main_flow_summary = arch_summaries["main.py::main"].get("summary", "")
        print(f"\n[E2E] main.py::main Flow Summary: {main_flow_summary}")
        self.assertGreater(len(main_flow_summary), 0, "Architecture summary for main flow should not be empty")

if __name__ == '__main__':
    unittest.main()
