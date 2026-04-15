import argparse
import sys
import os
from milo.codereview import review_path
from milo.utils import get_git_root, LocalGitProvider, FileSystemProvider

from milo.documentation import run_comb
from milo.codereview.codereview import run_crab

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

    file_manager = None

    if git_root:
        print(f"Git repository detected at: {git_root}")
        file_manager = LocalGitProvider(git_root)
        if args.updates:
            print(f"Looking for updates in {target_path}...")
            files_to_review = file_manager.get_changed_files(target_path)
        else:
            print(f"Constructing list of files from {target_path}...")
            files_to_review = file_manager.get_all_files(target_path)
    else:
        print(f"No git repository detected. Processing path: {target_path}")
        file_manager = FileSystemProvider(target_path)
        files_to_review = file_manager.get_all_files(target_path)
        if os.path.isdir(target_path):
            git_root = target_path
            repo_name = os.path.basename(target_path)

    if not files_to_review:
        print("No files found to process.")
    else:
        print(f"Found {len(files_to_review)} files to process.")
        run_crab(
            file_manager=file_manager,
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
    file_manager = None

    if git_root:
        print(f"Git repository detected at: {git_root}")
        file_manager = LocalGitProvider(git_root)
        if args.updates:
            print(f"Looking for updates in {target_path}...")
            files_to_document = file_manager.get_changed_files(target_path)
        else:
            print(f"Constructing list of files from {target_path}...")
            files_to_document = file_manager.get_all_files(target_path)
    else:
        print(f"No git repository detected. Processing path: {target_path}")
        file_manager = FileSystemProvider(target_path)
        files_to_document = file_manager.get_all_files(target_path)
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
    parser.add_argument('path', nargs='?', default='.', help='Path to the repository.')
    args = parser.parse_args()
    
    target_path = os.path.abspath(args.path)
    git_root = get_git_root(target_path) or target_path
    
    metadata_path = os.path.join(git_root, ".milo", "metadata.json")
    if not os.path.exists(metadata_path):
        print(f"Error: Semantic map not found at {metadata_path}.")
        print("Please run the SemanticIndexer first.")
        sys.exit(1)
        
    from milo.agents.repocomprehension import get_repocomprehension_agent
    agent = get_repocomprehension_agent(repo_path=git_root, metadata_path=metadata_path)
    
    print(f"\n[Codesift Navigator initialized for: {git_root}]")
    print("Type 'exit' or 'quit' to stop.\n")
    
    while True:
        try:
            user_input = input("You> ")
            if user_input.strip().lower() in ['exit', 'quit']:
                break
            if not user_input.strip():
                continue
                
            response = agent.call(user_input)
        except (KeyboardInterrupt, EOFError):
            break
        except Exception as e:
            print(f"\nError: {e}\n")


def main():
    """
    Main entry point for testing, but console scripts point to specific functions.
    """
    print("milo command-line interface. Use crab, comb, or codesift.")

if __name__ == '__main__':
    main()
