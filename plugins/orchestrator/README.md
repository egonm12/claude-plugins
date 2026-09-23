# orchestrator

Keeps the main agent thread in the orchestrator role. The orchestrator delegates the reading and searching to workers, keeps the judgement, and checks what comes back. The package blocks Fable workers, warns when a worker model is missing or unknown, and holds workers to verified reporting.

This package uses the terms orchestrator, worker and delegation as defined in the repository's [CONTEXT.md](../../CONTEXT.md). In Claude Code, a worker runs as a subagent.

## Install in Claude Code

You need `bash` and `jq` on the path. Without `jq`, the model gate runs in reduced mode. It blocks any Agent call that mentions Fable, checks nothing else, and tells you so.

1. Add the marketplace and install the package:
   ```
   /plugin marketplace add egonm12/claude-plugins
   /plugin install orchestrator@egonm12-plugins
   ```
2. Restart Claude Code. Hooks load at session start, so the package does nothing until you restart.

Do not also run `apm compile` in a Claude Code project. The SessionStart hook already loads the protocol, so a compiled `CLAUDE.md` loads it a second time. That is harmless, but it wastes context. Compile is for other agents.

### Upgrade from delegation-policy

Version 0.2.0 renamed the package from `delegation-policy`. There are no aliases.

1. `/plugin uninstall delegation-policy@egonm12-plugins`
2. `/plugin marketplace update egonm12-plugins`
3. `/plugin install orchestrator@egonm12-plugins`
4. Restart Claude Code.

Rename `DELEGATION_POLICY_OFF` and `DELEGATION_POLICY_DEBUG` in your shell to `ORCHESTRATOR_OFF` and `ORCHESTRATOR_DEBUG`. The old names do nothing.

## What each agent gets

The orchestration idea works on any agent. Only the enforcement is specific to Claude Code.

| Part | File | Claude Code | Other agents, such as Codex |
|---|---|---|---|
| Model gate | `hooks/scripts/agent-model-gate.sh` | Yes | No |
| Protocol loader | `hooks/scripts/load-protocol.sh` | Yes | No |
| Worker | `agents/verifying-worker.md` | Yes | No |
| Instructions | `.apm/instructions/orchestrator.instructions.md` | Not needed | Yes, through `apm compile` into `AGENTS.md` |

The instructions are tool-neutral. They name no models and no Claude Code tools.

## What it does in Claude Code

| Part | Event | Behaviour |
|---|---|---|
| Model gate | PreToolUse on `Agent` or `Task` | Denies any worker that asks for Fable. Warns Claude when the model is missing, unknown or a fork. |
| Protocol loader | SessionStart | Loads `references/orchestrator-protocol.md` at session start. SessionStart fires again after compaction, so it reloads then too. |
| `verifying-worker` | Agent | Worker for any task. The orchestrator's prompt gives the task, and the worker brings the reporting rules, the report format and the scope rules. |

The worker carries the protocol's four reporting rules word for word.

### Why one worker for any task

The package ships one worker, not one per task type. Tasks come in too many kinds: research, parsing, transforming, implementing, reviewing. Most tasks mix several. What a built-in worker adds is the reporting contract, which holds even when the orchestrator forgets to paste the rules, plus a pinned model. Both apply to every task type.

Version 0.2.0 shipped a separate `implementing-worker`. Version 0.3.0 folded it into `verifying-worker`.

## The model rule

The gate denies what it can see is off policy, and warns about what it cannot resolve.

- **Fable is denied.** This covers `fable`, full IDs such as `claude-fable-5-1`, and any case. The call fails with exit code 2, and Claude retries with another model.
- **Allowed models pass silently.** The default list is `opus`, `sonnet` and `haiku`. Full IDs such as `claude-sonnet-5` also pass.
- **Unknown models pass with a warning.** A typo like `sonet`, or another vendor's model, gets a warning.
- **A missing model passes with a warning.** The effective model then comes from the agent definition or the configured default, and the hook cannot read either.
- **A fork passes with a warning.** A fork ignores the model override and runs on the session model, which the hook cannot read.

Warnings go to Claude through `additionalContext` and to you through `systemMessage`.

To change the allowed list, set `ORCHESTRATOR_MODELS`, for example `ORCHESTRATOR_MODELS=opus,sonnet`. Fable stays denied even if you list it.

### Why forks are warned and not blocked

A fork keeps its tool output out of the main thread, so it does save context. Its cost is a large input prompt, and that is mostly cache reads. The one real gap is that a fork inherits the session model. If the session itself runs on Fable, its forks are Fable workers and the hook cannot tell. Keep the session on Opus or Sonnet and the gap closes.

## Turn it off

Set `ORCHESTRATOR_OFF=1` in the environment to switch off every hook for that session.

## Why there is no report gate

Version 0.1.0 had a SubagentStop prompt hook that blocked worker reports without evidence. Version 0.2.0 removed it, for four reasons:

- It asked the evaluator for the wrong reply format.
- On Claude Code 2.1.271 and later, it read the worker's closing text, not the delivered report.
- It fired for Claude Code's own internal agents too.
- It cost one model call each time a worker stopped, and the off switch could not stop it.

The orchestrator is the quality gate. The protocol tells it to check every report, and the worker carries the reporting rules in its system prompt.

## Why there is no per-turn reminder

Version 0.1.0 also had a UserPromptSubmit hook that repeated a short version of the protocol on every turn. It cost context on every turn, and its model descriptions had drifted from the protocol. SessionStart already loads the full protocol, and reloads it after compaction.

If Claude stops delegating late in long sessions, bring back a one-line reminder that points to the protocol.

## Check that the hooks fire

Confirmed on 2026-09-13, on version 0.1.0: Claude Code sends `tool_name` as `Agent`. A denied call surfaces as `PreToolUse:Agent hook error`. The matcher also accepts `Task` as insurance for other builds, but only `Agent` has been seen live.

To see every field Claude Code sends, set `ORCHESTRATOR_DEBUG` to a file path. The model gate then appends the full hook payload to that file on each `Agent` call.

```bash
export ORCHESTRATOR_DEBUG="$HOME/orchestrator-hook.jsonl"
# restart Claude Code, delegate to one worker, then:
jq -r '.tool_name' "$HOME/orchestrator-hook.jsonl"
```

The capture holds full worker prompts. Keep it out of shared directories such as `/tmp`, and delete it when you are done.

If a session model field turns out to be present, the fork case can become a hard block instead of a warning.

## Component status

| Component | Status |
|---|---|
| Fable deny | Confirmed live on 2026-09-13, on version 0.1.0. |
| Warnings through `additionalContext` | Confirmed live on 2026-09-23, on version 0.2.0. A call without a model put the warning in Claude's context. |
| SessionStart loader at startup and resume | Confirmed live on 2026-09-13, and again on 2026-09-23 on version 0.2.0. |
| SessionStart reload after compaction | Confirmed live on 2026-09-23, on version 0.3.0. After `/compact`, the protocol was back in Claude's context. |

## Known costs

- The protocol adds about 520 words of context at session start and after each compaction.
- A warning adds one short message to Claude's context for that Agent call.

## Testing

```bash
bash plugins/orchestrator/tests/gate.test.sh
```

The test runs offline and needs `bash` and `jq`. It covers:
- the model gate: Fable deny cases, allowed names and full IDs, warnings, bad input, the off switch, the debug capture and reduced mode without `jq`
- JSON validity of `hooks.json` and `plugin.json`
- drift: the worker must carry the protocol's four rules word for word, and the protocol's model table must match the gate's default list
- tool neutrality: the instructions must not name a model

The test does not check whether Claude Code fires the hooks. That needs a restart and `claude --debug`.
