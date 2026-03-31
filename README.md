# Claude plugins

A Claude Code plugin marketplace by Egon Meijers.

## Available plugins

| Plugin | Description |
|--------|-------------|
| odoo-mcp | Odoo MCP tools for search, create, read, update, and delete operations via XML-RPC |

## Installation

1. Add the marketplace:
   ```
   /plugin marketplace add egonm12/claude-plugins
   ```

2. Install a plugin:
   ```
   /plugin install odoo-mcp@egonm12-plugins
   ```

## Prerequisites for odoo-mcp

- [uv](https://docs.astral.sh/uv/) installed
- Odoo instance with API access
- Environment variables set:
  ```bash
  export ODOO_URL="https://your-odoo-instance.com"
  export ODOO_DB="your-database-name"
  export ODOO_USERNAME="your-email@example.com"
  export ODOO_PASSWORD="your-api-key"
  ```
