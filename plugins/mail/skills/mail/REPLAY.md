# Replay

Completion: a scorecard for N threads is shown and the owner has given a verdict per draft. The mailbox is not written to: no labels, no drafts, no state changes except `replay_runs`.

## 1. Pick threads

Search `in:sent newer_than:2y` for replies (the subject starts with a reply prefix) and pick N threads that spread across the profile's registers: every language and relationship, short and long. Skip threads already used in `state.replay_runs`, so calibration does not overfit. Also pick N inbound threads the owner never replied to, for triage scoring.

## 2. Triage scoring

Classify all threads with [TRIAGE.md](TRIAGE.md) step 3, using only the messages before the owner's reply. Ground truth: replied means `To reply`; archived or never opened without a reply means `FYI` or `To read`; can't tell means excluded. Report agreement per label and list each miss with the reason.

## 3. Drafting

For each replied thread, hide the owner's reply and everything after it. Run [DRAFT.md](DRAFT.md) steps 2 to 6, with exemplars limited to mail sent before that reply. Use no intent: replay measures how much of the owner's voice the profile carries alone.

## 4. Ending check (automatic)

For every draft, check with a script and report pass or fail:

- the last line is content: nothing from the profile's `signature_start` onward, no typed closing from the register's "Closing and signature start", and no name,
- the HTML uses only the tags allowed in [DRAFT.md](DRAFT.md) step 7.

## 5. Side by side

Show each pair: thread summary, the draft, the owner's real reply cut at the signature start. Ask per pair: "send as is / small edits / rewrite", plus what gives it away. Turn every "gives it away" into a lesson (see [PROFILE.md](PROFILE.md) "Lessons") and propose the profile edits.

## 6. Record

Append `{date, thread_ids, verdicts}` to `state.replay_runs`. Calibration is done when two consecutive replays score at least 80% "send as is" or "small edits".
