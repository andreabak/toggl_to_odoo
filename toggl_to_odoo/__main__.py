import argparse
import getpass
import logging
import math
import os.path
from datetime import datetime
from typing import List, Mapping, MutableMapping, Union, Optional, Tuple, Sequence
from urllib.parse import urlparse, ParseResult, urlunparse

import pytz
from dateutil.parser import parse as dateutil_parse
from dateutil.relativedelta import relativedelta

from toggl.api import TimeEntry
from toggl.api.base import TogglSet

from . import converters
from .odoo_upload import odoo_upload
from .utils import fmt_time
from .processing import fetch_and_process
from .convert import get_converter, ChainedConverter, TimesheetLine


LOG_FORMAT: str = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
LOG_DATEFORMAT: str = "%Y-%m-%d %H:%M:%S"


logger: logging.Logger = logging.getLogger(__package__)


class CommaSplitArgs(argparse.Action):
    """
    Converter for command line arguments passed as comma-separated lists of values
    """

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Union[str, Sequence, None],
        option_string: Optional[str] = None,
    ) -> None:
        values = values.split(",") if isinstance(values, str) else values
        setattr(namespace, self.dest, values)


def setup_logger(verbosity: int) -> None:
    log_formatter: logging.Formatter = logging.Formatter(
        fmt=LOG_FORMAT, datefmt=LOG_DATEFORMAT
    )
    stream_handler: logging.StreamHandler = logging.StreamHandler()
    stream_handler.setFormatter(log_formatter)
    logger.addHandler(stream_handler)
    levels: Mapping[int, int] = {
        0: logging.WARNING,
        1: logging.INFO,
        2: logging.DEBUG,
        3: logging.NOTSET,
    }
    verbosity = min(max(min(levels), verbosity), max(levels))
    logger.setLevel(levels[verbosity])


def parse_odoo_credentials(
    url: str, username: Optional[str], password: Optional[str]
) -> Tuple[str, str, str]:
    parsed: ParseResult = urlparse(url)

    if username and parsed.username and parsed.username != username:
        raise AttributeError("Passed two different usernames in url and arguments")
    if not username and not parsed.username:
        username = input("Odoo DB username: ")
    else:
        username = username or parsed.username

    if password and parsed.password and parsed.password != password:
        raise AttributeError("Passed two different passwords in url and arguments")
    if not password and not parsed.password:
        password = getpass.getpass("Odoo DB password: ")
    else:
        password = password or parsed.password

    assert username and password and parsed.hostname  # TODO: convert to exception?

    # Rebuild url without username and password
    cleaned_url: str = urlunparse(
        ParseResult(
            scheme=parsed.scheme,
            netloc=parsed.hostname + (f":{parsed.port}" if parsed.port else ""),
            path=parsed.path,
            params=parsed.params,
            query=parsed.query,
            fragment=parsed.fragment,
        )
    )
    return cleaned_url, username, password


def main():
    general_parser = argparse.ArgumentParser(add_help=False)
    general_parser.add_argument(
        "-v",
        "--verbose",
        dest="verbosity",
        default=-1,
        action="count",
        help="Increase verbosity (can be repeated)",
    )
    general_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Do not make any changes",
    )

    fetch_parser = argparse.ArgumentParser(add_help=False)
    dates_parse_group = fetch_parser.add_mutually_exclusive_group()
    dates_manual_parse_group = dates_parse_group.add_argument_group()
    dates_manual_parse_group.add_argument(
        "-ds",
        "--since",
        metavar="DATETIME",
        help="Get entries since the given date/time",
    )
    dates_manual_parse_group.add_argument(
        "-du",
        "--until",
        metavar="DATETIME",
        help="Get entries until the given date/time",
    )
    dates_parse_group.add_argument(
        "-lm", "--last-month",
        action="store_true",
        help="Get entries from last month",
    )
    dates_parse_group.add_argument(
        "-tm", "--this-month",
        action="store_true",
        help="Get entries from this month",
    )
    dates_parse_group.add_argument(
        "-lw", "--last-week",
        action="store_true",
        help="Get entries from last week",
    )
    dates_parse_group.add_argument(
        "-tw", "--this-week",
        action="store_true",
        help="Get entries from this week",
    )
    fetch_parser.add_argument(
        "-c",
        "--clients",
        metavar="CLIENT[,CLIENT,...]",
        default="",
        help="Clients to filter by, comma-separated",
    )
    fetch_parser.add_argument(
        "-pi",
        "--projects",
        "--projects-include",
        metavar="PROJECT[,PROJECT,...]",
        dest="projects_include",
        default="",
        help="Projects to filter by, comma-separated",
    )
    fetch_parser.add_argument(
        "-pe",
        "--projects-exclude",
        metavar="PROJECT[,PROJECT,...]",
        default="",
        help="Projects to exclude, comma-separated",
    )
    fetch_parser.add_argument(
        "-ti",
        "--tags",
        "--tags-include",
        dest="tags_include",
        metavar="TAG[,TAG,...]",
        default="",
        help="Tags to filter by, comma-separated",
    )
    fetch_parser.add_argument(
        "-te",
        "--tags-exclude",
        metavar="TAG[,TAG,...]",
        default="",
        help="Tags to exclude, comma-separated",
    )
    fetch_parser.add_argument(
        "-s",
        "--snap",
        metavar="SECONDS",
        type=float,
        help="Snap together entries closer than the specified amount of seconds",
    )

    convert_parser = argparse.ArgumentParser(add_help=False)
    convert_parser.add_argument(
        "converter", help="The converter used to process the entries"
    )
    convert_parser.add_argument(
        "-cp",
        "--converts-paths",
        action=CommaSplitArgs,
        help="comma-separated list of paths where to look for converters",
    )
    convert_parser.add_argument(
        "--convert-options",
        nargs="*",
        metavar="OPTION=VALUE",
        help="Additional options for the converters",
    )
    convert_parser.add_argument(
        "--skip-unmatched",
        action="store_true",
        help="Skip unmatched entries during conversion, instead of raising an error",
    )
    convert_parser.add_argument(
        "-m",
        "--merge",
        action="store_true",
        help="Merge timesheet lines by grouping them together into a single one",
    )
    convert_parser.add_argument(
        "--merge-keys",
        metavar="KEY[,KEY,...]",
        default="",
        help="Timesheet fields used to group lines together for merging",
    )

    upload_parser = argparse.ArgumentParser(add_help=False)
    upload_parser.add_argument("url", help="Url of the odoo server")
    upload_parser.add_argument("database", help="Name of the odoo database")
    upload_parser.add_argument(
        "-u",
        "--user",
        "--username",
        dest="username",
        help="Username for the odoo database",
    )
    upload_parser.add_argument(
        "-p",
        "--pass",
        "--password",
        "--apikey",
        dest="password",
        help="Password or API key for the odoo database",
    )
    upload_parser.add_argument(
        "history",
        help="Store upload history in the specified file for incremental uploads",
    )
    upload_parser.add_argument(
        "--create-tasks",
        action="store_true",
        help="Create missing tasks",
    )
    upload_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite conflicting timesheet entries",
    )
    main_parser: argparse.ArgumentParser = argparse.ArgumentParser()
    subparsers = main_parser.add_subparsers(
        title="mode",
        dest="mode",
        required=True,
        help="Action to perform with the entries",
    )
    subparsers.add_parser(
        "fetch", help="Fetch time entries", parents=[general_parser, fetch_parser]
    )
    subparsers.add_parser(
        "convert",
        help="Fetch and convert time entries to timesheet lines",
        parents=[general_parser, fetch_parser, convert_parser],
    )
    subparsers.add_parser(
        "upload",
        help="Fetch, convert and upload time entries to an odoo database",
        parents=[general_parser, fetch_parser, convert_parser, upload_parser],
    )

    args: argparse.Namespace = main_parser.parse_args()

    converters_paths: List[str] = [os.path.join(os.getcwd(), "converters")]
    converters_paths.extend(getattr(args, "converters_paths", None) or [])
    converters.__path__ += converters_paths
    converters.import_converters()

    if args.mode not in ("fetch", "convert", "upload"):
        raise NotImplementedError

    verbosity: int = args.verbosity
    if verbosity == -1:
        verbosity = 1 if args.mode == "fetch" else 0
    setup_logger(verbosity)

    odoo_username: Optional[str] = None
    odoo_password: Optional[str] = None
    odoo_url: Optional[str] = None
    if args.mode == "upload":
        odoo_url, odoo_username, odoo_password = parse_odoo_credentials(
            url=args.url, username=args.username, password=args.password
        )

    with TogglSet.cache_context():
        date_since: Optional[datetime] = None
        date_until: Optional[datetime] = None
        now: datetime = datetime.now(pytz.utc)
        month_start: datetime = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        week_start: datetime = datetime.fromisocalendar(now.year, now.isocalendar()[1], 1)
        if args.last_month:
            date_since = month_start - relativedelta(months=1)
            date_until = month_start
        elif args.this_month:
            date_since = month_start
            date_until = month_start + relativedelta(months=1)
        elif args.last_week:
            date_since = week_start - relativedelta(days=7)
            date_until = week_start
        elif args.this_week:
            date_since = week_start
            date_until = week_start + relativedelta(days=7)
        if args.since:
            date_since = dateutil_parse(args.since)
        if args.until:
            date_until = dateutil_parse(args.until)

        logger.debug("Fetching time entries...")
        time_entries: List[TimeEntry] = fetch_and_process(
            since=date_since,
            until=date_until,
            clients=args.clients.split(",") if args.clients else None,
            projects=args.projects_include.split(",")
            if args.projects_include
            else None,
            projects_exclude=args.projects_exclude.split(",")
            if args.projects_exclude
            else None,
            tags_include=args.tags_include.split(",") if args.tags_include else None,
            tags_exclude=args.tags_exclude.split(",") if args.tags_exclude else None,
            snap_seconds=args.snap or None,
        )
        entries_duration: float = sum(e.duration for e in time_entries)
        logger.info(f"Fetched and processed {len(time_entries)} time entries")
        logger.info(f"Total duration of time entries: {fmt_time(entries_duration)}")

        if args.mode in ("convert", "upload"):
            logger.debug("Converting time entries to timesheet lines...")
            converter: ChainedConverter = get_converter(args.converter)
            converter_options: MutableMapping[str, str] = dict(
                tuple(opt.split("=")) for opt in (args.convert_options or [])
            )
            # TODO: Converter options type casting (how?) / remove feature
            timesheet_lines: List[TimesheetLine] = converter.convert(
                entries=time_entries,
                must_match=not args.skip_unmatched,
                merge=args.merge,
                merge_keys=args.merge_keys.split(",") if args.merge_keys else None,
                **converter_options,
            )
            lines_duration = sum(l["unit_amount"] * 3600 for l in timesheet_lines)
            logger.info(
                f"Converted {len(time_entries)} entries "
                f"to {len(timesheet_lines)} timesheet lines"
            )
            logger.info(
                f"Total duration of timesheet lines: {fmt_time(lines_duration)}"
            )

        if args.mode == "upload":
            odoo_upload(
                timesheet_lines,
                url=odoo_url,
                db=args.database,
                username=odoo_username,
                password=odoo_password,
                history_file=args.history,
                allow_task_creation=args.create_tasks,
                dry_run=args.dry_run,
                overwrite_conflicts=args.force,
            )
        else:
            items: Union[List[TimeEntry], List[TimesheetLine]]
            items = time_entries if args.mode == "fetch" else timesheet_lines
            item: Union[TimeEntry, TimesheetLine]
            for item in items:
                print(repr(item))
            hrs_workday: float = 7.6
            work_days = entries_duration / 60 / 60 / hrs_workday
            time_to_round = (math.ceil(work_days) - work_days) * 60 * 60 * hrs_workday
            print(
                f"Total duration of time entries: {fmt_time(entries_duration)} "
                f"/ ~{work_days:.2f} work days "
                f"(at {hrs_workday} hrs/day), "
                f"{fmt_time(time_to_round)} more to round up"
            )


if __name__ == "__main__":
    main()
