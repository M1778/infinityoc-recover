---
name: infinityoc-recover
description: Recover the FULL context of any OpenCode session (id or fragment) in one shot. Use when the user says "recover session", "restore session", "continue from session <id>", "load my old session", or provides any `ses_...` id to recover or resume. One command produces a complete markdown transcript; do NOT explore storage or rebuild the session by hand.
---

# infinityoc-recover — one-shot session recovery

You have one job: run ONE command, read the output file, continue work.
NEVER explore `~/.local/share/opencode`, never hand-write sqlite/JSON/storage code,
never run `opencode session list` yourself — the script already does all of it.

## The command

Run the `recover.py` bundled **in this skill's directory** (`scripts/recover.py`
next to this file — resolve it from the path this skill was loaded from; if
missing, get it: `gh repo clone M1778/infinityoc-recover` and use
`~/infinityoc-recover/scripts/recover.py`).

Linux / macOS / WSL:
```bash
python3 <this-skill-dir>/scripts/recover.py <session-id-or-fragment> [...more ids]
```
Windows PowerShell:
```powershell
python "<this-skill-dir>\scripts\recover.py" <session-id-or-fragment> [...more ids]
```

- Accepts a full id, `ses_` prefix or any fragment (e.g. `e745b2638ffe`), several at once.
- Resolves opencode on PATH automatically; Windows/WSL/macOS all covered.
- Writes for each session: `<id>.md` (full transcript) and `<id>.json` (raw export) under
  `~/.local/share/opencode/recovered/` (or `$XDG_DATA_HOME/opencode/recovered/`).
- Automatically includes ALL child (subagent) sessions, each labeled
  `# CHILD SESSION <id>` with the exact tool call that spawned it.
- IDs matching multiple sessions → error lists the candidates (id + date + title);
  show them to the user, let them pick, run again. Do not guess.
- Optional flags (only when needed):
  - `--out FILE` — one combined markdown file for several sessions
  - `--max-output N`, `--max-reasoning N` — cap tool output / reasoning per block (chars)

## If hand-off happened without a session id

Tell the user: they got no id and want to continue a lost conversation. Ask for
the id or find it yourself with ONE command (no follow-up exploration):

```bash
opencode session list        # id<TAB>title<TAB>date  — one line per session
```

## After running — limits of recovered data and how to read it

- Trust the transcript for: user intent, decisions, edits made, tool calls, all
  assistant conclusions, acceptance criteria, in-flight work state.
- Do not re-verify every tool result as "done": treat completed steps as done.
- If the transcript references child sessions (a `subagent` call result) they
  are already appended; find them by searching `# CHILD SESSION` with grep.
- Big session? Read: `tail` the transcript first (newest context matters most),
  then fill earlier gaps front-to-back. .json sidecars are byte-perfect raw
  exports — only needed when exact tool-output fidelity matters (rare).
- The md can be large (tool outputs kept by default). Cap with
  `--max-output 4000 --max-reasoning 1000` if your context window is tight.

## Rules

1. Run the script BEFORE replying anything substantive. One command. No forks.
2. If the script prints an error (candidates list, empty export), relay it —
   do not improvise a replacement recovery method.
3. If the user asked to "continue" that session: after reading the transcript,
   state in one line what state was recovered, then continue naturally — do
   not re-ask what the transcript already answers.
