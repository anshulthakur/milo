import hashlib
import os
from typing import List, Optional
from abc import ABC, abstractmethod
from git import Repo, GitCommandError
from unidiff import PatchSet, PatchedFile, Hunk
from tree_sitter import Node

class VCSProvider(ABC):
    """
    Abstract base class for Version Control System providers.
    Allows plugging in Local Git, GitLab, GitHub, etc.
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

class LocalGitProvider(VCSProvider):
    """
    Implementation of VCSProvider for a local git repository.
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
            
            # GitPython strips trailing newlines by default. We must explicitly disable this.
            return self.repo.git.show(ref_spec, strip_newline_in_stdout=False)

        except (GitCommandError, KeyError):
            return None

    def get_current_rev(self) -> str:
        return self.repo.head.commit.hexsha

class DiffUtils:
    """
    Static utilities for fingerprinting and normalization.
    """
    @staticmethod
    def normalize_hunk(hunk: Hunk) -> str:
        """
        Produces a normalized string representation of a hunk for fingerprinting.
        Ignores line numbers and context lines, focuses strictly on added/removed content.
        This ensures that shifting code up/down doesn't change the fingerprint.
        """
        content = []
        for line in hunk:
            # We strip whitespace to make the fingerprint robust against indentation changes
            # if that is desired. For strict code review, maybe we want to keep indentation.
            # CRAB.md suggests "trivial changes (whitespace...)" should not invalidate.
            clean_val = line.value.strip()
            if not clean_val:
                continue
                
            if line.is_added:
                content.append(f"+{clean_val}")
            elif line.is_removed:
                content.append(f"-{clean_val}")
        
        return "\n".join(content)

    @staticmethod
    def compute_patch_fingerprint(hunk: Hunk) -> str:
        """
        Generates a SHA-256 hash of the normalized hunk.
        """
        normalized = DiffUtils.normalize_hunk(hunk)
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

    @staticmethod
    def compute_ast_fingerprint(node: Node) -> str:
        """
        Generates a SHA-256 hash of the AST structure and leaf content.
        This provides a semantic fingerprint that is robust against 
        whitespace, formatting, and comment changes (if comments are ignored by the walker).
        """
        def _walk(n: Node):
            # Include node type to capture structure
            yield n.type
            # If it's a leaf node, include the actual code content
            if n.child_count == 0:
                yield n.text.decode('utf-8', errors='ignore')
            for child in n.children:
                yield from _walk(child)
        
        # Use a null byte delimiter to prevent collision between adjacent tokens
        stream = "\0".join(_walk(node))
        return hashlib.sha256(stream.encode('utf-8')).hexdigest()
