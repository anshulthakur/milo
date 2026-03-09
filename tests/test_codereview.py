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
        
        code1 = "def foo():\n    print('hello')"
        ts.parse(code1.encode('utf-8'))
        root1 = ts.tree.root_node
        fp1 = DiffUtils.compute_ast_fingerprint(root1)
        
        # Identical code should have identical fingerprint
        ts.parse(code1.encode('utf-8'))
        root1_dup = ts.tree.root_node
        fp1_dup = DiffUtils.compute_ast_fingerprint(root1_dup)
        self.assertEqual(fp1, fp1_dup)

        # Code with different semantics should differ
        code2 = "def foo():\n    print('world')"
        ts.parse(code2.encode('utf-8'))
        root2 = ts.tree.root_node
        fp2 = DiffUtils.compute_ast_fingerprint(root2)
        self.assertNotEqual(fp1, fp2)

    def test_ast_fingerprint_c(self):
        """Test AST fingerprinting for C code, ensuring robustness to insignificant whitespace."""
        ts = Treesitter.create_treesitter(Language.C)
        
        code1 = "int main() { return 0; }"
        ts.parse(code1.encode('utf-8'))
        root1 = ts.tree.root_node
        fp1 = DiffUtils.compute_ast_fingerprint(root1)
        
        # C is generally whitespace insensitive (except in strings/preproc)
        code2 = "int main() { \n  return 0; \n}"
        ts.parse(code2.encode('utf-8'))
        root2 = ts.tree.root_node
        fp2 = DiffUtils.compute_ast_fingerprint(root2)
        
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
        self.tmp_dir = Path('tests/tmp/git_provider_test')
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
        self.assertEqual(changes[0].path, "test.txt")

if __name__ == '__main__':
    unittest.main()
