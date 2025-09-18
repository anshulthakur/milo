# Call Flow Analysis Design

## 1. Objective

The goal of this feature is to provide tools to identify and trace call flows within a given repository. This will help developers understand the high-level execution paths, locate primary entry points, and discover independent parts of the codebase.

## 2. Core Data Structure

The analysis will be performed on the `RepoGraph`, which is a `networkx.DiGraph`. In this graph:
- **Nodes**: Represent code objects such as functions, methods, or classes.
- **Edges**: Represent a call or reference from one code object to another.

## 3. Methodology

The process is divided into two main parts: identifying entry points and tracing the flows from them.

### 3.1. Entry Point Identification

A call flow begins at an entry point. We can identify these using two main strategies: static analysis (zero in-degree) and semantic analysis (dynamic/callback-based).

#### 3.1.1. Static Entry Points (Zero In-Degree Nodes)

The most straightforward way to find an entry point is to find nodes in the `RepoGraph` with an in-degree of zero. These are functions or methods that are defined in the repository but are not called by any other analyzed code.

- **Examples**: `main()` functions, public API endpoints, or functions intended to be used externally.
- **Implementation**: Filter for nodes `n` where `graph.in_degree(n) == 0`, ensuring that these nodes are defined within the repository and are not external dependencies.

#### 3.1.2. Dynamic Entry Points (Semantic Analysis)

For more complex scenarios like callbacks, static analysis is not enough. We must enhance the language parsers to identify specific patterns where a function call dynamically creates a new entry point.

- **Examples**: A call to `pthread_create` in C starts a new thread, and the function pointer passed to it is the entry point for that thread. A call to `signal()` registers a callback function to handle an OS signal.

**Methodology for Dynamic Entry Points:**

1.  **Dispatcher Registry**: For each language parser, we will maintain a registry of "dispatcher" functions known to register callbacks (e.g., `{"pthread_create": 2, "signal": 1}` where the value is the 0-indexed argument position of the callback function).

2.  **Parser Enhancement**: The `treesitter` parsers will be upgraded to recognize calls to these dispatchers. When a dispatcher is called, the parser will extract the name of the function from the designated argument.

3.  **Graph Annotation**: The `create_repograph` process will receive this information from the parser. When adding the callback function to the graph, it will annotate its node with a special attribute, e.g., `is_dynamic_entry_point=True`.

4.  **Analyzer Update**: The `CallFlowAnalyzer.find_entry_points` method will be updated to find all nodes that have an in-degree of 0 **OR** have the `is_dynamic_entry_point=True` attribute.

### 3.2. Call Flow Tracing

Once a set of entry points is identified, we can trace the execution paths originating from each one.

- **Graph Traversal**: Starting from each entry point, we will perform a graph traversal (e.g., Depth-First Search) to find all reachable nodes.
- **Path Generation**: The output will be the set of all possible paths from the entry point to any terminal node (a node with no outgoing edges) or nodes involved in a cycle. `networkx.all_simple_paths` can be used for this.
- **Cycle Handling**: The traversal algorithm must be able to detect and report cycles (e.g., recursion) to avoid infinite loops during analysis.

## 4. Implementation

This functionality will be encapsulated in a new class within `milo/codesift/repobrowser.py`.

```python
import networkx as nx
from .repograph import RepoGraph # Assuming this is the class

class CallFlowAnalyzer:
    """
    Analyzes a RepoGraph to find and trace call flows.
    """

    def __init__(self, repo_graph: RepoGraph):
        self.graph = repo_graph.graph

    def find_entry_points(self) -> list:
        """
        Finds all potential entry points in the graph.
        Initially, this will be nodes with an in-degree of 0.
        """
        return [n for n, d in self.graph.in_degree() if d == 0]

    def get_call_flow(self, start_node) -> list[list]:
        """
        Traces all possible call paths starting from a given node.
        """
        # Find all terminal nodes in the graph
        terminal_nodes = [n for n, d in self.graph.out_degree() if d == 0]

        paths = []
        for end_node in terminal_nodes:
            # Find all simple paths from the start_node to the end_node
            # This inherently handles cycles by only visiting nodes once per path.
            try:
                for path in nx.all_simple_paths(self.graph, source=start_node, target=end_node):
                    paths.append(path)
            except nx.NetworkXNoPath:
                continue
        return paths

    def get_all_call_flows(self) -> dict[object, list[list]]:
        """
        Finds all entry points and gets the call flows for each one.
        """
        entry_points = self.find_entry_points()
        all_flows = {}
        for entry in entry_points:
            all_flows[entry] = self.get_call_flow(entry)
        return all_flows

```

## 5. Testing

A new test file, `tests/test_repobrowser.py`, will be created to validate the `CallFlowAnalyzer`. Tests will involve:
- Creating a sample `RepoGraph` with known entry points, branches, and cycles.
- Asserting that `find_entry_points()` correctly identifies the entry points.
- Asserting that `get_call_flow()` and `get_all_call_flows()` return the expected paths.
