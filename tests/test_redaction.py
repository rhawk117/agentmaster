import re
from pathlib import Path

from ledger.artifact_store import ArtifactStore
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


def test_redacts_a_github_fine_grained_pat():
    token = b'github_pat_11AAAAAAA0abcdefghijklmnopqrstuvwxyz0123456789'
    raw = b'push using ' + token

    redacted = redact(raw)

    assert token not in redacted


def test_redacts_a_bare_jwt():
    jwt = (
        b'eyJhbGciOiJIUzI1NiJ9'
        b'.eyJzdWIiOiIxMjM0NTY3ODkwIn0'
        b'.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U'
    )
    raw = b'Authorization: ' + jwt

    redacted = redact(raw)

    assert jwt not in redacted


def test_redacts_a_multiline_pem_private_key_block_including_newlines():
    pem = (
        b'-----BEGIN RSA PRIVATE KEY-----\n'
        b'MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj\n'
        b'MzEfYyjiWA4R4/M2bS1GB4t7NXp98C3SC6dVMvDuictGeurT8jNbvJZHtCSuYEvu\n'
        b'-----END RSA PRIVATE KEY-----'
    )
    raw = b'saved key:\n' + pem + b'\ndone'

    redacted = redact(raw)

    assert b'BEGIN RSA PRIVATE KEY' not in redacted
    assert (
        b'MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj'
        not in redacted
    )
    assert b'END RSA PRIVATE KEY' not in redacted


def test_redacts_a_short_sk_style_token_regardless_of_env_length_threshold():
    raw = b'export KEY=sk-a1b2c3'

    redacted = redact(raw)

    assert b'sk-a1b2c3' not in redacted


def test_planted_secrets_do_not_survive_a_round_trip_through_artifact_store(tmp_path):
    pem = (
        b'-----BEGIN PRIVATE KEY-----\n'
        b'MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcw\n'
        b'-----END PRIVATE KEY-----'
    )
    raw = (
        b'github_pat_11AAAAAAA0abcdefghijklmnopqrstuvwxyz0123456789\n'
        b'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U\n'
        b'sk-a1b2c3\n' + pem
    )

    redacted = redact(raw)
    store = ArtifactStore(tmp_path)
    write = store.put(redacted)
    persisted = store.read(write.sha256)

    assert b'github_pat_' not in persisted
    assert b'eyJhbGciOiJIUzI1NiJ9' not in persisted
    assert b'sk-a1b2c3' not in persisted
    assert b'BEGIN PRIVATE KEY' not in persisted
