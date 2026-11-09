import argparse
import json
import os
from pathlib import Path
import threading
import time
import urllib.error
from .client import request, HTTPError


class LostLease(Exception):
    pass


def log(event, job, **fields):
    print(
        json.dumps(
            {
                "event": event,
                "job_id": job["id"],
                "attempt": job["attempt"],
                "token": job["token"],
                **fields,
            }
        ),
        flush=True,
    )


def execute(job, device):
    from .data import ROOT, sha, write_json

    stop = threading.Event()
    lost = threading.Event()
    progress = [0.0]
    base = "/jobs/" + job["id"]
    token = job["token"]

    def heartbeat():
        while not stop.wait(1):
            try:
                request(base + "/heartbeat", {"token": token, "progress": progress[0]})
            except HTTPError as e:
                if e.code in (404, 409):
                    lost.set()
                    return
                log("heartbeat_error", job, error=str(e))
            except (OSError, urllib.error.URLError) as e:
                log("heartbeat_error", job, error=str(e))

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()

    def update(value):
        if lost.is_set():
            raise LostLease()
        progress[0] = value

    try:
        out = (
            Path(os.environ.get("ARTIFACT_ROOT", str(ROOT / "artifacts"))).resolve()
            / job["id"]
            / token
        )
        out.mkdir(parents=True, exist_ok=False)
        spec = job["spec"]
        log("started", job, label=spec["label"])
        if spec["task"] == "fake":
            duration = spec["duration"]
            start = time.monotonic()
            while time.monotonic() - start < duration:
                update(min(0.99, (time.monotonic() - start) / max(duration, 0.001)))
                time.sleep(0.05)
            if spec.get("invalid"):
                raise ValueError("injected invalid input")
            if job["attempt"] <= spec.get("fail_until", 0):
                raise OSError("injected retryable failure")
            write_json(
                out / "result.json",
                {
                    "kind": "fake",
                    "label": "fake queue workload",
                    "job_id": job["id"],
                    "attempt": job["attempt"],
                    "duration": duration,
                },
            )
        elif spec["task"] == "evaluate":
            from .evaluate import evaluate

            evaluate(spec, out, progress=update, device_name=device)
        else:
            raise ValueError("unknown task")
        update(1)
        # Result bytes never change once published. Retry a lost completion response
        # with exactly the same token and digest; server returns the original success.
        body = {"token": token, "sha256": sha(out / "result.json")}
        for retry in range(5):
            try:
                request(base + "/complete", body)
                log("accepted", job)
                return
            except HTTPError as e:
                if e.code in (404, 409):
                    raise LostLease() from e
                if e.code < 500:
                    raise ValueError(str(e)) from e
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(min(2**retry, 4))
        log("completion_uncertain", job)
    except LostLease:
        log("lease_lost", job)
    except Exception as e:
        retryable = not isinstance(e, (ValueError, KeyError, FileNotFoundError))
        log("failed", job, error=str(e), retryable=retryable)
        try:
            request(
                base + "/fail",
                {"token": token, "error": str(e)[:4096], "retryable": retryable},
            )
        except Exception as update_error:
            log("failure_report_rejected", job, error=str(update_error))
    finally:
        stop.set()
        thread.join(timeout=9)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--name", default="worker-" + str(os.getpid()))
    p.add_argument("--once", action="store_true")
    p.add_argument("--device", default="cpu")
    a = p.parse_args()
    while True:
        try:
            job = request("/claim", {"worker": a.name})
            if job:
                execute(job, a.device)
            if a.once:
                return
        except (HTTPError, OSError, urllib.error.URLError) as e:
            print(json.dumps({"event": "claim_error", "error": str(e)}), flush=True)
        time.sleep(0.4)


if __name__ == "__main__":
    main()
