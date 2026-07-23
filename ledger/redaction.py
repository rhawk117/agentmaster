import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_MASK = b'[REDACTED]'
_PATH_MASK = b'[REDACTED-PATH]'

_MIN_ENV_VALUE_LENGTH = 8

_SECRET_KEY_ASSIGNMENT = re.compile(
    rb'(?i)\b([\w.-]*(?:KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL)[\w.-]*)'
    rb'\s*[:=]\s*("[^"\n]*"|\'[^\'\n]*\'|\S+)'
)

_PROVIDER_TOKEN_PATTERNS = (
    re.compile(rb'sk-ant-[A-Za-z0-9_-]+'),
    re.compile(rb'sk-[A-Za-z0-9]+'),
    re.compile(rb'gh[pousr]_[A-Za-z0-9]+'),
    re.compile(rb'github_pat_[A-Za-z0-9_]+'),
    re.compile(rb'AKIA[0-9A-Z]{16}'),
    re.compile(rb'xox[baprs]-[A-Za-z0-9-]+'),
    re.compile(rb'(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}'),
    re.compile(rb'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'),
    re.compile(
        rb'-----BEGIN [^-\n]*PRIVATE KEY-----.*?-----END [^-\n]*PRIVATE KEY-----',
        re.DOTALL,
    ),
)

_UNIX_PATH = re.compile(rb'(?<![\w/])/(?:[\w.@%+-]+/)+[\w.@%+-]+')
_WINDOWS_PATH = re.compile(rb'(?<![\w\\])[A-Za-z]:\\(?:[\w .@%+-]+\\)+[\w .@%+-]+')


@dataclass(frozen=True, slots=True)
class RedactionPolicy:
    allowed_env_names: frozenset[str] = frozenset()
    environment: Mapping[str, str] = field(default_factory=dict)
    allowed_roots: tuple[Path, ...] = ()
    extra_patterns: tuple[re.Pattern[bytes], ...] = ()


def redact(data: bytes, policy: RedactionPolicy | None = None) -> bytes:
    policy = policy if policy is not None else RedactionPolicy()
    safe_values = _allow_listed_values(policy)
    result = _redact_environment_values(data, policy)
    for pattern in _PROVIDER_TOKEN_PATTERNS:
        result = pattern.sub(_MASK, result)
    result = _SECRET_KEY_ASSIGNMENT.sub(
        lambda match: match.group(1) + b'=' + _MASK, result
    )
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
