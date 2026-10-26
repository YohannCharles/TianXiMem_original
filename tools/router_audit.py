"""Route the selected official Search events with the configured router model.

This is a measurement-only tool. It calls the query router and records one JSONL
row per Search event. It never calls Add, Search, answer generation, or judging.

```bash
uv run --env-file deploy/.env python tools/router_audit.py \
  --out eval/reports/runs/router-audit-qwen-20261026
```

The command is resumable: rows already present in ``routes.jsonl`` are skipped.
``progress.json`` is rewritten atomically after each completed event and is safe
to poll while the audit is running.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEFAULT_OUT = ROOT / "eval" / "reports" / "runs" / "router-audit-qwen-20261026"
DEFAULT_SELECTION = (
    ROOT / "eval" / "reports" / "runs" / "official-v1.2-answer-v2" / "selection-manifest.json"
)
DEFAULT_SEARCHES = ROOT / "official-dataset-2026-09-29" / "official-searches.jsonl"


@dataclass(frozen=True, slots=True)
class QueryItem:
    seq: int
    dataset: str
    user_id: str
    query: str


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_items(selection: Path, searches: Path) -> list[QueryItem]:
    """Load selected Search events in their original selected order."""
    manifest = json.loads(selection.read_text(encoding="utf-8"))
    selected = manifest.get("questions")
    if not isinstance(selected, list):
        raise SystemExit(f"✗ {selection} 缺少 questions 列表")

    by_seq: dict[int, dict[str, Any]] = {}
    with searches.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            seq = row.get("seq")
            if isinstance(seq, int):
                if seq in by_seq:
                    raise SystemExit(f"✗ official-searches.jsonl 有重复 seq: {seq}")
                by_seq[seq] = row

    items: list[QueryItem] = []
    seen: set[int] = set()
    for selected_row in selected:
        seq = selected_row.get("seq")
        if not isinstance(seq, int):
            raise SystemExit(f"✗ selection 行缺少整数 seq: {selected_row!r}")
        if seq in seen:
            raise SystemExit(f"✗ selection 有重复 seq: {seq}")
        seen.add(seq)
        source = by_seq.get(seq)
        if source is None:
            raise SystemExit(f"✗ selection seq={seq} 在 official-searches.jsonl 中找不到")
        query = source.get("query")
        if not isinstance(query, str) or not query.strip():
            raise SystemExit(f"✗ seq={seq} 的 query 为空或不是字符串")
        items.append(
            QueryItem(
                seq=seq,
                dataset=str(selected_row.get("dataset") or source.get("dataset") or ""),
                user_id=str(selected_row.get("user_id") or source.get("user_id") or ""),
                query=query,
            )
        )
    return items


def _read_done(path: Path) -> dict[int, dict[str, Any]]:
    done: dict[int, dict[str, Any]] = {}
    if not path.exists():
        return done
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"✗ {path}:{number} JSONL 损坏：{exc}") from exc
            seq = row.get("seq")
            if not isinstance(seq, int):
                raise SystemExit(f"✗ {path}:{number} 缺整数 seq")
            done[seq] = row
    return done


def _counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    routes = Counter(str(row.get("parsed_route")) for row in rows)
    statuses = Counter(str(row.get("route_status")) for row in rows)
    datasets: dict[str, dict[str, int]] = {}
    for row in rows:
        dataset = str(row.get("dataset") or "")
        bucket = datasets.setdefault(dataset, {})
        route = str(row.get("parsed_route"))
        bucket[route] = bucket.get(route, 0) + 1
    latencies = [
        row["latency_ms"] for row in rows if isinstance(row.get("latency_ms"), int | float)
    ]
    input_tokens = [row["input_tokens"] for row in rows if isinstance(row.get("input_tokens"), int)]
    output_tokens = [
        row["output_tokens"] for row in rows if isinstance(row.get("output_tokens"), int)
    ]
    return {
        "routes": dict(sorted(routes.items())),
        "statuses": dict(sorted(statuses.items())),
        "datasets": dict(sorted(datasets.items())),
        "metrics": {
            "latency_ms_mean": round(sum(latencies) / len(latencies), 3) if latencies else None,
            "input_tokens_sum": sum(input_tokens) if input_tokens else None,
            "output_tokens_sum": sum(output_tokens) if output_tokens else None,
            "usage_rows": len(input_tokens),
        },
    }


def _progress(
    *,
    rows: list[dict[str, Any]],
    total: int,
    started_at: str,
    started_monotonic: float,
    errors: int,
    running: int,
    output: Path,
    model: str,
) -> dict[str, Any]:
    completed = len(rows)
    elapsed = time.monotonic() - started_monotonic
    rate = completed / elapsed if elapsed > 0 else 0.0
    remaining = max(0, total - completed)
    eta_seconds = remaining / rate if rate > 0 else None
    return {
        "state": "running" if completed < total else "completed",
        "model": model,
        "started_at": started_at,
        "updated_at": _now(),
        "total": total,
        "completed": completed,
        "remaining": remaining,
        "running": running,
        "errors": errors,
        "percent": round(completed * 100.0 / total, 3) if total else 100.0,
        "elapsed_seconds": round(elapsed, 3),
        "events_per_second": round(rate, 4),
        "eta_seconds": round(eta_seconds, 1) if eta_seconds is not None else None,
        "routes": _counts(rows),
        "routes_file": str(output / "routes.jsonl"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "Router audit").splitlines()[0])
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--searches", type=Path, default=DEFAULT_SEARCHES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    if args.workers < 1:
        raise SystemExit("✗ --workers 必须 ≥ 1")

    items = load_items(args.selection, args.searches)
    if args.limit is not None:
        if args.limit < 1:
            raise SystemExit("✗ --limit 必须 ≥ 1")
        items = items[: args.limit]

    args.out.mkdir(parents=True, exist_ok=True)
    routes_path = args.out / "routes.jsonl"
    progress_path = args.out / "progress.json"
    done = _read_done(routes_path)
    pending = [item for item in items if item.seq not in done]
    if not done:
        routes_path.touch()

    from tools.router_eval import build_runner

    runners = [build_runner() for _ in range(args.workers)]
    runner_pool: queue.Queue[Any] = queue.Queue()
    for runner in runners:
        runner_pool.put(runner)
    model = runners[0].model
    started_at = _now()
    started_monotonic = time.monotonic()
    errors = 0
    rows = list(done.values())
    write_lock = threading.Lock()
    in_flight = 0
    _atomic_json(
        progress_path,
        _progress(
            rows=rows,
            total=len(items),
            started_at=started_at,
            started_monotonic=started_monotonic,
            errors=errors,
            running=0,
            output=args.out,
            model=model,
        ),
    )
    print(
        f"router audit: model={model} total={len(items)} "
        f"already_done={len(done)} pending={len(pending)} workers={args.workers}",
        flush=True,
    )

    def run_one(item: QueryItem) -> dict[str, Any]:
        nonlocal errors, in_flight
        runner = runner_pool.get()
        with write_lock:
            in_flight += 1
        try:
            result = runner.route(item.query)
            row = {
                "seq": item.seq,
                "dataset": item.dataset,
                "user_id": item.user_id,
                "query": item.query,
                **result,
                "recorded_at": _now(),
            }
        except Exception as exc:  # noqa: BLE001 - keep the audit alive and record the failure
            row = {
                "seq": item.seq,
                "dataset": item.dataset,
                "user_id": item.user_id,
                "query": item.query,
                "model_output": None,
                "parsed_route": "ERROR",
                "route_status": "audit_error",
                "route_reason": f"{type(exc).__name__}: {exc}",
                "latency_ms": None,
                "input_tokens": None,
                "output_tokens": None,
                "recorded_at": _now(),
            }
        finally:
            runner_pool.put(runner)
        with write_lock:
            in_flight -= 1
            if row["parsed_route"] == "ERROR":
                errors += 1
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            rows.append(row)
            completed = len(rows)
            _atomic_json(
                progress_path,
                _progress(
                    rows=rows,
                    total=len(items),
                    started_at=started_at,
                    started_monotonic=started_monotonic,
                    errors=errors,
                    running=in_flight,
                    output=args.out,
                    model=model,
                ),
            )
            if completed % 50 == 0 or completed == len(items):
                print(
                    f"[{completed}/{len(items)}] routes={_counts(rows)['routes']} errors={errors}",
                    flush=True,
                )
        return row

    with (
        routes_path.open("a", encoding="utf-8") as handle,
        ThreadPoolExecutor(max_workers=args.workers) as pool,
    ):
        futures = [pool.submit(run_one, item) for item in pending]
        for future in as_completed(futures):
            future.result()

    # Recompute from final rows in case an existing run was resumed.
    final_rows = list(_read_done(routes_path).values())
    final_errors = sum(row.get("parsed_route") == "ERROR" for row in final_rows)
    _atomic_json(
        progress_path,
        _progress(
            rows=final_rows,
            total=len(items),
            started_at=started_at,
            started_monotonic=started_monotonic,
            errors=final_errors,
            running=0,
            output=args.out,
            model=model,
        ),
    )
    for runner in runners:
        close = getattr(runner.client, "close", None)
        if callable(close):
            close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
