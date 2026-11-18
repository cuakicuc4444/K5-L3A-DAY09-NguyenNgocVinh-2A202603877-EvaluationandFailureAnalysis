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
    metrics = pr.get("metrics")
    if not isinstance(metrics, dict):
        problems.append("pr.metrics is missing or not an object")
    else:
        for name, value in metrics.items():
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                problems.append(f"metric {name} is not numeric")
            elif isinstance(value, float) and not math.isfinite(value):
                problems.append(f"metric {name} is not finite")

    manifest = pr.get("manifest")
    expected_rows = None
    if not isinstance(manifest, dict):
        problems.append("pr.manifest is missing or not an object")
    else:
        items = manifest.get("items")
        seeds = manifest.get("seeds")
        if not isinstance(items, int) or isinstance(items, bool) or items < 1:
            problems.append("pr.manifest.items must be a positive integer")
        if not isinstance(seeds, list) or not seeds or any(
            not isinstance(seed, int) or isinstance(seed, bool) for seed in seeds
        ):
            problems.append("pr.manifest.seeds must be a non-empty list of integers")
        elif len(set(seeds)) != len(seeds):
            problems.append("pr.manifest.seeds contains duplicates")
        if (isinstance(items, int) and not isinstance(items, bool) and items > 0
                and isinstance(seeds, list) and seeds
                and all(isinstance(seed, int) and not isinstance(seed, bool) for seed in seeds)):
            expected_rows = items * len(seeds)

    evaluator_failures = pr.get("evaluator_failures")
    if not isinstance(evaluator_failures, list):
        problems.append("pr.evaluator_failures is missing or not a list")
    elif evaluator_failures:
        problems.append(f"pr.evaluator_failures is non-empty ({len(evaluator_failures)})")

    pr_rows = pr.get("rows")
    if not isinstance(pr_rows, list):
        problems.append("pr.rows is missing or not a list")
        pr_rows = []
    elif expected_rows is not None and len(pr_rows) != expected_rows:
        problems.append(f"pr has {len(pr_rows)} rows, expected {expected_rows}")

    def row_keys(rows: list, report_name: str) -> set[tuple[str, int]]:
        keys: list[tuple[str, int]] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                problems.append(f"{report_name}.rows[{index}] is not an object")
                continue
            item_id, seed = row.get("item_id"), row.get("seed")
            if not isinstance(item_id, str) or not isinstance(seed, int) or isinstance(seed, bool):
                problems.append(f"{report_name}.rows[{index}] has invalid item_id/seed")
                continue
            keys.append((item_id, seed))
        if len(set(keys)) != len(keys):
            problems.append(f"{report_name}.rows contains duplicate (item_id, seed) pairs")
        return set(keys)

    pr_keys = row_keys(pr_rows, "pr")
    base_rows = base.get("rows")
    if not isinstance(base_rows, list):
        problems.append("baseline.rows is missing or not a list")
        base_rows = []
    base_keys = row_keys(base_rows, "baseline")
    if pr_keys != base_keys:
        problems.append("pr (item_id, seed) pairs differ from baseline")

    for metric in spec.get("metrics", []):
        if not isinstance(metric, dict) or metric.get("grader") == "lab8.metrics.summarize":
            continue
        metric_id = metric.get("id")
        if not isinstance(metric_id, str):
            problems.append("spec contains a metric without a valid id")
            continue
        for row in pr_rows:
            if not isinstance(row, dict):
                continue
            score = row.get(metric_id)
            row_label = f"row {row.get('item_id')}@{row.get('seed')}"
            if score is None:
                problems.append(f"{row_label} has no {metric_id} score")
            elif isinstance(score, float) and not math.isfinite(score):
                problems.append(f"{row_label} has a non-finite {metric_id} score")
            elif not isinstance(score, (bool, int, float)):
                problems.append(f"{row_label} has a non-numeric {metric_id} score")

    def slice_tags(rows: list, report_name: str) -> dict[str, tuple[str, ...]]:
        tags_by_item: dict[str, tuple[str, ...]] = {}
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or not isinstance(row.get("item_id"), str):
                continue
            raw_tags = row.get("slices") or []
            if not isinstance(raw_tags, list) or any(not isinstance(tag, str) for tag in raw_tags):
                problems.append(f"{report_name}.rows[{index}].slices is invalid")
                continue
            tags = tuple(sorted(set(raw_tags)))
            item_id = row["item_id"]
            if item_id in tags_by_item and tags_by_item[item_id] != tags:
                problems.append(f"{report_name} has inconsistent slice tags for {item_id}")
            tags_by_item[item_id] = tags
        return tags_by_item

    pr_tags = slice_tags(pr_rows, "pr")
    base_tags = slice_tags(base_rows, "baseline")
    for item_id in sorted(set(pr_tags) & set(base_tags)):
        if pr_tags[item_id] != base_tags[item_id]:
            problems.append(f"slice tags differ for {item_id}")

    if (base_spec is not None
            and spec.get("eval_set_version") == base_spec.get("eval_set_version")):
        def keyed(entries: object, key_fields: tuple[str, ...], label: str) -> dict[tuple, dict]:
            indexed: dict[tuple, dict] = {}
            if not isinstance(entries, list):
                problems.append(f"{label} is missing or not a list")
                return indexed
            for entry in entries:
                if not isinstance(entry, dict) or any(not isinstance(entry.get(k), str) for k in key_fields):
                    problems.append(f"{label} contains an entry with an invalid identity")
                    continue
                key = tuple(entry[k] for k in key_fields)
                if key in indexed:
                    problems.append(f"{label} contains duplicate entry {key}")
                indexed[key] = entry
            return indexed

        def check_thresholds(old: dict, new: dict, subject: str) -> None:
            old_threshold = old.get("threshold", old)
            new_threshold = new.get("threshold", new)
            if not isinstance(old_threshold, dict) or not isinstance(new_threshold, dict):
                problems.append(f"{subject} has an invalid threshold")
                return
            for bound in ("max", "max_increase", "min"):
                if bound not in old_threshold:
                    continue
                if bound not in new_threshold:
                    problems.append(f"{subject} dropped its {bound} threshold")
                    continue
                old_value, new_value = old_threshold[bound], new_threshold[bound]
                if (isinstance(old_value, bool) or not isinstance(old_value, (int, float))
                        or isinstance(new_value, bool) or not isinstance(new_value, (int, float))
                        or isinstance(old_value, float) and not math.isfinite(old_value)
                        or isinstance(new_value, float) and not math.isfinite(new_value)):
                    problems.append(f"{subject} has a non-numeric {bound} threshold")
                elif (bound in ("max", "max_increase") and new_value > old_value) or (
                    bound == "min" and new_value < old_value
                ):
                    problems.append(f"{subject} loosened its {bound} threshold")
            if old_threshold.get("no_significant_drop") and not new_threshold.get("no_significant_drop"):
                problems.append(f"{subject} dropped no_significant_drop")
            if old.get("blocking") and not new.get("blocking"):
                problems.append(f"{subject} changed from blocking to non-blocking")

        old_metrics = keyed(base_spec.get("metrics"), ("id",), "base_spec.metrics")
        new_metrics = keyed(spec.get("metrics"), ("id",), "spec.metrics")
        for key, old_metric in old_metrics.items():
            new_metric = new_metrics.get(key)
            if new_metric is None:
                problems.append(f"metric {key[0]} was removed")
            else:
                check_thresholds(old_metric, new_metric, f"metric {key[0]}")

        old_slices = keyed(base_spec.get("slices", []), ("name", "metric"), "base_spec.slices")
        new_slices = keyed(spec.get("slices", []), ("name", "metric"), "spec.slices")
        for key, old_slice in old_slices.items():
            new_slice = new_slices.get(key)
            label = f"slice {key[0]}/{key[1]}"
            if new_slice is None:
                problems.append(f"{label} was removed")
            else:
                check_thresholds(old_slice, new_slice, label)

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
        name = slice_spec["name"]
        metric = slice_spec["metric"]
        slice_id = f"slice:{name}/{metric}"
        threshold = {key: value for key, value in slice_spec.items()
                     if key not in ("name", "metric", "blocking")}

        pr_items = per_item(pr, metric, slice_name=name)
        base_items = per_item(base, metric, slice_name=name)
        value = sum(pr_items.values()) / len(pr_items) if pr_items else None
        verdict = "ok"
        note = ""

        if value is None:
            verdict = "missing"
        elif "min" in slice_spec and value < slice_spec["min"]:
            verdict = "fail"

        if slice_spec.get("no_significant_drop"):
            keys = sorted(set(pr_items) & set(base_items))
            if not keys:
                verdict = "missing"
                note = "no paired slice items"
            else:
                delta, lo, hi = stats.paired_bootstrap(
                    [pr_items[key] for key in keys],
                    [base_items[key] for key in keys],
                    n_resamples=bs.get("n_resamples", 1000),
                    rng=bs.get("rng", 2027),
                    confidence=bs.get("confidence", 0.95),
                )
                note = f"Δ {delta:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"

        is_blocking = slice_spec.get("blocking", False)
        if verdict != "ok" and is_blocking:
            blocked.append(slice_id)
        label = {"ok": "ok", "missing": "MISSING"}.get(
            verdict, "BLOCK" if is_blocking else "warn"
        )
        lines.append(
            f"  {slice_id:<36} {value!s:<8} {json.dumps(threshold):<40} {note:<28} {label}"
        )
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
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
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
