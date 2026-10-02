# mail

A skill that sorts your inbox into action labels and writes reply drafts in your own voice. It never sends: every reply ends as a draft that you read and send yourself.

The skill learns your voice from your sent mail. It builds a style profile per register, a combination of language and relationship such as English to clients, and checks every draft against it. The terms owner, owner data, provider, context source, register and style profile are defined in the skill's [CONTEXT.md](skills/mail/CONTEXT.md).

## Prerequisites

- An agent with skill support, such as pi or Claude Code.
- One supported provider:

| Provider | Reference file | Triage and labels | Signature |
|---|---|---|---|
| google-workspace MCP server | [google-workspace-mcp.md](skills/mail/providers/google-workspace-mcp.md) | Yes | The provider appends it |
| `gog` command-line client | [gog.md](skills/mail/providers/gog.md) | Yes | The skill appends it |

## Install

### Claude Code

1. Add the marketplace and install the package:
   ```
   /plugin marketplace add egonm12/claude-plugins
   /plugin install mail@egonm12-plugins
   ```
2. Restart Claude Code.
3. Run `/mail setup`. Claude Code namespaces skills from a plugin, so the command can also show as `/mail:mail`.

### pi

Link the skill folder into a folder that pi scans for skills:

```bash
git clone https://github.com/egonm12/claude-plugins.git
ln -s "$PWD/claude-plugins/plugins/mail/skills/mail" ~/.agents/skills/mail
```

Run `/reload` or restart pi, then run `/skill:mail setup`.

The skill sets `disable-model-invocation: true`, so it runs only when you type the command: `/skill:mail` in pi, `/mail` in Claude Code.

## Set up

`setup` walks you through five steps:

1. It detects the available providers, and stops when it finds none.
2. It asks which provider and account to use, which folders to use as context sources and which to exclude, whether to use the calendar, an optional writing rules file, and whether to override any path.
3. It copies the templates into place.
4. It builds your style profile from your sent mail and asks you to approve it.
5. It suggests a replay to calibrate the profile.

Drafting stays blocked until the profile has `status: active`.

## Modes

The commands below use the Claude Code form. In pi, type `/skill:mail` instead of `/mail`.

| Command | What it does |
|---|---|
| `/mail` | The full run: triage, your confirmation, then drafts for the threads labelled To reply |
| `/mail setup` | First-time setup, see above |
| `/mail triage [--since YYYY-MM-DD]` | Triage only |
| `/mail draft [thread id, link or search]` | Drafts only. Without a target, every To reply thread that has no draft yet |
| `/mail replay [N]` | Drafts for N past threads you already answered, side by side with your real reply. Writes nothing to your mailbox |
| `/mail profile [refresh]` | Builds the style profile, or adds mail sent since the last build |

## Owner data

Everything the skill learns about you lives outside the package, in `~/.config/mail/` by default:

| File | What it holds |
|---|---|
| `config.json` | Provider, account, paths, context sources, calendar and labels |
| `style-profile.md` | Your voice per register, and your signature start |
| `triage-rules.md` | Triage rules you approved |
| `state.json` | Run state: triaged threads, open drafts and their fingerprints, replay runs |

Setup can move the profile, the triage rules and the state anywhere. The config always stays at `~/.config/mail/config.json`, and the skill reads it first, every run.

### Config fields

| Field | Default | Meaning |
|---|---|---|
| `account` | | The mailbox address |
| `provider` | | A file name in `skills/mail/providers/`, without `.md` |
| `paths.profile`, `paths.triage_rules`, `paths.state` | `~/.config/mail/` | Where the owner data files live |
| `context_sources` | `[]` | Folders the skill may search for facts about a sender or a subject |
| `excluded_sources` | `[]` | Folders the skill never reads, even inside a context source |
| `calendar` | `false` | Use the provider's calendar when a reply proposes dates |
| `writing_rules_file` | `null` | Optional file with your general writing rules. The profile build compares against it |
| `label_prefix` | `AI/` | Prefix for the skill's labels, such as `AI/To reply` |
| `auto_archive_fyi` | `false` | Archive FYI threads after triage |

The templates for these files are in [templates/](templates/).

### Signature

The style profile records your signature start: the first line of your mail signature, often a closing. It also records whether the provider appends the signature to a draft. Every draft ends on its last content line, before the signature start, so the closing and your name never appear twice. The ending check in replay and the draft fingerprint both cut at the signature start.

## Privacy

- **State stays local.** Owner data lives on your machine and is never part of the package. The package's `.gitignore` blocks instance files of the config, the profile, the triage rules and the state.
- **The profile holds only anonymised fragments.** A fragment is at most 15 words, with names, companies, amounts and dates replaced by placeholders.
- **The skill never sends.** No mode calls a send operation of any provider, even when you ask during a run.
- **Context sources are an explicit opt-in.** The skill reads only the folders you list, never an excluded one, and the calendar only when you turn it on. With no context sources it uses the thread and your sent mail, and marks every missing fact `[TODO: ...]`.

## Add a provider

The skill works through six abstract operations: search, read thread, read sent mail, list and create labels, modify labels, and create a draft in a thread. A provider file maps them to concrete tools.

1. Copy a file in `skills/mail/providers/` to `<name>.md`. The file name is the value of `provider` in the config.
2. Fill in each section:
   - **Labels and signature:** whether the provider has labels, and whether creating a draft appends the owner's signature.
   - **Detect:** how setup finds out that the provider is available and which accounts it has, without a mail operation.
   - **Every call:** arguments or flags that every call needs.
   - **Operations:** a tool or command per operation, plus an optional calendar lookup.
   - **Signature:** when the provider does not append it, how the skill reads the signature to append it itself.
   - **Search syntax:** how the provider's queries differ from Gmail search syntax, which the skill uses.
   - **Auth errors:** what the owner must do when a call fails on auth or scope.
   - **Never call:** every operation that sends.
3. A provider without labels gets drafting only: `draft` with a target, `replay` and `profile`. Triage and the full run stay off.
4. Run `setup` and pick the new provider.

The hard rule holds for every provider: the skill never calls a send operation.

## Layout

```
plugins/mail/
├── .claude-plugin/
│   └── plugin.json
├── .gitignore
├── README.md
├── skills/mail/
│   ├── SKILL.md            # entry point: hard rules, modes, preflight, state
│   ├── CONTEXT.md          # glossary
│   ├── SETUP.md            # setup mode
│   ├── TRIAGE.md           # triage mode
│   ├── DRAFT.md            # draft mode
│   ├── REPLAY.md           # replay mode
│   ├── PROFILE.md          # profile mode and lessons
│   └── providers/
│       ├── google-workspace-mcp.md
│       └── gog.md
└── templates/
    ├── config.template.json
    ├── style-profile.template.md
    └── triage-rules.template.md
```

## License

MIT
