import datetime
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qbit_space_gate as g  # noqa: E402
from qbit_traffic_guard import TB, upload_limit  # noqa: E402

GB = g.GB
CFG = {"categories": ["aither"], "limit_gb": 180, "min_free_gb": 10, "safe_progress": 0.05}


class FakeQbit:
    def __init__(self):
        self.torrents, self.calls = [], []

    def add(self, h, size_gb, progress=0.0, state="stoppedDL"):
        self.torrents.append({"hash": h, "name": h, "category": "aither", "size": size_gb * GB,
                              "amount_left": size_gb * GB * (1 - progress), "progress": progress,
                              "state": state, "added_on": len(self.torrents)})

    def call(self, path, data=None):
        if path.startswith("torrents/info"):
            return json.dumps(self.torrents)
        action = path.split("/")[1]
        self.calls.append((action, data["hashes"]))
        if action == "delete":
            self.torrents = [t for t in self.torrents if t["hash"] != data["hashes"]]
        if action == "start":
            for t in self.torrents:
                if t["hash"] == data["hashes"]:
                    t["state"] = "downloading"
        return "Ok."


class GateTest(unittest.TestCase):
    def gate(self, free_gb=190):
        q = FakeQbit()
        gate = g.Gate(CFG, q)
        gate.free_bytes = lambda: free_gb * GB
        return q, gate

    def test_fits_start_else_delete(self):
        q, gate = self.gate()
        q.add("A", 100); q.add("B", 70); q.add("C", 30)
        gate.step()
        self.assertEqual(q.calls, [("start", "A"), ("start", "B"), ("delete", "C")])

    def test_freed_budget_lets_next_new_one_in(self):
        q, gate = self.gate()
        q.add("A", 100); q.add("B", 70)
        gate.step()
        q.torrents = [t for t in q.torrents if t["hash"] != "A"]   # relay removed A
        q.add("D", 100)
        gate.step()
        self.assertIn(("start", "D"), q.calls)

    def test_running_over_budget_kept_above_safe_progress(self):
        q, gate = self.gate()
        q.add("A", 170); q.add("E", 30, 0.10, "downloading"); q.add("F", 30, 0.01, "downloading")
        gate.step()
        self.assertEqual(gate.st, {"A": "started", "E": "started"})
        self.assertIn(("delete", "F"), q.calls)

    def test_disk_floor(self):
        q, gate = self.gate(free_gb=50)
        q.add("A", 45)
        gate.step()
        self.assertEqual(q.calls, [("delete", "A")])

    def test_decides_only_once(self):
        q, gate = self.gate()
        q.add("A", 10)
        gate.step()
        gate.step()
        self.assertEqual(q.calls, [("start", "A")])


class GuardTest(unittest.TestCase):
    def test_limits(self):
        now = datetime.datetime(2026, 11, 16, 0, 0, 0)
        self.assertEqual(upload_limit(int(10 * TB), now, 24, 29, 65536), 0)
        self.assertEqual(upload_limit(int(29.5 * TB), now, 24, 29, 65536), 65536)
        mid = upload_limit(int(26 * TB), now, 24, 29, 65536)
        self.assertTrue(65536 < mid < 3 * TB / (14 * 86400))


if __name__ == "__main__":
    unittest.main()
