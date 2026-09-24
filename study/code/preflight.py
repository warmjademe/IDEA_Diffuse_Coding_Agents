"""NAS-only API and format preflight. No paper task or formal result is generated."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import platform
import sys

from api import Runner, MODELS, dump, parse_score


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    root = Path(args.root)
    if platform.node() != "qyb-SJHY-ubuntu25":
        raise RuntimeError("Experimental API calls are authorized on NAS only")
    budget = root / "protocol/budget.json"
    if not budget.exists():
        dump(budget, {"usd_cap": 5.0, "allowed_phases": ["pilot"],
                      "pilot_calls": 100, "development_calls": 1500, "all_calls": 17000,
                      "note": "Conservative initial USD 5 pilot limit, within CNY 50. Full-study ceiling is pending author input."})
    runner = Runner(root)
    messages = [{"role": "system", "content": "You evaluate code reviews. Return a JSON object containing score (0–100) and reason."},
                {"role": "user", "content": 'Code: def mean(xs): return sum(xs)/len(xs)\nReview: Empty input raises ZeroDivisionError; explicitly reject an empty list or define its result.\nAssess the review for correctness and usefulness. Respond as JSON with score and reason.'}]
    def one(role):
        return role, runner.call("preflight/v2/" + role, "pilot", role, messages,
                                 max_tokens=1024, temperature=0.0, parser=parse_score)
    roles = [role for role in MODELS if role != 'official_pro']
    with ThreadPoolExecutor(max_workers=3) as pool:
        records = dict(pool.map(one, roles))
    pins = json.loads((root/'protocol/model_versions.json').read_text()) if (root/'protocol/model_versions.json').exists() else {}
    for role, record in records.items():
        if record["status"] == "ok":
            pins[role] = record["raw_response"]["model"]
    if all(role in pins and records[role]['status'] == 'ok' for role in roles):
        dump(root / "protocol/model_versions.json", pins)
    report = {"host": platform.node(), "python": sys.version, "models": pins,
              "all_passed": all(records[role]['status'] == 'ok' for role in roles), "usage": runner.summary()}
    dump(root / "runs/preflight_report.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
