from pydantic import BaseModel
from tree_sitter import Node
import os
import json
import re
import shutil
from pathlib import Path
from typing import List, Optional
import traceback

from milo.codesift.parsers import supported_languages, Treesitter
from milo.codesift.repograph import create_repograph
from milo.codesift.parsers.languages import get_programming_language, get_file_extension, guess_extension_from_shebang
from milo.utils.vcs import FileManager

from milo.agents.documentation import get_agent as get_documentation_agent

try:
    from claw_compactor import FusionEngine
except ImportError:
    try:
        from claw_compactor.fusion.engine import FusionEngine
    except ImportError:
        FusionEngine = None

compactor_engine = FusionEngine() if FusionEngine else None

class InputCode(BaseModel):
    language: str
    method: str
    docstring: str = ""
    file_path: Optional[str] = None
    request: str = ("Please revise the docstring for the provided method. "
                    "Return the result in JSON format using the schema provided. "
                    "Use tools to fetch further context from the repository graph to ensure documentation relevance. ")

class InputHeader(BaseModel):
    language: str
    source: str
    request: str = ("Please revise the docstrings for the provided struct/typedef in doxygen compliant format. "
                    "Document each member on a separate line inside the structure and do not do inline documentation. "
                    "Make sure that the outermost comment on the struct does not contain documentation for members. "
                    "Return the result in JSON format using the following schema: "
                    """{
  "name": "<name of struct or typedef>",
  "source": "<doxygen compliant documented code>"
}"""
                    " Use tools to fetch further context to ensure documentation relevance.")

class CommentedStruct(BaseModel):
    name: str
    source: str
class CommentedCode(BaseModel):
    method_name: str
    documentation: str


def insert_docstring_c(file_content: str, tree, node, docstring: str) -> str:
    """
    Inserts a comment block above the C function definition.
    """
    lines = file_content.splitlines()
    start_line = node.node.start_point[0]
    indent = re.match(r"\s*", lines[start_line]).group()
    comment_lines = [f"{indent}{line}" for line in docstring.strip().splitlines()]
    return "\n".join(lines[:start_line] + comment_lines + lines[start_line:])


def remove_existing_docstring_c(file_content: str, tree, node: Node, language) -> tuple[bool, str]:
    """
    Removes the Doxygen-style comment block immediately preceding a C function definition.
    Uses Tree-sitter AST traversal to find and remove the comment node.
    """
    # Get the parent node and find the previous sibling
    parent = node.node.parent
    if not parent:
        return False, file_content

    siblings = [child for child in parent.children if child.end_byte <= node.node.start_byte]
    if not siblings:
        return False, file_content

    # Find the immediate previous sibling
    prev_sibling = siblings[-1] if len(siblings) >= 1 else None
    if not prev_sibling or prev_sibling.type != "comment":
        return False, file_content

    # Check if it's a Doxygen-style comment    
    comment_text = file_content[prev_sibling.start_byte:prev_sibling.end_byte].strip()
    if not (
        comment_text.startswith("/**") or
        comment_text.startswith("/*!") or
        comment_text.startswith("///") or
        comment_text.startswith("//!")
    ):
        return False, file_content

    # Remove the comment block
    updated_content = (
        file_content[:prev_sibling.start_byte] +
        file_content[prev_sibling.end_byte:]
    )
    return True, updated_content

def sanitize_docstring_c(comment):
    return comment


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

    docstring = docstring.strip()
    is_quoted = docstring.startswith(('"""', "'''")) and docstring.endswith(('"""', "'''")) and len(docstring) >= 6

    # Build docstring block with correct indentation
    if is_quoted:
        docstring_lines = docstring.splitlines()
        docstring_block = ""
        for i, line in enumerate(docstring_lines):
             if i == 0:
                 docstring_block += f"{line}\n"
             else:
                 docstring_block += f"{indent}{line}\n"
        docstring_block += indent
    else:
        docstring_lines = docstring.splitlines()
        if len(docstring_lines) == 1:
            docstring_block = f'"""{docstring_lines[0].strip()}"""\n{indent}'
        else:
            docstring_block = f'"""\n'
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
    node = method_node.node
    comment_node = None
    if node.type in ("function_definition", "class_definition"):
        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                if child.type == "comment":
                    continue
                
                if child.type == "expression_statement":
                    for grandchild in child.children:
                        if grandchild.type == "string":
                            comment_node = child
                            break
                elif child.type == "string":
                    comment_node = child
                
                # We only check the first non-comment statement
                break

    if comment_node:
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




DOCSTRING_SANITIZER = {
    "c": sanitize_docstring_c,
    "python": sanitize_docstring_python
}

DOCSTRING_REMOVE_HANDLERS = {
    "c": remove_existing_docstring_c,
    "python": remove_existing_docstring_python
}

DOCSTRING_INSERT_HANDLERS = {
    "c": insert_docstring_c,
    "python": insert_docstring_python
}

def _extract_node_name(node: Node) -> Optional[str]:
    '''TODO: Move this to language specific treesitter parser for general use'''
    # Python: name field
    name_node = node.child_by_field_name("name")
    if name_node:
        return name_node.text.decode("utf-8")
    
    # C: declarator field
    declarator = node.child_by_field_name("declarator")
    while declarator:
        if declarator.type == "identifier":
            return declarator.text.decode("utf-8")
        
        # Handle pointer_declarator, function_declarator, etc.
        next_decl = declarator.child_by_field_name("declarator")
        if next_decl:
            declarator = next_decl
        else:
            break
    return None

def locate_node_by_name(nodes, target_name: str, target_type: str):
    """
    Recursively searches for a node with the given name and type.
    """
    if not nodes:
        return None

    for node in nodes:
        name = node.name or _extract_node_name(node.node)
        if name == target_name and node.node_type == target_type:
            node.name = name
            return node
    return None

def update_docstring(local_path, programming_language, node, comment):
    with open(local_path, "r", encoding="utf-8") as f:
        current_source = f.read()

    live_parser = Treesitter.create_treesitter(programming_language)
    live_parser.parse(current_source.encode())
    live_nodes = live_parser.iterate_blocks()
    live_node = locate_node_by_name(
                                        live_nodes,
                                        target_name=node.name,
                                        target_type=node.node.type
                                    )
    
    if not live_node:
        return

    remover = DOCSTRING_REMOVE_HANDLERS.get(programming_language.value)
    if remover:
        (updated, cleaned_content) = remover(current_source, live_parser, live_node, programming_language)
        if updated:
            current_source = cleaned_content
            live_parser.parse(current_source.encode())
            live_nodes = live_parser.iterate_blocks()
            live_node = locate_node_by_name(
                                                live_nodes,
                                                target_name=node.name,
                                                target_type=node.node.type
                                            )
            if not live_node:
                return
    
    inserter = DOCSTRING_INSERT_HANDLERS.get(programming_language.value)
    sanitizer = DOCSTRING_SANITIZER.get(programming_language.value)
    
    if inserter and sanitizer:
        sanitized_comment = sanitizer(comment.documentation)
        updated_content = inserter(cleaned_content, live_parser, live_node, sanitized_comment)

        with open(local_path, "w", encoding="utf-8") as f:
            f.write(updated_content)

def run_comb(file_manager: Optional[FileManager] = None, repo_root: Optional[str] = None, repo_name: Optional[str] = None, files: List[str] = None):
    if files is None:
        files = []
        
    if not repo_root and file_manager:
        repo_root = file_manager.repo_root

    files_to_document = set()
    for path_str in files:
        path = Path(path_str).resolve()
        if not path.exists():
            continue

        if path.is_file():
            file_extension = get_file_extension(str(path))
            if len(file_extension) == 0:
                file_extension = guess_extension_from_shebang(file_path=str(path))
            programming_language = get_programming_language(file_extension)
            if programming_language.value in supported_languages():
                files_to_document.add(str(path))
        elif path.is_dir():
            for root, _, files in os.walk(path):
                for file in files:
                    file_path = Path(root) / file
                    file_extension = get_file_extension(str(file_path))
                    if len(file_extension) == 0:
                        file_extension = guess_extension_from_shebang(file_path=str(file_path))
                    programming_language = get_programming_language(file_extension)
                    if programming_language.value in supported_languages():
                        files_to_document.add(str(file_path))
    repomap_path = None
    if repo_root:
        # Generate a repograph of the repository
        repomap_path = os.path.join(repo_root, '.milo')

        Path(repomap_path).mkdir(exist_ok=True)
        create_repograph(root = str(repo_root),
                        save_path=repomap_path)
    else:
        #Create a repo_root in /tmp/ to have a repomap, keep it unhidden
        repomap_path = os.path.join('/tmp', 'milo')
        Path(repomap_path).mkdir(exist_ok=True)
    
    metadata_path = os.path.join(repomap_path, "metadata.json") if repomap_path is not None else None
    agent = get_documentation_agent(metadata_path=metadata_path, repo_path=repo_root, repo_name=repo_name)

    for local_path in files_to_document:
        if not repo_root:
            #Individual files passed for documentation. Create repograph for each 
            create_repograph(root = os.path.dirname(local_path),
                            save_path=repomap_path)
        # Guess the programming language
        file_extension = get_file_extension(local_path)
        if len(file_extension) == 0:
            file_extension = guess_extension_from_shebang(file_path=local_path)
        programming_language = get_programming_language(file_extension)
        
        if repo_root:
            rel_file_path = os.path.relpath(local_path, repo_root)
        else:
            rel_file_path = os.path.basename(local_path)

        file_content = None
        try:
            print(f"Processing {local_path}")
            with open(local_path, "r") as file:
                # Read the entire content of the file into a string
                file_content = file.read().encode()

                # Parse the file using treesitter, and extract the elements from the code
                treesitter_parser = Treesitter.create_treesitter(programming_language)
                treesitter_parser.parse(file_content)
                treesitter_nodes = treesitter_parser.iterate_blocks()
                for node in treesitter_nodes:
                    if node.node_type not in treesitter_parser.documentable_node_types:
                        continue
                        
                    method_name = node.name
                    method_comment = None

                    method_source_code = node.source_code
                    if node.doc_comment and node.doc_comment not in node.source_code:
                        method_comment = node.doc_comment
                    try:
                        if compactor_engine:
                            try:
                                comp_result = compactor_engine.compress(
                                    text=method_source_code,
                                    content_type="code",
                                    language=programming_language.value
                                )
                                method_source_code = comp_result.get("compressed", method_source_code)
                            except Exception:
                                pass

                        request = ("Please revise the docstring for the provided method. "
                                   "Return the result in JSON format using the schema provided. "
                                   "Use tools to fetch further context from the repository graph to ensure documentation relevance. "
                                   "However, DO NOT use tools to fetch the source code of the function currently being documented, as it is already provided below.")
                        
                        user_prompt = f"{request}\n\nFile: `{rel_file_path}`\n\n"
                        if method_comment:
                            user_prompt += f"### Existing Docstring\n```text\n{method_comment}\n```\n\n"
                        user_prompt += f"### Full Source\n```{programming_language.value}\n{method_source_code}\n```"
            
                        agent.clear_history()
                        agent.set_format(CommentedCode.model_json_schema())
                        response = agent.call(user_prompt)
                        
                        comment = CommentedCode.model_validate_json(response)
                        
                        if len(comment.documentation.strip()) > 0:
                            update_docstring(local_path, programming_language, node, comment)
                    except:
                        print("Error processing node. Skip")
                        traceback.print_exc()
        except FileNotFoundError:
            print(f"{local_path} No longer exists.")
