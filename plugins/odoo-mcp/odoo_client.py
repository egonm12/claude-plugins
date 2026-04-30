"""Odoo XML-RPC client with API key authentication support."""

import xmlrpc.client
from typing import Any, Dict, List, Optional


class OdooClient:
    """
    Odoo XML-RPC client that supports API key authentication.

    This client handles authentication and provides a simple interface
    for executing Odoo operations via XML-RPC with API keys (required
    when 2FA is enabled).
    """

    def __init__(self, url: str, db: str, username: str, api_key: str):
        """
        Initialize the Odoo client.

        Args:
            url: Odoo instance URL (e.g., 'https://portal.kabisa.nl')
            db: Database name (e.g., 'kabisa-main-8947371')
            username: User email (e.g., 'user@example.com')
            api_key: API key for authentication (replaces password when 2FA is enabled)
        """
        self._url = url.rstrip('/')
        self._db = db
        self._username = username
        self._api_key = api_key

        # Lazy initialization - connect on first use
        self._uid: Optional[int] = None
        self._models: Optional[xmlrpc.client.ServerProxy] = None

    def _ensure_connected(self) -> None:
        """Establish connection to Odoo if not already connected."""
        if self._uid is None or self._models is None:
            # Reset state before attempting connection
            self._uid = None
            self._models = None

            try:
                # Connect to common endpoint for authentication
                common = xmlrpc.client.ServerProxy(f'{self._url}/xmlrpc/2/common')

                # Authenticate using API key
                uid = common.authenticate(
                    self._db,
                    self._username,
                    self._api_key,
                    {}
                )

                if not uid or not isinstance(uid, int):
                    raise ValueError("Authentication failed - check credentials")

                # Connect to object endpoint for operations
                models = xmlrpc.client.ServerProxy(f'{self._url}/xmlrpc/2/object')

                # Only update instance variables after successful setup
                self._uid = uid
                self._models = models

            except Exception as e:
                # Ensure state is reset on failure
                self._uid = None
                self._models = None
                raise ConnectionError(f"Failed to connect to Odoo: {str(e)}")

    def execute(
        self,
        model: str,
        method: str,
        *args,
        **kwargs
    ) -> Any:
        """
        Execute an Odoo method on a model.

        Args:
            model: Odoo model name (e.g., 'project.project')
            method: Method to call (e.g., 'search_read', 'create', 'write')
            *args: Positional arguments for the method
            **kwargs: Keyword arguments for the method

        Returns:
            Result from Odoo operation

        Raises:
            ConnectionError: If connection fails
            Exception: If the operation fails
        """
        self._ensure_connected()

        try:
            return self._models.execute_kw(
                self._db,
                self._uid,
                self._api_key,
                model,
                method,
                list(args),
                kwargs
            )
        except xmlrpc.client.Fault as e:
            raise Exception(f"Odoo error: {e.faultString}")
        except Exception as e:
            raise Exception(f"Operation failed: {str(e)}")

    def search_read(
        self,
        model: str,
        domain: List[Any],
        fields: Optional[List[str]] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        order: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Search and read records from Odoo.

        Args:
            model: Odoo model name
            domain: Search domain (e.g., [['name', 'ilike', 'Hertek']])
            fields: Fields to return (None = all fields)
            limit: Maximum number of records to return
            offset: Number of records to skip
            order: Sort order (e.g., 'name desc')

        Returns:
            List of dictionaries containing record data
        """
        kwargs = {}
        if fields:
            kwargs['fields'] = fields
        if limit:
            kwargs['limit'] = limit
        if offset > 0:
            kwargs['offset'] = offset
        if order:
            kwargs['order'] = order

        return self.execute(model, 'search_read', domain, **kwargs)

    def create(self, model: str, values: Dict[str, Any]) -> int:
        """
        Create a new record.

        Args:
            model: Odoo model name
            values: Dictionary of field values

        Returns:
            ID of the created record
        """
        return self.execute(model, 'create', values)

    def read(
        self,
        model: str,
        ids: List[int],
        fields: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Read records by ID.

        Args:
            model: Odoo model name
            ids: List of record IDs to read
            fields: Fields to return (None = all fields)

        Returns:
            List of dictionaries containing record data
        """
        if not ids:
            return []

        kwargs = {}
        if fields:
            kwargs['fields'] = fields

        return self.execute(model, 'read', ids, **kwargs)

    def write(
        self,
        model: str,
        ids: List[int],
        values: Dict[str, Any]
    ) -> bool:
        """
        Update existing records.

        Args:
            model: Odoo model name
            ids: List of record IDs to update
            values: Dictionary of field values to update

        Returns:
            True if successful
        """
        return self.execute(model, 'write', ids, values)

    def unlink(self, model: str, ids: List[int]) -> bool:
        """
        Delete records by ID.

        Args:
            model: Odoo model name
            ids: List of record IDs to delete

        Returns:
            True if successful
        """
        return self.execute(model, 'unlink', ids)

    def search_count(self, model: str, domain: List[Any]) -> int:
        """
        Count records matching a domain.

        Args:
            model: Odoo model name
            domain: Search domain

        Returns:
            Number of matching records
        """
        return self.execute(model, 'search_count', domain)

    def search(
        self,
        model: str,
        domain: List[Any],
        limit: Optional[int] = None,
        offset: int = 0,
        order: Optional[str] = None
    ) -> List[int]:
        """
        Search for record IDs matching domain.

        Args:
            model: Odoo model name
            domain: Search domain
            limit: Maximum number of IDs to return
            offset: Number of records to skip
            order: Sort order

        Returns:
            List of record IDs
        """
        kwargs = {}
        if limit:
            kwargs['limit'] = limit
        if offset > 0:
            kwargs['offset'] = offset
        if order:
            kwargs['order'] = order

        return self.execute(model, 'search', domain, **kwargs)
