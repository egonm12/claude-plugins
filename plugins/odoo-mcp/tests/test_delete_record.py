"""Tests for delete_record tool."""

from server import delete_record

delete_record_fn = delete_record.fn


class TestDeleteRecord:
    def test_successful_deletion(self, mock_client):
        mock_client.unlink.return_value = True

        result = delete_record_fn(model="res.partner", ids=[42])

        assert result == {"success": True}
        mock_client.unlink.assert_called_once_with(model="res.partner", ids=[42])

    def test_multiple_records_deleted(self, mock_client):
        """Multiple IDs deleted in a single call."""
        mock_client.unlink.return_value = True

        result = delete_record_fn(model="res.partner", ids=[1, 2, 3])

        assert result == {"success": True}
        mock_client.unlink.assert_called_once_with(
            model="res.partner", ids=[1, 2, 3]
        )

    def test_invalid_model_or_ids(self, mock_client):
        """Invalid model or non-existent IDs returns error."""
        mock_client.unlink.side_effect = Exception(
            "Odoo error: Model 'fake.model' does not exist"
        )

        result = delete_record_fn(model="fake.model", ids=[999])

        assert result["success"] is False
        assert "error" in result

    def test_connection_failure(self, mock_client):
        """Connection failure returns error."""
        mock_client.unlink.side_effect = Exception("Connection refused")

        result = delete_record_fn(model="res.partner", ids=[1])

        assert result["success"] is False
        assert "error" in result
