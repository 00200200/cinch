"""Parameterized skills: schema validation, overrides, and safe template substitution.

Supports a ``parameters`` block in skill frontmatter without pulling in Jinja2 or
Pydantic. Placeholders in skill bodies use ``{{ name }}`` or ``$name`` /
``${name}`` and only declared parameter names are replaced (no code execution).
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from cinch.doc import Doc
from cinch.errors import CinchError

ALLOWED_TYPES = frozenset({"string", "int", "boolean", "choice"})
_TYPE_ALIASES = {"bool": "boolean"}

_BRACE_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_DOLLAR_BRACE_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_DOLLAR_NAME_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)\b")

_TRUE = frozenset({"true", "yes", "1", "on"})
_FALSE = frozenset({"false", "no", "0", "off"})


@dataclass(frozen=True)
class ParamSpec:
    """One skill parameter declaration."""

    name: str
    type: str
    default: Any = None
    has_default: bool = False
    help: str | None = None
    choices: tuple[str, ...] | None = None


def parse_param_flags(items: list[str] | tuple[str, ...] | None) -> dict[str, str]:
    """Parse repeated ``--param key=value`` CLI flags into a dict."""
    if not items:
        return {}
    out: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise CinchError(f"Invalid --param '{item}'; expected KEY=VALUE")
        key, _, value = item.partition("=")
        key = key.strip()
        if not key:
            raise CinchError(f"Invalid --param '{item}'; expected KEY=VALUE")
        out[key] = value
    return out


def params_from_environ(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Read ``CINCH_PARAM_<KEY>`` environment overrides (KEY uppercased)."""
    env = os.environ if environ is None else environ
    prefix = "CINCH_PARAM_"
    out: dict[str, str] = {}
    for key, value in env.items():
        if key.startswith(prefix) and len(key) > len(prefix):
            out[key[len(prefix) :].lower()] = value
    return out


def parse_param_specs(raw: Any) -> dict[str, ParamSpec]:
    """Validate a raw ``parameters`` frontmatter value into typed specs."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CinchError(f"Invalid parameters block: expected mapping, got {type(raw).__name__}")
    specs: dict[str, ParamSpec] = {}
    for name, decl in raw.items():
        if not isinstance(name, str) or not name.strip():
            raise CinchError("Invalid parameters block: parameter names must be non-empty strings")
        name = name.strip()
        if not isinstance(decl, dict):
            raise CinchError(
                f"Invalid parameter '{name}': expected mapping with type/default/help, "
                f"got {type(decl).__name__}"
            )
        specs[name] = _spec_from_decl(name, decl)
    return specs


def _spec_from_decl(name: str, decl: dict[str, Any]) -> ParamSpec:
    raw_type = decl.get("type", "string")
    if not isinstance(raw_type, str):
        raise CinchError(f"Invalid parameter '{name}': type must be a string")
    type_name = _TYPE_ALIASES.get(raw_type.strip().lower(), raw_type.strip().lower())
    if type_name not in ALLOWED_TYPES:
        raise CinchError(
            f"Invalid parameter '{name}': unknown type '{raw_type}' "
            f"(allowed: string, int, boolean, choice)"
        )

    help_val = decl.get("help")
    if help_val is not None and not isinstance(help_val, str):
        raise CinchError(f"Invalid parameter '{name}': help must be a string")

    choices_raw = decl.get("choices")
    choices: tuple[str, ...] | None = None
    if choices_raw is not None:
        if not isinstance(choices_raw, (list, tuple)) or not choices_raw:
            raise CinchError(f"Invalid parameter '{name}': choices must be a non-empty list")
        choices = tuple(str(c) for c in choices_raw)

    if type_name == "choice" and not choices:
        raise CinchError(f"Invalid parameter '{name}': type 'choice' requires choices")

    # string + choices behaves as a constrained choice set
    if choices and type_name == "string":
        type_name = "choice"

    has_default = "default" in decl
    default = decl.get("default") if has_default else None
    if has_default:
        try:
            default = coerce_value(
                ParamSpec(
                    name=name,
                    type=type_name,
                    default=None,
                    has_default=False,
                    help=help_val,
                    choices=choices,
                ),
                default,
            )
        except CinchError as exc:
            raise CinchError(f"Invalid default for parameter '{name}': {exc}") from exc

    return ParamSpec(
        name=name,
        type=type_name,
        default=default,
        has_default=has_default,
        help=help_val,
        choices=choices,
    )


def coerce_value(spec: ParamSpec, raw: Any) -> Any:
    """Coerce a raw override/default to the parameter's declared type."""
    if spec.type == "string":
        if raw is None:
            raise CinchError("expected a string value")
        return str(raw)

    if spec.type == "int":
        if isinstance(raw, bool):
            raise CinchError(f"expected int, got boolean {raw!r}")
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and re.fullmatch(r"-?\d+", raw.strip()):
            return int(raw.strip())
        raise CinchError(f"expected int, got {raw!r}")

    if spec.type == "boolean":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)) and raw in (0, 1):
            return bool(raw)
        if isinstance(raw, str):
            lowered = raw.strip().lower()
            if lowered in _TRUE:
                return True
            if lowered in _FALSE:
                return False
        raise CinchError(f"expected boolean, got {raw!r}")

    if spec.type == "choice":
        if spec.choices is None:
            raise CinchError("choice parameter has no choices")
        value = str(raw)
        if value not in spec.choices:
            allowed = ", ".join(spec.choices)
            raise CinchError(f"value {value!r} not in choices [{allowed}]")
        return value

    raise CinchError(f"unknown type '{spec.type}'")


def render_template(text: str, values: Mapping[str, Any]) -> str:
    """Replace ``{{ name }}``, ``${name}``, and ``$name`` for declared keys only."""
    if not values or not text:
        return text

    stringified = {name: str(value) for name, value in values.items()}

    def _brace(match: re.Match[str]) -> str:
        name = match.group(1)
        return stringified[name] if name in stringified else match.group(0)

    def _dollar_brace(match: re.Match[str]) -> str:
        name = match.group(1)
        return stringified[name] if name in stringified else match.group(0)

    def _dollar(match: re.Match[str]) -> str:
        name = match.group(1)
        return stringified[name] if name in stringified else match.group(0)

    text = _BRACE_RE.sub(_brace, text)
    text = _DOLLAR_BRACE_RE.sub(_dollar_brace, text)
    text = _DOLLAR_NAME_RE.sub(_dollar, text)
    return text


def resolve_param_values(
    specs: Mapping[str, ParamSpec],
    *,
    cli_overrides: Mapping[str, str] | None = None,
    environ: Mapping[str, str] | None = None,
    interactive: bool = False,
) -> dict[str, Any]:
    """Resolve parameter values: CLI > env > default > interactive prompt.

    Raises :class:`CinchError` when a required value is missing in non-interactive mode.
    """
    cli = dict(cli_overrides or {})
    env = params_from_environ(environ)

    unknown = set(cli) - set(specs)
    if unknown:
        names = ", ".join(sorted(unknown))
        raise CinchError(f"Unknown parameter override(s): {names}")

    values: dict[str, Any] = {}
    for name, spec in specs.items():
        raw: Any | None
        source: str
        if name in cli:
            raw = cli[name]
            source = "cli"
        elif name in env:
            raw = env[name]
            source = "env"
        elif spec.has_default:
            values[name] = spec.default
            continue
        else:
            raw = None
            source = "missing"

        if raw is not None:
            try:
                values[name] = coerce_value(spec, raw)
            except CinchError as exc:
                raise CinchError(f"Invalid {source} value for parameter '{name}': {exc}") from exc
            continue

        if interactive and sys.stdin.isatty():
            values[name] = _prompt_param(spec)
            continue

        env_key = f"CINCH_PARAM_{name.upper()}"
        raise CinchError(
            f"Missing required parameter '{name}'. Pass --param {name}=VALUE or set {env_key}"
        )

    return values


def _prompt_param(spec: ParamSpec) -> Any:
    """Prompt for a missing required parameter via questionary."""
    import questionary

    message = spec.help or f"Value for parameter '{spec.name}'"
    if spec.type == "choice" and spec.choices:
        selected = questionary.select(message, choices=list(spec.choices)).ask()
        if selected is None:
            raise CinchError("Cancelled")
        return coerce_value(spec, selected)

    if spec.type == "boolean":
        selected = questionary.confirm(message, default=False).ask()
        if selected is None:
            raise CinchError("Cancelled")
        return bool(selected)

    typed = questionary.text(message).ask()
    if typed is None:
        raise CinchError("Cancelled")
    return coerce_value(spec, typed)


def apply_parameters_to_doc(
    doc: Doc,
    *,
    cli_overrides: Mapping[str, str] | None = None,
    environ: Mapping[str, str] | None = None,
    interactive: bool = False,
) -> Doc:
    """Validate parameters, resolve values, substitute into body/description, strip schema."""
    raw = doc.extra_meta.get("parameters") if doc.extra_meta else None
    if raw is None:
        return doc

    specs = parse_param_specs(raw)
    new_meta = {k: v for k, v in doc.extra_meta.items() if k != "parameters"}

    if not specs:
        return replace(doc, extra_meta=new_meta)

    values = resolve_param_values(
        specs,
        cli_overrides=cli_overrides,
        environ=environ,
        interactive=interactive,
    )
    return replace(
        doc,
        description=render_template(doc.description, values),
        body=render_template(doc.body, values),
        extra_meta=new_meta,
    )
