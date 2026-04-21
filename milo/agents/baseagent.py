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

    def prune_old_tool_calls(self, current_tool_calls: List[Dict[str, Any]]):
        """Removes older duplicate tool calls and their results from history."""
        ids_to_remove = set()
        for current_tc in current_tool_calls:
            c_func = current_tc.get("function", {})
            c_name = c_func.get("name")
            c_args_str = c_func.get("arguments", "{}")
            c_id = current_tc.get("id")
            
            try:
                c_args = json.loads(c_args_str)
            except Exception:
                c_args = c_args_str
            
            for msg in self._history:
                if msg.get("role") == "assistant" and msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        if tc.get("id") == c_id:
                            continue
                        t_func = tc.get("function", {})
                        if t_func.get("name") == c_name:
                            t_args_str = t_func.get("arguments", "{}")
                            try:
                                t_args = json.loads(t_args_str)
                                is_match = (t_args == c_args)
                            except Exception:
                                is_match = (t_args_str == c_args_str)
                            
                            if is_match:
                                ids_to_remove.add(tc.get("id"))
        
        if not ids_to_remove:
            return

        print(f"Pruning {len(ids_to_remove)} duplicate tool calls from history to save context.")
        new_history = []
        for msg in self._history:
            if msg.get("role") == "tool" and msg.get("tool_call_id") in ids_to_remove:
                continue
            
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                filtered_tcs = [tc for tc in msg["tool_calls"] if tc.get("id") not in ids_to_remove]
                
                if not filtered_tcs and not msg.get("content") and not msg.get("reasoning"):
                    continue
                    
                msg_copy = msg.copy()
                msg_copy["tool_calls"] = filtered_tcs if filtered_tcs else None
                new_history.append(msg_copy)
            else:
                new_history.append(msg)
                
        self._history = new_history

    def get_messages(self, include_reasoning: bool = False) -> List[Dict[str, Any]]:
        if include_reasoning:
            return self._history
            
        messages = []
        for i, msg in enumerate(self._history):
            msg_copy = msg.copy()
            
            # Skip ephemeral messages if they are no longer part of the active recovery turn
            is_ephemeral = msg_copy.pop("ephemeral", False)
            if is_ephemeral:
                is_followed_by_non_ephemeral = any(not m.get("ephemeral") for m in self._history[i+1:])
                if is_followed_by_non_ephemeral:
                    continue

            msg_copy.pop("reasoning", None)
            msg_copy.pop("reflective_thinking", None)
            msg_copy.pop("tool_args", None)
            
            if msg_copy.get("role") == "assistant" and msg_copy.get("tool_calls"):
                # Do not feed back reasoning content on subsequent calls (when a newer assistant message exists)
                if any(m.get("role") == "assistant" for m in self._history[i+1:]):
                    msg_copy["content"] = ""
                    
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
            tool_name = message.get("name", "")
            
            # Use claw-compactor if available and content is large
            if self.engine and tool_name != "delegate_research_task":
                print(f"CompactContextProcessor: Compressing tool output ({len(content)} chars) with FusionEngine...")
                try:
                    result = self.engine.compress(content, content_type="code")
                    content = result.get("compressed", content)
                    #print(f"Compression results: {result.get('stats')}")
                except Exception as e:
                    print(f"FusionEngine compression failed: {e}")
                    content = content[:MAX_TOOL_RESULT_LEN] + "\n\n...[TRUNCATED: Tool output too large]..."
            elif tool_name == "delegate_research_task":
                print("Skip compression  for delegator")
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
        max_steps: int = 15,
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
        
        if self.tools:
            prompt_addition = "IMPORTANT: You must provide a terse reasoning for using tools in the tool call's 'reasoning' argument. If you have already reached a conclusion, DO NOT invoke any tools. Just output your final answer."
            if self.system_prompt:
                self.system_prompt = f"{self.system_prompt}\n{prompt_addition}"
            else:
                pass
                #self.system_prompt = prompt_addition
                
        self.model = model
        self.client = OpenAI(base_url=self.endpoint, api_key="ollama") # api_key is required but not used for local Ollama
        self.options = options
        self.format = format
        self.context_processor = context_processor or CompactContextProcessor()
        self.context_size = context_size
        self.max_steps = max_steps
        self.total_tokens_consumed = 0
        self.current_context_size = 0
        self._last_tool_calls = None
        self._tool_loop_count = 0

        if self.system_prompt:
            self.context_processor.add_message({"role": "system", "content": self.system_prompt})

        # Expose rewind tool to the LLM if context processor supports it
        if hasattr(self.context_processor, "engine") and self.context_processor.engine:
            self.tools["rewind_content"] = Tool(
                name="rewind_content",
                description="Retrieve the original uncompressed content using a rewind marker provided by the compactor.",
                schema=RewindArgs,
                func=lambda marker, **kwargs: self.context_processor.engine.rewind_store.retrieve(marker) or "Marker not found."
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
        self._last_tool_calls = None
        self._tool_loop_count = 0
        if self.system_prompt:
            self.context_processor.add_message({"role": "system", "content": self.system_prompt})

    def set_format(self, format):
        self.format = format

    def call(self, followup: str = None, current_step: int = 0) -> Any:
        """
        Executes a chat sequence with optional follow-up instruction. Handles message history tracking,
        tool registration, and client interaction.
    
        Args:
            followup (str, optional): User-provided follow-up instruction to append to message history. 
            current_step (int): Execution step counter to prevent infinite looping.
        """
        if current_step >= self.max_steps:
            print(f"[{self.name}] Max steps ({self.max_steps}) reached. Aborting to prevent infinite loop.")
            return "ERROR: Agent exceeded maximum allowed steps. Task aborted."

        if followup is not None:
            self.context_processor.add_message({"role": "user", "content": followup})
            print("Followup chat::")

        if hasattr(self.context_processor, 'compress_if_needed'):
            self.context_processor.compress_if_needed(self.context_size)

        #print(self.history)
        
        messages = self.context_processor.get_messages(include_reasoning=False)

        # Context Limit Redaction Check
        def estimate_tokens(msgs):
            if hasattr(self.context_processor, '_num_tokens'):
                return sum(self.context_processor._num_tokens(str(m.get("content", "")) + str(m.get("tool_calls", ""))) for m in msgs)
            return sum(len(str(m)) // 4 for m in msgs)

        current_tokens = estimate_tokens(messages)
        if current_tokens > self.context_size * 0.75:
            print(f"[{self.name}] Context size ({current_tokens}) critically close to limit ({self.context_size}). Applying redaction.")
            first_user_idx = -1
            last_user_idx = -1
            for i, m in enumerate(messages):
                if m.get('role') == 'user':
                    if first_user_idx == -1:
                        first_user_idx = i
                    last_user_idx = i
            
            if first_user_idx != -1 and last_user_idx > first_user_idx:
                redacted_messages = messages[:first_user_idx + 1]
                redacted_messages.append({
                    "role": "user",
                    "content": "[SYSTEM NOTIFICATION: Intermediate tool calls and results have been redacted to preserve context boundary.]"
                })
                redacted_messages.extend(messages[last_user_idx:])
                messages = redacted_messages
            elif first_user_idx != -1 and len(messages) - first_user_idx > 5:
                # Find a safe starting point for the tail (an assistant message to prevent dangling tool results)
                tail_start_idx = len(messages) - 4
                while tail_start_idx > first_user_idx and messages[tail_start_idx].get('role') == 'tool':
                    tail_start_idx -= 1
                
                redacted_messages = messages[:first_user_idx + 1]
                redacted_messages.append({
                    "role": "user",
                    "content": "[SYSTEM NOTIFICATION: Intermediate tool calls and results have been redacted to preserve context boundary.]"
                })
                redacted_messages.extend(messages[tail_start_idx:])
                messages = redacted_messages

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

        print(messages)
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
        return self._handle_response(message_dict, current_step=current_step)

    def _handle_response(self, message: Dict[str, Any], current_step: int = 0) -> Any:
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
                if self.format:
                    # Models sometimes wrap JSON in markdown, so we strip it.
                    match = re.search(r"```(json)?\s*([\s\S]*?)\s*```", content)
                    if match:
                        content = match.group(2).strip()
                    else:
                        content = content.strip()
                else:
                    content = content.strip()
                    
            if self.format and content:
                try:
                    json.loads(content)
                except json.JSONDecodeError:
                    print(f"[{self.name}] Output is not valid JSON. Cycling back for formatting.")
                    fix_messages = []
                    if self.system_prompt:
                        fix_messages.append({"role": "system", "content": self.system_prompt})
                    else:
                        fix_messages.append({"role": "system", "content": "You are a helpful assistant. Your only task is to format the provided text into the required JSON schema."})
                        
                    fix_messages.append({
                        "role": "user", 
                        "content": f"Please extract the relevant information from the following text and format it strictly according to the required JSON schema. Do not add any extra commentary:\n\n{content}"
                    })
                    
                    try:
                        chat_kwargs = {
                            "model": self.model,
                            "messages": fix_messages,
                            "stream": False,
                            "response_format": {"type": "json_schema", "json_schema": self.format}
                        }
                        
                        supported_options = ["temperature", "top_p", "seed"]
                        for option in supported_options:
                            if option in self.options:
                                chat_kwargs[option] = self.options[option]
                                
                        fix_response = self.client.chat.completions.create(**chat_kwargs)
                        fixed_content = fix_response.choices[0].message.content or ""
                        
                        match = re.search(r"```(json)?\s*([\s\S]*?)\s*```", fixed_content)
                        if match:
                            fixed_content = match.group(2).strip()
                        else:
                            fixed_content = fixed_content.strip()
                            
                        return fixed_content
                    except Exception as e:
                        print(f"[{self.name}] Failed to fix formatting: {e}")
            
            print(f"Returning:: {content}")
            return content
                
        current_signature = [(tc.get("function", {}).get("name"), tc.get("function", {}).get("arguments")) for tc in tool_calls]
        if getattr(self, '_last_tool_calls', None) == current_signature:
            self._tool_loop_count = getattr(self, '_tool_loop_count', 0) + 1
        else:
            self._last_tool_calls = current_signature
            self._tool_loop_count = 0

        if hasattr(self.context_processor, "prune_old_tool_calls"):
            self.context_processor.prune_old_tool_calls(tool_calls)

        reflective_thinking = message.get("reasoning") or message.get("content", "").strip()

        results = []
        for call in tool_calls:
            try:
                tool_name = call["function"]["name"]
                # Arguments are a JSON string in the OpenAI response
                arguments_str = call["function"].get("arguments", "{}")
                arguments = json.loads(arguments_str)
                
                if isinstance(arguments, dict) and "reasoning" not in arguments:
                    arguments["reasoning"] = ""

                if self._tool_loop_count >= 2:
                    print(f"[{self.name}] Tool loop detected for {tool_name}. Sending loop break message.")
                    error_msg = "ERROR: Repeated identical tool call detected. You are in an infinite loop. Stop calling this tool with these arguments. Provide a final answer based on your current assessment."
                    results.append({"tool": tool_name, "result": error_msg})
                    
                    # Remove the looping tool call from the assistant message in history
                    if hasattr(self.context_processor, "_history") and self.context_processor._history:
                        last_msg = self.context_processor._history[-1]
                        if last_msg.get("role") == "assistant" and last_msg.get("tool_calls"):
                            last_msg["tool_calls"] = [tc for tc in last_msg["tool_calls"] if tc["id"] != call["id"]]
                            if not last_msg["tool_calls"]:
                                last_msg["tool_calls"] = None
                                
                    self.context_processor.add_message(
                        {
                            "role": "user",
                            "content": error_msg,
                            "ephemeral": True
                        }
                    )
                    continue

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

        return self.call(current_step=current_step + 1)


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
