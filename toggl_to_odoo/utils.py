import pkgutil
from importlib import import_module
from types import ModuleType
from typing import (
    TypeVar,
    Union,
    Collection,
    Optional,
    List,
    Protocol,
    Iterable,
    Tuple,
    Any,
    MutableMapping,
    Dict,
)


_T = TypeVar("_T")
ValueOrCollection = Union[Collection[_T], _T]
OptionalValueOrCollection = Union[Collection[_T], _T, None]
OptionalStrOrCollection = OptionalValueOrCollection[str]
OptList = Optional[List[_T]]


# pylint: disable=invalid-name
def fmt_time(seconds: float, precision: int = 0, with_letters: bool = True) -> str:
    """
    Format a duration in seconds into a timer-like string
    :param seconds: The number of seconds
    :param precision: The amount of digits for the decimal part of the seconds
    :param with_letters: If True, use letter formatting instead of colons
    :return: The formatted "timer" string
    """
    s_fmt_l: int = precision + 3 if precision else 2
    s_fmt_spec_full: str = f"{{:0{s_fmt_l}.{precision}f}}"
    s_fmt_spec_min: str = f"{{:.{precision}f}}"
    h: int = int(seconds) // 3600
    m: int = (int(seconds) // 60) % 60
    s: float = seconds % 60
    h_fmt: str = f"{h:d}"
    m_fmt: str = ("{:02d}" if seconds >= 3600 else "{:d}").format(m)
    s_fmt: str = (s_fmt_spec_full if seconds >= 60 else s_fmt_spec_min).format(s) + (
        "s" if with_letters else ""
    )
    ms_fmt: str = f"{m_fmt}m {s_fmt}" if with_letters else f"{m_fmt}:{s_fmt}"
    hms_fmt: str = f"{h_fmt}h {ms_fmt}" if with_letters else f"{h_fmt}:{ms_fmt}"
    timer: str = hms_fmt if seconds >= 3600 else (ms_fmt if seconds >= 60 else s_fmt)
    return timer


class ImportHook(Protocol):
    """Typing protocol for import hook callables"""

    def __call__(self, module: ModuleType) -> Optional[Iterable[Tuple[str, Any]]]:
        ...


def import_submodules(
    base_path: List[str],
    globals_: MutableMapping[str, Any],
    package: Optional[str] = None,
    on_import: Optional[ImportHook] = None,
) -> List[str]:
    """
    Dynamically import all submodules (non-recursively) into the given dict.

    :param base_path: the base path where to look for submodules.
    :param globals_: a dict where the imported modules will be stored.
    :param package: optional package name required to enable relative imports.
    :param on_import: optional hook that will be called with the imported module
        as sole argument to do custom additional processing and can insert more
        attributes and values into the package namespace.
    :return: the list of imported module names.
    """
    imported_names: List[str] = []
    module_name: str
    for _, module_name, _ in pkgutil.iter_modules(base_path):  # type: ignore
        imported_module: ModuleType = import_module("." + module_name, package=package)
        added_attributes: Dict[str, Any] = {module_name: imported_module}
        if on_import is not None:
            hook_additions: Optional[Iterable[Tuple[str, Any]]]
            hook_additions = on_import(imported_module)
            if hook_additions is not None:
                added_attributes.update(hook_additions)
        for attr_name, attr_value in added_attributes.items():
            globals_[attr_name] = attr_value
            imported_names.append(attr_name)
    return imported_names
