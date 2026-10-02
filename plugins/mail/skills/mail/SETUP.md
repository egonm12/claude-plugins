# Setup

Completion: the config, the style profile, the triage rules and the state exist at their configured paths, the profile has `status: active` or the owner chose to finish it later, and replay has been suggested.

Setup never overwrites an existing owner data file. When one exists, keep it, say so, and go on with the next file.

## 1. Detect providers

Read every file in `providers/` and run its "Detect" check. Call no mail operation yet.

When no provider is found, stop: tell the owner that the skill needs one supported provider, and name the files in `providers/`. Setup does not continue without one.

Completion: a list of the available providers, with the accounts each one reports.

## 2. Ask

Ask in one message, with the defaults shown:

- **Provider and account:** which detected provider and which account. Say so when a provider has no labels: it supports drafting only.
- **Context sources:** which folders the skill may search for context, as absolute paths. None is a valid answer.
- **Excluded sources:** which folders the skill must never read, even inside a context source, such as finance or personal notes.
- **Calendar:** whether to use the provider's calendar when a reply proposes dates. Default no.
- **Writing rules file:** an optional file with the owner's general writing rules, as an absolute path. The profile build compares against it.
- **Paths:** whether to override the default path of the profile, the triage rules or the state, all in `~/.config/mail/` by default. The config itself always lives at `~/.config/mail/config.json`.

Check that every folder and file given exists. Ask again for any that does not.

Completion: every question has an answer or an accepted default, and every given path exists.

## 3. Copy templates

The templates live in `templates/`, two levels above the real directory of this skill. Resolve the skill directory with `realpath` first: the skill folder may be a symlink, and `..` from the link path lands in the wrong place.

1. `config.template.json` → `~/.config/mail/config.json`, filled with the answers. Keep `label_prefix` at `AI/` and `auto_archive_fyi` at `false`, and tell the owner they can change both in the file.
2. `style-profile.template.md` → `paths.profile`.
3. `triage-rules.template.md` → `paths.triage_rules`.
4. Write `paths.state` as `{"last_run": null, "triaged": {}, "drafts": {}, "replay_runs": []}`.

Validate the config and the state as JSON, for example with `python3 -m json.tool`.

Completion: all four files exist and both JSON files parse.

## 4. Build the profile

Run "Build" in [PROFILE.md](PROFILE.md), with the provider file loaded.

Completion: the profile has `status: active`, or the owner chose to finish it later. Drafting stays blocked until it is active.

## 5. Suggest replay

Show the owner a setup summary: provider, account, paths, context sources, excluded sources and calendar. Then suggest `replay` to calibrate the profile on past threads before the first real run: `/skill:mail replay` in pi, `/mail replay` in Claude Code.

Completion: the owner has the summary and the replay suggestion.
