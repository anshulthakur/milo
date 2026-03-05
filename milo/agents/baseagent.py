import os
import json
import traceback
from typing import List, Dict, Any

# from ollama import Client
from openai import OpenAI
from milo.agents.tools import Tool

LLM_ENDPOINT = os.environ.get('LLM_ENDPOINT', "http://localhost:11434/v1")
LLM_MODEL = os.environ.get('LLM_MODEL', "comb")


class Agent:
    def __init__(
        self,
        name: str,
        tools: List[Tool],
        options: Dict = {},
        system_prompt="",
        format=None,
        model=LLM_MODEL,
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

        Attributes:
            history (List): Conversation history maintained as message list (initialized empty)
            client (OpenAI): OpenAI API client connected to LLM_ENDPOINT
        """
        self.name = name
        self.system_prompt = system_prompt
        self.tools: Dict[str, Tool] = {t.name: t for t in tools}
        self.history = []
        self.model = model
        self.client = OpenAI(base_url=LLM_ENDPOINT, api_key="ollama") # api_key is required but not used for local Ollama
        self.options = options
        self.format = format

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
            Appends a message dictionary to self.history in the format:
            {"role": "user", "content": <seed_value>}
        """
        self.history.append({"role": "user", "content": seed})

    def clear_history(self):
        """
        Resets the agent's conversation history to an empty list.
        """
        self.history = []

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
            self.history.append({"role": "user", "content": followup})
            print("Followup chat::")

        print(self.history)
        
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(self.history)

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
            chat_kwargs["response_format"] = {"type": self.format}

        # The OpenAI API doesn't have an 'options' parameter like ollama's.
        # These would need to be mapped to top-level arguments like temperature, top_p, etc.
        # A more robust solution would map them.
        supported_options = ["temperature", "top_p", "seed"]
        for option in supported_options:
            if option in self.options:
                chat_kwargs[option] = self.options[option]

        response = self.client.chat.completions.create(**chat_kwargs)
        
        message = response.choices[0].message
        
        # Convert the message to a dict to maintain compatibility
        message_dict = {
            "role": message.role,
            "content": message.content,
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
        
        self.history.append(message_dict)
        print("Reply::")
        print(message_dict)
        return self._handle_response(message_dict)

    def _handle_response(self, message: Dict[str, Any]) -> Any:
        """
        Processes and executes tool calls from an incoming message dictionary.
        """
        tool_calls = message.get("tool_calls")
        if not tool_calls:
            print("No tool calls")
            return message.get("content")

        results = []
        for call in tool_calls:
            try:
                tool_name = call["function"]["name"]
                # Arguments are a JSON string in the OpenAI response
                arguments = json.loads(call["function"].get("arguments", "{}"))
                tool = self.tools[tool_name]

                print(f"Calling tool: {tool_name}")
                
                # Validate and parse arguments via Pydantic
                args_obj = tool.schema(**arguments)
                print(f"args: {args_obj}")
                result = tool.func(**args_obj.model_dump())
                print(f"Called tool")
                print(result)
                results.append({"tool": tool_name, "result": result})

                # Add result back to conversation history
                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "name": tool_name,
                        "content": json.dumps(result),
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
                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "name": call.get("function", {}).get("name", "unknown"),
                        "content": json.dumps(error_msg),
                    }
                )
                print(tb)

        return self.call()
