import os
import json
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import traceback
import re

from milo.codesift.repograph import create_repograph
from milo.agents.codereview import get_agent as get_codereview_agent
from milo.codesift.parsers.languages import (get_file_extension, get_programming_language, guess_extension_from_shebang)
from milo.codesift.parsers import supported_languages, Treesitter
from milo.codereview.models import ReviewListModel, ReviewInputCode, CodeReview, VerificationListModel, VerificationResult
from milo.codereview.diff import DiffUtils
from milo.utils.vcs import FileManager
from milo.codereview.state import ReviewStore, Review, ReviewAnchor, ReviewStatus

def _translate_virtual_lines(text: str, line_map: Dict[int, int]) -> str:
    if not text or not line_map:
        return text
        
    def match_replacer(m):
        def num_replacer(num_match):
            v_line = int(num_match.group(0))
            return str(line_map.get(v_line, v_line))
        return re.sub(r'\d+', num_replacer, m.group(0))
        
    # Intercept variants like "line X", "lines X-Y", "lines X, Y, and Z"
    pattern = r'\b(?:line|lines)\s+\d+(?:\s*(?:-|to|and|,)\s*\d+)*\b'
    return re.sub(pattern, match_replacer, text, flags=re.IGNORECASE)

class ReviewEngine:
    """
    Extensible engine for generating code reviews using an LLM agent.
    Separates the LLM interaction from state management and VCS operations.
    """
    def __init__(self, agent):
        self.agent = agent

    def verify_reviews(self, lang: str, code: str, file_path: str, hunk_text: Optional[str], open_reviews: List[Review], line_map: Optional[Dict[int, int]] = None) -> List[VerificationResult]:
        if not open_reviews:
            return []
            
        issues_list = [{"id": r.id, "issue": r.conversation[0].content if r.conversation else "Unknown issue"} for r in open_reviews]
        issues_json = json.dumps(issues_list)
        
        if hunk_text:
            request = (f"You are reviewing changes in `{file_path}`. "
                       "The `Diff` section below contains the unified diff of modifications with line numbers on the left. "
                       "The `Full Source` section below contains the full function source after applying changes. "
                       f"Below is a JSON list of previously identified, currently OPEN issues for this function:\n{issues_json}\n"
                       "Review the new code and determine if the developer has resolved them.\n"
                       "Output a JSON array containing the `id`, the new `status` (OPEN or RESOLVED), and a `reason`.\n"
                       "IMPORTANT: Do NOT mention the virtual line numbers from the diff in your `reason`. Reference code snippets or variable names directly instead.")
        else:
            request = (f"You are reviewing changes in `{file_path}`. "
                       "The `Full Source` section below contains the full function source after applying changes. "
                       f"Below is a JSON list of previously identified, currently OPEN issues for this function:\n{issues_json}\n"
                       "Review the new code and determine if the developer has resolved them.\n"
                       "Output a JSON array containing the `id`, the new `status` (OPEN or RESOLVED), and a `reason`.\n"
                       "IMPORTANT: Do NOT mention the virtual line numbers from the code in your `reason`. Reference code snippets or variable names directly instead.")

        user_prompt = f"{request}\n\n"
        if hunk_text:
            user_prompt += f"### Diff\n```diff\n{hunk_text}\n```\n\n"
        user_prompt += f"### Full Source\n```{lang}\n{code}\n```"
        
        try:
            self.agent.clear_history()
            self.agent.set_format(VerificationListModel.json_schema())
            
            response = self.agent.call(user_prompt)
            response_json = json.loads(response)
            verifications = VerificationListModel.validate_python(response_json if isinstance(response_json, list) else [])
            return verifications
        except Exception:
            print(f"Error verifying reviews for {file_path}")
            traceback.print_exc()
            return []

    def discover_reviews(self, lang: str, code: str, file_path: str, hunk_text: Optional[str], open_reviews: List[Review], line_map: Optional[Dict[int, int]] = None) -> list:
        try:
            known_issues_text = ""
            if open_reviews:
                issues_list = [r.conversation[0].content if r.conversation else "Unknown issue" for r in open_reviews]
                known_issues_text = "\nNote: The following issues are already known and being tracked:\n" + "\n".join(f"- {iss}" for iss in issues_list) + "\nDo NOT report these again."

            if hunk_text:
                request = (f"You are reviewing changes in `{file_path}`. "
                           "The `Diff` section below contains the unified diff of modifications with line numbers on the left. "
                           "The `Full Source` section below contains the full function source after applying changes. "
                           "Analyze both added (+) and removed (-) lines. If removing code introduces a bug, report it, "
                           "but always anchor the line number of your feedback to a nearby added (+) or context ( ) line that still exists in the new code. "
                           "Do not comment on parts of the code that were not changed. "
                           "When returning the line number, use the line number listed on the left side of the diff_hunk.\n"
                           "IMPORTANT: Do NOT mention the virtual line numbers in the `description` or `suggestion` fields. Reference the code snippets or variable names directly instead.\n"
                           "IMPORTANT: ONLY report actual defects, vulnerabilities, or required improvements. Do NOT report positive feedback, code explanations, or 'no action needed' comments. If there are no issues, return an empty array `[]`.\n"
                           f"{known_issues_text}\n"
                           "Return the result in JSON format using the schema provided. "
                           "Use tools extensively to fetch further context from the repository graph to ensure code review relevance. "
                           "However, DO NOT use tools to fetch the source code of the function currently under review, as it is already provided below.")
            else:
                request = ("Please review the entire method source provided for potential bugs, style violations, or performance issues. "
                           "The `Full Source` code is provided with line numbers on the left. "
                           "When returning the line number, use the line number listed on the left side of the method code.\n"
                           "IMPORTANT: Do NOT mention the virtual line numbers in the `description` or `suggestion` fields. Reference the code snippets or variable names directly instead.\n"
                           "IMPORTANT: ONLY report actual defects, vulnerabilities, or required improvements. Do NOT report positive feedback, code explanations, or 'no action needed' comments. If there are no issues, return an empty array `[]`.\n"
                           f"{known_issues_text}\n"
                           "Return the result in JSON format using the schema provided. "
                           "Use tools extensively to fetch further context from the repository graph to ensure code review relevance. "
                           "However, DO NOT use tools to fetch the source code of the function currently under review, as it is already provided below.")

            user_prompt = f"{request}\n\n"
            if hunk_text:
                user_prompt += f"### Diff\n```diff\n{hunk_text}\n```\n\n"
            user_prompt += f"### Full Source\n```{lang}\n{code}\n```"
            
            # Inject history if available
            self.agent.clear_history()
            self.agent.set_format(ReviewListModel.json_schema())
            
            response = self.agent.call(user_prompt)
            response_json = json.loads(response)
            reviews = ReviewListModel.validate_python(response_json if isinstance(response_json, list) else [])
            
            if line_map and reviews:
                fallback_line = next(iter(line_map.values())) if line_map else 0
                for review in reviews:
                    # Map the LLM's virtual line back to the actual line number
                    # If LLM hallucinates a line, fallback to the first mapped line
                    review.line = line_map.get(review.line, fallback_line)
                    review.description = _translate_virtual_lines(review.description, line_map)
                    review.suggestion = _translate_virtual_lines(review.suggestion, line_map)
            
            return reviews
        except Exception:
            print(f"Error discovering reviews for {file_path}")
            traceback.print_exc()
            return []
            
    def generate_reviews(self, lang: str, code: str, file_path: str, hunk_text: Optional[str] = None, history: Optional[List[Any]] = None, line_map: Optional[Dict[int, int]] = None) -> list:
        return self.discover_reviews(lang, code, file_path, hunk_text, [], line_map)

def run_crab(file_manager: Optional[FileManager] = None, repo_root: Optional[str] = None, files: List[str] = None, review_staged: bool = False) -> List[Review]:
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
    review_engine = ReviewEngine(agent)

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
    all_reviews = []
    
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
            
        file_reviews = process_file_changes(
            file_path=file_path,
            file_content=file_content,
            hunks=patched_file,
            review_store=review_store,
            review_engine=review_engine,
            repo_root=repo_root
        )
        
        for review, generated_items in file_reviews:
            for item in generated_items:
                print(f"[{item.type.value}] {file_path}:{item.line} - {item.description}")
                review.add_bot_comment(f"[{item.type.value}] {item.description}\nSuggestion: {item.suggestion}")
            review_store.add_review(review)
            all_reviews.append(review)
        
    return all_reviews

def process_file_changes(file_path, file_content, hunks, review_store, review_engine, repo_root, force_review: bool = False) -> List[Tuple[Review, List[CodeReview]]]:
    """
    Maps diff hunks to semantic symbols and triggers reviews.
    """
    # 1. Parse file
    extension = get_file_extension(file_path)
    lang = get_programming_language(extension)
    if lang.value not in supported_languages():
        return []

    treesitter = Treesitter.create_treesitter(lang)
    treesitter.parse(file_content.encode('utf-8'))
    
    # Get all function definitions to map hunks
    definitions = treesitter.get_definitions("function")
    new_reviews = []
    
    # Build the list of targets to review: either mapped from hunks, or all definitions if no hunks.
    review_targets = []
    if hunks:
        for hunk in hunks:
            if not hunk:
                #Hunk may be none (seen in some cases)
                continue
            hunk_start = hunk.target_start
            hunk_end = hunk.target_start + hunk.target_length
            
            # Determine which target lines were actually changed
            changed_target_lines = []
            for i, line in enumerate(hunk):
                if line.is_added:
                    changed_target_lines.append(line.target_line_no)
                elif line.is_removed:
                    target_line = None
                    for j in range(i + 1, len(hunk)):
                        if hunk[j].target_line_no is not None:
                            target_line = hunk[j].target_line_no
                            break
                    if target_line is None:
                        for j in range(i - 1, -1, -1):
                            if hunk[j].target_line_no is not None:
                                target_line = hunk[j].target_line_no
                                break
                    if target_line is not None:
                        changed_target_lines.append(target_line)

            matched_defs_set = set()
            
            for line_no in changed_target_lines:
                best_def = None
                min_dist = float('inf')
                for definition in definitions:
                    def_start = definition.node.start_point[0] + 1
                    def_end = definition.node.end_point[0] + 1
                    
                    if def_start <= line_no <= def_end:
                        dist = 0
                    elif line_no < def_start:
                        dist = def_start - line_no
                    else:
                        dist = line_no - def_end
                        
                    if dist < min_dist:
                        min_dist = dist
                        best_def = definition
                        
                # Allow up to 10 lines of proximity buffer to attach detached comments/macros
                if best_def and min_dist <= 10:
                    matched_defs_set.add(best_def)
            
            matched_defs = list(matched_defs_set)
            
            # Fallback to general overlap if no changed lines are strictly inside any function
            if not matched_defs:
                max_overlap = 0
                best_match = None
                for definition in definitions:
                    def_start = definition.node.start_point[0] + 1
                    def_end = definition.node.end_point[0] + 1
                    hunk_end_inclusive = max(hunk_start, hunk.target_start + hunk.target_length - 1)
                    overlap_start = max(hunk_start, def_start)
                    overlap_end = min(hunk_end_inclusive, def_end)
                    overlap = max(0, overlap_end - overlap_start + 1)
                    if overlap > max_overlap:
                        max_overlap = overlap
                        best_match = definition
                if best_match:
                    matched_defs.append(best_match)
            
            for matched_def in matched_defs:
                review_targets.append((hunk, matched_def))
    else:
        # Standalone mode: Review all definitions in the file
        for definition in definitions:
            review_targets.append((None, definition))

    for hunk, matched_def in review_targets:

        symbol_name = matched_def.name
        symbol_code = matched_def.source_code
        
        # 3. Compute Fingerprints
        patch_fingerprint = DiffUtils.compute_patch_fingerprint(hunk)
        ast_fingerprint = DiffUtils.compute_ast_fingerprint(matched_def.node)
        
        # 4. Check State
        open_reviews = review_store.get_open_reviews_for_symbol(file_path, symbol_name)
        
        skip_symbol = False
        if open_reviews:
            if open_reviews[0].anchor.ast_fingerprint == ast_fingerprint and not force_review:
                print(f"Skipping {symbol_name} (AST unchanged)")
                skip_symbol = True
                
        if skip_symbol:
            continue

        print(f"Reviewing {symbol_name} (Phase 1 & 2)")

        if hunk:
            hunk_text, line_map = DiffUtils.format_hunk_with_virtual_lines(hunk)
            method_text = symbol_code # Leave method without numbers so LLM focuses on hunk
        else:
            hunk_text = None
            method_text, line_map = DiffUtils.format_code_with_virtual_lines(symbol_code, matched_def.node.start_point[0] + 1)

        still_open_reviews = []
        if open_reviews:
            print(f"Phase 1: Verifying {len(open_reviews)} open issue(s) for {symbol_name}")
            verifications = review_engine.verify_reviews(
                lang=lang.value,
                code=method_text,
                file_path=file_path,
                hunk_text=hunk_text,
                open_reviews=open_reviews,
                line_map=line_map
            )
            
            ver_dict = {v.id: v for v in verifications}
            
            for r in open_reviews:
                v = ver_dict.get(r.id)
                if v:
                    if v.status.value == "RESOLVED":
                        r.mark_resolved()
                        r.add_bot_comment(f"RESOLVED: {v.reason}")
                        review_store.add_review(r)
                    else:
                        r.add_bot_comment(f"OPEN: {v.reason}")
                        r.anchor.ast_fingerprint = ast_fingerprint
                        r.anchor.patch_fingerprint = patch_fingerprint
                        review_store.add_review(r)
                        still_open_reviews.append(r)
                else:
                    r.anchor.ast_fingerprint = ast_fingerprint
                    r.anchor.patch_fingerprint = patch_fingerprint
                    review_store.add_review(r)
                    still_open_reviews.append(r)
                    
        print(f"Phase 2: Discovering new issues for {symbol_name}")
        new_defects = review_engine.discover_reviews(
            lang=lang.value,
            code=method_text,
            file_path=file_path,
            hunk_text=hunk_text,
            open_reviews=still_open_reviews,
            line_map=line_map
        )
        
        if new_defects:
            for defect in new_defects:
                anchor = ReviewAnchor(
                    file_path=file_path,
                    symbol_name=symbol_name,
                    symbol_type="function",
                    patch_fingerprint=patch_fingerprint,
                    ast_fingerprint=ast_fingerprint,
                    line_range_start=matched_def.node.start_point[0] + 1,
                    line_range_end=matched_def.node.end_point[0] + 1
                )
                new_review = Review(anchor=anchor)
                new_reviews.append((new_review, [defect]))
                
    return new_reviews
