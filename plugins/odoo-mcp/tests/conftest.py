"""Shared fixtures for Odoo MCP acceptance tests."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_client():
    """Provide a mocked OdooClient that bypasses XML-RPC entirely."""
    with patch("server.client") as mock:
        yield mock
