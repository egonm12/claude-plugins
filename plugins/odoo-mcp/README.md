# Odoo MCP

A Model Context Protocol (MCP) server for Odoo, packaged as an [MCP Bundle (`.mcpb`)](https://github.com/anthropics/mcpb). Authenticates with an Odoo API key, so it works with accounts that have 2FA enabled.

The same `server/index.js` is shipped two ways:

- **MCPB bundle** — packaged via `mcpb pack` and loaded by MCPB-aware hosts (Claude Desktop). Configuration is collected from the user via `manifest.json`'s `user_config`.
- **Claude Code plugin** — loaded from `.claude-plugin/plugin.json`. Configuration is read from environment variables.

## Available tools

| Tool | Description |
| --- | --- |
| `search_read` | Search records and return their data |
| `search_ids` | Search for record IDs only |
| `search_count` | Count matching records |
| `read_record` | Read records by ID |
| `create_record` | Create a new record |
| `update_record` | Update existing records |
| `delete_record` | Delete records by ID |
| `list_models` | List available Odoo models with an optional keyword filter |
| `get_model_fields` | Get field metadata (name, type, label, required) for a model |

All tool responses are JSON objects with a `success` boolean. Errors include an `error_type` (`invalid_field`, `invalid_model`, `access_denied`, `validation_error`, `connection_error`, `unknown`) and, where useful, fuzzy-matched `suggestions` to help an LLM recover from typos.

## Building the bundle

Prerequisite: Node.js 18 or newer.

```sh
cd plugins/odoo-mcp
npm install
npm test
npx -y @anthropic-ai/mcpb pack .
```

The pack step produces `odoo-mcp-1.0.0.mcpb`. Open the file with an MCPB-compatible host (e.g. Claude Desktop) to install.

The bundle prompts the user for:

- **Odoo URL** — base URL of the instance, e.g. `https://example.odoo.com`
- **Database** — Odoo database name
- **Username** — Odoo user email
- **API key** — stored as a sensitive value (use this in place of a password; required when 2FA is enabled)
- **Request timeout (ms)** — optional, default `30000`
- **Verbose logging** — optional boolean; logs every tool call and result preview to stderr

## Using as a Claude Code plugin

Once installed via the marketplace, set the credentials in your shell:

```sh
export ODOO_URL="https://your-odoo-instance.com"
export ODOO_DB="your-database-name"
export ODOO_USERNAME="your-email@example.com"
export ODOO_API_KEY="your-api-key"
```

Restart your terminal, launch Claude Code, and the Odoo tools will be available.

The legacy `ODOO_PASSWORD` variable is also accepted for backwards compatibility.

## Getting an API key

1. Log in to your Odoo instance.
2. Go to **Preferences → Account Security → API Keys**.
3. Click **New API Key** and give it a descriptive name (e.g. "Claude MCP").
4. Copy the generated key and use it as `ODOO_API_KEY`.

## Examples

Find a project:

```text
search_read(model='project.project', domain=[['name', 'ilike', 'Hertek']], fields=['id', 'name'])
```

Create a timesheet entry:

```text
create_record(model='account.analytic.line', values={
  date: '2025-01-15',
  project_id: 1814,
  task_id: 23004,
  name: 'Development work',
  unit_amount: 4.5,
  employee_id: 50
})
```

Discover models matching a keyword:

```text
list_models(filter='project')
```

Inspect a model's schema:

```text
get_model_fields(model='project.project', field_types=['char', 'many2one'])
```

## Development

```sh
npm install      # install runtime + dev deps
npm test         # run the node:test suite (no Odoo connection needed; uses a mock client)
npm start        # launch the server over stdio (for manual MCP probes)
```

The MCP protocol layer is intentionally thin: `server/index.js` only wires `ListTools`/`CallTool` to a pure `callTool(client, name, args)` function in `server/tools.js`. Tests exercise that function directly with a mock client; no real XML-RPC traffic occurs in the suite.

### Layout

```
plugins/odoo-mcp/
├── manifest.json              # MCPB manifest (host-facing metadata)
├── package.json               # Node deps and scripts
├── .claude-plugin/
│   └── plugin.json            # Claude Code plugin entry point
├── server/
│   ├── index.js               # stdio entry: wires SDK to callTool()
│   ├── tools.js               # tool definitions + dispatcher
│   ├── odoo-client.js         # XML-RPC client with API key auth + timeout
│   └── errors.js              # error classification + fuzzy suggestions
└── test/
    ├── helpers.js
    ├── tools.test.js
    ├── error-messages.test.js
    ├── schema-introspection.test.js
    └── delete-record.test.js
```

## Troubleshooting

| Error | Resolution |
| --- | --- |
| `Authentication failed - check credentials` | Verify the API key, URL, database, and username. |
| `Failed to connect to Odoo: …` | Confirm `ODOO_URL` is reachable and uses `https://`. |
| `Model 'X' does not exist` | The error message lists fuzzy-matched alternatives; or run `list_models` to discover names. |
| `Invalid field 'X' on model 'Y'` | The error message lists fuzzy-matched alternatives; or run `get_model_fields` to inspect the schema. |
| `Odoo request timed out after Nms` | Increase the **Request timeout (ms)** user_config value (or `ODOO_TIMEOUT_MS`). |

## Security

- Never commit the API key. The MCPB user_config marks it as sensitive so the host stores it securely.
- The API key inherits all permissions of the Odoo user that owns it.
- The server runs locally and communicates over stdio; no traffic leaves the machine except XML-RPC calls to your configured Odoo instance.

## License

MIT
