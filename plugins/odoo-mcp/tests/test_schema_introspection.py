"""Tests for schema introspection tools (list_models, get_model_fields)."""

from server import list_models, get_model_fields

list_models_fn = list_models.fn
get_model_fields_fn = get_model_fields.fn


# ── 1. Listing available models ──────────────────────────────────────────────


class TestListModels:
    def test_all_models_returned(self, mock_client):
        mock_client.search_read.return_value = [
            {"model": "res.partner", "name": "Contact"},
            {"model": "project.project", "name": "Project"},
        ]

        result = list_models_fn()

        assert result["success"] is True
        assert result["models"] == [
            {"model": "res.partner", "name": "Contact"},
            {"model": "project.project", "name": "Project"},
        ]
        mock_client.search_read.assert_called_once()

    def test_filtered_model_list(self, mock_client):
        """Keyword filter returns only matching models."""
        mock_client.search_read.return_value = [
            {"model": "project.project", "name": "Project"},
            {"model": "project.task", "name": "Task"},
        ]

        result = list_models_fn(filter="project")

        assert result["success"] is True
        assert len(result["models"]) == 2
        # Verify the domain passed to search_read contains an ilike filter
        call_args = mock_client.search_read.call_args
        domain = call_args.kwargs.get("domain") or call_args[1].get("domain") or call_args[0][1]
        assert any("ilike" in str(clause) and "project" in str(clause) for clause in domain)

    def test_no_matches_for_filter(self, mock_client):
        """Filter with no matches returns empty list and success: true."""
        mock_client.search_read.return_value = []

        result = list_models_fn(filter="nonexistent_xyz")

        assert result["success"] is True
        assert result["models"] == []

    def test_connection_failure(self, mock_client):
        mock_client.search_read.side_effect = Exception("Connection refused")

        result = list_models_fn()

        assert result["success"] is False
        assert "error" in result


# ── 2. Inspecting model fields ───────────────────────────────────────────────


class TestGetModelFields:
    def test_fields_returned_for_valid_model(self, mock_client):
        mock_client.execute.return_value = {
            "name": {"string": "Name", "type": "char", "required": True},
            "active": {"string": "Active", "type": "boolean", "required": False},
            "partner_id": {"string": "Customer", "type": "many2one", "required": False},
        }

        result = get_model_fields_fn(model="project.project")

        assert result["success"] is True
        fields = result["fields"]
        assert len(fields) == 3
        # Each field should have name, type, label, required
        field_names = {f["name"] for f in fields}
        assert field_names == {"name", "active", "partner_id"}
        for field in fields:
            assert "name" in field
            assert "type" in field
            assert "label" in field
            assert "required" in field

    def test_field_type_filtering(self, mock_client):
        """field_types filter returns only matching field types."""
        mock_client.execute.return_value = {
            "name": {"string": "Name", "type": "char", "required": True},
            "active": {"string": "Active", "type": "boolean", "required": False},
            "partner_id": {"string": "Customer", "type": "many2one", "required": False},
        }

        result = get_model_fields_fn(
            model="project.project", field_types=["char", "many2one"]
        )

        assert result["success"] is True
        fields = result["fields"]
        assert len(fields) == 2
        returned_types = {f["type"] for f in fields}
        assert returned_types == {"char", "many2one"}

    def test_invalid_model_name(self, mock_client):
        """Invalid model returns success: false with descriptive error."""
        mock_client.execute.side_effect = Exception(
            "Odoo error: Model 'fake.model' does not exist"
        )

        result = get_model_fields_fn(model="fake.model")

        assert result["success"] is False
        assert "error" in result

    def test_connection_failure(self, mock_client):
        mock_client.execute.side_effect = Exception("Connection refused")

        result = get_model_fields_fn(model="project.project")

        assert result["success"] is False
        assert "error" in result
