# A Beginner's Guide to Querying C Code with Tree-sitter

## Introduction

When we write code, we see it as text. But for a computer to understand it, it needs to be parsed into a structured format. One such format is an **Abstract Syntax Tree (AST)**. An AST represents the structure of your code. For example, a function call has a name and a list of arguments. In an AST, you'd have a `function_call` node with children for the function name and its arguments.

**Tree-sitter** is a powerful parser generator that can build an AST for your code and, more importantly, let you query it. Think of it like using CSS selectors to find elements on a web page, but for your code.

This tutorial will guide you through constructing queries for C code using tree-sitter, based on examples from this project.

## Basic Query Syntax: S-expressions

Tree-sitter queries are written using S-expressions, which are expressions enclosed in parentheses `()`. The basic building block of a query is a node pattern.

A node pattern looks like this: `(node_type)`. `node_type` is the type of the AST node you want to find. For C, some common node types are `function_definition`, `if_statement`, `call_expression`, etc.

### Capturing Nodes

To do something useful with the nodes you find, you need to "capture" them. You can capture a node by adding a capture name after it, like this: `@capture_name`.

**Example: Finding Function Definitions**

Let's say we want to find all function definitions in a C file. The node type for a function definition in C is `function_definition`.

Here's the query:
```scheme
(function_definition) @definition
```

This query finds all `function_definition` nodes and captures them with the name `definition`.

Consider this C code:
```c
void my_function() {
    // function body
}
```
The query `(function_definition) @definition` will match the entire `my_function` definition.

## Querying for Specific Nodes: Fields and Nesting

An AST is a tree, so nodes are nested inside other nodes. You can write queries that reflect this structure.

**Example: Finding Struct Names**

Let's look at a more complex query for finding the name of a struct.
```scheme
(struct_specifier
  name: (type_identifier) @name) @definition
```

Let's break it down:
- `(struct_specifier ... ) @definition`: This finds a `struct_specifier` node and captures the whole node as `@definition`.
- `name: (type_identifier) @name`: This is the interesting part. Inside the `struct_specifier` node, we are looking for a child node associated with the `name` field. We are saying that this child must be a `type_identifier` node, and we capture it as `@name`.

For this C code:
```c
struct MyStruct {
    int id;
};
```
The AST for `struct MyStruct` would look something like this (simplified):
```
(struct_specifier
  name: (type_identifier)  // "MyStruct"
  body: (field_declaration_list ...))
```
Our query matches this structure perfectly. The outer `(struct_specifier)` matches the struct definition. The inner `name: (type_identifier) @name` matches the `type_identifier` node containing "MyStruct" because it's the `name` of the `struct_specifier`.

## Matching Multiple Node Types: Lists

Sometimes you want to find nodes of different types with a single query. You can do this by putting multiple node patterns inside square brackets `[]`.

**Example: Finding Top-Level Blocks**

Imagine you want to get all the main "blocks" of a C file, like functions, declarations, and preprocessor directives.

Here's the query:
```scheme
[
  (function_definition)
  (declaration)
  (preproc_def)
  (preproc_function_def)
  (preproc_include)
  (type_definition)
  (struct_specifier)
] @block
```

This query will match any of the listed node types (`function_definition`, `declaration`, etc.) and capture it as `@block`. This is a powerful way to get a high-level overview of a file's structure.

## Advanced Querying: Alternatives within a Node

Just as you can use `[]` to match different types of nodes, you can use it to match different patterns for a child node. This is useful when a function argument, for example, can be passed in different ways.

**Example: Finding Dynamic Entry Points (Callbacks)**

In C, a function can be passed as an argument to another function (a callback). This can be done by just using the function name, or by using the `&` operator.

Consider these two calls:
```c
register_callback(my_callback_handler);
pthread_create(&thread_id, NULL, &thread_function, NULL);
```
In the first case, `my_callback_handler` is an `identifier`. In the second, `&thread_function` is a `pointer_expression` whose child is an `identifier`. We want to capture the function name in both cases.

Here's the query to find such callbacks when passed as arguments:
```scheme
(call_expression
  arguments: (argument_list
    [
      (identifier) @callback_arg
      (pointer_expression argument: (identifier) @callback_arg)
    ]
  )
)
```

Let's dissect this:
- `(call_expression ...)`: We are looking inside a function call.
- `arguments: (argument_list ...)`: We are looking at the arguments of the call.
- `[...]`: This is where the magic happens. It says "match one of the following patterns":
    1. `(identifier) @callback_arg`: This matches arguments that are simple identifiers, like `my_callback_handler`.
    2. `(pointer_expression argument: (identifier) @callback_arg)`: This matches arguments that are pointer expressions, like `&thread_function`. It looks for a `pointer_expression`, then its `argument` field which should be an `identifier`, and captures that identifier.

This query lets us find function names passed as callbacks, regardless of whether the `&` is used.

## Conclusion

Tree-sitter queries are a very powerful tool for static analysis. By understanding the structure of your code's AST and using S-expressions, you can extract almost any information you need.

To explore the AST of a C file yourself, you can use the `tree-sitter` CLI. For example:
`tree-sitter parse path/to/your/file.c`

This will print the full AST, which you can use to figure out the node types and field names you need for your queries. Happy querying!
