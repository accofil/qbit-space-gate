#!/usr/bin/env python3
"""qbit-space-gate: decides once, right away, about every new torrent of the watched categories.

autobrr adds torrents STOPPED, so nothing is downloaded before the decision:
  * fits    -> started. "Fits" means the full size of every torrent already let in
               (still present in qBittorrent) plus its own stays within limit_gb, and the
               disk keeps at least min_free_gb after all running downloads finish.
  * no room -> deleted with its data at once (it never started, so it is at 0%).
A torrent that is already running when first seen (e.g. added by hand) and does not
fit is only deleted below safe_progress, so it can never reach a hit-and-run threshold;
above that it is kept and logged."""
from __future__ import annotations

import http.cookiejar
import json
import logging
import os
import shutil
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request

GB = 1024 ** 3
DEFAULT_CONFIG = "/etc/qbit-space-gate/config.toml"
log = logging.getLogger("qbit-space-gate")


def load_config(path: str) -> dict:
    with open(path, "rb") as fh:
        c = tomllib.load(fh)
    q, g = c["qbittorrent"], c.get("gate", {})
    return {
        "url": q["url"].rstrip("/") + "/api/v2/", "referer": q["url"],
        "username": q["username"], "password": q["password"],
        "categories": g.get("categories", ["aither"]),
        "limit_gb": float(g.get("limit_gb", 180)),
        "min_free_gb": float(g.get("min_free_gb", 10)),
        "safe_progress": float(g.get("safe_progress", 0.05)),
        "poll_seconds": float(g.get("poll_seconds", 0.5)),
        "disk": os.path.expanduser(g.get("disk", "~/torrents")),
        "state_dir": os.path.expanduser(g.get("state_dir", "~/.local/state")),
    }


class Qbit:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.login()

    def login(self) -> None:
        self._call("auth/login", {"username": self.cfg["username"], "password": self.cfg["password"]})

    def _call(self, path: str, data: dict | None = None) -> str:
        req = urllib.request.Request(self.cfg["url"] + path,
                                     data=urllib.parse.urlencode(data).encode() if data else None,
                                     headers={"Referer": self.cfg["referer"]})
        return self.op.open(req, timeout=30).read().decode()

    def call(self, path: str, data: dict | None = None) -> str:
        try:
            return self._call(path, data)
        except urllib.error.HTTPError as e:
            if e.code != 403:
                raise
            self.login()
            return self._call(path, data)


class Gate:
    def __init__(self, cfg: dict, qbit, state_path: str | None = None):
        self.cfg, self.q = cfg, qbit
        self.state_path = state_path
        self.st: dict[str, str] = {}
        if state_path:
            try:
                with open(state_path) as fh:
                    self.st = json.load(fh)
            except FileNotFoundError:
                pass

    def save(self) -> None:
        if not self.state_path:
            return
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(self.st, fh, indent=1)
        os.replace(tmp, self.state_path)

    def free_bytes(self) -> int:
        return shutil.disk_usage(self.cfg["disk"]).free

    def step(self) -> None:
        cfg, q, st = self.cfg, self.q, self.st
        torrents = [t for c in cfg["categories"]
                    for t in json.loads(q.call("torrents/info?category=" + urllib.parse.quote(c)))]
        present = {t["hash"] for t in torrents}
        changed = False
        for h in list(st):
            if h not in present:
                del st[h]
                changed = True
        used = sum(t["size"] for t in torrents if st.get(t["hash"]) == "started")
        pending = sum(t["amount_left"] for t in torrents if st.get(t["hash"]) == "started")
        free = self.free_bytes()

        def fits(t: dict) -> bool:
            return (used + t["size"] <= cfg["limit_gb"] * GB
                    and free - pending - t["size"] >= cfg["min_free_gb"] * GB)

        for t in sorted(torrents, key=lambda t: t["added_on"]):
            h, name = t["hash"], t["name"]
            if h in st or t["size"] <= 0 or t["state"] in ("checkingResumeData", "metaDL", "forcedMetaDL"):
                continue
            if fits(t):
                if t["state"].startswith(("stopped", "paused")):
                    q.call("torrents/start", {"hashes": h})
                st[h] = "started"
                used += t["size"]
                pending += t["amount_left"]
                log.info("START  %.1f GB (budget %.0f/%.0f GB)  %s", t["size"] / GB, used / GB, cfg["limit_gb"], name)
            elif t["progress"] < cfg["safe_progress"]:
                q.call("torrents/delete", {"hashes": h, "deleteFiles": "true"})
                log.info("DROP   %.1f GB at %.1f%% (budget %.0f/%.0f GB full) - deleted with data  %s",
                         t["size"] / GB, t["progress"] * 100, used / GB, cfg["limit_gb"], name)
            else:
                st[h] = "started"
                used += t["size"]
                log.warning("OVER   %.1f GB already at %.1f%% - kept running (hit-and-run safety)  %s",
                            t["size"] / GB, t["progress"] * 100, name)
            changed = True
        if changed:
            self.save()


def main() -> int:
    cfg = load_config(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CONFIG)
    os.makedirs(cfg["state_dir"], exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        handlers=[logging.FileHandler(os.path.join(cfg["state_dir"], "qbit-space-gate.log")),
                                  logging.StreamHandler()])
    state = os.path.join(cfg["state_dir"], "qbit-space-gate.json")
    gate = None
    while True:
        try:
            if gate is None:
                gate = Gate(cfg, Qbit(cfg), state)
            gate.step()
        except Exception as e:  # keep running across qBittorrent restarts
            log.warning("step failed: %r", e)
            gate = None
            time.sleep(30)
        time.sleep(cfg["poll_seconds"])


if __name__ == "__main__":
    sys.exit(main())
