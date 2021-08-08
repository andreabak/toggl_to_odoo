import logging
import shelve
from functools import lru_cache
from typing import (
    Iterable,
    List,
    Tuple,
    Any,
    TypeVar,
    MutableMapping,
    Optional,
    Union,
    Collection,
    Hashable,
    Set,
    Sequence,
)

from .convert import TimesheetLine
from .odoo_xmlrpc import OdooXmlRpc


logger: logging.Logger = logging.getLogger(__name__)


class UploadException(Exception):
    ...


class MissingRecord(UploadException):
    ...


class TooManyRecords(UploadException):
    ...


class ConstraintError(UploadException):
    ...


class HistoryError(UploadException):
    ...


class InconsistentHistory(HistoryError):
    ...


_V = TypeVar("_V")


def ensure_one(results: List[_V], model: str, field: str, value: Any) -> _V:
    if not results:
        raise MissingRecord(f'No results found in "{model}" with {field}: {value}')
    if len(results) > 1:
        raise TooManyRecords(
            f'More than one result in "{model}" matching {field}: {value}'
        )
    return results[0]


def name_search_one(odoo_rpc: OdooXmlRpc, model: str, name: str) -> int:
    rpc_result: List[Tuple[int, str]] = odoo_rpc.name_search(model, name, limit=10)
    return ensure_one(rpc_result, model, "name", name)[0]


def read_one(
    odoo_rpc: OdooXmlRpc,
    model: str,
    id_: int,
    fields: Optional[Sequence[str]] = None,
) -> MutableMapping[str, Any]:
    rpc_result: List[MutableMapping[str, Any]] = odoo_rpc.read(model, id_, fields)
    return ensure_one(rpc_result, model, "id", id_)


@lru_cache()
def find_one(
    odoo_rpc: OdooXmlRpc,
    model: str,
    name_or_id: Union[str, int],
    fields: Optional[Sequence[str]] = None,
) -> MutableMapping[str, Any]:
    record_id: int
    if isinstance(name_or_id, str):
        record_id = name_search_one(odoo_rpc, model, name_or_id)
    else:
        record_id = int(name_or_id)
    return read_one(odoo_rpc, model, record_id, fields)


def odoo_upload_line(
    line: TimesheetLine,
    odoo_rpc: OdooXmlRpc,
    history: Optional[shelve.DbfilenameShelf],
    allow_task_creation: bool = False,
    dry_run: bool = False,
) -> int:
    def create_record(
        model: str,
        values: MutableMapping[str, Any],
        refs: Optional[Collection[Hashable]] = None,
    ) -> int:
        nonlocal odoo_rpc, history, dry_run
        if dry_run:
            print(
                f"[DRY RUN] Would create new record in {model} with values {repr(values)}"
            )
            return -1
        new_id: int = odoo_rpc.create(model, values)
        print(f"Created new record in {model} with id={new_id}")
        refs = refs or []
        assert history is not None
        history.setdefault(model, {})
        history[model].setdefault(new_id, set())
        history[model][new_id] |= set(refs)
        history.setdefault("_refs", {})
        history["_refs"].update({(model, ref): new_id for ref in refs})
        history.sync()
        return new_id

    # Must explicitly specify fields due to broken xmlrpc bug in odoo saas~14.4,
    # that doesn't serialize/escape HTML, resulting in invalid xml for html fields.
    # Also improves performance, with a small sacrifice in code flexibility.
    project_fields: Sequence[str] = ("id", "name")
    task_fields: Sequence[str] = ("id", "name", "project_id")

    project: Optional[MutableMapping[str, Any]] = (
        find_one(odoo_rpc, "project.project", line["project"], project_fields)
        if "project" in line
        else None
    )
    # TODO: maybe restrict task search domain to project when specified
    new_task: bool
    task: Optional[MutableMapping[str, Any]] = None
    try:
        if "task" in line:
            task = find_one(odoo_rpc, "project.task", line["task"], task_fields)
        new_task = False
    except MissingRecord as exc:
        if not isinstance(line["task"], str):
            raise ConstraintError("No task found and line's is not str") from exc
        # pylint: disable=raise-missing-from
        if not allow_task_creation:
            raise ConstraintError("Task creation is not enabled")
        new_task = True

    # Project must exist
    if project is None:
        if new_task:
            raise ConstraintError("Cannot create new task without project")
        if task is None:
            raise ConstraintError("No project nor task in line")
        project = find_one(
            odoo_rpc, "project.project", task["project_id"][0], project_fields
        )
    else:
        if task is not None and task["project_id"][0] != project["id"]:
            raise ConstraintError("Task's project and specified project mismatch")

    if new_task:
        new_task_data: MutableMapping[str, Any] = dict(
            name=line["task"], project_id=project["id"]
        )
        new_task_id: int = create_record("project.task", new_task_data)

        if dry_run and new_task_id == -1:
            task = dict(new_task_data, id="NEW")
        else:
            task = find_one(odoo_rpc, "project.task", new_task_id, task_fields)

    # TODO: Maybe try searching timesheet entry with same values (except time unit) and either raise an error or warn
    assert task is not None
    new_ts_line_id: int = create_record(
        "account.analytic.line",
        dict(
            date=line["date"].isoformat(),
            project_id=project["id"],
            task_id=task["id"],
            name=line["name"],
            unit_amount=line["unit_amount"],
        ),
        refs=line["_toggl_ids"],
    )
    return new_ts_line_id


# TODO: convert to delete line and get refs from there?
def odoo_delete_records(
    model: str,
    ids: Set[int],
    odoo_rpc: OdooXmlRpc,
    history: Optional[shelve.DbfilenameShelf],
):
    if not odoo_rpc.unlink(model, list(ids)):
        raise UploadException(f'Failed deleting records for "{model}" (ids={ids})')
    if history is not None:
        conflict_refs: Set[int] = {
            ref for id_ in ids for ref in history[model].pop(id_, [])
        }
        for ref in conflict_refs:
            history["_refs"].pop((model, ref), None)
        history.sync()


def match_history_refs(
    history: MutableMapping[str, Any], record_model: str, refs: Set[int]
) -> Set[int]:
    if "_refs" not in history:
        raise InconsistentHistory('Missing "_refs" dict')
    stored_refs: Set[int] = set()
    ref: int
    for ref in refs:
        ref_key: Tuple[str, Any] = (record_model, ref)
        record_id: Optional[int] = history["_refs"].get(ref_key)
        if record_id is None:
            continue
        if record_model not in history:
            raise InconsistentHistory(f'Missing "{record_model}" dict')
        if record_id not in history[record_model]:
            raise InconsistentHistory(
                f'Missing referenced record id={record_id} in "{record_model}" dict'
            )
        stored_refs |= history[record_model][record_id]
    return stored_refs


def odoo_upload(
    timesheet_lines: Iterable[TimesheetLine],
    url: str,
    db: str,
    username: str,
    password: str,
    history_file: Optional[str] = None,
    allow_task_creation: bool = False,
    dry_run: bool = False,
    overwrite_conflicts: bool = False,
):
    logger.info(f"Connecting to XML-RPC at {url}")
    odoo_rpc: OdooXmlRpc = OdooXmlRpc(
        url=url, db=db, username=username, password=password
    )
    odoo_rpc.authenticate()

    history: Optional[shelve.DbfilenameShelf] = None
    if history_file:
        history = shelve.open(history_file, writeback=True)
        history.setdefault("_refs", {})
    else:
        logger.warning(
            ("[DRY RUN] Would perform " if dry_run else "Performing ")
            + "upload without history file!"
        )
    # TODO: Exclude already uploaded
    line: TimesheetLine
    for line in timesheet_lines:
        try:
            if history is not None:
                if not line.get("_toggl_ids"):
                    raise ConstraintError('Timesheet line without "_toggl_ids"!')
                line_refs: Set[int] = line["_toggl_ids"]
                model_name: str = "account.analytic.line"
                stored_refs: Set[int] = match_history_refs(
                    history, model_name, line_refs
                )
                if not stored_refs:
                    pass  # proceed with upload
                elif stored_refs == line_refs:
                    # TODO: Verify line still exists in remote db or not?
                    continue  # already exists, no need to insert
                elif overwrite_conflicts:
                    conflict_ids: Set[int] = {
                        history["_refs"][(model_name, ref)] for ref in stored_refs
                    }
                    logger.warning(
                        ("[DRY RUN] Would delete" if dry_run else "Deleting")
                        + f' conflicting "{model_name}" records with ids={conflict_ids}'
                    )
                    if not dry_run:
                        odoo_delete_records(
                            model=model_name,
                            ids=conflict_ids,
                            odoo_rpc=odoo_rpc,
                            history=history,
                        )
                else:
                    raise HistoryError(
                        f'Stored records "{model_name}" refs mismatch: '
                        f"stored={stored_refs} vs current={line_refs}"
                    )

            odoo_upload_line(
                line,
                odoo_rpc=odoo_rpc,
                history=history,
                allow_task_creation=allow_task_creation,
                dry_run=dry_run,
            )
        except UploadException as exc:
            raise UploadException(
                f"Error while trying to upload line: {line}\n"
                f"{exc.__class__.__name__}: {exc}"
            ) from exc
