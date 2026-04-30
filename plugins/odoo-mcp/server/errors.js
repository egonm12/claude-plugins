const INVALID_FIELD_RE = /Invalid field '([^']+)' on model '([^']+)'/;
const INVALID_MODEL_RE = /Model '([^']+)' does not exist/;
const ACCESS_DENIED_RE = /Access Denied/i;
const VALIDATION_RE = /Missing required fields/;

export function classifyError(err) {
  if (err && err.name === 'ConnectionError') return 'connection_error';
  const msg = String((err && err.message) ?? err ?? '');
  if (INVALID_FIELD_RE.test(msg)) return 'invalid_field';
  if (INVALID_MODEL_RE.test(msg)) return 'invalid_model';
  if (ACCESS_DENIED_RE.test(msg)) return 'access_denied';
  if (VALIDATION_RE.test(msg)) return 'validation_error';
  return 'unknown';
}

function levenshtein(a, b) {
  const la = a.length;
  const lb = b.length;
  if (la === 0) return lb;
  if (lb === 0) return la;
  const prev = new Array(lb + 1);
  const curr = new Array(lb + 1);
  for (let j = 0; j <= lb; j++) prev[j] = j;
  for (let i = 1; i <= la; i++) {
    curr[0] = i;
    for (let j = 1; j <= lb; j++) {
      const cost = a.charCodeAt(i - 1) === b.charCodeAt(j - 1) ? 0 : 1;
      curr[j] = Math.min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost);
    }
    for (let j = 0; j <= lb; j++) prev[j] = curr[j];
  }
  return prev[lb];
}

function similarity(a, b) {
  if (!a.length && !b.length) return 1;
  if (!a.length || !b.length) return 0;
  return 1 - levenshtein(a, b) / Math.max(a.length, b.length);
}

export function closeMatches(needle, haystack, { n = 5, cutoff = 0.4 } = {}) {
  const lcNeedle = String(needle).toLowerCase();
  return haystack
    .map((h) => ({ value: h, score: similarity(lcNeedle, String(h).toLowerCase()) }))
    .filter((entry) => entry.score >= cutoff)
    .sort((a, b) => b.score - a.score)
    .slice(0, n)
    .map((entry) => entry.value);
}

async function suggestFields(client, model, invalidField) {
  try {
    const raw = await client.fieldsGet(model);
    const matches = closeMatches(invalidField, Object.keys(raw));
    return matches.length ? matches : null;
  } catch {
    return null;
  }
}

async function suggestModels(client, invalidName) {
  try {
    const records = await client.searchRead('ir.model', [], { fields: ['model'], limit: 0 });
    const names = records.map((r) => r.model);
    const matches = closeMatches(invalidName, names);
    return matches.length ? matches : null;
  } catch {
    return null;
  }
}

export async function enrichError(err, { client, model } = {}) {
  const errorType = classifyError(err);
  const msg = String((err && err.message) ?? err ?? '');
  const result = { success: false, error: msg, error_type: errorType };

  if (errorType === 'invalid_field' && client && model) {
    const m = INVALID_FIELD_RE.exec(msg);
    if (m) {
      const invalidField = m[1];
      const matches = await suggestFields(client, model, invalidField);
      if (matches) {
        result.suggestions = { [invalidField]: matches };
        result.error = `Invalid field '${invalidField}' on model '${model}'. Did you mean: ${matches.join(', ')}?`;
      }
    }
  } else if (errorType === 'invalid_model' && client) {
    const m = INVALID_MODEL_RE.exec(msg);
    if (m) {
      const invalidName = m[1];
      const matches = await suggestModels(client, invalidName);
      if (matches) {
        result.suggestions = matches;
        result.error = `Model '${invalidName}' not found. Did you mean: ${matches.join(', ')}?`;
      }
    }
  }

  return result;
}
