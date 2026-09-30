"""Workflows shared by the CLI and the local UI.

Orchestration of `core/` and `adapters/`: what the CLI commands used to do
inline. No print, no typer, no sys.exit, no get_config(); every function takes
a `Workspace`. Refusals are typed exceptions carrying facts, and the caller
words them. See specs/001-local-ui/contracts/services.md.
"""
