"""Tests for LLM-friendly error messages with suggestions and classification."""

import server

search_read = server.search_read.fn
create_record = server.create_record.fn
read_record = server.read_record.fn
update_record = server.update_record.fn
search_ids = server.search_ids.fn
delete_record = server.delete_record.fn
list_models = server.list_models.fn
get_model_fields = server.get_model_fields.fn


# ── 1. Invalid field name suggestions ───────────────────────────────────────


class TestInvalidFieldSuggestions:
    def test_search_read_suggests_valid_fields(self, mock_client):
        """When search_read fails due to an invalid field, suggest close matches."""
        mock_client.search_read.side_effect = Exception(
            "Odoo error: Invalid field 'nme' on model 'res.partner'"
        )
        mock_client.execute.return_value = {
            "name": {"string": "Name", "type": "char", "required": True},
            "email": {"string": "Email", "type": "char", "required": False},
            "phone": {"string": "Phone", "type": "char", "required": False},
        }

        result = search_read(
            model="res.partner",
            domain=[],
            fields=["nme"],
        )

        assert result["success"] is False
        assert result["error_type"] == "invalid_field"
        assert "suggestions" in result
        assert "nme" in result["suggestions"]
        assert "name" in result["suggestions"]["nme"]

    def test_create_record_suggests_valid_fields(self, mock_client):
        """When create_record fails due to an invalid field, suggest close matches."""
        mock_client.create.side_effect = Exception(
            "Odoo error: Invalid field 'emial' on model 'res.partner'"
        )
        mock_client.execute.return_value = {
            "name": {"string": "Name", "type": "char", "required": True},
            "email": {"string": "Email", "type": "char", "required": False},
        }

        result = create_record(
            model="res.partner",
            values={"emial": "test@example.com"},
        )

        assert result["success"] is False
        assert result["error_type"] == "invalid_field"
        assert "emial" in result["suggestions"]
        assert "email" in result["suggestions"]["emial"]

    def test_suggestions_sorted_by_similarity(self, mock_client):
        """Suggested field names are ordered by similarity to the invalid name."""
        mock_client.search_read.side_effect = Exception(
            "Odoo error: Invalid field 'naem' on model 'res.partner'"
        )
        mock_client.execute.return_value = {
            "name": {"string": "Name", "type": "char", "required": True},
            "email": {"string": "Email", "type": "char", "required": False},
            "phone": {"string": "Phone", "type": "char", "required": False},
            "active": {"string": "Active", "type": "boolean", "required": False},
        }

        result = search_read(model="res.partner", domain=[], fields=["naem"])

        assert result["success"] is False
        suggestions = result["suggestions"]["naem"]
        assert suggestions[0] == "name"

    def test_suggestions_capped_at_five(self, mock_client):
        """At most 5 suggestions are returned per invalid field."""
        mock_client.search_read.side_effect = Exception(
            "Odoo error: Invalid field 'nam' on model 'res.partner'"
        )
        many_fields = {
            f"name_{i}": {"string": f"Name {i}", "type": "char", "required": False}
            for i in range(20)
        }
        mock_client.execute.return_value = many_fields

        result = search_read(model="res.partner", domain=[], fields=["nam"])

        assert result["success"] is False
        assert len(result["suggestions"]["nam"]) <= 5

    def test_error_string_includes_suggestions(self, mock_client):
        """The error string is human-readable and includes suggestions."""
        mock_client.search_read.side_effect = Exception(
            "Odoo error: Invalid field 'nme' on model 'res.partner'"
        )
        mock_client.execute.return_value = {
            "name": {"string": "Name", "type": "char", "required": True},
        }

        result = search_read(model="res.partner", domain=[], fields=["nme"])

        assert "nme" in result["error"]
        assert "name" in result["error"]


# ── 2. Invalid model name suggestions ──────────────────────────────────────


class TestInvalidModelSuggestions:
    def test_suggests_valid_models(self, mock_client):
        """When a tool call uses a non-existent model, suggest close matches."""
        mock_client.search_read.side_effect = Exception(
            "Odoo error: Model 'res.parner' does not exist"
        )
        mock_client.search_read.side_effect = [
            Exception("Odoo error: Model 'res.parner' does not exist"),
            # Second call is the model lookup for suggestions
            [
                {"model": "res.partner", "name": "Contact"},
                {"model": "res.partner.bank", "name": "Bank Account"},
                {"model": "res.partner.category", "name": "Partner Tag"},
            ],
        ]

        result = search_read(model="res.parner", domain=[])

        assert result["success"] is False
        assert result["error_type"] == "invalid_model"
        assert "suggestions" in result
        assert "res.partner" in result["suggestions"]

    def test_model_suggestions_capped_at_five(self, mock_client):
        """At most 5 model suggestions are returned."""
        models = [
            {"model": f"res.partner.{i}", "name": f"Partner {i}"}
            for i in range(20)
        ]
        mock_client.search_read.side_effect = [
            Exception("Odoo error: Model 'res.parner' does not exist"),
            models,
        ]

        result = search_read(model="res.parner", domain=[])

        assert result["success"] is False
        assert len(result["suggestions"]) <= 5

    def test_error_string_includes_model_suggestions(self, mock_client):
        """The error string includes suggested model names."""
        mock_client.search_read.side_effect = [
            Exception("Odoo error: Model 'res.parner' does not exist"),
            [{"model": "res.partner", "name": "Contact"}],
        ]

        result = search_read(model="res.parner", domain=[])

        assert "res.parner" in result["error"]
        assert "res.partner" in result["error"]


# ── 3. Error classification ────────────────────────────────────────────────


class TestErrorClassification:
    def test_invalid_field_classified(self, mock_client):
        mock_client.search_read.side_effect = Exception(
            "Odoo error: Invalid field 'xyz' on model 'res.partner'"
        )
        mock_client.execute.return_value = {}

        result = search_read(model="res.partner", domain=[])

        assert result["error_type"] == "invalid_field"

    def test_invalid_model_classified(self, mock_client):
        mock_client.search_read.side_effect = [
            Exception("Odoo error: Model 'fake.model' does not exist"),
            [],
        ]

        result = search_read(model="fake.model", domain=[])

        assert result["error_type"] == "invalid_model"

    def test_access_denied_classified(self, mock_client):
        mock_client.search_read.side_effect = Exception(
            "Odoo error: Access Denied"
        )

        result = search_read(model="res.partner", domain=[])

        assert result["error_type"] == "access_denied"

    def test_validation_error_classified(self, mock_client):
        mock_client.create.side_effect = Exception(
            "Odoo error: Missing required fields: name"
        )

        result = create_record(model="res.partner", values={})

        assert result["error_type"] == "validation_error"

    def test_connection_error_classified(self, mock_client):
        mock_client.search_read.side_effect = ConnectionError(
            "Failed to connect to Odoo: Connection refused"
        )

        result = search_read(model="res.partner", domain=[])

        assert result["error_type"] == "connection_error"

    def test_unknown_error_classified(self, mock_client):
        mock_client.search_read.side_effect = Exception(
            "Something completely unexpected"
        )

        result = search_read(model="res.partner", domain=[])

        assert result["error_type"] == "unknown"

    def test_unknown_error_has_no_suggestions(self, mock_client):
        mock_client.search_read.side_effect = Exception("Unexpected error")

        result = search_read(model="res.partner", domain=[])

        assert "suggestions" not in result


# ── 4. Backward compatibility ──────────────────────────────────────────────


class TestBackwardCompatibility:
    def test_error_response_contains_success_false(self, mock_client):
        mock_client.search_read.side_effect = Exception(
            "Odoo error: Invalid field 'nme' on model 'res.partner'"
        )
        mock_client.execute.return_value = {
            "name": {"string": "Name", "type": "char", "required": True},
        }

        result = search_read(model="res.partner", domain=[])

        assert result["success"] is False

    def test_error_response_contains_error_string(self, mock_client):
        mock_client.search_read.side_effect = Exception(
            "Odoo error: Invalid field 'nme' on model 'res.partner'"
        )
        mock_client.execute.return_value = {
            "name": {"string": "Name", "type": "char", "required": True},
        }

        result = search_read(model="res.partner", domain=[])

        assert isinstance(result["error"], str)
        assert len(result["error"]) > 0

    def test_new_fields_are_additive(self, mock_client):
        """error_type and suggestions are additional fields, not replacements."""
        mock_client.search_read.side_effect = Exception(
            "Odoo error: Invalid field 'nme' on model 'res.partner'"
        )
        mock_client.execute.return_value = {
            "name": {"string": "Name", "type": "char", "required": True},
        }

        result = search_read(model="res.partner", domain=[])

        assert "success" in result
        assert "error" in result
        assert "error_type" in result


# ── 5. Suggestion resilience ───────────────────────────────────────────────


class TestSuggestionResilience:
    def test_field_suggestion_lookup_failure_returns_error_without_suggestions(
        self, mock_client
    ):
        """If fetching fields for suggestions fails, return error without suggestions."""
        mock_client.search_read.side_effect = Exception(
            "Odoo error: Invalid field 'nme' on model 'res.partner'"
        )
        mock_client.execute.side_effect = Exception("Connection lost")

        result = search_read(model="res.partner", domain=[])

        assert result["success"] is False
        assert result["error_type"] == "invalid_field"
        assert "suggestions" not in result or result["suggestions"] == {}

    def test_model_suggestion_lookup_failure_returns_error_without_suggestions(
        self, mock_client
    ):
        """If fetching models for suggestions fails, return error without suggestions."""
        mock_client.search_read.side_effect = Exception(
            "Odoo error: Model 'fake.model' does not exist"
        )

        result = search_read(model="fake.model", domain=[])

        assert result["success"] is False
        assert result["error_type"] == "invalid_model"
        # Should not raise, even though the model lookup for suggestions
        # would also fail (since search_read is what we use for model lookup)
