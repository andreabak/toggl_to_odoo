from typing import Optional

from toggl.api import TimeEntry

from toggl_to_odoo.convert import ChainedConverter, SimpleConverter, TimesheetLine
from .odoo_common import (
    OdooConverter,
    OdooOnboarding,
    OdooTraining,
    OdooOwndb,
    OdooMisc,
    OdooImprovement,
    OdooCoaching,
    OdooReview,
    OdooTask,
    extract_task,
)


converter2owndb = ChainedConverter("toggl2owndb")


class SimpleConverter2Owndb(SimpleConverter):
    ...


class OdooConverter2Owndb(SimpleConverter2Owndb, OdooConverter):
    def convert(self, entry: TimeEntry) -> TimesheetLine:
        line: TimesheetLine = super().convert(entry)
        line["project"] = f"Odoo {line['date'].year}"
        return line


@converter2owndb.register(110)
class OdooOnboarding2Owndb(OdooOnboarding, OdooConverter2Owndb):
    def convert(self, entry: TimeEntry) -> TimesheetLine:
        line: TimesheetLine = super().convert(entry)
        line.update(
            task="Training (functional)",
            name=f"[onboarding] {entry.description}",
        )
        return line


@converter2owndb.register(120)
class OdooTraining2Owndb(OdooTraining, OdooConverter2Owndb):
    def convert(self, entry: TimeEntry) -> TimesheetLine:
        line: TimesheetLine = super().convert(entry)
        line["task"] = "Training (technical)"
        return line


@converter2owndb.register(180)
class OdooOwndb2Owndb(OdooOwndb, OdooConverter2Owndb):
    def convert(self, entry: TimeEntry) -> TimesheetLine:
        line: TimesheetLine = super().convert(entry)
        line["task"] = "Training (owndb)"
        return line


@converter2owndb.register(210)
class OdooMisc2Owndb(OdooMisc, OdooConverter2Owndb):
    def convert(self, entry: TimeEntry) -> TimesheetLine:
        line: TimesheetLine = super().convert(entry)
        line["task"] = "Miscellaneous"
        return line


@converter2owndb.register(410)
class OdooImprovement2Owndb(OdooImprovement, OdooConverter2Owndb):
    def convert(self, entry: TimeEntry) -> TimesheetLine:
        line: TimesheetLine = super().convert(entry)
        line["task"] = "Int. Improvement"
        return line


@converter2owndb.register(510)
class OdooCoaching2Owndb(OdooCoaching, OdooConverter2Owndb):
    def convert(self, entry: TimeEntry) -> TimesheetLine:
        line: TimesheetLine = super().convert(entry)
        line["task"] = "Coaching"
        return line


@converter2owndb.register(610)
class OdooReview2Owndb(OdooReview, OdooConverter2Owndb):
    def convert(self, entry: TimeEntry) -> TimesheetLine:
        line: TimesheetLine = super().convert(entry)
        line["task"] = "Code Review"
        return line


@converter2owndb.register(810)
class OdooTask2Owndb(OdooTask, OdooConverter2Owndb):
    def convert(self, entry: TimeEntry) -> TimesheetLine:
        line: TimesheetLine = super().convert(entry)
        task_id: int
        task_desc: Optional[str]
        description: str
        task_id, task_desc, description = extract_task(entry)
        line.update(
            task=f"[{task_id}]" + (f" {task_desc}" if task_desc else ""),
            name=description,
        )
        return line


@converter2owndb.register(9999)
class OdooNonBillable2Owndb(OdooConverter2Owndb):
    def matches(self, entry: TimeEntry) -> bool:
        return super().matches(entry) and "non-billable" in entry.tags

    def convert(self, entry: TimeEntry) -> TimesheetLine:
        line: TimesheetLine = super().convert(entry)
        line["task"] = "Non-billable"
        return line
