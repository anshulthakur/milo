import os
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
import traceback

from milo.codesift.repograph import create_repograph, extract_function_calls
from milo.agents.codereview import get_agent as get_codereview_agent
from milo.codesift.parsers.utils import (get_file_extension, get_programming_language, guess_extension_from_shebang)
from milo.codesift.parsers import supported_languages, Treesitter
from milo.codereview.models import InputCode, ReviewListModel
from milo.codereview.diff import VCSProvider, DiffUtils
from milo.codereview.state import ReviewStore, Review, ReviewAnchor, ReviewStatus

def run_crab(vcs: Optional[VCSProvider] = None, repo_root: Optional[str] = None, files: List[str] = []) -> None:
    """
    Main entry point for CRAB (Comment Review and Aggregation Bot).
    Orchestrates the review process using VCS, State Store, and Agents.
    """
    if not repo_root and vcs:
        # If using VCS, assume repo_root is managed by it or passed explicitly
        pass
    elif not repo_root:
        # Fallback for standalone mode
        repo_root = os.getcwd()

    # 1. Initialize State Store
    repomap_path = None
    if repo_root:
        repomap_path = os.path.join(repo_root, '.milo')
        Path(repomap_path).mkdir(exist_ok=True)
    else:
        repomap_path = os.path.join('/tmp', 'milo')
        Path(repomap_path).mkdir(exist_ok=True)
    
    review_store = ReviewStore(Path(repomap_path) / "reviews.json")
    
    # 2. Generate/Load Repograph for Context
    # We create it fresh to ensure we have the latest context
    create_repograph(root=str(repo_root), save_path=repomap_path)
    metadata_path = os.path.join(repomap_path, "metadata.json")

    # 3. Initialize Agent
    agent = get_codereview_agent(metadata_path=metadata_path, repo_path=repo_root)

    # 4. Determine Changes to Review
    if vcs:
        # Scenario B: Git Repository Review
        # We assume we are reviewing changes between HEAD and its parent (or a base branch)
        # For simplicity, let's diff against HEAD~1 if not specified
        # In a real CI env, these would be arguments.
        head_rev = vcs.get_current_rev()
        base_rev = f"{head_rev}~1" # Default to previous commit
        
        patch_set = vcs.get_changes(base_rev, head_rev)
        
        for patched_file in patch_set:
            file_path = patched_file.path
            full_path = os.path.join(repo_root, file_path)
            
            # Skip deletions
            if patched_file.is_removed_file:
                continue

            # Parse the NEW file content to map hunks to symbols
            file_content = vcs.get_file_content(file_path, head_rev)
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
            
    else:
        # Scenario A: Standalone Review
        # Iterate over provided files, treat everything as "new" but check against state
        for file_path in files:
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                
                # In standalone mode, we don't have diff hunks. 
                # We review the whole file's symbols if they changed.
                process_file_symbols(
                    file_path=file_path,
                    file_content=content,
                    review_store=review_store,
                    agent=agent,
                    repo_root=repo_root
                )
            except Exception as e:
                print(f"Error processing {file_path}: {e}")

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
                line_range=(matched_def.node.start_point[0] + 1, matched_def.node.end_point[0] + 1)
            )

def process_file_symbols(file_path, file_content, review_store, agent, repo_root):
    """
    Standalone mode: iterates all symbols and checks for changes.
    """
    extension = get_file_extension(file_path)
    lang = get_programming_language(extension)
    if lang.value not in supported_languages():
        return

    treesitter = Treesitter.create_treesitter(lang)
    treesitter.parse(file_content.encode('utf-8'))
    definitions = treesitter.get_definitions("function")

    for definition in definitions:
        symbol_name = definition.name
        symbol_code = definition.source_code
        ast_fingerprint = DiffUtils.compute_ast_fingerprint(definition.node)
        
        existing_review = review_store.find_matching_review(file_path, symbol_name)
        
        if existing_review and existing_review.anchor.ast_fingerprint == ast_fingerprint:
            continue
            
        # If changed or new, review it
        perform_review(
            agent=agent,
            lang=lang.value,
            code=symbol_code,
            file_path=file_path,
            symbol_name=symbol_name,
            history=existing_review.conversation if existing_review else [],
            review_store=review_store,
            patch_fingerprint="standalone_no_diff",
            ast_fingerprint=ast_fingerprint,
            line_range=(definition.node.start_point[0] + 1, definition.node.end_point[0] + 1)
        )

def perform_review(agent, lang, code, file_path, symbol_name, history, review_store, patch_fingerprint, ast_fingerprint, line_range):
    try:
        user_prompt = InputCode(
            language=lang,
            method=code,
            docstring="" # Docstring extraction can be improved
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
