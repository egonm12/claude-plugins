# Claude plugins

A Claude Code plugin marketplace by Egon Meijers.

## Available plugins

| Plugin | Version | Description |
|--------|---------|-------------|
| [odoo-mcp](plugins/odoo-mcp/README.md) | 1.0.0 | Odoo MCP tools to search, create, read, update and delete records through XML-RPC. |
| [orchestrator](plugins/orchestrator/README.md) | 0.5.5 | Keeps the main thread in the orchestrator role. Blocks Fable workers, warns when a worker model is missing or unknown, holds workers to verified reporting, and lets an optional local classifier hint when to delegate and pick the worker model. |
| [mail](plugins/mail/README.md) | 0.1.0 | Triages the owner's mailbox into action labels and writes reply drafts in the owner's own voice. Drafts only, never sends. |

## Installation

1. Add the marketplace:
   ```
   /plugin marketplace add egonm12/claude-plugins
   ```

2. Install a plugin:
   ```
   /plugin install odoo-mcp@egonm12-plugins
   /plugin install orchestrator@egonm12-plugins
   /plugin install mail@egonm12-plugins
   ```

3. Restart Claude Code. Hooks and MCP servers load at session start.

## Prerequisites for odoo-mcp

- Node.js 18 or newer
- An Odoo instance with API access
- These environment variables:
  ```bash
  export ODOO_URL="https://your-odoo-instance.com"
  export ODOO_DB="your-database-name"
  export ODOO_USERNAME="your-email@example.com"
  export ODOO_API_KEY="your-api-key"
  ```

Use an Odoo API key, not your password. Odoo requires a key when the account has 2FA turned on. See the [odoo-mcp README](plugins/odoo-mcp/README.md) for details.

## Prerequisites for orchestrator

- `bash` on the path. The hooks are shell scripts.
- `jq` on the path. Without `jq`, the model gate runs in reduced mode and only blocks calls that mention Fable.

Upgrading from `delegation-policy`? See [the upgrade steps](plugins/orchestrator/README.md#upgrade-from-delegation-policy).

## Prerequisites for mail

- An agent with skill support, such as Claude Code or pi.
- One supported mail provider: the google-workspace MCP server or the `gog` command-line client.

In Claude Code, run `/mail setup` after the install. In pi, link the skill folder from a checkout of this repository instead of installing from the marketplace:

```bash
ln -s "$PWD/plugins/mail/skills/mail" ~/.agents/skills/mail
```

Then run `/skill:mail setup`. See the [mail README](plugins/mail/README.md) for the modes, the owner data and the privacy rules.
