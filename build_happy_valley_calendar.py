#!/usr/bin/env python3
"""Build Happy Valley racing calendar ICS/CSV/README from official HKJC sources.

Sources (priority order):
1. Official HKJC Google Calendar ICS feed (live auto-updating)
2. PDF baseline in data/baseline_26-27.json (anti-drift reference)
3. Monthly fixture pages on racing.hkjc.com (provisional race counts)
4. Published race cards (first-race times when available)

Never invent dates. Never invent race times.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
BASELINE_PATH = ROOT / "data" / "baseline_26-27.json"
DOCS_DIR = ROOT / "docs"
ICS_PATH = DOCS_DIR / "happy-valley.ics"
CSV_PATH = ROOT / "Happy_Valley_Racing_2026-27_Details.csv"
README_PATH = ROOT / "Happy_Valley_Racing_2026-27_README.md"
PREVIEW_JSON = ROOT / "data" / "preview_events.json"

HKJC_FEED = (
    "https://calendar.google.com/calendar/ical/"
    "gturu5cp1tfpdgmlio8tinhlis%40group.calendar.google.com/public/basic.ics"
)
FIXTURE_PDF = (
    "https://res.hkjc.com/racingnews/wp-content/uploads/sites/3/2026/07/fixture_26-27.pdf"
)
RACING_NEWS_FIXTURES = (
    "https://racingnews.hkjc.com/english/2026/07/20/racing-fixtures-2026-2027-season/"
)
AMENDMENT_NO1 = (
    "https://racingnews.hkjc.com/english/2026/09/08/"
    "2026-2027-season-programme-amendment-no-1/"
)
HKJC_RACING_CAL = "https://www.hkjc.com/english/racinginfo/racing-calendar.asp"
FIXTURE_MONTHLY = (
    "https://racing.hkjc.com/racing/information/english/Racing/Fixture.aspx"
    "?CalMonth={month:02d}&CalYear={year}"
)
RACECARD = (
    "https://racing.hkjc.com/racing/information/English/Racing/RaceCard.aspx"
    "?RaceDate={yyyy}/{mm}/{dd}&Racecourse=HV&RaceNo={race_no}"
)
INTERNAL_NOTE_MARKERS = ("Programme Amendment",)
RACE_INFO = (
    "https://www.hkjc.com/english/racinginfo/racing_cal.asp?d={yyyymmdd}"
)

VENUE = "Happy Valley Racecourse"
ADDRESS = "Wong Nai Chung Road, Happy Valley, Hong Kong"
LOCATION = f"{VENUE}, {ADDRESS}"
GEO_LAT = 22.2706
GEO_LON = 114.1840
TZ_NAME = "Asia/Hong_Kong"
TZ = ZoneInfo(TZ_NAME)
SURFACE = "Turf"
PRODID = "-//Happy Valley Racing Calendar//EN"
CALNAME = "Happy Valley Racing"
# Bump when published DESCRIPTION layout changes so SEQUENCE increments for subscribers.
DESCRIPTION_SCHEMA = "v3-apple-structured-location"

# Provisional placeholders only — never presented as official times.
NIGHT_START = (19, 0)
NIGHT_END = (23, 0)
DAY_START = (13, 0)
DAY_END = (18, 0)

UA = "HappyValleyCalendarBuilder/1.0 (+local; educational; respects HKJC terms)"


def fetch(url: str, timeout: int = 45) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            return data.decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} fetching {url}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error fetching {url}: {e}") from e


def unfold_ics(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n[ \t]", "", text)


def parse_ics_events(text: str) -> list[dict[str, str]]:
    text = unfold_ics(text)
    chunks = text.split("BEGIN:VEVENT")[1:]
    events: list[dict[str, str]] = []
    for chunk in chunks:
        body = chunk.split("END:VEVENT", 1)[0]
        props: dict[str, str] = {}
        for line in body.split("\n"):
            if not line or ":" not in line:
                continue
            key, val = line.split(":", 1)
            name = key.split(";", 1)[0].upper()
            props[name] = val.strip()
        events.append(props)
    return events


def load_baseline() -> dict[str, Any]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def fetch_official_hv_events() -> list[dict[str, Any]]:
    raw = fetch(HKJC_FEED)
    if "BEGIN:VCALENDAR" not in raw:
        raise RuntimeError("Official HKJC feed did not return a VCALENDAR")
    events = parse_ics_events(raw)
    if not events:
        raise RuntimeError("Official HKJC feed returned zero events")

    hv: list[dict[str, Any]] = []
    for e in events:
        summary = e.get("SUMMARY", "")
        if not summary.startswith("HV"):
            continue
        dt = e.get("DTSTART", "")
        if len(dt) != 8 or not dt.isdigit():
            raise RuntimeError(f"Unexpected DTSTART in feed: {dt!r} for {summary}")
        d = date(int(dt[:4]), int(dt[4:6]), int(dt[6:8]))
        session = "Day" if "Day" in summary else "Night"
        special = ""
        if " - " in summary:
            special = summary.split(" - ", 1)[1].strip()
        hv.append(
            {
                "date": d.isoformat(),
                "day": d.strftime("%A"),
                "session": session,
                "feed_summary": summary,
                "special_event": special,
                "feed_description": e.get("DESCRIPTION", ""),
                "feed_uid": e.get("UID", ""),
                "feed_status": e.get("STATUS", "CONFIRMED"),
            }
        )
    hv.sort(key=lambda x: x["date"])
    return hv


def reconcile(baseline: dict[str, Any], feed_events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    base_by_date = {m["date"]: m for m in baseline["meetings"]}
    feed_by_date = {e["date"]: e for e in feed_events}
    changes: list[str] = []

    only_base = sorted(set(base_by_date) - set(feed_by_date))
    only_feed = sorted(set(feed_by_date) - set(base_by_date))
    for d in only_base:
        changes.append(f"REMOVED from official feed (was in PDF baseline): {d}")
    for d in only_feed:
        changes.append(f"ADDED in official feed (not in PDF baseline): {d}")

    # Prefer live feed dates; annotate with baseline session when present.
    merged: list[dict[str, Any]] = []
    for d, fe in sorted(feed_by_date.items()):
        be = base_by_date.get(d)
        session = fe["session"]
        if be and be["session"] != fe["session"]:
            changes.append(
                f"SESSION mismatch {d}: baseline={be['session']} feed={fe['session']} (using feed)"
            )
        notes = (be or {}).get("notes", "") or ""
        if fe["special_event"] and not notes:
            notes = fe["special_event"]
        tentative = d in only_feed or d in only_base
        if be and be.get("day") != fe["day"]:
            changes.append(f"WEEKDAY mismatch {d}: baseline={be['day']} feed={fe['day']}")
        # Prefer live-feed special labels; fall back to baseline notes that are
        # real meeting names — never promote internal amendment notes.
        special = fe["special_event"] or ""
        if not special and notes and not is_internal_note(notes):
            special = notes
        merged.append(
            {
                "date": d,
                "day": fe["day"],
                "session": session,
                "special_event": special,
                "feed_summary": fe["feed_summary"],
                "notes": notes,
                "baseline_present": be is not None,
                "force_tentative": tentative,
            }
        )

    # If feed is empty of HV, hard fail (already checked). If count drifts, warn but continue.
    expected = baseline["official_summary"]["total_happy_valley"]
    if len(merged) != expected:
        changes.append(
            f"COUNT drift: expected {expected} Happy Valley meetings from baseline, "
            f"official feed currently has {len(merged)}"
        )
    return merged, changes


def is_internal_note(text: str) -> bool:
    """True for baseline/changelog notes that are not public special-event labels."""
    return any(marker in text for marker in INTERNAL_NOTE_MARKERS)


def format_distance_summary(by_distance: dict[str, int]) -> str:
    parts = [
        f"{count}x{dist}m"
        for dist, count in sorted(by_distance.items(), key=lambda x: int(x[0]))
    ]
    return ", ".join(parts)


def parse_fixture_day_programmes(
    html: str,
) -> dict[int, dict[str, Any]]:
    """Parse provisional race programmes per calendar day from Fixture.aspx HTML.

    Tokens like ``1200(2)`` mean two races at 1200 m — sum the parenthetical
    section counts rather than counting token lines.
    """
    html = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", "", html, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"</tr>", "\n---ROW---\n", text, flags=re.I)
    text = re.sub(r"</td>", "\n---CELL---\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    results: dict[int, dict[str, Any]] = {}
    for block in re.split(r"---CELL---|---ROW---", text):
        lines = [re.sub(r"\s+", " ", ln).strip() for ln in block.split("\n")]
        lines = [ln for ln in lines if ln]
        if not lines or not lines[0].isdigit():
            continue
        day = int(lines[0])
        if day < 1 or day > 31:
            continue
        pairs = re.findall(r"(\d{3,4})\((\d+)\)", " ".join(lines[1:]))
        if not pairs:
            continue
        by_distance: dict[str, int] = {}
        total = 0
        for dist, sections in pairs:
            n = int(sections)
            total += n
            by_distance[dist] = by_distance.get(dist, 0) + n
        results[day] = {
            "count": total,
            "by_distance": by_distance,
            "summary": format_distance_summary(by_distance),
        }
    return results


def parse_fixture_day_race_counts(html: str) -> dict[int, int]:
    """Compatibility wrapper: day → total race count from provisional programme."""
    return {day: info["count"] for day, info in parse_fixture_day_programmes(html).items()}


def racecard_url_for(d: date, race_no: int = 1) -> str:
    return RACECARD.format(
        yyyy=f"{d.year:04d}",
        mm=f"{d.month:02d}",
        dd=f"{d.day:02d}",
        race_no=race_no,
    )


def parse_race_card_detail(html: str, race_no: int) -> dict[str, Any] | None:
    """Extract time / distance / class for one race from a RaceCard.aspx page."""
    pat = re.compile(
        rf"Race\s*{race_no}\s*-\s*([^<]+)</span><br>"
        rf"[^<]*,\s*(\d{{1,2}}:\d{{2}})<br>"
        rf"[^<]*?(\d{{3,4}})M[^<]*<br>"
        rf"[^<]*?(Class\s*\d)",
        re.I,
    )
    m = pat.search(html)
    if not m:
        # Fallback: looser extraction around the Race N header.
        header = re.search(
            rf"Race\s*{race_no}\s*-\s*([^<]+)</span><br>([\s\S]{{0,220}})",
            html,
            re.I,
        )
        if not header:
            return None
        blob = header.group(0)
        time_m = re.search(r"\b(\d{1,2}:\d{2})\b", blob)
        dist_m = re.search(r"\b(\d{3,4})M\b", blob)
        class_m = re.search(r"(Class\s*\d)", blob, re.I)
        if not (time_m and dist_m and class_m):
            return None
        name = re.sub(r"\s+", " ", header.group(1)).strip()
        return {
            "no": race_no,
            "name": name,
            "time": time_m.group(1),
            "distance_m": int(dist_m.group(1)),
            "class": class_m.group(1).title().replace("Class ", "Class "),
        }
    name = re.sub(r"\s+", " ", m.group(1)).strip()
    klass = re.sub(r"\s+", " ", m.group(4)).strip()
    if klass.lower().startswith("class"):
        klass = "Class " + klass.split()[-1]
    return {
        "no": race_no,
        "name": name,
        "time": m.group(2),
        "distance_m": int(m.group(3)),
        "class": klass,
    }


def enrich_race_counts(meetings: list[dict[str, Any]]) -> None:
    months = sorted({(int(m["date"][:4]), int(m["date"][5:7])) for m in meetings})
    cache: dict[tuple[int, int], dict[int, dict[str, Any]]] = {}
    url_cache: dict[tuple[int, int], str] = {}
    for year, month in months:
        url = FIXTURE_MONTHLY.format(month=month, year=year)
        url_cache[(year, month)] = url
        try:
            html = fetch(url)
            cache[(year, month)] = parse_fixture_day_programmes(html)
            print(
                f"  fetched fixture {year}-{month:02d} "
                f"({len(cache[(year, month)])} programmed days)"
            )
        except RuntimeError as e:
            print(f"  WARN fixture page {year}-{month:02d}: {e}")
            cache[(year, month)] = {}

    for m in meetings:
        d = date.fromisoformat(m["date"])
        info = cache.get((d.year, d.month), {}).get(d.day)
        m["fixture_page_url"] = url_cache.get(
            (d.year, d.month), FIXTURE_MONTHLY.format(month=d.month, year=d.year)
        )
        m["race_programme"] = []
        m["provisional_programme_summary"] = None
        m["fixture_race_count"] = None
        m["races_source"] = None
        if info:
            m["fixture_race_count"] = info["count"]
            m["number_of_races"] = info["count"]
            m["number_of_races_label"] = str(info["count"])
            m["provisional_programme_summary"] = info["summary"]
            m["races_source"] = "FIXTURE"
        else:
            m["number_of_races"] = None
            m["number_of_races_label"] = "Not yet published"


def enrich_first_race_times(meetings: list[dict[str, Any]]) -> None:
    """Fetch published race cards for near-term meetings; leave others unpublished."""
    today = datetime.now(TZ).date()
    for m in meetings:
        d = date.fromisoformat(m["date"])
        m["racecard_url"] = racecard_url_for(d, 1)
        m["official_info_url"] = RACE_INFO.format(yyyymmdd=d.strftime("%Y%m%d"))
        m["first_race_time"] = None
        m["first_race_time_label"] = "To be confirmed by HKJC"
        m["time_source"] = "PROVISIONAL"
        m["race_card_published"] = False
        m.setdefault("race_programme", [])

        # Probe race cards for meetings within a ~45-day forward window (and recent past).
        if d > today + timedelta(days=45) or d < today - timedelta(days=7):
            continue
        try:
            html = fetch(m["racecard_url"])
        except RuntimeError as e:
            print(f"  WARN racecard {m['date']}: {e}")
            continue

        if "Happy Valley" not in html and "跑馬地" not in html:
            continue

        race_nos = sorted(
            {int(x) for x in re.findall(r"RaceNo=(\d+)", html) if 1 <= int(x) <= 14}
        )
        if len(race_nos) < 4:
            continue

        programme: list[dict[str, Any]] = []
        for no in race_nos:
            page = html if no == 1 else None
            if page is None:
                try:
                    page = fetch(racecard_url_for(d, no))
                except RuntimeError as e:
                    print(f"  WARN racecard {m['date']} race {no}: {e}")
                    continue
            detail = parse_race_card_detail(page, no)
            if detail:
                programme.append(detail)

        if not programme:
            continue

        programme.sort(key=lambda r: r["no"])
        m["race_programme"] = programme
        m["number_of_races"] = len(race_nos)
        m["number_of_races_label"] = str(len(race_nos))
        m["races_source"] = "RACE_CARD"
        m["first_race_time"] = programme[0]["time"]
        m["first_race_time_label"] = m["first_race_time"]
        m["time_source"] = "OFFICIAL"
        m["race_card_published"] = True
        print(
            f"  official race card {m['date']}: first {m['first_race_time']} "
            f"({len(programme)}/{len(race_nos)} races detailed)"
        )

        fixture_count = m.get("fixture_race_count")
        if fixture_count and fixture_count != len(race_nos):
            print(
                f"  NOTE {m['date']}: fixture programme={fixture_count} races, "
                f"race card={len(race_nos)} races (using race card)"
            )


def event_title(m: dict[str, Any]) -> str:
    special = m.get("special_event") or ""
    if m["date"] == "2026-11-01":
        return "🏇 Happy Valley — Day Race Meeting"
    if m["date"] == "2027-02-11":
        return "🏇 Happy Valley — Special Thursday Race Meeting"
    if m["date"] == "2027-07-14" or "Finale" in special:
        return "🏇 Happy Valley Season Finale"
    if "LONGINES" in special.upper() or "IJC" in special.upper():
        return "🏇 Happy Valley — LONGINES International Jockeys' Championship"
    if m["date"] == "2026-09-09":
        return "🏇 Happy Valley Season Opening"
    if m["session"] == "Day":
        return "🏇 Happy Valley Day Race Meeting"
    return "🏇 Happy Valley Race Meeting"


def event_times(m: dict[str, Any]) -> tuple[datetime, datetime, str]:
    d = date.fromisoformat(m["date"])
    if m.get("race_card_published") and m.get("first_race_time"):
        hh, mm = map(int, m["first_race_time"].split(":"))
        start = datetime(d.year, d.month, d.day, hh, mm, tzinfo=TZ)
        # Approximate meeting window after first race (~4h night / ~5h day)
        end = start + timedelta(hours=4 if m["session"] == "Night" else 5)
        return start, end, "OFFICIAL"

    if m["session"] == "Day":
        sh, sm = DAY_START
        eh, em = DAY_END
    else:
        sh, sm = NIGHT_START
        eh, em = NIGHT_END
    start = datetime(d.year, d.month, d.day, sh, sm, tzinfo=TZ)
    end = datetime(d.year, d.month, d.day, eh, em, tzinfo=TZ)
    return start, end, "PROVISIONAL"


def event_status(m: dict[str, Any]) -> str:
    if m.get("force_tentative"):
        return "TENTATIVE"
    if m.get("race_card_published"):
        return "CONFIRMED"
    return "TENTATIVE"


def build_description(m: dict[str, Any], detail: str = "standard") -> str:
    """Compact event description for ICS / preview.

    detail:
      - standard (published): session, status, times/programme, one URL, disclaimer
      - full (audit): adds GPS, time source, all official URLs, primary sources
    """
    start, end, src = event_times(m)
    session_blurb = (
        "Day race meeting at Happy Valley Racecourse."
        if m["session"] == "Day"
        else "Night race meeting at Happy Valley Racecourse."
    )
    special = (m.get("special_event") or "").strip()
    if is_internal_note(special):
        special = ""

    lines: list[str] = [session_blurb]
    if special:
        lines.append(special + ".")
    elif m["date"] == "2026-09-09":
        lines.append("Season opening of the HKJC 2026/27 season.")
    lines.append("")

    if src == "OFFICIAL" and m.get("first_race_time"):
        lines.append(f"First race: {m['first_race_time']} HKT")
    else:
        lines.append(
            "Time: not yet published by the HKJC — the "
            f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')} slot is a placeholder."
        )

    if m.get("race_card_published"):
        lines.append("Status: Confirmed — official race card published")
    else:
        lines.append("Status: Provisional — race card not yet published")
    lines.append("")

    programme = m.get("race_programme") or []
    race_count = m.get("number_of_races")
    if m.get("race_card_published") and programme:
        lines.append(f"Race card ({len(programme)} races):")
        for race in programme:
            lines.append(
                f"{race['no']}. {race['time']} - {race['distance_m']}m - {race['class']}"
            )
        lines.append("")
        lines.append("Full card:")
        lines.append(m.get("racecard_url") or m["official_info_url"])
    elif race_count and m.get("provisional_programme_summary"):
        lines.append(
            f"Provisional programme ({race_count} races): "
            f"{m['provisional_programme_summary']}"
        )
        lines.append("Subject to amendment by the HKJC.")
        lines.append("")
        lines.append("Race info:")
        lines.append(m["official_info_url"])
    elif race_count:
        lines.append(f"Races: {race_count} (provisional programme, subject to amendment)")
        lines.append("")
        lines.append("Race info:")
        lines.append(m["official_info_url"])
    else:
        lines.append("Race info:")
        lines.append(m["official_info_url"])

    lines.append("")
    lines.append(
        "Fixtures and race times may be amended or cancelled by the HKJC. "
        "Please check before attending."
    )

    if detail == "full":
        lines.extend(
            [
                "",
                f"GPS: {GEO_LAT}, {GEO_LON}",
                f"Time source: {src}",
                f"Races source: {m.get('races_source') or 'none'}",
                f"Track surface: {SURFACE} (Happy Valley is turf-only)",
                "",
                "Official URLs:",
                m["official_info_url"],
                m.get("fixture_page_url") or "",
                m.get("racecard_url") or "",
                "",
                "Primary sources:",
                FIXTURE_PDF,
                HKJC_FEED,
                RACING_NEWS_FIXTURES,
            ]
        )
        if m.get("notes") and is_internal_note(m["notes"]):
            lines.extend(["", f"Internal note: {m['notes']}"])

    # Drop accidental blank-only trailing empties while keeping intentional spacing.
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def fold_line(line: str) -> str:
    """Fold ICS content lines to ≤75 octets (UTF-8), with space-prefixed continuations."""

    def take_utf8_prefix(data: bytes, max_bytes: int) -> bytes:
        if len(data) <= max_bytes:
            return data
        cut = max_bytes
        # Walk back while we are inside a multibyte sequence or an incomplete starter
        while cut > 0:
            b = data[cut - 1]
            if (b & 0xC0) == 0x80:
                # continuation byte — keep walking back
                cut -= 1
                continue
            # b is an ASCII or starter byte at position cut-1
            # How many bytes does this character need?
            if b < 0x80:
                needed = 1
            elif (b & 0xE0) == 0xC0:
                needed = 2
            elif (b & 0xF0) == 0xE0:
                needed = 3
            elif (b & 0xF8) == 0xF0:
                needed = 4
            else:
                needed = 1
            available = max_bytes - (cut - 1)
            if available < needed:
                cut -= 1  # drop the incomplete character from this chunk
                continue
            break
        if cut <= 0:
            # Force at least one complete character
            b0 = data[0]
            if b0 < 0x80:
                cut = 1
            elif (b0 & 0xE0) == 0xC0:
                cut = 2
            elif (b0 & 0xF0) == 0xE0:
                cut = 3
            elif (b0 & 0xF8) == 0xF0:
                cut = 4
            else:
                cut = 1
        return data[:cut]

    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts: list[str] = []
    first = True
    while raw:
        limit = 75 if first else 74  # continuation has a leading space
        chunk = take_utf8_prefix(raw, limit)
        parts.append(chunk.decode("utf-8"))
        raw = raw[len(chunk) :]
        first = False
    return "\r\n ".join(parts)


def ics_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
    )


def stable_uid(meeting_date: str) -> str:
    return f"hv-{meeting_date}@happy-valley-racing-calendar"


def content_hash(m: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "date": m["date"],
            "session": m["session"],
            "title": event_title(m),
            "special": m.get("special_event"),
            "races": m.get("number_of_races"),
            "races_source": m.get("races_source"),
            "programme": m.get("race_programme") or [],
            "provisional_summary": m.get("provisional_programme_summary"),
            "first": m.get("first_race_time"),
            "status": event_status(m),
            "time_source": event_times(m)[2],
            "description_schema": DESCRIPTION_SCHEMA,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def load_previous_sequences() -> dict[str, dict[str, Any]]:
    path = ROOT / "data" / "sequences.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_sequences(seq: dict[str, dict[str, Any]]) -> None:
    path = ROOT / "data" / "sequences.json"
    path.write_text(json.dumps(seq, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def apple_structured_location_line() -> str:
    """Apple Calendar needs this proprietary field for tappable Maps locations."""
    address = ics_escape(ADDRESS)
    title = ics_escape(VENUE)
    return (
        "X-APPLE-STRUCTURED-LOCATION;VALUE=URI;"
        f"X-ADDRESS={address};"
        "X-APPLE-RADIUS=150;"
        f"X-TITLE={title}:"
        f"geo:{GEO_LAT},{GEO_LON}"
    )


def build_vevent(m: dict[str, Any], sequences: dict[str, dict[str, Any]], now: datetime) -> list[str]:
    start, end, time_source = event_times(m)
    uid = stable_uid(m["date"])
    h = content_hash(m)
    prev = sequences.get(uid, {"sequence": 0, "hash": ""})
    sequence = int(prev.get("sequence", 0))
    if prev.get("hash") and prev["hash"] != h:
        sequence += 1
    sequences[uid] = {"sequence": sequence, "hash": h, "date": m["date"]}

    status = event_status(m)
    desc = build_description(m, "standard")
    url = m["official_info_url"]
    # Title + newline + address matches X-TITLE / X-ADDRESS for Apple Maps linking.
    location_text = f"{VENUE}\n{ADDRESS}"

    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART;TZID={TZ_NAME}:{start.strftime('%Y%m%dT%H%M%S')}",
        f"DTEND;TZID={TZ_NAME}:{end.strftime('%Y%m%dT%H%M%S')}",
        f"SUMMARY:{ics_escape(event_title(m))}",
        f"LOCATION:{ics_escape(location_text)}",
        apple_structured_location_line(),
        f"DESCRIPTION:{ics_escape(desc)}",
        f"URL:{url}",
        f"GEO:{GEO_LAT};{GEO_LON}",
        f"STATUS:{status}",
        "TRANSP:OPAQUE",
        f"SEQUENCE:{sequence}",
        f"X-HKJC-TIME-SOURCE:{time_source}",
        f"X-HKJC-SESSION:{m['session']}",
        "BEGIN:VALARM",
        "TRIGGER:-P1D",
        "ACTION:DISPLAY",
        "DESCRIPTION:🏇 Happy Valley race meeting tomorrow",
        "END:VALARM",
        "END:VEVENT",
    ]
    return lines


def vtimezone_block() -> list[str]:
    # Hong Kong has no DST; fixed offset +08:00
    return [
        "BEGIN:VTIMEZONE",
        f"TZID:{TZ_NAME}",
        "X-LIC-LOCATION:Asia/Hong_Kong",
        "BEGIN:STANDARD",
        "TZOFFSETFROM:+0800",
        "TZOFFSETTO:+0800",
        "TZNAME:HKT",
        "DTSTART:19700101T000000",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]


def write_ics(meetings: list[dict[str, Any]]) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    sequences = load_previous_sequences()
    now = datetime.now(timezone.utc)
    out: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{CALNAME}",
        f"X-WR-TIMEZONE:{TZ_NAME}",
        "X-WR-CALDESC:Happy Valley Racecourse race meetings — HKJC 2026/27 (filtered & enriched from official HKJC sources)",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]
    out.extend(vtimezone_block())
    for m in meetings:
        out.extend(build_vevent(m, sequences, now))
    out.append("END:VCALENDAR")

    # Fold long lines and join with CRLF
    folded: list[str] = []
    for line in out:
        if (
            line.startswith("DESCRIPTION:")
            or line.startswith("SUMMARY:")
            or line.startswith("LOCATION:")
            or line.startswith("X-APPLE-STRUCTURED-LOCATION")
            or len(line.encode("utf-8")) > 75
        ):
            folded.append(fold_line(line))
        else:
            folded.append(line)
    text = "\r\n".join(folded) + "\r\n"
    ICS_PATH.write_bytes(text.encode("utf-8"))
    save_sequences(sequences)
    print(f"Wrote {ICS_PATH} ({len(meetings)} events)")


def write_csv(meetings: list[dict[str, Any]]) -> None:
    fields = [
        "Date",
        "Day",
        "Event Name",
        "Session Type",
        "Venue",
        "Address",
        "Surface",
        "Timezone",
        "First Race Time",
        "Number of Races",
        "Special Event",
        "Status",
        "Official Source URL",
        "Programme Summary",
    ]
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for m in meetings:
            start, _, src = event_times(m)
            first = (
                m["first_race_time_label"]
                if src == "OFFICIAL"
                else f"Provisional placeholder {start.strftime('%H:%M')} HKT — To be confirmed by HKJC"
            )
            w.writerow(
                {
                    "Date": m["date"],
                    "Day": m["day"],
                    "Event Name": event_title(m),
                    "Session Type": (
                        "Day Race Meeting" if m["session"] == "Day" else "Night Race Meeting"
                    ),
                    "Venue": VENUE,
                    "Address": ADDRESS,
                    "Surface": SURFACE,
                    "Timezone": TZ_NAME,
                    "First Race Time": first,
                    "Number of Races": m.get("number_of_races_label", "Not yet published"),
                    "Special Event": m.get("special_event") or "",
                    "Status": event_status(m),
                    "Official Source URL": m["official_info_url"],
                    "Programme Summary": (
                        "; ".join(
                            f"{r['no']}. {r['time']} {r['distance_m']}m {r['class']}"
                            for r in (m.get("race_programme") or [])
                        )
                        or m.get("provisional_programme_summary")
                        or ""
                    ),
                }
            )
    print(f"Wrote {CSV_PATH}")


def write_readme(meetings: list[dict[str, Any]], changes: list[str]) -> None:
    night = sum(1 for m in meetings if m["session"] == "Night")
    day = sum(1 for m in meetings if m["session"] == "Day")
    non_wed = [m for m in meetings if m["day"] != "Wednesday"]
    specials = [
        m
        for m in meetings
        if m.get("special_event") and not is_internal_note(m["special_event"])
    ]
    confirmed = sum(1 for m in meetings if event_status(m) == "CONFIRMED")
    first = meetings[0]["date"] if meetings else "n/a"
    last = meetings[-1]["date"] if meetings else "n/a"

    non_wed_lines = "\n".join(
        f"- {m['date']} ({m['day']}) — {event_title(m)}" for m in non_wed
    ) or "- None"
    special_lines = "\n".join(
        f"- {m['date']} — {m['special_event']}" for m in specials
    ) or "- None listed yet"
    change_block = (
        "\n".join(f"- {c}" for c in changes)
        if changes
        else "- None — official feed matches PDF baseline date-for-date."
    )

    subscribe_url = (
        "webcal://dario-apm-monaco.github.io/happy-valley-racing-calendar/happy-valley.ics"
    )
    https_url = (
        "https://dario-apm-monaco.github.io/happy-valley-racing-calendar/happy-valley.ics"
    )

    text = f"""# Happy Valley Racing Calendar — 2026/27

Auto-updating subscription calendar of **Happy Valley Racecourse** race meetings
for the Hong Kong Jockey Club racing season **2026/2027**.

## Subscribe (primary deliverable)

**Apple Calendar (recommended):**

1. Open **Calendar** on your Mac.
2. Menu **File → New Calendar Subscription…**
3. Paste:

   `{subscribe_url}`

4. Choose location **iCloud** (so it syncs to iPhone/iPad).
5. **Do not** enable “Remove alarms” — keep the 1-day-before reminder.
6. Set refresh to **Every hour** (or more frequent).

HTTPS fallback (same file):

`{https_url}`

> This is a **subscription**, not a one-time import. Events update when the
> published ICS is regenerated from the official HKJC feed.

## Files in this repository

| File | Purpose |
| ---- | ------- |
| `docs/happy-valley.ics` | Served via GitHub Pages as the subscription feed |
| `Happy_Valley_Racing_2026-27_Details.csv` | Structured audit table (UTF-8) |
| `Happy_Valley_Racing_2026-27_README.md` | This documentation |
| `data/baseline_26-27.json` | PDF-verified baseline of 39 dates |
| `build_happy_valley_calendar.py` | Regenerator (run by GitHub Action) |

## Summary

| Metric | Value |
| ------ | ----- |
| Happy Valley meetings | {len(meetings)} |
| Night meetings | {night} |
| Day meetings | {day} |
| First meeting | {first} |
| Last meeting | {last} |
| Race-card CONFIRMED | {confirmed} |
| Season-fixture TENTATIVE | {len(meetings) - confirmed} |

### Non-Wednesday meetings

{non_wed_lines}

### Special / named meetings

{special_lines}

### Feed vs PDF baseline

{change_block}

## Sources

1. Official fixture PDF: {FIXTURE_PDF}
2. Racing News announcement: {RACING_NEWS_FIXTURES}
3. Official HKJC subscription feed: {HKJC_FEED} (linked from {HKJC_RACING_CAL})
4. Monthly fixtures: https://racing.hkjc.com/en-us/local/information/fixture
5. Programme Amendment No. 1 (08 Sep 2026 — race distance change only, **no date change**): {AMENDMENT_NO1}

## Status & times

- `STATUS:CONFIRMED` — only when an official race card with first-race time is published.
- `STATUS:TENTATIVE` — date is on the official season fixture / live feed, but race-card details are not yet published.
- Race times: official when published; otherwise a **provisional placeholder** window
  (night 19:00–23:00 HKT, day 13:00–18:00 HKT), clearly labelled as such.
- Reminder: **1 day before** each meeting (`VALARM -P1D`).
- Event descriptions omit unknown fields (no “Not yet published” placeholders) and omit
  constant venue/address/timezone/turf lines already carried by other ICS fields.
  Happy Valley is turf-only; when an official race card is published the description
  lists each race (time, distance, class); otherwise a one-line provisional distance
  summary is shown when the monthly fixture programme is available.

## Important

> The Hong Kong Jockey Club may amend, reschedule or cancel race meetings.
> Always check the official HKJC fixture and race card before attending.

## Local rebuild

```bash
python3 build_happy_valley_calendar.py
```

Requires Python 3.10+ (stdlib only).
"""
    README_PATH.write_text(text, encoding="utf-8")
    print(f"Wrote {README_PATH}")


def write_preview_json(meetings: list[dict[str, Any]]) -> None:
    rows = []
    for m in meetings:
        start, end, src = event_times(m)
        rows.append(
            {
                "date": m["date"],
                "day": m["day"],
                "title": event_title(m),
                "session": m["session"],
                "status": event_status(m),
                "time_source": src,
                "start": start.strftime("%H:%M"),
                "end": end.strftime("%H:%M"),
                "first_race": m.get("first_race_time_label"),
                "races": m.get("number_of_races_label"),
                "races_source": m.get("races_source"),
                "special": m.get("special_event") or "",
                "provisional_programme": m.get("provisional_programme_summary") or "",
                "race_programme": m.get("race_programme") or [],
                "url": m["official_info_url"],
                "description_standard": build_description(m, "standard"),
                "description_full": build_description(m, "full"),
            }
        )
    PREVIEW_JSON.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {PREVIEW_JSON}")


def qa(meetings: list[dict[str, Any]]) -> None:
    errors: list[str] = []
    dates = [m["date"] for m in meetings]
    if len(dates) != len(set(dates)):
        errors.append("Duplicate dates found")
    for m in meetings:
        d = date.fromisoformat(m["date"])
        if d.strftime("%A") != m["day"]:
            errors.append(f"Weekday mismatch {m['date']}: {m['day']} vs {d.strftime('%A')}")
        if not (date(2026, 9, 6) <= d <= date(2027, 7, 14)):
            errors.append(f"Date outside season: {m['date']}")
        if m.get("special_event") and is_internal_note(m["special_event"]):
            errors.append(f"Internal note leaked into special_event: {m['date']}")
        if m.get("race_card_published") and not m.get("race_programme"):
            errors.append(f"CONFIRMED without race programme: {m['date']}")
        fixture_count = m.get("fixture_race_count")
        if (
            m.get("races_source") == "RACE_CARD"
            and fixture_count
            and fixture_count != m.get("number_of_races")
        ):
            # Amendment is allowed; log only — do not fail QA.
            print(
                f"QA note: {m['date']} fixture={fixture_count} vs "
                f"race card={m.get('number_of_races')}"
            )
        desc = build_description(m, "standard")
        if "Not yet published" in desc:
            errors.append(f"Description still contains 'Not yet published': {m['date']}")
        if "Track: Turf" in desc or "Track Surface:" in desc:
            errors.append(f"Description still contains turf track line: {m['date']}")
        if "Venue:" in desc or "Timezone:" in desc:
            errors.append(f"Description still contains redundant venue/timezone: {m['date']}")

    # Non-regression: 9 Sep provisional programme must sum sections to 8.
    sept = next((m for m in meetings if m["date"] == "2026-09-09"), None)
    if sept and sept.get("fixture_race_count") not in (None, 8):
        errors.append(
            f"9 Sep fixture race count expected 8, got {sept.get('fixture_race_count')}"
        )
    if sept and sept.get("race_card_published") and sept.get("number_of_races") != 8:
        errors.append(
            f"9 Sep race card race count expected 8, got {sept.get('number_of_races')}"
        )

    night = sum(1 for m in meetings if m["session"] == "Night")
    dayn = sum(1 for m in meetings if m["session"] == "Day")
    print(f"QA: {len(meetings)} meetings ({night} night, {dayn} day)")

    ics = ICS_PATH.read_bytes()
    if b"BEGIN:VCALENDAR" not in ics or b"END:VCALENDAR" not in ics:
        errors.append("ICS missing VCALENDAR markers")
    text = ics.decode("utf-8")
    vevents = text.count("BEGIN:VEVENT")
    if vevents != len(meetings):
        errors.append(f"ICS VEVENT count {vevents} != meetings {len(meetings)}")
    if "TRIGGER:-P1D" not in text:
        errors.append("Missing -P1D VALARM")
    if "TRIGGER:-P7D" in text:
        errors.append("Unexpected -P7D VALARM (should be removed)")
    if "X-APPLE-STRUCTURED-LOCATION" not in text:
        errors.append("Missing X-APPLE-STRUCTURED-LOCATION for Apple Maps")
    if text.count("X-APPLE-STRUCTURED-LOCATION") != len(meetings):
        errors.append("X-APPLE-STRUCTURED-LOCATION count mismatch")
    uids = re.findall(r"^UID:(.+)$", text, re.M)
    if len(uids) != len(set(uids)):
        errors.append("Duplicate UIDs in ICS")

    with CSV_PATH.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != len(meetings):
        errors.append(f"CSV rows {len(rows)} != meetings {len(meetings)}")
    for r in rows:
        if "Sha Tin" in r.get("Venue", "") or "Sha Tin" in r.get("Event Name", ""):
            errors.append(f"Sha Tin leaked into CSV: {r.get('Date')}")
        if r.get("Date") == "2026-11-18" and "Programme Amendment" in (r.get("Special Event") or ""):
            errors.append("Programme Amendment leaked into CSV Special Event for 2026-11-18")

    if errors:
        print("QA FAILED:")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print("QA PASSED")


def main() -> int:
    print("Loading baseline…")
    baseline = load_baseline()
    expected = baseline["official_summary"]["total_happy_valley"]

    print("Fetching official HKJC feed…")
    feed_events = fetch_official_hv_events()
    print(f"  feed HV events: {len(feed_events)}")
    if len(feed_events) == 0:
        print("FATAL: official feed returned 0 Happy Valley events — refusing to overwrite ICS")
        return 2

    meetings, changes = reconcile(baseline, feed_events)
    print(f"  merged meetings: {len(meetings)}")
    for c in changes:
        print(f"  CHANGE: {c}")

    if len(meetings) == 0:
        print("FATAL: zero meetings after reconcile — refusing to overwrite ICS")
        return 2

    print("Enriching race counts from monthly fixtures…")
    enrich_race_counts(meetings)
    print("Enriching first-race times from race cards (when published)…")
    enrich_first_race_times(meetings)

    write_ics(meetings)
    write_csv(meetings)
    write_readme(meetings, changes)
    write_preview_json(meetings)
    qa(meetings)

    if len(meetings) != expected:
        print(
            f"WARNING: count {len(meetings)} != baseline expected {expected}. "
            "ICS published with TENTATIVE flags on drifted dates; see README feed vs baseline."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
