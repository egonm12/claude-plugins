import xmlrpc from 'xmlrpc';

export class ConnectionError extends Error {
  constructor(message) {
    super(message);
    this.name = 'ConnectionError';
  }
}

export class OdooClient {
  constructor({ url, db, username, apiKey, timeoutMs = 30000 }) {
    if (!url || !db || !username || !apiKey) {
      throw new Error('OdooClient requires url, db, username, and apiKey');
    }
    this.url = String(url).replace(/\/+$/, '');
    this.db = db;
    this.username = username;
    this.apiKey = apiKey;
    this.timeoutMs = timeoutMs;
    this.uid = null;
    this._common = null;
    this._models = null;
  }

  _buildClient(path) {
    const u = new URL(this.url + path);
    const opts = {
      host: u.hostname,
      port: u.port ? Number(u.port) : (u.protocol === 'https:' ? 443 : 80),
      path: u.pathname,
    };
    return u.protocol === 'https:' ? xmlrpc.createSecureClient(opts) : xmlrpc.createClient(opts);
  }

  _methodCall(client, method, params) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error(`Odoo request timed out after ${this.timeoutMs}ms`));
      }, this.timeoutMs);
      client.methodCall(method, params, (err, value) => {
        clearTimeout(timer);
        if (err) reject(err);
        else resolve(value);
      });
    });
  }

  async _ensureConnected() {
    if (this.uid && this._models) return;
    this.uid = null;
    this._models = null;
    if (!this._common) this._common = this._buildClient('/xmlrpc/2/common');

    let uid;
    try {
      uid = await this._methodCall(this._common, 'authenticate', [
        this.db, this.username, this.apiKey, {},
      ]);
    } catch (err) {
      throw new ConnectionError(`Failed to connect to Odoo: ${err.message ?? err}`);
    }
    if (!uid || typeof uid !== 'number') {
      throw new ConnectionError('Authentication failed - check credentials');
    }
    this.uid = uid;
    this._models = this._buildClient('/xmlrpc/2/object');
  }

  async execute(model, method, args = [], kwargs = {}) {
    await this._ensureConnected();
    try {
      return await this._methodCall(this._models, 'execute_kw', [
        this.db, this.uid, this.apiKey, model, method, args, kwargs,
      ]);
    } catch (err) {
      if (err && err.faultString) throw new Error(`Odoo error: ${err.faultString}`);
      throw new Error(`Operation failed: ${err.message ?? err}`);
    }
  }

  searchRead(model, domain, { fields, limit, offset = 0, order } = {}) {
    const kwargs = {};
    if (fields) kwargs.fields = fields;
    if (limit) kwargs.limit = limit;
    if (offset > 0) kwargs.offset = offset;
    if (order) kwargs.order = order;
    return this.execute(model, 'search_read', [domain], kwargs);
  }

  search(model, domain, { limit, offset = 0, order } = {}) {
    const kwargs = {};
    if (limit) kwargs.limit = limit;
    if (offset > 0) kwargs.offset = offset;
    if (order) kwargs.order = order;
    return this.execute(model, 'search', [domain], kwargs);
  }

  searchCount(model, domain) {
    return this.execute(model, 'search_count', [domain]);
  }

  read(model, ids, fields) {
    if (!ids || ids.length === 0) return Promise.resolve([]);
    const kwargs = {};
    if (fields) kwargs.fields = fields;
    return this.execute(model, 'read', [ids], kwargs);
  }

  create(model, values) {
    return this.execute(model, 'create', [values]);
  }

  write(model, ids, values) {
    return this.execute(model, 'write', [ids, values]);
  }

  unlink(model, ids) {
    return this.execute(model, 'unlink', [ids]);
  }

  fieldsGet(model, attributes = ['string', 'type', 'required']) {
    return this.execute(model, 'fields_get', [], { attributes });
  }
}
