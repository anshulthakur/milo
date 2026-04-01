# Milo API Integration Guide

Milo provides high-level APIs to programmatically generate documentation and perform code reviews. These orchestration functions act as convenient wrappers around the underlying AI agents.

This document outlines how to integrate `run_comb` (documentation) and `run_crab` (code review) into your own Python services.

## Core Concepts

To use the Milo API, you need to understand two key components:

1.  **Entry Points**: `run_comb` (for documentation) and `run_crab` (for code review).
2.  **`FileManager`**: An abstraction that provides file content and metadata. Milo includes two implementations:
    *   `LocalGitProvider`: Use this when your code is in a Git repository. It can intelligently find all files or only those that have been changed.
    *   `FileSystemProvider`: Use this for any regular directory that is not a Git repository.

## Configuration

The documentation agent requires a connection to an OpenAI-compatible Large Language Model (LLM) endpoint. You must configure the following environment variables before running your script:

-   **`LLM_ENDPOINT`**: The URL of the LLM service.
    *   *Example*: `export LLM_ENDPOINT="http://localhost:11434/v1"`
-   **`LLM_MODEL`**: The name of the model to use for generation.
    *   *Example*: `export LLM_MODEL="comb"`

## Usage Scenarios

### Documentation API (`run_comb`)

Below are examples demonstrating how to call `run_comb` for different project types.

### Scenario 1: Documenting a Git Repository

This is the recommended approach, as it allows Milo to leverage Git history for more context.

```python
import os
from milo.documentation import run_comb
from milo.utils import LocalGitProvider, FileManager

# 1. Specify the path to the local git repository
repo_path = "/path/to/your/git/repo"

# 2. Instantiate the provider for a Git repository
git_provider = LocalGitProvider(repo_path)

# 3. Get the list of files to document
# Option A: Get all files in the repository (at the specified path)
files_to_doc = git_provider.get_all_files(repo_path)

# Option B: Get only changed/staged files
# files_to_doc = git_provider.get_changed_files(repo_path)

# 4. Get repository metadata
repo_root = git_provider.repo_root
repo_name = os.path.basename(repo_root)

# 5. Run the documentation process
print(f"Starting documentation for {len(files_to_doc)} files in '{repo_name}'...")
run_comb(
    file_manager=git_provider,
    repo_root=repo_root,
    repo_name=repo_name,
    files=files_to_doc
)
print("Documentation complete.")
```

### Scenario 2: Documenting a Simple Directory (Non-Git)

If your source code is not in a Git repository, you can use the `FileSystemProvider`.

```python
import os
from milo.documentation import run_comb
from milo.utils import FileSystemProvider, FileManager

# 1. Specify the path to the source code directory
target_path = "/path/to/your/source/folder"

# 2. Instantiate the provider for a standard directory
fs_provider = FileSystemProvider(target_path)

# 3. Get the list of files to document
files_to_doc = fs_provider.get_all_files(target_path)

# 4. Get repository metadata (for a non-git repo, root is the path itself)
repo_root = fs_provider.repo_root
repo_name = os.path.basename(repo_root)

# 5. Run the documentation process
print(f"Starting documentation for {len(files_to_doc)} files in '{repo_name}'...")
run_comb(
    file_manager=fs_provider,
    repo_root=repo_root,
    repo_name=repo_name,
    files=files_to_doc
)
print("Documentation complete.")
```

## Function Signature

`run_comb(file_manager: FileManager, repo_root: str, repo_name: str, files: List[str])`

### Parameters:

-   **`file_manager`** (`FileManager`): An initialized instance of `LocalGitProvider` or `FileSystemProvider`. This is a **required** parameter.
-   **`repo_root`** (`str`): The absolute path to the root of the repository or source directory. Milo uses this path to create a `.milo` directory for caching analysis results. This is a **required** parameter.
-   **`repo_name`** (`str`): The name of the repository (e.g., `my-project`). This is a **required** parameter.
-   **`files`** (`List[str]`): A list of absolute file paths to be documented. This is a **required** parameter.

### Code Review API (`run_crab`)

The `milo.codereview.run_crab` function orchestrates code analysis and AI-powered code reviews, generating feedback on changed code. It uses a `ReviewStore` to persist review state and avoid redundant reviews on unchanged code blocks.

**Usage Example:**

```python
import os
from milo.codereview import run_crab
from milo.utils import LocalGitProvider

# 1. Specify the path to the local git repository
repo_path = "/path/to/your/git/repo"

# 2. Instantiate the provider
git_provider = LocalGitProvider(repo_path)

# 3. Get repository metadata
repo_root = git_provider.repo_root

# 4. Run the code review process on staged changes
print("Starting code review for staged changes...")
run_crab(
    file_manager=git_provider,
    repo_root=repo_root,
    review_staged=True  # Set to False to review recent commits instead
)
print("Code review complete.")
```

**Function Signature:**

`run_crab(file_manager: Optional[FileManager] = None, repo_root: Optional[str] = None, files: List[str] = None, review_staged: bool = False) -> None`

**Parameters:**

-   **`file_manager`** (`Optional[FileManager]`): An initialized instance of `LocalGitProvider` or `FileSystemProvider`. Required to detect changes.
-   **`repo_root`** (`Optional[str]`): The absolute path to the root of the repository. Milo uses this path to create a `.milo` directory for the `ReviewStore` and `metadata.json`.
-   **`files`** (`List[str]`): An optional list of absolute file paths to restrict the review. If empty, all changed files identified by the `file_manager` are reviewed.
-   **`review_staged`** (`bool`): If `True`, reviews staged changes (index vs. HEAD). If `False`, reviews the latest commit (HEAD vs. HEAD~1). Defaults to `False`.

## Utility Functions

This section documents helper functions that can be useful when integrating with Milo.

### `is_file_supported(file_name: str) -> bool`

Checks if a given file is supported for documentation generation. This is useful for pre-filtering files before passing them to `run_comb`.

**Import:**
```python
from milo.codesift.parsers import is_file_supported
```

**Parameters:**

-   **`file_name`** (`str`): The path to the file.

**Returns:**

-   `bool`: `True` if the file's language is supported, `False` otherwise.

**Behavior:**

-   It first checks the file's extension (e.g., `.py`, `.c`, `.h`).
-   If no extension is found, and the file exists on disk, it will attempt to read the first line to check for a shebang (e.g., `#!/usr/bin/env python`) to infer the language.
-   The list of supported languages is determined by `milo.codesift.parsers.supported_languages()`.

**Example:**

```python
from milo.codesift.parsers import is_file_supported

# Check supported files
assert is_file_supported("my_script.py") is True
assert is_file_supported("/path/to/my_c_file.h") is True

# Check an unsupported file
assert is_file_supported("README.md") is False
```