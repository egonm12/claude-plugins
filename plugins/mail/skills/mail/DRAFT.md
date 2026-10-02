# Draft

Completion: every target thread has a draft that passed the voice check and the ending check, or is listed as skipped with a reason.

Read the style profile (`paths.profile`) in full before the first draft. For mail it outranks the writing rules file.

## Per thread

### 1. Skip check

Skip and report when the thread already has a draft: an edited one is the owner's, and an untouched one stays because the skill never updates or deletes a draft. Tell the owner to discard it in their mail client if they want a fresh one.

### 2. Gather

- **Thread:** the full thread.
- **Exemplars:** read sent mail for `in:sent to:<recipient>`, the 3 most recent. If none, 3 recent sent mails to the same domain. If still none, use the register's fragments in the profile.
- **Recipients:** the reply pattern the owner used earlier in this thread (reply or reply-all, who they dropped). If they have not replied in the thread: reply-all, dropping no-reply addresses, mailing lists and the owner. Record every drop for the report.
- **Context:** the facts the reply needs, from the context sources (see SKILL.md "Context sources"). For scheduling, and only when `calendar` is `true`, the calendar for the proposed dates.
- **Intent:** from triage or the owner's argument. No intent means: answer what was asked, using only gathered facts.

Completion: thread, exemplars, recipients and context are gathered, or their absence is noted.

### 3. Pick the register

- **Language:** the language of the last inbound message, unless the owner's exemplars to this recipient use another language. Then use theirs.
- **Relationship:** from the context sources and the exemplars (client, colleague, team member, external, personal). Pick the matching profile register. When two fit, follow the exemplars.

### 4. Write

Write the reply in the register, following the profile's rules and the exemplars' opening, length and closing. Every fact you cannot source becomes `[TODO: what is missing]`. Keep it as short as the owner's exemplars; they write shorter than you would.

End on the last line of content, before the signature start. Type nothing the signature carries: the signature begins with the profile's `signature_start`, often the closing, and carries the owner's name, so anything typed here appears twice.

### 5. Humanizer (optional)

When a skill named `humanizer` is available, run the draft through it. Keep its removals of AI tells. Reject any change that breaks a profile rule. Record the kept and rejected changes for the run report.

When it is not available, skip this step and say so in the run report.

### 6. Voice check

Compare the result, line by line, against the profile register and the exemplars:

- the opening matches the owner's pattern for this register,
- sentence length and directness match the exemplars,
- every phrase is one they would use; replace anything the profile lists under "Never" or "Phrases never used",
- every shared rule in the profile holds,
- the draft ends on content: no closing and no name typed, nothing from the signature start onward.

Revise until every item passes. When the profile and the writing rules file disagree, follow the profile and add the conflict to the report.

### 7. Create

Convert to simple HTML: `<p>`, `<br>`, `<ul>`, `<li>` and `<b>` only, no styling. When the profile has `signature_appended_by_provider: false`, append the signature as the provider file describes. Create a draft in the thread with:

- the HTML body,
- the thread and the reply headers of the last message,
- the subject as `Re: <original>`, unless it already starts with a reply prefix such as `Re:` or `Antw:`,
- `to` and `cc` from step 2.

Add `Drafted` to the thread, unless the provider has no labels. Store `{draft_id, fingerprint, text, created}` in `state.drafts`.
