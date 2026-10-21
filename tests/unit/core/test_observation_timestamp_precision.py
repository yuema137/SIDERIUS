"""Timestamp precision and legacy normalization under isolated host timezones."""

import json
import os
import subprocess
import sys
import time

import pytest


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="requires host timezone selection")
@pytest.mark.parametrize("zone", ["UTC", "America/Los_Angeles", "Asia/Shanghai"])
def test_fractional_offsets_leaps_and_dst_are_consistent(zone):
    script = """
import json,time
from datetime import datetime
from core.runtime_control.observation_store import _timestamp_seconds

time.tzset()
base=datetime.strptime("2026-07-23T12:00:00+0000", "%Y-%m-%dT%H:%M:%S%z").timestamp()
cases = {
    "2026-07-23T12:00:00+00:00:00.500000": base-0.5,
    "2026-07-23T12:00:00-00:00:00.500000": base+0.5,
    "2026-07-23T12:00:00+05:30:12.125": base-19812.125,
    "2026-07-23T12:00:00-05:30:12.125": base+19812.125,
    "2026-07-23T12:00:60+00:00:00.5": base+59.5,
    "2026-07-23T12:00:61-00:00:00.5": base+61.5,
    "2026-7-23T12:0:0+0000": base,
}
for timestamp, expected in cases.items():
    assert _timestamp_seconds(timestamp) == expected, timestamp
# The repeated autumn hour is ordered by its explicit offsets, not its clock text.
first = _timestamp_seconds("2026-11-01T01:30:00-0700")
second = _timestamp_seconds("2026-11-01T01:30:00-0800")
assert second-first == 3600
for timestamp in ("2026-07-23T12:00:60", "2026-11-01T01:30:00", "2026-03-08T02:30:00"):
    assert _timestamp_seconds(timestamp) == time.mktime(time.strptime(timestamp, "%Y-%m-%dT%H:%M:%S"))
for timestamp in ("2026-07-23T12:00:00+25:00", "2026-07-23T12:00:00+00:00:00.1234567", "not-a-time"):
    assert _timestamp_seconds(timestamp) is None
print(json.dumps({"passed": True}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "TZ": zone},
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    assert json.loads(result.stdout) == {"passed": True}
