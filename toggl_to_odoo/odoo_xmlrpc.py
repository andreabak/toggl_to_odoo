from xmlrpc.client import ServerProxy as XmlRpcServerProxy
from typing import Optional, Any, List, Sequence, MutableMapping, Tuple

from .utils import ValueOrCollection


class OdooXmlRpc:
    username: str
    password: str
    uid: Optional[int] = None

    def __init__(self, url: str, db: str, username: str, password: str):
        self._url: str = url
        self.db_name: str = db
        self.username: str = username
        self.password: str = password
        self.uid: Optional[int] = None
        self._xmlrpc_common: XmlRpcServerProxy = XmlRpcServerProxy(
            f"{self._url}/xmlrpc/2/common"
        )
        self._xmlrpc_object: XmlRpcServerProxy = XmlRpcServerProxy(
            f"{self._url}/xmlrpc/2/object"
        )

    @property
    def is_logged_in(self) -> bool:
        return self.uid is not None

    def authenticate(self) -> int:
        result: Any = self._xmlrpc_common.authenticate(
            self.db_name, self.username, self.password, {}
        )
        if not isinstance(result, int):
            raise ValueError("Failed authenticating to odoo xmlrpc!")
        self.uid = result
        return self.uid

    def _object_command(self, model: str, command: str, *args: Any) -> Any:
        if not self.is_logged_in:
            raise SystemError("Did not authenticate to xmlrpc!")
        result = self._xmlrpc_object.execute_kw(
            self.db_name,
            self.uid,
            self.password,
            model,
            command,
            *args,
        )
        return result

    def search_read(
        self,
        model: str,
        domain: List[Any],
        fields: Optional[Sequence[str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        order: Optional[str] = None,
    ) -> List[MutableMapping[str, Any]]:
        params: MutableMapping[str, Any] = {}
        if fields is not None:
            params["fields"] = list(fields)
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        if order is not None:
            params["order"] = order
        results = self._object_command(model, "search_read", (domain,), params)
        assert isinstance(results, list)
        return results

    def read(
        self,
        model: str,
        ids: ValueOrCollection[int],
        fields: Optional[Sequence[str]] = None,
    ) -> List[MutableMapping[str, Any]]:
        params: MutableMapping[str, Any] = {}
        if fields is not None:
            params["fields"] = list(fields)
        results = self._object_command(model, "read", (ids,), params)
        assert isinstance(results, list)
        return results

    @staticmethod
    def _assert_name_result(r: Any) -> Tuple[int, str]:
        assert isinstance(r, (tuple, list))
        assert len(r) == 2
        assert isinstance(r[0], int)
        assert isinstance(r[1], str)
        return r[0], r[1]

    def name_get(
        self, model: str, ids: ValueOrCollection[int]
    ) -> List[Tuple[int, str]]:
        results = self._object_command(model, "name_get", (ids,))
        assert isinstance(results, list)
        return [self._assert_name_result(r) for r in results]

    def name_search(
        self,
        model: str,
        name: str,
        limit: Optional[int] = None,
        operator: Optional[str] = None,
    ) -> List[Tuple[int, str]]:
        params: MutableMapping[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if operator is not None:
            params["operator"] = operator
        results = self._object_command(model, "name_search", (name,), params)
        assert isinstance(results, list)
        return [self._assert_name_result(r) for r in results]

    def create(self, model: str, values: MutableMapping[str, Any]) -> int:
        result = self._object_command(model, "create", (values,))
        assert isinstance(result, int)
        return result

    def write(
        self, model: str, ids: ValueOrCollection[int], values: MutableMapping[str, Any]
    ) -> int:
        result = self._object_command(model, "write", (ids, values))
        assert isinstance(result, int)
        return result

    def unlink(self, model: str, ids: ValueOrCollection[int]) -> bool:
        return self._object_command(model, "unlink", (ids,))

    delete = unlink
