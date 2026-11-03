#!/usr/bin/env python3
"""qbit-traffic-guard: keeps a box under its monthly outbound quota (run every few minutes).

Reads this month's TX of the interface from vnstat. Below soft_tb the qBittorrent upload is
unlimited; between soft_tb and hard_tb it is limited so the rest of the quota is spread evenly
over the rest of the month; from hard_tb on it is capped to a trickle. Other outbound traffic
(e.g. rsync to the seedbox) also counts as TX but is not throttled."""
from __future__ import annotations

import calendar
import datetime
import json
import subprocess
import sys
import tomllib

from qbit_space_gate import DEFAULT_CONFIG, Qbit, load_config

TB = 1000 ** 4


def tx_this_month(interface: str) -> int:
    d = json.loads(subprocess.check_output(["vnstat", "--json", "m", "1", "-i", interface]))
    months = d["interfaces"][0]["traffic"]["month"]
    return months[-1]["tx"] if months else 0


def upload_limit(tx: int, now: datetime.datetime, soft_tb: float, hard_tb: float, trickle: int) -> int:
    """Bytes/s for qBittorrent's global upload limit (0 = unlimited)."""
    if tx < soft_tb * TB:
        return 0
    if tx >= hard_tb * TB:
        return trickle
    days = calendar.monthrange(now.year, now.month)[1]
    month_end = datetime.datetime(now.year, now.month, days, 23, 59, 59)
    secs_left = max(3600.0, (month_end - now).total_seconds())
    return max(trickle, int((hard_tb * TB - tx) / secs_left))


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CONFIG
    cfg = load_config(path)
    with open(path, "rb") as fh:
        g = tomllib.load(fh).get("guard", {})
    tx = tx_this_month(g.get("interface", "eth0"))
    tx += int(float(g.get("tx_offset_tb", 0)) * TB)   # traffic before vnstat started counting
    now = datetime.datetime.now()
    limit = upload_limit(tx, now, float(g.get("soft_tb", 24)), float(g.get("hard_tb", 29)),
                         int(g.get("trickle_kib", 64)) * 1024)
    q = Qbit(cfg)
    if int(q.call("transfer/uploadLimit")) != limit:
        q.call("transfer/setUploadLimit", {"limit": limit})
    shown = "unlimited" if not limit else f"{limit / 1e6:.2f} MB/s"
    print(f"{now:%F %T} tx={tx / TB:.2f} TB  upload limit {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
