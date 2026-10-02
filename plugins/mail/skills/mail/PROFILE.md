# Style profile

Builds and maintains the style profile at `paths.profile`. This is the most important part of the skill: a draft can only be as close to the owner's voice as this file.

Completion for a build: every register with at least 5 sent replies has a filled section, every claim in it is backed by at least 3 sent mails, the signature fields are set, and the owner has approved the profile.

## Build (`profile`, or `profile refresh`)

### 1. Collect

Read sent mail for `in:sent newer_than:3y`, paged to the end. For `refresh`, only mail after the profile's `updated` date. For each sent message read the thread, and keep the pair: the message the owner answered (or none for a new mail) and their own text. Strip quoted history and the signature block from their text.

Weight: last 12 months ×3, 12 to 24 months ×2, older ×1. When old and new mail disagree, the newest pattern wins.

Do the counting in code and keep raw mail out of the conversation: print only aggregates and short fragments.

### 2. Signature

Find the signature block that recurs at the end of the owner's sent mail. Its first line is the signature start, often a closing. When it changed over time, take the current one and note since when. Set `signature_start` in the frontmatter, and `signature_appended_by_provider` from the provider file. Confirm both with the owner.

### 3. Group into registers

Cluster pairs by language and relationship. Start from the registers the writing rules file names, if any, then split or merge on evidence (for example colleague and external mail in one language). A register needs at least 5 replies; smaller groups fold into the nearest register.

### 4. Measure per register

Fill each field of the register block:

- **When it applies:** language, relationship, counts.
- **Opening:** openings and their frequency ("Hi [name]," against no greeting).
- **Closing and signature start:** what the owner types after the last content line, and which signature start follows.
- **Length:** median words, median sentences per paragraph.
- **How they respond:** answer first or context first; how they say yes, no and "not now"; how they ask a question back; how they handle thanks.
- **Structure:** when they use lists or bold mini-headers.
- **Phrases used** and **Phrases never used:** words and phrases they use often, and words LLMs love that they never use.
- **Fragments:** see step 5.

Rules that hold in every register, such as formality markers (formal or informal address, contractions, exclamation marks), go under Shared rules. Words absent from all mail go under Never.

### 5. Anonymise fragments

Quote at most 15 words per fragment. Replace names with `[name]`, companies with `[company]`, amounts and dates with `[amount]` and `[date]`. Never quote a whole mail.

### 6. Conflicts

When a writing rules file is configured, compare its mail rules with the evidence. List each disagreement with its evidence count under Open conflicts and ask the owner to decide. After the decision, move it to Decided and update the profile. Once, propose an edit that points the writing rules file's mail rules to the profile, and apply it only after the owner approves.

### 7. Write and approve

Write the profile in the structure of the template. Fill only its fixed sections: Shared rules, Registers, Never, Open conflicts, Decided and Change log, plus the frontmatter. Add no other sections. Set `status: draft`, show the owner a summary per register, apply their corrections, then set `status: active` and `updated`. Suggest `replay` next.

## Lessons

A lesson comes from a difference between a skill draft and what the owner sent, or from a replay verdict.

1. Ignore factual changes (dates, decisions): those are context, not voice.
2. Describe the voice difference in one line, naming the register: "colleague register: drops the opening sentence and starts with the answer."
3. Propose the concrete edit to the profile. Apply it only after the owner approves, and add a line to the profile's change log.
