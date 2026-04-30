"""Tests for core Odoo MCP tools (search_read, create, read, update, search)."""

import server

search_read = server.search_read.fn
create_record = server.create_record.fn
read_record = server.read_record.fn
update_record = server.update_record.fn
search_ids = server.search_ids.fn
search_count = server.search_count.fn


# ── search_read ──────────────────────────────────────────────────────────────


class TestSearchRead:
    def test_returns_matching_records(self, mock_client):
        mock_client.search_read.return_value = [
            {"id": 1, "name": "Project Alpha"},
            {"id": 2, "name": "Project Beta"},
        ]

        result = search_read(
            model="project.project",
            domain=[["name", "ilike", "Project"]],
            fields=["id", "name"],
            limit=10,
        )

        assert result == {
            "success": True,
            "records": [
                {"id": 1, "name": "Project Alpha"},
                {"id": 2, "name": "Project Beta"},
            ],
        }
        mock_client.search_read.assert_called_once_with(
            model="project.project",
            domain=[["name", "ilike", "Project"]],
            fields=["id", "name"],
            limit=10,
            offset=0,
            order=None,
        )

    def test_passes_all_optional_params(self, mock_client):
        mock_client.search_read.return_value = []

        search_read(
            model="res.partner",
            domain=[],
            fields=["name"],
            limit=5,
            offset=10,
            order="name asc",
        )

        mock_client.search_read.assert_called_once_with(
            model="res.partner",
            domain=[],
            fields=["name"],
            limit=5,
            offset=10,
            order="name asc",
        )

    def test_returns_error_on_exception(self, mock_client):
        mock_client.search_read.side_effect = Exception("Connection refused")

        result = search_read(model="res.partner", domain=[])

        assert result["success"] is False
        assert result["error"] == "Connection refused"


# ── create_record ────────────────────────────────────────────────────────────


class TestCreateRecord:
    def test_returns_created_id(self, mock_client):
        mock_client.create.return_value = 42

        result = create_record(
            model="account.analytic.line",
            values={"name": "Dev work", "unit_amount": 4.0},
        )

        assert result == {"success": True, "id": 42}
        mock_client.create.assert_called_once_with(
            model="account.analytic.line",
            values={"name": "Dev work", "unit_amount": 4.0},
        )

    def test_returns_error_on_exception(self, mock_client):
        mock_client.create.side_effect = Exception("Access denied")

        result = create_record(model="res.partner", values={"name": "Test"})

        assert result["success"] is False
        assert result["error"] == "Access denied"


# ── read_record ──────────────────────────────────────────────────────────────


class TestReadRecord:
    def test_returns_records_by_id(self, mock_client):
        mock_client.read.return_value = [
            {"id": 10, "name": "Task A"},
            {"id": 11, "name": "Task B"},
        ]

        result = read_record(
            model="project.task",
            ids=[10, 11],
            fields=["id", "name"],
        )

        assert result == {
            "success": True,
            "records": [
                {"id": 10, "name": "Task A"},
                {"id": 11, "name": "Task B"},
            ],
        }
        mock_client.read.assert_called_once_with(
            model="project.task", ids=[10, 11], fields=["id", "name"]
        )

    def test_returns_error_on_exception(self, mock_client):
        mock_client.read.side_effect = Exception("Record not found")

        result = read_record(model="project.task", ids=[999])

        assert result["success"] is False
        assert result["error"] == "Record not found"


# ── update_record ────────────────────────────────────────────────────────────


class TestUpdateRecord:
    def test_returns_success_on_write(self, mock_client):
        mock_client.write.return_value = True

        result = update_record(
            model="account.analytic.line",
            ids=[100],
            values={"unit_amount": 8.0},
        )

        assert result == {"success": True}
        mock_client.write.assert_called_once_with(
            model="account.analytic.line",
            ids=[100],
            values={"unit_amount": 8.0},
        )

    def test_returns_error_on_exception(self, mock_client):
        mock_client.write.side_effect = Exception("Validation error")

        result = update_record(
            model="res.partner", ids=[1], values={"name": ""}
        )

        assert result["success"] is False
        assert result["error"] == "Validation error"


# ── search_ids ───────────────────────────────────────────────────────────────


class TestSearchIds:
    def test_returns_ids_and_count(self, mock_client):
        mock_client.search.return_value = [1, 2, 3]

        result = search_ids(
            model="project.project",
            domain=[["active", "=", True]],
            limit=100,
        )

        assert result == {"success": True, "ids": [1, 2, 3], "count": 3}
        mock_client.search.assert_called_once_with(
            model="project.project",
            domain=[["active", "=", True]],
            limit=100,
            offset=0,
            order=None,
        )

    def test_returns_empty_list_when_no_matches(self, mock_client):
        mock_client.search.return_value = []

        result = search_ids(model="res.partner", domain=[["id", "=", -1]])

        assert result == {"success": True, "ids": [], "count": 0}

    def test_returns_error_on_exception(self, mock_client):
        mock_client.search.side_effect = Exception("Timeout")

        result = search_ids(model="res.partner", domain=[])

        assert result["success"] is False
        assert result["error"] == "Timeout"


# ── search_count ────────────────────────────────────────────────────────────


class TestSearchCount:
    def test_returns_count_for_matching_records(self, mock_client):
        mock_client.search_count.return_value = 42

        result = search_count(
            model="project.project",
            domain=[["active", "=", True]],
        )

        assert result == {"success": True, "count": 42}
        mock_client.search_count.assert_called_once_with(
            model="project.project",
            domain=[["active", "=", True]],
        )

    def test_returns_zero_when_no_matches(self, mock_client):
        mock_client.search_count.return_value = 0

        result = search_count(
            model="res.partner",
            domain=[["id", "=", -1]],
        )

        assert result == {"success": True, "count": 0}

    def test_returns_error_on_exception(self, mock_client):
        mock_client.search_count.side_effect = Exception("Access denied")

        result = search_count(model="res.partner", domain=[])

        assert result["success"] is False
        assert result["error"] == "Access denied"
