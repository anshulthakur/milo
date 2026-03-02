import os
from git import Repo, InvalidGitRepositoryError, NoSuchPathError

def get_git_root(path):
    """
    Check if the given path is inside a Git repository.
    If yes, return the repository's root directory.
    If not, return None.
    """
    try:
        # Resolve to absolute path
        abs_path = os.path.abspath(path)

        # Try to create a Repo object, searching parent directories
        repo = Repo(abs_path, search_parent_directories=True)

        # Return the root directory of the repository
        return repo.git.rev_parse("--show-toplevel")

    except (InvalidGitRepositoryError, NoSuchPathError):
        return None

def get_changed_files(git_root, path):
    """Returns a list of changed files (staged and unstaged) in the git repo, filtered by path."""
    changed_file_paths = set()
    try:
        repo = Repo(git_root)
        abs_path = os.path.abspath(path)

        # Staged changes (index vs. HEAD)
        staged_diffs = repo.index.diff(repo.head.commit)
        for diff in staged_diffs:
            full_path = os.path.abspath(os.path.join(git_root, diff.a_path))
            if full_path.startswith(abs_path):
                changed_file_paths.add(full_path)

        # Unstaged changes (working tree vs. index)
        unstaged_diffs = repo.index.diff(None)
        for diff in unstaged_diffs:
            full_path = os.path.abspath(os.path.join(git_root, diff.a_path))
            if full_path.startswith(abs_path):
                changed_file_paths.add(full_path)
    except Exception:
        # Broad exception to mimic the original's `pass` on error
        return []
    return list(changed_file_paths)