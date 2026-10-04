"""Calendar tool: read and write iCloud events over CalDAV.

The only module that touches the iCloud credentials. Other agents never
import this; they read the `calendar_events` table and ask for writes
through `calendar_event_requests`, which need approval.
"""

import os
import xml.etree.ElementTree as ET
from datetime import date, datetime, time, timedelta, timezone
from typing import Protocol
from urllib.parse import quote, urljoin, urlsplit
from zoneinfo import ZoneInfo

import recurring_ical_events
from icalendar import Calendar as ICalendar
from icalendar import Event as IEvent
from pydantic import BaseModel, Field, model_validator

ICLOUD_CALDAV_URL = "https://caldav.icloud.com"
# iCloud redirects each account to its own pNN-caldav.icloud.com host. Credentials
# are only ever sent to hosts under this domain, whatever the server tells us.
ALLOWED_HOST_SUFFIX = ".icloud.com"
DEFAULT_TZ = "Asia/Hong_Kong"
REQUEST_TIMEOUT_SECONDS = 30
MAX_ERROR_CHARS = 200
NO_TITLE = "(no title)"


class CalendarError(Exception):
    """Raised when iCloud can't be read or written. Message is already scrubbed."""


class CalendarEvent(BaseModel):
    uid: str
    calendar_name: str
    title: str
    starts_at: datetime
    ends_at: datetime | None = None
    all_day: bool = False
    location: str | None = None


class NewEvent(BaseModel):
    uid: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    starts_at: datetime
    ends_at: datetime
    all_day: bool = False
    location: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _check_times(self) -> "NewEvent":
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("starts_at and ends_at must be timezone-aware")
        if self.ends_at < self.starts_at:
            raise ValueError("ends_at must not be before starts_at")
        return self


class CalendarBackend(Protocol):
    """What the tool needs from a CalDAV server; tests use an in-memory fake."""

    def list_calendars(self) -> list[str]: ...

    def fetch_ical(self, calendar_name: str, start: datetime, end: datetime) -> list[str]: ...

    def put_ical(self, calendar_name: str, uid: str, ical: str) -> None: ...


def scrub(text: str, secrets: list[str]) -> str:
    """Remove credentials from text that is about to be logged or stored."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text[:MAX_ERROR_CHARS]


def _to_aware(value: date | datetime, tz: ZoneInfo) -> tuple[datetime, bool]:
    """Return (aware datetime, is_all_day). A bare date means an all-day event."""
    if isinstance(value, datetime):
        # Floating times (no tz) are meant as local wall-clock time.
        return (value if value.tzinfo else value.replace(tzinfo=tz)), False
    return datetime.combine(value, time.min, tzinfo=tz), True


def parse_events(
    ical: str, calendar_name: str, tz: ZoneInfo, start: datetime, end: datetime
) -> list[CalendarEvent]:
    """Events from one CalDAV object that fall in [start, end). Repeating events
    are expanded here, because iCloud returns the series, not its occurrences."""
    try:
        parsed = ICalendar.from_ical(ical)
        components = recurring_ical_events.of(parsed).between(start, end)
    except Exception:  # one malformed object must not break the whole sync
        return []

    events: list[CalendarEvent] = []
    for component in components:
        uid = component.get("UID")
        dtstart = component.get("DTSTART")
        if uid is None or dtstart is None:
            continue
        if str(component.get("STATUS", "")).upper() == "CANCELLED":
            continue

        starts_at, all_day = _to_aware(dtstart.dt, tz)
        dtend = component.get("DTEND")
        ends_at = _to_aware(dtend.dt, tz)[0] if dtend is not None else None
        location = str(component.get("LOCATION") or "").strip() or None
        events.append(
            CalendarEvent(
                uid=str(uid),
                calendar_name=calendar_name,
                title=str(component.get("SUMMARY") or "").strip() or NO_TITLE,
                starts_at=starts_at,
                ends_at=ends_at,
                all_day=all_day,
                location=location,
            )
        )
    return events


def build_ical(event: NewEvent, tz: ZoneInfo) -> str:
    component = IEvent()
    component.add("uid", event.uid)
    component.add("dtstamp", datetime.now(timezone.utc))
    component.add("summary", event.title)
    if event.all_day:
        # All-day events use dates; DTEND is exclusive, so it is always a later day.
        start_day = event.starts_at.astimezone(tz).date()
        end_day = max(event.ends_at.astimezone(tz).date(), start_day + timedelta(days=1))
        component.add("dtstart", start_day)
        component.add("dtend", end_day)
    else:
        component.add("dtstart", event.starts_at.astimezone(timezone.utc))
        component.add("dtend", event.ends_at.astimezone(timezone.utc))
    if event.location:
        component.add("location", event.location)
    if event.notes:
        component.add("description", event.notes)

    calendar = ICalendar()
    calendar.add("prodid", "-//Friday//Calendar Agent//EN")
    calendar.add("version", "2.0")
    calendar.add_component(component)
    return calendar.to_ical().decode("utf-8")


class CalendarTool:
    def __init__(
        self, backend: CalendarBackend, tz: ZoneInfo, secrets: list[str] | None = None
    ) -> None:
        self._backend = backend
        self._tz = tz
        self._secrets = secrets or []

    def _fail(self, action: str, exc: Exception) -> CalendarError:
        detail = scrub(f"{exc.__class__.__name__}: {exc}", self._secrets)
        return CalendarError(f"{action} failed: {detail}")

    def list_calendars(self) -> list[str]:
        try:
            return self._backend.list_calendars()
        except Exception as exc:  # caldav raises many classes; callers only need one
            # `from None` drops the original traceback, which can carry the request URL/auth.
            raise self._fail("list calendars", exc) from None

    def upcoming(self, calendar_names: list[str], days: int) -> list[CalendarEvent]:
        """Events happening in the next `days` days, across the given calendars."""
        if not 1 <= days <= 366:
            raise ValueError("days must be between 1 and 366")
        start = datetime.now(timezone.utc)
        end = start + timedelta(days=days)

        events: list[CalendarEvent] = []
        for name in calendar_names:
            try:
                objects = self._backend.fetch_ical(name, start, end)
            except Exception as exc:
                raise self._fail("read calendar", exc) from None
            for ical in objects:
                events.extend(parse_events(ical, name, self._tz, start, end))

        unique = {(e.calendar_name, e.uid, e.starts_at): e for e in events}
        return sorted(unique.values(), key=lambda e: e.starts_at)

    def create(self, calendar_name: str, event: NewEvent) -> None:
        """Write one event. Same uid twice updates the event instead of duplicating it."""
        ical = build_ical(event, self._tz)
        try:
            self._backend.put_ical(calendar_name, event.uid, ical)
        except Exception as exc:
            raise self._fail("write event", exc) from None


NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav"}

PRINCIPAL_BODY = (
    '<d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop></d:propfind>'
)
HOME_BODY = (
    '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    "<d:prop><c:calendar-home-set/></d:prop></d:propfind>"
)
CALENDARS_BODY = (
    '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop>'
    "<d:displayname/><d:resourcetype/><c:supported-calendar-component-set/>"
    "</d:prop></d:propfind>"
)
QUERY_BODY = (
    '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    "<d:prop><c:calendar-data/></d:prop><c:filter>"
    '<c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
    '<c:time-range start="{start}" end="{end}"/>'
    "</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>"
)


def check_url(url: str) -> str:
    """Refuse to send credentials anywhere but iCloud over TLS."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not ("." + host).endswith(ALLOWED_HOST_SUFFIX):
        raise ValueError("refusing to talk to a non-iCloud or non-HTTPS host")
    return url


def parse_calendars(xml: str, base_url: str) -> dict[str, str]:
    """Map display name -> collection URL for collections that can hold events."""
    found: dict[str, str] = {}
    for response in ET.fromstring(xml).findall("d:response", NS):
        href = response.findtext("d:href", default="", namespaces=NS)
        if response.find(".//d:resourcetype/c:calendar", NS) is None:
            continue
        # iCloud lists Reminders collections here too; they only take VTODO.
        components = {c.get("name") for c in response.findall(".//c:comp", NS)}
        name = response.findtext(".//d:displayname", default="", namespaces=NS).strip()
        if "VEVENT" in components and name and href:
            found[name] = urljoin(base_url, href)
    return found


class CalDavBackend:
    """Minimal CalDAV client: just what the tool needs. Connects on first use.

    Hand-written on purpose: the `caldav` package timed out against iCloud, and
    this keeps every request that carries the credentials in ~80 visible lines.
    """

    def __init__(self, url: str, username: str, password: str) -> None:
        self._url = url
        self._auth = (username, password)
        self._calendars: dict[str, str] | None = None

    def __repr__(self) -> str:  # never let credentials reach a log line
        return "CalDavBackend(<redacted>)"

    def _request(self, method: str, url: str, body: str, depth: str | None = None) -> str:
        # Imported lazily so tests and the heartbeat never need the library.
        import httpx

        headers = {"Content-Type": "application/xml; charset=utf-8"}
        if depth is not None:
            headers["Depth"] = depth
        if method == "PUT":
            headers["Content-Type"] = "text/calendar; charset=utf-8"
        # No redirects: a redirect must not carry the credentials to another host.
        response = httpx.request(
            method,
            check_url(url),
            content=body.encode("utf-8"),
            headers=headers,
            auth=self._auth,
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=False,
        )
        if response.status_code >= 300:
            # Status only: response bodies and URLs can contain account identifiers.
            raise RuntimeError(f"iCloud answered HTTP {response.status_code}")
        return response.text

    def _href(self, xml: str, path: str, base_url: str) -> str:
        href = ET.fromstring(xml).findtext(path, default="", namespaces=NS)
        if not href:
            raise RuntimeError("iCloud response was missing an expected address")
        return urljoin(base_url, href)

    def _load(self) -> dict[str, str]:
        if self._calendars is None:
            xml = self._request("PROPFIND", self._url, PRINCIPAL_BODY, depth="0")
            principal = self._href(xml, ".//d:current-user-principal/d:href", self._url)
            xml = self._request("PROPFIND", principal, HOME_BODY, depth="0")
            home = self._href(xml, ".//c:calendar-home-set/d:href", principal)
            xml = self._request("PROPFIND", home, CALENDARS_BODY, depth="1")
            self._calendars = parse_calendars(xml, home)
        return self._calendars

    def _calendar_url(self, calendar_name: str) -> str:
        calendars = self._load()
        if calendar_name not in calendars:
            raise KeyError("calendar not found")
        return calendars[calendar_name]

    def list_calendars(self) -> list[str]:
        return sorted(self._load())

    def fetch_ical(self, calendar_name: str, start: datetime, end: datetime) -> list[str]:
        stamp = "%Y%m%dT%H%M%SZ"
        body = QUERY_BODY.format(
            start=start.astimezone(timezone.utc).strftime(stamp),
            end=end.astimezone(timezone.utc).strftime(stamp),
        )
        xml = self._request("REPORT", self._calendar_url(calendar_name), body, depth="1")
        return [node.text for node in ET.fromstring(xml).iterfind(".//c:calendar-data", NS)
                if node.text]

    def put_ical(self, calendar_name: str, uid: str, ical: str) -> None:
        # The uid names the resource, so writing the same request twice overwrites.
        url = urljoin(self._calendar_url(calendar_name), quote(uid, safe="") + ".ics")
        self._request("PUT", url, ical)


def calendar_timezone() -> ZoneInfo:
    return ZoneInfo(os.environ.get("CALENDAR_TZ", DEFAULT_TZ))


def build_calendar_tool() -> CalendarTool:
    """Build the real iCloud-backed tool from the environment."""
    username = os.environ.get("ICLOUD_USERNAME")
    password = os.environ.get("ICLOUD_APP_PASSWORD")
    if not username or not password:
        raise CalendarError("ICLOUD_USERNAME / ICLOUD_APP_PASSWORD are not set")

    backend = CalDavBackend(ICLOUD_CALDAV_URL, username, password)
    return CalendarTool(backend, calendar_timezone(), secrets=[password, username])
