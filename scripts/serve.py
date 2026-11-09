#!/usr/bin/env python3
"""Start native local processes; terminate only this supervisor's process groups."""

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--production", action="store_true")
    a = p.parse_args()
    logs = ROOT / "storage" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    processes = []
    handles = []

    def launch(name, args, cwd=ROOT):
        f = (logs / (name + ".log")).open("a")
        handles.append(f)
        child = subprocess.Popen(
            args, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, start_new_session=True
        )
        processes.append(child)
        return child

    def stop(*_):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, stop)
    try:
        relay = launch("relay", [str(ROOT / "bin" / "relay")])
        ready = False
        for _ in range(40):
            if relay.poll() is not None:
                raise RuntimeError("Relay stopped; inspect storage/logs/relay.log")
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:8080/health", timeout=1
                ) as response:
                    ready = response.status == 200
            except OSError:
                pass
            if ready:
                break
            time.sleep(0.25)
        if not ready:
            raise RuntimeError(
                "Relay did not become healthy; check PostgreSQL and DATABASE_URL"
            )
        for name in ("local-a", "local-b"):
            launch(name, [sys.executable, "-m", "worker.run", "--name", name])
        args = [
            "node",
            "node_modules/next/dist/bin/next",
            "start" if a.production else "dev",
            "--hostname",
            "127.0.0.1",
        ]
        if not a.production:
            args.append("--webpack")
        launch("web", args, ROOT / "web")
        print(
            "RoadLab: http://127.0.0.1:3000 · Ctrl-C stops the application (PostgreSQL stays running).",
            flush=True,
        )
        while True:
            time.sleep(1)
            if any(child.poll() is not None for child in processes):
                raise RuntimeError("A process stopped; inspect storage/logs/")
    except KeyboardInterrupt:
        pass
    finally:
        for child in reversed(processes):
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(8)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
        for f in handles:
            f.close()


if __name__ == "__main__":
    main()
