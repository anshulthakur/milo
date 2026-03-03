# COMB

Since COMB alters the code, it is recommended that the tool be run on git repositories only. This allows for examining the
diff and reverting back if needed. 

### Usage:

```
comb <path> --updates
```

3 cases arise with the path:

## Running on an entire git repository
- get git repo root folder
- Create/Update repo map
- If `--updates` flag is passed, look for files with changes
- Construct list of files to document from the entire repo
- For each file, run COMB agent


## Running on a git repository's path (folder/file)
- get git repo root folder
- Create/Update repo map
- If `--updates` flag is passed, look for files with changes at the path
- Construct list of files to document from the path in repo
- For each file, run COMB agent

## Running on a codebase without git
- Construct list of files to document at the path
- For each file, run COMB agent