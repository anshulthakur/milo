# Milo Architecture Evolution Proposal

## 1. Executive Summary

Milo has evolved from a set of standalone scripts into a nascent Code Intelligence Platform. The current architecture successfully demonstrates **Graph-Augmented Generation (GAG)**, where LLM agents are grounded by a repository call graph (`repograph`).

However, the current implementation suffers from monolithic orchestration logic, expensive re-computation of context, and a fragmentation between local execution (`codereview.py`) and CI/CD logic (`legacy.py`).

This proposal outlines a strategy to refactor Milo into a modular, extensible platform capable of incremental analysis and multi-forge support.

## 2. Architectural Critique

### 2.1. Strengths
*   **Context-Awareness**: The `RepoGraph` and `RepoBrowser` provide agents with "lookaround" capabilities, significantly reducing hallucinations compared to naive file-level analysis.
*   **State Management**: The `ReviewStore` (JSON-based) correctly decouples the review state from the code, allowing for persistence across runs.
*   **Tooling**: The `Treesitter` integration is robust and allows for precise AST-based querying.

### 2.2. Weaknesses
*   **Expensive Context Building**: `create_repograph` parses the entire repository on every run. For large repositories, this is a performance bottleneck.
*   **Coupled Orchestration**: `run_crab` and `run_comb` mix configuration, VCS operations, graph generation, and agent interaction in single functions.
*   **Provider Fragmentation**: `codereview.py` uses a clean `VCSProvider` abstraction, but `legacy.py` contains rich GitLab-specific logic (cloning, MR comments) that is currently orphaned and tightly coupled to the `python-gitlab` library.
*   **Hardcoded Agents**: Agent configuration (prompts, parameters) is buried in Python code (`agents/codereview.py`), making it hard to tune without code changes.

## 3. Proposed Architecture: The "Milo Platform"

We propose moving to a layered architecture:

```mermaid
graph TD
    CLI[CLI / CI Runner] --> Orchestrator
    Orchestrator --> ContextEngine
    Orchestrator --> AgentRuntime
    Orchestrator --> ForgeLayer
    
    subgraph ContextEngine [Context Engine]
        Indexer[Incremental Indexer]
        GraphDB[NetworkX Graph]
        VectorDB[Vector Store (Future)]
    end
    
    subgraph ForgeLayer [Forge Abstraction]
        VCS[VCS Provider (Git)]
        Remote[Forge Provider (GitLab/GitHub)]
    end
    
    subgraph AgentRuntime [Agent Runtime]
        Registry[Agent Registry]
        Tools[Toolbox]
        LLM[LLM Client (Ollama/OpenAI)]
    end
```

### 3.1. The Context Engine (Incremental Analysis)
**Problem**: Re-parsing the whole repo is slow.
**Solution**: Implement an **Incremental Indexer**.
1.  **Checksum Tracking**: Store a map of `{file_path: file_hash}`.
2.  **Delta Parsing**: On startup, compare current file hashes with the stored map. Only re-parse changed files using Tree-sitter.
3.  **Graph Patching**: Update the `networkx` graph by removing nodes/edges belonging to changed files and re-inserting the new ones.

### 3.2. The Forge Abstraction Layer
**Problem**: `legacy.py` logic needs to be integrated without polluting the core logic with GitLab dependencies.
**Solution**: Split the abstraction into two distinct interfaces:

1.  **`VCSProvider`** (Existing): Handles local git operations (diffs, blame, file content).
    *   *Implementations*: `LocalGitProvider`.
2.  **`ForgeProvider`** (New): Handles remote interactions.
    *   *Methods*: `post_comment(file, line, body)`, `get_merge_request_details()`, `update_status()`.
    *   *Implementations*: `GitLabProvider` (porting `legacy.py`), `GitHubProvider`, `LocalMockProvider` (for standalone runs).

### 3.3. Configurable Agent Runtime
**Problem**: Prompts are hardcoded.
**Solution**: Externalize Agent definitions to YAML/TOML.

```yaml
agents:
  reviewer:
    model: "qwen2.5-coder"
    system_prompt_path: "prompts/reviewer.md"
    tools:
      - "fetch_source"
      - "get_call_graph"
    parameters:
      temperature: 0.2
```

## 4. Implementation Roadmap

### Phase 1: Consolidation (The "Refactor")
*   **Goal**: Retire `legacy.py` and fully utilize `VCSProvider`.
*   **Tasks**:
    1.  Implement `GitLabProvider` implementing a new `ForgeProvider` interface.
    2.  Move the "Hunk to Function" mapping logic from `legacy.py` into `DiffUtils` or a specialized `CodeMapper` class.
    3.  Update `run_crab` to accept a `ForgeProvider` argument.

### Phase 2: Optimization (The "Indexer")
*   **Goal**: Sub-second startup time for re-runs.
*   **Tasks**:
    1.  Modify `create_repograph` to accept a `previous_metadata` argument.
    2.  Implement file hashing and delta detection.
    3.  Serialize the graph to a more efficient format (e.g., Pickle or a lightweight DB) instead of just JSON.

### Phase 3: Intelligence (The "Brain")
*   **Goal**: Semantic understanding beyond structure.
*   **Tasks**:
    1.  Integrate a Vector Database (e.g., ChromaDB or FAISS).
    2.  Embed function bodies and docstrings during indexing.
    3.  Add a `semantic_search` tool to the Agent, allowing it to find code based on "meaning" rather than just regex or call graph.

## 5. Specific Code Recommendations

### 5.1. Refactoring `codereview.py`
Currently, `process_file_changes` does too much. It should be split:
*   `ChangeDetector`: Identifies what changed (VCS).
*   `ContextBuilder`: Assembles the prompt (Graph + Diff).
*   `ReviewEngine`: Interactions with the Agent.

### 5.2. Enhancing `repograph.py`
The `call_dict` global variable is a code smell. This should be encapsulated within a `RepoGraphBuilder` class instance to ensure thread safety and cleaner state management.

### 5.3. Unified Configuration
Create a `milo.config` module using `pydantic-settings`. This will centralize reading from `pyproject.toml`, `.env`, and CLI arguments, removing the reliance on scattered `os.environ.get` calls.

## 6. Conclusion

Milo is well-positioned to be a powerful local-first code assistant. By formalizing the `ForgeProvider` interface and implementing incremental indexing, we can make it robust enough for heavy CI/CD usage while keeping the developer experience fast and responsive.