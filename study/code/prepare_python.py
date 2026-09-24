"""Reproduce historical candidate PRs in credential-free, resource-limited containers.

Selections depend on source/provenance and executable fail/pass checks only, never
on model scores. Corpus lines are split on LF bytes: Unicode line separators can
occur inside JSON string values and must not be treated as record boundaries.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import random
import re
import subprocess
import shutil
import tarfile
import time
import urllib.error
import urllib.request

from api import dump

SEED = 20260922


def rows(path):
    return [json.loads(line) for line in Path(path).read_bytes().split(b"\n") if line.strip()]


def run(cmd, cwd, log, timeout=300, env=None):
    start = time.time()
    with Path(log).open("wb") as f:
        try:
            p = subprocess.run(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT,
                               timeout=timeout, env=env)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = 124
    dump(str(log) + ".meta.json", {"command": cmd, "cwd": str(cwd), "returncode": rc,
                                   "seconds": time.time() - start})
    return rc


def fetch(url, path, accept=None):
    path = Path(path)
    if path.exists():
        return path.read_bytes()
    headers = {"User-Agent": "JSEP-Diffuse-reproduction/3"}
    if accept:
        headers["Accept"] = accept
    keypath = Path.home() / ".config/jsep-diffuse/github.key"
    if url.startswith("https://api.github.com/") and keypath.exists():
        headers["Authorization"] = "Bearer " + keypath.read_text().strip()
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        started = time.monotonic()
        chunks, size = [], 0
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > 80_000_000:
                raise ValueError("archive exceeds 80 MB reproducibility budget")
            if time.monotonic() - started > 180:
                raise TimeoutError("download exceeds 180 second reproducibility budget")
        content = b"".join(chunks)
    if len(content) > 80_000_000:
        raise ValueError("archive exceeds 80 MB reproducibility budget")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


def historical_ids(source):
    ids = set()
    def visit(value):
        if isinstance(value, dict):
            for key, val in value.items():
                if key in {"task_id", "tid"} and isinstance(val, str):
                    ids.add(val)
                elif key in {"tasks", "task_ids", "runnable"} and isinstance(val, list):
                    ids.update(x for x in val if isinstance(x, str))
                visit(val)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    for f in (source / "results").rglob("*"):
        try:
            if f.suffix == ".json":
                visit(json.loads(f.read_bytes()))
            elif f.suffix == ".jsonl":
                for row in rows(f):
                    visit(row)
        except (ValueError, OSError):
            continue
    return ids


def freeze_candidates(root, source):
    target = root / "data/python_candidates.json"
    if target.exists():
        return json.loads(target.read_text())
    corpus = rows(source / "data/tasks_2026.jsonl")
    old = historical_ids(source)
    unique = {}
    exclusions = []
    for t in corpus:
        tid = t["task_id"]
        if tid in unique:
            exclusions.append({"id": tid, "reason": "duplicate_id"})
            continue
        if not t.get("gold_patch") or not t.get("tests", {}).get("test_files"):
            exclusions.append({"id": tid, "reason": "missing_patch_or_test"})
            continue
        if len(t["gold_patch"]) > 16000:
            exclusions.append({"id": tid, "reason": "patch_over_input_budget"})
            continue
        unique[tid] = t
    old_runnable = json.loads((source / "results/runnable_tasks.json").read_text())["runnable"]
    dev = [i for i in old_runnable if i in unique]
    random.Random(SEED).shuffle(dev)
    # Round-robin projects after seeded shuffling prevents one large project dominating.
    groups = {}
    for tid, t in unique.items():
        if tid not in old:
            groups.setdefault(t["repo"], []).append(tid)
    rng = random.Random(SEED)
    projects = sorted(groups)
    rng.shuffle(projects)
    for group in groups.values():
        rng.shuffle(group)
    formal = [groups[p][i] for i in range(max(map(len, groups.values())))
              for p in projects if i < len(groups[p])]
    record = {"seed": SEED, "corpus_n": len(corpus), "corpus_sha256": hashlib.sha256((source / "data/tasks_2026.jsonl").read_bytes()).hexdigest(),
              "historical_ids": sorted(old), "pre_execution_exclusions": exclusions,
              "development_order": dev, "formal_order": formal,
              "formal_per_project_cap": 2, "tasks": unique,
              "created": time.time(), "selection": "first executable tasks in frozen order; formal maximum 2 tasks per repository"}
    dump(target, record)
    return record


def context_from_patch(repo, patch, limit=24000):
    selections = {}
    filename = None
    for line in patch.splitlines():
        if line.startswith("diff --git a/"):
            m = re.match(r"diff --git a/(.*?) b/(.*)$", line)
            filename = m[1] if m else None
        elif line.startswith("--- a/"):
            filename = line[6:]
        elif line.startswith("@@") and filename:
            m = re.match(r"@@ -(\d+)(?:,(\d+))?", line)
            if m:
                start, size = int(m[1]), int(m[2] or 1)
                selections.setdefault(filename, set()).update(range(max(1, start-35), start+size+36))
    parts = []
    for file, nums in selections.items():
        path = (repo / file).resolve()
        if not path.is_relative_to(repo.resolve()) or not path.is_file():
            raise ValueError("missing or unsafe pre-image source")
        lines = path.read_text(errors="replace").splitlines()
        selected = [f"{i}: {lines[i-1]}" for i in sorted(nums) if i <= len(lines)]
        parts.append("# file: " + file + "\n" + "\n".join(selected))
    text = "\n\n".join(parts)
    if not text or len(text) > limit:
        raise ValueError("code context outside predeclared input budget")
    return text


def normalize_patch(patch, repo):
    """Restore omitted file headers from recorded diff metadata, without changing hunks."""
    blocks = re.split(r"(?m)(?=^diff --git )", patch)
    out = []
    for block in blocks:
        if not block.strip():
            continue
        lines = block.splitlines()
        m = re.match(r"diff --git a/(.*?) b/(.*)$", lines[0])
        if not m:
            raise ValueError("unrecognized patch metadata")
        if not any(l.startswith("--- ") for l in lines):
            oldpath = "a/"+m[1] if (repo/m[1]).exists() else "/dev/null"
            lines[1:1] = ["--- " + oldpath, "+++ b/" + m[2]]
        if "--- /dev/null" in lines and not any(l.startswith("new file mode ") for l in lines):
            lines.insert(1, "new file mode 100644")
        out.append("\n".join(lines)+"\n")
    return "".join(out)


def docker_prefix(work):
    return ["docker", "run", "--rm", "--name", "jsep-py-" + work.name.lower()[:48],
            "--cpus", "2", "--memory", "4g", "--pids-limit", "256", "--cap-drop=ALL",
            "--user", str(os.getuid())+":"+str(os.getgid()),
            "-e", "HOME=/tmp", "-e", "PIP_DISABLE_PIP_VERSION_CHECK=1",
            "-e", "PYTHONDONTWRITEBYTECODE=1", "-v", str(work)+":/work", "-w", "/work/repo",
            "python:3.12-slim"]


def reproduce(task, root):
    tid = task["task_id"]
    work = root / "work/python_v3" / tid
    work.mkdir(parents=True, exist_ok=True)
    outcome = work / "outcome.json"
    if outcome.exists():
        old = json.loads(outcome.read_text())
        reason = old.get("reason", "")
        patch_log = (work/"test_patch.log").read_text(errors="replace") if (work/"test_patch.log").exists() else ""
        test_log = (work/"buggy.log").read_text(errors="replace") if (work/"buggy.log").exists() else ""
        cached = root/"data/base_archives"/(tid+".tar.gz")
        infrastructure_retry = (
            (cached.exists() and ("download" in reason.lower() or "timed out" in reason.lower())) or
            ("regression_test_patch_does_not_apply" in reason and "dev/null" in patch_log) or
            ("buggy_test_execution_failed" in reason and any(x in test_log for x in ("No module named 'requests_mock'", "No module named 'requests_cache'")))
        )
        if not infrastructure_retry:
            return old
        archive = work/("infrastructure-attempt-"+str(time.time_ns()))
        archive.mkdir()
        for f in work.iterdir():
            if f.is_file() and f.suffix in (".log", ".json", ".xml", ".txt", ".patch"):
                shutil.copy2(f, archive/f.name)
        outcome.rename(archive/"outcome.json")
    if shutil.disk_usage(root).free < 80 * 1024**3:
        raise RuntimeError("data preparation stopped: less than 80 GiB free")
    result = {"task_id": tid, "repo": task["repo"], "status": "excluded", "started": time.time()}
    try:
        # Use the collected test hunk directly when it has one unambiguous file.
        files = task["tests"]["test_files"]
        if len(files) == 1 and task["tests"].get("test_patch", "").startswith("@@"):
            testpatch = "diff --git a/{0} b/{0}\n--- a/{0}\n+++ b/{0}\n".format(files[0]) + task["tests"]["test_patch"] + "\n"
        else:
            url = f"https://api.github.com/repos/{task['repo']}/pulls/{task['pr']}/files?per_page=100"
            info = json.loads(fetch(url, work / "pr_files.json"))
            chunks = []
            for item in info:
                if item.get("filename") in files:
                    if not item.get("patch"):
                        raise ValueError("test diff missing or truncated by source API")
                    name = item["filename"]
                    if item.get("status") == "renamed":
                        raise ValueError("renamed regression test unsupported")
                    oldpath = "/dev/null" if item.get("status") == "added" else "a/"+name
                    chunks.append(f"diff --git a/{name} b/{name}\n--- {oldpath}\n+++ b/{name}\n"+item["patch"]+"\n")
            if len(chunks) != len(files):
                raise ValueError("incomplete test file coverage")
            testpatch = "".join(chunks)
        for version in ("python_v2", "python"):
            old_archive = root / "work" / version / tid / "base.tar.gz"
            if old_archive.exists() and not (work/"base.tar.gz").exists():
                os.link(old_archive, work/"base.tar.gz")
        cached = root/"data/base_archives"/(tid+".tar.gz")
        if cached.exists() and not (work/"base.tar.gz").exists():
            os.link(cached, work/"base.tar.gz")
        archive = fetch(f"https://codeload.github.com/{task['repo']}/tar.gz/{task['base_commit']}", work / "base.tar.gz")
        repo = work / "repo"
        # A killed attempt may have patched its working copy; preserve it and restore
        # a clean archive pre-image before resuming an unfinished candidate.
        if repo.exists():
            repo.rename(work / ("repo.interrupted-" + str(time.time_ns())))
        if not repo.exists():
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
                tops = {m.name.split('/')[0] for m in tar.getmembers()}
                if len(tops) != 1:
                    raise ValueError("unexpected archive root")
                tar.extractall(work, filter="data")
            (work / next(iter(tops))).rename(repo)
        code = context_from_patch(repo, task["gold_patch"])
        testpatch = normalize_patch(testpatch, repo)
        if len(files) == 1 and not (repo/files[0]).exists():
            testpatch = testpatch.replace("--- a/"+files[0]+"\n", "--- /dev/null\n", 1)
            testpatch = normalize_patch(testpatch, repo)
        (work / "test.patch").write_text(testpatch)
        (work / "fix.patch").write_text(normalize_patch(task["gold_patch"], repo))
        if run(["git", "apply", "--recount", "--whitespace=nowarn", str(work/"test.patch")], repo, work/"test_patch.log", 30):
            raise ValueError("regression_test_patch_does_not_apply")
        pyfiles = [f for f in files if f.endswith(".py")]
        if not pyfiles:
            raise ValueError("no_python_regression_test")
        prefix = docker_prefix(work)
        # A project-local virtual environment keeps dependency changes out of the host.
        setup = "python -m venv /work/env && /work/env/bin/pip install pytest pytest-asyncio pytest-mock requests-mock requests-cache && if [ -f pyproject.toml ] || [ -f setup.py ]; then /work/env/bin/pip install -e '.[test,tests,testing]'; elif [ -f requirements.txt ]; then /work/env/bin/pip install -r requirements.txt; fi"
        if run(prefix + ["sh", "-c", setup], work, work/"setup.log", 300):
            raise ValueError("dependency_setup_failed")
        run(prefix + ["/work/env/bin/pip", "freeze", "--all"], work, work/"dependencies.txt", 30)
        testcmd = prefix + ["/work/env/bin/python", "-m", "pytest", "-q", "--tb=short", "-o", "addopts=", *pyfiles, "--junitxml=/work/buggy.xml"]
        buggy_rc = run(testcmd, work, work/"buggy.log", 180)
        import xml.etree.ElementTree as ET
        if not (work/"buggy.xml").exists():
            raise ValueError("buggy_test_execution_failed")
        tree = ET.parse(work/"buggy.xml")
        failures = [(tc.get("classname"), tc.get("name")) for tc in tree.iter("testcase") if tc.find("failure") is not None]
        errors = list(tree.iter("error"))
        if buggy_rc != 1 or not failures or errors:
            raise ValueError("no_clean_assertion_failure_on_buggy")
        if run(["git", "apply", "--recount", "--whitespace=nowarn", str(work/"fix.patch")], repo, work/"fix_patch.log", 30):
            raise ValueError("reference_fix_does_not_apply")
        fixedcmd = testcmd[:-1] + ["--junitxml=/work/fixed.xml"]
        if run(fixedcmd, work, work/"fixed.log", 180) != 0:
            raise ValueError("fixed_tests_do_not_pass")
        fixed = ET.parse(work/"fixed.xml")
        if not list(fixed.iter("testcase")) or list(fixed.iter("failure")) or list(fixed.iter("error")):
            raise ValueError("fixed_test_evidence_invalid")
        log = (work/"buggy.log").read_text(errors="replace")
        # Deterministic raw head/tail; no author-written explanation is sent as a log.
        sent_log = log if len(log) <= 12000 else log[:6000]+"\n[RAW LOG MIDDLE OMITTED]\n"+log[-6000:]
        result.update(status="verified", language="Python", code_context=code,
                      gold_patch=task["gold_patch"], test_patch=testpatch,
                      failure_log=sent_log, raw_failure_log=str(work/"buggy.log"),
                      log_truncated=len(log)>12000, hidden_defect=task.get("hidden_defect", {}),
                      base_commit=task["base_commit"], merged_at=task["merged_at"],
                      tests_source="original bug-fix pull request", failed_tests=failures,
                      archive_sha256=hashlib.sha256(archive).hexdigest(), evidence_dir=str(work))
    except Exception as exc:
        result["reason"] = type(exc).__name__ + ": " + str(exc)[:500]
        # A subprocess timeout must not leave its Docker workload consuming resources.
        subprocess.run(["docker", "rm", "-f", "jsep-py-"+tid.lower()[:48]], capture_output=True)
    result["ended"] = time.time()
    dump(outcome, result)
    print(json.dumps({k: result.get(k) for k in ("task_id", "status", "reason")}), flush=True)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--source", default="/home/qyb/IDEA_Diffuse_Coding_Agents/Source_Codes")
    ap.add_argument("--stage", choices=["development", "formal"], required=True)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--max-attempts", type=int, default=250)
    args = ap.parse_args()
    root, source = Path(args.root), Path(args.source)
    policy_file = root/'protocol/python_sample_policy.json'
    policy = json.loads(policy_file.read_text()) if policy_file.exists() else {}
    final_file = root/f'data/python_{args.stage}.json'
    if args.stage == 'formal' and policy.get('screening_stopped') and final_file.exists():
        fixed = json.loads(final_file.read_text())
        if not fixed.get('complete') or len(fixed['tasks']) != policy['target']:
            raise RuntimeError('stopped dataset does not match authorized sample size')
        print(json.dumps({'stage': 'formal', 'already_selected': len(fixed['tasks']), 'screening_stopped_by_author': True}))
        return
    candidates = freeze_candidates(root, source)
    order = candidates[args.stage+"_order"][:args.max_attempts]
    wanted = 20 if args.stage == "development" else policy.get('target', 40)
    chosen, counts, attempts = [], {}, []
    # Consume each batch in the frozen candidate order, not fastest-completion order.
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for start in range(0, len(order), args.workers):
            batch = order[start:start+args.workers]
            for result in pool.map(lambda tid: reproduce(candidates["tasks"][tid], root), batch):
                attempts.append({k: result.get(k) for k in ("task_id", "status", "reason")})
                if result["status"] != "verified" or len(chosen) >= wanted:
                    continue
                repo = result["repo"]
                if args.stage == "formal" and counts.get(repo, 0) >= 2:
                    continue
                chosen.append(result)
                counts[repo] = counts.get(repo, 0)+1
            dump(root/f"data/python_{args.stage}_progress.json", {"n": len(chosen), "target": wanted, "tasks": chosen, "attempts": attempts})
            if len(chosen) == wanted:
                break
    output = {"complete": len(chosen) == wanted, "tasks": chosen, "attempts": attempts,
              "stage": args.stage, "seed": SEED, "created": time.time()}
    if args.stage == "development" and output["complete"]:
        output["calibration_ids"] = [t["task_id"] for t in chosen[:10]]
        output["optimization_ids"] = [t["task_id"] for t in chosen[10:]]
    dump(root/f"data/python_{args.stage}.json", output)
    print(json.dumps({"stage": args.stage, "verified": len(chosen), "attempted": len(attempts)}))


if __name__ == "__main__":
    main()
