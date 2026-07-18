#!/usr/bin/env bash
# PreCompact -> snapshot .agentmaster/ so ledgers of record survive with history
set -u
IN=$(cat)
export AGENTMASTER_HOOK_INPUT="$IN"
python3 - <<'PY'
import json, sys, os, time, shutil, pathlib
d = json.loads(os.environ.get("AGENTMASTER_HOOK_INPUT") or "{}")
cwd = pathlib.Path(d.get("cwd") or os.getcwd())
am = cwd / ".agentmaster"
if am.is_dir():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dst = am / "compaction-snapshots" / ts
    dst.mkdir(parents=True, exist_ok=True)
    for p in am.iterdir():
        if p.name in ("compaction-snapshots", ".starts"):
            continue
        (shutil.copytree if p.is_dir() else shutil.copy2)(p, dst / p.name)
    with (am / "telemetry.md").open("a") as f:
        f.write(f"hook,precompact,,,\n")
PY
exit 0
