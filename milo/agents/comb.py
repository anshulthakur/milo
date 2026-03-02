import os
import json
import re
import shutil
from pathlib import Path
from typing import List, Optional

from milo.agents.baseagent import Agent
from milo.codesift.parsers.treesitter.treesitter import Treesitter, ParsedNode
from milo.codesift.parsers.utils import get_programming_language, get_file_extension, guess_extension_from_shebang

from pydantic import BaseModel
from tree_sitter import Node

class InputCode(BaseModel):
    language: str
    method: str
    docstring: str = ""
    request: str = ("Please revise the docstring for the provided method. "
                    "Return the result in JSON format using the schema provided. "
                    "Use tools to fetch further context from the repository graph to ensure documentation relevance. ")

class CommentedCode(BaseModel):
    method_name: str
    documentation: str

def insert_docstring_python(file_content: str, tree, method_node, docstring: str) -> str:
    body_node = method_node.node.child_by_field_name("body")
    if not body_node:
        raise ValueError("Function body not found")

    insert_byte = body_node.start_byte
    file_bytes = file_content.encode("utf-8")

    # Find indentation from first meaningful statement
    indent = "    "  # fallback
    for child in body_node.children:
        if child.type == "expression_statement":
            text = file_bytes[child.start_byte:child.end_byte].decode("utf-8").strip()
            if text.startswith(("'''", '"""')):
                continue
        if child.type not in {"comment", "ERROR"}:
            line_start = file_bytes[:child.start_byte].rfind(b"\n") + 1
            indent_bytes = file_bytes[line_start:child.start_byte]
            indent = indent_bytes.decode("utf-8")
            break

    # Build docstring block with correct indentation
    docstring_lines = docstring.strip().splitlines()
    if len(docstring_lines) == 1:
        docstring_block = f'"""{docstring_lines[0].strip()}"""\n{indent}'
    else:
        docstring_block = '"""\n'
        for line in docstring_lines:
            docstring_block += f'{indent}{line}\n'
        docstring_block += f'{indent}"""\n{indent}'

    # Insert docstring
    updated_bytes = (
        file_bytes[:insert_byte] +
        docstring_block.encode("utf-8") +
        file_bytes[insert_byte:]
    )
    return updated_bytes.decode("utf-8")

def remove_existing_docstring_python(file_content: str, tree, method_node, language) -> str:
    """
    Removes the docstring from a specific Python method using Tree-sitter.
    """
    comment_nodes = tree._query_doc_comment_node(method_node.node)

    if comment_nodes:
        comment_node = comment_nodes[0]
        #print(comment_node.text.decode())
        # This is the docstring node
        start_byte, end_byte = comment_node.start_byte, comment_node.end_byte

        file_bytes = file_content.encode("utf-8")
        # Find line boundaries
        # Revise pre to beginning of line (remove indent)
        line_start = file_bytes[:start_byte].rfind(b"\n") + 1
        pre = file_bytes[:line_start]
        post = file_bytes[end_byte:]

        # Remove trailing newline if present
        if post.startswith(b"\n"):
            post = post[1:]

        cleaned_bytes = pre + post
        return (True, cleaned_bytes.decode("utf-8"))

    return (False, file_content)


def sanitize_docstring_python(doc):
    """
    Ensures the input string is a properly formatted Python docstring.
    
    Rules:
    - If the string starts with triple quotes, return as-is.
    - If it contains triple quotes elsewhere, extract the quoted part.
    - If it contains no triple quotes, wrap the entire string in triple quotes.
    """
    doc = doc.strip()

    # Case 1: Already starts with triple quotes
    if doc.startswith('"""') or doc.startswith("'''"):
        return doc

    # Case 2: Contains triple quotes somewhere
    for quote in ('"""', "'''"):
        if quote in doc:
            start = doc.find(quote)
            end = doc.find(quote, start + 3)
            if end != -1:
                return doc[start:end + 3]

    # Case 3: No triple quotes found — wrap the whole string
    return f'"""\n{doc}\n"""'

comb_agent = None

def get_agent():
    global comb_agent
    if not comb_agent:
        comb_agent = Agent(
            name="COMB",
            tools=[],
            system_prompt="You are a comment bot. Your purpose is to add comments to code."
        )
    return comb_agent

DOCSTRING_SANITIZER = {
    "python": sanitize_docstring_python
}

DOCSTRING_REMOVE_HANDLERS = {
    "python": remove_existing_docstring_python
}

DOCSTRING_INSERT_HANDLERS = {
    "python": insert_docstring_python
}

def locate_node_by_name(nodes, target_name: str, target_type: str) -> Node | None:
    """
    Recursively searches for a node with the given name and type.
    """
    for node in nodes:
        if node.name == target_name:
            return node
    return None

def update_docstring(local_path, programming_language, node, comment):
    with open(local_path, "r", encoding="utf-8") as f:
        current_source = f.read()

    live_parser = Treesitter.create_treesitter(programming_language)
    live_tree = live_parser.parse(current_source.encode())
    live_node = locate_node_by_name(
                                        live_tree,
                                        target_name=node.name,
                                        target_type=node.node.type
                                    )
    
    remover = DOCSTRING_REMOVE_HANDLERS.get(programming_language.value)
    if remover:
        (updated, cleaned_content) = remover(current_source, live_parser, live_node, programming_language)
        if updated:
            current_source = cleaned_content
            live_tree = live_parser.parse(current_source.encode())
            live_node = locate_node_by_name(
                                                live_tree,
                                                target_name=node.name,
                                                target_type=node.node.type
                                            )
    
    inserter = DOCSTRING_INSERT_HANDLERS.get(programming_language.value)
    sanitizer = DOCSTRING_SANITIZER.get(programming_language.value)
    
    if inserter and sanitizer:
        sanitized_comment = sanitizer(comment.documentation)
        updated_content = inserter(cleaned_content, live_tree, live_node, sanitized_comment)

        with open(local_path, "w", encoding="utf-8") as f:
            f.write(updated_content)

def run_comb(agent: Agent, files: List[str]):
    for file_path in files:
        file_extension = get_file_extension(file_path)
        if len(file_extension) == 0:
            file_extension = guess_extension_from_shebang(file_path=file_path)
        
        programming_language = get_programming_language(file_extension)

        if programming_language.value == "unknown":
            print(f"Skip unsupported format: {file_path}")
            continue

        with open(file_path, "r") as file:
            file_content = file.read().encode()

        treesitter_parser = Treesitter.create_treesitter(programming_language)
        treesitter_nodes: list[ParsedNode] = treesitter_parser.parse(file_content)

        for node in treesitter_nodes:
            method_name = node.name
            method_comment = None

            method_source_code = node.method_source_code
            if node.doc_comment and node.doc_comment not in node.method_source_code:
                method_comment = node.doc_comment
            
            user_prompt = InputCode(language = programming_language.value, 
                                    method=method_source_code, 
                                    docstring = method_comment or "")
            
            agent.clear_history()
            response = agent.call(user_prompt.model_dump_json())
            
            comment = CommentedCode.model_validate_json(response)
            
            if len(comment.documentation.strip()) > 0:
                update_docstring(file_path, programming_language, node, comment)
