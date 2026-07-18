# agentmaster — GitHub Copilot port

The same architecture as the Claude Code version, expressed as Copilot custom
agents: two Opus coordinators that can only delegate, and four cheap workers
that do everything else. One thing is actually *better* here than in Claude
Code: a Copilot agent's `tools` list restricts the agent itself, so the
coordinators mechanically cannot read files or run commands — the cost
boundary that had to be prose in the Claude Code skills is config in this
port.

## Requirements

The superpowers plugin is required: `agentmaster-plan` runs its
`brainstorming` skill during framing and formalizes with `writing-plans`,
and the handoff offers `executing-plans`. The installer detects it and
offers to install it (`copilot plugin marketplace add
obra/superpowers-marketplace`, then `copilot plugin install
superpowers@superpowers-marketplace`). Without it, plan formalization falls
back to inline structure — functional, but not the supported configuration.

## Install

The scripted path handles everything below — superpowers check, model
selection, backups, and conflict cleanup:

```bash
python install.py install --target copilot
```

Or manually:

```bash
# repo-scoped (check into version control)
mkdir -p .github/agents
cp copilot/agents/*.agent.md .github/agents/

# or user-scoped for Copilot CLI
mkdir -p ~/.copilot/agents
cp copilot/agents/*.agent.md ~/.copilot/agents/
```

## Use

VS Code: open the agent picker and select `agentmaster-plan`, describe the
task, and let it run; the workers are `user-invocable: false` so they stay
out of your picker and exist only for delegation. At the Plan Ready for
Review prompt, settle any blocking open questions, exit plan mode, and run
the `agentmaster-execute` agent — it dispatches implementers per group and
performs the full review itself (embedded because subagent nesting is off by
default, so a coordinator can't reliably spawn the review coordinator with
its workers). Avoid the autopilot/`/fleet` accept options: fleet's generic
workers ignore the implementer's scope rules and inherit the Opus session
model. The plan now defends itself too — it opens with an execution contract
telling any fleet/autopilot/generic agent that reads it to stop and hand
back to `agentmaster-execute` — but prefer never sending it there.
Headless/CI: run `copilot -p "..." --no-ask-user` with `--headless` in the
task; coordinators substitute ASSUMED least-destructive defaults for
questions and emit a `BLOCKED:` report when no safe default exists.
Review criteria are single-sourced in `criteria/review-criteria.md` — edit
there and run `python install.py sync`; never edit the three carrier copies.
Plan-mode notes: the coordinators now carry `ask_user`, so decision batches
render as native question boxes (one batched ballot with defaults) instead
of text ballots — the tools allowlist is exclusive, and earlier versions
stripped the widget along with the repo tools. Plan mode also blocks
workspace writes for subagents: evidence files and ledger snapshots defer to
execution start, with evidence carried inline meanwhile. The finished plan
still lands in plan mode's own plan document and todos, so the native
accept flow keeps working.

Router skills: `copilot/skills/` ships three thin SKILL.md routers installed
to `~/.copilot/skills/` — they catch natural-language and `/agentmaster-*`
invocations by description and immediately hand off to the matching custom
agent, where the model pin and tool restriction live. Protocol stays
single-sourced in the agents; replace any stray full Claude Code SKILL.md
copies with these (the installer overwrites them). Manual install:
`cp -r copilot/skills/* ~/.copilot/skills/`. Review runs the same way —
select `agentmaster-review`, optionally giving a ref range. Copilot CLI: start
`copilot`, then `/agent` to select the coordinator. For ad-hoc parallel work
without this system, the CLI's built-in `/fleet` does orchestrator-style
decomposition on its own.

## Hook layer

`install.py` writes `~/.copilot/hooks/agentmaster.json` (its own
file — hook files combine additively, so yours are never edited) wiring
three scripts from `~/.copilot/agentmaster-hooks/`: dispatch telemetry on
`preToolUse`/`postToolUse` (self-filtered to the `agent` tool; wall-clock
per dispatch into `.agentmaster/telemetry.md` — Copilot hooks carry no token
counts, so spend stays with `/usage`), and a `sessionStart` pointer to
`.agentmaster/` artifacts. Headless note: `copilot -p` disables repository-level hooks by
default (`GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS=true` opts in); the layer
installs user-level partly for this reason. `AGENTMASTER_HOOK_DEBUG=1`
dumps payloads to `.agentmaster/hook-debug.jsonl`.

## Model notes

- Coordinators pin `model: claude-opus-4.8` (org disables fable). Model
  identifiers vary by org policy and surface — confirm the exact slugs your
  org enables via the model picker before first use, and adjust the worker
  pins (`claude-haiku-4.5`, `claude-sonnet-4.6`) to whatever cheap tiers are
  enabled.
- Keep `model` a plain string. VS Code accepts an array for fallback; the
  Copilot CLI rejects arrays and refuses to load the agent — the known
  cross-surface incompatibility.
- Copilot bills by premium-request multipliers, not tokens, which changes the
  economics in your favor: if your org enables a 0x included model, pinning
  `scout` to it makes evidence gathering effectively free. Check the current
  multiplier table before choosing worker models.
- The CLI's cost-multiplier guard silently *downgrades* a subagent whose
  pinned model exceeds the session's multiplier. This system runs the
  expensive model in the session and cheaper models in workers — the allowed
  direction — so the guard doesn't bite here. It would bite an inverted
  design (cheap session, premium workers).

## Platform caveats

- Subagent nesting is off by default in VS Code
  (`chat.subagents.allowInvocationsFromSubagents`), which matches this
  design — leave it off; workers should never spawn workers.
- `handoffs` and `argument-hint` frontmatter are ignored by the cloud coding
  agent on github.com, so this port avoids both; the review gate is written
  into the plan as an instruction instead.
- There are no `effort` or `maxTurns` equivalents. Bound runaway workers with
  the subagent concurrency and depth limits in the CLI's `/settings`
  (v1.0.66+) and the per-dispatch line caps in the report contract.
- There is no built-in Explore agent to override; Copilot has no equivalent
  of that Claude Code cost leak.
- Graph queries route through your graphify MCP server as configured in the
  harness; `code-analyst` is instructed to use those tools when the session
  exposes them.
- Superpowers works here too: with the superpowers marketplace installed as a
  Copilot plugin, the planning coordinator uses `brainstorming` in Phase 1
  and `writing-plans` to formalize, and the handoff offers
  `executing-plans` — the same workflow as the Claude Code version, degrading
  gracefully if the plugin is absent.
