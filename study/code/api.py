"""Audited model calls: TeamRouter main study, official DeepSeek Pro review.

No credentials are stored in this module, a request artifact, or an error message.
SDK retries are disabled: every network attempt must pass through the ledger.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
import threading
import urllib.request
import uuid

MODELS = {
    "sonnet": "claude-sonnet-4-6", "gpt": "gpt-5.5",
    "gemini": "gemini-3.5-flash-lite", "haiku": "claude-haiku-4-5-20251001",
    "mini": "gpt-5.4-mini", "reference": "deepseek-flash",
    "official_pro": "deepseek-v4-pro",
}

# NAS stack traces showed a native SQLite mutex deadlock when one thread closed
# a WAL connection while other threads opened connections. Guard the complete
# lifecycle, including connect and close, across all Runner instances. Model
# calls run outside this short critical section and retain their concurrency.
_DB_LIFECYCLE_LOCK = threading.RLock()


def dump(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def clean_error(text):
    return re.sub(r"(?:sk-|ghp_|olp_|hf_)[A-Za-z0-9_-]+", "[REDACTED]", str(text))[:2000]


def parse_json(text):
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)[:-3].strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("response must be a JSON object")
    return data


def parse_score(text):
    data = parse_json(text)
    score = data.get("score")
    if type(score) not in (int, float) or not 0 <= score <= 100:
        raise ValueError("invalid or missing score; no imputation")
    return data


def parse_reference(text):
    data = parse_json(text)
    for key in ("C", "A", "M"):
        value = data.get(key)
        if not (type(value) is int and value in (0, 1)) and value != "unknown":
            raise ValueError("reference dimensions require 0, 1 or unknown")
    evidence = data.get("evidence")
    evidence_ok = isinstance(evidence, str) and bool(evidence.strip())
    if isinstance(evidence, dict):
        evidence_ok = all(isinstance(evidence.get(k), str) and evidence[k].strip() for k in ("C", "A", "M"))
    if not evidence_ok:
        raise ValueError("reference evidence is required")
    c, a, m = (data[k] for k in ("C", "A", "M"))
    data["y"] = 0 if c == 0 or a == 0 or m == 1 else (1 if (c, a, m) == (1, 1, 0) else None)
    return data


class BudgetStop(RuntimeError):
    pass


class Runner:
    def __init__(self, root):
        self.root = Path(root)
        self.dbpath = self.root / "runs/ledger.sqlite"
        self.dbpath.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS calls (
              id TEXT PRIMARY KEY, logical_id TEXT NOT NULL, phase TEXT NOT NULL,
              role TEXT NOT NULL, attempt INTEGER NOT NULL, request_hash TEXT NOT NULL,
              status TEXT NOT NULL, reserved_usd REAL NOT NULL, estimated_usd REAL,
              started REAL NOT NULL, ended REAL, artifact TEXT, returned_model TEXT)""")
        self.network_slots = threading.BoundedSemaphore(8)

    def transport(self, role, request):
        # One SDK client per child: no shared HTTP connection-pool locks. The
        # parent kills and reaps the child at a wall deadline, including stalls
        # that an HTTP read timeout cannot interrupt. No credentials in argv.
        process = subprocess.run(
            [sys.executable, str(Path(__file__).with_name('transport.py'))],
            input=json.dumps({'role': role, 'request': request}), text=True,
            capture_output=True, timeout=195)
        if process.returncode:
            raise RuntimeError('transport child failed: '+clean_error(process.stderr))
        result = json.loads(process.stdout)
        if result.get('error'):
            raise RuntimeError(result['error'])
        return result

    @contextmanager
    def db(self):
        with _DB_LIFECYCLE_LOCK:
            db = sqlite3.connect(self.dbpath, timeout=30)
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                db.close()

    def prices(self):
        path = self.root / "protocol/pricing_snapshot.json"
        if not path.exists() or time.time() - path.stat().st_mtime > 900:
            with urllib.request.urlopen("https://api.teamorouter.cn/v1/models/pricing", timeout=30) as r:
                data = json.load(r)
            dump(path, data)
            dump(self.root / "runs/prices" / (str(time.time_ns()) + ".json"), data)
        return {m["id"]: m for m in json.loads(path.read_text())["models"]}

    def call(self, logical_id, phase, role, messages, max_tokens=2048,
             temperature=0.0, parser=None, attempt=0):
        request = {"model": MODELS[role], "messages": messages,
                   "max_tokens": max_tokens, "temperature": temperature}
        parameter_file = self.root / "protocol/model_parameters.json"
        if parameter_file.exists():
            request.update(json.loads(parameter_file.read_text()).get(role, {}))
        # Independent repetitions have different logical IDs, even with identical text.
        official = role == "official_pro"
        req_hash = digest(["https://api.deepseek.com", request]) if official else digest(request)
        call_id = digest([logical_id, attempt])
        artifact = self.root / "runs/raw" / (call_id + ".json")
        with self.db() as db:
            prior = db.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
        if prior:
            if prior["request_hash"] != req_hash:
                raise RuntimeError("immutable job reused with changed request: " + logical_id)
            if artifact.exists():
                return json.loads(artifact.read_text())
            raise RuntimeError("unresolved reserved call; inspect before retry: " + logical_id)

        limits = json.loads((self.root / "protocol/budget.json").read_text())
        price = (json.loads((self.root/'protocol/official_pro_pricing.json').read_text())
                 if official else self.prices()[MODELS[role]])
        # Reserve at published LIST prices, with one input token per UTF-8 byte plus overhead.
        # The reported cost estimate uses published gateway prices, without cache discounts.
        input_upper = len(json.dumps(messages, ensure_ascii=False).encode()) + 16384
        reserve = (input_upper * price["list_cost"]["input"] +
                   max_tokens * price["list_cost"]["output"]) / 1e6
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute("SELECT count(*) FROM calls").fetchone()[0] + 2
            dev = db.execute("SELECT count(*) FROM calls WHERE phase!='formal'").fetchone()[0] + 2
            pilot = db.execute("SELECT count(*) FROM calls WHERE phase='pilot'").fetchone()[0] + 2
            total_usd = db.execute("SELECT coalesce(sum(coalesce(estimated_usd,reserved_usd)),0) FROM calls").fetchone()[0]
            if count >= 17000 or (phase != "formal" and dev >= 1500):
                raise BudgetStop("call ceiling reached")
            if phase == "pilot" and pilot >= 100:
                raise BudgetStop("pilot call ceiling reached")
            if phase not in limits["allowed_phases"]:
                raise BudgetStop("phase gate: " + phase)
            if limits["usd_cap"] is not None and total_usd + reserve > limits["usd_cap"]:
                raise BudgetStop("monetary ceiling reached before reservation")
            if (self.root / "STOP").exists():
                raise BudgetStop("STOP file exists")
            db.execute("INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (call_id, logical_id, phase, role, attempt, req_hash, "reserved",
                        reserve, None, time.time(), None, str(artifact), None))

        result = {"id": call_id, "logical_id": logical_id, "phase": phase, "role": role,
                  "provider": "DeepSeek official" if official else "TeamRouter",
                  "attempt": attempt, "request": request, "request_hash": req_hash,
                  "pricing": price, "reserved_usd": reserve, "started": time.time()}
        # Preserve inputs even if this process is interrupted before a response.
        dump(self.root/'runs/requests'/(call_id+'.json'), result)
        returned = None
        cost = None
        try:
            with self.network_slots:
                result['network_started'] = time.time()
                dump(self.root/'runs/requests'/(call_id+'.json'), result)
                transported = self.transport(role, request)
            response = transported['response']
            result["raw_response"] = response
            result["request_id"] = transported.get('request_id')
            returned = response['model']
            choice = response['choices'][0]
            content = choice['message'].get('content') or ""
            result["content"] = content
            result["finish_reason"] = choice['finish_reason']
            usage = response.get('usage')
            if usage:
                cost = (usage['prompt_tokens'] * price["cost"]["input"] +
                        usage['completion_tokens'] * price["cost"]["output"]) / 1e6
            result["estimated_usd"] = cost
            # Version mismatches and token truncation cannot enter the analysis silently.
            pinfile = self.root / "protocol/model_versions.json"
            pins = json.loads(pinfile.read_text()) if pinfile.exists() else {}
            if role in pins and returned != pins[role]:
                raise ValueError("returned model version changed: " + str(returned))
            if choice['finish_reason'] not in ("stop", "end_turn"):
                raise ValueError("incomplete output: " + str(choice['finish_reason']))
            if not content.strip():
                raise ValueError("empty output")
            result["parsed"] = parser(content) if parser else {"text": content}
            result["status"] = "ok"
        except Exception as error:
            result["status"] = "failed"
            result["error_type"] = type(error).__name__
            result["error"] = clean_error(error)
        result["ended"] = time.time()
        result["duration_s"] = result["ended"] - result["started"]
        dump(artifact, result)
        with self.db() as db:
            db.execute("UPDATE calls SET status=?,estimated_usd=?,ended=?,artifact=?,returned_model=? WHERE id=?",
                       (result["status"], cost, time.time(), str(artifact), returned, call_id))
        print(json.dumps({k: result.get(k) for k in ("logical_id", "status", "duration_s", "estimated_usd", "error")}), flush=True)
        return result

    def summary(self):
        with self.db() as db:
            rows = [dict(r) for r in db.execute("SELECT phase,role,status,count(*) AS n,sum(estimated_usd) AS estimated_usd FROM calls GROUP BY phase,role,status")]
        return {"prior_connectivity_calls": 2, "calls": rows,
                "cost_note": "Published gateway price estimate; not a reconciled invoice. Unknown-usage calls retain reservations."}
