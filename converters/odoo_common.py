import re
from typing import Tuple, Optional, Match

from toggl.api import TimeEntry

from toggl_to_odoo.convert import SimpleConverter


class OdooConverter(SimpleConverter):
    def matches(self, entry: TimeEntry) -> bool:
        return super().matches(entry) and entry.project.client.name == "Odoo"


class OdooOnboarding(OdooConverter):
    def matches(self, entry: TimeEntry) -> bool:
        return super().matches(entry) and entry.project.name == "Odoo-onboarding"


class OdooTraining(OdooConverter):
    def matches(self, entry: TimeEntry) -> bool:
        return super().matches(entry) and entry.project.name == "Odoo-training"


class OdooOwndb(OdooConverter):
    def matches(self, entry: TimeEntry) -> bool:
        return super().matches(entry) and entry.project.name == "Odoo-owndb"


class OdooMisc(OdooConverter):
    def matches(self, entry: TimeEntry) -> bool:
        return super().matches(entry) and entry.project.name == "Odoo-misc"


class OdooImprovement(OdooConverter):
    def matches(self, entry: TimeEntry) -> bool:
        return super().matches(entry) and entry.project.name == "Odoo-improvement"


class OdooCoaching(OdooConverter):
    def matches(self, entry: TimeEntry) -> bool:
        return super().matches(entry) and entry.project.name == "Odoo-coaching"


class OdooReview(OdooConverter):
    def matches(self, entry: TimeEntry) -> bool:
        return super().matches(entry) and entry.project.name == "Odoo-review"


class OdooMeeting(OdooConverter):
    def matches(self, entry: TimeEntry) -> bool:
        return super().matches(entry) and entry.project.name == "Odoo-meeting"


class OdooTask(OdooConverter):
    def matches(self, entry: TimeEntry) -> bool:
        return super().matches(entry) and entry.project.name in (
            "Odoo-psbe",
            "Odoo-maintenance",
        )


def extract_task(entry: TimeEntry) -> Tuple[int, Optional[str], str]:
    match: Match = re.search(
        r"^\[(?P<task_id>\d+)(?::\s*(?P<task_desc>.*?))?\]\s*(?P<description>.*)",
        entry.description,
    )
    if not match:
        raise ValueError(f"Couldn't extract task info from entry: {repr(entry)}")
    task_id: int = int(match.group("task_id"))
    task_desc: Optional[str] = match.group("task_desc") or None
    description: str = match.group("description")
    return task_id, task_desc, description
