import { test } from 'node:test';
import assert from 'node:assert/strict';
import { callTool } from '../server/tools.js';
import { mockMethod, mockClient } from './helpers.js';

// ── 1. list_models ──────────────────────────────────────────────────────────

test('list_models returns all models when no filter is given', async () => {
  const searchRead = mockMethod([
    [
      { model: 'res.partner', name: 'Contact' },
      { model: 'project.project', name: 'Project' },
    ],
  ]);
  const client = mockClient({ searchRead });

  const result = await callTool(client, 'list_models', {});

  assert.equal(result.success, true);
  assert.deepEqual(result.models, [
    { model: 'res.partner', name: 'Contact' },
    { model: 'project.project', name: 'Project' },
  ]);
  assert.equal(searchRead.calls.length, 1);
});

test('list_models passes an ilike domain when filter is given', async () => {
  const searchRead = mockMethod([
    [
      { model: 'project.project', name: 'Project' },
      { model: 'project.task', name: 'Task' },
    ],
  ]);
  const client = mockClient({ searchRead });

  const result = await callTool(client, 'list_models', { filter: 'project' });

  assert.equal(result.success, true);
  assert.equal(result.models.length, 2);
  const domain = searchRead.calls[0][1];
  const flat = JSON.stringify(domain);
  assert.match(flat, /ilike/);
  assert.match(flat, /project/);
});

test('list_models with no filter matches returns empty list', async () => {
  const searchRead = mockMethod([[]]);
  const client = mockClient({ searchRead });

  const result = await callTool(client, 'list_models', { filter: 'nonexistent_xyz' });

  assert.equal(result.success, true);
  assert.deepEqual(result.models, []);
});

test('list_models surfaces connection failures as errors', async () => {
  const searchRead = mockMethod(new Error('Connection refused'));
  const client = mockClient({ searchRead });

  const result = await callTool(client, 'list_models', {});

  assert.equal(result.success, false);
  assert.ok('error' in result);
});

// ── 2. get_model_fields ─────────────────────────────────────────────────────

test('get_model_fields returns fields for a valid model', async () => {
  const fieldsGet = mockMethod([
    {
      name: { string: 'Name', type: 'char', required: true },
      active: { string: 'Active', type: 'boolean', required: false },
      partner_id: { string: 'Customer', type: 'many2one', required: false },
    },
  ]);
  const client = mockClient({ fieldsGet });

  const result = await callTool(client, 'get_model_fields', { model: 'project.project' });

  assert.equal(result.success, true);
  assert.equal(result.fields.length, 3);
  const names = new Set(result.fields.map((f) => f.name));
  assert.deepEqual(names, new Set(['name', 'active', 'partner_id']));
  for (const field of result.fields) {
    assert.ok('name' in field);
    assert.ok('type' in field);
    assert.ok('label' in field);
    assert.ok('required' in field);
  }
});

test('get_model_fields filters by field_types', async () => {
  const fieldsGet = mockMethod([
    {
      name: { string: 'Name', type: 'char', required: true },
      active: { string: 'Active', type: 'boolean', required: false },
      partner_id: { string: 'Customer', type: 'many2one', required: false },
    },
  ]);
  const client = mockClient({ fieldsGet });

  const result = await callTool(client, 'get_model_fields', {
    model: 'project.project',
    field_types: ['char', 'many2one'],
  });

  assert.equal(result.success, true);
  assert.equal(result.fields.length, 2);
  const types = new Set(result.fields.map((f) => f.type));
  assert.deepEqual(types, new Set(['char', 'many2one']));
});

test('get_model_fields surfaces invalid model errors', async () => {
  const fieldsGet = mockMethod(new Error("Odoo error: Model 'fake.model' does not exist"));
  // suggestModels uses searchRead on 'ir.model'; have it return no matches.
  const searchRead = mockMethod([[]]);
  const client = mockClient({ fieldsGet, searchRead });

  const result = await callTool(client, 'get_model_fields', { model: 'fake.model' });

  assert.equal(result.success, false);
  assert.ok('error' in result);
});

test('get_model_fields surfaces connection failures as errors', async () => {
  const fieldsGet = mockMethod(new Error('Connection refused'));
  const client = mockClient({ fieldsGet });

  const result = await callTool(client, 'get_model_fields', { model: 'project.project' });

  assert.equal(result.success, false);
  assert.ok('error' in result);
});
