"""
Wiring the nodes into a LangGraph state machine.

    python -m governance.graph.build --dataset synthetic

What the graph buys over the sequential runner:

    * quality and compliance genuinely run as one parallel superstep
    * every step is a named node with inspectable state either side of it
    * a conditional edge can skip work rather than the pipeline branching
      inside a function
    * a checkpointer makes any run replayable

What it does NOT buy is different results. The graph calls the same node
functions the sequential runner calls, so the two produce identical output by
construction - see tests/test_graph.py, which asserts it.
"""
from __future__ import annotations

import argparse

from langgraph.graph import END, START, StateGraph

from governance.graph import nodes
from governance.state import GovernanceContext


def _needs_narrative(state: GovernanceContext) -> str:
    """Conditional edge: skip the whole narrative step when it is switched off."""
    return "narrative" if state.get("llm_enabled") else "end"


def build_graph():
    graph = StateGraph(GovernanceContext)

    graph.add_node("metadata", nodes.metadata_node)
    graph.add_node("quality", nodes.quality_node)
    graph.add_node("compliance", nodes.compliance_node)
    graph.add_node("join", nodes.join_node)
    graph.add_node("risk", nodes.risk_node)
    graph.add_node("cite", nodes.cite_node)
    graph.add_node("gate", nodes.review_gate)
    graph.add_node("recommend", nodes.recommend_node)
    graph.add_node("narrative", nodes.narrative_node)

    graph.add_edge(START, "metadata")

    # Fan out. Both branches append to `issues`, which is why that key carries
    # an operator.add reducer - without it LangGraph refuses to guess how to
    # merge two concurrent writes and raises InvalidUpdateError at runtime.
    graph.add_edge("metadata", "quality")
    graph.add_edge("metadata", "compliance")

    # Fan in. `join` runs only once both branches have completed.
    graph.add_edge("quality", "join")
    graph.add_edge("compliance", "join")

    graph.add_edge("join", "risk")
    graph.add_edge("risk", "cite")
    graph.add_edge("cite", "gate")
    graph.add_edge("gate", "recommend")

    graph.add_conditional_edges("recommend", _needs_narrative,
                                {"narrative": "narrative", "end": END})
    graph.add_edge("narrative", END)

    return graph.compile()


def run_graph(df, name: str, llm_enabled: bool = False,
              backend: str = "auto") -> GovernanceContext:
    from governance.state import new_context

    state = new_context(name, df, llm_enabled=llm_enabled, llm_backend=backend)
    return build_graph().invoke(state)


def main() -> None:
    from governance import report, run

    ap = argparse.ArgumentParser(description="Run the pipeline through LangGraph.")
    ap.add_argument("--dataset", default="synthetic")
    ap.add_argument("--path")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--backend", default="auto",
                    choices=["auto", "groq", "grok", "off", "echo"])
    ap.add_argument("--diagram", action="store_true",
                    help="print the graph structure and exit")
    args = ap.parse_args()

    if args.diagram:
        # Mermaid rather than ASCII: draw_ascii() needs grandalf installed,
        # and mermaid text pastes straight into documentation.
        print(build_graph().get_graph().draw_mermaid())
        return

    df, name, _ = run.load(args.dataset, args.path)
    ctx = run_graph(df, name, llm_enabled=args.llm, backend=args.backend)
    run.summarise(ctx)
    report_path, audit_path = report.write(ctx)
    print(f"\n  wrote {report_path}")
    print(f"  wrote {audit_path}\n")


if __name__ == "__main__":
    main()