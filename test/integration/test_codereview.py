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
from milo.codereview.codereview import run_crab
from milo.codereview.models import CodeReview, DefectEnum

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

    def test_run_crab_e2e_no_mocks(self):
        """
        Exploratory end-to-end test for run_crab without mocks.
        This test makes a real call to the LLM and then prints the saved
        review comments from the ReviewStore for inspection.
        """
        # 1. Modify a file to introduce a reviewable issue
        self.py_file_path.write_text("def main():\n    password = '12345' # Bad practice\n    print('hello')\n")
        self.repo.index.add(["app.py"])
        self.repo.index.commit("Add insecure password")

        # 2. Run CRAB in git mode. This will populate the review store.
        file_manager = LocalGitProvider(str(self.repo_path))
        run_crab(file_manager=file_manager, repo_root=str(self.repo_path))
        
        # 3. Load the review store to inspect the saved comments
        review_store_path = self.repo_path / ".milo" / "reviews.json"
        self.assertTrue(review_store_path.exists(), "Review store file was not created.")
        store = ReviewStore(review_store_path)
        
        reviews = list(store.reviews.values())

        # 4. Print the saved reviews for the user to see
        print("\n--- Saved Reviews from ReviewStore ---")
        if not reviews:
            print("No reviews found in the store.")
        for review in reviews:
            print(f"Review ID: {review.id}")
            print(f"  File: {review.anchor.file_path}")
            print(f"  Symbol: {review.anchor.symbol_name}")
            print(f"  Status: {review.status.value}")
            print("  Conversation:")
            for comment in review.conversation:
                print(f"    - {comment.role.upper()}: {comment.content.strip()}")
            print("-" * 20)
        print("--------------------------------------\n")

        # 5. Assert that at least one review was created and saved
        self.assertGreater(len(reviews), 0, "No reviews were saved to the store.")
        self.assertEqual(reviews[0].anchor.symbol_name, "main")
        self.assertGreater(len(reviews[0].conversation), 0, "The saved review has no comments.")

    def test_run_crab_e2e_standalone_mixed_languages(self):
        """
        Exploratory end-to-end test for run_crab in standalone mode (no git).
        Reviews a folder with C and Python files.
        """
        # 1. Setup standalone directory
        standalone_dir = self.tmp_dir / "standalone_mixed"
        standalone_dir.mkdir()
        
        # 2. Create C file with issues
        c_file = standalone_dir / "unsafe.c"
        c_file.write_text("""
#include <stdio.h>
#include <string.h>

void process_input(char *input) {
    char buffer[10];
    strcpy(buffer, input); // Buffer overflow vulnerability
    printf("Processed: %s", buffer);
}
""", encoding='utf-8')

        # 3. Create Python file with issues
        py_file = standalone_dir / "script.py"
        py_file.write_text("""
def connect_db():
    password = "password123" # Hardcoded credential
    print("Connecting...")
""", encoding='utf-8')

        # 4. Run CRAB in standalone mode
        # In standalone mode, the CLI typically gathers files. Here we pass them explicitly.
        files_to_review = [str(c_file), str(py_file)]
        
        print("\n--- Running CRAB E2E Standalone (Mixed Languages) ---")
        file_manager = FileSystemProvider(str(standalone_dir))
        run_crab(file_manager=file_manager, repo_root=str(standalone_dir), files=files_to_review)
        
        # 5. Load and inspect ReviewStore
        review_store_path = standalone_dir / ".milo" / "reviews.json"
        self.assertTrue(review_store_path.exists(), "Review store file was not created.")
        store = ReviewStore(review_store_path)
        
        reviews = list(store.reviews.values())
        
        print("\n--- Saved Reviews from Standalone Run ---")
        if not reviews:
            print("No reviews found in the store.")
        for review in reviews:
            print(f"Review ID: {review.id}")
            print(f"  File: {review.anchor.file_path}")
            print(f"  Symbol: {review.anchor.symbol_name}")
            print(f"  Status: {review.status.value}")
            print("  Conversation:")
            for comment in review.conversation:
                print(f"    - {comment.role.upper()}: {comment.content.strip()}")
            print("-" * 20)
        print("-----------------------------------------\n")

        # 6. Assertions
        self.assertGreater(len(reviews), 0, "No reviews were generated.")
        
        # Check for Python review
        py_reviews = [r for r in reviews if r.anchor.file_path.endswith("script.py")]
        self.assertTrue(len(py_reviews) > 0, "No reviews for Python file.")
        self.assertEqual(py_reviews[0].anchor.symbol_name, "connect_db")
        
        # Check for C review
        c_reviews = [r for r in reviews if r.anchor.file_path.endswith("unsafe.c")]
        self.assertTrue(len(c_reviews) > 0, "No reviews for C file.")
        self.assertEqual(c_reviews[0].anchor.symbol_name, "process_input")

if __name__ == '__main__':
    unittest.main()
