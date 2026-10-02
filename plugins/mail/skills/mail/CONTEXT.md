# Mail

A self-triggered assistant that sorts the owner's mailbox and writes reply drafts in the owner's voice.

## Language

### Setup

**Owner**:
The person whose mailbox the skill sorts and in whose voice it writes. The only one who sends.
_Avoid_: user, account

**Owner data**:
The owner's own files for the skill: config, style profile, triage rules and state. Kept on the owner's machine, never part of the package.
_Avoid_: settings, cache

**Context source**:
A folder the owner opted in to, which the skill may search for facts about a sender or a subject.
_Avoid_: vault, knowledge base

**Provider**:
The mail tool through which the skill reaches the owner's mailbox, such as an MCP server or a command-line client.
_Avoid_: backend, integration

### Sorting

**Triage**:
Assigning each inbound thread exactly one action label.
_Avoid_: classification, filtering

**Action label**:
A label that names the owner's next step for a thread: To reply, To act, To read, FYI. Drafted is a status label added on top, never an action label.
_Avoid_: category, tag

**Triage rule**:
A learned, owner-approved rule that overrides the default triage for a pattern of mail.
_Avoid_: filter (that is a mail client feature)

### Writing

**Intent**:
The owner's one-line statement of what a reply should say.
_Avoid_: instruction, prompt

**Voice**:
How the owner actually writes, as evidenced by their sent mail.
_Avoid_: tone, style (alone)

**Register**:
One combination of language and relationship that changes the owner's voice, such as English to clients or a native language to colleagues.
_Avoid_: mode, tone

**Style profile**:
The owner data file that describes the owner's voice per register. The single source of truth for mail writing.
_Avoid_: style guide, persona

**Exemplar**:
A recent email the owner sent to the same recipient, used as a live voice sample for one draft.
_Avoid_: example, template

**Voice check**:
The final pass that compares a draft against the style profile and exemplars, after the humanizer.
_Avoid_: review, QA

**Lesson**:
A proposed style profile change, derived from the difference between a skill draft and what the owner actually sent.
_Avoid_: feedback, correction

### Testing

**Replay**:
Running triage and drafting on past threads with a known outcome, with mailbox writes switched off.
_Avoid_: simulation, dry run

**Calibration**:
Iterating on the style profile through replay until drafts are hard to tell from the owner's real replies.
_Avoid_: training, tuning
