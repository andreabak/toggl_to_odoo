import enum
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import (
    Any,
    MutableMapping,
    Union,
    Collection,
    Optional,
    Type,
    Tuple,
    Callable,
    Iterator,
)
from urllib.parse import urlencode

from toggl import utils, toggl
from toggl.api import Workspace, Client, Project, User, Tag, Task, TimeEntry
from toggl.api.base import TogglSet, TogglEntity
from toggl.api.models import TimeEntrySet

from .utils import OptionalValueOrCollection


# ---------------------- Patching TogglSet for caching ---------------------- #
#
_togglset_get_original = TogglSet.get


# pylint: disable=redefined-builtin
def _togglset_get(self, id=None, config=None, **conditions):
    cacheable: bool = self.cache_enabled and id is not None
    cache_key: Any = (self.__class__, self.entity_cls, id)
    if cacheable and cache_key in self.cache:
        return self.cache[cache_key]
    value = _togglset_get_original(self, id=id, config=config, **conditions)
    if cacheable:
        self.cache[cache_key] = value
    return value


def _togglset_clear_cache(cls):
    cls.cache.clear()


@contextmanager
def _togglset_cache_context(cls):
    cls.cache_enabled = True
    try:
        yield
    finally:
        cls.cache_enabled = False
        cls.clear_cache()


_togglset_cache: MutableMapping[Any, Any] = {}

TogglSet.cache = _togglset_cache
TogglSet.cache_enabled = False
TogglSet.get = _togglset_get
TogglSet.clear_cache = classmethod(_togglset_clear_cache)
TogglSet.cache_context = classmethod(_togglset_cache_context)
#
# ------------------------------ Done patching ------------------------------ #


WorkspaceType = Union[Workspace, int]
ClientType = Union[Client, int]
ProjectType = Union[Project, int]
UserType = Union[User, int]
TagType = Union[Tag, int]
TaskType = Union[Task, int]
EntryType = Union[TimeEntry, int]


class OrderBy(enum.Enum):
    date = "date"
    description = "description"
    duration = "duration"
    user = "user"


class OrderDirection(enum.Enum):
    asc = "asc"
    desc = "desc"


@dataclass(frozen=True)
class SentinelValue:
    value: Any = NotImplemented


@dataclass(frozen=True)
class _IS_SET(SentinelValue):
    """Sentinel object class for filter "with value set"."""

    value: Any = 0


IS_SET = _IS_SET()


@dataclass(frozen=True)
class _NOT_SET(SentinelValue):
    """Sentinel object class for not set parameters"""


NOT_SET = _NOT_SET()


def isofmt(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class BetterTimeEntrySet(TimeEntrySet):
    @staticmethod
    def maybe_none(
        value: Any,
        name: Optional[str] = None,
        default: Union[Any, _NOT_SET] = NOT_SET,
        allow_none: bool = True,
    ) -> Any:
        """Preprocess a parameter which value may be none"""
        if value is None:
            if default is not NOT_SET:
                return default
            elif allow_none:
                return None
            else:
                if name is None:
                    raise AttributeError("Value cannot be None")
                raise AttributeError(f'Missing parameter "{name}"')
        return value

    @classmethod
    def get_entity_id(
        cls, value: Any, name: str, expected_type: Type[TogglEntity], **kwargs
    ) -> Any:
        """Try extracting the id from an entity"""
        value = cls.maybe_none(value, name, **kwargs)
        if value is None:
            return None
        elif isinstance(value, expected_type):
            return value.id
        elif isinstance(value, int):
            return value
        try:
            return int(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f'Bad value for parameter "{name}": {value}') from exc

    def _build_reports_url(
        self,
        workspace: Optional[WorkspaceType] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        billable: Optional[bool] = None,
        clients: OptionalValueOrCollection[ClientType] = None,
        projects: OptionalValueOrCollection[ProjectType] = None,
        users: OptionalValueOrCollection[UserType] = None,
        tags: OptionalValueOrCollection[Union[TagType, _IS_SET]] = None,
        tasks: OptionalValueOrCollection[Union[TaskType, _IS_SET]] = None,
        entries: OptionalValueOrCollection[EntryType] = None,
        description: Optional[str] = None,
        include_without_description: Optional[bool] = None,
        order_by: Optional[OrderBy] = None,
        order_direction: Optional[OrderDirection] = None,
        rounding: Optional[bool] = False,
        page: int = 1,
        config: Optional[utils.Config] = None,
    ):
        """
        :param workspace: Workspace from where should be the time entries fetched from.
            If omitted, the default workspace is used.
        :param since: From when time entries should be fetched. Defaults to today - 6 days.
        :param until: Until when time entries should be fetched. Defaults to today,
            unless since is in future or more than year ago, in this case until is
            since + 6 days. Note: Maximum date span (until - since) is one year.
        :param billable: Set True to include only billable entries,
            False to include only non-billable entries. Omit or None for both.
        FIXME: Docstrings
        client_ids: A list of client IDs separated by a comma. Use "0" if you want to filter out time entries without a client.
        project_ids: A list of project IDs separated by a comma. Use "0" if you want to filter out time entries without a project.
        user_ids: A list of user IDs separated by a comma.
        members_of_group_ids: A list of group IDs separated by a comma. This limits provided user_ids to the members of the given groups.
        or_members_of_group_ids: A list of group IDs separated by a comma. This extends provided user_ids with the members of the given groups.
        tag_ids: A list of tag IDs separated by a comma. Use "0" if you want to filter out time entries without a tag.
        task_ids: A list of task IDs separated by a comma. Use "0" if you want to filter out time entries without a task.
        time_entry_ids: A list of time entry IDs separated by a comma.
        description: Matches against time entry descriptions.
        without_description: "true" or "false". Filters out the time entries which do not have a description (literally "(no description)").
        order_field:
            For detailed reports: "date", "description", "duration", or "user"
            For summary reports: "title", "duration", or "amount"
            For weekly reports: "title", "day1", "day2", "day3", "day4", "day5", "day6", "day7", or "week_total"
        order_desc: "on" for descending, or "off" for ascending order.
        distinct_rates: "on" or "off". Defaults to "off".
        rounding: "on" or "off". Defaults to "off". Rounds time according to workspace settings.
        display_hours: "decimal" or "minutes". Defaults to "minutes". Determines whether to display hours as a decimal number or with minutes.
        config:
        """
        fn_locals: MutableMapping[str, Any] = locals()

        def param(name: str) -> Tuple[str, Any]:
            nonlocal fn_locals
            assert name in fn_locals
            return fn_locals[name], name

        def one_or_many_entities(
            value: Any,
            name: str,
            value_processor: Callable = self.get_entity_id,
            **kwargs,
        ) -> Optional[str]:
            """Process one or many values"""
            if isinstance(value, Collection) and not isinstance(value, TogglEntity):
                values = value
            else:
                values = [value]
            if value_processor is not None:
                values = {value_processor(v, name, **kwargs) for v in values}
            values = {v for v in values if v is not None}
            if not values:
                return None
            return ",".join([str(v) for v in values])

        def sentinel_case(
            value: Any,
            name: str,
            sentinel: SentinelValue,
            value_processor: Callable = self.get_entity_id,
            **kwargs,
        ) -> Any:
            if value is sentinel:
                return value.value
            else:
                return value_processor(value, name, **kwargs)

        def convert_datetime(
            value: Optional[datetime], name: str, **kwargs
        ) -> Optional[str]:
            """Convert a datetime value"""
            value = self.maybe_none(value, name, **kwargs)
            if value is None:
                return None
            return isofmt(value.astimezone())

        def convert_bool(
            value: Optional[bool],
            name: str,
            true_value: Any = "true",
            false_value: Any = "false",
            **kwargs,
        ) -> Optional[str]:
            """Convert a bool value"""
            value = self.maybe_none(value, name, **kwargs)
            if value is None:
                return None
            return true_value if value else false_value

        def convert_enum(
            value: Optional[enum.Enum], name: str, **kwargs
        ) -> Optional[str]:
            """Convert an enum"""
            value = self.maybe_none(value, name, **kwargs)
            if value is None:
                return None
            return value.value

        config = config or utils.Config.factory()

        params: MutableMapping[str, Any] = {
            "user_agent": "toggl_cli",
            "workspace_id": self.get_entity_id(
                *param("workspace"),
                expected_type=Workspace,
                default=config.default_workspace,
                allow_none=False,
            ),
            "since": convert_datetime(*param("since")),
            "until": convert_datetime(*param("until")),
            "billable": convert_bool(
                *param("billable"), true_value="yes", false_value="no"
            ),
            "client_ids": one_or_many_entities(*param("clients"), expected_type=Client),
            "project_ids": one_or_many_entities(
                *param("projects"), expected_type=Project
            ),
            "user_ids": one_or_many_entities(*param("users"), expected_type=User),
            "tag_ids": one_or_many_entities(
                *param("tags"),
                value_processor=sentinel_case,
                sentinel=IS_SET,
                expected_type=Tag,
            ),
            "task_ids": one_or_many_entities(
                *param("tasks"),
                value_processor=sentinel_case,
                sentinel=IS_SET,
                expected_type=Task,
            ),
            "time_entry_ids": one_or_many_entities(
                *param("entries"), expected_type=TimeEntry
            ),
            "description": self.maybe_none(*param("description")),
            "without_description": convert_bool(*param("include_without_description")),
            "order_field": convert_enum(*param("order_by")),
            "order_desc": {"desc": "on", "asc": "off"}.get(
                convert_enum(*param("order_direction"))
            ),
            "rounding": convert_bool(
                *param("rounding"), true_value="yes", false_value="no"
            ),
            "page": page,
        }
        params = {k: str(v) for k, v in params.items() if v is not None}
        prepared_params: str = urlencode(params)
        return "/details?" + prepared_params

    def report_detailed(
        self,
        workspace: Optional[WorkspaceType] = None,
        config: Optional[utils.Config] = None,
        page: int = 1,
        **query,
    ) -> Iterator[TimeEntry]:
        """
        Fetch time entries through the detailed Report API.
        """
        config = config or utils.Config.factory()

        workspace_id = self.get_entity_id(
            workspace,
            "workspace",
            expected_type=Workspace,
            default=config.default_workspace,
            allow_none=False,
        )

        while True:
            url = self._build_reports_url(
                workspace=workspace_id, config=config, page=page, **query
            )
            returned = utils.toggl(url, "get", config=config, address=toggl.REPORTS_URL)

            if not returned.get("data"):
                return

            for entity in returned.get("data"):
                yield self._deserialize_from_reports(config, entity, workspace_id)

            if not self._should_fetch_more(page, returned):
                return

            page += 1


class BetterTimeEntry(TimeEntry):
    objects = BetterTimeEntrySet()

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} #{self.id}> "
            f"({isofmt(self.start)} -> {isofmt(self.stop)}) "
            + (f"[{self.project.name}] " if self.project else "")
            + f"{self.description}"
        )
