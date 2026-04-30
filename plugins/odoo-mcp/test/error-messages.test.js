import { test } from 'node:test';
import assert from 'node:assert/strict';
import { callTool } from '../server/tools.js';
import { mockMethod, mockClient, ConnError } from './helpers.js';

// ── 1. Invalid field name suggestions ───────────────────────────────────────

test('search_read suggests valid fields when an invalid one is used', async () => {
  const searchRead = mockMethod(new Error("Odoo error: Invalid field 'nme' on model 'res.partner'"));
  const fieldsGet = mockMethod([
    {
      name: { string: 'Name', type: 'char', required: true },
      email: { string: 'Email', type: 'char', required: false },
      phone: { string: 'Phone', type: 'char', required: false },
    },
  ]);
  const client = mockClient({ searchRead, fieldsGet });

  const result = await callTool(client, 'search_read', {
    model: 'res.partner',
    domain: [],
    fields: ['nme'],
  });

  assert.equal(result.success, false);
  assert.equal(result.error_type, 'invalid_field');
  assert.ok(result.suggestions, 'expected suggestions object');
  assert.ok('nme' in result.suggestions);
  assert.ok(result.suggestions.nme.includes('name'));
});

test('create_record suggests valid fields when an invalid one is used', async () => {
  const create = mockMethod(new Error("Odoo error: Invalid field 'emial' on model 'res.partner'"));
  const fieldsGet = mockMethod([
    {
      name: { string: 'Name', type: 'char', required: true },
      email: { string: 'Email', type: 'char', required: false },
    },
  ]);
  const client = mockClient({ create, fieldsGet });

  const result = await callTool(client, 'create_record', {
    model: 'res.partner',
    values: { emial: 'test@example.com' },
  });

  assert.equal(result.success, false);
  assert.equal(result.error_type, 'invalid_field');
  assert.ok('emial' in result.suggestions);
  assert.ok(result.suggestions.emial.includes('email'));
});

test('field suggestions are sorted by similarity', async () => {
  const searchRead = mockMethod(new Error("Odoo error: Invalid field 'naem' on model 'res.partner'"));
  const fieldsGet = mockMethod([
    {
      name: { string: 'Name', type: 'char', required: true },
      email: { string: 'Email', type: 'char', required: false },
      phone: { string: 'Phone', type: 'char', required: false },
      active: { string: 'Active', type: 'boolean', required: false },
    },
  ]);
  const client = mockClient({ searchRead, fieldsGet });

  const result = await callTool(client, 'search_read', {
    model: 'res.partner',
    domain: [],
    fields: ['naem'],
  });

  assert.equal(result.success, false);
  assert.equal(result.suggestions.naem[0], 'name');
});

test('field suggestions are capped at five', async () => {
  const searchRead = mockMethod(new Error("Odoo error: Invalid field 'nam' on model 'res.partner'"));
  const manyFields = {};
  for (let i = 0; i < 20; i++) {
    manyFields[`name_${i}`] = { string: `Name ${i}`, type: 'char', required: false };
  }
  const fieldsGet = mockMethod([manyFields]);
  const client = mockClient({ searchRead, fieldsGet });

  const result = await callTool(client, 'search_read', {
    model: 'res.partner',
    domain: [],
    fields: ['nam'],
  });

  assert.equal(result.success, false);
  assert.ok(result.suggestions.nam.length <= 5);
});

test('error string includes invalid field name and suggestions', async () => {
  const searchRead = mockMethod(new Error("Odoo error: Invalid field 'nme' on model 'res.partner'"));
  const fieldsGet = mockMethod([{ name: { string: 'Name', type: 'char', required: true } }]);
  const client = mockClient({ searchRead, fieldsGet });

  const result = await callTool(client, 'search_read', { model: 'res.partner', domain: [] });

  assert.match(result.error, /nme/);
  assert.match(result.error, /name/);
});

// ── 2. Invalid model name suggestions ───────────────────────────────────────

test('search_read suggests valid models when an invalid one is used', async () => {
  const searchRead = mockMethod([
    new Error("Odoo error: Model 'res.parner' does not exist"),
    [
      { model: 'res.partner', name: 'Contact' },
      { model: 'res.partner.bank', name: 'Bank Account' },
      { model: 'res.partner.category', name: 'Partner Tag' },
    ],
  ]);
  const client = mockClient({ searchRead });

  const result = await callTool(client, 'search_read', { model: 'res.parner', domain: [] });

  assert.equal(result.success, false);
  assert.equal(result.error_type, 'invalid_model');
  assert.ok(Array.isArray(result.suggestions));
  assert.ok(result.suggestions.includes('res.partner'));
});

test('model suggestions are capped at five', async () => {
  const models = [];
  for (let i = 0; i < 20; i++) {
    models.push({ model: `res.partner.${i}`, name: `Partner ${i}` });
  }
  const searchRead = mockMethod([
    new Error("Odoo error: Model 'res.parner' does not exist"),
    models,
  ]);
  const client = mockClient({ searchRead });

  const result = await callTool(client, 'search_read', { model: 'res.parner', domain: [] });

  assert.equal(result.success, false);
  assert.ok(result.suggestions.length <= 5);
});

test('error string includes invalid and suggested model names', async () => {
  const searchRead = mockMethod([
    new Error("Odoo error: Model 'res.parner' does not exist"),
    [{ model: 'res.partner', name: 'Contact' }],
  ]);
  const client = mockClient({ searchRead });

  const result = await callTool(client, 'search_read', { model: 'res.parner', domain: [] });

  assert.match(result.error, /res\.parner/);
  assert.match(result.error, /res\.partner/);
});

// ── 3. Error classification ────────────────────────────────────────────────

test('invalid field error is classified', async () => {
  const searchRead = mockMethod(new Error("Odoo error: Invalid field 'xyz' on model 'res.partner'"));
  const fieldsGet = mockMethod([{}]);
  const client = mockClient({ searchRead, fieldsGet });

  const result = await callTool(client, 'search_read', { model: 'res.partner', domain: [] });
  assert.equal(result.error_type, 'invalid_field');
});

test('invalid model error is classified', async () => {
  const searchRead = mockMethod([
    new Error("Odoo error: Model 'fake.model' does not exist"),
    [],
  ]);
  const client = mockClient({ searchRead });

  const result = await callTool(client, 'search_read', { model: 'fake.model', domain: [] });
  assert.equal(result.error_type, 'invalid_model');
});

test('access denied error is classified', async () => {
  const searchRead = mockMethod(new Error('Odoo error: Access Denied'));
  const client = mockClient({ searchRead });

  const result = await callTool(client, 'search_read', { model: 'res.partner', domain: [] });
  assert.equal(result.error_type, 'access_denied');
});

test('validation error is classified', async () => {
  const create = mockMethod(new Error('Odoo error: Missing required fields: name'));
  const client = mockClient({ create });

  const result = await callTool(client, 'create_record', { model: 'res.partner', values: {} });
  assert.equal(result.error_type, 'validation_error');
});

test('connection error is classified', async () => {
  const searchRead = mockMethod(new ConnError('Failed to connect to Odoo: Connection refused'));
  const client = mockClient({ searchRead });

  const result = await callTool(client, 'search_read', { model: 'res.partner', domain: [] });
  assert.equal(result.error_type, 'connection_error');
});

test('unknown error is classified', async () => {
  const searchRead = mockMethod(new Error('Something completely unexpected'));
  const client = mockClient({ searchRead });

  const result = await callTool(client, 'search_read', { model: 'res.partner', domain: [] });
  assert.equal(result.error_type, 'unknown');
});

test('unknown errors carry no suggestions', async () => {
  const searchRead = mockMethod(new Error('Unexpected error'));
  const client = mockClient({ searchRead });

  const result = await callTool(client, 'search_read', { model: 'res.partner', domain: [] });
  assert.equal(result.suggestions, undefined);
});

// ── 4. Backward compatibility ──────────────────────────────────────────────

test('error response always contains success: false', async () => {
  const searchRead = mockMethod(new Error("Odoo error: Invalid field 'nme' on model 'res.partner'"));
  const fieldsGet = mockMethod([{ name: { string: 'Name', type: 'char', required: true } }]);
  const client = mockClient({ searchRead, fieldsGet });

  const result = await callTool(client, 'search_read', { model: 'res.partner', domain: [] });
  assert.equal(result.success, false);
});

test('error response contains a non-empty error string', async () => {
  const searchRead = mockMethod(new Error("Odoo error: Invalid field 'nme' on model 'res.partner'"));
  const fieldsGet = mockMethod([{ name: { string: 'Name', type: 'char', required: true } }]);
  const client = mockClient({ searchRead, fieldsGet });

  const result = await callTool(client, 'search_read', { model: 'res.partner', domain: [] });
  assert.equal(typeof result.error, 'string');
  assert.ok(result.error.length > 0);
});

test('error_type and suggestions are additive', async () => {
  const searchRead = mockMethod(new Error("Odoo error: Invalid field 'nme' on model 'res.partner'"));
  const fieldsGet = mockMethod([{ name: { string: 'Name', type: 'char', required: true } }]);
  const client = mockClient({ searchRead, fieldsGet });

  const result = await callTool(client, 'search_read', { model: 'res.partner', domain: [] });
  assert.ok('success' in result);
  assert.ok('error' in result);
  assert.ok('error_type' in result);
});

// ── 5. Suggestion resilience ───────────────────────────────────────────────

test('field suggestion lookup failure leaves the error without suggestions', async () => {
  const searchRead = mockMethod(new Error("Odoo error: Invalid field 'nme' on model 'res.partner'"));
  const fieldsGet = mockMethod(new Error('Connection lost'));
  const client = mockClient({ searchRead, fieldsGet });

  const result = await callTool(client, 'search_read', { model: 'res.partner', domain: [] });

  assert.equal(result.success, false);
  assert.equal(result.error_type, 'invalid_field');
  assert.ok(result.suggestions === undefined);
});

test('model suggestion lookup failure leaves the error without suggestions', async () => {
  // Both the original call and the ir.model lookup throw.
  const searchRead = mockMethod(new Error("Odoo error: Model 'fake.model' does not exist"));
  const client = mockClient({ searchRead });

  const result = await callTool(client, 'search_read', { model: 'fake.model', domain: [] });

  assert.equal(result.success, false);
  assert.equal(result.error_type, 'invalid_model');
  assert.ok(result.suggestions === undefined);
});
