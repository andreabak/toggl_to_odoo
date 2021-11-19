from dataclasses import dataclass
from datetime import datetime
from typing import Collection, Optional

from configmanager import ConfigSectionAutoNamed, ConfigBase
from configmanager.configmanager import config_dataclass


@dataclass
class GeneralConfig(ConfigSectionAutoNamed):
    """Config section containing general parameters"""

    config_path: str = None
    """The path of the loaded config"""

    verbosity: int = -1
    """Verbosity level"""

    dry_run: bool = False
    """If enabled, does not make any changes"""


@dataclass
class FetchConfig(ConfigSectionAutoNamed):
    """Config section with time entries fetching parameters"""

    since: Optional[datetime] = None
    """Get entries since the given date/time"""

    until: Optional[datetime] = None
    """Get entries until the given date/time"""

    clients: Optional[Collection[str]] = None
    """Clients to filter by"""

    projects_include: Optional[Collection[str]] = None
    """Projects to filter by"""

    projects_exclude: Optional[Collection[str]] = None
    """Projects to exclude"""

    tags_include: Optional[Collection[str]] = None
    """Tags to filter by"""

    tags_exclude: Optional[Collection[str]] = None
    """Tags to exclude"""

    snap: Optional[float] = None
    """Snap together entries closer than the specified amount of seconds"""


@config_dataclass
class Config(ConfigBase):
    """
    The actual configuration class that when instantiated contains config subsections.
    The name of the sections in the external .ini file must match the attributes (dataclass fields) names
    """

    general: GeneralConfig = None
    fetch: FetchConfig = None
