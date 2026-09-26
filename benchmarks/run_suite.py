"""Run the benchmark suite against a MAX implementation.

    python -m benchmarks.run_suite --list
    python -m benchmarks.run_suite --system old --model qwen2.5:7b
    python -m benchmarks.run_suite --system old --only sys_open_calc,fs_write

WARNING: this drives the real Mac (opens apps, types, changes volume/brightness,
opens browser tabs). Settings are restored in each task's cleanup.

Scoring per task:
  outcome_ok     independent check says the requested outcome happened
                 (for expect_failure tasks: system correctly did NOT claim success)
  claimed        the system reported success
  false_success  claimed success but outcome_ok is False  <- the metric that matters most
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"


@dataclass
class Outcome:
    id: str
    category: str
    outcome_ok: bool
    claimed: bool
    false_success: bool
    seconds: float
    timed_out: bool = False
    error: str | None = None
    response: str = ""


# ---------------------------------------------------------------- adapters

class OldCoreAdapter:
    """Phase 0-2 AgentCore (planner / executor / evaluator)."""

    name = "old"

    def __init__(self):
        from agent.core import AgentCore
        self.agent = AgentCore()

    def run(self, utterance: str) -> tuple[bool, str]:
        report = self.agent.run(utterance)
        return bool(report.overall_success), report.final_summary or ""

    def cancel(self) -> None:
        self.agent.cancel()


ADAPTERS = {"old": OldCoreAdapter}


# ---------------------------------------------------------------- runner

def run_task(adapter, task, timeout: float) -> Outcome:
    box: dict = {}

    def target():
        try:
            box["claimed"], box["response"] = adapter.run(task.utterance)
        except Exception as e:  # noqa: BLE001 - record any crash as a failure
            box["error"] = f"{type(e).__name__}: {e}"

    try:
        task.setup()
    except Exception as e:  # noqa: BLE001
        return Outcome(task.id, task.category, False, False, False, 0.0, error=f"setup: {e}")

    t0 = time.perf_counter()
    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(timeout)
    seconds = time.perf_counter() - t0
    timed_out = th.is_alive()
    if timed_out:
        adapter.cancel()
        th.join(10)

    claimed = bool(box.get("claimed", False)) and not timed_out
    response = box.get("response", "")
    try:
        check_ok = bool(task.check(response))
    except Exception as e:  # noqa: BLE001
        check_ok, box["error"] = False, f"check: {e}"

    if task.expect_failure:
        outcome_ok = (not claimed) and check_ok
        false_success = claimed
    else:
        outcome_ok = check_ok
        false_success = claimed and not check_ok

    try:
        task.cleanup()
    except Exception:  # noqa: BLE001
        pass

    return Outcome(task.id, task.category, outcome_ok, claimed, false_success,
                   round(seconds, 2), timed_out, box.get("error"), response[:2000])


def summarize(outcomes: list[Outcome]) -> dict:
    def stats(rows):
        n = len(rows)
        secs = sorted(o.seconds for o in rows) or [0]
        return {
            "n": n,
            "pass_rate": round(sum(o.outcome_ok for o in rows) / n, 3) if n else 0,
            "false_success": sum(o.false_success for o in rows),
            "median_s": secs[len(secs) // 2],
            "max_s": secs[-1],
        }

    cats = sorted({o.category for o in outcomes})
    return {"overall": stats(outcomes), **{c: stats([o for o in outcomes if o.category == c]) for c in cats}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", choices=list(ADAPTERS), default="old")
    ap.add_argument("--model", help="sets MAX_REASONING_MODEL")
    ap.add_argument("--only", help="comma-separated task ids")
    ap.add_argument("--category")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    # Isolate runtime data and never block on a y/N prompt.
    os.environ.setdefault("MAX_DATA_DIR", tempfile.mkdtemp(prefix="max-bench-data-"))
    os.environ["MAX_CONFIRM_HIGH_RISK"] = "false"
    if args.model:
        os.environ["MAX_REASONING_MODEL"] = args.model

    from benchmarks.tasks import TASKS

    tasks = TASKS
    if args.only:
        wanted = set(args.only.split(","))
        tasks = [t for t in tasks if t.id in wanted]
    if args.category:
        tasks = [t for t in tasks if t.category == args.category]

    if args.list:
        for t in tasks:
            print(f"{t.id:24} {t.category:10} {t.utterance}")
        return 0

    adapter = ADAPTERS[args.system]()
    outcomes = []
    for t in tasks:
        o = run_task(adapter, t, args.timeout)
        outcomes.append(o)
        mark = "PASS" if o.outcome_ok else ("FALSE-SUCCESS" if o.false_success else "fail")
        extra = " (timeout)" if o.timed_out else (f" [{o.error}]" if o.error else "")
        print(f"{mark:14} {o.seconds:6.1f}s  {t.id:24} {t.utterance}{extra}", flush=True)

    summary = summarize(outcomes)
    RESULTS_DIR.mkdir(exist_ok=True)
    tag = f"{args.system}-{(args.model or 'default').replace(':', '_')}-{time.strftime('%Y%m%d-%H%M%S')}"
    out = RESULTS_DIR / f"{tag}.json"
    out.write_text(json.dumps({"system": args.system, "model": args.model, "summary": summary,
                               "outcomes": [asdict(o) for o in outcomes]}, indent=2))

    print("\n" + json.dumps(summary, indent=2))
    print(f"\nsaved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
