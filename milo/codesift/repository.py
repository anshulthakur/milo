import os
from abc import ABC, abstractmethod
from typing import List, Optional
from git import Repo, GitCommandError
from unidiff import PatchSet

class Repository(ABC):
    def __init__(self, root_path: str):
        self.root_path = os.path.abspath(root_path)

    @abstractmethod
    def list_files(self) -> List[str]:
        """List all source files in the repository."""
        pass

    @abstractmethod
    def get_file_content(self, file_path: str, ref: Optional[str] = None) -> Optional[str]:
        """Get content of a file, optionally at a specific git ref."""
        pass
    
    def get_absolute_path(self, file_path: str) -> str:
        if os.path.isabs(file_path):
            return file_path
        return os.path.join(self.root_path, file_path)

class FileSystemRepository(Repository):
    def list_files(self) -> List[str]:
        files = []
        for root, _, filenames in os.walk(self.root_path):
            if ".git" in root:
                continue
            for name in filenames:
                files.append(os.path.join(root, name))
        return files

    def get_file_content(self, file_path: str, ref: Optional[str] = None) -> Optional[str]:
        # FileSystemRepository doesn't support refs, it always reads current state on disk
        path = self.get_absolute_path(file_path)
        if os.path.exists(path):
            try:
                with open(path, 'r', errors='ignore') as f:
                    return f.read()
            except IOError:
                return None
        return None

class GitRepository(FileSystemRepository):
    def __init__(self, root_path: str):
        super().__init__(root_path)
        try:
            self.repo = Repo(self.root_path, search_parent_directories=True)
            self.root_path = self.repo.git.rev_parse("--show-toplevel")
        except Exception as e:
            raise ValueError(f"Invalid git repository at {root_path}") from e

    def list_files(self) -> List[str]:
        try:
            # List tracked files
            files_str = self.repo.git.ls_files()
            return [os.path.join(self.root_path, f) for f in files_str.split('\n') if f]
        except GitCommandError:
            return []

    def get_file_content(self, file_path: str, ref: Optional[str] = None) -> Optional[str]:
        if ref:
            path = self.get_absolute_path(file_path)
            try:
                rel_path = os.path.relpath(path, self.root_path)
                # Check if ref is 'index'
                if ref == 'index':
                    return self.repo.git.show(f":0:{rel_path}")
                return self.repo.git.show(f"{ref}:{rel_path}")
            except (GitCommandError, ValueError):
                return None

        # Fallback to filesystem if no ref provided (working copy)
        return super().get_file_content(file_path, ref)

def get_repository(root_path: str) -> Repository:
    """Factory to create the appropriate Repository instance."""
    try:
        return GitRepository(root_path)
    except ValueError:
        return FileSystemRepository(root_path)
