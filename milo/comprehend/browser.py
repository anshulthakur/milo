import os
from pathlib import Path

def list_directory(repo_path: str, target_path: str = ".") -> str:
    """
    Lists the contents of a directory within the repository (akin to `ls`).
    """
    base = Path(repo_path).resolve()
    target = (base / target_path).resolve()
    
    try:
        target.relative_to(base)
    except ValueError:
        return "Error: Cannot access paths outside the repository."
        
    if not target.exists() or not target.is_dir():
        return f"Error: Directory '{target_path}' does not exist or is not a directory."
        
    try:
        entries = []
        for entry in target.iterdir():
            if entry.name.startswith('.git'): continue
            suffix = "/" if entry.is_dir() else ""
            entries.append(f"{entry.name}{suffix}")
        return "\n".join(sorted(entries))
    except Exception as e:
        return f"Error listing directory: {e}"

def tree_directory(repo_path: str, target_path: str = ".", depth: int = 2) -> str:
    """
    Returns a tree representation of a directory within the repository.
    """
    base = Path(repo_path).resolve()
    target = (base / target_path).resolve()
    
    try:
        target.relative_to(base)
    except ValueError:
        return "Error: Cannot access paths outside the repository."
        
    if not target.exists() or not target.is_dir():
        return f"Error: Directory '{target_path}' does not exist or is not a directory."

    def build_tree(dir_path, prefix="", current_depth=1):
        if current_depth > depth: return ""
        try: entries = sorted([e for e in dir_path.iterdir() if not e.name.startswith('.git')])
        except Exception: return ""
        return "".join([f"{prefix}{'└── ' if i == len(entries)-1 else '├── '}{e.name}\n" + (build_tree(e, prefix + ("    " if i == len(entries)-1 else "│   "), current_depth + 1) if e.is_dir() else "") for i, e in enumerate(entries)])
        
    return f"{target.name}/\n" + build_tree(target)
