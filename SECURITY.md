# Security Policy

## Supported Versions

Agentmaster provides security fixes for the latest stable release line.

| Version | Support |
| --- | --- |
| `1.1.x` | Supported |
| `< 1.1` | Unsupported |
| `develop` and prereleases | Best effort; no guaranteed security support |

When a new major version is released, the previous major may receive critical
security fixes for up to 90 days to provide a reasonable migration window. Any
exception will be documented in the relevant release notes.

## Reporting a Vulnerability

Do not publish exploit details, secrets, tokens, private repository content, or
other sensitive information in a public issue.

### Sensitive vulnerabilities

Use GitHub's private vulnerability reporting feature:

1. Open the repository's **Security** tab.
2. Select **Advisories**.
3. Select **Report a vulnerability**.
4. Include the information requested below.

If private vulnerability reporting is unavailable, create a minimal public issue
requesting private contact. Use the `security` label if you have permission, or
prefix the title with `[Security]`. Do not include reproduction details or
sensitive evidence in that issue.

### Public security issues

Public issues are appropriate for non-sensitive security hardening,
documentation gaps, already-public advisories, and dependency maintenance.

Use the repository's security issue template when available. It should apply the
`security` label automatically. If opening an issue manually:

- apply `security` when permitted;
- otherwise prefix the title with `[Security]`;
- add `dependencies` for a dependency advisory;
- add `documentation` for security-policy or guidance changes;
- do not assign a severity label unless you are a maintainer performing triage.

Maintainers will add `bug` when the report is confirmed as a defect and assign
the appropriate severity and priority labels during triage.

## What to Include

Provide enough information to reproduce and assess the issue safely:

- affected Agentmaster version or commit;
- affected target, such as Claude Code, GitHub Copilot, installer, hooks, ledger,
  harnesses, or release tooling;
- operating system and relevant runtime versions;
- expected and observed behavior;
- security impact and required attacker access;
- minimal reproduction steps or proof of concept;
- relevant logs with credentials, tokens, personal data, and private paths
  removed;
- known mitigations or suggested fixes, if available.

Reports involving command execution, path traversal, settings corruption,
credential exposure, unsafe hook behavior, privilege or trust-boundary bypass,
ledger corruption, cross-project memory disclosure, concurrent-session isolation,
release integrity, or dependency compromise are considered security relevant.

## Response Process

The project will make a best-effort attempt to:

- acknowledge a private report within three business days;
- provide an initial assessment within seven business days;
- send an update at least every fourteen days while remediation is active;
- explain whether the report was accepted, declined, duplicated, or determined
  to be outside Agentmaster's scope;
- coordinate a fix, advisory, CVE request when appropriate, and release timing
  before public disclosure.

Response times may vary based on severity, maintainer availability, and the
complexity of reproducing the issue.

## Disclosure and Remediation

If a report is accepted, maintainers will:

1. Confirm affected versions and severity.
2. Develop and review the fix privately when disclosure would increase risk.
3. Add regression coverage where practical.
4. Publish a patched release and security advisory.
5. Credit the reporter unless they request anonymity.

Please allow maintainers reasonable time to investigate and release a fix before
public disclosure. Publishing a release does not authorize moving or reusing an
existing tag; a corrected release receives a new version.

If a report is declined, maintainers will provide a brief reason when doing so
would not expose sensitive information.

## Scope

This policy covers vulnerabilities introduced by Agentmaster's maintained
source code, installer, generated agents and skills, hooks, ledger, harnesses,
CI configuration, and release artifacts.

Security problems in Claude Code, GitHub Copilot, GitHub, operating systems, or
other third-party services should be reported to the applicable vendor. If an
Agentmaster integration makes an upstream issue exploitable in a new way, report
the integration behavior here as well.

## Safe Harbor

Good-faith research that avoids privacy violations, data destruction, service
disruption, social engineering, and access beyond what is necessary to
demonstrate the issue is welcome. This project does not currently operate a paid
bug-bounty program.
