import argparse
import sys
from milo.codereview import review_path

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
    parser.add_argument('repo_path', nargs='?', help='Path to the git repository.')
    parser.add_argument('--path', nargs='+', help='List of paths to files or folders.')

    args = parser.parse_args()

    if args.repo_path:
        print(f"Commenting on staged changes in repo: {args.repo_path}")
        # Add logic to comment on staged changes
    elif args.path:
        print(f"Commenting on paths: {args.path}")
        # Add logic to comment on specified paths
    else:
        parser.print_help()
        sys.exit(1)

def codesift_main():
    parser = argparse.ArgumentParser(description='Codesift: Terminal-based chat interface.')
    print("Starting terminal-based chat interface for Codesift...")
    # Add logic to start the chat interface

def main():
    """
    Main entry point for testing, but console scripts point to specific functions.
    """
    print("milo-dy command-line interface. Use crab, comb, or codesift.")

if __name__ == '__main__':
    main()
