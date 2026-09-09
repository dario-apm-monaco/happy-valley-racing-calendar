# Happy Valley Racing Calendar — 2026/27

Auto-updating subscription calendar of **Happy Valley Racecourse** race meetings
for the Hong Kong Jockey Club racing season **2026/2027**.

## Subscribe (primary deliverable)

**Apple Calendar (recommended):**

1. Open **Calendar** on your Mac.
2. Menu **File → New Calendar Subscription…**
3. Paste:

   `webcal://dario-apm-monaco.github.io/happy-valley-racing-calendar/happy-valley.ics`

4. Choose location **iCloud** (so it syncs to iPhone/iPad).
5. **Do not** enable “Remove alarms” — keep the 1-day-before reminder.
6. Set refresh to **Every hour** (or more frequent).

HTTPS fallback (same file):

`https://dario-apm-monaco.github.io/happy-valley-racing-calendar/happy-valley.ics`

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
| Happy Valley meetings | 39 |
| Night meetings | 38 |
| Day meetings | 1 |
| First meeting | 2026-09-09 |
| Last meeting | 2027-07-14 |
| Race-card CONFIRMED | 1 |
| Season-fixture TENTATIVE | 38 |

### Non-Wednesday meetings

- 2026-11-01 (Sunday) — 🏇 Happy Valley — Day Race Meeting
- 2027-02-11 (Thursday) — 🏇 Happy Valley — Special Thursday Race Meeting

### Special / named meetings

- 2026-11-01 — Only Happy Valley day meeting of the season
- 2026-11-18 — Programme Amendment No.1: Class 5 distance change (not a date change)
- 2026-12-09 — LONGINES IJC
- 2027-02-11 — Special Thursday meeting after Chinese New Year
- 2027-06-09 — Tuen Ng Festival public holiday
- 2027-07-14 — Happy Valley Finale Race Night

### Feed vs PDF baseline

- None — official feed matches PDF baseline date-for-date.

## Sources

1. Official fixture PDF: https://res.hkjc.com/racingnews/wp-content/uploads/sites/3/2026/07/fixture_26-27.pdf
2. Racing News announcement: https://racingnews.hkjc.com/english/2026/07/20/racing-fixtures-2026-2027-season/
3. Official HKJC subscription feed: https://calendar.google.com/calendar/ical/gturu5cp1tfpdgmlio8tinhlis%40group.calendar.google.com/public/basic.ics (linked from https://www.hkjc.com/english/racinginfo/racing-calendar.asp)
4. Monthly fixtures: https://racing.hkjc.com/en-us/local/information/fixture
5. Programme Amendment No. 1 (08 Sep 2026 — race distance change only, **no date change**): https://racingnews.hkjc.com/english/2026/09/08/2026-2027-season-programme-amendment-no-1/

## Status & times

- `STATUS:CONFIRMED` — only when an official race card with first-race time is published.
- `STATUS:TENTATIVE` — date is on the official season fixture / live feed, but race-card details are not yet published.
- Race times: official when published; otherwise a **provisional placeholder** window
  (night 19:00–23:00 HKT, day 13:00–18:00 HKT), clearly labelled as such.
- Reminder: **1 day before** each meeting (`VALARM -P1D`).

## Important

> The Hong Kong Jockey Club may amend, reschedule or cancel race meetings.
> Always check the official HKJC fixture and race card before attending.

## Local rebuild

```bash
python3 build_happy_valley_calendar.py
```

Requires Python 3.10+ (stdlib only).
