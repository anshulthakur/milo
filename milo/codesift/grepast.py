from grep_ast.main import enumerate_files
from grep_ast.grep_ast import TreeContext

from pathlib import Path
import pathspec
import traceback
from git import Repo


def lookup_file(filename, pattern, options=None):
    """
    Searches a file for a pattern using TreeContext parsing with configurable options.

    Args:
        filename (str): Path to the file to search
        pattern (str): Regex pattern to search for in the file
        options (dict, optional): Search configuration including:
            - encoding (str): File encoding (default: 'utf-8')
            - ignore_case (bool): Case-insensitive search (default: False)

    Returns:
        str | None: Formatted search results containing matched lines with surrounding context,
        or None if file can't be read/processed

    Handles UnicodeDecodeError and ValueError internally, returning None on failure.
    Used by grep_ast() for code searching in the same module. Does not perform AST parsing;
    instead, returns line-based matches with context from TreeContext.
    """
    grep_options = {
        "encoding": "utf-8",
        "ignore-case": False,
    }
    try:
        with open(filename, "r", encoding=grep_options.get("encoding")) as file:
            code = file.read()
    except UnicodeDecodeError:
        return

    try:
        tc = TreeContext(filename, code, color=False, verbose=False, line_number=False)
    except ValueError:
        return

    loi = tc.grep(pattern, grep_options.get("ignore_case"))
    if not loi:
        return

    tc.add_lines_of_interest(loi)
    tc.add_context()

    return tc.format()


def grep_ast(
    query: str,
    file_hint=None,
    repo_path="",
) -> dict | None:
    """
    Recursively searches for a string pattern in files within a repository, respecting .gitignore exclusions.

    Args:
        query (str): String pattern to search for in file contents.
        file_hint: Unused parameter (present in signature but not implemented in current logic).
        repo_path (str, optional): Root directory path of the repository. Defaults to current directory.

    Returns:
        dict | None: A dictionary with two keys if matches found:
            - "query": The searched string pattern
            - "results": Dictionary mapping filenames to their matched results {filename: [matches]}
            Returns None if an error occurs.

    Behavior:
        1. Loads .gitignore rules from repository root if repo_path is specified
        2. Uses gitwildmatch pattern matching to filter files during recursive search
        3. Aggregates all file matches into a structured dictionary format
        4. Returns a dictionary with empty results if no matches are found.
    """
    try:
        git_root = None
        search_path = repo_path if repo_path else "."
        try:
            repo = Repo(search_path, search_parent_directories=True)
            git_root = repo.working_tree_dir
        except Exception:
            pass

        if not repo_path:
            if git_root:
                repo_path = git_root
            else:
                repo_path = "."
        elif git_root:
            resolved_repo_path = str(Path(repo_path).resolve())
            resolved_git_root = str(Path(git_root).resolve())
            if resolved_repo_path != resolved_git_root:
                print(f"Anomaly: Provided repo_path '{resolved_repo_path}' does not match git root '{resolved_git_root}'. Using provided repo_path.")

        print(f'Grep: repo path: {repo_path}')
        parent = Path(repo_path).resolve()
        gitignore = None
        potential_gitignore = parent / ".gitignore"
        if potential_gitignore.exists():
            gitignore = potential_gitignore

        if gitignore:
            with gitignore.open() as f:
                spec = pathspec.PathSpec.from_lines("gitwildmatch", f)
        else:
            spec = pathspec.PathSpec.from_lines("gitwildmatch", [])
        results = {}
        for fname in enumerate_files([parent], spec):
            matches = lookup_file(fname, query)
            if matches is not None:
                results.update({fname: matches})
        return {"query": query, "results": results}
    except Exception:
        traceback.print_exc()
        return None
