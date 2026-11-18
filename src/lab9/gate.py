"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []

    def row_key(row: dict) -> tuple[str, int]:
        return str(row.get("item_id")), row.get("seed")

    # Reports must be complete, unique, finite, and comparable to the baseline.
    for label, report in (("pr", pr), ("baseline", base)):
        manifest = report.get("manifest") or {}
        rows = report.get("rows")
        if not isinstance(rows, list):
            problems.append(f"{label} rows missing")
            continue
        seeds = manifest.get("seeds") or []
        items = manifest.get("items")
        if not isinstance(items, int) or items < 0 or not isinstance(seeds, list):
            problems.append(f"{label} manifest items/seeds invalid")
        elif len(rows) != items * len(seeds):
            problems.append(f"{label} row count {len(rows)} != {items} items x {len(seeds)} seeds")
        keys = [row_key(r) for r in rows]
        if len(keys) != len(set(keys)):
            problems.append(f"{label} has duplicate (item_id, seed) rows")
        if report.get("evaluator_failures"):
            problems.append(f"{label} has evaluator failures")
        for metric, value in (report.get("metrics") or {}).items():
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                if not math.isfinite(float(value)):
                    problems.append(f"{label} metric {metric} is not finite")
            elif value is None and any(m["id"] == metric for m in spec.get("metrics", [])):
                problems.append(f"{label} metric {metric} is missing")

    pr_rows = pr.get("rows") or []
    base_rows = base.get("rows") or []
    pr_keys = {row_key(r) for r in pr_rows}
    base_keys = {row_key(r) for r in base_rows}
    if pr_keys != base_keys:
        problems.append("PR (item_id, seed) set differs from baseline")

    # A grader crash must not disappear from an average as None or as a missing field.
    row_metric_ids = {
        m["id"] for m in spec.get("metrics", [])
        if any(m["id"] in r for r in base_rows + pr_rows)
    }
    for i, row in enumerate(pr_rows):
        for metric in row_metric_ids:
            if metric not in row or row.get(metric) is None:
                problems.append(f"PR row {i} has missing grader value {metric}")

    # Slice membership is part of the eval-set contract, not something a PR may relabel.
    if pr_keys == base_keys:
        pr_slices = {row_key(r): frozenset(r.get("slices") or []) for r in pr_rows}
        base_slices = {row_key(r): frozenset(r.get("slices") or []) for r in base_rows}
        changed = [key for key in sorted(pr_keys) if pr_slices[key] != base_slices[key]]
        if changed:
            problems.append(f"slice tags differ from baseline for {len(changed)} row(s)")

    # Recompute row-derived metrics so hand-edited summaries cannot make a red report green.
    if pr_rows:
        grouped: dict[str, list[bool]] = {}
        for row in pr_rows:
            grouped.setdefault(str(row.get("item_id")), []).append(bool(row.get("pass_rate")))
        for metric in spec.get("metrics", []):
            mid, expected = metric["id"], None
            values = [row.get(mid) for row in pr_rows] if all(mid in row for row in pr_rows) else []
            if values and all(v is not None for v in values):
                if metric.get("kind") == "safety":
                    expected = sum(bool(v) for v in values)
                elif metric.get("kind") == "capability":
                    expected = round(sum(bool(v) for v in values) / len(values), 4)
            elif mid == "pass_5" and grouped:
                expected = round(sum(all(v) for v in grouped.values()) / len(grouped), 4)
            elif mid.startswith("pass_at_") or mid.startswith("pass_hat_"):
                k = int(mid.rsplit("_", 1)[1])
                fn = stats.pass_at_k if mid.startswith("pass_at_") else stats.pass_hat_k
                if grouped and min(map(len, grouped.values())) >= k:
                    expected = round(sum(fn(len(v), sum(v), k) for v in grouped.values()) / len(grouped), 4)
            elif mid == "cost_per_success" and all("cost" in row for row in pr_rows):
                passes = sum(bool(row.get("pass_rate")) for row in pr_rows)
                expected = round(sum(float(row["cost"]) for row in pr_rows) / passes, 4) if passes else None
            reported = (pr.get("metrics") or {}).get(mid)
            if expected is not None and (not isinstance(reported, (int, float)) or
                                         not math.isclose(float(reported), float(expected), abs_tol=1e-9)):
                problems.append(f"metric {mid} does not match rows")

    # Ratchet: on the same eval-set version, every old protection must remain at least as strict.
    if base_spec is not None and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        def threshold_problems(current: dict, old: dict, label: str) -> None:
            for key in ("min", "max", "max_increase"):
                if key not in old:
                    continue
                if key not in current:
                    problems.append(f"ratchet {label} dropped {key}")
                elif key == "min" and current[key] < old[key]:
                    problems.append(f"ratchet {label} lowered min")
                elif key in {"max", "max_increase"} and current[key] > old[key]:
                    problems.append(f"ratchet {label} raised {key}")
            if old.get("no_significant_drop") and not current.get("no_significant_drop"):
                problems.append(f"ratchet {label} dropped no_significant_drop")

        current_metrics = {m["id"]: m for m in spec.get("metrics", [])}
        for old in base_spec.get("metrics", []):
            mid = old["id"]
            current = current_metrics.get(mid)
            if current is None:
                problems.append(f"ratchet dropped metric {mid}")
                continue
            if old.get("blocking") and not current.get("blocking"):
                problems.append(f"ratchet metric {mid} became non-blocking")
            if current.get("kind") != old.get("kind"):
                problems.append(f"ratchet metric {mid} changed kind")
            threshold_problems(current.get("threshold") or {}, old.get("threshold") or {}, f"metric {mid}")

        current_slices = {s["name"]: s for s in spec.get("slices", [])}
        for old in base_spec.get("slices", []):
            name = old["name"]
            current = current_slices.get(name)
            if current is None:
                problems.append(f"ratchet dropped slice {name}")
                continue
            if old.get("blocking") and not current.get("blocking"):
                problems.append(f"ratchet slice {name} became non-blocking")
            if current.get("metric") != old.get("metric"):
                problems.append(f"ratchet slice {name} changed metric")
            threshold_problems(current, old, f"slice {name}")

    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for slice_spec in spec.get("slices", []):
        name, metric = slice_spec["name"], slice_spec["metric"]
        identifier = f"slice:{name}/{metric}"
        pr_values = per_item(pr, metric, slice_name=name)
        base_values = per_item(base, metric, slice_name=name)
        keys = sorted(set(pr_values) & set(base_values))
        verdict, notes = "ok", []
        if not pr_values or set(pr_values) != set(base_values):
            verdict = "fail"
            value = None
            notes.append("missing or mismatched slice items")
        else:
            value = sum(pr_values.values()) / len(pr_values)
            if "min" in slice_spec and value < slice_spec["min"]:
                verdict = "fail"
                notes.append(f"below min {slice_spec['min']}")
            if slice_spec.get("no_significant_drop"):
                d, lo, hi = stats.paired_bootstrap(
                    [pr_values[k] for k in keys], [base_values[k] for k in keys],
                    n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                    confidence=bs.get("confidence", 0.95),
                )
                notes.append(f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]")
                if hi < 0:
                    verdict = "fail"
        if verdict == "fail" and slice_spec.get("blocking"):
            blocked.append(identifier)
        label = "BLOCK" if verdict == "fail" and slice_spec.get("blocking") else ("warn" if verdict == "fail" else "ok")
        lines.append(f"  {identifier:<32} {value!s:<8} {'; '.join(notes):<48} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                                               confidence=bs.get("confidence", 0.95))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
