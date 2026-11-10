#!/usr/bin/env python3
"""Real process-crash/restart demonstration. Requires PostgreSQL and bin/relay."""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RELAY_URL", "http://127.0.0.1:8081")
from worker.client import request, HTTPError


def wait_for(fn, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = fn()
            if result:
                return result
        except (HTTPError, OSError):
            pass
        time.sleep(0.2)
    raise TimeoutError("condition not reached")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--no-web", action="store_true")
    p.add_argument(
        "--dataset", help="registered dataset for a real evaluation crash demo"
    )
    p.add_argument("--model", help="registered model, required with --dataset")
    p.add_argument("--comparison-model", help="optional baseline evaluated on the same dataset")
    a = p.parse_args()
    if a.comparison_model and not a.dataset:
        p.error("--comparison-model requires --dataset and --model")
    if bool(a.dataset) != bool(a.model):
        p.error("--dataset and --model must be supplied together")
    logdir = ROOT / "storage" / "demo-logs" / uuid.uuid4().hex[:12]
    logdir.mkdir(parents=True)
    processes = []
    handles = []
    env = {**os.environ, "RELAY_ADDR": "127.0.0.1:8081", "LEASE_SECONDS": "4"}

    def launch(name, args, cwd=ROOT):
        f = (logdir / (name + ".log")).open("w")
        handles.append(f)
        process = subprocess.Popen(
            args,
            cwd=cwd,
            env=env,
            stdout=f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        processes.append(process)
        return process

    def stop(process):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()

    try:
        api = launch("relay-1", [str(ROOT / "bin" / "relay")])
        wait_for(lambda: request("/health"), 15)
        if any(j["state"] in ("queued", "running") for j in request("/jobs")):
            raise RuntimeError("Use an idle database; stop other workers first.")
        if not a.no_web:
            launch(
                "web",
                [
                    "node",
                    "node_modules/next/dist/bin/next",
                    "dev",
                    "--webpack",
                    "--hostname",
                    "127.0.0.1",
                ],
                cwd=ROOT / "web",
            )
        key = "demo-" + uuid.uuid4().hex
        payload = {"task": "fake", "duration": 7, "max_attempts": 3}
        if a.dataset:
            payload = {
                "task": "evaluate",
                "dataset": a.dataset,
                "model": a.model,
                "max_attempts": 3,
            }
        first = request("/jobs", payload, key)
        one = launch(
            "worker-a", [sys.executable, "-m", "worker.run", "--name", "demo-a"]
        )
        wait_for(lambda: request("/jobs/" + first["id"])["state"] == "running")
        second = request("/jobs", payload, key + "-second")
        two = launch(
            "worker-b", [sys.executable, "-m", "worker.run", "--name", "demo-b"]
        )
        wait_for(lambda: request("/jobs/" + second["id"])["state"] == "running")
        old_claim = request("/jobs/" + first["id"])
        if a.dataset:
            attempt_dir = (
                Path(os.environ.get("ARTIFACT_ROOT", "storage/artifacts"))
                / first["id"]
                / old_claim["token"]
            )
            wait_for(lambda: any(attempt_dir.glob("*_original.png")), 90)
            if request("/jobs/" + first["id"])["state"] != "running":
                raise RuntimeError(
                    "evaluation finished before fault injection; no crash proof collected"
                )
        print("Killing worker A while its job is running:", first["id"], flush=True)
        os.killpg(one.pid, signal.SIGKILL)
        one.wait()
        wait_for(
            lambda: all(
                request("/jobs/" + j["id"])["state"] == "succeeded"
                for j in [first, second]
            )
        )
        results = []
        for j in [first, second]:
            final = request("/jobs/" + j["id"])
            attempts = request("/jobs/" + j["id"] + "/attempts")
            assert sum(x["state"] == "succeeded" for x in attempts) == 1
            assert final["state"] == "succeeded"
            results.append(
                {
                    "job": final,
                    "attempts": attempts,
                    "result": request("/jobs/" + j["id"] + "/result"),
                }
            )
        assert any(x["state"] == "expired" for x in results[0]["attempts"])
        assert results[0]["job"]["attempt"] == 2
        # Simulate a late publisher from the dead generation; Go must fence it.
        from worker.data import write_json, sha

        stale_dir = (
            Path(os.environ.get("ARTIFACT_ROOT", "storage/artifacts"))
            / first["id"]
            / old_claim["token"]
        )
        write_json(
            stale_dir / "result.json",
            {"kind": "stale-completion-probe", "accepted": False},
        )
        try:
            request(
                "/jobs/" + first["id"] + "/complete",
                {"token": old_claim["token"], "sha256": sha(stale_dir / "result.json")},
            )
            raise AssertionError("stale completion was accepted")
        except HTTPError as error:
            assert error.code == 409
        duplicate = request("/jobs", payload, key)
        assert duplicate["id"] == first["id"]
        # Persisted jobs must survive an actual API process restart.
        stop(api)
        api = launch("relay-2", [str(ROOT / "bin" / "relay")])
        wait_for(lambda: request("/health"), 15)
        after = request("/jobs/" + first["id"])
        assert after["state"] == "succeeded"
        assert after["result_sha256"] == results[0]["job"]["result_sha256"]
        # Repeat completion to model the first success response getting lost.
        repeat = request(
            "/jobs/" + first["id"] + "/complete",
            {"token": after["token"], "sha256": after["result_sha256"]},
        )
        assert repeat["state"] == "succeeded"
        comparison = None
        if a.comparison_model:
            baseline = request("/jobs", {**payload, "model": a.comparison_model}, key + "-baseline")
            wait_for(lambda: request("/jobs/" + baseline["id"])["state"] in ("succeeded", "failed"))
            baseline = request("/jobs/" + baseline["id"])
            assert baseline["state"] == "succeeded", baseline
            comparison = {"job": baseline, "result": request("/jobs/" + baseline["id"] + "/result")}
            assert comparison["result"]["dataset_sha256"] == results[0]["result"]["dataset_sha256"]
            assert comparison["result"]["metric_config"] == results[0]["result"]["metric_config"]
        report = {
            "description": "real SIGKILL recovery; two workers; API process restart; duplicate submit; repeated completion",
            "duplicate_id": duplicate["id"],
            "workload": payload,
            "stale_completion_status": 409,
            "jobs": results,
            "comparison": comparison,
        }
        (logdir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(
            "PASS: reclaimed dead worker job; one accepted attempt per job; duplicate and repeat completion stable; API restart preserved jobs."
        )
        print("Evidence:", logdir / "report.json")
    finally:
        for process in reversed(processes):
            stop(process)
        for f in handles:
            f.close()


if __name__ == "__main__":
    main()
