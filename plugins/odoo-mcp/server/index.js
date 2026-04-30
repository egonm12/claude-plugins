#!/usr/bin/env node
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import { OdooClient } from './odoo-client.js';
import { TOOL_DEFINITIONS, callTool } from './tools.js';

const ENV_KEYS = {
  url: 'ODOO_URL',
  db: 'ODOO_DB',
  username: 'ODOO_USERNAME',
  apiKey: 'ODOO_API_KEY',
};

function readConfig() {
  const cfg = {
    url: process.env.ODOO_URL,
    db: process.env.ODOO_DB,
    username: process.env.ODOO_USERNAME,
    apiKey: process.env.ODOO_API_KEY ?? process.env.ODOO_PASSWORD,
    timeoutMs: Number(process.env.ODOO_TIMEOUT_MS ?? 30000),
  };
  const missing = ['url', 'db', 'username', 'apiKey']
    .filter((k) => !cfg[k])
    .map((k) => ENV_KEYS[k]);
  if (missing.length) {
    console.error(`[odoo-mcp] Missing required environment variables: ${missing.join(', ')}`);
    console.error('[odoo-mcp] Configure these via the bundle user_config or your MCP host.');
    process.exit(1);
  }
  if (!Number.isFinite(cfg.timeoutMs) || cfg.timeoutMs <= 0) {
    cfg.timeoutMs = 30000;
  }
  return cfg;
}

const verbose = process.env.ODOO_VERBOSE === 'true';
function log(...args) {
  if (verbose) console.error('[odoo-mcp]', ...args);
}

const cfg = readConfig();
const client = new OdooClient(cfg);

const server = new Server(
  { name: 'odoo-mcp', version: '1.0.0' },
  { capabilities: { tools: {} } },
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: TOOL_DEFINITIONS,
}));

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  const { name, arguments: args } = req.params;
  log('call', name, args ? JSON.stringify(args) : '');
  const result = await callTool(client, name, args);
  if (verbose) log('result', JSON.stringify(result).slice(0, 500));
  return {
    content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
    isError: result.success === false,
  };
});

process.on('uncaughtException', (err) => {
  console.error('[odoo-mcp] uncaughtException:', err);
});
process.on('unhandledRejection', (err) => {
  console.error('[odoo-mcp] unhandledRejection:', err);
});

const transport = new StdioServerTransport();
await server.connect(transport);
console.error('[odoo-mcp] server running via stdio');
