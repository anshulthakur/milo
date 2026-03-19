import os
import difflib
from typing import List, Optional
from abc import ABC, abstractmethod
from git import Repo, GitCommandError, InvalidGitRepositoryError, NoSuchPathError
from unidiff import PatchSet

def get_git_root(path):
    """
    Check if the given path is inside a Git repository.
    If yes, return the repository's root directory.
    If not, return None.
    """
    try:
        abs_path = os.path.abspath(path)
        repo = Repo(abs_path, search_parent_directories=True)
        return repo.git.rev_parse("--show-toplevel")
    except (InvalidGitRepositoryError, NoSuchPathError, GitCommandError):
        return None

class FileManager(ABC):
    """
    Abstract base class for file management and change tracking providers.
    """
    @abstractmethod
    def get_changes(self, base_ref: str, head_ref: str) -> PatchSet:
        pass

    @abstractmethod
    def get_file_content(self, file_path: str, ref: str) -> Optional[str]:
        pass

    @abstractmethod
    def get_current_rev(self) -> str:
        pass

    @abstractmethod
    def get_all_files(self, path: str) -> List[str]:
        pass

    @abstractmethod
    def get_changed_files(self, path: str) -> List[str]:
        pass

class LocalGitProvider(FileManager):
    """
    Implementation of FileManager for a local git repository.
    """
    def __init__(self, repo_path: str, search_parent_directories: bool = True):
        try:
            self.repo = Repo(repo_path, search_parent_directories=search_parent_directories)
            self.repo_root = self.repo.git.rev_parse("--show-toplevel")
        except Exception as e:
            raise ValueError(f"Invalid git repository at {repo_path}: {e}")

    def get_changes(self, base_ref: str, head_ref: str) -> PatchSet:
        try:
            if head_ref == 'index':
                diff_text = self.repo.git.diff(
                    base_ref,
                    '--cached',
                    '--src-prefix=a/',
                    '--dst-prefix=b/',
                    ignore_blank_lines=True,
                    ignore_space_at_eol=True,
                    unified=3
                )
            else:
                diff_text = self.repo.git.diff(
                    base_ref,
                    head_ref,
                    '--src-prefix=a/',
                    '--dst-prefix=b/',
                    ignore_blank_lines=True,
                    ignore_space_at_eol=True,
                    unified=3
                )
            return PatchSet(diff_text)
        except GitCommandError as e:
            print(f"Git error extracting diff: {e}")
            return PatchSet("")

    def get_file_content(self, file_path: str, ref: str) -> Optional[str]:
        try:
            if os.path.isabs(file_path):
                file_path = os.path.relpath(file_path, self.repo.working_dir)

            if ref == 'index':
                ref_spec = f":0:{file_path}"
            else:
                ref_spec = f"{ref}:{file_path}"
            
            return self.repo.git.show(ref_spec, strip_newline_in_stdout=False)
        except (GitCommandError, KeyError):
            return None

    def get_current_rev(self) -> str:
        return self.repo.head.commit.hexsha

    def get_all_files(self, path: str) -> List[str]:
        files_list = []
        abs_path = os.path.abspath(path)
        if os.path.isfile(abs_path):
            return [abs_path]
        
        for root, dirs, files in os.walk(abs_path):
            if '.git' in dirs:
                dirs.remove('.git')
            for file in files:
                files_list.append(os.path.join(root, file))
        return files_list

    def get_changed_files(self, path: str) -> List[str]:
        changed_file_paths = set()
        try:
            abs_path = os.path.abspath(path)
            staged_diffs = self.repo.index.diff(self.repo.head.commit)
            for diff in staged_diffs:
                full_path = os.path.abspath(os.path.join(self.repo_root, diff.a_path))
                if full_path.startswith(abs_path):
                    changed_file_paths.add(full_path)

            unstaged_diffs = self.repo.index.diff(None)
            for diff in unstaged_diffs:
                full_path = os.path.abspath(os.path.join(self.repo_root, diff.a_path))
                if full_path.startswith(abs_path):
                    changed_file_paths.add(full_path)
        except Exception:
            return []
        return list(changed_file_paths)

class FileSystemProvider(FileManager):
    """
    Implementation of FileManager for a local file system (non-git).
    """
    def __init__(self, target_path: str):
        self.target_path = os.path.abspath(target_path)
        self.repo_root = self.target_path
        if os.path.isfile(self.repo_root):
            self.repo_root = os.path.dirname(self.repo_root)

    def get_changes(self, base_ref: str, head_ref: str) -> PatchSet:
        diffs = []
        files = self.get_all_files(self.target_path)
        for f in files:
            try:
                with open(f, 'r', encoding='utf-8') as file:
                    content = file.readlines()
            except Exception:
                continue
            
            rel_path = os.path.relpath(f, self.repo_root)
            diff = list(difflib.unified_diff(
                [], content,
                fromfile=f"a/{rel_path}",
                tofile=f"b/{rel_path}"
            ))
            if diff:
                if not diff[-1].endswith('\n'):
                    diff[-1] += '\n'
                diffs.extend(diff)
            
        diff_text = "".join(diffs)
        return PatchSet(diff_text)

    def get_file_content(self, file_path: str, ref: str) -> Optional[str]:
        full_path = file_path
        if not os.path.isabs(file_path):
            full_path = os.path.join(self.repo_root, file_path)
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            return None

    def get_current_rev(self) -> str:
        return "HEAD"

    def get_all_files(self, path: str) -> List[str]:
        files_list = []
        abs_path = os.path.abspath(path)
        if os.path.isfile(abs_path):
            return [abs_path]
        
        for root, dirs, files in os.walk(abs_path):
            if '.git' in dirs:
                dirs.remove('.git')
            for file in files:
                files_list.append(os.path.join(root, file))
        return files_list

    def get_changed_files(self, path: str) -> List[str]:
        return self.get_all_files(path)
