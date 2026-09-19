"""Observed usage across successful, failed and interrupted attempts (not a billing cap)."""
from __future__ import annotations

import json
from pathlib import Path


def summarize_usage(root: Path) -> dict:
    report = {"benchmark": {"charged_tokens": 0, "estimated_usd": None, "unpriced_calls": 0},
              "optimizer": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                            "calls_without_usage": 0}}
    priced = []
    for path in (root / "evaluations").glob("*/*/attempt-*/*_ledger.jsonl"):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            report["benchmark"]["charged_tokens"] += int(entry.get("charged_tokens", 0) or 0)
            if entry.get("cost_usd") is not None:
                priced.append(float(entry["cost_usd"]))
            elif entry.get("status") in {"ok", "fail_closed"}:
                report["benchmark"]["unpriced_calls"] += 1
    if priced:
        report["benchmark"]["estimated_usd"] = sum(priced)
    for path in (root / "optimizer").glob("*/generation-*/call-*.json"):
        entry = json.loads(path.read_text())
        usage = entry.get("usage")
        if usage:
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                report["optimizer"][key] += int(usage.get(key, 0) or 0)
        else:
            report["optimizer"]["calls_without_usage"] += 1
    report["note"] = ("Observed usage only. Missing usage after a crash or transport error is unknown, not free. "
                      "Benchmark USD excludes optimizer and EC2 charges. Set provider-side spending limits separately.")
    return report
