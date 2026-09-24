# orchestrator

Keeps the main agent thread in the orchestrator role. The orchestrator delegates the reading and searching to workers, keeps the judgement, and checks what comes back. The package blocks Fable workers, warns when a worker model is missing or unknown, and holds workers to verified reporting.

This package uses the terms orchestrator, worker and delegation as defined in the repository's [CONTEXT.md](../../CONTEXT.md). In Claude Code, a worker runs as a subagent.

## Install in Claude Code

You need `python3`, version 3.9 or later, on the path. Every hook is one Python entry point with only standard library imports. Set `ORCHESTRATOR_PYTHON` to another interpreter when `python3` is not the one you want. On a Mac without developer tools, `/usr/bin/python3` is a stub that asks to install them, so install Python first or point the variable at one you have.

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
| Hooks: gate, loader, reminder, router | `hooks/hook.py` with the package `hooks/orchestrator_hooks/` | Yes | No |
| Router service | `router/server.py` | Yes, optional | No |
| Worker | `agents/verifying-worker.md` | Yes | No |
| Instructions | `.apm/instructions/orchestrator.instructions.md` | Not needed | Yes, through `apm compile` into `AGENTS.md` |

The instructions are tool-neutral. They name no models and no Claude Code tools.

## What it does in Claude Code

| Part | Event | Behaviour |
|---|---|---|
| Model gate | PreToolUse on `Agent` or `Task` | Denies any worker that asks for Fable. Warns Claude when the model is missing, unknown or a fork. |
| Protocol loader | SessionStart | Loads `references/orchestrator-protocol.md` at session start. SessionStart fires again after compaction, so it reloads then too. |
| Per-turn reminder | UserPromptSubmit | Adds one line before Claude starts on each prompt: delegate the research when it needs more than two exploratory commands or the question is open. It reads that line from the protocol. |
| Delegation hint | UserPromptSubmit | Asks the router whether the prompt needs an investigation. Adds one line only when it does. Needs the router, see below. Skips worker hand-backs and task notices, see below. |
| Exploration counter | PreToolUse on Bash, Read, Grep, Glob, WebFetch, WebSearch | Counts exploratory commands in the main thread per turn. Warns once when the count passes a threshold that the router's verdict sets. |
| Model pick | PreToolUse on `Agent` or `Task` | Picks the model for every worker call from the task text. Claude's own choice stands only when your prompt named that subagent. Needs the router. |
| Router start | SessionStart | Starts the router daemon when it is installed and not running. Restarts a daemon that runs an older plugin version. |
| Turn finaliser | Stop | Writes the turn's outcome to the router log. |
| `verifying-worker` | Agent | Worker for any task. The orchestrator's prompt gives the task, and the worker brings the reporting rules, the report format and the scope rules. |

All hooks run through one entry point, `hooks/hook.py`, called with the event name. Steps that share an event run in one process and produce one output. The gate and the model pick share the Agent call. The reminder and the hint share the prompt. The loader and the daemon start share session start. The worker carries the protocol's four reporting rules word for word. The router steps do nothing until you install the router.

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

With the router installed, the gate runs first and the model pick runs second on the same call. Fable is still denied before the router looks at the call. When the router sets a model, the missing-model and unknown-model warnings are both skipped. The router's own line already says what happened.

### Why forks are warned and not blocked

A fork keeps its tool output out of the main thread, so it does save context. Its cost is a large input prompt, and that is mostly cache reads. The one real gap is that a fork inherits the session model. If the session itself runs on Fable, its forks are Fable workers and the hook cannot tell. Keep the session on Opus or Sonnet and the gap closes.

## Turn it off

Set `ORCHESTRATOR_OFF=1` in the environment to switch off every hook for that session. Set `ORCHESTRATOR_ROUTER_OFF=1` to switch off only the router hooks and keep the gate, the loader and the reminder.

## The router

The router is an optional local classifier that gives the hooks a fast verdict on two questions. Does this prompt need an investigation? Which model tier does this worker task need? It answers in about 100 ms on an Apple M-series chip, with no network call and no Claude tokens. It runs [laya](https://github.com/NandhaKishorM/laya), a 421 million parameter classifier, as a daemon on localhost.

The hooks use the verdict in three advisory ways. Nothing blocks by default.

- **Delegation hint.** When the route verdict is `delegate`, the prompt gets one extra line. It names the verdict, its confidence and the likely tier, and asks Claude to delegate before running commands. Quick prompts get nothing. Close verdicts get nothing either, see below.
- **Exploration counter.** The verdict sets a threshold for exploratory commands in the main thread: 2 after `delegate`, 5 after `self`, 3 otherwise. "Otherwise" covers `skill`, `unsure` and no verdict. When the count passes it, Claude gets one warning for that turn. A wrong verdict only shifts the threshold. Set `ORCHESTRATOR_EXPLORATION_BLOCK=1` to turn the warning into a deny.
- **Model pick.** On every worker call, the router picks `opus`, `sonnet` or `haiku` from the task text. An upgrade to a stronger tier is always set. A downgrade to a weaker tier is set only when the router is confident, see below. Claude's choice stands only when your prompt named that subagent, for example "use the verifying-worker for this". You see the picked model in a system message. Claude gets one line of context only when its own choice was replaced. When the router is down, the call goes through as Claude wrote it.

Every verdict and every outcome goes to an append-only log, so a better classifier can be trained on real sessions later.

### Close verdicts and short follow-ups

The hooks act on the effective route, not always on the router's raw verdict. Two rules decide it.

- **A close verdict counts as unsure.** The router gives a probability for `delegate` and one for `self`. When the two are less than 0.15 apart, the hooks treat the verdict as `unsure`. An unsure turn gets the default threshold of 3 and no hint. One real prompt scored 0.47 for `delegate` and 0.53 for `self`. Before this rule it got the lenient `self` threshold of 5, although it was a clear investigation. Set `ORCHESTRATOR_ROUTE_MARGIN` to change the gap. A slash command is never unsure, because a regex decides it.
- **A short follow-up keeps the previous route.** A prompt of 3 words or fewer, such as "continue", "yes do it" or "go on", takes the effective route and tier of the turn before. So "continue" after an investigation gets the `delegate` threshold and the hint again. "yes, branch and open a PR" has 6 words and gets its own verdict. The first prompt of a session never carries. A slash command never carries either. A turn after a down router has no route to pass on. Set `ORCHESTRATOR_CARRY_WORDS` to change the word limit, or to `0` to switch this off.

The router still judges every prompt. The log keeps its raw verdict next to the effective route, the gap between the two probabilities, and the turn a follow-up took its route from.

### Worker hand-backs and task notices are not user prompts

Claude Code delivers a subagent's report, and a background task notice, through the same UserPromptSubmit event as a real prompt. Their text starts with `<agent-message` or `<task-notification`, after any leading whitespace. The hooks skip these:

- No router call, no new turn, no `prompt` log record, no hint and no reminder line. The hook prints nothing.
- The current turn's state and its counters stay as they are.
- If Stop already finalized the turn, the hook reopens it, so the next Stop writes a fresh `prompt_outcome` for the same turn with the updated counts. A reader of the log takes the last `prompt_outcome` per session and turn as the true one.
- The exploration warning still fires at most once for the turn: reopening only clears the finalized flag, not the `warned` flag.

Before this, a worker hand-back got its own router verdict and hint, started a new turn, and reset the exploration counters mid-task.

### The downgrade guard and the judgement floor

The model pick can now keep a stronger model than the router suggests, so a review never quietly drops to haiku.

- **An upgrade is free.** When the router's tier is stronger than the model Claude gave, the hook always sets it.
- **A downgrade needs confidence.** When the router's tier is weaker than the model Claude gave, the hook sets it only when the gap between the top two tier probabilities is at least `ORCHESTRATOR_TIER_MARGIN`, 0.15 by default. Otherwise Claude's model stands. One real call gave `opus`, and the router's tier probabilities were opus 0.33, sonnet 0.29, haiku 0.38, a gap of 0.04. Before this rule the call dropped to haiku. Now `opus` stays.
- **A judgement task never lands on haiku.** When the description, the subagent type, or the first 200 characters of the worker prompt name review, audit, security, design or similar work, the floor raises a haiku result to sonnet, whether that haiku came from the router or from Claude's own choice.
- Claude's model counts for this comparison only when it is exactly `opus`, `sonnet` or `haiku`, case-insensitive. Anything else, such as a full model ID or another vendor's name, is treated as no model given, and the router's tier is used.
- A subagent your prompt named still keeps Claude's own choice outright, and a fork is still left alone. Both skip the guard and the floor entirely, as before.

The log keeps the gap as `tier_margin`, and the outcome as `reason`: `user_named_subagent`, `fork`, `router_down`, `no_change`, `upgrade`, `downgrade`, `downgrade_blocked`, `judgement_floor` or `no_model_given`.

### The worker model question

The router asks laya one question per worker call. Version 0.5.5 changes that question. The old question asked how much judgement a task needs. The new question asks whether the worker has to work out the approach itself, or whether the task gives it:

- **opus:** open-ended work where the worker must find its own way. Examples: research outside the codebase or in an unfamiliar system, finding the root cause of a failure, designing or splitting a change, or building new tooling.
- **sonnet:** work that follows a path the task lays out. Examples: drafting or reviewing against given criteria or a checklist, taking stock of the current state, comparing two things for parity, or a well-specified edit.
- **haiku:** mechanical work with an obvious answer, such as grepping, listing files, renaming, counting or reformatting.

The evidence comes from 40 worker calls that the author labelled by hand: 22 for sonnet and 18 for opus.

- Claude's own model choice matched the label on 18 of the 40.
- The old question matched on 18 of the 40.
- An offline replay of the new question, with the downgrade guard above, matched on 30 of the 40. It picked a model that was too strong 5 times and too weak 5 times.

Treat the 30 of 40 as optimistic. The new wording was written from the same 40 labels it was tested on. New labels will show the real rate.

Each wording has an id, such as `b-2026-09-24` for this tier question and `a-2026-09-23` for the route question. The router returns the ids with every verdict, and the log keeps them, see below.

### An outdated daemon restarts itself

The daemon keeps running the code it started with. After a plugin update it would keep serving the old question. So the health check names the plugin version the daemon runs, and the session start hook compares it with its own version. When the daemon runs an older version, or names none, the hook restarts it. A daemon that runs a newer version is left alone, so a session that has not reloaded yet never stops the router of a newer version:

- It reads the daemon's process id from the pid file in the data directory.
- It stops that process only when the command line of that process contains `server.py`.
- It waits up to 3 seconds for the port to free, then starts the new daemon without waiting for the model to load.
- It prints one line to say it restarted the daemon.

When the hook cannot confirm the process, it stops nothing. It prints one line that the router is outdated, and how to stop it by hand. It does the same when no new daemon can start, so the old one keeps serving. When the port stays busy after the stop, it prints one line, and the next session starts the new daemon.

### Why the router advises and does not block

Measured on 75 prompts from real sessions, Claude alone delegated 6 of the 29 prompts that needed it. Zero-shot laya flagged 22 of the 29, and wrongly flagged 10 of the 36 quick prompts. On 49 worker calls, Claude named no model on 23. Those numbers make laya a better advisor than the fixed reminder, and not good enough to block on. Two blind labellers agreed on 88 percent of route labels, so there is room to improve with training. The full evaluation is on the branch `prototype/laya-router`.

The confidence values are not calibrated, because the checkpoint ships invalid temperatures. No decision in the package depends on confidence. It is logged for later. The unsure rule uses the gap between the two route probabilities instead. Those probabilities are not calibrated either, so the gap is a setting you can tune.

### Install the router

You need Python 3.10 or later and about 3 GB of disk for the environment and the checkpoint.

```bash
bash ~/.claude/plugins/cache/egonm12-plugins/orchestrator/*/router/install.sh
```

Claude Code installs each plugin version under `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`. The wildcard picks the installed version. From a checkout of this repository, run `bash plugins/orchestrator/router/install.sh` instead. The script creates a Python environment in the plugin data directory, installs laya, and downloads the 842 MB English checkpoint once. The environment lives in the data directory and not under the version path, so it survives a plugin update. Restart Claude Code. The SessionStart hook then starts the daemon and prints one line to say so. The first verdicts arrive after the model has loaded, about 5 to 30 seconds later. Until then, the hooks behave as if the router is not installed.

Check that it runs:

```bash
curl -s http://127.0.0.1:8790/health
curl -s -X POST http://127.0.0.1:8790/route -d '{"text":"why does the login test fail after the refactor?"}'
```

The first command returns the status, the device, the checkpoint and the plugin version. The second returns the route and tier verdicts with probabilities, latency and the wording ids.

### Router settings

All optional, all environment variables.

| Variable | Default | Meaning |
|---|---|---|
| `ORCHESTRATOR_PYTHON` | `python3` | Interpreter that runs the hooks. Applies to every hook, not only the router |
| `ORCHESTRATOR_ROUTER_OFF` | `0` | `1` switches off the router steps and keeps the gate, the loader and the reminder |
| `ORCHESTRATOR_ROUTER_URL` | `http://127.0.0.1:8790` | Where the hooks find the daemon |
| `ORCHESTRATOR_ROUTER_PYTHON` | `<data dir>/router-venv/bin/python` | Interpreter that starts the daemon |
| `ORCHESTRATOR_LAYA_VERSION` | `0.3.11` | laya version that `router/install.sh` installs. Only read by the installer |
| `ORCHESTRATOR_ROUTER_TIMEOUT_MS` | `1500` | How long a hook waits for a verdict |
| `ORCHESTRATOR_THRESHOLD_DELEGATE` | `2` | Exploratory commands allowed after a `delegate` verdict |
| `ORCHESTRATOR_THRESHOLD_SELF` | `5` | Allowed after a `self` verdict |
| `ORCHESTRATOR_THRESHOLD_DEFAULT` | `3` | Allowed after `skill`, an `unsure` verdict, no verdict, or a down router |
| `ORCHESTRATOR_ROUTE_MARGIN` | `0.15` | A verdict whose `delegate` and `self` probabilities are closer than this counts as `unsure`. An invalid value uses the default |
| `ORCHESTRATOR_CARRY_WORDS` | `3` | A prompt with this many words or fewer keeps the previous turn's route and tier. `0` switches this off |
| `ORCHESTRATOR_TIER_MARGIN` | `0.15` | A downgrade from Claude's model applies only when the gap between the top two tier probabilities is at least this. `0` always allows the downgrade. An invalid value uses the default |
| `ORCHESTRATOR_EXPLORATION_BLOCK` | `0` | `1` denies the call instead of warning |
| `ORCHESTRATOR_LOG_OFF` | `0` | `1` stops writing the log |

### Where the data lives

The router keeps everything in the plugin data directory that Claude Code provides through `CLAUDE_PLUGIN_DATA`, with `~/.claude/orchestrator` as the fallback. For a marketplace install that directory is `~/.claude/plugins/data/orchestrator-egonm12-plugins/`. That directory holds the Python environment, one state record per session, the daemon's own log, and the training log `router-log.jsonl`. It is never inside a repository.

The training log holds your prompt texts and the task texts of your worker calls, truncated to 4000 characters. It also holds the router's verdicts and what happened in the turn. Set `ORCHESTRATOR_LOG_OFF=1` if you do not want that recorded. Delete the file to start over.

### What the training log records

The log has five record kinds. Records of one turn share `session_id` and `turn`.

- `prompt`: one per user prompt, with the router's verdict.
- `prompt_outcome`: one per turn, written when the turn ends.
- `agent_call`: one per worker call from the main thread, with the model pick.
- `exploration_warning`: one when the exploration counter warns.
- `agent_result`: one per worker that stops.

Every record has `plugin_version`. It names the plugin version that wrote the record. Use it to compare data from before and after a change.

The verdict in a `prompt` record has `route_wording` and `tier_wording`. The verdict in an `agent_call` record has `tier_wording`. Each names the wording of the question that gave the verdict. Use it to split the data by wording. Records from before version 0.5.5 lack these fields. A router that is down or older gives `null`.

A `prompt_outcome` record has these fields besides the counters:

- `n_edit`: how many times the main thread ran `Edit`, `Write`, `MultiEdit` or `NotebookEdit` in the turn. Edits never count as exploration and never trigger the warning.
- `duration_s`: whole seconds from the prompt to the moment the hooks wrote the outcome.
- `context_tokens_start`: the main thread's context size when the prompt arrived.
- `context_tokens_end`: the main thread's context size when the turn ended.

The hooks read the context size from the session transcript. It is the input tokens of the last assistant message, including cached tokens. The hooks read only the last 512 KB of the transcript. The value is `null` when the transcript is missing or holds no usage. A worker report that reopens a turn keeps the turn's start time and start size.

An `agent_result` record has these fields:

- `agent_id` and `agent_type`: the worker as Claude Code names it. Claude Code also runs internal agents, for example for prompt suggestions. For those, `agent_type` is an empty string, unless the session itself runs as a named agent. Filter on `agent_type` to leave them out.
- `tool_use_id`: the id of the `Agent` call that started the worker. The matching `agent_call` record has the same id. Join on this field. Do not join on the turn, because a background worker can finish in a later turn.
- `model`: the model the worker really ran on, from its own transcript, for example `claude-sonnet-5`. Compare it with `model_set` in the `agent_call` record to check that the router's model choice took effect.
- `duration_s`: seconds from the first to the last line of the worker's transcript, to one decimal.
- `context_tokens_end`: the worker's context size at its last message.
- `report_chars`: the length of the worker's report in characters. For a worker that hands back through `SubagentHandback`, this is the length of the handed-back message.

Any field the hooks cannot read is `null`. `tool_use_id` is also `null` in `agent_call` when Claude Code sends none.

### When the router is down

Every router step fails open when the daemon is not installed, not running, or slow. The hint then prints nothing. The one exception is a short follow-up, which still keeps a `delegate` route from the turn before. The counter uses the default threshold. The model pick leaves the call as it is. The log records `down`. No hook waits longer than the request timeout. The existing gate, loader and reminder do not depend on the router at all.

## Label the router log

The router log shows what the router chose. It does not show what was right. The labelling tool lets you add that by hand.

- `python3 tools/label.py` asks per turn: should this have been delegated? Press d (delegate), s (self), k (skip), u (undo) or q (quit).
- `python3 tools/label.py --workers` asks per worker call: what is the smallest model that would do this well? Press o (opus), s (sonnet) or h (haiku).
- The tool shows unsure turns first. Then it shows turns where the route and the work did not match.
- It saves each answer at once to `labels.jsonl` in the data dir. Undo adds a line, so no answer is lost.
- `--since`, `--session` and `--limit` narrow the items. `--stats` shows how often the router agreed with you. `--export FILE` writes the labelled examples for training.
- The tool reads local files only and sends nothing over the network.

## Why there is no report gate

Version 0.1.0 had a SubagentStop prompt hook that blocked worker reports without evidence. Version 0.2.0 removed it, for four reasons:

- It asked the evaluator for the wrong reply format.
- On Claude Code 2.1.271 and later, it read the worker's closing text, not the delivered report.
- It fired for Claude Code's own internal agents too.
- It cost one model call each time a worker stopped, and the off switch could not stop it.

The orchestrator is the quality gate. The protocol tells it to check every report, and the worker carries the reporting rules in its system prompt.

## Why the per-turn reminder came back

Version 0.1.0 had a UserPromptSubmit hook that repeated a short version of the protocol on every turn. Version 0.2.0 removed it. It cost context on every turn, and its model descriptions had drifted from the protocol.

Without it, Claude stopped delegating. On 2026-09-23, a `/release` session ran 17 tool calls in the main thread and delegated none of them. The question "Any risks before deploying?" alone took about eight calls. They pulled ADR text, memory files, Terraform diffs and live ECS state into the main thread. Three workers in parallel would have kept that out.

Three things caused it:

- The protocol loads once at session start. By the second prompt, many tool results sat between the protocol and the decision.
- Claude judges each command on its own, and one more grep never looks like a broad search.
- The skill's own steps were closer and more concrete than the protocol.

Version 0.4.0 fixes both old problems and the new one:

- The reminder is one line of about 35 words, not a copy of the protocol.
- It reads that line from the protocol, so it cannot drift. The test checks that the protocol has exactly one such line.
- The protocol now gives countable triggers: more than two exploratory commands, an open question, or large output. It also says that research inside a skill still counts as research.

Version 0.5.0 adds the counter hook that this left open. Hook payloads inside a worker carry an `agent_id` field, so the counter can tell the main thread apart from a worker. The router section above describes how the verdict sets the counter's threshold.

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
| Per-turn reminder | Confirmed live on 2026-09-23, on version 0.4.0. It also fires on a skill command such as `/implement`. |
| Python entry point for all hooks | Confirmed live on 2026-09-23, on version 0.5.1. Real sessions wrote prompt, outcome and worker call records to the log. |
| Router: hint, start, finaliser | Confirmed live on 2026-09-23, on version 0.5.1. The session start hook started the daemon, the hint reached Claude, and outcomes were written on Stop and at the next prompt. |
| Exploration counter | Counting confirmed live on 2026-09-23, on version 0.5.1. A warning has not fired live yet. |
| Model pick through `updatedInput` | Confirmed live on 2026-09-23, on version 0.5.2. Claude asked for opus, the router set sonnet, and the worker transcript shows every message on sonnet. |
| Unsure verdicts and carry-over of short follow-ups | Confirmed live on 2026-09-23, on version 0.5.2. A 51 to 49 verdict was logged as unsure, and "Only this one" took the route of the turn before. |
| Worker reports skipped by the prompt hook | Confirmed live on 2026-09-24, on version 0.5.3. No hand-back or task notice reached the log as a prompt. |
| Downgrade guard and judgement floor | Not yet confirmed live. No worker call on version 0.5.3 or later has needed them. |
| Turn outcome: edits, duration, context size | Confirmed live on 2026-09-24, on version 0.5.4. |
| Worker results | Fires live on 2026-09-24, on version 0.5.4, but only for Claude Code's internal agents so far. A result for a real worker has not been seen yet. |
| Worker model question `b-2026-09-24` | Not yet confirmed live. Only an offline replay on 40 labelled calls has tested it, see above. |
| Wording ids in the log | Not yet confirmed live. |
| Restart of an outdated daemon | Not yet confirmed live. The first session on version 0.5.5 should restart the daemon of version 0.5.4. |

## Known costs

- The protocol adds about 650 words of context at session start and after each compaction.
- The reminder adds about 35 words of context on every prompt.
- A warning adds one short message to Claude's context for that Agent call.
- Each hook event starts one Python process, about 50 to 70 ms on an Apple M-series chip. The bash version before it cost 120 to 160 ms per hook.
- With the router installed:
  - The daemon holds 1 to 2 GB of memory.
  - The checkpoint is an 842 MB one-time download.
  - Each prompt and each worker call adds about 100 ms for the classifier.
  - The first verdict after a daemon start can take about a second.
  - The hint adds about 30 words only on prompts the router marks `delegate`, and on short follow-ups to such a prompt.

## Testing

```bash
python3 -m unittest discover -s plugins/orchestrator/tests -v
```

The tests run offline with the standard library only. They stub the router's answer through `ORCHESTRATOR_ROUTER_STUB` and point `CLAUDE_PLUGIN_DATA` at a temp dir, so they need no model and no network. Two seams:

- Unit tests call the package in-process: the exploratory decision, thresholds, verdict parsing, the unsure rule, the short-prompt check, the state record, the log records, the HTTP client, and every handler.
- Seam tests run `hooks/hook.py` as Claude Code runs it. It runs as a subprocess with a JSON payload on stdin and environment variables set. Then stdout, stderr, exit code, the state file and the log are checked. They cover the gate's deny and warning cases, the reminder and the protocol, and the hint. They also cover the counter, the model pick, the daemon start with a fake interpreter, and the finaliser.
- A package test checks:
  - That `hooks.json` and `plugin.json` parse, and that the package version matches the manifests.
  - That the seven hook registrations are in place.
  - That the worker carries the protocol's four rules word for word.
  - That the protocol's model table matches the gate's default list.
  - That the protocol has exactly one reminder line.
  - That the tool-neutral instructions name no model.

A router test imports the router service with laya replaced by an empty module. It checks the tier question word for word, the key mapping, the wording ids in the answers, and the plugin version in the health check. It cannot check the model's answers, because that needs the checkpoint. The health and route checks under "Install the router" are that smoke test.

The tests do not check whether Claude Code fires the hooks. That needs a restart and `claude --debug`.
