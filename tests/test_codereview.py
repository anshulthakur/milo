import os
import shutil
import json
import unittest
from git import Repo
from pathlib import Path
from unidiff import PatchSet
from milo.codereview.diff import LocalGitProvider, DiffUtils
from milo.codereview.state import ReviewStore, Review, ReviewAnchor, ReviewStatus
from milo.codesift.parsers import Language
from milo.codesift.parsers.treesitter import Treesitter
from unittest.mock import patch, MagicMock
from milo.codereview.codereview import run_crab
from milo.codereview.models import CodeReview, DefectEnum


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

class TestStateManager(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path('tests/tmp/state_manager_test')
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
        self.tmp_dir = Path('tests/tmp/git_provider_test').resolve()
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

class TestCrabIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path('tests/tmp/crab_integration_test').resolve()
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
        mock_agent_instance.call.return_value = json.dumps(review_payload)

        # 2. Modify a file and commit
        self.py_file_path.write_text("def main():\n    print('hello world') # changed\n")
        self.repo.index.add(["app.py"])
        self.repo.index.commit("Second commit")

        # 3. Run CRAB in git mode
        vcs_provider = LocalGitProvider(str(self.repo_path))
        run_crab(vcs=vcs_provider, repo_root=str(self.repo_path))

        # 4. Assertions for first run
        mock_agent_instance.call.assert_called_once()
        review_store_path = self.repo_path / ".milo" / "reviews.json"
        self.assertTrue(review_store_path.exists())
        store = ReviewStore(review_store_path)
        reviews = store.get_reviews_by_file("app.py")
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].anchor.symbol_name, "main")
        original_ast_fingerprint = reviews[0].anchor.ast_fingerprint

        # 5. Run again. The diff is the same, so the AST fingerprint check should prevent re-review.
        mock_agent_instance.call.reset_mock()
        run_crab(vcs=vcs_provider, repo_root=str(self.repo_path))
        
        # Agent should NOT be called again.
        mock_agent_instance.call.assert_not_called()

        # 6. Now, modify the function's AST and commit.
        self.py_file_path.write_text("def main():\n    print('hello world again') # AST changed\n")
        self.repo.index.add(["app.py"])
        self.repo.index.commit("Third commit")

        run_crab(vcs=vcs_provider, repo_root=str(self.repo_path))
        
        # Agent should be called again because AST fingerprint changed.
        mock_agent_instance.call.assert_called_once()
        
        # Verify the anchor was updated
        store.load()
        updated_reviews = store.get_reviews_by_file("app.py")
        self.assertEqual(len(updated_reviews), 1)
        self.assertNotEqual(original_ast_fingerprint, updated_reviews[0].anchor.ast_fingerprint)

    @patch('milo.codereview.codereview.get_codereview_agent')
    def test_run_crab_standalone_mode(self, mock_get_agent):
        # 1. Setup mock agent
        mock_agent_instance = MagicMock()
        mock_get_agent.return_value = mock_agent_instance
        review_payload = [
            CodeReview(
                type=DefectEnum.style,
                file=str(self.standalone_file),
                line=1,
                description="Function name too generic",
                suggestion="Use a more descriptive name"
            ).model_dump()
        ]
        mock_agent_instance.call.return_value = json.dumps(review_payload)

        # 2. Run CRAB in standalone mode for the first time
        run_crab(vcs=None, repo_root=str(self.standalone_path), files=[str(self.standalone_file)])

        # 3. Assertions
        mock_agent_instance.call.assert_called_once()
        review_store_path = self.standalone_path / ".milo" / "reviews.json"
        self.assertTrue(review_store_path.exists())
        store = ReviewStore(review_store_path)
        reviews = store.get_reviews_by_file(str(self.standalone_file))
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].anchor.symbol_name, "process_data")
        original_ast_fingerprint = reviews[0].anchor.ast_fingerprint

        # 4. Run again without changes
        mock_agent_instance.call.reset_mock()
        run_crab(vcs=None, repo_root=str(self.standalone_path), files=[str(self.standalone_file)])
        mock_agent_instance.call.assert_not_called()

        # 5. Modify the file and run again
        self.standalone_file.write_text("def process_data():\n    # changed\n    return 2\n")
        run_crab(vcs=None, repo_root=str(self.standalone_path), files=[str(self.standalone_file)])
        mock_agent_instance.call.assert_called_once()

        # Check that the review was updated
        store.load()
        updated_reviews = store.get_reviews_by_file(str(self.standalone_file))
        self.assertEqual(len(updated_reviews), 1)
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
        mock_agent_instance.call.return_value = json.dumps(review_payload)

        # 2. Modify a file and STAGE it, but do not commit
        self.py_file_path.write_text("def main():\n    print('staged change')\n")
        self.repo.index.add(["app.py"])

        # 3. Run CRAB in staged mode
        vcs_provider = LocalGitProvider(str(self.repo_path))
        run_crab(vcs=vcs_provider, repo_root=str(self.repo_path), review_staged=True)

        # 4. Assertions
        mock_agent_instance.call.assert_called_once()
        review_store_path = self.repo_path / ".milo" / "reviews.json"
        self.assertTrue(review_store_path.exists())
        store = ReviewStore(review_store_path)
        reviews = store.get_reviews_by_file("app.py")
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].anchor.symbol_name, "main")
        self.assertIn("Staged change issue", reviews[0].conversation[0].content)

if __name__ == '__main__':
    unittest.main()
