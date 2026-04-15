import os
import re
from typing import Dict
from pydantic import BaseModel, Field

from milo.agents.baseagent import Agent, LLM_ENDPOINT


class ModuleSummaryOutput(BaseModel):
    summary: str = Field(..., description="A short paragraph summarizing the module's overarching purpose.")


class ModuleSummarizerAgent(Agent):
    def __init__(self, endpoint=LLM_ENDPOINT):
        schema_str = '{"summary": "A short paragraph summarizing the module\'s overarching purpose."}'
        super().__init__(
            name="ModuleSummarizer",
            tools=[],
            model=os.environ.get("GENERIC_MODEL", "miloagent"),
            endpoint=endpoint,
            system_prompt=(
                "You are a strictly factual code documentation assistant.\n"
                "Your task is to write a short paragraph summarizing what a specific file/module does, "
                "based on the list of functions it contains and their individual summaries.\n"
                "Keep it highly concise. DO NOT include code review, bugs, or suggestions.\n"
                f"IMPORTANT: Respond STRICTLY with a JSON with schema defined as:\n{schema_str}\n"
                "IMPORTANT: Do not wrap JSON in markdown."
            )
        )

    def summarize(self, file_path: str, function_summaries: Dict[str, str]) -> str:
        func_context = ""
        for func, summary in function_summaries.items():
            func_context += f"- {func}: {summary}\n"

        prompt = (
            f"File: {file_path}\n\n"
            f"Functions defined in this file:\n{func_context}\n"
            "Write a short paragraph summary of the file's overarching purpose."
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
                response_format={"type": "json_schema", "json_schema": ModuleSummaryOutput.model_json_schema()},
                reasoning_effort="none",
            )
            response_content = response.choices[0].message.content
            
            print(response_content)
            
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response_content)
            if match:
                response_content = match.group(1).strip()
                
            parsed = ModuleSummaryOutput.model_validate_json(response_content)
            return parsed.summary
        except Exception as e:
            print(f"Failed to summarize module {file_path}: {e}")
            if 'response_content' in locals() and response_content:
                return response_content.strip()
            return ""
