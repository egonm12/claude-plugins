import { test } from 'node:test';
import assert from 'node:assert/strict';
import { callTool } from '../server/tools.js';
import { mockMethod, mockClient } from './helpers.js';

// ── search_read ──────────────────────────────────────────────────────────────

test('search_read returns matching records', async () => {
  const searchRead = mockMethod([
    [
      { id: 1, name: 'Project Alpha' },
      { id: 2, name: 'Project Beta' },
    ],
  ]);
  const client = mockClient({ searchRead });

  const result = await callTool(client, 'search_read', {
    model: 'project.project',
    domain: [['name', 'ilike', 'Project']],
    fields: ['id', 'name'],
    limit: 10,
  });

  assert.deepEqual(result, {
    success: true,
    records: [
      { id: 1, name: 'Project Alpha' },
      { id: 2, name: 'Project Beta' },
    ],
  });
  assert.equal(searchRead.calls.length, 1);
  assert.deepEqual(searchRead.calls[0][0], 'project.project');
  assert.deepEqual(searchRead.calls[0][1], [['name', 'ilike', 'Project']]);
  assert.deepEqual(searchRead.calls[0][2], {
    fields: ['id', 'name'],
    limit: 10,
    offset: undefined,
    order: undefined,
  });
});

test('search_read passes all optional params through', async () => {
  const searchRead = mockMethod([[]]);
  const client = mockClient({ searchRead });

  await callTool(client, 'search_read', {
    model: 'res.partner',
    domain: [],
    fields: ['name'],
    limit: 5,
    offset: 10,
    order: 'name asc',
  });

  assert.deepEqual(searchRead.calls[0][2], {
    fields: ['name'],
    limit: 5,
    offset: 10,
    order: 'name asc',
  });
});

test('search_read returns enriched error on exception', async () => {
  const searchRead = mockMethod(new Error('Connection refused'));
  const client = mockClient({ searchRead });

  const result = await callTool(client, 'search_read', { model: 'res.partner', domain: [] });

  assert.equal(result.success, false);
  assert.equal(result.error, 'Connection refused');
  assert.equal(result.error_type, 'unknown');
});

// ── create_record ────────────────────────────────────────────────────────────

test('create_record returns created id', async () => {
  const create = mockMethod([42]);
  const client = mockClient({ create });

  const result = await callTool(client, 'create_record', {
    model: 'account.analytic.line',
    values: { name: 'Dev work', unit_amount: 4.0 },
  });

  assert.deepEqual(result, { success: true, id: 42 });
  assert.deepEqual(create.calls[0], ['account.analytic.line', { name: 'Dev work', unit_amount: 4.0 }]);
});

test('create_record returns error on exception', async () => {
  const create = mockMethod(new Error('Access denied'));
  const client = mockClient({ create });

  const result = await callTool(client, 'create_record', {
    model: 'res.partner',
    values: { name: 'Test' },
  });

  assert.equal(result.success, false);
  assert.equal(result.error, 'Access denied');
});

// ── read_record ──────────────────────────────────────────────────────────────

test('read_record returns records by id', async () => {
  const read = mockMethod([
    [
      { id: 10, name: 'Task A' },
      { id: 11, name: 'Task B' },
    ],
  ]);
  const client = mockClient({ read });

  const result = await callTool(client, 'read_record', {
    model: 'project.task',
    ids: [10, 11],
    fields: ['id', 'name'],
  });

  assert.deepEqual(result, {
    success: true,
    records: [
      { id: 10, name: 'Task A' },
      { id: 11, name: 'Task B' },
    ],
  });
  assert.deepEqual(read.calls[0], ['project.task', [10, 11], ['id', 'name']]);
});

test('read_record returns error on exception', async () => {
  const read = mockMethod(new Error('Record not found'));
  const client = mockClient({ read });

  const result = await callTool(client, 'read_record', { model: 'project.task', ids: [999] });

  assert.equal(result.success, false);
  assert.equal(result.error, 'Record not found');
});

// ── update_record ────────────────────────────────────────────────────────────

test('update_record returns success on write', async () => {
  const write = mockMethod([true]);
  const client = mockClient({ write });

  const result = await callTool(client, 'update_record', {
    model: 'account.analytic.line',
    ids: [100],
    values: { unit_amount: 8.0 },
  });

  assert.deepEqual(result, { success: true });
  assert.deepEqual(write.calls[0], ['account.analytic.line', [100], { unit_amount: 8.0 }]);
});

test('update_record returns error on exception', async () => {
  const write = mockMethod(new Error('Validation error'));
  const client = mockClient({ write });

  const result = await callTool(client, 'update_record', {
    model: 'res.partner',
    ids: [1],
    values: { name: '' },
  });

  assert.equal(result.success, false);
  assert.equal(result.error, 'Validation error');
});

// ── search_ids ───────────────────────────────────────────────────────────────

test('search_ids returns ids and count', async () => {
  const search = mockMethod([[1, 2, 3]]);
  const client = mockClient({ search });

  const result = await callTool(client, 'search_ids', {
    model: 'project.project',
    domain: [['active', '=', true]],
    limit: 100,
  });

  assert.deepEqual(result, { success: true, ids: [1, 2, 3], count: 3 });
});

test('search_ids returns empty list when no matches', async () => {
  const search = mockMethod([[]]);
  const client = mockClient({ search });

  const result = await callTool(client, 'search_ids', {
    model: 'res.partner',
    domain: [['id', '=', -1]],
  });

  assert.deepEqual(result, { success: true, ids: [], count: 0 });
});

test('search_ids returns error on exception', async () => {
  const search = mockMethod(new Error('Timeout'));
  const client = mockClient({ search });

  const result = await callTool(client, 'search_ids', { model: 'res.partner', domain: [] });

  assert.equal(result.success, false);
  assert.equal(result.error, 'Timeout');
});

// ── search_count ─────────────────────────────────────────────────────────────

test('search_count returns count for matching records', async () => {
  const searchCount = mockMethod([42]);
  const client = mockClient({ searchCount });

  const result = await callTool(client, 'search_count', {
    model: 'project.project',
    domain: [['active', '=', true]],
  });

  assert.deepEqual(result, { success: true, count: 42 });
});

test('search_count returns zero when no matches', async () => {
  const searchCount = mockMethod([0]);
  const client = mockClient({ searchCount });

  const result = await callTool(client, 'search_count', {
    model: 'res.partner',
    domain: [['id', '=', -1]],
  });

  assert.deepEqual(result, { success: true, count: 0 });
});

test('search_count returns error on exception', async () => {
  const searchCount = mockMethod(new Error('Access denied'));
  const client = mockClient({ searchCount });

  const result = await callTool(client, 'search_count', { model: 'res.partner', domain: [] });

  assert.equal(result.success, false);
  assert.equal(result.error, 'Access denied');
});
