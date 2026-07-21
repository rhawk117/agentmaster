"""Fail-closed redact-before-persist for raw command/tool captures (SPEC.md §16.2).

Redaction runs on raw bytes before any digest is computed and before
anything touches disk, so a secret is never hashed merely to claim it is
safe to store. Everything not explicitly allow-listed is treated as unsafe:
env values are masked unless their name is allow-listed, and filesystem
paths are masked unless they fall under an allowed root.
"""

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_MASK = b'[REDACTED]'
_PATH_MASK = b'[REDACTED-PATH]'

# Below this length an env value is too generic (e.g. "1", "true") to mask
# safely without redacting unrelated output wholesale.
_MIN_ENV_VALUE_LENGTH = 8

_SECRET_KEY_ASSIGNMENT = re.compile(
    rb'(?i)\b([\w.-]*(?:KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL)[\w.-]*)'
    rb'\s*[:=]\s*("[^"\n]*"|\'[^\'\n]*\'|\S+)'
)

_PROVIDER_TOKEN_PATTERNS = (
    re.compile(rb'sk-ant-[A-Za-z0-9_-]{20,}'),  # Anthropic
    re.compile(rb'sk-[A-Za-z0-9]{20,}'),  # OpenAI-style
    re.compile(rb'gh[pousr]_[A-Za-z0-9]{20,}'),  # GitHub tokens
    re.compile(rb'AKIA[0-9A-Z]{16}'),  # AWS access key id
    re.compile(rb'xox[baprs]-[A-Za-z0-9-]+'),  # Slack tokens
    re.compile(rb'(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}'),  # Bearer/Authorization headers
)

_UNIX_PATH = re.compile(rb'(?<![\w/])/(?:[\w.@%+-]+/)+[\w.@%+-]+')
_WINDOWS_PATH = re.compile(rb'(?<![\w\\])[A-Za-z]:\\(?:[\w .@%+-]+\\)+[\w .@%+-]+')


@dataclass(frozen=True, slots=True)
class RedactionPolicy:
    """What is explicitly safe to leave unmasked; everything else is redacted."""

    allowed_env_names: frozenset[str] = frozenset()
    environment: Mapping[str, str] = field(default_factory=dict)
    allowed_roots: tuple[Path, ...] = ()
    extra_patterns: tuple[re.Pattern[bytes], ...] = ()


def redact(data: bytes, policy: RedactionPolicy | None = None) -> bytes:
    """Mask secret assignments, provider tokens, unsafe env values, and unsafe paths.

    An allow-listed env value is treated as fully safe, including when it
    also matches the path pattern (e.g. an allow-listed `PATH`).
    """
    policy = policy if policy is not None else RedactionPolicy()
    safe_values = _allow_listed_values(policy)
    result = _redact_environment_values(data, policy)
    result = _SECRET_KEY_ASSIGNMENT.sub(
        lambda match: match.group(1) + b'=' + _MASK, result
    )
    for pattern in _PROVIDER_TOKEN_PATTERNS:
        result = pattern.sub(_MASK, result)
    result = _redact_paths(result, policy.allowed_roots, safe_values)
    for pattern in policy.extra_patterns:
        result = pattern.sub(_MASK, result)
    return result


def _allow_listed_values(policy: RedactionPolicy) -> frozenset[bytes]:
    return frozenset(
        value.encode('utf-8', errors='ignore')
        for name, value in policy.environment.items()
        if name in policy.allowed_env_names and value
    )


def _redact_environment_values(data: bytes, policy: RedactionPolicy) -> bytes:
    result = data
    for name, value in policy.environment.items():
        if name in policy.allowed_env_names:
            continue
        encoded = value.encode('utf-8', errors='ignore')
        if len(encoded) >= _MIN_ENV_VALUE_LENGTH:
            result = result.replace(encoded, _MASK)
    return result


def _redact_paths(
    data: bytes, allowed_roots: tuple[Path, ...], safe_values: frozenset[bytes]
) -> bytes:
    allowed_prefixes = tuple(str(root).encode() for root in allowed_roots)

    def _mask_if_outside(match: re.Match[bytes]) -> bytes:
        candidate = match.group(0)
        if candidate in safe_values or any(
            candidate.startswith(prefix) for prefix in allowed_prefixes
        ):
            return candidate
        return _PATH_MASK

    result = _UNIX_PATH.sub(_mask_if_outside, data)
    return _WINDOWS_PATH.sub(_mask_if_outside, result)
