# Provider: gog

Gmail and Calendar through the `gog` command-line client (gogcli).

- **Labels:** yes.
- **Signature:** the skill appends it. `gog gmail drafts create` has no signature flag, so the profile sets `signature_appended_by_provider: false`.

## Detect

Available when `command -v gog` succeeds. `gog auth list` lists the stored accounts: offer those as the account choice.

## Every call

Put these global flags before `gmail` or `calendar`:

```bash
gog --account <account> --json --no-input --gmail-no-send gmail ...
```

`--gmail-no-send` blocks every Gmail send operation as a second guard. Creating a draft still works with it.

## Operations

Commands below leave out `gog` and the global flags.

| Operation | Command | Notes |
|---|---|---|
| Search | `gmail search '<query>' --all` for threads; `gmail messages search '<query>' --all` for messages | `--all` fetches every page. |
| Read thread | `gmail thread get <threadId> --full` | |
| Read sent mail | `gmail messages search 'in:sent <query>' --all --full` | `--full` includes the full bodies. |
| List and create labels | `gmail labels list`; `gmail labels create '<name>'` | |
| Modify labels | `gmail batch modify <messageId> ... --add '<labels>' --remove '<labels>'` | Comma-separated label names or ids. Pass the latest message of each thread. Archive by removing `INBOX`. |
| Create a draft in a thread | `gmail drafts create --reply-to-message-id <messageId> --to '<to>' --cc '<cc>' --subject '<subject>' --body-html '<html>'` | `--reply-to-message-id` takes the Gmail message id of the last message and sets In-Reply-To, References and the thread. Append the signature to the HTML first (see "Signature"). |
| Calendar | `calendar events --from <start> --to <end>` | Only when `calendar` is `true`. |

## Signature

Read the signature once per run, with the global flags: `gmail settings sendas get <account>`. Its `signature` field holds the HTML signature. Append it to the HTML body after the last content line, separated by `<br><br>`. The fingerprint still cuts at the signature start.

## Search syntax

Gmail search syntax, as the skill writes it. Label search turns `/` and spaces into `-`: the label `AI/To reply` is `label:ai-to-reply`. Draft check: `gmail search 'in:drafts' --all` and match the thread id.

## Auth errors

On an auth or scope error, stop and tell the owner to authorise again with `gog auth add <account> --services gmail --force-consent` (`--services gmail,calendar` when `calendar` is `true`). `gog auth doctor` diagnoses the stored tokens.

## Never call

`gmail send`, `gmail drafts send`, `gmail forward` and `gmail autoreply`, in any mode. `gmail drafts update` and `gmail drafts delete` exist, but the skill never updates or deletes a draft.
