"""Tests for fail-closed redact-before-persist (SPEC.md §16.2)."""

import re
from pathlib import Path

from ledger.redaction import RedactionPolicy, redact


def test_redacts_a_secret_key_assignment():
    raw = b'DEBUG=true\nAPI_KEY=sk-live-abcdef1234567890\n'

    redacted = redact(raw)

    assert b'sk-live-abcdef1234567890' not in redacted
    assert b'DEBUG=true' in redacted


def test_redacts_a_known_provider_token_pattern():
    raw = b'curl -H "Authorization: Bearer sk-ant-api03-abcdefghijklmnopqrstuvwx"'

    redacted = redact(raw)

    assert b'sk-ant-api03-abcdefghijklmnopqrstuvwx' not in redacted


def test_redacts_an_environment_value_not_allow_listed():
    policy = RedactionPolicy(
        environment={'DATABASE_PASSWORD': 'correcthorsebatterystaple'}
    )

    redacted = redact(b'connecting with correcthorsebatterystaple now', policy)

    assert b'correcthorsebatterystaple' not in redacted


def test_leaves_an_allow_listed_environment_value_untouched():
    policy = RedactionPolicy(
        allowed_env_names=frozenset({'PATH'}),
        environment={'PATH': '/usr/local/bin/toolchain'},
    )

    redacted = redact(b'using /usr/local/bin/toolchain to build', policy)

    assert b'/usr/local/bin/toolchain' in redacted


def test_redacts_a_filesystem_path_outside_the_allowed_roots():
    redacted = redact(b'wrote output to /home/alice/.ssh/id_rsa', RedactionPolicy())

    assert b'/home/alice/.ssh/id_rsa' not in redacted


def test_leaves_a_path_under_an_allowed_root_untouched():
    policy = RedactionPolicy(allowed_roots=(Path('/repo'),))

    redacted = redact(b'wrote output to /repo/src/main.py', policy)

    assert b'/repo/src/main.py' in redacted


def test_applies_a_caller_supplied_regex_pattern():
    policy = RedactionPolicy(extra_patterns=(re.compile(rb'internal-[0-9]+'),))

    redacted = redact(b'ticket internal-4821 closed', policy)

    assert b'internal-4821' not in redacted


def test_redaction_is_deterministic_for_the_same_input():
    raw = b'API_KEY=sk-live-abcdef1234567890 and a path /home/alice/secret'

    assert redact(raw) == redact(raw)
