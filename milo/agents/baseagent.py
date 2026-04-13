import os
import json
import traceback
from typing import List, Dict, Any, Optional
import re

# from ollama import Client
from pydantic import BaseModel, Field
from openai import OpenAI
from milo.agents.tools import Tool


LLM_ENDPOINT = os.environ.get('LLM_ENDPOINT', "http://srsw.cdot.in:11434/v1")
LLM_MODEL = os.environ.get('LLM_MODEL', "comb")
MAX_TOOL_RESULT_LEN = int(os.environ.get('LLM_MAX_TOOL_RESULT_LEN_MODEL', "4000"))
USE_TOOL_SUMMARIZER = os.environ.get('USE_TOOL_SUMMARIZER', "0") in ('TRUE', 'true', 'True', '1')

class ContextProcessor:
    """Base interface for managing context/history passed to the LLM."""
    def add_message(self, message: Dict[str, Any]):
        raise NotImplementedError

    def get_messages(self, include_reasoning: bool = False) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def clear(self):
        raise NotImplementedError

class DefaultContextProcessor(ContextProcessor):
    """Default context processor that simply appends all messages."""
    def __init__(self):
        self._history = []

    def add_message(self, message: Dict[str, Any]):
        self._history.append(message)

    def get_messages(self, include_reasoning: bool = False) -> List[Dict[str, Any]]:
        if include_reasoning:
            return self._history
            
        messages = []
        for msg in self._history:
            msg_copy = msg.copy()
            msg_copy.pop("reasoning", None)
            messages.append(msg_copy)
        return messages

    def clear(self):
        self._history = []

class CompactContextProcessor(DefaultContextProcessor):
    """
    Optimizes token usage by converting verbose OpenAI tool call schemas 
    and tool responses into compact, plain-text conversation turns.
    """
    def add_message(self, message: Dict[str, Any]):
        role = message.get("role")
        
        if role == "assistant" and message.get("tool_calls"):
            # Compress the tool calls request into a simple assistant text action
            calls = []
            for tc in message["tool_calls"]:
                name = tc.get("function", {}).get("name", "unknown")
                args = tc.get("function", {}).get("arguments", "{}")
                calls.append(f"[Tool Call] Name: {name} | Args: {args}")
            
            content = message.get("content") or ""
            compressed_content = (content + "\n" + "\n".join(calls)).strip()
            
            super().add_message({
                "role": "assistant",
                "content": compressed_content
            })
            
        elif role == "tool":
            # Compress the tool execution result into a simple user message
            name = message.get("name", "unknown")
            content = message.get("content", "")
            
            # Strict Truncation Safety Net (~4000 chars is roughly 1000 tokens)
            if len(content) > MAX_TOOL_RESULT_LEN:
                content = content[:MAX_TOOL_RESULT_LEN] + "\n\n...[TRUNCATED: Tool output too large. Please refine your query or use more specific tool arguments]..."
            super().add_message({
                "role": "user",
                "content": f"[Tool Result] Name: {name}\n{content}"
            })
            
        else:
            super().add_message(message)

class Agent:
    def __init__(
        self,
        name: str,
        tools: List[Tool],
        options: Dict = {},
        system_prompt="",
        format=None,
        model=LLM_MODEL,
        endpoint = LLM_ENDPOINT,
        context_processor: ContextProcessor = None,
        context_size: int = 16000,
    ):
        """
        Initialize an Agent instance connected to an OpenAI-compatible LLM service.

        This agent is configured with specified tools, system prompt, and connects to the
        LLM server at LLM_ENDPOINT (default: http://localhost:11434/v1) using the
        model specified by LLM_MODEL (default: "qwen3:8b"). The agent maintains a history
        of interactions and can execute tool calls defined in its tools dictionary.

        Args:
            name (str): Identifier for this agent instance
            tools (List[Tool]): List of available tools, stored as {tool.name: tool} in self.tools
            options (Dict): Configuration options for the agent (default: empty dict)
            system_prompt (str): System message to prepend to all interactions (default: empty)
            format (Any): Expected response format specification (e.g., "json_object"). (default: None)
            model (str): Model name to use (default: LLM_MODEL from settings)
            context_processor (ContextProcessor): Manager for the conversation context handling.

        Attributes:
            history (List): Conversation history maintained as message list (initialized empty)
            client (OpenAI): OpenAI API client connected to LLM_ENDPOINT
        """
        self.name = name
        self.endpoint = endpoint
        self.system_prompt = system_prompt
        self.tools: Dict[str, Tool] = {t.name: t for t in tools}
        self.model = model
        self.client = OpenAI(base_url=self.endpoint, api_key="ollama") # api_key is required but not used for local Ollama
        self.options = options
        self.format = format
        self.context_processor = context_processor or CompactContextProcessor()
        self.context_size = context_size
        self.total_tokens_consumed = 0
        self.current_context_size = 0

    @property
    def history(self) -> List[Dict[str, Any]]:
        return self.context_processor.get_messages(include_reasoning=True)

    def seed_context(self, seed: str):
        """
        Inject an initial code snippet, diff, or reasoning seed into the agent's conversation history.
        This establishes foundational context for subsequent code review interactions.

        Args:
            seed (str): Initial input to prime the agent's analysis. Typically contains:
                        - Code snippets needing review
                        - Specific diff sections
                        - High-level reasoning instructions

        Side Effects:
            Appends a message dictionary to the conversation history in the format:
            {"role": "user", "content": <seed_value>}
        """
        self.context_processor.add_message({"role": "user", "content": seed})

    def clear_history(self):
        """
        Resets the agent's conversation history to an empty list.
        """
        self.context_processor.clear()
        self.current_context_size = 0

    def set_format(self, format):
        self.format = format

    def call(self, followup: str = None) -> Any:
        """
        Executes a chat sequence with optional follow-up instruction. Handles message history tracking,
        tool registration, and client interaction.
    
        Args:
            followup (str, optional): User-provided follow-up instruction to append to message history. 
                                        Defaults to None, which uses existing conversation history.
    
        Returns:
            Any: Processed response message from chat client, typically containing AI-generated content.
        """
        if followup is not None:
            self.context_processor.add_message({"role": "user", "content": followup})
            print("Followup chat::")

        print(self.history)
        
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(self.context_processor.get_messages(include_reasoning=False))

        tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.schema.model_json_schema(),
                },
            }
            for t in self.tools.values()
        ]
        
        chat_kwargs = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "stream": False,
        }

        if self.format:
            chat_kwargs["response_format"] = {"type": "json_schema", "json_schema": self.format}

        # The OpenAI API doesn't have an 'options' parameter like ollama's.
        # These would need to be mapped to top-level arguments like temperature, top_p, etc.
        # A more robust solution would map them.
        supported_options = ["temperature", "top_p", "seed"]
        for option in supported_options:
            if option in self.options:
                chat_kwargs[option] = self.options[option]

        response = self.client.chat.completions.create(**chat_kwargs)
        
        # Track token usage if provided by the API
        if getattr(response, "usage", None):
            self.total_tokens_consumed += response.usage.total_tokens
            self.current_context_size = response.usage.total_tokens
            print(f"[{self.name}] Context Size: {self.current_context_size}/{self.context_size} | Total Tokens Consumed: {self.total_tokens_consumed}")
        
        message = response.choices[0].message

        #print(message)
        
        content = message.content or ""
        reasoning = getattr(message, "reasoning", None)
        
        # Fallback for models that output thinking inside <think> tags in the main content
        if not reasoning:
            think_match = re.search(r"<think>([\s\S]*?)</think>", content)
            if think_match:
                reasoning = think_match.group(1).strip()
                # Strip the thinking block from the main content to save tokens in history
                content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
                
        if reasoning:
            #print(f"\n[{self.name} Thinking]:\n{reasoning}\n{'-'*40}")
            pass

        # Convert the message to a dict to maintain compatibility
        message_dict = {
            "role": message.role,
            "content": content,
            "reasoning": reasoning,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]
            if message.tool_calls
            else None,
        }
        
        self.context_processor.add_message(message_dict)
        print("Reply::")
        print(message_dict)
        return self._handle_response(message_dict)

    def _handle_response(self, message: Dict[str, Any]) -> Any:
        """
        Processes and executes tool calls from an incoming message dictionary.
        If no tool calls, it cleans and returns the content.
        """
        tool_calls = message.get("tool_calls")
        if not tool_calls:
            print("No tool calls")
            content = message.get("content", "")
            if content:
                # Models sometimes wrap JSON in markdown, so we strip it.
                match = re.search(r"```(json)?\s*([\s\S]*?)\s*```", content)
                if match:
                    return match.group(2).strip()
            return content.strip()
                
        reflective_thinking = message.get("reasoning") or message.get("content", "").strip()

        results = []
        for call in tool_calls:
            try:
                tool_name = call["function"]["name"]
                # Arguments are a JSON string in the OpenAI response
                arguments = json.loads(call["function"].get("arguments", "{}"))
                tool = self.tools[tool_name]
                
                # Validate and parse arguments via Pydantic
                args_obj = tool.schema(**arguments)
                print(f"[{self.name}] Calling tool: {tool_name}. args: {args_obj}")

                result = tool.func(**args_obj.model_dump())
                result_str = json.dumps(result) if not isinstance(result, str) else result
                
                print(result)
                if USE_TOOL_SUMMARIZER:
                    # Context Condensation Step
                    print(f"[{self.name}] Condensing tool output ({len(result_str)} chars)...")
                    
                    # Hard limit input to summarizer to prevent crashing the sub-agent
                    if len(result_str) > 50000:
                        result_str = result_str[:50000] + "\n...[TRUNCATED FOR SUMMARIZER]"
                        
                    summarizer = ToolSummaryAgent(endpoint=LLM_ENDPOINT)
                    condensed = summarizer.summarize(
                        tool_name=tool_name,
                        tool_args=json.dumps(arguments),
                        raw_output=result_str
                    )
                    result = condensed
                    print(f"[{self.name}] Condensation complete. Reduced to {len(condensed)} chars.")
                
                results.append({"tool": tool_name, "result": result})

                # Add result back to conversation history
                self.context_processor.add_message(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "name": tool_name,
                            "content": json.dumps(result) if not isinstance(result, str) else result,
                    }
                )

            except Exception as e:
                tb = traceback.format_exc()
                error_msg = {
                    "tool": call.get("function", {}).get("name", "unknown"),
                    "error": str(e),
                    "traceback": tb,
                }
                results.append(error_msg)
                self.context_processor.add_message(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "name": call.get("function", {}).get("name", "unknown"),
                        "content": json.dumps(error_msg),
                    }
                )
                print(tb)

        return self.call()


class ToolSummaryInput(BaseModel):
    tool_name: str = Field(..., description="The tool that was called")
    tool_args: str = Field(..., description="The arguments passed to the tool")
    raw_output: str = Field(..., description="The raw, unsummarized output of the tool")

class ToolSummaryOutput(BaseModel):
    extracted_data: str = Field(..., description="The exact, verbatim data segments from the raw_output that are relevant to the thinking. Do not summarize or add commentary.")


class ToolSummaryAgent(Agent):
    def __init__(self, endpoint=LLM_ENDPOINT):
        schema_str = '{"extracted_data": "The exact, verbatim data segments from the raw_output that are relevant to the thinking. Do not summarize or add commentary."}'
        super().__init__(
            name="ToolSummarizer",
            tools=[],
            model="ToolSummary",
            endpoint=endpoint,
            system_prompt=(
                "You are a strictly factual data extraction assistant.\n"
                "You will receive a JSON payload containing the 'tool_name', 'tool_args', and the 'raw_output'.\n"
                "Your task is to read the 'raw_output' and extract the exact, verbatim data segments that are relevant to the 'tool_name' and 'tool_args'.\n"
                "CRITICAL RULES:\n"
                "1. You are NOT a code reviewer. DO NOT evaluate bugs, correctness, or propose solutions.\n"
                "2. DO NOT summarize or draw conclusions. Copy the relevant parts of the 'raw_output' verbatim.\n"
                f"Respond STRICTLY with a JSON object matching this schema:\n{schema_str}"
            )
        )

    def summarize(self, tool_name: str, tool_args: str, raw_output: str) -> str:
        input_data = ToolSummaryInput(
            tool_name=tool_name,
            tool_args=tool_args,
            raw_output=raw_output
        )

        prompt = input_data.model_dump_json(indent=2)

        self.clear_history()
        self.context_processor.add_message({"role": "user", "content": prompt})
        
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(self.context_processor.get_messages(include_reasoning=False))
        
        print(f'Summarizer input to {self.model}:')
        print(messages)

        try:
            # Making direct completion call to avoid the printing overhead of self.call()
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=False,
                response_format={"type": "json_schema", "json_schema": ToolSummaryOutput.model_json_schema()},
                reasoning_effort="none",
            )
            
            response_content = response.choices[0].message.content
            print('Summarizer output:')
            print(response.choices[0].message)
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response_content)
            if match:
                response_content = match.group(1).strip()
            print("Stripped::")
            print(response.choices[0].message)
            parsed_output = ToolSummaryOutput.model_validate_json(response_content)
            return parsed_output.extracted_data
        except Exception as e:
            print(f"Summarizer API failed: {e}")
            return raw_output[:4000] + "\n...[TRUNCATED BY FALLBACK]"
