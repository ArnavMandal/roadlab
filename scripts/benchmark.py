#!/usr/bin/env python3
"""Measure fake queue scheduling only; requires running Relay, idle queue, no workers."""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
from worker.client import request


def percentiles(values):
    values = sorted(values)

    def q(p):
        i = (len(values) - 1) * p
        lo = int(i)
        hi = min(lo + 1, len(values) - 1)
        return values[lo] * (hi - i) + values[hi] * (i - lo) if lo != hi else values[lo]

    return {k: q(v) for k, v in [("p50", 0.5), ("p95", 0.95), ("p99", 0.99)]}


def stamp(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--jobs", type=int, default=30)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--duration", type=float, default=0.1)
    a = p.parse_args()
    if not 1 <= a.jobs <= 200 or not 1 <= a.workers <= 16 or not 0 <= a.duration <= 300:
        raise ValueError("jobs 1..200, workers 1..16, duration 0..300")
    if any(j["state"] in ("queued", "running") for j in request("/jobs")):
        raise ValueError("queue must be idle")
    batch = uuid.uuid4().hex
    started = time.monotonic()
    jobs = [
        request(
            "/jobs",
            {"task": "fake", "duration": a.duration, "max_attempts": 1},
            f"bench-{batch}-{i}",
        )
        for i in range(a.jobs)
    ]
    workers = []
    try:
        workers = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "worker.run",
                    "--name",
                    f"bench-{batch[:6]}-{i}",
                ],
                stdout=subprocess.DEVNULL,
            )
            for i in range(a.workers)
        ]
        deadline = time.monotonic() + max(120, a.jobs * (a.duration + 2) / a.workers)
        while True:
            done = [request("/jobs/" + j["id"]) for j in jobs]
            if all(j["state"] in ("succeeded", "failed") for j in done):
                break
            if time.monotonic() > deadline:
                raise TimeoutError("benchmark timed out")
            time.sleep(0.1)
        elapsed = time.monotonic() - started
        if any(j["state"] != "succeeded" for j in done):
            raise RuntimeError("benchmark job failed")
        attempts = [request("/jobs/" + j["id"] + "/attempts")[0] for j in done]
        waits = [
            stamp(a["started_at"]) - stamp(j["created_at"])
            for j, a in zip(done, attempts)
        ]
        latencies = [
            stamp(a["finished_at"]) - stamp(j["created_at"])
            for j, a in zip(done, attempts)
        ]
        report = {
            "machine": platform.platform(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
            "python": platform.python_version(),
            "workers": a.workers,
            "jobs": a.jobs,
            "workload": "fake sleep, no injected failures, one attempt",
            "duration_seconds": a.duration,
            "worker_poll_seconds": 0.4,
            "elapsed_seconds_including_submission_startup_and_polling": elapsed,
            "throughput_jobs_per_second": a.jobs / elapsed,
            "queue_wait_seconds": percentiles(waits),
            "end_to_end_seconds": percentiles(latencies),
            "job_ids": [j["id"] for j in done],
            "limitations": "Single machine, burst submission, process startup included; no multi-host scalability claim.",
        }
        target = ROOT / "storage" / "benchmarks" / (batch + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        print("Saved:", target)
    finally:
        for w in workers:
            w.terminate()
        for w in workers:
            try:
                w.wait(10)
            except subprocess.TimeoutExpired:
                w.kill()
                w.wait()


if __name__ == "__main__":
    main()
