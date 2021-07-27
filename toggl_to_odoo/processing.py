import logging
from collections import defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
from typing import (
    List,
    Union,
    DefaultDict,
    Mapping,
    Tuple,
    TypeVar,
    Optional,
    Type,
    Callable,
    Set,
)

from toggl import utils
from toggl.api import TimeEntry, Client, Project, Tag
from toggl.api.base import TogglEntity

from .toggl_patching import isofmt, BetterTimeEntry
from .utils import fmt_time, OptionalStrOrCollection, OptList


logger: logging.Logger = logging.getLogger(__name__)


def snap_entries(time_entries: List[TimeEntry], snap_seconds: float):
    @lru_cache(typed=True)
    def calc_window_id(timestamp: Union[float, datetime], window_size: float) -> int:
        if isinstance(timestamp, datetime):
            timestamp = timestamp.timestamp()
        return int(timestamp / window_size)

    time_entries_with_midtime: List[Tuple[float, TimeEntry]]
    time_entries_with_midtime = [
        (((e.start.timestamp() + e.stop.timestamp()) / 2), e) for e in time_entries
    ]
    time_entries_with_midtime.sort(key=lambda te: te[0])
    start_windows: DefaultDict[int, List[Tuple[float, TimeEntry]]] = defaultdict(list)
    stop_windows: DefaultDict[int, List[Tuple[float, TimeEntry]]] = defaultdict(list)
    for midtime, entry in time_entries_with_midtime:
        start_windows[calc_window_id(entry.start, snap_seconds)].append(
            (midtime, entry)
        )
        stop_windows[calc_window_id(entry.stop, snap_seconds)].append((midtime, entry))
    snapped_seconds: float = 0.0
    entry: TimeEntry
    for midtime, entry in time_entries_with_midtime:
        # Only considering prev stop times to next start times once
        # start_window_id: int = calc_window_id(entry.start, snap_seconds)
        stop_window_id: int = calc_window_id(entry.stop, snap_seconds)

        def extract_entries(
            windows: Mapping[int, List[Tuple[float, TimeEntry]]], window_id: int
        ) -> List[Tuple[float, TimeEntry]]:
            nonlocal entry
            return [e for e in windows.get(window_id, []) if e[1] is not entry]

        nearby_window_entries: List[Tuple[float, TimeEntry]] = [
            *extract_entries(start_windows, stop_window_id - 1),
            *extract_entries(start_windows, stop_window_id),
            *extract_entries(start_windows, stop_window_id + 1),
        ]
        snap_candidates: List[Tuple[float, TimeEntry]] = sorted(
            (
                (delta, e)
                for m, e in nearby_window_entries
                if abs(delta := (e.start - entry.stop).total_seconds()) <= snap_seconds
                and m >= midtime
            ),
            key=lambda t: abs(t[0]),
        )

        # Only snap the closest
        if not snap_candidates:
            continue
        delta: float
        snap_entry: TimeEntry
        delta, snap_entry = snap_candidates[0]
        if delta < 0:
            logger.warning(f"Entries times overlap by {fmt_time(abs(delta))}")
            # TODO: consider if skipping negative entries (filter them out)
        logger.debug(
            f"Snapping entries by {fmt_time(delta)}: "
            f"#{entry.id} -> {isofmt(entry.stop)} "
            f"| {isofmt(snap_entry.start)} -> #{snap_entry.id}"
        )
        entry.stop += timedelta(seconds=delta / 2)
        snap_entry.start -= timedelta(seconds=delta / 2)
        snapped_seconds += delta
    logger.info(f"Total snapped time: {fmt_time(snapped_seconds)}")
    return snapped_seconds


_ET = TypeVar("_ET", bound=TogglEntity)


def fetch_and_process(
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    clients: OptionalStrOrCollection = None,
    projects: OptionalStrOrCollection = None,
    projects_exclude: OptionalStrOrCollection = None,
    tags_include: OptionalStrOrCollection = None,
    tags_exclude: OptionalStrOrCollection = None,
    snap_seconds: Optional[float] = None,
):
    config: utils.Config = utils.Config.factory()

    def get_entities(
        values: OptionalStrOrCollection,
        model: Type[_ET],
        value_attr: str = "name",
    ) -> Optional[List[_ET]]:
        nonlocal config
        entities: Optional[List[Client]] = None
        if values:
            if isinstance(values, str):
                values = [values]
            entities = [
                model.objects.get(**{value_attr: c}, config=config) for c in set(values)
            ]
            entities = [e for e in entities if e]
        return entities or None

    client_entities: OptList[Client] = get_entities(clients, Client)
    project_entities: OptList[Project] = get_entities(projects, Project)
    project_exclude_entities: OptList[Project] = get_entities(projects_exclude, Project)
    tags_include_entities: OptList[Tag] = get_entities(tags_include, Tag)
    tags_exclude_entities: OptList[Tag] = get_entities(tags_exclude, Tag)

    # TODO: running entry skipping / handling (seems to be not fetched tho)

    time_entries: List[TimeEntry] = list(
        BetterTimeEntry.objects.report_detailed(
            since=since,
            until=until,
            clients=client_entities,
            projects=project_entities,
            tags=tags_include_entities,
            config=config,
        )
    )

    entry_filters: List[Callable[[TimeEntry], bool]] = []

    def entries_filters(entry: TimeEntry) -> bool:
        nonlocal entry_filters
        result = True
        for filter_fn in entry_filters:
            result = result and filter_fn(entry)
            if not result:
                break
        return result

    if client_entities and project_entities:
        project_ids: Set[int] = {p.id for p in project_entities}
        entry_filters.append(lambda e: e.project.id in project_ids)
    if project_exclude_entities:
        project_exclude_ids: Set[int] = {p.id for p in project_exclude_entities}
        entry_filters.append(lambda e: e.project.id not in project_exclude_ids)
    if tags_exclude_entities:
        tags_exclude_names: Set[int] = {t.name for t in tags_exclude_entities}
        entry_filters.append(lambda e: not set(e.tags).intersection(tags_exclude_names))

    time_entries = [e for e in time_entries if entries_filters(e)]

    if snap_seconds:
        snap_entries(time_entries, snap_seconds)

    time_entries.sort(key=lambda e: e.start)

    return time_entries
