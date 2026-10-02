# Triage

Completion: every inbound thread in scope carries exactly one action label, and the owner has confirmed the list.

## 1. Scope

- `--since` given: `in:inbox after:YYYY/MM/DD`.
- `state.last_run` is null (first run): `in:inbox newer_than:30d`.
- Otherwise: `in:inbox after:<last_run as epoch seconds>`, plus every thread that already has a skill label and received a new inbound message since `last_run` (re-triage).

Search until the results run out. Group the results by thread and read the threads, in batches when the provider supports it.

Completion: every thread in scope is read.

## 2. Ensure labels

List the labels. Create any that is missing: the parent label (`label_prefix` without its trailing `/`), `To reply`, `To act`, `To read`, `FYI` and `Drafted`. Record their ids.

## 3. Classify

Apply the triage rules first; a matching rule decides. Otherwise judge from the latest message:

| Label | When |
|---|---|
| `To reply` | A human asks the owner something or expects their answer, and the last sent message is not the owner's (a draft does not count, see SKILL.md "Drafts in a thread"). Direct questions, requests for their opinion or availability, threads where they are clearly the one to answer. |
| `To act` | The owner must do something that is not a reply: approve, pay, sign, review a PR or document, fill in a form, accept an invite that needs a decision. |
| `To read` | Written by a human or relevant to the owner's work, worth reading, no response expected: updates, CC'd decisions, reports from their team or clients. |
| `FYI` | Automated or bulk: newsletters, notifications, receipts, marketing, no-reply senders, mailing lists where the owner is not addressed. |

Tie-breaks: reply beats act beats read beats FYI. When the owner is only in CC, prefer `To read` unless the body names them. Use the context sources (see SKILL.md "Context sources") to recognise colleagues and clients.

## 4. Confirm

Show one compact table grouped by label: sender, subject, one-line reason. For `To reply` rows add a blank intent column. Ask the owner to:

- correct labels (by row number),
- add intents for replies (optional),
- say "go".

Wait. Corrections made here are also triage rule candidates: propose a rule when the correction names a pattern.

## 5. Apply

Modify labels on the latest message of each thread: add the action label, remove any other action label. Update `state.triaged`. When `auto_archive_fyi` is `true`, also remove the inbox label from `FYI` threads.

In the full run, hand the confirmed `To reply` threads and their intents to [DRAFT.md](DRAFT.md).

Completion: every confirmed thread carries its label, and `state.triaged` matches.
