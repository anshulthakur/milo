import hashlib
import os
from typing import List, Optional, Tuple, Dict
from unidiff import Hunk
from tree_sitter import Node

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
    def format_hunk_with_line_numbers(hunk: Hunk) -> str:
        """
        Formats a hunk of code changes into a unified diff-style string with line numbers.
        This is used to provide the LLM with exact line numbers for reporting issues.
        """
        lines = []
        for i, line in enumerate(hunk):
            if line.is_added:
                prefix = "+"
                line_no = line.target_line_no
            elif line.is_removed:
                prefix = "-"
                line_no = None
                for j in range(i + 1, len(hunk)):
                    if hunk[j].target_line_no is not None:
                        line_no = hunk[j].target_line_no
                        break
                if line_no is None:
                    for j in range(i - 1, -1, -1):
                        if hunk[j].target_line_no is not None:
                            line_no = hunk[j].target_line_no
                            break
            elif line.is_context:
                prefix = " "
                line_no = line.target_line_no or line.source_line_no
            else:
                prefix = " "
                line_no = line.target_line_no or line.source_line_no or 0
            
            # Format: 4-digit line number, prefix, value
            lines.append(f"{line_no if line_no else 0:4} {prefix} {line.value}")
        return "".join(lines)

    @staticmethod
    def format_hunk_with_virtual_lines(hunk: Hunk) -> Tuple[str, Dict[int, int]]:
        """
        Formats a hunk with 1-based virtual line numbers for the LLM,
        and returns a mapping back to the actual target line numbers.
        """
        lines = []
        line_map = {}
        virtual_line = 1
        
        for i, line in enumerate(hunk):
            if line.is_added:
                prefix = "+"
                actual_line = line.target_line_no
            elif line.is_removed:
                prefix = "-"
                actual_line = None
                for j in range(i + 1, len(hunk)):
                    if hunk[j].target_line_no is not None:
                        actual_line = hunk[j].target_line_no
                        break
                if actual_line is None:
                    for j in range(i - 1, -1, -1):
                        if hunk[j].target_line_no is not None:
                            actual_line = hunk[j].target_line_no
                            break
            else:
                prefix = " "
                actual_line = line.target_line_no or line.source_line_no or 0
            
            lines.append(f"{virtual_line:4} {prefix} {line.value}")
            if actual_line is not None:
                 line_map[virtual_line] = actual_line
            virtual_line += 1
            
        return "".join(lines), line_map

    @staticmethod
    def format_code_with_virtual_lines(code: str, start_line_no: int) -> Tuple[str, Dict[int, int]]:
        """
        Formats an entire code block with 1-based virtual line numbers for the LLM,
        and returns a mapping back to the actual line numbers in the file.
        """
        lines = []
        line_map = {}
        virtual_line = 1
        
        for i, line_text in enumerate(code.splitlines(keepends=True)):
            lines.append(f"{virtual_line:4} | {line_text}")
            line_map[virtual_line] = start_line_no + i
            virtual_line += 1
            
        return "".join(lines), line_map

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
