/**
 * Mock helpers for the Odoo MCP test suite.
 *
 * `mockMethod(behavior)` returns an async function that records each call.
 *  - If `behavior` is an array, sequential calls return its entries in order
 *    (Error instances are thrown). The last entry repeats once exhausted.
 *  - If `behavior` is a single Error instance, every call throws.
 *  - Otherwise every call resolves with that value.
 *
 * `mockClient(overrides)` returns an object exposing the OdooClient surface
 *  (searchRead, search, searchCount, read, create, write, unlink, fieldsGet)
 *  with each method defaulting to throwing 'unexpected call'. Override the
 *  ones a given test exercises.
 */

export function mockMethod(behavior) {
  const calls = [];
  const responses = Array.isArray(behavior) ? behavior : [behavior];
  let i = 0;
  const fn = async (...args) => {
    calls.push(args);
    const r = responses[Math.min(i, responses.length - 1)];
    i += 1;
    if (r instanceof Error) throw r;
    return r;
  };
  fn.calls = calls;
  return fn;
}

export function mockClient(overrides = {}) {
  const unset = (name) => async () => {
    throw new Error(`mockClient.${name} not configured for this test`);
  };
  return {
    searchRead: unset('searchRead'),
    search: unset('search'),
    searchCount: unset('searchCount'),
    read: unset('read'),
    create: unset('create'),
    write: unset('write'),
    unlink: unset('unlink'),
    fieldsGet: unset('fieldsGet'),
    ...overrides,
  };
}

export class ConnError extends Error {
  constructor(msg) {
    super(msg);
    this.name = 'ConnectionError';
  }
}
