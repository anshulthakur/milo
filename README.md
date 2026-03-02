# Machine in the Loop (MiLo)

A library of tools to help access LLM and AI tools for productivity.

The initial goal is to add tools for developers, such as code commenting and code reviewing, code insights etc. with a focus on local-first (using Ollama).

Use OpenAI library for cross-compatibility instead of Ollama native python library.

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