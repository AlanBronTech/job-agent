"""What a paid action would be missing, found before anyone is asked to confirm it.

Free: it reads configuration, never calls a model. The confirm page lists
these instead of a Confirm button, so a click cannot start a run that is bound
to fail on setup. The workflows still refuse on their own; this is only there
so the page can say so first.
"""

from __future__ import annotations

import os

from jobagent.adapters.llm import CallType, LLMError, Provider, resolve_route
from jobagent.services.workspace import Workspace

_CALL_TYPE = {
    "add_ad": CallType.parse_jd,
    "score": CallType.score,
    "generate": CallType.generate,
    "prep": CallType.prep,
}

# Actions that read the profile. Parsing an ad does not.
_NEEDS_PROFILE = {"score", "generate", "prep"}


def missing(ws: Workspace, config, action: str) -> list[str]:
    problems: list[str] = []
    if action in _NEEDS_PROFILE and ws.profile_dir is None:
        problems.append("No profile directory: set PROFILE_DIR in .env.")
    try:
        route = resolve_route(config, _CALL_TYPE[action])
    except LLMError as exc:
        problems.append(str(exc))
        return problems
    if route.provider is Provider.anthropic:
        if not (config.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")):
            problems.append("No Anthropic API key: set ANTHROPIC_API_KEY in .env.")
    elif route.provider is Provider.gemini:
        if not (
            config.gemini_api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        ):
            problems.append("No Gemini API key: set GEMINI_API_KEY in .env.")
    return problems
