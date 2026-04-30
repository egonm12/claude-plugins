#!/usr/bin/env python3
"""Odoo MCP Server with API key authentication support.

This MCP server provides tools for interacting with Odoo via XML-RPC,
supporting API key authentication for accounts with 2FA enabled.
"""

import difflib
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastmcp import FastMCP

from odoo_client import OdooClient

# Load environment variables from opencode .env file
opencode_env = Path.home() / ".config" / "opencode" / ".env"
if opencode_env.exists():
    load_dotenv(opencode_env, override=True)

# Initialize FastMCP server
mcp = FastMCP("odoo")

# Validate required environment variables
required_env_vars = {
    "ODOO_URL": os.getenv("ODOO_URL"),
    "ODOO_DB": os.getenv("ODOO_DB"),
    "ODOO_USERNAME": os.getenv("ODOO_USERNAME"),
    "ODOO_PASSWORD": os.getenv("ODOO_PASSWORD")
}

missing_vars = [key for key, value in required_env_vars.items() if not value]
if missing_vars:
    print(f"Error: Missing required environment variables: {', '.join(missing_vars)}", file=sys.stderr)
    print("Please set these in your MCP server configuration.", file=sys.stderr)
    sys.exit(1)

# Initialize Odoo client with validated environment variables
try:
    client = OdooClient(
        url=required_env_vars["ODOO_URL"],
        db=required_env_vars["ODOO_DB"],
        username=required_env_vars["ODOO_USERNAME"],
        api_key=required_env_vars["ODOO_PASSWORD"]  # ODOO_PASSWORD env var contains the API key
    )
except Exception as e:
    print(f"Error initializing Odoo client: {e}", file=sys.stderr)
    sys.exit(1)


# ── Error enrichment helpers ────────────────────────────────────────────────

_INVALID_FIELD_RE = re.compile(r"Invalid field '([^']+)' on model '([^']+)'")
_INVALID_MODEL_RE = re.compile(r"Model '([^']+)' does not exist")
_ACCESS_DENIED_RE = re.compile(r"Access Denied", re.IGNORECASE)
_VALIDATION_RE = re.compile(r"Missing required fields")


def _classify_error(error: Exception) -> str:
    """Classify an exception into an error type based on message patterns."""
    if isinstance(error, ConnectionError):
        return "connection_error"
    msg = str(error)
    if _INVALID_FIELD_RE.search(msg):
        return "invalid_field"
    if _INVALID_MODEL_RE.search(msg):
        return "invalid_model"
    if _ACCESS_DENIED_RE.search(msg):
        return "access_denied"
    if _VALIDATION_RE.search(msg):
        return "validation_error"
    return "unknown"


def _suggest_fields(model: str, invalid_field: str) -> Dict[str, List[str]]:
    """Fetch valid field names for a model and return fuzzy matches."""
    try:
        raw_fields = client.execute(
            model, 'fields_get', [], attributes=['string', 'type', 'required']
        )
        valid_names = list(raw_fields.keys())
        matches = difflib.get_close_matches(invalid_field, valid_names, n=5, cutoff=0.4)
        if matches:
            return {invalid_field: matches}
    except Exception:
        pass
    return {}


def _suggest_models(invalid_model: str) -> List[str]:
    """Fetch valid model names and return fuzzy matches."""
    try:
        records = client.search_read(
            model='ir.model',
            domain=[],
            fields=['model'],
            limit=0,
        )
        valid_models = [r['model'] for r in records]
        return difflib.get_close_matches(invalid_model, valid_models, n=5, cutoff=0.4)
    except Exception:
        return []


def _enrich_error(error: Exception, model: Optional[str] = None) -> Dict[str, Any]:
    """Build an enriched error response with classification and suggestions."""
    error_type = _classify_error(error)
    msg = str(error)
    result: Dict[str, Any] = {"success": False, "error": msg, "error_type": error_type}

    if error_type == "invalid_field" and model:
        match = _INVALID_FIELD_RE.search(msg)
        if match:
            invalid_field = match.group(1)
            suggestions = _suggest_fields(model, invalid_field)
            if suggestions:
                result["suggestions"] = suggestions
                field_list = ", ".join(suggestions[invalid_field])
                result["error"] = (
                    f"Invalid field '{invalid_field}' on model '{model}'. "
                    f"Did you mean: {field_list}?"
                )

    elif error_type == "invalid_model":
        match = _INVALID_MODEL_RE.search(msg)
        if match:
            invalid_name = match.group(1)
            suggestions = _suggest_models(invalid_name)
            if suggestions:
                result["suggestions"] = suggestions
                model_list = ", ".join(suggestions)
                result["error"] = (
                    f"Model '{invalid_name}' not found. "
                    f"Did you mean: {model_list}?"
                )

    return result


@mcp.tool()
def search_read(
    model: str,
    domain: List[Any],
    fields: Optional[List[str]] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    order: Optional[str] = None
) -> Dict[str, Any]:
    """
    Search and read records from Odoo.

    This tool searches for records matching a domain and returns their data.
    Commonly used for finding projects, tasks, employees, etc.

    Args:
        model: Odoo model name (e.g., 'project.project', 'project.task',
               'account.analytic.line', 'hr.employee')
        domain: Search criteria as list of tuples
                (e.g., [['name', 'ilike', 'Hertek']])
        fields: Specific fields to return (None = all fields)
        limit: Maximum number of records to return
        offset: Number of records to skip (for pagination)
        order: Sort order (e.g., 'name desc', 'create_date asc')

    Returns:
        Dictionary with 'success' and either 'records' (list of dicts) or 'error' (string)

    Example:
        search_read(
            model='project.project',
            domain=[['name', 'ilike', 'Hertek']],
            fields=['id', 'name'],
            limit=10
        )
    """
    try:
        records = client.search_read(
            model=model,
            domain=domain,
            fields=fields,
            limit=limit,
            offset=offset,
            order=order
        )
        return {"success": True, "records": records}
    except Exception as e:
        return _enrich_error(e, model=model)


@mcp.tool()
def create_record(model: str, values: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a new record in Odoo.

    This tool creates a new record with the specified field values.
    Commonly used for creating timesheet entries.

    Args:
        model: Odoo model name (e.g., 'account.analytic.line')
        values: Dictionary of field names and values
                (e.g., {'date': '2025-01-15', 'project_id': 1814,
                        'task_id': 23004, 'name': 'Development work',
                        'unit_amount': 4.5, 'employee_id': 50})

    Returns:
        Dictionary with 'success' and either 'id' (int) or 'error' (string)

    Example:
        create_record(
            model='account.analytic.line',
            values={
                'date': '2025-01-15',
                'project_id': 1814,
                'task_id': 23004,
                'name': 'Development / Programming',
                'unit_amount': 4.5,
                'employee_id': 50
            }
        )
    """
    try:
        record_id = client.create(model=model, values=values)
        return {"success": True, "id": record_id}
    except Exception as e:
        return _enrich_error(e, model=model)


@mcp.tool()
def read_record(
    model: str,
    ids: List[int],
    fields: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Read records by ID from Odoo.

    This tool retrieves specific records by their IDs.

    Args:
        model: Odoo model name
        ids: List of record IDs to read
        fields: Specific fields to return (None = all fields)

    Returns:
        Dictionary with 'success' and either 'records' (list of dicts) or 'error' (string)

    Example:
        read_record(
            model='project.task',
            ids=[23004, 23005],
            fields=['id', 'name', 'project_id']
        )
    """
    try:
        records = client.read(model=model, ids=ids, fields=fields)
        return {"success": True, "records": records}
    except Exception as e:
        return _enrich_error(e, model=model)


@mcp.tool()
def update_record(
    model: str,
    ids: List[int],
    values: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Update existing records in Odoo.

    This tool updates one or more records with new field values.

    Args:
        model: Odoo model name
        ids: List of record IDs to update
        values: Dictionary of field names and new values

    Returns:
        Dictionary with 'success' (bool) and optional 'error' (string)

    Example:
        update_record(
            model='account.analytic.line',
            ids=[12345],
            values={'unit_amount': 5.0, 'name': 'Updated description'}
        )
    """
    try:
        result = client.write(model=model, ids=ids, values=values)
        return {"success": result}
    except Exception as e:
        return _enrich_error(e, model=model)


@mcp.tool()
def search_ids(
    model: str,
    domain: List[Any],
    limit: Optional[int] = None,
    offset: int = 0,
    order: Optional[str] = None
) -> Dict[str, Any]:
    """
    Search for record IDs matching a domain.

    This tool searches for records and returns only their IDs (not full data).
    Useful for counting records or getting IDs for subsequent operations.

    Args:
        model: Odoo model name
        domain: Search criteria as list of tuples
        limit: Maximum number of IDs to return
        offset: Number of records to skip
        order: Sort order

    Returns:
        Dictionary with 'success' and either 'ids' (list of ints) or 'error' (string)

    Example:
        search_ids(
            model='project.project',
            domain=[['name', 'ilike', 'Hertek'], ['active', '=', True]],
            limit=5
        )
    """
    try:
        ids = client.search(
            model=model,
            domain=domain,
            limit=limit,
            offset=offset,
            order=order
        )
        return {"success": True, "ids": ids, "count": len(ids)}
    except Exception as e:
        return _enrich_error(e, model=model)


@mcp.tool()
def search_count(
    model: str,
    domain: List[Any],
) -> Dict[str, Any]:
    """
    Count records matching a domain without fetching them.

    This tool returns only the count of matching records, which is faster
    than search_read when you only need to know how many records exist.

    Args:
        model: Odoo model name (e.g., 'project.task', 'res.partner')
        domain: Search criteria as list of tuples
                (e.g., [['active', '=', True]])

    Returns:
        Dictionary with 'success' and either 'count' (int) or 'error' (string)

    Example:
        search_count(
            model='project.task',
            domain=[['project_id', '=', 42], ['stage_id.name', '!=', 'Done']]
        )
    """
    try:
        count = client.search_count(model=model, domain=domain)
        return {"success": True, "count": count}
    except Exception as e:
        return _enrich_error(e, model=model)


@mcp.tool()
def delete_record(model: str, ids: List[int]) -> Dict[str, Any]:
    """
    Delete records from Odoo.

    This tool deletes one or more records by their IDs using the Odoo unlink method.

    Args:
        model: Odoo model name
        ids: List of record IDs to delete

    Returns:
        Dictionary with 'success' (bool) and optional 'error' (string)

    Example:
        delete_record(model='account.analytic.line', ids=[12345, 12346])
    """
    try:
        result = client.unlink(model=model, ids=ids)
        return {"success": result}
    except Exception as e:
        return _enrich_error(e, model=model)


@mcp.tool()
def list_models(
    filter: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> Dict[str, Any]:
    """
    List available models in the Odoo instance.

    Useful for discovering which models exist before querying them
    with search_read or get_model_fields.

    Args:
        filter: Optional keyword to filter models by technical name or display label
        limit: Maximum number of models to return (default 100)
        offset: Number of records to skip (for pagination)

    Returns:
        Dictionary with 'success' and either 'models' (list of dicts with
        'model' and 'name' keys) or 'error' (string)

    Example:
        list_models(filter='project', limit=10)
    """
    try:
        domain: List[Any] = []
        if filter:
            domain = [
                '|',
                ['model', 'ilike', filter],
                ['name', 'ilike', filter],
            ]

        records = client.search_read(
            model='ir.model',
            domain=domain,
            fields=['model', 'name'],
            limit=limit,
            offset=offset,
        )
        return {"success": True, "models": records}
    except Exception as e:
        return _enrich_error(e)


@mcp.tool()
def get_model_fields(
    model: str,
    field_types: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Get field metadata for an Odoo model.

    Returns the fields defined on a model with their type, label, and
    whether they are required. Useful for understanding a model's schema
    before constructing queries or creating records.

    Args:
        model: Odoo model name (e.g., 'project.project')
        field_types: Optional list of field types to include
                     (e.g., ['char', 'many2one']). Returns all types if omitted.

    Returns:
        Dictionary with 'success' and either 'fields' (list of dicts with
        'name', 'type', 'label', 'required' keys) or 'error' (string)

    Example:
        get_model_fields(model='project.project', field_types=['char', 'many2one'])
    """
    try:
        raw_fields = client.execute(
            model, 'fields_get', [], attributes=['string', 'type', 'required']
        )

        fields = [
            {
                "name": field_name,
                "type": meta.get("type", ""),
                "label": meta.get("string", ""),
                "required": meta.get("required", False),
            }
            for field_name, meta in raw_fields.items()
            if field_types is None or meta.get("type") in field_types
        ]

        return {"success": True, "fields": fields}
    except Exception as e:
        return _enrich_error(e, model=model)


if __name__ == "__main__":
    # Run the MCP server with STDIO transport
    mcp.run(transport="stdio")
