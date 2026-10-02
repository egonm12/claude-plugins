# Provider: google-workspace-mcp

Gmail and Calendar through the google-workspace MCP server.

- **Labels:** yes.
- **Signature:** the provider appends it (`include_signature=true`), so the profile sets `signature_appended_by_provider: true`.

## Detect

Available when the agent has a tool whose name ends in `search_gmail_messages`. When the agent loads MCP tools on demand, search for "gmail" first (in pi: `tool_search`). The server lists no accounts: ask the owner for the address.

## Every call

Pass `user_google_email` as the config `account`. Load the Gmail tools before the first call, and the Calendar tools when `calendar` is `true`.

## Operations

| Operation | Tool | Notes |
|---|---|---|
| Search | `search_gmail_messages` with `query`, `page_size` and `page_token` | Repeat with the returned page token until there is none. Returns message ids and thread ids. |
| Read thread | `get_gmail_thread_content` with `thread_id`; for several threads `get_gmail_threads_content_batch` with `thread_ids` | |
| Read sent mail | Search with an `in:sent` query, then `get_gmail_messages_content_batch` or `get_gmail_threads_content_batch` | |
| List and create labels | `list_gmail_labels`; `manage_gmail_label` with `action="create"` and `name` | Record the label ids: modify takes ids. |
| Modify labels | `batch_modify_gmail_message_labels` with `message_ids`, `add_label_ids` and `remove_label_ids` | Takes message ids, not thread ids: pass the latest message of each thread. Archive by removing `INBOX`. |
| Create a draft in a thread | `draft_gmail_message` with `body_format="html"`, `include_signature=true`, `thread_id`, `in_reply_to`, `references`, `subject`, `to` and `cc` | `in_reply_to` and `references` come from the Message-ID and References headers of the last message. Gmail appends the signature. There is no draft update or delete. |
| Calendar | `get_events` with `time_min` and `time_max` | Only when `calendar` is `true`. |

## Search syntax

Gmail search syntax, as the skill writes it. Label search turns `/` and spaces into `-`: the label `AI/To reply` is `label:ai-to-reply`. Draft check: search `in:drafts` and match the thread id.

## Auth errors

On an insufficient-scope or auth error, stop and report: "Gmail needs re-authorisation with the gmail.compose and gmail.modify scopes. Re-run any google-workspace Gmail tool and complete the browser sign-in."

## Never call

`send_gmail_message` (sends mail) and `send_message` (sends a Google Chat message), in any mode.
