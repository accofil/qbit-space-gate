#!/usr/bin/env python3
"""qbit-traffic-guard: keeps a box under its monthly outbound quota (run every few minutes).

Reads this month's TX of the interface from vnstat. Below soft_tb the qBittorrent upload is
unlimited; between soft_tb and hard_tb it is limited so the rest of the quota is spread evenly
over the rest of the month; from hard_tb on it is capped to a trickle. Other outbound traffic
(e.g. rsync to the seedbox) also counts as TX but is not throttled.

Optional [handover]: when hard_tb is reached, run switch_away_cmd (e.g. tell autobrr on the
seedbox to send new torrents to its own qBittorrent), stop every torrent here and create the
relay's evacuate flag so it hands everything over at once; in the next month switch_back_cmd
runs and the flag is removed."""
from __future__ import annotations

import calendar
import datetime
import json
import os
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


def run_hook(cmd: str) -> bool:
    if not cmd:
        return True
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    print(f"hook `{cmd}` exit {r.returncode}: {(r.stdout + r.stderr).strip()[-500:]}")
    return r.returncode == 0


def handover(q: Qbit, h: dict, state: dict, month: str, tx: int, hard_tb: float) -> None:
    """At hard_tb: send new torrents elsewhere, stop everything here, let the relay evacuate.
    In the next month: undo it. Each step is retried on the next run until it succeeded."""
    flag = os.path.expanduser(h.get("evacuate_flag", ""))
    if tx >= hard_tb * TB and state.get("evacuated") != month:
        if not state.get("switched_away") == month:
            if run_hook(h.get("switch_away_cmd", "")):
                state["switched_away"] = month
        q.call("torrents/stop", {"hashes": "all"})
        if flag:
            open(flag, "w").close()
        if state.get("switched_away") == month:
            state["evacuated"] = month
        print(f"HANDOVER: quota reached ({tx / TB:.2f} TB) - torrents stopped, relay evacuating")
    elif state.get("evacuated") and state["evacuated"] != month:
        if run_hook(h.get("switch_back_cmd", "")):
            if flag and os.path.exists(flag):
                os.remove(flag)
            state.clear()
            print("HANDOVER undone: new month, new torrents come here again")


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CONFIG
    cfg = load_config(path)
    with open(path, "rb") as fh:
        conf = tomllib.load(fh)
    g, h = conf.get("guard", {}), conf.get("handover", {})
    tx = tx_this_month(g.get("interface", "eth0"))
    tx += int(float(g.get("tx_offset_tb", 0)) * TB)   # traffic before vnstat started counting
    now = datetime.datetime.now()
    hard_tb = float(g.get("hard_tb", 29))
    limit = upload_limit(tx, now, float(g.get("soft_tb", 24)), hard_tb, int(g.get("trickle_kib", 64)) * 1024)
    q = Qbit(cfg)
    if int(q.call("transfer/uploadLimit")) != limit:
        q.call("transfer/setUploadLimit", {"limit": limit})
    shown = "unlimited" if not limit else f"{limit / 1e6:.2f} MB/s"
    print(f"{now:%F %T} tx={tx / TB:.2f} TB  upload limit {shown}")
    if h.get("enabled"):
        state_path = os.path.join(cfg["state_dir"], "qbit-traffic-guard.json")
        try:
            with open(state_path) as fh:
                state = json.load(fh)
        except FileNotFoundError:
            state = {}
        handover(q, h, state, f"{now:%Y-%m}", tx, hard_tb)
        with open(state_path, "w") as fh:
            json.dump(state, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
