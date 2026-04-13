import os
import json
import re
import networkx as nx
from typing import Dict
from pydantic import BaseModel, Field

from milo.codesift.repograph import RepoGraph
from milo.codesift.repository import get_repository
from milo.agents.baseagent import Agent, LLM_ENDPOINT


class FunctionSummaryOutput(BaseModel):
    summary: str = Field(..., description="A highly concise, 1-sentence summary of the function's purpose.")


class FunctionSummarizerAgent(Agent):
    def __init__(self, endpoint=LLM_ENDPOINT):
        schema_str = json.dumps(FunctionSummaryOutput.model_json_schema(), indent=2)
        super().__init__(
            name="FunctionSummarizer",
            tools=[],
            model=os.environ.get("GENERIC_MODEL", "miloagent"), # Using a more capable model than ToolSummary
            endpoint=endpoint,
            system_prompt=(
                "You are a strictly factual code documentation assistant.\n"
                "Your task is to write a single-sentence summary of what a specific function does, "
                "based on its source code and the summaries of the functions it calls.\n"
                "Keep it highly concise. DO NOT include code review, bugs, or suggestions.\n"
                f"IMPORTANT: Respond STRICTLY with a JSON with schema defined as:\n{schema_str}\n"
                "IMPORTANT: Do not wrap JSON in markdown."
            )
        )

    def summarize(self, func_name: str, source_code: str, callee_summaries: Dict[str, str]) -> str:
        callee_context = ""
        if callee_summaries:
            callee_context = "Summaries of functions called by this function:\n"
            for callee, summary in callee_summaries.items():
                callee_context += f"- {callee}: {summary}\n"

        prompt = (
            f"Function: {func_name}\n\n"
            f"Source Code:\n```\n{source_code}\n```\n\n"
            f"{callee_context}\n"
            "Write a 1-sentence summary of the function."
        )

        self.clear_history()
        self.context_processor.add_message({"role": "user", "content": prompt})

        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(self.context_processor.get_messages(include_reasoning=False))

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=False,
                response_format={"type": "json_schema", "json_schema": FunctionSummaryOutput.model_json_schema()},
                reasoning_effort="none",
            )
            response_content = response.choices[0].message.content

            print(response_content)
            
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response_content)
            if match:
                response_content = match.group(1).strip()
                
            parsed = FunctionSummaryOutput.model_validate_json(response_content)
            return parsed.summary
        except Exception as e:
            print(f"Failed to summarize {func_name}: {e}")
            if 'response_content' in locals() and response_content:
                return response_content.strip()
            return ""


class SemanticIndexer:
    def __init__(self, repo_path: str, repomap_dir: str):
        self.repo_path = repo_path
        self.repomap_dir = repomap_dir
        self.metadata_path = os.path.join(repomap_dir, "metadata.json")
        self.agent = FunctionSummarizerAgent()
        
        repo = get_repository(repo_path)
        self.rg = RepoGraph(repo)
        if os.path.exists(self.metadata_path):
            self.rg.load(self.metadata_path)
        else:
            self.rg.build()
            self.rg.save(repomap_dir)

    def run(self):
        G = self.rg.graph
        internal_nodes = [n for n, attr in G.nodes(data=True) if not attr.get('is_third_party')]
        internal_G = G.subgraph(internal_nodes)
        
        condensed = nx.condensation(internal_G)
        scc_order = list(reversed(list(nx.topological_sort(condensed))))
        
        print(f"Found {len(scc_order)} components to summarize.")
        updated_count = 0
        for scc_idx in scc_order:
            members = condensed.nodes[scc_idx]['members']
            for fn_id in members:
                meta = G.nodes[fn_id]
                if meta.get("summary"):
                    continue
                    
                print(f"Summarizing: {fn_id}")
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
            print(f"Saving final metadata ({updated_count} new summaries)...")
            with open(self.metadata_path, "w") as f:
                json.dump(self.rg.metadata, f, indent=2)
        else:
            print("All functions already summarized.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: python semantic_indexer.py <repo_path> <repomap_dir>")
        sys.exit(1)
    indexer = SemanticIndexer(sys.argv[1], sys.argv[2])
    indexer.run()
