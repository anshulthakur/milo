import os
import json
import traceback
from typing import List, Dict, Any, Optional
import re

try:
    import tiktoken
except ImportError:
    tiktoken = None

# from ollama import Client
from pydantic import BaseModel, Field
from openai import OpenAI
from milo.agents.tools import Tool, RewindArgs


LLM_ENDPOINT = os.environ.get('LLM_ENDPOINT', "http://srsw.cdot.in:11434/v1")
LLM_MODEL = os.environ.get('LLM_MODEL', "comb")
MAX_TOOL_RESULT_LEN = int(os.environ.get('LLM_MAX_TOOL_RESULT_LEN_MODEL', "4000"))
USE_TOOL_SUMMARIZER = os.environ.get('USE_TOOL_SUMMARIZER', "0") in ('TRUE', 'true', 'True', '1')

try:
    from claw_compactor import FusionEngine
except ImportError:
    try:
        from claw_compactor.fusion.engine import FusionEngine
    except ImportError:
        FusionEngine = None

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
    def __init__(self):
        super().__init__()
        if FusionEngine:
            self.engine = FusionEngine(enable_rewind=True)
        else:
            self.engine = None
        
        self.tokenizer = None
        if tiktoken:
            try:
                # Using cl100k_base as a general-purpose tokenizer for modern models.
                self.tokenizer = tiktoken.get_encoding("cl100k_base")
            except Exception as e:
                print(f"Warning: Failed to load tiktoken tokenizer: {e}")
        else:
            print("Warning: tiktoken is not installed. Context size management will be disabled.")

    def _num_tokens(self, text: str) -> int:
        if not self.tokenizer or not text:
            return 0
        return len(self.tokenizer.encode(text))

    def compress_if_needed(self, context_size_limit: int):
        if not self.engine or not self.tokenizer:
            return

        print("compress_if_needed")
        # Estimate token usage by summing tokens of content for each message
        current_tokens = sum(self._num_tokens(str(msg.get("content", ""))) for msg in self._history)
        
        # Trigger compression at 80% capacity
        if current_tokens > context_size_limit * 0.8:
            print(f"Context size ({current_tokens}) exceeds 80% of limit ({context_size_limit}). Compressing history.")
            try:
                result = self.engine.compress_messages(self._history)

                # The claw-compactor README is ambiguous. Handle both a dict with a 'messages' key or a direct list.
                new_history = None
                if isinstance(result, dict) and 'messages' in result:
                    new_history = result['messages']
                elif isinstance(result, list):
                    new_history = result

                if new_history is not None:
                    self._history = new_history
                    new_tokens = sum(self._num_tokens(str(msg.get("content", ""))) for msg in self._history)
                    print(f"History compressed. Token count reduced from {current_tokens} to {new_tokens}.")
                else:
                    print(f"Warning: compress_messages returned an unexpected structure ({type(result)}). History not compressed.")

            except Exception as e:
                print(f"Full history compression failed: {e}")

    def add_message(self, message: Dict[str, Any]):
        role = message.get("role")
        
        if role == "tool":
            content = message.get("content", "")
            
            # Use claw-compactor if available and content is large
            if self.engine and len(content) > MAX_TOOL_RESULT_LEN:
                print(f"CompactContextProcessor: Compressing tool output ({len(content)} chars) with FusionEngine...")
                try:
                    result = self.engine.compress(content, content_type="text")
                    content = result.get("compressed", content)
                except Exception as e:
                    print(f"FusionEngine compression failed: {e}")
                    content = content[:MAX_TOOL_RESULT_LEN] + "\n\n...[TRUNCATED: Tool output too large]..."
            # Fallback to simple truncation
            elif len(content) > MAX_TOOL_RESULT_LEN:
                content = content[:MAX_TOOL_RESULT_LEN] + "\n\n...[TRUNCATED: Tool output too large. Please refine your query or use more specific tool arguments]..."
            
            tool_msg = message.copy()
            tool_msg["content"] = content
                
            super().add_message(tool_msg)
        else:
            super().add_message(message)

class Agent:
    def __init__(
        self,
        name: str,
        tools: List[Tool],
        options: Dict = {},
        system_prompt=None,
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

        if self.system_prompt:
            self.context_processor.add_message({"role": "system", "content": self.system_prompt})

        # Expose rewind tool to the LLM if context processor supports it
        if hasattr(self.context_processor, "engine") and self.context_processor.engine:
            self.tools["rewind_content"] = Tool(
                name="rewind_content",
                description="Retrieve the original uncompressed content using a rewind marker provided by the compactor.",
                schema=RewindArgs,
                func=lambda marker: self.context_processor.engine.rewind_store.retrieve(marker) or "Marker not found."
            )

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
        if self.system_prompt:
            self.context_processor.add_message({"role": "system", "content": self.system_prompt})

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

        if hasattr(self.context_processor, 'compress_if_needed'):
            self.context_processor.compress_if_needed(self.context_size)

        print(self.history)
        
        messages = self.context_processor.get_messages(include_reasoning=False)

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
        content = message.get("content", "")

        # Handle case where model hallucinates a tool call in the content field
        if not tool_calls and content and content.strip().startswith("[Tool Call]"):
            print("Hallucinated tool call detected in content. Attempting to parse.")
            parsed_calls = []
            for line in content.strip().split('\n'):
                # Pattern: [Tool Call] Name: <name> | Args: <json>
                match = re.match(r"\[Tool Call\] Name: ([\w_]+) \| Args: (.*)", line.strip())
                if match:
                    tool_name = match.group(1)
                    args_str = match.group(2)
                    try:
                        call_id = f"hallucinated-call-{os.urandom(4).hex()}"
                        parsed_calls.append({
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": args_str
                            }
                        })
                    except Exception as e:
                        print(f"Failed to create structure for hallucinated tool call: {e}")
                        continue
            if parsed_calls:
                tool_calls = parsed_calls

        if not tool_calls:
            print("No tool calls")
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

                results.append({"tool": tool_name, "result": result_str})

                # Add result back to conversation history
                self.context_processor.add_message(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "name": tool_name,
                        "content": result_str,
                        "tool_args": json.dumps(arguments),
                        "reflective_thinking": reflective_thinking,
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
    reflective_thinking: Optional[str] = Field(None, description="The reasoning or 'thinking' process of the parent agent that led to this tool call.")

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
                "You will receive a JSON payload containing the 'tool_name', 'tool_args', 'raw_output', and optionally the parent agent's 'reflective_thinking'.\n"
                "Your task is to read the 'raw_output' and extract the exact, verbatim data segments that are relevant to the 'reflective_thinking'. If no thinking is provided, extract the most salient parts of the output.\n"
                "CRITICAL RULES:\n"
                "1. You are NOT a code reviewer. DO NOT evaluate bugs, correctness, or propose solutions.\n"
                "2. DO NOT summarize or draw conclusions. Copy the relevant parts of the 'raw_output' verbatim.\n"
                f"Respond STRICTLY with a JSON object matching this schema:\n{schema_str}"
            )
        )

    def summarize(self, tool_name: str, tool_args: str, raw_output: str, reflective_thinking: Optional[str] = None) -> str:
        input_data = ToolSummaryInput(
            tool_name=tool_name,
            tool_args=tool_args,
            raw_output=raw_output,
            reflective_thinking=reflective_thinking
        )

        prompt = input_data.model_dump_json(indent=2)

        self.clear_history()
        self.context_processor.add_message({"role": "user", "content": prompt})
        
        messages = self.context_processor.get_messages(include_reasoning=False)
        
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
