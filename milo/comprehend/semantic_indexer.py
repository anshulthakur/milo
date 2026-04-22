import os
import json
import networkx as nx

from milo.codesift.repograph import RepoGraph
from milo.codesift.repository import get_repository
from milo.codesift.repobrowser import summarize_module_hierarchy
from milo.agents.function_summarizer_agent import FunctionSummarizerAgent
from milo.agents.module_summarizer_agent import ModuleSummarizerAgent
from milo.agents.architecture_summarizer_agent import ArchitectureSummarizerAgent
from milo.comprehend.call_flow import CallFlowAnalyzer


class SemanticIndexer:
    def __init__(self, repo_path: str, repomap_dir: str):
        self.repo_path = repo_path
        self.repomap_dir = repomap_dir
        self.metadata_path = os.path.join(repomap_dir, "metadata.json")
        self.agent = FunctionSummarizerAgent(repo_path=repo_path)
        self.module_agent = ModuleSummarizerAgent(repo_path=repo_path)
        self.arch_agent = ArchitectureSummarizerAgent(repo_path=repo_path)
        
        repo = get_repository(repo_path)
        self.rg = RepoGraph(repo)
        if os.path.exists(self.metadata_path):
            self.rg.load(self.metadata_path)
        else:
            self.rg.build()
            self.rg.save(repomap_dir)

    def run(self):
        self._run_layer1()
        self._run_layer2()
        self._run_layer3()

    def _run_layer1(self):
        G = self.rg.graph
        internal_nodes = [n for n, attr in G.nodes(data=True) if not attr.get('is_third_party')]
        internal_G = G.subgraph(internal_nodes)
        
        condensed = nx.condensation(internal_G)
        scc_order = list(reversed(list(nx.topological_sort(condensed))))
        
        print(f"Layer 1: Found {len(internal_nodes)} functions to summarize.")
        updated_count = 0
        for scc_idx in scc_order:
            members = condensed.nodes[scc_idx]['members']
            for fn_id in members:
                meta = G.nodes[fn_id]
                if meta.get("summary"):
                    continue
                    
                print(f"Summarizing Function: {fn_id}")
                source = self.rg.fetch_source_snippet(fn_id)
                if source.startswith("["):
                    continue
                    
                callees = meta.get("calls", [])
                callee_summaries = {G.nodes[c].get("label", c): G.nodes[c]["summary"] for c in callees if G.nodes.get(c, {}).get("summary")}
                        
                summary = self.agent.summarize(meta.get("label", fn_id), source, callee_summaries)
                print(f"  -> {summary}")
                
                meta["summary"] = summary
                if fn_id in self.rg.metadata.get("defined_mappings", {}):
                    self.rg.metadata["defined_mappings"][fn_id]["summary"] = summary
                updated_count += 1
                
                if updated_count % 10 == 0:
                    with open(self.metadata_path, "w") as f:
                        json.dump(self.rg.metadata, f, indent=2)
                        
        if updated_count > 0:
            print(f"Saving metadata ({updated_count} new function summaries)...")
            with open(self.metadata_path, "w") as f:
                json.dump(self.rg.metadata, f, indent=2)
        else:
            print("Layer 1: All functions already summarized.")
            
    def _run_layer2(self):
        print("Layer 2: Starting Module Summarization...")
        G = self.rg.graph
        module_map = summarize_module_hierarchy(G)
        
        if "file_mappings" not in self.rg.metadata:
            self.rg.metadata["file_mappings"] = {}
            
        updated_count = 0
        for file_path, func_nodes in module_map.items():
            if file_path == "<unknown>" or file_path == "external":
                continue
                
            if file_path in self.rg.metadata["file_mappings"] and self.rg.metadata["file_mappings"][file_path].get("summary"):
                continue
                
            print(f"Summarizing Module: {file_path}")
            
            func_summaries = {}
            for fn_id in func_nodes:
                meta = G.nodes[fn_id]
                label = meta.get("label", fn_id)
                summary = meta.get("summary", "")
                if summary:
                    func_summaries[label] = summary
                    
            if not func_summaries:
                print(f"  -> Skipping (no function summaries available)")
                continue
                
            summary = self.module_agent.summarize(file_path, func_summaries)
            print(f"  -> {summary}")
            
            self.rg.metadata["file_mappings"][file_path] = {"summary": summary}
            updated_count += 1
            
            if updated_count % 5 == 0:
                with open(self.metadata_path, "w") as f:
                    json.dump(self.rg.metadata, f, indent=2)
                    
        if updated_count > 0:
            print(f"Saving final metadata ({updated_count} new module summaries)...")
            with open(self.metadata_path, "w") as f:
                json.dump(self.rg.metadata, f, indent=2)
        else:
            print("Layer 2: All modules already summarized.")

    def _run_layer3(self):
        print("Layer 3: Starting System-Level & Call Flow Summarization...")
        G = self.rg.graph
        
        analyzer = CallFlowAnalyzer(G)
        entry_points = analyzer.find_entry_points()
        
        if not entry_points:
            print("Layer 3: No entry points found. Skipping.")
            return

        if "architecture_summaries" not in self.rg.metadata:
            self.rg.metadata["architecture_summaries"] = {}
        
        updated_count = 0
        for entry_point_id in entry_points:
            
            if entry_point_id in self.rg.metadata["architecture_summaries"]:
                print(f"Skipping already summarized flow: {entry_point_id}")
                continue

            print(f"Summarizing Architecture Flow from: {entry_point_id}")
            
            descendants = nx.descendants(G, entry_point_id)
            descendants.add(entry_point_id)
            
            touched_files = set()
            for node_id in descendants:
                if G.has_node(node_id) and "defined_in" in G.nodes[node_id]:
                    file_path = G.nodes[node_id]["defined_in"]
                    if file_path and file_path != "<unknown>":
                        touched_files.add(file_path)
            
            module_summaries = {
                fp: self.rg.metadata.get("file_mappings", {}).get(fp, {}).get("summary", "No summary available.")
                for fp in touched_files
            }

            if not module_summaries:
                print(f"  -> Skipping (no module summaries available for this flow)")
                continue

            flow_summary = self.arch_agent.summarize_flow(
                entry_point=entry_point_id,
                touched_modules=sorted(list(touched_files)),
                module_summaries=module_summaries
            )
            print(f"  -> {flow_summary}")
            self.rg.metadata["architecture_summaries"][entry_point_id] = {"summary": flow_summary}
            updated_count += 1

        if updated_count > 0:
            print(f"Saving final metadata ({updated_count} new architecture summaries)...")
            with open(self.metadata_path, "w") as f:
                json.dump(self.rg.metadata, f, indent=2)
        else:
            print("Layer 3: All architecture flows already summarized.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: python -m milo.comprehend.semantic_indexer <repo_path> <repomap_dir>")
        sys.exit(1)
    indexer = SemanticIndexer(sys.argv[1], sys.argv[2])
    indexer.run()
