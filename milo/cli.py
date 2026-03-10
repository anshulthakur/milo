import argparse
import sys
import os
from milo.codereview import review_path
from milo.utils.git_tools import get_git_root, get_changed_files
from milo.utils.path_utils import get_all_files

from milo.documentation.documentation import run_comb
from milo.codereview.codereview import run_crab
from milo.codereview.diff import LocalGitProvider

def crab_main():
    parser = argparse.ArgumentParser(description='Comment Review and Aggregation Bot (CRAB)')
    parser.add_argument('path', nargs='?', default='.', help='Path to the git repository or file/folder to review.')
    parser.add_argument('--updates', action='store_true', help='Only process staged files with changes.')

    args = parser.parse_args()

    target_path = os.path.abspath(args.path)
    if not os.path.exists(target_path):
        print(f"Error: Path '{target_path}' does not exist.")
        sys.exit(1)

    git_root = get_git_root(target_path)
    repo_name = git_root.split('/')[-1] if git_root is not None else None
    files_to_review = []

    vcs_provider = None

    if git_root:
        print(f"Git repository detected at: {git_root}")
        vcs_provider = LocalGitProvider(git_root)
        if args.updates:
            print(f"Looking for updates in {target_path}...")
            files_to_review = get_changed_files(git_root, target_path)
        else:
            print(f"Constructing list of files from {target_path}...")
            files_to_review = get_all_files(target_path)
    else:
        print(f"No git repository detected. Processing path: {target_path}")
        files_to_review = get_all_files(target_path)
        if os.path.isdir(target_path):
            git_root = target_path
            repo_name = os.path.basename(target_path)

    if not files_to_review:
        print("No files found to process.")
    else:
        print(f"Found {len(files_to_review)} files to process.")
        run_crab(
            vcs=vcs_provider,
            repo_root=git_root,
            files=files_to_review,
            review_staged=args.updates
        )

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
    repo_name = git_root.split('/')[-1] if git_root is not None else None
    files_to_document = []

    if git_root:
        print(f"Git repository detected at: {git_root}")
        if args.updates:
            print(f"Looking for updates in {target_path}...")
            files_to_document = get_changed_files(git_root, target_path)
        else:
            print(f"Constructing list of files from {target_path}...")
            files_to_document = get_all_files(target_path)
    else:
        print(f"No git repository detected. Processing path: {target_path}")
        files_to_document = get_all_files(target_path)
        if os.path.isdir(target_path):
            git_root = target_path
            repo_name = os.path.basename(target_path)

    if not files_to_document:
        print("No files found to process.")
    else:
        print(f"Found {len(files_to_document)} files to process.")
        run_comb(repo_root=git_root,
                 repo_name=repo_name,
                 files = files_to_document)

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
