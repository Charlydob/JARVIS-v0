import os


# Legacy integration suites exercise deterministic executors without requiring
# a running Ollama process. SemanticPlanner has its own schema/validator suites
# and the local-model evaluation script covers the live boundary.
os.environ.setdefault("JARVIS_SEMANTIC_PLANNER_ENABLED", "false")
