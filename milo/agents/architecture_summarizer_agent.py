import os
import re
from typing import Dict, List
from pydantic import BaseModel, Field

from milo.agents.baseagent import Agent, LLM_ENDPOINT
from milo.agents.tools import get_filesystem_tools


class ArchSummaryOutput(BaseModel):
    summary: str = Field(..., description="A high-level summary of the software's architecture or a specific feature flow.")


class ArchitectureSummarizerAgent(Agent):
    def __init__(self, endpoint=LLM_ENDPOINT, repo_path=None):
        schema_str = '{"summary": "A high-level summary of the software\'s architecture or a specific feature flow."}'
        tools = get_filesystem_tools(repo_path) if repo_path else []
        super().__init__(
            name="ArchitectureSummarizer",
            tools=tools,
            model=os.environ.get("GENERIC_MODEL", "miloagent"),
            endpoint=endpoint,
            system_prompt=(
                "You are an expert software architect writing a High-Level Design (HLD) summary.\n"
                "Your task is to describe the overarching business logic and system capabilities originating from a specific entry point.\n"
                "You will be given an entry point and the module summaries it interacts with.\n"
                "CRITICAL INSTRUCTIONS:\n"
                "1. Focus on the core domain logic, data flow, and system purpose.\n"
                "2. DO NOT enumerate file names (e.g., 'main.py') or specific function/module names.\n"
                "3. Abstract away the implementation details. Describe the 'what' and 'why', not the 'where'.\n"
                f"IMPORTANT: Respond STRICTLY with a JSON with schema defined as:\n{schema_str}\n"
                "IMPORTANT: Do not wrap JSON in markdown."
            )
        )

    def summarize_flow(self, entry_point: str, touched_modules: List[str], module_summaries: Dict[str, str]) -> str:
        
        module_context = "This flow interacts with the following modules:\n"
        for module_path in touched_modules:
            summary = module_summaries.get(module_path, "No summary available.")
            module_context += f"- {module_path}: {summary}\n"

        prompt = (
            f"Entry Point: `{entry_point}`\n\n"
            f"Context Modules:\n{module_context}\n"
            "Write a High-Level Design (HLD) summary for this execution flow. "
            "Abstract away the specific file names and focus strictly on the overarching capability and business logic."
        )

        self.clear_history()
        self.context_processor.add_message({"role": "user", "content": prompt})

        messages = self.context_processor.get_messages(include_reasoning=False)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=False,
                response_format={"type": "json_schema", "json_schema": ArchSummaryOutput.model_json_schema()},
                reasoning_effort="none",
            )
            response_content = response.choices[0].message.content
            
            print(response_content)
            
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response_content)
            if match:
                response_content = match.group(1).strip()
                
            parsed = ArchSummaryOutput.model_validate_json(response_content)
            return parsed.summary
        except Exception as e:
            print(f"Failed to summarize architecture flow for {entry_point}: {e}")
            if 'response_content' in locals() and response_content:
                return response_content.strip()
            return ""
