# Spawn ntm Workers

Reference for orchestrator agents delegating work to parallel Claude sessions via ntm + agent-mail.

## Orchestrator Workflow

The full lifecycle for delegating work:

1. **Register** — controller registers with agent-mail at session start
2. **Spawn with worktrees** — `ntm spawn kerf --cc=N --worktrees` for implementers, `ntm add kerf --cc=N` for reviewers (paired on same worktree)
3. **Wait for ready** — poll `ntm activity` until workers show WAITING
4. **Send ONE bead** — implementer gets the bead prompt (never chain multiple)
5. **Poll inbox** — implementer signals DONE via agent-mail
6. **Trigger review** — controller sends reviewer a review prompt for the same worktree
7. **Review loop** — reviewer ↔ implementer iterate via agent-mail until APPROVED (controller monitors, does not participate)
8. **Merge** — `ntm worktrees merge cc_N` to bring approved work to main
9. **Clear & reset** — `/clear` both agents, reset worktree to main, send next bead

See `implement-beads.md` for the full procedure with prompt templates.

## Agent-Mail Setup

The orchestrator registers via the HTTP API (MCP tools require session restart to load):

```bash
# Ensure project exists (once per session)
curl -s -X POST http://127.0.0.1:8765/mcp/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ensure_project","arguments":{"human_key":"/Users/gb/github/kerf"}}}'

# Register orchestrator (once per session)
curl -s -X POST http://127.0.0.1:8765/mcp/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"register_agent","arguments":{"project_key":"/Users/gb/github/kerf","program":"claude-code","model":"opus-4.6","task_description":"Orchestrator"}}}'
# Returns: {"name":"SomeAgent", ...} — this is your agent name for inbox checks
```

## Poll for Completion

Use the `am` CLI — cleaner and faster than raw curl:

```bash
# Check inbox (--rate-limit 0 disables the default 120s cooldown)
am check-inbox --agent YOUR_AGENT_NAME --project /Users/gb/github/kerf --rate-limit 0 --json

# Filter for completion messages in a script
am check-inbox --agent YOUR_AGENT_NAME --project /Users/gb/github/kerf --rate-limit 0 --json \
  | python3 -c "import sys,json; d=json.load(sys.stdin); [print(f'{m[\"from\"]}: {m[\"subject\"]}') for m in d['messages'] if 'DONE' in m.get('subject','') or 'FIX' in m.get('subject','') or 'REVIEW' in m.get('subject','')]"
```

## Monitoring Workers

```bash
# Agent states (WAITING = idle, ready for work)
ntm activity kerf

# Capture recent output from specific panes (reliable)
ntm logs kerf --panes=2,3,4 --limit=30

# Dump full pane output to file
ntm copy kerf:2 --output /tmp/pane2.txt

# Stream live output
ntm logs kerf --follow
```

**Do NOT use `tmux capture-pane` directly** — it returns stale buffer snapshots and will mislead you about worker state. Use `ntm logs` instead.

## Worker Prompt Template

Every worker prompt MUST include this agent-mail block at the end:

```markdown
## When Done

After completing your task:

1. Use your agent-mail MCP tools:
   - Call `ensure_project` with human_key `/Users/gb/github/kerf`
   - Call `register_agent` with project_key `/Users/gb/github/kerf`, program `claude-code`, model `sonnet-4.6`
   - Call `send_message` with:
     - project_key: `/Users/gb/github/kerf`
     - sender_name: (your registered agent name)
     - to: ["ORCHESTRATOR_NAME"]
     - subject: `DONE: <filename>`
     - body_md: Summary of what you wrote and any decisions/ambiguities encountered

2. Do NOT exit or quit — wait for further instructions.
```

Replace `ORCHESTRATOR_NAME` with the orchestrator's registered agent-mail name.

## ntm Commands

```bash
# Add N workers to the kerf session
ntm add kerf --cc=N

# Check agent states (wait for WAITING before sending prompts)
ntm activity kerf

# Send a task to a specific pane
ntm send kerf --pane=N "your prompt here"

# Send a task from a file
ntm send kerf --pane=N --file path/to/prompt.md

# Clear a worker's context for reuse
ntm send kerf --pane=N "/clear"
```

## Resetting Workers Between Batches

Two options, from lightest to heaviest:

1. **`/clear` (light reset)** — clears conversation context, keeps MCP connection. Good for sending sequential tasks of similar type.
   ```bash
   ntm send kerf --pane=N "/clear"
   ```

2. **Kill + re-add (full reset)** — fresh claude process, fresh MCP. Use between unrelated tasks or when MCP is flaky.
   ```bash
   # Get pane IDs
   tmux list-panes -t kerf -F "#{pane_index} #{pane_id}"
   # Kill worker panes (NOT pane 1 — that's the orchestrator/user)
   tmux kill-pane -t %PANE_ID
   # Add fresh workers
   ntm add kerf --cc=N
   ```

**WARNING**: `ntm respawn` does NOT reliably restart claude — it kills the process but leaves an empty terminal. Use kill + re-add instead.

## Gotchas

- Do NOT use `--prompt` at spawn time (known bug). Always spawn first, wait for WAITING, then `ntm send`.
- `ntm add` adds N panes to existing count. 3 panes + `add --cc=4` = 7 total.
- Check pane numbers with `ntm activity kerf` — they may not start at 1.
- For model selection: `ntm add kerf --cc=1:opus` or `--cc=1:sonnet`
- Workers need `.mcp.json` in the project root to access agent-mail MCP tools.
- Orchestrator uses HTTP API (curl) or `am` CLI, not MCP tools directly (MCP requires session restart to load).
- `ntm respawn` is unreliable — use kill + re-add for full resets.
- `tmux capture-pane` returns stale snapshots — use `ntm logs` for reliable output capture.
