import tree_sitter
from typing import List, Dict
from milo.codesift.parsers import Language
from milo.codesift.parsers.treesitter.treesitter import Treesitter
from milo.codesift.parsers.treesitter.treesitter_registry import TreesitterRegistry


class TreesitterHaskell(Treesitter):
    def __init__(self):
        """
        Initializes a new instance of the class with Haskell language settings.

        This method initializes a new instance of the class by setting up the language-specific
        parameters for Haskell. It calls the superclass constructor with the appropriate values
        for the language, function identifier, variable identifier, and comment identifier.

        Args:
            None

        Returns:
            None
        """
        super().__init__(Language.HASKELL, "function", "variable", "comment")

    def parse(self, file_bytes: bytes) -> list[TreesitterMethodNode]:
        """
        Parses the given file bytes and returns a list of TreesitterMethodNode objects.

        This method processes the provided file bytes using a parser to generate an abstract
        syntax tree (AST). It then extracts all method nodes from the AST, determines their
        names, associated documentation comments, and source code. Each processed method is
        encapsulated into a TreesitterMethodNode object which is added to a result list.

        Args:
            file_bytes (bytes): The content of the file as bytes that needs to be parsed.

        Returns:
            list[TreesitterMethodNode]: A list containing TreesitterMethodNode objects,
            each representing a method found in the input file.
        """
        self.tree = self.parser.parse(file_bytes)
        result = []
        methods = self._query_all_methods(self.tree.root_node)
        for method in methods:
            method_name = self._query_method_name(method["method"])
            doc_comment = method["doc_comment"]
            source_code = None
            if method["method"].type == "signature":
                sc = map(
                    lambda x: "\n" + x.text.decode() if x.type == "function" else "",
                    method["method"].children,
                )
                source_code = method["method"].text.decode() + "".join(sc)
            result.append(
                TreesitterMethodNode(
                    method_name, doc_comment, source_code, method["method"]
                )
            )
        return result

    # def _query_all_methods(
    #     self,
    #     node: tree_sitter.Node,
    # ):
    #     methods: List[Dict[tree_sitter.Node, tree_sitter.Node]] = []
    #     if node.type == self.method_declaration_identifier:
    #         doc_comment_nodes = []
    #         if (
    #             node.prev_named_sibling
    #             and node.prev_named_sibling.type == self.doc_comment_identifier
    #         ):
    #             current_doc_comment_node = node.prev_named_sibling
    #             while (
    #                 current_doc_comment_node
    #                 and current_doc_comment_node.type == self.doc_comment_identifier
    #             ):
    #                 # TODO - Why some doc comments are not being populated?
    #                 doc_comment_nodes.append (current_doc_comment_node.text.decode())
    #                 if current_doc_comment_node.prev_named_sibling:
    #                     current_doc_comment_node = (
    #                         current_doc_comment_node.prev_named_sibling
    #                     )
    #                 else:
    #                     current_doc_comment_node = None
    #         else:
    #             if node.prev_named_sibling and node.prev_named_sibling.type == "signature":
    #                 prev_node = node.prev_named_sibling
    #                 if (
    #                     prev_node.prev_named_sibling
    #                     and prev_node.prev_named_sibling.type == self.doc_comment_identifier
    #                 ):
    #                     current_doc_comment_node = prev_node.prev_named_sibling
    #                     while (
    #                         current_doc_comment_node
    #                         and current_doc_comment_node.type == self.doc_comment_identifier
    #                     ):
    #                         # print(current_doc_comment_node.text.decode())
    #                         doc_comment_nodes.append(current_doc_comment_node.text.decode())
    #                         if current_doc_comment_node.prev_named_sibling:
    #                             current_doc_comment_node = (
    #                                 current_doc_comment_node.prev_named_sibling
    #                             )
    #                         else:
    #                             current_doc_comment_node = None
    #                 prev_node.children.append(node)
    #                 node = prev_node
    #         doc_comment_str = ""
    #         # print(len(doc_comment_nodes))
    #         doc_comment_nodes.reverse()
    #         for doc_comment_node in doc_comment_nodes:
    #             doc_comment_str += doc_comment_node + "\n"
    #         # print(doc_comment_str)
    #         if doc_comment_str.strip() != "":
    #             methods.append({"method": node, "doc_comment": doc_comment_str.strip()})
    #         else:
    #             methods.append({"method": node, "doc_comment": None})
    #         # methods.append({"method": node, "doc_comment": doc_comment_node})
    #     else:
    #         for child in node.children:
    #             current = self._query_all_methods(child)
    #             if methods and current:
    #                 previous = methods[-1]
    #                 if self._query_method_name(previous["method"]) == self._query_method_name(current[0]["method"]):
    #                     previous["method"].children.extend(map(lambda x: x["method"], current))
    #                     methods = methods[:-1]
    #                     methods.append(previous)
    #                 else:
    #                     methods.extend(current)
    #             else:
    #                 methods.extend(current)
    #     return methods

    def _query_all_methods(self, node: tree_sitter.Node):
        """
        Recursively queries all method declarations in the AST and collects associated doc comments

        This method traverses the abstract syntax tree (AST) to find all method declarations.
        For each method declaration, it looks for preceding doc comments and includes them in the result.
        If a method is preceded by a signature node, special handling is applied to maintain proper structure.
        When multiple methods are found with the same name, they are merged into a single entry with combined children.

        Returns a list of dictionaries containing method nodes and their associated doc comments.
        """
        methods = []
        if node.type == self.method_declaration_identifier:
            doc_comment_node = None
            if (
                node.prev_named_sibling
                and node.prev_named_sibling.type == self.doc_comment_identifier
            ):
                doc_comment_node = node.prev_named_sibling.text.decode()
            else:
                if (
                    node.prev_named_sibling
                    and node.prev_named_sibling.type == "signature"
                ):
                    prev_node = node.prev_named_sibling
                    if (
                        prev_node.prev_named_sibling
                        and prev_node.prev_named_sibling.type
                        == self.doc_comment_identifier
                    ):
                        doc_comment_node = prev_node.prev_named_sibling.text.decode()
                    prev_node.children.append(node)
                    node = prev_node
            methods.append({"method": node, "doc_comment": doc_comment_node})
        else:
            for child in node.children:
                current = self._query_all_methods(child)
                if methods and current:
                    previous = methods[-1]
                    if self._query_method_name(
                        previous["method"]
                    ) == self._query_method_name(current[0]["method"]):
                        previous["method"].children.extend(
                            map(lambda x: x["method"], current)
                        )
                        methods = methods[:-1]
                        methods.append(previous)
                    else:
                        methods.extend(current)
                else:
                    methods.extend(current)
        return methods

    def _query_method_name(self, node: tree_sitter.Node):
        """
        Returns the name of a method from a given node.

        This method checks if the provided node represents a method signature or declaration.
        If it does, it iterates through the node's children to find the child that represents the method name.
        Once found, it returns the decoded text of that child node.

        Args:
            node (tree_sitter.Node): The node to query for the method name.

        Returns:
            str: The decoded text of the method name node if found, otherwise None.
        """
        if node.type == "signature" or node.type == self.method_declaration_identifier:
            for child in node.children:
                if child.type == self.method_name_identifier:
                    return child.text.decode()
        return None


# Register the TreesitterHaskell class in the registry
TreesitterRegistry.register_treesitter(Language.HASKELL, TreesitterHaskell)
