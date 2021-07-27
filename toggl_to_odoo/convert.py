import logging
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from typing import (
    TypedDict,
    Union,
    MutableMapping,
    TypeVar,
    Type,
    Callable,
    Optional,
    Tuple,
    Generator,
    MutableSequence,
    List,
    Sequence,
    Set,
    ClassVar,
)

from toggl.api import TimeEntry

from .utils import ValueOrCollection


__all__ = [
    "ConverterClass",
    "ChainedConverter",
    "get_converter",
    "SimpleConverter",
    "EntryConverterBase",
    "TimesheetLine",
]


logger: logging.Logger = logging.getLogger(__name__)


class TimesheetLine(TypedDict, total=False):
    date: date
    project: Union[str, int]
    task: Union[str, int]
    name: str
    unit_amount: float
    _toggl_ids: Set[int]


class EntryConverterBase(ABC):
    @abstractmethod
    def matches(self, entry: TimeEntry) -> bool:
        ...

    @abstractmethod
    def convert(self, entry: TimeEntry) -> TimesheetLine:
        ...


class SimpleConverter(EntryConverterBase):
    def __init__(
        self, datetime_middle: bool = False, nightly_cutoff: Optional[float] = None
    ):
        self.datetime_middle: bool = datetime_middle
        self.nightly_cutoff: Optional[float] = nightly_cutoff

    def extract_date(self, entry: TimeEntry) -> date:
        entry_dt: datetime = entry.start
        if self.datetime_middle:
            entry_dt += timedelta(seconds=entry.duration) / 2
        if self.nightly_cutoff is not None:
            entry_dt -= timedelta(hours=self.nightly_cutoff)
        return entry_dt.date()

    def matches(self, entry: TimeEntry) -> bool:
        return True

    def convert(self, entry: TimeEntry) -> TimesheetLine:
        line: TimesheetLine = TimesheetLine(
            date=self.extract_date(entry),
            project=entry.project.name,
            name=entry.description,
            unit_amount=entry.duration / 3600,
            _toggl_ids={entry.id},
        )
        return line


_CT = TypeVar("_CT", bound=EntryConverterBase)
ConverterClass = Type[_CT]


class ChainedConverter:
    _instances: ClassVar[MutableMapping[str, "ChainedConverter"]] = {}

    @classmethod
    def get_converter(cls, name: str) -> "ChainedConverter":
        if name not in cls._instances:
            raise NameError(f'No converter found with name "{name}"')
        return cls._instances[name]

    def __init__(self, name: str):
        self.name: str = name
        self.converters: MutableMapping[Union[int, float], ConverterClass] = {}
        if name in self._instances:
            raise NameError(f"Conflicting name for {repr(self)}")
        self._instances[name] = self

    def register(
        self, priority: Union[int, float]
    ) -> Callable[[ConverterClass], ConverterClass]:
        def decorator(converter_class: ConverterClass) -> ConverterClass:
            nonlocal self, priority
            if priority in self.converters:
                priority -= 0.00001 * len(self.converters)
                logger.warning(
                    f"Duplicate priority {priority} in {repr(self)}. "
                    f"Converter {repr(converter_class)} will be added with a lower priority"
                )
            self.converters[priority] = converter_class
            return converter_class

        if not isinstance(priority, (int, float)):
            raise AttributeError(
                '"priority" must be a number ' "(did you forget to call the decorator?)"
            )
        return decorator

    def _build_converters(self, **converter_kwargs) -> List[_CT]:
        return [
            converter_cls(**converter_kwargs)
            for _, converter_cls in sorted(
                self.converters.items(), key=lambda c: c[0], reverse=True
            )
        ]

    def _convert_one(
        self,
        entry: TimeEntry,
        converters: Optional[MutableSequence[_CT]] = None,
        must_match: bool = True,
        **converter_kwargs,
    ) -> Optional[TimesheetLine]:
        if converters is None:
            converters = self._build_converters(**converter_kwargs)
        for converter in converters:
            if converter.matches(entry):
                return converter.convert(entry)
        if must_match:
            raise LookupError(
                f"No converter in {repr(self)} matches for entry: {repr(entry)}"
            )
        return None

    @staticmethod
    def merge(
        lines: List[TimesheetLine], keys: Optional[Sequence[str]] = None
    ) -> List[TimesheetLine]:
        if keys is None:
            keys = ("date", "project", "task", "name")
        buckets: MutableMapping[Tuple, TimesheetLine] = {}
        line: TimesheetLine
        for line in lines:
            key: Tuple = tuple(line.get(k) for k in keys)
            bucket_line: Optional[TimesheetLine] = buckets.get(key)
            if bucket_line is None:
                buckets[key] = line.copy()
            else:
                bucket_line["unit_amount"] += line["unit_amount"]
                bucket_line["_toggl_ids"] |= line["_toggl_ids"]
        return list(buckets.values())

    def convert_iter(
        self,
        entries: ValueOrCollection[TimeEntry],
        must_match: bool = True,
        **converter_kwargs,
    ) -> Generator[Optional[TimesheetLine], None, Optional[TimesheetLine]]:
        is_single: bool = isinstance(entries, TimeEntry)
        converters = self._build_converters(**converter_kwargs)
        entry: TimeEntry
        for entry in [entries] if is_single else entries:
            line: Optional[TimesheetLine] = self._convert_one(
                entry, converters=converters, must_match=must_match
            )
            if is_single:
                return line  # TODO: I forgot, why am I returning here?
            if line is not None:
                yield line
        return None

    def convert(
        self,
        entries: ValueOrCollection[TimeEntry],
        must_match: bool = True,
        merge: bool = False,
        merge_keys: Optional[Sequence[str]] = None,
        **converter_kwargs,
    ) -> List[TimesheetLine]:
        lines: List[TimesheetLine] = list(
            self.convert_iter(entries, must_match=must_match, **converter_kwargs)
        )
        if merge:
            lines = self.merge(lines, keys=merge_keys)
        return lines

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({repr(self.name)})"


get_converter = ChainedConverter.get_converter


# Base converters


# Odoo client base converters


# Odoo onboarding (functional training)


# Odoo training (technical)


# Odoo owndb


# Odoo misc


# Extract task-like entry formatted like: "[task_id: task_name] description"


# Odoo improvement


# Odoo coaching


# Odoo code reviews


# Odoo tasks (psbe, etc.)


# Odoo non-billable
