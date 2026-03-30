# Milo Documentation API (`run_comb`)

The `milo.documentation.documentation.run_comb` function provides a high-level API to programmatically generate documentation for source code files. It orchestrates file discovery, code analysis, and AI-powered documentation generation, acting as a convenient wrapper around the underlying `DocumentationAgent`.

This document outlines how to integrate `run_comb` into your own Python services.

## Core Concepts

To use `run_comb`, you need to understand two key components:

1.  **`run_comb`**: The main entry point function. It requires a list of files and a `FileManager` to operate.
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