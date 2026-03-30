import os
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
import traceback

from milo.codesift.repograph import create_repograph
from milo.agents.codereview import get_agent as get_codereview_agent
from milo.codesift.parsers.languages import (get_file_extension, get_programming_language, guess_extension_from_shebang)
from milo.codesift.parsers import supported_languages, Treesitter
from milo.codereview.models import ReviewListModel, ReviewInputCode
from milo.codereview.diff import DiffUtils
from milo.utils.vcs import FileManager
from milo.codereview.state import ReviewStore, Review, ReviewAnchor, ReviewStatus

def run_crab(file_manager: Optional[FileManager] = None, repo_root: Optional[str] = None, files: List[str] = None, review_staged: bool = False) -> None:
    """
    Main entry point for CRAB (Comment Review and Aggregation Bot).
    Orchestrates the review process using file managers, State Store, and Agents.
    """
    if not repo_root and file_manager:
        repo_root = file_manager.repo_root
    elif not repo_root:
        # Fallback for standalone mode
        repo_root = os.getcwd()

    if files is None:
        files = []

    # 1. Initialize State Store
    repomap_path = None
    if repo_root:
        repomap_path = os.path.join(repo_root, '.milo')
        Path(repomap_path).mkdir(parents=True, exist_ok=True)
    else:
        repomap_path = os.path.join('/tmp', 'milo')
        Path(repomap_path).mkdir(parents=True, exist_ok=True)
    
    review_store = ReviewStore(Path(repomap_path) / "reviews.json")
    
    # 2. Generate/Load Repograph for Context
    # We create it fresh to ensure we have the latest context
    if repo_root:
        create_repograph(root=str(repo_root), save_path=repomap_path)
    metadata_path = os.path.join(repomap_path, "metadata.json")

    # 3. Initialize Agent
    agent = get_codereview_agent(metadata_path=metadata_path, repo_path=repo_root)

    # 4. Determine Changes to Review
    if not file_manager:
        print("No file manager supplied. Cannot determine changes.")
        return

    if review_staged:
        # Scenario C: Review staged changes against HEAD
        base_rev = file_manager.get_current_rev()
        head_rev = 'index'
    else:
        # Scenario B: Git Repository Review (committed changes) or Standalone Review
        head_rev = file_manager.get_current_rev()
        base_rev = f"{head_rev}~1" if head_rev != "HEAD" else "HEAD"
    
    patch_set = file_manager.get_changes(base_rev, head_rev)
    
    for patched_file in patch_set:
        file_path = patched_file.path
        
        if patched_file.is_removed_file:
            continue

        abs_file_path = os.path.abspath(os.path.join(repo_root, file_path))
        if files:
            if not any(os.path.abspath(f) == abs_file_path for f in files):
                continue

        file_content = file_manager.get_file_content(file_path, head_rev)
        if not file_content:
            continue
            
        process_file_changes(
            file_path=file_path,
            file_content=file_content,
            hunks=patched_file,
            review_store=review_store,
            agent=agent,
            repo_root=repo_root
        )

def process_file_changes(file_path, file_content, hunks, review_store, agent, repo_root):
    """
    Maps diff hunks to semantic symbols and triggers reviews.
    """
    # 1. Parse file
    extension = get_file_extension(file_path)
    lang = get_programming_language(extension)
    if lang.value not in supported_languages():
        return

    treesitter = Treesitter.create_treesitter(lang)
    treesitter.parse(file_content.encode('utf-8'))
    
    # Get all function definitions to map hunks
    definitions = treesitter.get_definitions("function")
    
    for hunk in hunks:
        # 2. Map hunk to symbol
        # We use the target start line of the hunk
        hunk_start = hunk.target_start
        hunk_end = hunk.target_start + hunk.target_length
        
        matched_def = None
        for definition in definitions:
            # Tree-sitter uses 0-based indexing, diff uses 1-based
            def_start = definition.node.start_point[0] + 1
            def_end = definition.node.end_point[0] + 1
            
            # Check overlap
            if (hunk_start <= def_end) and (hunk_end >= def_start):
                matched_def = definition
                break
        
        if not matched_def:
            continue # Skip changes outside functions for now (or handle global scope later)

        symbol_name = matched_def.name
        symbol_code = matched_def.source_code
        
        # 3. Compute Fingerprints
        patch_fingerprint = DiffUtils.compute_patch_fingerprint(hunk)
        ast_fingerprint = DiffUtils.compute_ast_fingerprint(matched_def.node)
        
        # 4. Check State
        existing_review = review_store.find_matching_review(file_path, symbol_name)
        
        needs_review = False
        context_history = []
        
        if existing_review:
            # Check if AST changed since last review
            if existing_review.anchor.ast_fingerprint == ast_fingerprint:
                print(f"Skipping {symbol_name} (AST unchanged)")
                continue
            else:
                print(f"Re-reviewing {symbol_name} (AST changed)")
                needs_review = True
                context_history = existing_review.conversation
        else:
            print(f"New review for {symbol_name}")
            needs_review = True

        if needs_review:
            # 5. Invoke Agent
            perform_review(
                agent=agent,
                lang=lang.value,
                code=symbol_code,
                file_path=file_path,
                symbol_name=symbol_name,
                history=context_history,
                review_store=review_store,
                patch_fingerprint=patch_fingerprint,
                ast_fingerprint=ast_fingerprint,
                line_range=(matched_def.node.start_point[0] + 1, matched_def.node.end_point[0] + 1),
                hunk=hunk
            )

def perform_review(agent, lang, code, file_path, symbol_name, history, review_store, patch_fingerprint, ast_fingerprint, line_range, hunk=None):
    try:
        hunk_text = DiffUtils.format_hunk_with_line_numbers(hunk) if hunk else None
        
        if hunk_text:
            request = (f"You are reviewing changes in `{file_path}`. "
                       "The `diff_hunk` field contains the unified diff of modifications with line numbers. "
                       "The `method` field contains the full function source after applying changes. "
                       "Focus on issues introduced by the change (lines starting with +). "
                       "Do not comment on parts of the code that were not changed. "
                       "Return the result in JSON format using the schema provided. "
                       "Use tools extensively to fetch further context from the repository graph to ensure code review relevance.")
        else:
            request = ("Please review the entire method source provided for potential bugs, style violations, or performance issues. "
                       "Return the result in JSON format using the schema provided. "
                       "Use tools extensively to fetch further context from the repository graph to ensure code review relevance.")

        user_prompt = ReviewInputCode(
            language=lang,
            method=code,
            file_path=file_path,
            diff_hunk=hunk_text,
            request=request
        )
        
        # Inject history if available
        # Note: Agent currently takes a single prompt string, so we might need to append history to the prompt
        # or update the agent to handle conversation history explicitly.
        # For now, we rely on the agent's internal state if it persists, or we'd append it here.
        
        agent.clear_history()
        agent.set_format(ReviewListModel.json_schema())
        
        # TODO: Inject history into prompt text if Agent doesn't support it natively yet
        
        response = agent.call(user_prompt.model_dump_json())
        response_json = json.loads(response)
        reviews = ReviewListModel.validate_python(
            response_json if isinstance(response_json, list) else []
        )
        
        # Create or Update Review Object
        anchor = ReviewAnchor(
            file_path=file_path,
            symbol_name=symbol_name,
            symbol_type="function",
            patch_fingerprint=patch_fingerprint,
            ast_fingerprint=ast_fingerprint,
            line_range_start=line_range[0],
            line_range_end=line_range[1]
        )
        
        existing_review = review_store.find_matching_review(file_path, symbol_name)
        
        if existing_review:
            review = existing_review
            review.anchor = anchor # Update anchor with new fingerprints/lines
        else:
            review = Review(anchor=anchor)
        
        for item in reviews:
            print(f"[{item.type}] {file_path}:{item.line} - {item.description}")
            review.add_bot_comment(f"[{item.type}] {item.description}\nSuggestion: {item.suggestion}")
            
        review_store.add_review(review)
        
    except Exception:
        print(f"Error reviewing {symbol_name}")
        traceback.print_exc()
