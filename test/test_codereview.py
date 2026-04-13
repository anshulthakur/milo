import os
import shutil
import json
import unittest
from git import Repo
from pathlib import Path
from unidiff import PatchSet, Hunk
from milo.codereview.diff import DiffUtils
from milo.utils.vcs import LocalGitProvider, FileSystemProvider
from milo.codereview.state import ReviewStore, Review, ReviewAnchor, ReviewStatus
from milo.codesift.parsers import Language
from milo.codesift.parsers.treesitter import Treesitter
from unittest.mock import patch, MagicMock
from milo.codereview.codereview import run_crab, ReviewEngine
from milo.agents.tools import FetchSourceArgs, GetMetadataArgs
from milo.codereview.models import CodeReview, DefectEnum
from milo.agents.baseagent import Agent
from milo.agents.tools import Tool
from pydantic import BaseModel


class TestDiffUtils(unittest.TestCase):
    def test_patch_fingerprint_stability(self):
        """Test that fingerprint remains same despite line number changes (context shifts)."""
        diff_text_1 = """
diff --git a/file.py b/file.py
index 123..456 100644
--- a/file.py
+++ b/file.py
@@ -1,3 +1,3 @@
 context
-old_code
+new_code
 context
"""
        patch1 = PatchSet(diff_text_1)
        hunk1 = patch1[0][0]
        fp1 = DiffUtils.compute_patch_fingerprint(hunk1)

        # Same change, different context/lines
        diff_text_2 = """
diff --git a/file.py b/file.py
index 123..456 100644
--- a/file.py
+++ b/file.py
@@ -10,3 +10,3 @@
 other_context
-old_code
+new_code
 other_context
"""
        patch2 = PatchSet(diff_text_2)
        hunk2 = patch2[0][0]
        fp2 = DiffUtils.compute_patch_fingerprint(hunk2)

        self.assertEqual(fp1, fp2, "Fingerprints should match for identical logical changes despite line shifts")

    def test_ast_fingerprint_python(self):
        """Test AST fingerprinting for Python code."""
        ts = Treesitter.create_treesitter(Language.PYTHON)
        
        # Case 1: Base function at the start of the file
        code1 = "def foo():\n    print('hello')"
        ts.parse(code1.encode('utf-8'))
        # Extract the function node specifically (ignoring module root)
        func1 = ts.tree.root_node.children[0]
        fp1 = DiffUtils.compute_ast_fingerprint(func1)
        
        # Case 2: Identical function, but shifted down (location change)
        # This mimics the 'context shift' stability tested in test_patch_fingerprint_stability
        code2 = "# Header comment\n\n\ndef foo():\n    print('hello')"
        ts.parse(code2.encode('utf-8'))
        # Find the function node (skipping comments/whitespace nodes)
        func2 = next(c for c in ts.tree.root_node.children if c.type == 'function_definition')
        fp2 = DiffUtils.compute_ast_fingerprint(func2)
        
        self.assertEqual(fp1, fp2, "AST fingerprint should be invariant to file location (line shifts)")

        # Case 3: Code with different semantics should differ
        code3 = "def foo():\n    print('world')"
        ts.parse(code3.encode('utf-8'))
        func3 = ts.tree.root_node.children[0]
        fp3 = DiffUtils.compute_ast_fingerprint(func3)
        self.assertNotEqual(fp1, fp3)

    def test_ast_fingerprint_c(self):
        """Test AST fingerprinting for C code, ensuring robustness to insignificant whitespace."""
        ts = Treesitter.create_treesitter(Language.C)
        
        code1 = "int main() { return 0; }"
        ts.parse(code1.encode('utf-8'))
        func1 = ts.tree.root_node.children[0]
        fp1 = DiffUtils.compute_ast_fingerprint(func1)
        
        # C is generally whitespace insensitive (except in strings/preproc)
        code2 = "int main() { \n  return 0; \n}"
        ts.parse(code2.encode('utf-8'))
        func2 = ts.tree.root_node.children[0]
        fp2 = DiffUtils.compute_ast_fingerprint(func2)
        
        self.assertEqual(fp1, fp2, "AST fingerprint should be robust to insignificant whitespace in C")

    def test_format_hunk_with_line_numbers(self):
        """Test that hunks are formatted with correct line numbers and prefixes."""
        diff_text = """
diff --git a/file.py b/file.py
index 111..222 100644
--- a/file.py
+++ b/file.py
@@ -10,2 +10,2 @@
 context
-removed
+added
"""
        patch = PatchSet(diff_text.strip())
        hunk = patch[0][0]
        
        formatted = DiffUtils.format_hunk_with_line_numbers(hunk)
        
        self.assertIn("  10   context", formatted) # 4 spaces for line number + 1 space + 1 prefix + 1 space + content
        self.assertIn("  11 - removed", formatted)
        self.assertIn("  11 + added", formatted)

    def test_format_hunk_with_virtual_lines(self):
        """Test that hunk lines are translated to 1-based sequential integers with a correct lookup map."""
        diff_text = """
diff --git a/file.py b/file.py
index 111..222 100644
--- a/file.py
+++ b/file.py
@@ -10,2 +10,3 @@
 context
-removed
+added1
+added2
"""
        patch = PatchSet(diff_text.strip())
        hunk = patch[0][0]
        
        formatted, line_map = DiffUtils.format_hunk_with_virtual_lines(hunk)
        
        # Virtual lines should be strictly 1-based sequential integers
        self.assertIn("   1   context", formatted)
        self.assertIn("   2 - removed", formatted)
        self.assertIn("   3 + added1", formatted)
        self.assertIn("   4 + added2", formatted)
        
        # Check exact mapping back to the actual target/source lines
        self.assertEqual(line_map[1], 10)  # context line maps to 10
        self.assertEqual(line_map[2], 11)  # removed line maps to source line 11
        self.assertEqual(line_map[3], 11)  # added1 maps to target line 11
        self.assertEqual(line_map[4], 12)  # added2 maps to target line 12

    def test_format_code_with_virtual_lines(self):
        """Test entire code blocks mapping 1-based integers to AST absolute lines."""
        code = "def foo():\n    pass\n    return 0"
        start_line = 45  # Let's pretend this function was defined at line 45 in the file
        
        formatted, line_map = DiffUtils.format_code_with_virtual_lines(code, start_line_no=start_line)
        
        self.assertIn("   1 | def foo():", formatted)
        self.assertIn("   2 |     pass", formatted)
        self.assertIn("   3 |     return 0", formatted)
        
        self.assertEqual(line_map[1], 45)
        self.assertEqual(line_map[3], 47)

class TestStateManager(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path('/tmp/state_manager_test')
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir(parents=True)
        self.store_path = self.tmp_dir / "reviews.json"

    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    def test_persistence(self):
        store = ReviewStore(self.store_path)
        
        anchor = ReviewAnchor(
            file_path="src/main.py",
            symbol_name="process_request",
            symbol_type="function",
            patch_fingerprint="abc123hash",
            ast_fingerprint="ast_hash_xyz",
            line_range_start=10,
            line_range_end=15
        )
        
        review = Review(anchor=anchor)
        review.add_bot_comment("Fix this.")
        
        store.add_review(review)
        
        # Reload
        new_store = ReviewStore(self.store_path)
        loaded_review = new_store.get_review(review.id)
        
        self.assertIsNotNone(loaded_review)
        self.assertEqual(loaded_review.anchor.file_path, "src/main.py")
        self.assertEqual(loaded_review.anchor.symbol_name, "process_request")
        self.assertEqual(loaded_review.anchor.ast_fingerprint, "ast_hash_xyz")
        self.assertEqual(len(loaded_review.conversation), 1)
        self.assertEqual(loaded_review.conversation[0].content, "Fix this.")

    def test_find_matching_review(self):
        store = ReviewStore(self.store_path)
        anchor = ReviewAnchor(
            file_path="test.py", 
            symbol_name="my_func",
            symbol_type="function",
            patch_fingerprint="hash1", 
            ast_fingerprint="ast1",
            line_range_start=1, 
            line_range_end=2
        )
        review = Review(anchor=anchor)
        store.add_review(review)
        
        match = store.find_matching_review("test.py", "my_func")
        self.assertIsNotNone(match)
        self.assertEqual(match.id, review.id)
        
        no_match = store.find_matching_review("test.py", "other_func")
        self.assertIsNone(no_match)

class TestLocalGitProvider(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path('/tmp/git_provider_test').resolve()
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir(parents=True)
        self.repo = Repo.init(self.tmp_dir)
        self.git_file = "test.txt"
        self.file_path = self.tmp_dir / self.git_file

    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    def test_get_changes(self):
        provider = LocalGitProvider(str(self.tmp_dir))
        
        with open(self.file_path, 'w') as f:
            f.write("line1\n")
        self.repo.index.add([str(self.git_file)])
        c1 = self.repo.index.commit("Initial")
        
        with open(self.file_path, 'w') as f:
            f.write("line1\nline2\n")
        self.repo.index.add([str(self.git_file)])
        c2 = self.repo.index.commit("Update")
        
        changes = provider.get_changes(c1.hexsha, c2.hexsha)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].path, self.git_file)

    def test_get_changes_staged(self):
        provider = LocalGitProvider(str(self.tmp_dir))
        
        # Initial commit
        with open(self.file_path, 'w') as f:
            f.write("line1\n")
        self.repo.index.add([str(self.git_file)])
        c1 = self.repo.index.commit("Initial")
        
        # Stage a change
        with open(self.file_path, 'w') as f:
            f.write("line1\nline2\n")
        self.repo.index.add([str(self.git_file)])
        
        # Diff HEAD vs Index
        changes = provider.get_changes(c1.hexsha, 'index')
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].path, self.git_file)
        
        # Verify we picked up the addition
        hunk = changes[0][0]
        self.assertTrue(any(line.value.strip() == 'line2' for line in hunk if line.is_added))

    def test_get_file_content_staged(self):
        provider = LocalGitProvider(str(self.tmp_dir))
        
        # Initial commit
        with open(self.file_path, 'w') as f:
            f.write("line1\n")
        self.repo.index.add([str(self.git_file)])
        self.repo.index.commit("Initial")
        
        # Stage a change
        with open(self.file_path, 'w') as f:
            f.write("line1\nline2\n")
        self.repo.index.add([str(self.git_file)])
        
        # Test with relative path
        content = provider.get_file_content(self.git_file, 'index')
        self.assertEqual(content, "line1\nline2\n")

        # Test with absolute path (verifies relpath logic)
        content_abs = provider.get_file_content(str(self.file_path), 'index')
        self.assertEqual(content_abs, "line1\nline2\n")

class TestReviewEngine(unittest.TestCase):
    def test_virtual_line_translation(self):
        """Verify ReviewEngine dynamically maps virtual line numbers and guards against hallucinated out-of-bound references."""
        mock_agent = MagicMock()
        
        # Simulate LLM returning citations for virtual lines: 3 and 10
        review_payload = [
            CodeReview(type=DefectEnum.bug, file="app.py", line=3, description="Valid citation", suggestion="Fix").model_dump(),
            CodeReview(type=DefectEnum.style, file="app.py", line=10, description="Hallucinated citation", suggestion="Fallback needed").model_dump()
        ]
        mock_agent.call.return_value = json.dumps(review_payload)
        
        engine = ReviewEngine(mock_agent)
        
        # Provide a synthetic line_map corresponding to what DiffUtils would generate
        mock_line_map = {
            1: 100,
            2: 101,
            3: 105, # Gap exists due to diff jumps
            4: 106
        }
        
        reviews = engine.generate_reviews(
            lang="python",
            code="def foo(): pass",
            file_path="app.py",
            hunk_text="+def foo(): pass",
            line_map=mock_line_map
        )
        
        self.assertEqual(len(reviews), 2)
        # Virtual Line 3 should map strictly to actual line 105
        self.assertEqual(reviews[0].line, 105)
        # Virtual Line 10 hallucinated outside bounds; engine must fallback safely to the first tracked line (100)
        self.assertEqual(reviews[1].line, 100)

class TestFileSystemProvider(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path('/tmp/fs_provider_test').resolve()
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir(parents=True)
        self.file_path = self.tmp_dir / "test.txt"

    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    def test_get_changes(self):
        with open(self.file_path, 'w') as f:
            f.write("line1\nline2\n")
        
        provider = FileSystemProvider(str(self.tmp_dir))
        changes = provider.get_changes("HEAD~1", "HEAD")
        self.assertEqual(len(changes), 1)
        self.assertTrue(changes[0].path.endswith("test.txt"))
        
        hunk = changes[0][0]
        self.assertTrue(any("line1" in line.value for line in hunk if line.is_added))

class TestCrabIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path('/tmp/crab_integration_test').resolve()
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir(parents=True)

        # Setup Git Repo
        self.repo_path = self.tmp_dir / "repo"
        self.repo_path.mkdir()
        self.repo = Repo.init(self.repo_path)
        
        # Configure git user
        with self.repo.config_writer() as cw:
            cw.set_value("user", "name", "Test User").release()
            cw.set_value("user", "email", "test@example.com").release()

        # Initial file
        self.py_file_path = self.repo_path / "app.py"
        self.py_file_path.write_text("def main():\n    print('hello')\n")
        self.repo.index.add(["app.py"])
        self.repo.index.commit("Initial commit")

        # Standalone file setup
        self.standalone_path = self.tmp_dir / "standalone"
        self.standalone_path.mkdir()
        self.standalone_file = self.standalone_path / "standalone_app.py"
        self.standalone_file.write_text("def process_data():\n    return 1\n")

    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    @patch('milo.codereview.codereview.get_codereview_agent')
    def test_run_crab_git_mode(self, mock_get_agent):
        # 1. Setup mock agent
        mock_agent_instance = MagicMock()
        mock_get_agent.return_value = mock_agent_instance
        review_payload = [
            CodeReview(
                type=DefectEnum.bug,
                file="app.py",
                line=2,
                description="Hardcoded string",
                suggestion="Use a constant"
            ).model_dump()
        ]
        
        def agent_side_effect(payload):
            if "OPEN or RESOLVED" in json.loads(payload)["request"]:
                return json.dumps([])
            return json.dumps(review_payload)
        mock_agent_instance.call.side_effect = agent_side_effect

        # 2. Modify a file and commit
        self.py_file_path.write_text("def main():\n    print('hello world') # changed\n")
        self.repo.index.add(["app.py"])
        self.repo.index.commit("Second commit")

        # 3. Run CRAB in git mode
        file_manager = LocalGitProvider(str(self.repo_path))
        run_crab(file_manager=file_manager, repo_root=str(self.repo_path))

        # 4. Assertions for first run
        mock_agent_instance.call.assert_called_once()
        
        # Verify the payload sent to the agent
        call_args = mock_agent_instance.call.call_args
        self.assertIsNotNone(call_args, "Agent should have been called")
        payload_json = call_args[0][0]
        payload = json.loads(payload_json)
        
        self.assertEqual(payload.get("file_path"), "app.py")
        self.assertIn("diff_hunk", payload)
        self.assertIn("print('hello world') # changed", payload["diff_hunk"])
        self.assertIn("You are reviewing changes in `app.py`", payload["request"])

        review_store_path = self.repo_path / ".milo" / "reviews.json"
        self.assertTrue(review_store_path.exists())
        store = ReviewStore(review_store_path)
        reviews = store.get_reviews_by_file("app.py")
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].anchor.symbol_name, "main")
        original_ast_fingerprint = reviews[0].anchor.ast_fingerprint

        # 5. Run again. The diff is the same, so the AST fingerprint check should prevent re-review.
        mock_agent_instance.call.reset_mock()
        run_crab(file_manager=file_manager, repo_root=str(self.repo_path))
        
        # Agent should NOT be called again.
        mock_agent_instance.call.assert_not_called()

        # 6. Now, modify the function's AST and commit.
        self.py_file_path.write_text("def main():\n    print('hello world again') # AST changed\n")
        self.repo.index.add(["app.py"])
        self.repo.index.commit("Third commit")

        run_crab(file_manager=file_manager, repo_root=str(self.repo_path))
        
        # Agent should be called TWICE because AST fingerprint changed (Phase 1 + Phase 2).
        self.assertEqual(mock_agent_instance.call.call_count, 2)
        
        # Verify the anchor was updated
        store.load()
        updated_reviews = store.get_reviews_by_file("app.py")
        self.assertEqual(len(updated_reviews), 2)
        self.assertNotEqual(original_ast_fingerprint, updated_reviews[0].anchor.ast_fingerprint)

    @patch('milo.codereview.codereview.get_codereview_agent')
    def test_run_crab_standalone_mode(self, mock_get_agent):
        # 1. Setup mock agent
        mock_agent_instance = MagicMock()
        mock_get_agent.return_value = mock_agent_instance
        rel_file_path = self.standalone_file.name
        review_payload = [
            CodeReview(
                type=DefectEnum.style,
                file=rel_file_path,
                line=1,
                description="Function name too generic",
                suggestion="Use a more descriptive name"
            ).model_dump()
        ]
        
        def agent_side_effect(payload):
            if "OPEN or RESOLVED" in json.loads(payload)["request"]:
                return json.dumps([])
            return json.dumps(review_payload)
        mock_agent_instance.call.side_effect = agent_side_effect

        file_manager = FileSystemProvider(str(self.standalone_path))
        # 2. Run CRAB in standalone mode for the first time
        run_crab(file_manager=file_manager, repo_root=str(self.standalone_path), files=[str(self.standalone_file)])

        # 3. Assertions
        mock_agent_instance.call.assert_called_once()
        review_store_path = self.standalone_path / ".milo" / "reviews.json"
        self.assertTrue(review_store_path.exists())
        store = ReviewStore(review_store_path)
        reviews = store.get_reviews_by_file(rel_file_path)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].anchor.symbol_name, "process_data")
        original_ast_fingerprint = reviews[0].anchor.ast_fingerprint

        # 4. Run again without changes
        mock_agent_instance.call.reset_mock()
        run_crab(file_manager=file_manager, repo_root=str(self.standalone_path), files=[str(self.standalone_file)])
        mock_agent_instance.call.assert_not_called()

        # 5. Modify the file and run again
        self.standalone_file.write_text("def process_data():\n    # changed\n    return 2\n")
        run_crab(file_manager=file_manager, repo_root=str(self.standalone_path), files=[str(self.standalone_file)])
        self.assertEqual(mock_agent_instance.call.call_count, 2)

        # Check that the review was updated
        store.load()
        updated_reviews = store.get_reviews_by_file(rel_file_path)
        self.assertEqual(len(updated_reviews), 2)
        self.assertNotEqual(original_ast_fingerprint, updated_reviews[0].anchor.ast_fingerprint)

    @patch('milo.codereview.codereview.get_codereview_agent')
    def test_run_crab_staged_mode(self, mock_get_agent):
        # 1. Setup mock agent
        mock_agent_instance = MagicMock()
        mock_get_agent.return_value = mock_agent_instance
        review_payload = [
            CodeReview(
                type=DefectEnum.bug,
                file="app.py",
                line=2,
                description="Staged change issue",
                suggestion="Fix staged change"
            ).model_dump()
        ]
        
        def agent_side_effect(payload):
            if "OPEN or RESOLVED" in json.loads(payload)["request"]:
                return json.dumps([])
            return json.dumps(review_payload)
        mock_agent_instance.call.side_effect = agent_side_effect

        # 2. Modify a file and STAGE it, but do not commit
        self.py_file_path.write_text("def main():\n    print('staged change')\n")
        self.repo.index.add(["app.py"])

        # 3. Run CRAB in staged mode
        file_manager = LocalGitProvider(str(self.repo_path))
        run_crab(file_manager=file_manager, repo_root=str(self.repo_path), review_staged=True)

        # 4. Assertions
        mock_agent_instance.call.assert_called_once()
        review_store_path = self.repo_path / ".milo" / "reviews.json"
        self.assertTrue(review_store_path.exists())
        store = ReviewStore(review_store_path)
        reviews = store.get_reviews_by_file("app.py")
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].anchor.symbol_name, "main")
        self.assertIn("Staged change issue", reviews[0].conversation[0].content)

    def test_tool_arguments_support_file_path(self):
        """
        Verify that the tool argument models used by the agent have been updated
        to support file_path/file_hint.
        """
        # FetchSourceArgs
        args = FetchSourceArgs(fn_name="main", file_path="app.py")
        self.assertEqual(args.file_path, "app.py")

        # GetMetadataArgs
        meta_args = GetMetadataArgs(fn_name="main", file_path="app.py")
        self.assertEqual(meta_args.file_path, "app.py")

    @patch('milo.codereview.codereview.get_codereview_agent')
    @patch('builtins.print')
    def test_end_to_end_virtual_line_mapping(self, mock_print, mock_get_agent):
        """
        Comprehensive E2E test verifying changes translated into virtual diff hunks,
        interpreted by an LLM mock on relative coordinates, and safely transformed back
        to actual source target lines in the output thread state.
        """
        # 1. Establish an initial file so treesitter anchors exist
        initial_code = (
            "def calculate_tax(amount):\n"   # Line 1
            "    tax = 0\n"                  # Line 2
            "    if amount > 100:\n"         # Line 3
            "        tax = amount * 0.2\n"   # Line 4
            "    else:\n"                    # Line 5
            "        tax = amount * 0.1\n"   # Line 6
            "    return tax\n"               # Line 7
        )
        self.py_file_path.write_text(initial_code)
        self.repo.index.add(["app.py"])
        self.repo.index.commit("Add calculate_tax")

        # 2. Modify the file to trigger a Git Diff hunk
        modified_code = (
            "def calculate_tax(amount):\n"   
            "    tax = 0\n"                  
            "    if amount > 100:\n"         
            "        tax = amount * 0.3\n"   # Line 4 (Changed target)
            "    else:\n"                    
            "        tax = amount * 0.0\n"   # Line 6 (Changed target)
            "    return tax\n"               
        )
        self.py_file_path.write_text(modified_code)
        self.repo.index.add(["app.py"])
        self.repo.index.commit("Modify tax rates")

        # 3. Simulate the agent pointing at virtual diff coordinates
        # In the resulting unified diff, virtual line 5 aligns with target line 4
        # and virtual line 8 aligns with target line 6.
        mock_agent_instance = MagicMock()
        mock_get_agent.return_value = mock_agent_instance
        
        review_payload = [
            CodeReview(type=DefectEnum.bug, file="app.py", line=5, description="High tax rate", suggestion="Fix").model_dump(),
            CodeReview(type=DefectEnum.bug, file="app.py", line=8, description="Zero tax rate", suggestion="Fix").model_dump()
        ]
        mock_agent_instance.call.return_value = json.dumps(review_payload)

        file_manager = LocalGitProvider(str(self.repo_path))
        
        # Execute code review orchestrator
        run_crab(file_manager=file_manager, repo_root=str(self.repo_path))

        # 4. Verify Final State captures mapped lines (4 and 6), NOT virtual lines (5 and 8)
        printed_messages = [call.args[0] for call in mock_print.call_args_list if isinstance(call.args[0], str)]
        
        self.assertTrue(any("[bug] app.py:4 - High tax rate" in msg for msg in printed_messages),
                        "Failed to translate virtual line 5 to actual target line 4.")
        self.assertTrue(any("[bug] app.py:6 - Zero tax rate" in msg for msg in printed_messages),
                        "Failed to translate virtual line 8 to actual target line 6.")

    @patch('milo.codereview.codereview.get_codereview_agent')
    def test_hunk_matching_adjacent_functions(self, mock_get_agent):
        """
        Test that changes are correctly attributed to the modified function
        even if the unified diff context overlaps with an adjacent function.
        """
        # 1. Setup C file with two adjacent functions
        c_file_path = self.repo_path / "app.c"
        initial_code = (
            "int func1() {\n"
            "    return 1;\n"
            "}\n"
            "\n"
            "void func2(int a) {\n"
            "    printf(\"%d\", a);\n"
            "}\n"
        )
        c_file_path.write_text(initial_code)
        self.repo.index.add(["app.c"])
        self.repo.index.commit("Initial commit app.c")

        # 2. Modify func2. The diff context will include the end of func1.
        modified_code = initial_code.replace('printf("%d", a);', 'printf("value: %d", a);\n    return;')
        c_file_path.write_text(modified_code)
        self.repo.index.add(["app.c"])
        self.repo.index.commit("Modify func2")

        # 3. Setup mock agent
        mock_agent_instance = MagicMock()
        mock_get_agent.return_value = mock_agent_instance
        review_payload = [CodeReview(type=DefectEnum.bug, file="app.c", line=6, description="Test issue", suggestion="Fix").model_dump()]
        mock_agent_instance.call.return_value = json.dumps(review_payload)

        # 4. Run CRAB
        file_manager = LocalGitProvider(str(self.repo_path))
        
        # Explicitly verify the test's diff premise: 
        # Ensure git generated exactly 1 hunk, and its context naturally overlaps with func1's closing brace
        changes = file_manager.get_changes("HEAD~1", "HEAD")
        self.assertEqual(len(changes[0]), 1, "Expected exactly 1 hunk due to context overlap")
        self.assertTrue(any(line.is_context and "}" in line.value for line in changes[0][0]), "Expected hunk context to contain func1's closing brace")
        
        run_crab(file_manager=file_manager, repo_root=str(self.repo_path))

        # 5. Verify ReviewStore captured the correct symbol (func2, NOT func1)
        store = ReviewStore(self.repo_path / ".milo" / "reviews.json")
        reviews = store.get_reviews_by_file("app.c")
        
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].anchor.symbol_name, "func2")

    @patch('milo.codereview.codereview.get_codereview_agent')
    def test_hunk_matching_multiple_functions(self, mock_get_agent):
        """
        Test that a single unfocused diff hunk spanning modifications across 
        multiple functions correctly maps to all modified functions based on score.
        """
        # 1. Setup C file with two adjacent functions
        c_file_path = self.repo_path / "app.c"
        initial_code = (
            "void func1() {\n"
            "    int a = 1;\n"
            "}\n"
            "void func2() {\n"
            "    int b = 2;\n"
            "}\n"
        )
        c_file_path.write_text(initial_code)
        self.repo.index.add(["app.c"])
        self.repo.index.commit("Initial commit app.c multiple")

        # 2. Modify both functions. The context overlap will cause Git to output a single hunk.
        modified_code = initial_code.replace('int a = 1;', 'int a = 1;\n    a++;').replace('int b = 2;', 'int b = 2;\n    b++;')
        c_file_path.write_text(modified_code)
        self.repo.index.add(["app.c"])
        self.repo.index.commit("Modify both functions")

        # 3. Setup mock agent
        mock_agent_instance = MagicMock()
        mock_get_agent.return_value = mock_agent_instance
        review_payload = [CodeReview(type=DefectEnum.bug, file="app.c", line=3, description="Test issue", suggestion="Fix").model_dump()]
        mock_agent_instance.call.return_value = json.dumps(review_payload)

        # 4. Run CRAB
        file_manager = LocalGitProvider(str(self.repo_path))
        
        # Explicitly verify the test's diff premise: 
        # Both functions modified within 3 lines of each other should merge into exactly ONE unfocused hunk
        changes = file_manager.get_changes("HEAD~1", "HEAD")
        self.assertEqual(len(changes[0]), 1, "Expected both modifications to be merged into a single unfocused hunk")
        hunk_text = str(changes[0][0])
        self.assertTrue("a++" in hunk_text and "b++" in hunk_text, "Hunk must contain modifications for both functions")

        run_crab(file_manager=file_manager, repo_root=str(self.repo_path))

        # 5. Verify ReviewStore captured both symbols (func1 and func2)
        store = ReviewStore(self.repo_path / ".milo" / "reviews.json")
        reviews = store.get_reviews_by_file("app.c")
        
        self.assertEqual(len(reviews), 2)
        symbol_names = [r.anchor.symbol_name for r in reviews]
        self.assertIn("func1", symbol_names)
        self.assertIn("func2", symbol_names)

    @patch('milo.codereview.codereview.get_codereview_agent')
    def test_hunk_matching_dpdk_c_fragment(self, mock_get_agent):
        """
        Test case to reproduce the specific DPDK-style C fragment parsing issue,
        checking if macros or syntax errors drop the function definition from the AST.
        """
        c_file_path = self.repo_path / "main.c"
        
        initial_code = (
            '#include "npf/wigw/wigw_init.h"\n'
            '#include "ip_icmp.h"\n\n'
            'packet_input_t packet_input_func __hot_data = ether_input_no_dyn_feats;\n\n'
            'static inline bool forwarding_lcore(const struct lcore_conf *conf)\n'
            '{\n'
            '\treturn !bitmask_isempty(&conf->portmask);\n'
            '}\n\n'
            'static inline\n'
            'bool forwarding_or_crypto_engine_lcore(const struct lcore_conf *conf)\n'
            '{\n'
            '\treturn conf->do_crypto || forwarding_lcore(conf);\n'
            '}\n\n'
            '/* Free any packets left in the rings or bursts */\n'
            'void pkt_ring_empty(portid_t port)\n'
            '{\n'
            '\tstruct rte_ring *ring;\n'
            '\tstruct rte_mbuf *m;\n'
            '\tunsigned int lcore;\n'
            '\tuint8_t r;\n\n'
            '\tfor (r = 0; r < port_config[port].max_rings; r++) {\n'
            '\t\tring = port_config[port].pkt_ring[r];\n\n'
            '\t\twhile (rte_ring_sc_dequeue(ring, (void **)&m) == 0)\n'
            '\t\t\trte_pktmbuf_free(m);\n'
            '\t}\n'
            '}\n\n'
            '/* Check for packets from network ports */\n'
            'static void __hot_func\n'
            'poll_receive_queues(struct lcore_conf *conf)\n'
            '{\n'
            '\tstruct crypto_pkt_buffer *cpb = RTE_PER_LCORE(crypto_pkt_buffer);\n'
            '\tuint16_t high_rxq;\n'
            '\tunsigned int i;\n\n'
            '\thigh_rxq = CMM_LOAD_SHARED(conf->high_rxq);\n'
            '\tfor (i = 0; i < high_rxq; i++) {\n'
            '\t\tstruct lcore_rx_queue *rxq = &conf->rx_poll[i];\n'
            '\t\tstruct rte_mbuf *rx_pkts[RX_PKT_BURST];\n'
            '\t\tportid_t portid;\n'
            '\t\tuint16_t nb;\n\n'
            '\t\tportid = CMM_LOAD_SHARED(rxq->portid);\n\n'
            '\t\t/* port unused or not up yet? */\n'
            '\t\tif (unlikely(portid == NO_OWNER) ||\n'
            '\t\t    unlikely(!bitmask_isset(&active_port_mask, portid)))\n'
            '\t\t\tcontinue;\n'
            '\t}\n'
            '}\n'
        )

        c_file_path.write_text(initial_code)
        self.repo.index.add(["main.c"])
        self.repo.index.commit("Initial commit main.c")

        modified_code = (
            '#include "npf/wigw/wigw_init.h"\n'
            '#include "ip_icmp.h"\n\n'
            '#include <stdio.h>\n'
            '#include checkcheckech\n\n'
            'packet_input_t packet_input_func __hot_data = ether_input_no_dyn_feats;\n\n'
            'static inline bool forwarding_lcore(const struct lcore_conf *conf)\n'
            '{\n'
            '\treturn !bitmask_isempty(&conf->portmask);\n'
            '}\n\n'
            'static inline\n'
            'bool forwarding_or_crypto_engine_lcore(const struct lcore_conf *conf)\n'
            '{\n'
            '\treturn conf->do_crypto || forwarding_lcore(conf);\n'
            '}\n\n'
            '/* Free any packets left in the rings or bursts */\n'
            'void pkt_ring_emptied(portid_t port)\n'
            '{\n'
            '\tstruct rte_ring *ring;\n'
            '\tstruct rte_mbuf *m;\n'
            '\tunsigned int lcore;\n'
            '\tuint8_t r;\n\n'
            '\tfor (r = 0; r < port_config[port].max_rings; r++) {\n'
            '\t\tring = port_config[port].pkt_ring[r];\n\n'
            '\t\twhile (rte_ring_sc_dequeue(ring, (void **)&m) == 0)\n'
            '\t\t\trte_pktmbuf_free(m);\n'
            '\t}\n'
            '}\n\n'
            '/* Check for packets from network ports */\n'
            'static void __hot_func\n'
            'poll_receive_queues(struct lcore_conf *conf)\n'
            '{\n'
            '\tstruct crypto_pkt_buffer *cpb = RTE_PER_LCORE(crypto_pkt_buffer);\n'
            '\tuint16_t high_rxq;\n'
            '\tunsigned int i;\n'
            '\tint port_id;\n\n'
            '\thigh_rxq = CMM_LOAD_SHARED(conf->high_rxq);\n'
            '\tfor (i = 0; i < high_rxq; i++) {\n'
            '\t\tstruct lcore_rx_queue *rxq = &conf->rx_poll[i];\n'
            '\t\tstruct rte_mbuf *rx_pkts[RX_PKT_BURST];\n'
            '\t\tportid_t portid;\n'
            '\t\tuint16_t nb;\n\n'
            '\t\tportid = CMM_LOAD_SHARED(rxq->portid);\n\n'
            '\t\tport_id = 0;\n\n'
            '\t\t/* port unused or not up yet? */\n'
            '\t\tif (unlikely(portid == NO_OWNER) ||\n'
            '\t\t    unlikely(!bitmask_isset(&active_port_mask, portid)))\n'
            '\t\t\tcontinue;\n'
            '\t}\n'
            '}\n'
        )

        c_file_path.write_text(modified_code)
        self.repo.index.add(["main.c"])
        self.repo.index.commit("Modify main.c")

        mock_agent_instance = MagicMock()
        mock_get_agent.return_value = mock_agent_instance
        review_payload = [CodeReview(type=DefectEnum.bug, file="main.c", line=5, description="Test issue", suggestion="Fix").model_dump()]
        mock_agent_instance.call.return_value = json.dumps(review_payload)

        file_manager = LocalGitProvider(str(self.repo_path))
        
        run_crab(file_manager=file_manager, repo_root=str(self.repo_path))

        store = ReviewStore(self.repo_path / ".milo" / "reviews.json")
        reviews = store.get_reviews_by_file("main.c")
        
        symbol_names = [r.anchor.symbol_name for r in reviews]
        
        print(f"\n[DEBUG] Evaluated Symbols: {symbol_names}\n")
        
        # Test will fail if it matched the previous context function due to Tree-sitter AST dropping `pkt_ring_emptied`
        self.assertNotIn("forwarding_or_crypto_engine_lcore", symbol_names, "Incorrectly anchored to the context function!")
        self.assertIn("pkt_ring_emptied", symbol_names, "Failed to map changes to pkt_ring_emptied")

    @patch('milo.codereview.codereview.get_codereview_agent')
    def test_hunk_matching_full_dpdk_file(self, mock_get_agent):
        """
        Test case using the full test.c file to reproduce the exact DPDK-style 
        C parsing issue and verify the proximity matching behavior on a real codebase size.
        """
        test_c_path = Path(__file__).parent / "test.c"
        if not test_c_path.exists():
            self.skipTest("test.c not found")
            
        modified_code = test_c_path.read_text(encoding='utf-8')
        
        # Reconstruct the original code to form the base commit
        initial_code = modified_code.replace('#include <stdio.h>\n#include checkcheckech\n', '')
        initial_code = initial_code.replace('void pkt_ring_emptied(portid_t port)', 'void pkt_ring_empty(portid_t port)')
        initial_code = initial_code.replace('\tint port_id;\n', '')
        initial_code = initial_code.replace('\t\tport_id = 0;\n', '')

        # 1. Setup git repo
        c_file_path = self.repo_path / "test.c"
        c_file_path.write_text(initial_code)
        self.repo.index.add(["test.c"])
        self.repo.index.commit("Initial commit test.c")

        # 2. Apply modifications
        c_file_path.write_text(modified_code)
        self.repo.index.add(["test.c"])
        self.repo.index.commit("Modify test.c")

        # 3. Setup mock agent
        mock_agent_instance = MagicMock()
        mock_get_agent.return_value = mock_agent_instance
        review_payload = [CodeReview(type=DefectEnum.bug, file="test.c", line=515, description="Test issue", suggestion="Fix").model_dump()]
        mock_agent_instance.call.return_value = json.dumps(review_payload)

        # 4. Run CRAB
        file_manager = LocalGitProvider(str(self.repo_path))
        run_crab(file_manager=file_manager, repo_root=str(self.repo_path))

        # 5. Assertions
        store = ReviewStore(self.repo_path / ".milo" / "reviews.json")
        reviews = store.get_reviews_by_file("test.c")
        
        symbol_names = [r.anchor.symbol_name for r in reviews]
        print(f"\n[DEBUG] Full file Evaluated Symbols: {symbol_names}\n")
        
        self.assertIn("pkt_ring_emptied", symbol_names, "Failed to map changes to pkt_ring_emptied")
        self.assertIn("poll_receive_queues", symbol_names, "Failed to map changes to poll_receive_queues")

class TestCrabCoverageMocked(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path('/tmp/crab_coverage').resolve()
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir(parents=True)

        # 1. Setup Git directory
        self.repo_dir = self.tmp_dir / "repo"
        self.repo_dir.mkdir()
        self.repo = Repo.init(self.repo_dir)
        with self.repo.config_writer() as cw:
            cw.set_value("user", "name", "Test User").release()
            cw.set_value("user", "email", "test@example.com").release()

        self.app1 = self.repo_dir / "app1.py"
        self.app1.write_text("def func1(): pass\n")
        self.app2 = self.repo_dir / "app2.py"
        self.app2.write_text("def func2(): pass\n")
        
        self.repo.index.add(["app1.py", "app2.py"])
        self.repo.index.commit("Initial commit")

        # 2. Setup Non-Git directory
        self.nogit_dir = self.tmp_dir / "nogit"
        self.nogit_dir.mkdir()
        self.script1 = self.nogit_dir / "script1.py"
        self.script1.write_text("def func3(): pass\n")
        self.script2 = self.nogit_dir / "script2.py"
        self.script2.write_text("def func4(): pass\n")
        
    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    def _setup_mock(self, mock_get_agent):
        mock_agent = MagicMock()
        mock_get_agent.return_value = mock_agent
        review_payload = [
            CodeReview(
                type=DefectEnum.bug,
                file="test.py",
                line=1,
                description="Mocked Review",
                suggestion="Fix it"
            ).model_dump()
        ]
        def agent_side_effect(payload):
            if "OPEN or RESOLVED" in json.loads(payload)["request"]:
                return json.dumps([])
            return json.dumps(review_payload)
        mock_agent.call.side_effect = agent_side_effect
        return mock_agent

    @patch('milo.codereview.codereview.get_codereview_agent')
    def test_case_1_subset_git(self, mock_get_agent):
        mock_agent = self._setup_mock(mock_get_agent)
        
        self.app1.write_text("def func1(): print('a')\n")
        self.app2.write_text("def func2(): print('b')\n")
        self.repo.index.add(["app1.py", "app2.py"])
        self.repo.index.commit("Update both")
        
        file_manager = LocalGitProvider(str(self.repo_dir))
        run_crab(file_manager=file_manager, repo_root=str(self.repo_dir), files=[str(self.app1)])
        
        self.assertEqual(mock_agent.call.call_count, 1)
        store = ReviewStore(self.repo_dir / ".milo" / "reviews.json")
        self.assertEqual(len(store.get_reviews_by_file("app1.py")), 1)
        self.assertEqual(len(store.get_reviews_by_file("app2.py")), 0)

    @patch('milo.codereview.codereview.get_codereview_agent')
    def test_case_2_entire_git(self, mock_get_agent):
        mock_agent = self._setup_mock(mock_get_agent)
        
        self.app1.write_text("def func1(): print('c')\n")
        self.app2.write_text("def func2(): print('d')\n")
        self.repo.index.add(["app1.py", "app2.py"])
        self.repo.index.commit("Update both again")
        
        file_manager = LocalGitProvider(str(self.repo_dir))
        run_crab(file_manager=file_manager, repo_root=str(self.repo_dir), files=[str(self.app1), str(self.app2)])
        
        self.assertEqual(mock_agent.call.call_count, 2)
        store = ReviewStore(self.repo_dir / ".milo" / "reviews.json")
        self.assertEqual(len(store.get_reviews_by_file("app1.py")), 1)
        self.assertEqual(len(store.get_reviews_by_file("app2.py")), 1)
        
    @patch('milo.codereview.codereview.get_codereview_agent')
    def test_case_3_staged_changes_git(self, mock_get_agent):
        mock_agent = self._setup_mock(mock_get_agent)
        self.app1.write_text("def func1(): print('staged')\n")
        self.repo.index.add(["app1.py"])
        
        file_manager = LocalGitProvider(str(self.repo_dir))
        changed = file_manager.get_changed_files(str(self.repo_dir))
        run_crab(file_manager=file_manager, repo_root=str(self.repo_dir), files=changed, review_staged=True)
        
        self.assertEqual(mock_agent.call.call_count, 1)
        store = ReviewStore(self.repo_dir / ".milo" / "reviews.json")
        self.assertEqual(len(store.get_reviews_by_file("app1.py")), 1)

    @patch('milo.codereview.codereview.get_codereview_agent')
    def test_case_4_all_nogit(self, mock_get_agent):
        mock_agent = self._setup_mock(mock_get_agent)
        file_manager = FileSystemProvider(str(self.nogit_dir))
        run_crab(file_manager=file_manager, repo_root=str(self.nogit_dir), files=[str(self.script1), str(self.script2)])
        
        self.assertEqual(mock_agent.call.call_count, 2)
        store = ReviewStore(self.nogit_dir / ".milo" / "reviews.json")
        self.assertEqual(len(store.get_reviews_by_file("script1.py")), 1)
        self.assertEqual(len(store.get_reviews_by_file("script2.py")), 1)

    @patch('milo.codereview.codereview.get_codereview_agent')
    def test_case_5_subset_nogit(self, mock_get_agent):
        mock_agent = self._setup_mock(mock_get_agent)
        file_manager = FileSystemProvider(str(self.nogit_dir))
        run_crab(file_manager=file_manager, repo_root=str(self.nogit_dir), files=[str(self.script1)])
        
        self.assertEqual(mock_agent.call.call_count, 1)
        store = ReviewStore(self.nogit_dir / ".milo" / "reviews.json")
        self.assertEqual(len(store.get_reviews_by_file("script1.py")), 1)
        self.assertEqual(len(store.get_reviews_by_file("script2.py")), 0)


class MockGrepArgs(BaseModel):
    query: str


class TestAgentReasoningAndCondensation(unittest.TestCase):
    @patch('milo.agents.baseagent.OpenAI')
    def test_end_to_end_reasoning_and_condensation(self, mock_openai):
        """
        Verifies that <think> tags are extracted from the LLM's response,
        stripped from the main content to save history tokens, and successfully
        passed as 'reflective_thinking' to the ToolSummaryAgent when a tool
        returns a massive payload.
        """
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        
        # 1. Main agent's first response: a tool call + thinking
        tool_call_message = MagicMock()
        tool_call_message.role = "assistant"
        tool_call_message.content = "<think>\nI must find this using grep.\n</think>"
        tool_call_message.reasoning_content = None
        
        mock_tc = MagicMock()
        mock_tc.id = "call_abc123"
        mock_tc.type = "function"
        mock_tc.function.name = "grep_keyword"
        mock_tc.function.arguments = '{"query": "test"}'
        tool_call_message.tool_calls = [mock_tc]
        
        # 2. ToolSummaryAgent's response: condensed summary (simulated JSON output)
        condensation_message = MagicMock()
        condensation_message.role = "assistant"
        condensation_message.content = '```json\n{"summary": "Condensed grep output."}\n```'
        condensation_message.reasoning_content = None
        condensation_message.tool_calls = None
        
        # 3. Main agent's final response: final JSON array + thinking
        final_message = MagicMock()
        final_message.role = "assistant"
        final_message.content = "<think>\nNow I know the answer.\n</think>\n```json\n[]\n```"
        final_message.reasoning_content = None
        final_message.tool_calls = None
        
        mock_response_1 = MagicMock(choices=[MagicMock(message=tool_call_message)])
        mock_response_1.usage.total_tokens = 100
        mock_response_2 = MagicMock(choices=[MagicMock(message=condensation_message)])
        mock_response_2.usage.total_tokens = 50
        mock_response_3 = MagicMock(choices=[MagicMock(message=final_message)])
        mock_response_3.usage.total_tokens = 100
        
        mock_client.chat.completions.create.side_effect = [
            mock_response_1, mock_response_2, mock_response_3
        ]
        
        # Create a tool that returns a huge payload
        def massive_grep(query):
            return "MATCH data " * 1000  # ~11,000 chars, well over MAX_TOOL_RESULT_LEN (4000)
            
        grep_tool = Tool(name="grep_keyword", description="Search", func=massive_grep, schema=MockGrepArgs)
        agent = Agent(name="TestOrchestrator", tools=[grep_tool])
        
        result = agent.call("Find bugs related to test")
        
        # Assertions
        self.assertEqual(mock_client.chat.completions.create.call_count, 3)
        
        condensation_call_kwargs = mock_client.chat.completions.create.call_args_list[1].kwargs
        user_msg = next(m for m in condensation_call_kwargs['messages'] if m['role'] == 'user')
        self.assertIn("I must find this using grep.", user_msg['content'])
        self.assertIn("MATCH data", user_msg['content'])
        
        history = agent.history
        assistant_msg = next(m for m in history if m['role'] == 'assistant' and "grep_keyword" in m['content'])
        self.assertNotIn("<think>", assistant_msg['content'])
        
        tool_msg = next(m for m in history if m['role'] == 'user' and '[Tool Result]' in m['content'])
        self.assertIn("Condensed grep output.", tool_msg['content'])
        self.assertNotIn("MATCH data MATCH data", tool_msg['content'])
        
        final_assistant_msg = history[-1]
        self.assertEqual(final_assistant_msg['reasoning'], "Now I know the answer.")
        self.assertNotIn("<think>", final_assistant_msg['content'])
        self.assertEqual(result, "[]")

    @patch('milo.agents.baseagent.OpenAI')
    def test_native_reasoning_content_extraction(self, mock_openai):
        """
        Verifies that native OpenAI 'reasoning_content' is correctly extracted
        and passed as 'reflective_thinking' to the ToolSummaryAgent when a tool
        returns a massive payload, without relying on <think> tags.
        """
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        
        # 1. Main agent's first response: a tool call + native reasoning
        tool_call_message = MagicMock()
        tool_call_message.role = "assistant"
        tool_call_message.content = ""
        tool_call_message.reasoning_content = "I must find this using grep natively."
        
        mock_tc = MagicMock()
        mock_tc.id = "call_abc123"
        mock_tc.type = "function"
        mock_tc.function.name = "grep_keyword"
        mock_tc.function.arguments = '{"query": "test"}'
        tool_call_message.tool_calls = [mock_tc]
        
        # 2. ToolSummaryAgent's response: condensed summary (simulated JSON output)
        condensation_message = MagicMock()
        condensation_message.role = "assistant"
        condensation_message.content = '```json\n{"summary": "Condensed grep output."}\n```'
        condensation_message.reasoning_content = None
        condensation_message.tool_calls = None
        
        # 3. Main agent's final response: final JSON array + native reasoning
        final_message = MagicMock()
        final_message.role = "assistant"
        final_message.content = "```json\n[]\n```"
        final_message.reasoning_content = "Now I know the answer natively."
        final_message.tool_calls = None
        
        mock_response_1 = MagicMock(choices=[MagicMock(message=tool_call_message)])
        mock_response_1.usage.total_tokens = 100
        mock_response_2 = MagicMock(choices=[MagicMock(message=condensation_message)])
        mock_response_2.usage.total_tokens = 50
        mock_response_3 = MagicMock(choices=[MagicMock(message=final_message)])
        mock_response_3.usage.total_tokens = 100
        
        mock_client.chat.completions.create.side_effect = [
            mock_response_1, mock_response_2, mock_response_3
        ]
        
        # Create a tool that returns a huge payload
        def massive_grep(query):
            return "MATCH data " * 1000  # ~11,000 chars
            
        grep_tool = Tool(name="grep_keyword", description="Search", func=massive_grep, schema=MockGrepArgs)
        agent = Agent(name="TestOrchestrator", tools=[grep_tool])
        
        result = agent.call("Find bugs related to test")
        
        # Assertions
        self.assertEqual(mock_client.chat.completions.create.call_count, 3)
        
        condensation_call_kwargs = mock_client.chat.completions.create.call_args_list[1].kwargs
        user_msg = next(m for m in condensation_call_kwargs['messages'] if m['role'] == 'user')
        self.assertIn("I must find this using grep natively.", user_msg['content'])
        self.assertIn("MATCH data", user_msg['content'])
        
        history = agent.history
        assistant_msg = next(m for m in history if m['role'] == 'assistant' and "grep_keyword" in m['content'])
        self.assertEqual(assistant_msg['reasoning'], "I must find this using grep natively.")
        
        final_assistant_msg = history[-1]
        self.assertEqual(final_assistant_msg['reasoning'], "Now I know the answer natively.")
        self.assertEqual(result, "[]")

class TestGrepAstPagination(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path('/tmp/grep_pagination_test').resolve()
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir(parents=True)
        self.file_path = self.tmp_dir / "test_grep.py"
        
        lines = []
        for i in range(50):
            # 10 words per line: 1 (def) + 1 (name) + 1 (#) + 7 (numbers) = 10 words
            lines.append(f"def search_target_{i}(): # 1 2 3 4 5 6 7")
        self.file_path.write_text("\n".join(lines), encoding='utf-8')

    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    @patch.dict(os.environ, {"GREP_PAGE_LENGTH": "100"})
    def test_pagination_limits(self):
        from milo.codesift.grepast import grep_ast
        
        # Page 1
        res1 = grep_ast(query="search_target", repo_path=str(self.tmp_dir), page=1)
        self.assertIsNotNone(res1)
        self.assertTrue(res1["has_more_pages"])
        self.assertEqual(res1["page"], 1)
        self.assertTrue(len(res1["results"]) > 0)
        
        content1 = list(res1["results"].values())[0]
        words1 = len(content1.split())
        self.assertLessEqual(words1, 100)
        self.assertGreater(words1, 0)
        
        # Page 6 (Out of bounds, skipping 500 words)
        res6 = grep_ast(query="search_target", repo_path=str(self.tmp_dir), page=6)
        self.assertIsNotNone(res6)
        self.assertFalse(res6["has_more_pages"])
        self.assertEqual(res6["page"], 6)
        if res6["results"]:
            content6 = list(res6["results"].values())[0]
            self.assertEqual(len(content6.split()), 0)
        else:
            self.assertEqual(len(res6["results"]), 0)

if __name__ == '__main__':
    unittest.main()
