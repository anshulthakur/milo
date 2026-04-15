import os
import subprocess
import tempfile
from pathlib import Path
import difflib

def create_file(repo_path: str, file_path: str, content: str) -> str:
    """Creates a new file with the given content."""
    base = Path(repo_path).resolve()
    target = (base / file_path).resolve()
    
    try:
        target.relative_to(base)
    except ValueError:
        return "Error: Cannot access paths outside the repository."
        
    if target.exists():
        return f"Error: File '{file_path}' already exists. Use apply_diff to modify it."
        
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Successfully created {file_path}"
    except Exception as e:
        return f"Error creating file: {e}"

def apply_diff(repo_path: str, file_path: str, diff: str) -> str:
    """Applies a standard unified diff to a file using the patch utility."""
    base = Path(repo_path).resolve()
    target = (base / file_path).resolve()
    
    try:
        target.relative_to(base)
    except ValueError:
        return "Error: Cannot access paths outside the repository."
        
    if not target.exists():
        return f"Error: File '{file_path}' does not exist. Use create_file first."
        
    with tempfile.NamedTemporaryFile('w', delete=False, suffix=".patch") as f:
        if not diff.endswith('\n'):
            diff += '\n'
        f.write(diff)
        tmp_name = f.name
        
    try:
        result = subprocess.run(["patch", str(target), tmp_name], capture_output=True, text=True)
        if result.returncode == 0:
            return f"Successfully applied diff to {file_path}"
        else:
            return f"Failed to apply diff to {file_path}:\nOutput: {result.stdout}\nError: {result.stderr}\n\nNote: Ensure the diff contains a valid header (--- and +++) and matches the surrounding context lines exactly."
    finally:
        os.remove(tmp_name)

def replace_snippet(repo_path: str, file_path: str, search_text: str, replace_text: str) -> str:
    """Replaces an exact snippet of text in a file."""
    base = Path(repo_path).resolve()
    target = (base / file_path).resolve()
    
    try:
        target.relative_to(base)
    except ValueError:
        return "Error: Cannot access paths outside the repository."
        
    if not target.exists():
        return f"Error: File '{file_path}' does not exist. Use create_file first."

    content = target.read_text(encoding="utf-8")
    
    occurrences = content.count(search_text)
    if occurrences == 0:
        return "Error: The search_text was not found in the file. Ensure you provide an exact match, including exact whitespace and indentation."
    elif occurrences > 1:
        return f"Error: The search_text was found {occurrences} times. Please provide more context lines in the search_text to ensure it is unique."
        
    new_content = content.replace(search_text, replace_text)
    target.write_text(new_content, encoding="utf-8")
    
    diff = difflib.unified_diff(
        content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f'a/{file_path}',
        tofile=f'b/{file_path}',
    )
    
    return "Successfully replaced snippet. Diff:\n" + "".join(diff)
