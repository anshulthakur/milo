# Machine in the Loop (MiLo)

A library of tools to help access LLM and AI tools for productivity.

The initial goal is to add tools for developers, such as code commenting and code reviewing, code insights etc. with a focus on local-first (using Ollama).

Use OpenAI library for cross-compatibility instead of Ollama native python library.

## Project Structure

```
├── milo/
│   ├── agents/
│   │   ├── baseagent.py         # Base agent class definition
│   │   ├── documentation.py     # Documentation agent logic
│   │   └── codereview.py        # Code review agent implementation
│   ├── codereview/
│   │   ├── __init__.py
│   │   ├── codereview.py        # Main code review functionality
│   │   ├── diff.py              # Diff computation utilities
│   │   ├── models.py            # Data models for code review
│   │   └── state.py             # State management
│   ├── codesift/
│   │   ├── __init__.py
│   │   ├── repograph.py         # Repository graph representation
│   │   ├── grepast.py           # Grep with AST support
│   │   ├── languages.py         # Language detection utilities
│   │   ├── design.md            # Codesift architecture design
│   │   └── parsers/
│   │       ├── languages.py     # Parser language mappings
│   │       └── treesitter/      # Tree-sitter parser implementations
│   │           ├── treesitter_py.py       # Python parser
│   │           ├── treesitter_cpp.py      # C++ parser
│   │           ├── treesitter_go.py       # Go parser
│   │           ├── treesitter_java.py     # Java parser
│   │           ├── treesitter_cs.py       # C# parser
│   │           ├── treesitter_hs.py       # Haskell parser
│   │           ├── parse_headers_c.py     # C header parsing
│   │           └── treesitter_registry.py # Parser registry
│   ├── documentation/
│   │   ├── __init__.py
│   │   └── documentation.py     # Documentation generation module
│   ├── utils/
│   │   └── vcs.py               # Git and Filesystem operations utilities
│   ├── tools.py                 # Tool definitions for agents
├── test/
│   ├── __init__.py
│   ├── test_codereview.py       # Code review tests
│   ├── test_documentor.py       # Documentation tests
│   ├── test_repobrowser.py      # Repository browser tests
│   ├── test_repograph.py        # Repository graph tests
│   └── test_treesitter.py       # Tree-sitter parser tests
│   └── integration/
│       ├── __init__.py
│       ├── test_codereview.py   # Integration tests for codereview
│       └── test_documentor.py   # Integration tests for documentor
├── modelfiles/
│   ├── Modelfile.crab           # CRAB agent model configuration
│   └── Modelfile.comb           # COMB agent model configuration
├── docs/
│   ├── README.md                # Documentation overview
│   ├── agents.md                # Agents documentation
│   ├── architecture.md          # System architecture
│   ├── CRAB.md                  # CRAB tool documentation
│   ├── codesift.md              # Codesift documentation
│   ├── documentor.md            # Documentor tool documentation
│   ├── FLOW.md                  # Workflow and flow diagrams
│   └── proposal.md              # Project proposals
├── setup.py                     # Package installation script
├── requirements.txt             # Project dependencies
├── LICENSE                      # License file
└── README.md                    # This file
```

## Usage:
3 command line options are provided as executable scripts:

**crab**: Comment Review and Aggregation Bot
**comb**: Comment Bot
**codesift**: Utility to interact with the codebase

### CRAB
Usage:

1. Review all the staged changes in the git repo

```
crab <path-to-repo>
```

2. Review complete folder/file path irrespective of git

```
crab --path <path-to-folder-1> <path-to-folder-2> ...
crab --path <path-to-file-1> <path-to-file-2> ...
crab --path <path-to-file-1> <path-to-folder-1> ...
```

### COMB
Usage:

1. Comment code in all files affected in the staged changes in the git repo

```
comb <path-to-repo>
```

2. Comment code in complete folder/file path irrespective of git

```
comb --path <path-to-folder-1> <path-to-folder-2> ...
comb --path <path-to-file-1> <path-to-file-2> ...
comb --path <path-to-file-1> <path-to-folder-1> ...
```

### Codesift

Usage:

```
codesift
```

This will open a terminal based chat interface.