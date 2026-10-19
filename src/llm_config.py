"""
LLM access for all agents.

Agents never construct a client themselves; they call invoke_llm(), which
decides how the prompt is answered:

  live     ChatOpenAI against OpenRouter, with a request timeout and a
           bounded number of retries (config.LLM_TIMEOUT_SECONDS /
           LLM_MAX_RETRIES). Retries are safe here because an LLM call has
           no side effects.
  offline  No network call. The agent's deterministic rule baseline is
           returned in the same text format the LLM is asked to use, so it
           goes through the same parser and validation. Every record is
           labelled with the mode it ran in.
  override Tests install a fake (set_llm_override) to return canned,
           malformed or failing responses without any network access.

invoke_llm() never raises for an LLM failure. It returns an LLMResponse
with `error` set, and the agent falls back to its rule baseline and flags
the output so the decision gate sends it to a human.
"""

import os
from dataclasses import dataclass
from typing import Callable

import config


class LLMConfigError(RuntimeError):
    """Raised when live mode is requested but the LLM cannot be configured."""


@dataclass
class LLMResponse:
    text: str | None          # raw text to parse (None if the call failed)
    source: str               # "llm" | "offline" | "override"
    error: str | None = None  # short, secret-free error description


_override: Callable[[str, str, str], str] | None = None
_llm_client = None


def set_llm_override(fn: Callable[[str, str, str], str] | None):
    """
    Test hook. fn(agent_name, prompt, offline_response) -> response text, or
    raise to simulate
    an outage. Returning offline_response leaves that agent on its rule
    answer. Pass None to remove the override.
    """
    global _override
    _override = fn


def resolve_mode() -> str:
    """The mode this process will run in: 'live' or 'offline'."""
    mode = config.LLM_MODE
    if mode not in ("auto", "live", "offline"):
        raise LLMConfigError(f"LLM_MODE must be auto, live or offline (got {mode!r})")
    if mode == "auto":
        return "live" if os.getenv("OPENROUTER_API_KEY") else "offline"
    return mode


def check_configuration():
    """Fail fast with an actionable message instead of a stack trace mid-run."""
    if resolve_mode() == "live" and not os.getenv("OPENROUTER_API_KEY"):
        raise LLMConfigError(
            "LLM_MODE=live but OPENROUTER_API_KEY is not set. Add it to .env "
            "(see .env.example) or set LLM_MODE=offline to run with the rule-based agents."
        )


def get_llm():
    """
    Get LLM configured for OpenRouter, with a timeout and bounded retries.
    The client is created once and reused.
    """
    global _llm_client
    check_configuration()
    if _llm_client is None:
        from langchain_openai import ChatOpenAI  # imported lazily: offline mode never needs it
        _llm_client = ChatOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
            model=os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
            temperature=0.0,
            timeout=config.LLM_TIMEOUT_SECONDS,
            max_retries=config.LLM_MAX_RETRIES,
        )
    return _llm_client


def invoke_llm(agent: str, prompt: str, offline_response: str, run_config: dict | None = None) -> LLMResponse:
    """
    Answer `prompt` for `agent`. `offline_response` is the rule-based answer
    used in offline mode. `run_config` carries LangSmith run name/tags/metadata.
    """
    if _override is not None:
        try:
            return LLMResponse(text=_override(agent, prompt, offline_response), source="override")
        except Exception as exc:  # simulated outage
            return LLMResponse(text=None, source="override", error=f"{type(exc).__name__}: {exc}"[:300])

    if resolve_mode() == "offline":
        return LLMResponse(text=offline_response, source="offline")

    try:
        response = get_llm().invoke(prompt, config=run_config or {})
        return LLMResponse(text=response.content, source="llm")
    except LLMConfigError:
        raise
    except Exception as exc:
        # Keep only the exception type and a short message: provider errors
        # can echo request details, and this text ends up in the audit log.
        return LLMResponse(text=None, source="llm", error=f"{type(exc).__name__}: {str(exc)[:200]}")


def verify_tracing():
    """Verify LangSmith tracing is configured correctly."""
    tracing_enabled = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
    api_key = os.getenv("LANGCHAIN_API_KEY")
    project = os.getenv("LANGCHAIN_PROJECT", "default")

    if tracing_enabled and api_key:
        print("LangSmith tracing enabled")
        print(f"  Project: {project}")
        print(f"  Endpoint: {os.getenv('LANGCHAIN_ENDPOINT', 'https://api.smith.langchain.com')}")
        return True
    else:
        print("LangSmith tracing disabled")
        return False
