import { enrichError } from './errors.js';

const domainSchema = {
  type: 'array',
  description: "Odoo search domain (list of triples and/or operators, e.g. [['name','ilike','Hertek']])",
  items: {},
};

const valuesSchema = {
  type: 'object',
  description: 'Field name to value map',
  additionalProperties: true,
};

const idsSchema = {
  type: 'array',
  description: 'Record IDs',
  items: { type: 'integer' },
};

export const TOOL_DEFINITIONS = [
  {
    name: 'search_read',
    description:
      'Search and read records from Odoo matching a domain. Returns records with the requested fields.',
    inputSchema: {
      type: 'object',
      required: ['model', 'domain'],
      properties: {
        model: { type: 'string', description: "Odoo model name (e.g. 'project.project')" },
        domain: domainSchema,
        fields: { type: 'array', items: { type: 'string' }, description: 'Fields to return (omit for all)' },
        limit: { type: 'integer', minimum: 0, description: 'Max records to return' },
        offset: { type: 'integer', minimum: 0, default: 0 },
        order: { type: 'string', description: "Sort order, e.g. 'create_date desc'" },
      },
      additionalProperties: false,
    },
  },
  {
    name: 'search_ids',
    description: 'Search for record IDs matching a domain. Returns ids and count.',
    inputSchema: {
      type: 'object',
      required: ['model', 'domain'],
      properties: {
        model: { type: 'string' },
        domain: domainSchema,
        limit: { type: 'integer', minimum: 0 },
        offset: { type: 'integer', minimum: 0, default: 0 },
        order: { type: 'string' },
      },
      additionalProperties: false,
    },
  },
  {
    name: 'search_count',
    description: 'Count records matching a domain without fetching their data.',
    inputSchema: {
      type: 'object',
      required: ['model', 'domain'],
      properties: {
        model: { type: 'string' },
        domain: domainSchema,
      },
      additionalProperties: false,
    },
  },
  {
    name: 'read_record',
    description: 'Read records by ID.',
    inputSchema: {
      type: 'object',
      required: ['model', 'ids'],
      properties: {
        model: { type: 'string' },
        ids: idsSchema,
        fields: { type: 'array', items: { type: 'string' } },
      },
      additionalProperties: false,
    },
  },
  {
    name: 'create_record',
    description: 'Create a new record. Returns the new id.',
    inputSchema: {
      type: 'object',
      required: ['model', 'values'],
      properties: {
        model: { type: 'string' },
        values: valuesSchema,
      },
      additionalProperties: false,
    },
  },
  {
    name: 'update_record',
    description: 'Update one or more existing records by ID.',
    inputSchema: {
      type: 'object',
      required: ['model', 'ids', 'values'],
      properties: {
        model: { type: 'string' },
        ids: idsSchema,
        values: valuesSchema,
      },
      additionalProperties: false,
    },
  },
  {
    name: 'delete_record',
    description: 'Delete records by ID (Odoo unlink).',
    inputSchema: {
      type: 'object',
      required: ['model', 'ids'],
      properties: {
        model: { type: 'string' },
        ids: idsSchema,
      },
      additionalProperties: false,
    },
  },
  {
    name: 'list_models',
    description: 'List available Odoo models, optionally filtered by keyword.',
    inputSchema: {
      type: 'object',
      properties: {
        filter: { type: 'string', description: 'Keyword filter on technical name or label' },
        limit: { type: 'integer', minimum: 1, default: 100 },
        offset: { type: 'integer', minimum: 0, default: 0 },
      },
      additionalProperties: false,
    },
  },
  {
    name: 'get_model_fields',
    description: 'Get field metadata (name, type, label, required) for an Odoo model.',
    inputSchema: {
      type: 'object',
      required: ['model'],
      properties: {
        model: { type: 'string' },
        field_types: {
          type: 'array',
          items: { type: 'string' },
          description: "Restrict to these field types (e.g. ['char','many2one'])",
        },
      },
      additionalProperties: false,
    },
  },
];

async function dispatch(client, name, args) {
  const a = args ?? {};
  switch (name) {
    case 'search_read': {
      const records = await client.searchRead(a.model, a.domain, {
        fields: a.fields, limit: a.limit, offset: a.offset, order: a.order,
      });
      return { success: true, records };
    }
    case 'search_ids': {
      const ids = await client.search(a.model, a.domain, {
        limit: a.limit, offset: a.offset, order: a.order,
      });
      return { success: true, ids, count: ids.length };
    }
    case 'search_count': {
      const count = await client.searchCount(a.model, a.domain);
      return { success: true, count };
    }
    case 'read_record': {
      const records = await client.read(a.model, a.ids, a.fields);
      return { success: true, records };
    }
    case 'create_record': {
      const id = await client.create(a.model, a.values);
      return { success: true, id };
    }
    case 'update_record': {
      const result = await client.write(a.model, a.ids, a.values);
      return { success: result };
    }
    case 'delete_record': {
      const result = await client.unlink(a.model, a.ids);
      return { success: result };
    }
    case 'list_models': {
      let domain = [];
      if (a.filter) {
        domain = ['|', ['model', 'ilike', a.filter], ['name', 'ilike', a.filter]];
      }
      const models = await client.searchRead('ir.model', domain, {
        fields: ['model', 'name'],
        limit: a.limit ?? 100,
        offset: a.offset ?? 0,
      });
      return { success: true, models };
    }
    case 'get_model_fields': {
      const raw = await client.fieldsGet(a.model);
      const types = a.field_types;
      const fields = Object.entries(raw)
        .filter(([, meta]) => !types || types.includes(meta.type))
        .map(([name, meta]) => ({
          name,
          type: meta.type ?? '',
          label: meta.string ?? '',
          required: !!meta.required,
        }));
      return { success: true, fields };
    }
    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}

export async function callTool(client, name, args) {
  try {
    return await dispatch(client, name, args);
  } catch (err) {
    return enrichError(err, { client, model: args?.model });
  }
}
