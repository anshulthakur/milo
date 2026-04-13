import unittest
from unittest.mock import patch, MagicMock
import json
import os
import shutil
from pathlib import Path
import networkx as nx

from milo.agents.semantic_indexer import FunctionSummarizerAgent, SemanticIndexer

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

    @patch('milo.agents.semantic_indexer.get_repository')
    @patch('milo.agents.semantic_indexer.FunctionSummarizerAgent')
    @patch('milo.agents.semantic_indexer.RepoGraph')
    def test_indexer_topological_sort(self, mock_repo_graph_cls, mock_agent_cls, mock_get_repo):
        """
        Ensures the indexer runs a reverse topological sort, processing leaf nodes first
        so that callers receive the summaries of their callees as context.
        """
        mock_agent = MagicMock()
        mock_agent.summarize.side_effect = ["Summary for C", "Summary for B", "Summary for A"]
        mock_agent_cls.return_value = mock_agent

        # Dependency Graph: A calls B, B calls C
        G = nx.DiGraph()
        G.add_node("C", label="C", calls=[], is_third_party=False)
        G.add_node("B", label="B", calls=["C"], is_third_party=False)
        G.add_node("A", label="A", calls=["B"], is_third_party=False)
        G.add_edge("A", "B")
        G.add_edge("B", "C")
        
        mock_rg = MagicMock()
        mock_rg.graph = G
        mock_rg.metadata = {"defined_mappings": {"A": {}, "B": {}, "C": {}}}
        mock_rg.fetch_source_snippet.return_value = "def dummy(): pass"
        mock_repo_graph_cls.return_value = mock_rg

        indexer = SemanticIndexer(str(self.repo_path), str(self.repomap_dir))
        indexer.run()

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
        main_file.write_text('from helper import get_discount\n\ndef calculate_total(price):\n    """Calculates the total price after applying the discount."""\n    return price * (1 - get_discount())\n', encoding='utf-8')
        
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
        main_key = "main.py::calculate_total"
        
        self.assertIn(helper_key, defined_mappings)
        self.assertIn(main_key, defined_mappings)
        
        helper_summary = defined_mappings[helper_key].get("summary", "")
        main_summary = defined_mappings[main_key].get("summary", "")
        
        print(f"\n[E2E] {helper_key} Summary: {helper_summary}")
        print(f"[E2E] {main_key} Summary: {main_summary}")
        
        self.assertGreater(len(helper_summary), 0, "Summary for get_discount should not be empty")
        self.assertGreater(len(main_summary), 0, "Summary for calculate_total should not be empty")

if __name__ == '__main__':
    unittest.main()
