"""
model_backends.py — provider-agnostic model adapters + a real test runner for the driver.

driver.run_task takes an injected `model(system, user, phase) -> str` and a
`run_tests() -> str`. The loop is backend-free; this module supplies the real edges so
they're chosen at the entry point, not baked into the pipeline.

Providers (all lazy-import their SDK, so every dependency is optional):
  minimax     — Xiaomi/Mimo gateway via OpenAI-compatible chat completions. DEFAULT.
                key: MINIMAX_API_KEY
  claude-cli  — headless Claude Code CLI (`claude -p`, prompt via stdin). Reuses the
                existing Claude Code auth; no API key, no extra dependency.
  anthropic   — Anthropic Python SDK.                       key: ANTHROPIC_API_KEY
  openai      — OpenAI SDK chat-completions. With `base_url` this also speaks to ANY
                OpenAI-COMPATIBLE endpoint — OpenRouter (→ Claude/Gemini/Llama/…), Groq,
                Together, Fireworks, vLLM, Ollama/LM Studio (local). key: OPENAI_API_KEY
                (or pass api_key_env=...).
  gemini      — Google Generative AI SDK.                    key: GEMINI_API_KEY

Pick one with `make_model(provider, model=..., base_url=...)`, or call an adapter
directly. `command_test_runner(cmd)` runs the project's REAL tests for VERIFY (the SHA
gate hashes genuine stdout, never a model's invented output).
"""
from __future__ import annotations

import inspect
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Union

# A model call for one agent phase: (system, user, phase) -> raw text artifact.
ModelFn = Callable[[str, str, str], str]


def _require_key(env: str) -> str:
    val = os.environ.get(env)
    if not val:
        raise RuntimeError(f"{env} is not set.")
    return val


# ── claude-cli ───────────────────────────────────────────────────────────────

def claude_cli_model(*, binary: str = "claude", timeout: int = 600,
                     extra_args: Optional[list[str]] = None) -> ModelFn:
    """Headless Claude Code CLI: `system`+`user` sent on stdin to `claude -p`, stdout
    returned. Prompt via stdin (not argv) to avoid length limits. No API key needed."""
    if shutil.which(binary) is None:
        raise RuntimeError(
            f"'{binary}' CLI not found on PATH. Install Claude Code, or use another "
            f"provider (anthropic / openai / gemini)."
        )

    def _model(system: str, user: str, phase: str) -> str:
        prompt = f"{system}\n\n---\n\n{user}"
        cmd = [binary, "-p", *(extra_args or [])]
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude CLI failed (phase={phase}, code={proc.returncode}): "
                f"{proc.stderr.strip()[:300]}"
            )
        return proc.stdout.strip()

    return _model


# ── anthropic ────────────────────────────────────────────────────────────────

def anthropic_model(*, model: str = "claude-opus-4-8", max_tokens: int = 8000,
                    temperature: float = 0.2, api_key_env: str = "ANTHROPIC_API_KEY") -> ModelFn:
    """Anthropic Python SDK. Needs `pip install anthropic` and the API key."""
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError("`pip install anthropic` to use the anthropic provider.") from e
    client = anthropic.Anthropic(api_key=_require_key(api_key_env))

    def _model(system: str, user: str, phase: str) -> str:
        msg = client.messages.create(
            model=model, max_tokens=max_tokens, temperature=temperature,
            system=system, messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()

    return _model


# ── openai (and any OpenAI-compatible endpoint via base_url) ──────────────────

def openai_model(*, model: str = "gpt-4o", base_url: Optional[str] = None,
                 max_tokens: int = 8000, temperature: float = 0.2,
                 api_key_env: str = "OPENAI_API_KEY") -> ModelFn:
    """OpenAI chat-completions. Set `base_url` to point at any OpenAI-compatible gateway
    (OpenRouter, Groq, Together, Fireworks, vLLM, Ollama/LM Studio) — that one switch is
    what makes this reach essentially every model. Needs `pip install openai`."""
    try:
        import openai
    except ImportError as e:
        raise RuntimeError("`pip install openai` to use the openai provider.") from e
    client = openai.OpenAI(api_key=_require_key(api_key_env), base_url=base_url)

    def _model(system: str, user: str, phase: str) -> str:
        resp = client.chat.completions.create(
            model=model, max_tokens=max_tokens, temperature=temperature,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        return (resp.choices[0].message.content or "").strip()

    return _model


# ── gemini ───────────────────────────────────────────────────────────────────

def gemini_model(*, model: str = "gemini-2.0-flash", max_tokens: int = 8000,
                 temperature: float = 0.2, api_key_env: str = "GEMINI_API_KEY") -> ModelFn:
    """Google Generative AI SDK. Needs `pip install google-generativeai` and the key."""
    try:
        import google.generativeai as genai
    except ImportError as e:
        raise RuntimeError(
            "`pip install google-generativeai` to use the gemini provider."
        ) from e
    genai.configure(api_key=_require_key(api_key_env))

    def _model(system: str, user: str, phase: str) -> str:
        gm = genai.GenerativeModel(model, system_instruction=system)
        resp = gm.generate_content(
            user,
            generation_config={"temperature": temperature, "max_output_tokens": max_tokens},
        )
        return (resp.text or "").strip()

    return _model


# ── minimax (xiaomi/mimo) — OpenAI-compatible gateway to the Xiaomi family ──

# Xiaomi/Mimo subscription default endpoint. Override with base_url= if you proxy it.
MINIMAX_BASE_URL = "https://api.minimax.io/v1"
MINIMAX_API_KEY_ENV = "MINIMAX_API_KEY"
# Common Xiaomi family models (override per-call via model=).
MINIMAX_DEFAULT_MODEL = "MiniMax-M2.7"


def minimax_model(*, model: str = MINIMAX_DEFAULT_MODEL,
                  base_url: str = MINIMAX_BASE_URL,
                  max_tokens: int = 8000, temperature: float = 0.2,
                  api_key_env: str = MINIMAX_API_KEY_ENV) -> ModelFn:
    """Xiaomi/Mimo (minimax) provider. Reuses the openai SDK because Xiaomi's gateway
    speaks the OpenAI chat-completions protocol. The defaults match the minimax
    subscription: base_url points at the official MiniMax API, and the API key
    is read from MINIMAX_API_KEY. Override `model` to use other Xiaomi-family models
    (mimo-v2.5, mimo-v2.5-pro, MiniMax-M2.7, MiniMax-M3)."""
    return openai_model(
        model=model, base_url=base_url,
        max_tokens=max_tokens, temperature=temperature,
        api_key_env=api_key_env,
    )


# ── PhaseRouter — per-phase model routing ──────────────────────────────────
# A ModelFn that delegates to different backends based on the phase string.
# This lets the pipeline use, e.g., a cheap/fast model for CRITIQUE/REVIEW
# and a stronger model for IMPLEMENT, without changing the driver code.

@dataclass
class _PhaseRoute:
    """One route: phase prefix → ModelFn."""
    phase_prefix: str   # case-insensitive prefix to match (e.g. "implement", "review")
    model: ModelFn

class PhaseRouter:
    """ModelFn that dispatches to different backends per phase.

    Usage:
        router = PhaseRouter(default=mimo_model)
        router.route("implement", claude_model)   # stronger model for code
        router.route("review",    gemini_model)   # different reviewer
        # all other phases → mimo_model

    The first matching route wins (longest prefix). Case-insensitive.
    The `default` model handles any phase with no matching route.
    """
    def __init__(self, *, default: ModelFn):
        self._default = default
        self._routes: list[_PhaseRoute] = []

    def route(self, phase_prefix: str, model: ModelFn) -> "PhaseRouter":
        """Register a model for phases whose name starts with `phase_prefix`."""
        self._routes.append(_PhaseRoute(phase_prefix.lower(), model))
        return self  # chainable

    def __call__(self, system: str, user: str, phase: str) -> str:
        phase_lower = phase.lower()
        # Longest-prefix match
        best: _PhaseRoute | None = None
        for r in self._routes:
            if phase_lower.startswith(r.phase_prefix):
                if best is None or len(r.phase_prefix) > len(best.phase_prefix):
                    best = r
        model = best.model if best else self._default
        return model(system, user, phase)


# ── registry / factory ───────────────────────────────────────────────────────

_BACKENDS: dict[str, Callable[..., ModelFn]] = {
    "claude-cli": claude_cli_model,
    "anthropic": anthropic_model,
    "openai": openai_model,
    "gemini": gemini_model,
    "minimax": minimax_model,
}


def default_provider() -> str:
    """The provider make_model() picks when none is specified. Kept as a function so
    tests / env-driven entry points can override without patching the registry."""
    return os.environ.get("TECHNE_PROVIDER", "minimax")


def providers() -> list[str]:
    """Registered provider names (for CLI choices / help)."""
    return sorted(_BACKENDS)


def make_model(provider: str, **opts) -> ModelFn:
    """Build a ModelFn for `provider`. Forwards only the options that provider's adapter
    accepts (so a uniform CLI can pass model/base_url/temperature without each backend
    choking on the ones it ignores). None-valued options are dropped."""
    factory = _BACKENDS.get(provider)
    if factory is None:
        raise RuntimeError(f"unknown provider {provider!r}; choose from {providers()}")
    accepted = inspect.signature(factory).parameters
    kwargs = {k: v for k, v in opts.items() if k in accepted and v is not None}
    return factory(**kwargs)


def make_phase_router(
    *,
    default: str = "minimax",
    default_model: str | None = None,
    routes: dict[str, tuple[str, str | None]] | None = None,
) -> PhaseRouter:
    """Build a PhaseRouter from provider names.

    `default` is the fallback provider. `routes` maps phase prefixes to
    (provider, model_id) tuples. Example:
        make_phase_router(
            default="minimax",
            default_model="MiniMax-M2.7",
            routes={"implement": ("anthropic", "claude-sonnet-4-6")},
        )
    """
    router = PhaseRouter(default=make_model(default, model=default_model))
    for prefix, (provider, model_id) in (routes or {}).items():
        router.route(prefix, make_model(provider, model=model_id))
    return router


# ── real test runner (VERIFY) ────────────────────────────────────────────────

def command_test_runner(cmd: Union[str, Sequence[str]], *, cwd: Optional[str] = None,
                        timeout: int = 600) -> Callable[[], str]:
    """Return a TestFn that runs a REAL test command and returns combined stdout+stderr.
    Use for VERIFY — the SHA gate hashes whatever this returns, so it must be the actual
    suite output. A non-zero exit is fine; the SHA gate reads pass/fail indicators itself."""
    def _run() -> str:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
            shell=isinstance(cmd, str),
        )
        return (proc.stdout or "") + (proc.stderr or "")

    return _run
