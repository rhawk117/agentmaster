#!/usr/bin/env bash
# install-claude.sh — install agentmaster into Claude Code (user scope): skills,
# agents, and the lifecycle hook layer. Run from the unpacked bundle root.
set -euo pipefail

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
  YELLOW=$'\033[33m'; BLUE=$'\033[34m'; CYAN=$'\033[36m'; RESET=$'\033[0m'
else
  BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; CYAN=""; RESET=""
fi
step() { printf '%s\n' "${BOLD}${BLUE}==>${RESET}${BOLD} $*${RESET}"; }
ok()   { printf '%s\n' "  ${GREEN}✔${RESET} $*"; }
warn() { printf '%s\n' "  ${YELLOW}!${RESET} $*"; }
err()  { printf '%s\n' "  ${RED}✘${RESET} $*" >&2; }
info() { printf '%s\n' "  ${DIM}$*${RESET}"; }
ask() {
  local prompt="$1" default="${2:-Y}" reply hint
  [[ "$default" == "Y" ]] && hint="[Y/n]" || hint="[y/N]"
  if [[ ! -t 0 ]]; then info "non-interactive — assuming '${default}' for: ${prompt}"; [[ "$default" == "Y" ]]; return; fi
  read -rp "  ${CYAN}?${RESET} ${prompt} ${hint} " reply || reply=""
  [[ "${reply:-$default}" =~ ^[Yy] ]]
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
CLAUDE_HOME="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SKILLS=(agentmaster-plan agentmaster-execute agentmaster-review)
AGENTS=(scout code-analyst plan-critic implementer explore)
HOOKS=(telemetry.sh subagent-start.sh dispatch-guard.sh precompact-snapshot.sh session-context.sh git-guard.sh)

printf '%s\n' "${BOLD}agentmaster — Claude Code installer${RESET}"
printf '%s\n' "${DIM}skills + workers + the lifecycle hook layer${RESET}"; echo

step "1/6 Preflight"
command -v python3 >/dev/null || { err "python3 is required (hooks and settings merge)"; exit 1; }
for s in "${SKILLS[@]}"; do [[ -f "${SCRIPT_DIR}/skills/${s}/SKILL.md" ]] || { err "missing skills/${s}"; exit 1; }; done
for a in "${AGENTS[@]}"; do [[ -f "${SCRIPT_DIR}/agents/${a}.md" ]] || { err "missing agents/${a}.md"; exit 1; }; done
for h in "${HOOKS[@]}"; do [[ -f "${SCRIPT_DIR}/hooks/${h}" ]] || { err "missing hooks/${h}"; exit 1; }; done
ok "bundle complete: 3 skills, 5 agents, 6 hooks"
if [[ -n "${CLAUDE_CODE_SUBAGENT_MODEL:-}" ]]; then
  warn "CLAUDE_CODE_SUBAGENT_MODEL is exported — it overrides every worker model pin;"
  warn "the dispatch-guard hook will block dispatches until it is unset"
fi
command -v claude >/dev/null && ok "claude CLI found" || warn "claude CLI not on PATH — plugin check falls back to the filesystem"

step "2/6 Superpowers skills"
if { command -v claude >/dev/null && claude plugin list 2>/dev/null | grep -qi superpowers; } \
   || compgen -G "${CLAUDE_HOME}/plugins/*superpowers*" >/dev/null; then
  ok "superpowers detected"
else
  warn "superpowers not detected — agentmaster-plan uses brainstorming and writing-plans when present"
  if ask "install the superpowers plugin now?" Y; then
    if command -v claude >/dev/null; then
      claude plugin marketplace add obra/superpowers-marketplace 2>/dev/null || true
      claude plugin install superpowers@superpowers-marketplace \
        && ok "superpowers installed" \
        || { err "install failed — inside claude, run /plugin and install superpowers manually"; }
    else
      info "install later: claude plugin marketplace add obra/superpowers-marketplace"
      info "               claude plugin install superpowers@superpowers-marketplace"
    fi
  else
    info "skipped — the skills degrade gracefully"
  fi
fi

step "3/6 Frontier model for the plan and review skills"
info "execute stays on sonnet by design; only plan and review elevate"
printf '    %s\n' "1) opus ${DIM}(alias — resolves to Opus 4.8; default)${RESET}" \
                  "2) claude-opus-4-8 ${DIM}(pinned full ID)${RESET}" \
                  "3) fable ${DIM}(if your org enables it)${RESET}" \
                  "4) custom"
MODEL="opus"
if [[ -t 0 ]]; then
  read -rp "  ${CYAN}?${RESET} choice [1]: " c || c=""
  case "${c:-1}" in 1|"") MODEL="opus";; 2) MODEL="claude-opus-4-8";; 3) MODEL="fable";; 4) read -rp "  ${CYAN}?${RESET} model: " MODEL;; *) warn "using default"; MODEL="opus";; esac
else info "non-interactive — using default"; fi
[[ "$MODEL" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { err "invalid model: ${MODEL}"; exit 1; }
ok "plan and review will run on: ${BOLD}${MODEL}${RESET}"

step "4/6 Install skills and agents"
mkdir -p "${CLAUDE_HOME}/skills" "${CLAUDE_HOME}/agents"
NEW_DIRS=""
[[ -d "${CLAUDE_HOME}/skills" && -d "${CLAUDE_HOME}/agents" ]] || NEW_DIRS=1
existing=(); for a in "${AGENTS[@]}"; do [[ -f "${CLAUDE_HOME}/agents/${a}.md" ]] && existing+=("${a}.md"); done
if (( ${#existing[@]} )); then
  B="${CLAUDE_HOME}/agentmaster-backup-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$B"
  for f in "${existing[@]}"; do cp "${CLAUDE_HOME}/agents/${f}" "$B/"; done
  warn "backed up ${#existing[@]} existing agent file(s) to ${B#"$HOME"/}"
fi
for s in "${SKILLS[@]}"; do rm -rf "${CLAUDE_HOME}/skills/${s}"; cp -r "${SCRIPT_DIR}/skills/${s}" "${CLAUDE_HOME}/skills/"; done
for a in "${AGENTS[@]}"; do cp "${SCRIPT_DIR}/agents/${a}.md" "${CLAUDE_HOME}/agents/"; done
for s in agentmaster-plan agentmaster-review; do
  sed -i.bak "s|^model: .*$|model: ${MODEL}  # set by install-claude.sh|" "${CLAUDE_HOME}/skills/${s}/SKILL.md"
  rm -f "${CLAUDE_HOME}/skills/${s}/SKILL.md.bak"
done
ok "installed 3 skills (plan/review on ${MODEL}) and 5 agents"
legacy=(); for f in delegated-planning delegated-review delegated-execution; do
  [[ -d "${CLAUDE_HOME}/skills/${f}" ]] && legacy+=("${CLAUDE_HOME}/skills/${f}"); done
if (( ${#legacy[@]} )); then
  warn "legacy delegated-* skills from a pre-rebrand install found"
  if ask "remove them?" Y; then rm -rf "${legacy[@]}"; ok "removed ${#legacy[@]} legacy skill(s)"; fi
fi

step "5/6 Hook layer"
mkdir -p "${CLAUDE_HOME}/agentmaster/hooks"
cp "${SCRIPT_DIR}"/hooks/*.sh "${CLAUDE_HOME}/agentmaster/hooks/"
chmod +x "${CLAUDE_HOME}/agentmaster/hooks/"*.sh
SETTINGS="${CLAUDE_HOME}/settings.json"
[[ -f "$SETTINGS" ]] && cp "$SETTINGS" "${SETTINGS}.agentmaster-backup-$(date +%s)" && info "settings.json backed up"
CLAUDE_HOME="$CLAUDE_HOME" python3 - <<'PY'
import json, os, pathlib
home = os.environ["CLAUDE_HOME"]
sp = pathlib.Path(home) / "settings.json"
s = json.loads(sp.read_text()) if sp.exists() else {}
hooks = s.setdefault("hooks", {})
hd = home + "/agentmaster/hooks"
roster = "^(scout|code-analyst|plan-critic|implementer|Explore)$"
def cmd(name): return {"type": "command", "command": f"{hd}/{name}"}
ours = {
  "SubagentStart": [{"matcher": roster, "hooks": [cmd("subagent-start.sh")]}],
  "SubagentStop":  [{"matcher": roster, "hooks": [cmd("telemetry.sh")]}],
  "PreToolUse":    [{"matcher": "^(Agent|Task)$", "hooks": [cmd("dispatch-guard.sh")]}],
  "PreCompact":    [{"hooks": [cmd("precompact-snapshot.sh")]}],
  "SessionStart":  [{"hooks": [cmd("session-context.sh")]}],
}
for ev, entries in ours.items():
    lst = hooks.setdefault(ev, [])
    lst[:] = [e for e in lst if not any("agentmaster/hooks" in h.get("command", "")
              for h in e.get("hooks", []))]
    lst.extend(entries)
sp.write_text(json.dumps(s, indent=2) + "\n")
print(f"  wired 5 hook events into {sp}")
PY
ok "hook layer installed (idempotent — re-running replaces agentmaster entries only)"

step "6/6 Done — next steps"
info "restart Claude Code if ~/.claude/skills or ~/.claude/agents were new this session"
info "run /hooks to confirm the five events; hooked skills prompt once for approval on first use"
info "/agentmaster-plan <task> — the pipeline; --lite for the proportionate path"
info "AGENTMASTER_HOOK_DEBUG=1 dumps hook payloads to .agentmaster/hook-debug.jsonl if telemetry lines come up empty"
info "./telemetry-report.sh summarizes .agentmaster/telemetry.md after real runs"
printf '%s\n' "${GREEN}${BOLD}Setup complete.${RESET}"
