# CRAB: Comment Review and Aggregation Bot - Architecture & Implementation Plan

## 1. Overview
CRAB is an intelligent code review assistant designed to operate locally or within CI/CD pipelines. It decouples review logic from specific git forges (GitLab/GitHub), enabling persistent, context-aware reviews that survive re-runs and code updates.

## 2. Problem Statement
Code diffs should not have the following attributes:
1.  **Brittle Hunk Matching**: Relying on exact text hashes meant trivial changes (whitespace, line shifts) invalidated previous reviews.
2.  **Statelessness**: No memory of previous comments or user responses across runs.
3.  **Context Isolation**: Reviews looked at diffs in isolation without understanding the broader repository graph.

## 3. Architecture

### 3.1 Core Components

1.  **Diff Engine (Git Interface)**
    *   Responsible for extracting changes between commits/branches.
    *   Normalizes diffs to generate stable `PatchIDs`.
    *   Tracks line number movements using Git's ancestry (blame/reverse-blame).

2.  **Context Engine (CodeSift Integration)**
    *   Leverages `repograph.py` and `repobrowser.py`.
    *   Maps raw diff hunks to **Semantic Symbols** (Functions, Classes).
    *   Retrieves dependency graphs (callers/callees) to provide the LLM with "Lookaround" capability.

3.  **State Manager (The "Cortex")**
    *   A local persistent store (JSON/SQLite) tracking the lifecycle of a review.
    *   Responsible for **Anchor Tracking**: Keeping comments attached to the correct lines as code evolves.

4.  **Review Agent**
    *   The LLM interface that generates critiques.
    *   Receives: Diff  Symbol Context  Conversation History.

### 3.2 Data Model

To solve the tracking issue, we move from "Hunk Hashes" to **Semantic Anchors**.

#### The Review Object
```json
{
  "id": "uuid-v4",
  "status": "OPEN|RESOLVED|DISMISSED",
  "anchor": {
    "file_path": "src/main.py",
    "symbol_name": "process_request",
    "symbol_type": "function",
    "patch_fingerprint": "sha256_of_normalized_diff",
    "line_range_start": 45,
    "line_range_end": 50
  },
  "conversation": [
    { "role": "bot", "content": "Potential SQL injection...", "timestamp": "..." },
    { "role": "user", "content": "Fixed in next commit.", "timestamp": "..." }
  ],
  "history": [
    { "commit_sha": "abc1234", "verdict": "fail" }
  ]
}
```

## 4. Implementation Plan

### Phase 1: Robust Diff & Anchoring
**Goal**: Identify if a change has been reviewed before, even if line numbers shift.

1.  **Semantic Mapping**:
    *   Use `Treesitter` (via `codereview.py`) to parse the *new* file version.
    *   Map every hunk in the diff to a specific function/class node.
    *   If a hunk falls outside a function (global scope), map to the file scope.

2.  **Fuzzy Fingerprinting**:
    *   Instead of hashing the raw hunk, hash the **Normalized AST** of the changed function.
    *   If the AST of `function_A` is identical to the previous run, skip review.
    *   If the AST changed, trigger a review, but provide the *previous* review of `function_A` as context to the Agent.

### Phase 2: State Management & Persistence
**Goal**: Track conversations across runs.

1.  **Local State Store**:
    *   Implement `ReviewStore` class in `milo/codereview/state.py`.
    *   Store state in `.milo/reviews.json` (git-ignored) or a user-local DB.

2.  **Forward-Porting Logic**:
    *   When running on a new commit, load previous open reviews.
    *   Attempt to locate the anchor (Function `X`) in the new file.
    *   **Verification**:
        *   If the code matches the "Suggestion" provided by the bot previously -> Mark as **RESOLVED**.
        *   If the code is different but the issue persists -> Append new bot comment.
        *   If the function is deleted -> Mark as **OBSOLETE**.

### Phase 3: Context-Aware Agent
**Goal**: Reduce hallucinations by providing graph context.

1.  **Graph Injection**:
    *   When reviewing `function_A`, query `repograph` for:
        *   `calls(function_A)`: What does it use?
        *   `called_by(function_A)`: Who uses it?
    *   Inject this metadata into the system prompt.

2.  **Conversation Loop**:
    *   Allow the user to add comments to the state file (or via CLI `crab reply <id>`).
    *   Feed these user responses back to the Agent in the next run.

## 5. Directory Structure Refactor

```
milo/
├── codereview/
│   ├── engine.py       # Main logic (formerly crab.py)
│   ├── state.py        # Persistence & History tracking
│   ├── diff.py         # Git & Hunk processing (Smart Diffing)
│   ├── anchors.py      # Logic to map lines to symbols
│   └── agents.py       # Interface to LLM
├── codesift/           # Existing analysis tools
│   ├── repograph.py
│   └── ...
```

## 6. Request Flow

### 6.1 Scenario A: Standalone Review (No Git Repository)
Used when running CRAB on a local folder or specific files without version control metadata. This mode relies heavily on AST fingerprinting to detect changes since the last run.

1. **Discovery**:
    * User provides a path (file or directory).
    * CRAB scans for supported files (py, c, cpp, etc.) ignoring standard exclude patterns.

2. **Snapshotting & Fingerprinting**:
    * Since no "diff" exists, CRAB treats the current file state as the target.
    * **Parsing**: Files are parsed using Treesitter.
    * **Fingerprinting**:
        *   Generates AST fingerprints (SHA-256) for all top-level symbols (functions, classes).
        *   Hashes the full file content for global scope/scripts.

3. **State Reconciliation**:
    * Loads the local state store (.milo/reviews.json).
    * Compares current fingerprints against stored fingerprints from the previous run.
    * **New/Modified**: If a symbol's fingerprint differs from the stored state (or is missing), it is marked for review.
    * **Unchanged**: Skipped to save tokens and time.

4. **Review Generation**:
    * Agent receives the full code of the modified symbol.
    * **Context**: No "diff" context is available, so the prompt focuses on static analysis (bugs, style, best practices) of the code block in its entirety.

5. **Persistence**:
    * Stores the new fingerprints and generated comments.
    * Anchors are purely semantic (Symbol Name + File Path).

### 6.2 Scenario B: Git Repository Review 
Used when running within a Git repo, CI/CD pipeline, or processing a Pull Request. This mode leverages Git history for precise change tracking.

1. **Context Extraction**:
    * Identifies `Base SHA` (e.g., `main` or previous commit) and `Head SHA` (current commit).
    * **DiffEngine** extracts the `PatchSet` (modified files and hunks).

2. **Semantic Mapping**:
    * For every modified file, parses the Head version.
    * Maps specific Diff Hunks to Semantic Symbols (e.g., "Hunk #1 modifies `process_request`").
3. **Anchor Resolution & Forward Porting**:
    * Check for existing OPEN reviews in `ReviewStore`.
    * For each existing review:
        *   Check if the anchor (Symbol) still exists.
        *   **Smart Blame**: Use `git blame` to see if the specific lines of the comment were modified in the new range.
        *   **AST Check**: Compare the AST fingerprint of the symbol in `Head` vs the fingerprint stored in the review.
            *   *Outcome*:
                *   **Identical AST**: Review remains OPEN, no re-analysis needed.
                *   **Modified AST**: Re-queue for review, providing previous comments as context ("Did the user fix the issue?").
                *   **Symbol Deleted**: Mark review as OBSOLETE.

4. **New Change Analysis**:
    For hunks not covered by existing reviews:
    *   Generate `PatchID` (normalized diff hash).
    *   If `PatchID` has been seen before (e.g., in a previous commit that was rebased), retrieve cached result.
    *   Otherwise, send to Agent.

5. **Agent Execution**:
    Prompt includes:
    *   The Unified Diff Hunk (with explicit line numbers for accurate reporting).
    *   The Full Symbol Code (Context).
    *   Graph Context (Callers/Callees from `repograph`).
    *   History of previous comments on this symbol.