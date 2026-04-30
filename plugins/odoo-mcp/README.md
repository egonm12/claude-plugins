# Odoo MCP server

A Model Context Protocol (MCP) server for Odoo that supports API key authentication, enabling use with Odoo accounts that have two-factor authentication (2FA) enabled.

## Features

- **API key authentication**: works with Odoo accounts that have 2FA enabled
- **Schema introspection**: discover models and fields at runtime
- **LLM-friendly errors**: structured error messages with suggestions to help self-correct
- **Comprehensive tools**: search, create, read, update, and delete operations

## Installation

### As a Claude Code plugin (recommended)

1. **Install the plugin:**
   ```bash
   claude plugin install odoo-mcp --scope user
   ```

2. **Set your Odoo credentials** as environment variables (e.g., in `~/.zshrc` or `~/.bashrc`):
   ```bash
   export ODOO_URL="https://your-odoo-instance.com"
   export ODOO_DB="your-database-name"
   export ODOO_USERNAME="your-email@example.com"
   export ODOO_PASSWORD="your-api-key"
   ```

3. **Restart your terminal** and launch Claude Code. The Odoo tools are now available.

### Manual setup

If you prefer not to use the plugin, you can configure the MCP server directly.

**Prerequisites:** Python 3.7+, [uv](https://docs.astral.sh/uv/)

Add to your project's `.mcp.json` or Claude Desktop config:

```json
{
  "mcpServers": {
    "odoo": {
      "command": "uv",
      "args": [
        "run",
        "--with", "fastmcp>=0.1.0",
        "--with", "python-dotenv>=1.0.0",
        "python",
        "/path/to/odoo-mcp/server.py"
      ],
      "env": {
        "ODOO_URL": "https://your-odoo-instance.com",
        "ODOO_DB": "your-database-name",
        "ODOO_USERNAME": "your-email@example.com",
        "ODOO_PASSWORD": "your-api-key"
      }
    }
  }
}
```

## Getting an API key

1. Log in to your Odoo instance
2. Go to Preferences > Account Security > API Keys
3. Click "New API Key"
4. Give it a descriptive name (e.g., "Claude MCP")
5. Copy the generated key and use it as `ODOO_PASSWORD`

## Available tools

### Data operations

| Tool | Description |
|------|-------------|
| `search_read` | Search records and return their data |
| `search_ids` | Search for record IDs only |
| `search_count` | Count matching records |
| `read_record` | Read records by ID |
| `create_record` | Create a new record |
| `update_record` | Update existing records |
| `delete_record` | Delete records by ID |

### Schema introspection

| Tool | Description |
|------|-------------|
| `list_models` | List available Odoo models with optional keyword filter |
| `get_model_fields` | Get field metadata for a model (name, type, required) |

## Examples

### Find a project
```
search_read(model='project.project', domain=[['name', 'ilike', 'Hertek']], fields=['id', 'name'])
```

### Create a timesheet entry
```
create_record(model='account.analytic.line', values={
    'date': '2025-01-15',
    'project_id': 1814,
    'task_id': 23004,
    'name': 'Development work',
    'unit_amount': 4.5,
    'employee_id': 50
})
```

### Discover models
```
list_models(filter='project')
```

### Inspect a model's fields
```
get_model_fields(model='project.project', field_types=['char', 'many2one'])
```

## Troubleshooting

| Error | Solution |
|-------|----------|
| Authentication failed | Verify your API key, URL, database, and username |
| Connection refused | Check that ODOO_URL is accessible and uses `https://` |
| Model does not exist | Check the model name; use `list_models` to discover valid names |
| Invalid field | Check field names; the error message suggests valid alternatives |
| Tools not appearing | Restart Claude Code after configuration changes |

## Security

- Never commit API keys to version control
- API keys have the same permissions as your Odoo account
- The MCP server runs locally and communicates via STDIO

## License

MIT
