import { test } from 'node:test';
import assert from 'node:assert/strict';
import { callTool } from '../server/tools.js';
import { mockMethod, mockClient } from './helpers.js';

test('delete_record deletes a single record successfully', async () => {
  const unlink = mockMethod([true]);
  const client = mockClient({ unlink });

  const result = await callTool(client, 'delete_record', { model: 'res.partner', ids: [42] });

  assert.deepEqual(result, { success: true });
  assert.deepEqual(unlink.calls[0], ['res.partner', [42]]);
});

test('delete_record deletes multiple records in one call', async () => {
  const unlink = mockMethod([true]);
  const client = mockClient({ unlink });

  const result = await callTool(client, 'delete_record', { model: 'res.partner', ids: [1, 2, 3] });

  assert.deepEqual(result, { success: true });
  assert.deepEqual(unlink.calls[0], ['res.partner', [1, 2, 3]]);
});

test('delete_record surfaces invalid model / id errors', async () => {
  const unlink = mockMethod(new Error("Odoo error: Model 'fake.model' does not exist"));
  // model-suggestion lookup uses searchRead on ir.model
  const searchRead = mockMethod([[]]);
  const client = mockClient({ unlink, searchRead });

  const result = await callTool(client, 'delete_record', { model: 'fake.model', ids: [999] });

  assert.equal(result.success, false);
  assert.ok('error' in result);
});

test('delete_record surfaces connection failures', async () => {
  const unlink = mockMethod(new Error('Connection refused'));
  const client = mockClient({ unlink });

  const result = await callTool(client, 'delete_record', { model: 'res.partner', ids: [1] });

  assert.equal(result.success, false);
  assert.ok('error' in result);
});
