---
name: mail
description: "Triage the owner's mailbox into action labels and write reply drafts in the owner's own voice. Drafts only, never sends."
disable-model-invocation: true
---

> **Arguments:** `$ARGUMENTS` is the text after the command (`/skill:mail` in pi, `/mail` in Claude Code). Empty means the full run.

Vocabulary (owner, owner data, provider, context source, triage, action label, intent, register, style profile, voice check, lesson, replay) is defined in [CONTEXT.md](CONTEXT.md). Use those words exactly.

## Hard rules

1. **Drafts only.** Every reply ends as a draft that the owner sends. Never call a send operation of any provider, in any mode, even when the owner asks inside a run: tell them to press send in their mail client. The provider file names its send operations.
2. **Labels only.** Triage adds and removes labels under `label_prefix`. Archive only when `auto_archive_fyi` is `true` in the config.
3. **The owner's edits are theirs.** A draft whose fingerprint no longer matches the state is never touched again. The skill never updates or deletes a draft.
4. **Facts come from sources.** Every fact in a draft comes from the thread, the owner's intent, a context source or the calendar. Anything else becomes `[TODO: ...]`.
5. **Privacy.** Read only the configured context sources, never an excluded source, and the calendar only when `calendar` is `true`. The style profile holds anonymised fragments only. Owner data stays at its configured paths.

## Modes

Parse `$ARGUMENTS` and run exactly one branch:

| Argument | Branch |
|---|---|
| empty | [TRIAGE.md](TRIAGE.md), then [DRAFT.md](DRAFT.md) on the confirmed `To reply` threads |
| `setup` | [SETUP.md](SETUP.md) |
| `triage` [`--since YYYY-MM-DD`] | [TRIAGE.md](TRIAGE.md) only |
| `draft` [thread id, thread link or search] | [DRAFT.md](DRAFT.md) only. Without a target: every thread labelled `To reply` and not `Drafted` |
| `replay` [N, default 8] | [REPLAY.md](REPLAY.md) |
| `profile` [`refresh`] | [PROFILE.md](PROFILE.md) |

Read the branch file before acting, and only the branch files the mode needs.

Label names in these files leave out the prefix: `To reply` means `label_prefix` + `To reply`, so `AI/To reply` with the default prefix.

## Preflight (every mode except `setup`)

1. **Config.** Read `~/.config/mail/config.json` first. When it is missing, stop and tell the owner to run `setup`. Expand a leading `~` in every path.
2. **Provider.** Read `providers/<provider>.md` for the configured provider and load its tools. A provider without labels supports drafting only: `draft` needs a target, the full run and `triage` stop, and every label step is skipped.
3. **Owner data.** Read the state (`paths.state`) and the triage rules (`paths.triage_rules`).
4. **Profile gate.** For the full run, `draft` and `replay`: when the profile at `paths.profile` does not have `status: active`, stop and tell the owner to run `profile`. A draft without a profile is the thing this skill exists to prevent.
5. **Auth.** When a provider call fails with an auth or scope error, stop and report the fix from the provider file. Never retry around it.

Completion: the config, the provider file, the state and the triage rules are loaded, and the profile gate passed or the run stopped.

## Provider operations

The branch files use seven operations. The provider file maps each one to a concrete tool or command:

- **Search:** find messages or threads with a query, paged to the end.
- **Read thread:** every message of a thread, with sender, recipients, reply headers, labels and drafts.
- **Read sent mail:** the owner's own sent messages for a query, with their bodies.
- **Draft check:** the message id and thread id of every draft in the mailbox, paged to the end.
- **List and create labels.**
- **Modify labels:** add and remove labels, including the inbox label to archive.
- **Create a draft in a thread:** a reply draft with recipients, subject, reply headers and an HTML body. The provider file says whether the provider appends the owner's signature or the skill must.

Queries in these files use Gmail search syntax. A provider file translates it when its provider uses another syntax.

## Drafts in a thread

A thread read can list drafts as ordinary messages, with a sender, a date and a body, and without any draft marker. Never decide from a thread read alone that a message is sent.

Run the draft check once per mode, before the first decision that depends on it. A message is a **draft** when its message id is in the draft check result, and **sent** otherwise. Every rule in these files that names "the owner's message", "the last message" or "a sent reply" means sent messages only: leave drafts out of the thread before applying it. The reply headers for a new draft also come from the last message that is not a draft.

When the draft check fails or returns nothing while `state.drafts` is not empty, stop reconcile and report it. Never fall back to guessing.

Completion: every message of every thread read in this mode is known as draft or sent.

## Context sources

For a thread, search every folder in `context_sources` for the sender's name, email address and domain, and for keywords from the subject. Excluded sources are never read: list the text files of each context source, drop every path inside an `excluded_sources` entry, and search only the rest. Read the hits that name the sender or the subject.

With no context sources, use only the thread and the owner's sent mail, and mark every missing fact `[TODO: ...]`.

Use the calendar only when `calendar` is `true`, through the calendar lookup in the provider file.

## Reconcile (every mode except `setup`, `profile` and `replay`)

Run before triage or drafting. For every thread id in `state.drafts`:

1. Run the draft check (see "Drafts in a thread") and read the thread. Split its messages into drafts and sent messages.
2. **Draft still there:** the thread has a draft from the owner. Compute its fingerprint. When it matches the state, the draft is untouched: leave it and the labels alone. When it differs, set `edited: true` and leave it alone. Stop here for this thread: a thread with a draft is never sent or discarded, whatever its last message looks like.
3. **Sent:** no draft, and the last sent message is from the owner and newer than the entry's `created`. Remove `To reply` and `Drafted`. When the sent body differs from the stored `text`, extract a **lesson** (see [PROFILE.md](PROFILE.md) "Lessons"). Then delete the state entry.
4. **Discarded:** no draft and no sent reply from the owner since `created`. Remove `Drafted` and delete the state entry.

In the run report, name for every thread which of the four cases applied and the evidence: the draft's message id, or the sent message's date.

Then, for threads labelled `To reply` where the last sent message is from the owner: remove `To reply`. A draft at the end of the thread does not count.

Then, for every thread with a skill label that differs from `state.triaged[threadId]`: the owner relabelled it. Propose a triage rule that describes the pattern (sender, domain or subject type, not the single thread), add it to the triage rules once the owner approves, and update `triaged`.

Completion: every state draft is sent, edited, discarded or untouched on the evidence of the draft check, and every relabel has a rule proposal.

## Run report (end of every mode)

Reply in chat. Write nothing outside the owner data and the provider.

- Labels added and removed, counted per label.
- One line per draft: recipient, subject, register, number of `[TODO]` markers.
- The humanizer's kept and rejected changes per draft, or "humanizer skipped: not available".
- Recipients dropped from reply-all and why.
- Lessons and triage rules, as proposed edits waiting for the owner's approval.
- Conflicts between the style profile and the writing rules file, when one is configured.
- Skipped threads and why (edited draft, existing draft, missing context).

## State

The state file (`paths.state`) is the only run state. Update it at the end of each mode:

- `last_run`: ISO timestamp of this run.
- `triaged`: thread id → action label the skill set.
- `drafts`: thread id → `{draft_id, fingerprint, text, created}`, plus `edited: true` once the owner edited it. `text` is the plain-text body, kept only until the lesson is extracted.
- `replay_runs`: one entry per replay (see [REPLAY.md](REPLAY.md)).

**Fingerprint:** the SHA-256 of the draft body as plain text with whitespace collapsed, cut at the profile's `signature_start`: the first line that starts with it, and everything after, stay out, both when storing and when comparing at reconcile. Compute it with a script, never by hand. An empty `signature_start` means no cut.
