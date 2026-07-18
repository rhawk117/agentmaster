#!/usr/bin/env bash
# install-copilot.sh — install the agentmaster system into GitHub Copilot CLI (user scope).
# Run from anywhere inside the bundle; tested for Git Bash / WSL / Linux / macOS.
set -euo pipefail

# ---------- colors ----------
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

# ask <prompt> <default Y|N> -> returns 0 for yes
ask() {
  local prompt="$1" default="${2:-Y}" reply hint
  [[ "$default" == "Y" ]] && hint="[Y/n]" || hint="[y/N]"
  if [[ ! -t 0 ]]; then
    info "non-interactive shell — assuming '${default}' for: ${prompt}"
    [[ "$default" == "Y" ]]; return
  fi
  read -rp "  ${CYAN}?${RESET} ${prompt} ${hint} " reply || reply=""
  reply="${reply:-$default}"
  [[ "$reply" =~ ^[Yy] ]]
}

# ---------- locate sources ----------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
SRC="${SCRIPT_DIR}/copilot/agents"
COPILOT_HOME="${COPILOT_CONFIG_DIR:-$HOME/.copilot}"
DEST="${COPILOT_HOME}/agents"
AGENTS=(scout code-analyst plan-critic implementer agentmaster-plan agentmaster-review agentmaster-execute)
HOOK_SCRIPTS=(agent-telemetry-pre.sh agent-telemetry-post.sh git-guard.sh session-context.sh)
COORDINATORS=(agentmaster-plan agentmaster-review agentmaster-execute)
SKILLS=(agentmaster-plan agentmaster-execute agentmaster-review)
SKILL_SRC="${SCRIPT_DIR}/copilot/skills"
SKILL_DEST="${COPILOT_HOME}/skills"

printf '%s\n' "${BOLD}agentmaster — GitHub Copilot installer${RESET}"
printf '%s\n' "${DIM}coordinators reason and delegate; workers gather, implement, and stay cheap${RESET}"
echo

step "1/6 Preflight"
if git rev-parse --is-inside-work-tree &>/dev/null; then
  ok "running inside a git repository ($(git rev-parse --show-toplevel 2>/dev/null || echo '?'))"
else
  warn "not inside a git repository — continuing; agents install user-scoped so this is fine"
fi
for a in "${AGENTS[@]}"; do
  [[ -f "${SRC}/${a}.agent.md" ]] || { err "missing ${SRC}/${a}.agent.md — run this script from the unpacked bundle"; exit 1; }
done
for sk in "${SKILLS[@]}"; do
  [[ -f "${SKILL_SRC}/${sk}/SKILL.md" ]] || { err "missing copilot/skills/${sk}/SKILL.md — run this script from the unpacked bundle"; exit 1; }
done
ok "all 7 agent files and 3 skills present in the bundle"
if command -v copilot &>/dev/null; then
  ok "copilot CLI found: $(command -v copilot)"
  HAVE_CLI=1
else
  warn "copilot CLI not on PATH — plugin checks fall back to the filesystem; agents still install"
  HAVE_CLI=0
fi

step "2/6 Superpowers skills"
SUPERPOWERS=0
if [[ "$HAVE_CLI" == 1 ]] && copilot plugin list 2>/dev/null | grep -qi superpowers; then
  SUPERPOWERS=1
elif compgen -G "${COPILOT_HOME}/installed-plugins/*superpowers*" >/dev/null; then
  SUPERPOWERS=1
fi
if [[ "$SUPERPOWERS" == 1 ]]; then
  ok "superpowers detected — brainstorming / writing-plans / executing-plans will be used"
else
  warn "superpowers not detected"
  info "the planning coordinator uses its skills for brainstorming and plan formalization"
  if ask "install the superpowers plugin now?" Y; then
    if [[ "$HAVE_CLI" == 1 ]]; then
      copilot plugin marketplace list 2>/dev/null | grep -qi "superpowers-marketplace" \
        || copilot plugin marketplace add obra/superpowers-marketplace
      if copilot plugin install superpowers@superpowers-marketplace; then
        ok "superpowers installed"
        SUPERPOWERS=1
      else
        err "install failed — browse the marketplace and install manually:"
        info "copilot plugin marketplace browse superpowers-marketplace"
      fi
    else
      err "copilot CLI unavailable — install manually once it is:"
      info "copilot plugin marketplace add obra/superpowers-marketplace"
      info "copilot plugin install superpowers@superpowers-marketplace"
    fi
  else
    warn "skipped — note that superpowers is a documented requirement of the pipeline;"
    warn "plan formalization falls back to inline structure until it is installed"
  fi
fi

step "3/6 Frontier reasoning model for the coordinators"
info "availability is governed by your org's Copilot policy — verify with /model after install"
printf '    %s\n' "1) claude-opus-4.8   ${DIM}(default — frontier reasoning)${RESET}" \
                  "2) claude-sonnet-4.6 ${DIM}(budget alternative)${RESET}" \
                  "3) custom slug"
MODEL="claude-opus-4.8"
if [[ -t 0 ]]; then
  read -rp "  ${CYAN}?${RESET} choice [1]: " choice || choice=""
  case "${choice:-1}" in
    1|"") MODEL="claude-opus-4.8" ;;
    2)    MODEL="claude-sonnet-4.6" ;;
    3)    read -rp "  ${CYAN}?${RESET} model slug: " MODEL ;;
    *)    warn "unrecognized choice — using default"; MODEL="claude-opus-4.8" ;;
  esac
else
  info "non-interactive shell — using default"
fi
[[ "$MODEL" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { err "invalid model slug: ${MODEL}"; exit 1; }
ok "coordinators will run on: ${BOLD}${MODEL}${RESET}"
info "workers keep their cheap pins (claude-haiku-4.5 / claude-sonnet-4.6) — edit ${DEST#"$HOME"/}/*.agent.md to change"

step "4/6 Install agents and skills"
mkdir -p "$DEST"
existing=()
for a in "${AGENTS[@]}"; do [[ -f "${DEST}/${a}.agent.md" ]] && existing+=("${a}.agent.md"); done
if (( ${#existing[@]} )); then
  BACKUP="${COPILOT_HOME}/agents-backup-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$BACKUP"
  for f in "${existing[@]}"; do cp "${DEST}/${f}" "${BACKUP}/"; done
  warn "backed up ${#existing[@]} existing file(s) to ${BACKUP#"$HOME"/}"
fi
for a in "${AGENTS[@]}"; do cp "${SRC}/${a}.agent.md" "${DEST}/"; done
for c in "${COORDINATORS[@]}"; do
  sed -i.sedbak "s/^model: .*$/model: ${MODEL}/" "${DEST}/${c}.agent.md"
  rm -f "${DEST}/${c}.agent.md.sedbak"
done
ok "installed 7 agents to ${DEST#"$HOME"/} (coordinators pinned to ${MODEL})"
mkdir -p "$SKILL_DEST"
for sk in "${SKILLS[@]}"; do
  rm -rf "${SKILL_DEST:?}/${sk}"
  cp -r "${SKILL_SRC}/${sk}" "${SKILL_DEST}/"
done
ok "installed 3 router skills to ${SKILL_DEST#"$HOME"/} (they delegate to the coordinator agents)"

# (stray Claude Code SKILL.md variants are handled by the router-skill install
#  above, which overwrites same-named skill dirs with the thin routers)

step "5/6 Hook layer"
HOOK_SRC="${SCRIPT_DIR}/copilot/hooks"
if [[ -d "$HOOK_SRC" ]]; then
  HOOK_DEST="${COPILOT_HOME}/agentmaster-hooks"
  mkdir -p "$HOOK_DEST" "${COPILOT_HOME}/hooks"
  for h in "${HOOK_SCRIPTS[@]}"; do cp "${HOOK_SRC}/${h}" "$HOOK_DEST/"; done
  chmod +x "$HOOK_DEST"/*.sh
  GUARD=1
  if ask "enable the git-guard hook? (blocks write git for ALL Copilot sessions; AGENTMASTER_GIT_GUARD=off disables)" Y; then GUARD=1; else GUARD=0; fi
  {
    echo '{'
    echo '  "version": 1,'
    echo '  "hooks": {'
    echo '    "preToolUse": ['
    echo "      { \"type\": \"command\", \"bash\": \"${HOOK_DEST}/agent-telemetry-pre.sh\", \"timeoutSec\": 5 }$([[ $GUARD == 1 ]] && echo ',')"
    if [[ $GUARD == 1 ]]; then echo "      { \"type\": \"command\", \"bash\": \"${HOOK_DEST}/git-guard.sh\", \"timeoutSec\": 5 }"; fi
    echo '    ],'
    echo "    \"postToolUse\": [ { \"type\": \"command\", \"bash\": \"${HOOK_DEST}/agent-telemetry-post.sh\", \"timeoutSec\": 5 } ],"
    echo "    \"sessionStart\": [ { \"type\": \"command\", \"bash\": \"${HOOK_DEST}/session-context.sh\", \"timeoutSec\": 5 } ]"
    echo '  }'
    echo '}'
  } > "${COPILOT_HOME}/hooks/agentmaster.json"
  python3 -c "import json;json.load(open('${COPILOT_HOME}/hooks/agentmaster.json'))" 2>/dev/null     && ok "hook layer written to hooks/agentmaster.json (own file — your other hook files untouched)"     || err "generated hook JSON failed to parse — report this"
  info "restart copilot to load hooks; verify git-guard with a throwaway 'run git commit' ask"
  info "telemetry lines carry wall-clock only — premium-request spend stays in /usage"
else
  warn "hooks/ not found in bundle — skipping hook layer"
fi

step "6/6 Done — next steps"
info "start a fresh 'copilot' session (a running one won't rescan a new agents directory)"
info "/model   — confirm '${MODEL}' and the worker slugs are enabled for your org; edit files if not"
info "/agent   — agentmaster-plan and agentmaster-review should appear; the 4 workers should not"
info "smoke test: select agentmaster-plan, hand it something trivial, and confirm it dispatches"
info "a scout on the cheap model instead of reading files itself"
printf '%s\n' "${GREEN}${BOLD}Setup complete.${RESET}"
