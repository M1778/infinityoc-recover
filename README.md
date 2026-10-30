# infinityoc-recover

One-shot recovery of the **full context** of an OpenCode session — from a session
id or even a fragment. One command, a complete markdown transcript, zero
context-window wasted on figuring out *how* to recover.

Includes every user message, assistant text and reasoning, and every tool call
with its input and output — plus all **child (subagent) sessions**, each labeled
with the exact tool call that spawned it.

## How it works

OpenCode ships `opencode session export <id>` (full JSON from its SQLite store).
This skill wraps it (`scripts/recover.py`, Python 3 stdlib only):

1. resolves the id (full id, `ses_` prefix, or fragment — DB lookup, CLI fallback)
2. exports the session **to a file** (opencode caps piped stdout at 256 KiB — a
   real file redirect is not capped)
3. renders a compact transcript + saves the raw export `.json` beside it
4. auto-follows child sessions found in `session_v2.parent_id` and referenced by
   `subagent`/`task` tool calls

Output goes to `~/.local/share/opencode/recovered/` (respects
`$XDG_DATA_HOME`; falls back to the system temp dir if no data dir exists).

## Install

Any of:

```bash
# 1) opencode global skill (recommended) — works in every project
~/.config/opencode/skills  # target dir
git clone https://github.com/M1778/infinityoc-recover
cp -r infinityoc-recover   ~/.config/opencode/skills/
```

…or run the installer:

```bash
git clone https://github.com/M1778/infinityoc-recover
cd infinityoc-recover
./install.sh          # macOS / Linux / WSL
```

Windows PowerShell:

```powershell
git clone https://github.com/M1778/infinityoc-recover
cd infinityoc-recover
.\install.ps1
```

Requires only `python3` (or `python` on Windows) and `opencode` on PATH.

No-install one-shot (script served over HTTPS):

```bash
curl -fsSL https://raw.githubusercontent.com/M1778/infinityoc-recover/main/scripts/recover.py | python3 - <session-id>
```

## Use

```bash
python3 .../scripts/recover.py e745b2638ffe        # full id, ses_ prefix or fragment
python3 .../scripts/recover.py <id1> <id2> --out combined.md
python3 .../scripts/recover.py <id> --max-output 4000 --max-reasoning 1000
python3 .../scripts/recover.py <id> --no-children
```

Then read the produced `<id>.md`. Agents: pair the command with the bundled
`SKILL.md` so the flow is automatic ("recover session <id>").

## Flags

| flag | meaning |
|------|---------|
| `--out FILE` | write everything into one markdown file |
| `--max-output N` | cap each tool input/output block (0 = unlimited) |
| `--max-reasoning N` | cap each reasoning block (0 = unlimited) |
| `--no-children` | skip child/subagent sessions |
| `--plain` | print the transcript instead of writing files |

## Notes

- Multiple-id fragments are resolved against stored sessions; ambiguous ones
  abort with the candidate list rather than guessing.
- Exports that OpenCode itself truncated are marked in the transcript
  (`[output had already been truncated…]`); the `.json` sidecar is the
  byte-perfect raw export.
- Idle/system messages (`type: idle`, step markers, snapshots) are skipped.
- No plugin/npm package: OpenCode picks the skill up straight from the skills
  directory — nothing to publish beyond this repo.
