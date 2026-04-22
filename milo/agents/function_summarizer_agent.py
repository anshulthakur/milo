import os
import json
import re
from typing import Dict
from pydantic import BaseModel, Field

from milo.agents.baseagent import Agent, LLM_ENDPOINT
from milo.agents.tools import get_filesystem_tools


class FunctionSummaryOutput(BaseModel):
    summary: str = Field(..., description="A highly concise, 1-sentence summary of the function's purpose.")


class FunctionSummarizerAgent(Agent):
    def __init__(self, endpoint=LLM_ENDPOINT, repo_path=None):
        schema_str = json.dumps(FunctionSummaryOutput.model_json_schema(), indent=2)
        tools = get_filesystem_tools(repo_path) if repo_path else []
        super().__init__(
            name="FunctionSummarizer",
            tools=tools,
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

        messages = self.context_processor.get_messages(include_reasoning=False)

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
