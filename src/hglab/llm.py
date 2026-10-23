"""Provider adapters routed from config/models.yaml."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from hglab.secrets import get_secret


@dataclass
class ModelResult:
    value: dict[str, Any]
    input_tokens: int
    output_tokens: int
    provider: str
    model: str


def route_config(route: str, root: Path, author_runtime: str | None = None) -> dict[str, Any]:
    """Resolve a route; the review route prefers the other vendor only when both keys exist.

    A route whose vendor has no key configured falls back to the vendor that does (using the
    science route's model for Anthropic), so a single key is enough to run everything.
    """
    config = yaml.safe_load((root / "config/models.yaml").read_text(encoding="utf-8"))
    try:
        selected = dict(config["routes"][route])
    except KeyError as exc:
        raise ValueError(f"unknown model route: {route}") from exc
    if selected.get("provider") == "ollama":
        return selected  # a local model never falls back to a vendor: the route is the promise
    has_anthropic = bool(get_secret("ANTHROPIC_API_KEY", root))
    has_openai = bool(get_secret("OPENAI_API_KEY", root))
    openai_model = next(
        (r.get("model", "") for r in config["routes"].values() if r.get("provider") == "openai" and r.get("model") not in ("", "TODO")),
        "",
    )
    openai_usable = bool(has_openai and openai_model)
    if route == "review" and has_anthropic and openai_usable:
        if author_runtime and author_runtime.startswith("actions-openai"):
            selected["provider"] = "anthropic"
            selected["model"] = config["routes"]["science"]["model"]
            selected["effort"] = "high"
        elif author_runtime and author_runtime.startswith("actions-anthropic"):
            selected["provider"] = "openai"
            selected["model"] = openai_model
    if selected["provider"] == "openai" and not openai_usable and has_anthropic:
        selected["provider"] = "anthropic"
        selected["model"] = config["routes"]["science"]["model"]
        selected["effort"] = selected.get("effort", "high")
    elif selected["provider"] == "anthropic" and not has_anthropic and openai_usable:
        selected["provider"] = "openai"
        selected["model"] = openai_model
    return selected


UNSUPPORTED_SCHEMA_KEYS = {
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength",
    "minItems", "maxItems", "minProperties", "maxProperties", "pattern", "format", "$schema",
    "uniqueItems", "default", "multipleOf",
}


def strict_schema(schema: Any) -> Any:
    """Copy of a JSON Schema in the subset structured outputs accept.

    Drops value constraints (bounds, lengths, patterns), closes every object, and keeps
    ``$ref``/``$defs``. Our own validators enforce the dropped limits after the call.
    """
    if isinstance(schema, list):
        return [strict_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key in UNSUPPORTED_SCHEMA_KEYS:
            continue
        if key in {"properties", "$defs", "definitions"} and isinstance(value, dict):
            out[key] = {name: strict_schema(sub) for name, sub in value.items()}
        else:
            out[key] = strict_schema(value)
    types = out.get("type")
    is_object = types == "object" or (isinstance(types, list) and "object" in types)
    if is_object:
        out["additionalProperties"] = False
        if "properties" in out and "required" not in out:
            out["required"] = list(out["properties"])
    return out


def structured_call(
    route: str,
    prompt: str,
    schema: dict[str, Any],
    *,
    root: Path,
    output_tokens: int = 1600,
    author_runtime: str | None = None,
) -> ModelResult:
    """Call the configured vendor once; world-provided strings remain delimited data."""
    config = route_config(route, root, author_runtime)
    schema = strict_schema(schema)
    if config["provider"] == "anthropic":
        import anthropic

        client = anthropic.Anthropic(
            api_key=get_secret("ANTHROPIC_API_KEY", root),
            timeout=18 if route == "challenge" else 120,
        )
        response = client.messages.create(
            model=config["model"],
            max_tokens=output_tokens,
            output_config={
                "effort": config.get("effort", "low"),
                "format": {"type": "json_schema", "schema": schema},
            },
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason in {"refusal", "max_tokens"}:
            raise ValueError(f"model stopped without a complete response: {response.stop_reason}")
        text = "".join(block.text for block in response.content if getattr(block, "text", None))
        usage = response.usage
        model = response.model
        provider = "anthropic"
        input_tokens, output_tokens_used = usage.input_tokens, usage.output_tokens
    elif config["provider"] == "openai":
        import openai

        client = openai.OpenAI(
            api_key=get_secret("OPENAI_API_KEY", root),
            timeout=18 if route == "challenge" else 120,
        )
        response = client.responses.create(
            model=config["model"],
            input=prompt,
            text={
                "format": {
                    "type": "json_schema",
                    "name": f"hglab_{route}",
                    "schema": schema,
                    "strict": True,
                }
            },
        )
        text = response.output_text
        model = response.model
        provider = "openai"
        input_tokens = response.usage.input_tokens if response.usage else 0
        output_tokens_used = response.usage.output_tokens if response.usage else 0
    elif config["provider"] == "ollama":
        import httpx

        base = str(config.get("base_url") or "http://127.0.0.1:11434").rstrip("/")
        payload = {
            "model": config["model"],
            "stream": False,
            "think": False,  # a thinking model spends its whole budget thinking; the fool just answers
            "format": schema,
            "options": {"num_predict": output_tokens, "temperature": float(config.get("temperature", 0.7))},
            "messages": [{"role": "user", "content": prompt}],
        }
        response = httpx.post(f"{base}/api/chat", json=payload, timeout=float(config.get("timeout", 120)))
        response.raise_for_status()
        data = response.json()
        text = str((data.get("message") or {}).get("content") or "")
        if data.get("done_reason") == "length" or not text.strip():
            raise ValueError(f"local model stopped without a complete response: {data.get('done_reason')}")
        model = str(data.get("model") or config["model"])
        provider = "ollama"
        input_tokens = int(data.get("prompt_eval_count") or 0)
        output_tokens_used = int(data.get("eval_count") or 0)
    else:
        raise ValueError(f"unsupported model provider: {config['provider']}")
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise TypeError("structured model output must be a JSON object")
    return ModelResult(parsed, input_tokens, output_tokens_used, provider, model)
