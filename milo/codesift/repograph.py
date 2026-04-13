import os
import sys
import networkx as nx
from milo.codesift.parsers.treesitter.treesitter import Treesitter
from milo.codesift.parsers.languages import supported_languages, supported_extensions, get_programming_language, get_file_extension, guess_extension_from_shebang
from tree_sitter import Node, Tree
import json
import re
from collections import defaultdict
import traceback
from milo.codesift.repository import Repository

class RepoGraph:
    """
    Encapsulates the repository call graph and providing browsing utilities.
    """
    def __init__(self, repository: Repository):
        self.repo = repository
        self.graph = nx.DiGraph()
        self.call_dict = {}
        self.metadata = {}
        self.reset_call_dict()

    def reset_call_dict(self):
        self.call_dict.clear()
        self.call_dict["third_party"] = defaultdict(lambda: {"called_by": []})
        self.call_dict["dynamic_entry_point_candidates"] = []

    def _get_qualified_name(self, func_node):
        name = func_node.name
        # Heuristic for Python class methods
        if hasattr(func_node, 'node'):
            parent = func_node.node.parent
            while parent:
                if parent.type == 'class_definition':
                    class_name_node = parent.child_by_field_name('name')
                    if class_name_node:
                        class_name = class_name_node.text.decode('utf-8')
                        if not name.startswith(f"{class_name}."):
                            name = f"{class_name}.{name}"
                    break
                if parent.type in ('function_definition', 'translation_unit', 'module'):
                    break
                parent = parent.parent
        return name

    def update_callgraph(self, caller, callee=None, params=None, filename=None):
        if filename:
            key = f"{filename}::{caller}"
        else:
            key = caller

        callee_key = None

        if key not in self.call_dict:
            self.call_dict[key] = {
                "func_name": caller,
                "args": params or "",
                "calls": [],
                "defined_in": filename,
                "summary": "",
            }

        if callee:
            if not callee_key:
                for k in self.call_dict:
                    if k.endswith(f"::{callee}"):
                        callee_key = k
                        break

            if not callee_key:
                third_party = self.call_dict.setdefault("third_party", {})
                tp = third_party.setdefault(callee, {"called_by": []})
                if key not in tp["called_by"]:
                    tp["called_by"].append(key)
            else:
                if callee_key not in self.call_dict[key]["calls"]:
                    self.call_dict[key]["calls"].append(callee_key)

        if params and self.call_dict[key]["args"] != params.strip():
            # print(f"Warning: Update {key} params from {self.call_dict[key]['args'].strip()} to {params}")
            self.call_dict[key]["args"] = params.strip()

    def extract_function_calls(self, treesitter: Treesitter, filename: str):
        # 1. Map function definitions
        functions = treesitter.get_definitions("function")

        for func_node in functions:
            current_func = self._get_qualified_name(func_node)
            params = func_node.parameters
            self.update_callgraph(caller=current_func, params=params, filename=filename)

        # 2. Map direct calls within functions
        for func_node in functions:
            current_func = self._get_qualified_name(func_node)
            calls = treesitter.get_calls(func_node.node)
            for call_node in calls:
                callee = call_node.name
                self.update_callgraph(caller=current_func, callee=callee, filename=filename)

        # 3. Map dynamic entry points (File-level scan)
        # We scan the whole file tree because dynamic entries (callbacks) might happen 
        # inside functions, or potentially in global scope initializers (C/C++).
        if hasattr(treesitter, 'tree') and treesitter.tree:
            root = treesitter.tree.root_node
            dynamic_entries = treesitter.get_dynamic_entry_points(root)
            for entry in dynamic_entries:
                candidate_name = entry.name
                call_expr_node = entry.node
                while call_expr_node and call_expr_node.type != 'call_expression':
                    call_expr_node = call_expr_node.parent

                if call_expr_node:
                    function_id_node = call_expr_node.child_by_field_name('function')
                    if function_id_node:
                        dynamic_caller_name = function_id_node.text.decode().strip()
                        caller_key = f"{filename}::{dynamic_caller_name}"
                        if candidate_name:
                            candidate_name = candidate_name.strip()
                            self.call_dict['dynamic_entry_point_candidates'].append((caller_key, candidate_name))

    def resolve_dynamic_entry_points(self):
        candidates = self.call_dict.pop('dynamic_entry_point_candidates', [])
        if not candidates:
            return

        name_to_key_map = defaultdict(list)
        for k in self.call_dict:
            if k not in ("third_party", "dynamic_entry_point_candidates") and "::" in k:
                name_to_key_map[k.split('::')[-1]].append(k)

        for caller_key, candidate_name in candidates:
            # 1. Resolve the Callee (the function being registered)
            possible_callees = name_to_key_map.get(candidate_name, [])
            resolved_callee_key = None
            caller_filename = caller_key.split('::')[0]
            
            if possible_callees:
                # Prefer same file
                for key in possible_callees:
                    if key.startswith(caller_filename + '::'):
                        resolved_callee_key = key
                        break
                # Fallback to unique global match
                if not resolved_callee_key and len(possible_callees) == 1:
                    resolved_callee_key = possible_callees[0]
            
            # If callee is found, mark it as a dynamic entry point
            if resolved_callee_key and resolved_callee_key in self.call_dict:
                self.call_dict[resolved_callee_key]['is_dynamic_entry_point'] = True
            
            # 2. Resolve the Caller (the registrar function)
            # The caller_key constructed in extract_function_calls uses the call-site filename.
            # If the registrar is defined in the same file, this key matches exactly.
            resolved_caller_key = None
            if caller_key in self.call_dict:
                resolved_caller_key = caller_key
            else:
                # Try to resolve by name if exact key match fails (e.g. path differences)
                caller_name = caller_key.split('::')[-1]
                possible_callers = name_to_key_map.get(caller_name, [])
                
                # Prefer same file
                for key in possible_callers:
                    if key.startswith(caller_filename + '::'):
                        resolved_caller_key = key
                        break
                
                # Fallback to unique global match
                if not resolved_caller_key and len(possible_callers) == 1:
                    resolved_caller_key = possible_callers[0]
            
            # 3. Add the edge if both resolved
            # This represents that 'registering' the callback implies the registrar 'calls' the callback
            if resolved_callee_key and resolved_caller_key:
                if resolved_caller_key in self.call_dict:
                     if resolved_callee_key not in self.call_dict[resolved_caller_key]['calls']:
                        self.call_dict[resolved_caller_key]['calls'].append(resolved_callee_key)

    def resolve_references(self):
        """
        Resolves calls that were tentatively marked as third-party because the callee
        had not been parsed yet.
        """
        third_party = self.call_dict.get("third_party", {})
        if not third_party:
            return

        # Build lookup map for all defined functions
        name_to_key_map = defaultdict(list)
        for k in self.call_dict:
            if k not in ("third_party", "dynamic_entry_point_candidates") and "::" in k:
                name_to_key_map[k.split('::')[-1]].append(k)

        resolved_callees = []

        for callee_name, info in third_party.items():
            possible_matches = name_to_key_map.get(callee_name)
            if possible_matches:
                # Match found in repo; resolve to the first match
                target_key = possible_matches[0]
                
                # Update callers
                for caller_key in info.get("called_by", []):
                    if caller_key in self.call_dict:
                        if target_key not in self.call_dict[caller_key]["calls"]:
                            self.call_dict[caller_key]["calls"].append(target_key)
                
                resolved_callees.append(callee_name)

        # Remove resolved from third_party
        for callee in resolved_callees:
            del third_party[callee]

    def build(self):
        self.graph = nx.DiGraph()
        self.reset_call_dict()

        # 1. Parse each file
        files = self.repo.list_files()
        for filepath in files:
            extension = get_file_extension(filepath)
            content = self.repo.get_file_content(filepath)
            if not content:
                continue

            if len(extension) == 0:
                extension = guess_extension_from_shebang(file_content=content)
            
            if not extension:
                # print(f"Undetermined extension in {filepath}")
                continue
                
            lang = get_programming_language(extension)
            if lang.value not in supported_languages():
                continue
            
            treesitter = Treesitter.create_treesitter(lang)
            rel_path = os.path.relpath(filepath, self.repo.root_path)
            
            try:
                treesitter.parse(content.encode("utf8"))
                self.extract_function_calls(treesitter, filename=rel_path)
            except Exception:
                print(f"Could not extract calls from {filepath}")
                traceback.print_exc()

        self.resolve_references()
        self.resolve_dynamic_entry_points()

        # 2. Add definitions to graph
        for func_id, meta in self.call_dict.items():
            if func_id in ["third_party", "dynamic_entry_points"]:
                continue
            self.graph.add_node(func_id, label=func_id.split("::")[-1], **meta)
            for callee_key in meta.get("calls", []):
                self.graph.add_edge(func_id, callee_key)

        # 3. Track third-party
        third_party = self.call_dict.get("third_party", {})
        for callee, info in third_party.items():
            stub_id = f"external::{callee}"
            if not self.graph.has_node(stub_id):
                self.graph.add_node(
                    stub_id,
                    label=callee,
                    func_name=callee,
                    defined_in="external",
                    calls=[],
                    is_third_party=True,
                )
            for caller in info.get("called_by", []):
                if self.graph.has_node(caller):
                    self.graph.add_edge(caller, stub_id)

        # 4. Annotate metadata
        for func_id, meta in self.call_dict.items():
            if func_id in ["third_party", "dynamic_entry_points"]:
                continue

            file = meta.get("defined_in", "").lower()
            name = func_id.split("::")[-1].lower()

            meta["incoming_calls"] = (
                list(self.graph.predecessors(func_id)) if func_id in self.graph else []
            )
            meta["semantic_role"] = (
                "initializer"
                if name.startswith("init") or name.startswith("setup")
                else (
                    "handler"
                    if name.startswith("handle") or name.endswith("handler")
                    else (
                        "utility"
                        if "util" in file or "helper" in file
                        else (
                            "test"
                            if "test" in file or name.startswith("test_")
                            else "unspecified"
                        )
                    )
                )
            )
            meta["is_test"] = "test" in file or name.startswith("test_")
            meta["call_depth"] = None

    def save(self, save_path: str):
        # Write DOT
        nx.drawing.nx_pydot.write_dot(self.graph, os.path.join(save_path, "callgraph.dot"))

        # Write Callflow text
        with open(os.path.join(save_path, "callflow.txt"), "w") as callflow_file:
            def print_call_tree(func, depth=0, visited=None):
                if visited is None:
                    visited = set()
                if func in visited:
                    return
                visited.add(func)
                callflow_file.write("  " * depth + func + "\n")
                for callee in self.graph.successors(func):
                    print_call_tree(callee, depth + 1, visited)

            top_level_funcs = [node for node in self.graph.nodes if self.graph.in_degree(node) == 0]
            for func in sorted(top_level_funcs):
                print_call_tree(func, visited=set())

        # Build metadata.json
        defined_mappings = {}
        third_party_mappings = {}
        lookup = defaultdict(list)
        
        third_party = self.call_dict.get("third_party", {})

        for fn_id, meta in self.call_dict.items():
            if fn_id in ["third_party", "dynamic_entry_points"]:
                continue
            shortname = fn_id.split("::")[-1]
            defined_mappings[fn_id] = meta
            lookup[shortname].append(fn_id)
            
            # Also index the full ID to support exact match resolution
            if fn_id not in lookup[fn_id]:
                lookup[fn_id].append(fn_id)

            # Index method shortnames (e.g. 'greet' for 'MyClass.greet')
            if "." in shortname:
                method_name = shortname.split(".")[-1]
                if method_name != shortname and fn_id not in lookup[method_name]:
                    lookup[method_name].append(fn_id)

        for shortname, third_meta in third_party.items():
            third_party_mappings[shortname] = {
                "name": shortname,
                "calls": [],
                "called_by": third_meta["called_by"],
                "defined_in": "external",
                "is_third_party": True,
            }
            if shortname not in lookup:
                lookup[shortname] = [shortname]

        metadata_out = {
            "lookup": dict(lookup),
            "defined_mappings": defined_mappings,
            "third_party_mappings": third_party_mappings,
        }

        with open(os.path.join(save_path, "metadata.json"), "w") as f:
            json.dump(metadata_out, f, indent=2)
            
        self.metadata = metadata_out

    def load(self, metadata_path: str):
        with open(metadata_path, "r") as f:
            metadata_all = json.load(f)

        lookup = metadata_all.get("lookup", {})
        defined = metadata_all.get("defined_mappings", {})
        third_party = metadata_all.get("third_party_mappings", {})

        def get_label(fn_id):
            return fn_id.split("::")[-1]

        self.graph = nx.DiGraph()
        for fn_id, meta in defined.items():
            self.graph.add_node(fn_id, label=get_label(fn_id), **meta)

        for fn_id, meta in third_party.items():
            self.graph.add_node(fn_id, label=fn_id, **meta)

        for fn_id, meta in defined.items():
            for callee in meta.get("calls", []):
                if not self.graph.has_node(callee):
                    self.graph.add_node(callee, label=get_label(callee))
                self.graph.add_edge(fn_id, callee)

        self.graph.graph["lookup"] = lookup
        self.metadata = metadata_all

    def resolve_function_name(self, name: str, file_hint: str = None) -> str | None:
        lookup = self.metadata.get("lookup", {})
        matches = lookup.get(name, [])

        if not matches:
            return None

        if file_hint:
            for m in matches:
                if m.startswith(file_hint + "::"):
                    return m
            return None

        if len(matches) == 1:
            return matches[0]

        return None

    def get_function_metadata(self, fn_id: str, file_hint: str = None) -> dict | None:
        resolved_id = fn_id
        if "::" not in fn_id:
            resolved_id = self.resolve_function_name(fn_id, file_hint=file_hint)

        if not resolved_id:
            return None

        if resolved_id in self.graph.nodes:
            return self.graph.nodes[resolved_id]

        meta_lookup = self.metadata.get("defined_mappings", {})
        return meta_lookup.get(resolved_id)

    def get_contextual_neighbors(self, fn_id, depth=2, file_hint=None):
        resolved_id = fn_id
        if "::" not in fn_id:
            resolved_id = self.resolve_function_name(fn_id, file_hint=file_hint)

        if not resolved_id or resolved_id not in self.graph:
            return []

        visited = {resolved_id}
        frontier = {resolved_id}

        for _ in range(depth):
            next_frontier = set()
            for node in frontier:
                next_frontier.update(set(self.graph.successors(node)))
                next_frontier.update(set(self.graph.predecessors(node)))
            next_frontier -= visited
            visited.update(next_frontier)
            frontier = next_frontier

        visited.remove(resolved_id)
        return list(visited)

    def fetch_source_snippet(self, fn_id, file_hint=None):
        meta = self.get_function_metadata(fn_id, file_hint=file_hint)
        if not meta:
            return "[Function not found]"

        # Assuming meta['defined_in'] is relative to repo root
        # But for 'defined_in' we need full content to parse with treesitter to get exact snippet
        filepath = meta.get("defined_in")
        content = self.repo.get_file_content(filepath)
        if not content:
            return f"[Source file missing: {filepath}]"

        func_name = fn_id.split("::")[-1]
        if "::" not in fn_id:
            # Re-resolve to get full name if passed short name
            resolved = self.resolve_function_name(fn_id, file_hint=file_hint)
            if resolved: func_name = resolved.split("::")[-1]

        # We need to re-parse to get source_code for the node
        # Optimization: Store source code or byte offsets in metadata? 
        # For now, replicate repobrowser logic of re-parsing
        extension = get_file_extension(filepath)
        if not extension:
            extension = guess_extension_from_shebang(file_content=content)
        
        lang = get_programming_language(extension)
        if lang.value not in supported_languages():
            return "[Language not supported]"

        treesitter = Treesitter.create_treesitter(lang)
        try:
            treesitter.parse(content.encode("utf8"))
            functions = treesitter.get_definitions("function")
            for func in functions:
                if func.name == func_name:
                    return func.source_code
            return "[Function not located in source]"
        except Exception as e:
            return f"[Error reading source: {str(e)}]"

    def lookaround_source_snippet(self, fn_id, context_lines=5, file_hint=None):
        meta = self.get_function_metadata(fn_id, file_hint=file_hint)
        if not meta:
            return "[Function not found]"

        filepath = meta.get("defined_in")
        content = self.repo.get_file_content(filepath)
        if not content:
             return f"[Source file missing: {filepath}]"
        
        lines = content.splitlines(keepends=True)
        func_name = fn_id.split("::")[-1]
        if "::" not in fn_id:
            resolved = self.resolve_function_name(fn_id, file_hint=file_hint)
            if resolved: func_name = resolved.split("::")[-1]

        # Regex search for context
        for i, line in enumerate(lines):
            if re.search(rf"\b{re.escape(func_name)}\b", line):
                start = max(i - context_lines, 0)
                end = min(i + context_lines + 1, len(lines))
                return "".join(lines[start:end])
        return "[Function not located in source]"


def create_repograph(root, search=None, save_path="./"):
    # Backward compatibility wrapper
    from milo.codesift.repository import get_repository
    repo = get_repository(root)
    graph = RepoGraph(repo)
    graph.build()
    graph.save(save_path)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python repo_callflow_mapper_nx.py <repo_path> <language>")
    else:
        create_repograph(sys.argv[1], sys.argv[2], search=None)
        # main(sys.argv[1], sys.argv[2], search="tdpi_trl_is_hhe")
