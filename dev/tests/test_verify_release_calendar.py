# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pytest
import time_machine

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "verify_release_calendar.py"


@pytest.fixture(scope="module")
def calendar_mod():
    spec = importlib.util.spec_from_file_location("verify_release_calendar", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RESTRUCTURED_WIKI_HTML = """
<html><body>
<h1>Support for Airflow in Providers</h1>
<p>Compatibility notes, not a release schedule.</p>
<h1>Airflow 3 Core</h1>
<table>
  <tr>
    <th>Version</th><th>Planned Cut Date</th><th>Planned Release Date</th>
    <th>Release Manager</th><th>Scope / Notes</th>
  </tr>
  <tr>
    <td>3.2.2</td><td>15 May 2026</td><td>22 May 2026</td>
    <td>Rahul Vats</td><td>Probably last release of 3.2-line</td>
  </tr>
</table>
<h1>Provider Releases</h1>
<table>
  <tr>
    <th>Planned Cut Date: Every second Tuesday</th>
    <th>Release Manager</th>
    <th>Scope / Notes</th>
  </tr>
  <tr><td>18 Aug 2026</td><td>Hussein Awala</td><td></td></tr>
  <tr><td>08 Aug 2026</td><td>06 Aug 2026</td><td>Follow-up wave</td></tr>
  <tr><td>01 Sep 2026</td><td></td><td>Airflow summit - No release!</td></tr>
  <tr><td>25 Aug 2026</td><td>Niko Oliveira</td><td>Ad-hoc wave only if needed</td></tr>
</table>
<h1>Airflow Ctl</h1>
<table>
  <tr>
    <th>Release/Cut Date</th><th>Release manager</th><th>Version</th><th>Scope / Notes</th>
  </tr>
  <tr><td>Week of 22 Jun 2026</td><td>Buğra Öztürk</td><td>1.0.0?</td><td>Planned</td></tr>
  <tr><td>18 May 2026</td><td>Buğra Öztürk</td><td>0.1.5</td><td></td></tr>
</table>
</body></html>
"""


def test_parse_confluence_uses_provider_releases_not_support_heading(calendar_mod):
    releases = calendar_mod.parse_confluence_releases(RESTRUCTURED_WIKI_HTML)
    keys = {
        (item.release_type, item.version, item.date.strftime("%Y-%m-%d"), item.release_manager)
        for item in releases
    }

    assert ("Providers", "3.2.2", "2026-05-22", "Rahul") not in keys
    assert ("Providers", "2026.08.18", "2026-08-18", "Hussein") in keys
    assert ("Providers", "2026.08.25", "2026-08-25", "Niko") in keys
    assert ("Airflow Ctl", "0.1.5", "2026-05-18", "Buğra") in keys


def test_parse_confluence_skips_non_release_rows(calendar_mod):
    releases = calendar_mod.parse_confluence_releases(RESTRUCTURED_WIKI_HTML)
    dates = {item.date.strftime("%Y-%m-%d") for item in releases}

    assert "2026-08-08" not in dates
    assert "2026-09-01" not in dates
    assert all(item.version != "1.0.0?" for item in releases)


@pytest.mark.parametrize(
    ("header", "section_name", "expected"),
    [
        ("Provider Releases", "Provider Releases", True),
        ("Support for Airflow in Providers", "Providers", False),
        ("Support for Airflow in Providers", "provider release", False),
        ("Airflow Ctl", "airflow ctl", True),
    ],
)
def test_heading_matches_section(calendar_mod, header, section_name, expected):
    assert calendar_mod.heading_matches_section(header, section_name) is expected


def test_find_column_indices_prefers_cut_date(calendar_mod):
    version_idx, date_idx, manager_idx = calendar_mod.find_column_indices(
        ["version", "planned cut date", "planned release date", "release manager"]
    )
    assert (version_idx, date_idx, manager_idx) == (0, 1, 3)


def test_matching_entry_still_requires_date_type_and_manager(calendar_mod):
    release = calendar_mod.Release(
        release_type="Providers",
        version="2026.08.18",
        date=datetime(2026, 8, 18),
        release_manager="Hussein",
    )
    matching = calendar_mod.CalendarEntry(
        summary="Providers release - Hussein Awala", start_date=datetime(2026, 8, 18)
    )
    other_manager = calendar_mod.CalendarEntry(
        summary="Providers release - Jarek", start_date=datetime(2026, 8, 18)
    )
    other_day = calendar_mod.CalendarEntry(
        summary="Providers release - Hussein Awala", start_date=datetime(2026, 8, 19)
    )

    assert calendar_mod.is_matching_entry(release, matching)
    assert not calendar_mod.is_matching_entry(release, other_manager)
    assert not calendar_mod.is_matching_entry(release, other_day)


RECURRING_ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART;VALUE=DATE:20260811
RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=TU;UNTIL=20260908
UID:providers-series@example.com
SUMMARY:Providers release - ?
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20260818
RECURRENCE-ID;VALUE=DATE:20260811
UID:providers-series@example.com
SUMMARY:Providers release - Hussein Awala
END:VEVENT
END:VCALENDAR
"""


def test_parse_calendar_data_expands_rrule_and_keeps_overrides(calendar_mod):
    entries = calendar_mod.parse_calendar_data(RECURRING_ICS)
    by_date = {item.start_date.strftime("%Y-%m-%d"): item.summary for item in entries}

    assert "2026-08-11" not in by_date
    assert by_date["2026-08-18"] == "Providers release - Hussein Awala"
    assert by_date["2026-08-25"] == "Providers release - ?"


@time_machine.travel("2026-08-20", tick=False)
def test_select_releases_to_verify_skips_past_rows(calendar_mod):
    past = calendar_mod.Release("Providers", "2026.08.18", datetime(2026, 8, 18), "Hussein")
    today = calendar_mod.Release("Providers", "2026.08.20", datetime(2026, 8, 20), "Jarek")
    future = calendar_mod.Release("Providers", "2026.08.25", datetime(2026, 8, 25), "Niko")

    upcoming = calendar_mod.select_releases_to_verify([past, today, future], include_past=False)
    assert [item.date.strftime("%Y-%m-%d") for item in upcoming] == ["2026-08-20", "2026-08-25"]

    all_rows = calendar_mod.select_releases_to_verify([past, today, future], include_past=True)
    assert len(all_rows) == 3
