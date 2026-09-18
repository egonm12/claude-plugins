# delegation-policy

Keeps the main Claude thread in an orchestrator role. It pushes work to subagents, blocks Fable subagents, and holds subagents to verified reporting.

## What it does

| Hook | Event | Behaviour |
|---|---|---|
| Model gate | PreToolUse on `Agent` or `Task` | Blocks any subagent that asks for Fable. Warns when the model cannot be resolved. |
| Orchestrator nudge | UserPromptSubmit | One short reminder per turn to delegate and to state a model. |
| Protocol loader | SessionStart, PreCompact | Loads the full protocol once per session and again before compaction. |
| Report gate | SubagentStop | Blocks a subagent that states findings with no evidence and no uncertainty label. |

It also ships a `verifying-worker` agent whose system prompt carries the verification protocol.

## The model rule

Deny what the hook can see is off policy. Warn about what it cannot resolve.

- `model: "fable"` is denied. The call fails with exit code 2 and Claude retries.
- `model: "opus"`, `"sonnet"` and `"haiku"` pass silently.
- A missing `model` passes with a warning. The effective model comes from the agent definition or the configured default, and the hook cannot read either.
- `subagent_type: "fork"` passes with a warning. A fork ignores the model override and runs on the session model, which the hook cannot read.

### Why forks are warned and not blocked

A fork keeps its tool output out of the main thread, so it does save context. Its cost is a large input prompt, and that is mostly cache reads. The one real gap is that a fork inherits the session model. If the session itself runs on Fable, its forks are Fable subagents and this hook cannot tell. Keep the session on Opus or Sonnet and the gap closes.

## How the delegation instruction reaches Claude

Two paths, and the second is the stronger one.

The UserPromptSubmit reminder nudges the current session. It is advisory and costs tokens every turn.

`.apm/instructions/delegation.instructions.md` compiles into `AGENTS.md` and `CLAUDE.md` in consuming projects. That is a standing instruction Claude reads as project policy, not a per-turn hint. If you only keep one, keep this one.

## Verify the gate actually fires

Confirmed on 2026-09-13: this build sends `tool_name` as `Agent`. A denied call surfaces as `PreToolUse:Agent hook error`. The matcher still accepts `Agent|Task` as cheap insurance for other builds, but only `Agent` is exercised here.

To re-check on a different build, or to see every field the hook receives:

```bash
export DELEGATION_POLICY_DEBUG=/tmp/agent-hook.jsonl
# restart Claude Code, spawn one subagent, then:
jq -r '.tool_name' /tmp/agent-hook.jsonl
```

The same capture shows every field the hook receives. If a session model field turns out to be present, the fork case can become a hard block instead of a warning.

## Install

Add the plugin from the `egon-local` marketplace, then restart Claude Code. Hooks load at session start, so a restart is required.

## Turn it off

Set `DELEGATION_POLICY_OFF=1` in the environment to disable every hook for that session.

## Debug the payload

Set `DELEGATION_POLICY_DEBUG=/tmp/agent-hook.jsonl` to append the real hook payload on each `Agent` call. Use it to see which fields Claude Code actually sends. If a session model field turns out to be present, the fork case can be made deterministic instead of advisory.

## Component status

Verified live on 2026-09-13:

| Component | Status |
|---|---|
| PreToolUse model gate | Confirmed. A Fable call was denied, surfaced as `PreToolUse:Agent hook error`. |
| UserPromptSubmit nudge | Confirmed. Fires on every turn. |
| SessionStart loader | Confirmed. Fired on session resume. |
| SubagentStop report gate | **Unconfirmed.** See below. |

### The SubagentStop gate is unconfirmed

It is a prompt hook, so it runs through the hook evaluator API rather than a shell. An approving prompt hook prints nothing, so "approved" and "never ran" look identical from outside.

A prompt Stop hook in a different session on this machine failed with `Hook evaluator API error: There's an issue with the selected model (sonnet)`. This gate uses the same evaluator, so it may fail the same way. Note that Sonnet subagents themselves run fine, so the evaluator resolves a different model than the Agent tool does.

To settle it, restart with `claude --debug` and spawn one subagent. Debug output shows prompt-hook evaluation and any evaluator error directly.

If it does error, remove the `SubagentStop` block from `hooks/hooks.json`. Nothing is lost that matters: `agents/verifying-worker.md` and `references/delegation-protocol.md` already carry the verification protocol, and a live subagent returned a fully evidence-cited report with explicit "Unverified" and "Could not check" sections. The hook was always the redundant belt, not the braces.

## Known costs

- The UserPromptSubmit reminder adds a few lines of context on every turn. That works slightly against the context saving, so it is kept short on purpose.
- The SubagentStop gate is a prompt hook, so it costs one model call every time a subagent finishes. With wide fan-out this adds up. Remove that hook from `hooks/hooks.json` if the cost outweighs the benefit for your use.
- The SubagentStop gate applies to every subagent in the workspace, not only `verifying-worker`. Agents that return ranked file lists or structured findings are explicitly approved, and a loop guard stops any subagent being blocked twice. Watch the first few sessions anyway.

## Testing

```bash
echo '{"tool_name":"Agent","tool_input":{"model":"fable","description":"x"}}' \
  | bash hooks/scripts/agent-model-gate.sh; echo "exit=$?"
```

Expect exit code 2 and a message naming the allowed models.

Tested offline: the three bash scripts across nine input shapes, both tool names, the off switch, the debug capture, and the fallback when `CLAUDE_PLUGIN_ROOT` is unset. Not tested offline: the SubagentStop prompt hook, and whether the hooks fire at all. Hooks load at session start, so that needs a restart and `claude --debug`.
