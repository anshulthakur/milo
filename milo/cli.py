import argparse
import sys
import os
from milo.codereview import review_path
from milo.utils.git_tools import get_git_root, get_changed_files
from milo.utils.path_utils import get_all_files

from milo.agents.comb import COMB

def run_comb(files):
    """Placeholder for running the COMB agent on a file."""
    print(f"Running COMB agent on: {files}")
    comb = COMB()
    comb.run(files)

def create_update_repo_map(git_root):
    """Placeholder for creating/updating the repo map."""
    print(f"Creating/Updating repo map for: {git_root}")

def crab_main():
    parser = argparse.ArgumentParser(description='Comment Review and Aggregation Bot (CRAB)')
    parser.add_argument('repo_path', nargs='?', help='Path to the git repository.')
    parser.add_argument('--path', nargs='+', help='List of paths to files or folders.')

    args = parser.parse_args()

    if args.repo_path:
        print(f"Reviewing staged changes in repo: {args.repo_path}")
        # Add logic to review staged changes
    elif args.path:
        files_to_review = review_path(args.path)
        print("Files to review:")
        for file in files_to_review:
            print(file)
    else:
        parser.print_help()
        sys.exit(1)

def comb_main():
    parser = argparse.ArgumentParser(description='Comment Bot (COMB)')
    parser.add_argument('path', nargs='?', default='.', help='Path to the git repository or file/folder.')
    parser.add_argument('--updates', action='store_true', help='Only process files with changes.')

    args = parser.parse_args()
    
    target_path = os.path.abspath(args.path)
    if not os.path.exists(target_path):
        print(f"Error: Path '{target_path}' does not exist.")
        sys.exit(1)

    git_root = get_git_root(target_path)
    files_to_document = []

    if git_root:
        print(f"Git repository detected at: {git_root}")
        create_update_repo_map(git_root)
        if args.updates:
            print(f"Looking for updates in {target_path}...")
            files_to_document = get_changed_files(git_root, target_path)
        else:
            print(f"Constructing list of files from {target_path}...")
            files_to_document = get_all_files(target_path)
    else:
        print(f"No git repository detected. Processing path: {target_path}")
        files_to_document = get_all_files(target_path)

    if not files_to_document:
        print("No files found to process.")
    else:
        print(f"Found {len(files_to_document)} files to process.")
        run_comb(files_to_document)

def codesift_main():
    parser = argparse.ArgumentParser(description='Codesift: Terminal-based chat interface.')
    print("Starting terminal-based chat interface for Codesift...")
    # Add logic to start the chat interface


def main():
    """
    Main entry point for testing, but console scripts point to specific functions.
    """
    print("milo command-line interface. Use crab, comb, or codesift.")

if __name__ == '__main__':
    main()
