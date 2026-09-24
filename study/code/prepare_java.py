"""Pinned Defects4J: original triggering tests, buggy/fixed replay, no LLM calls."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import difflib
import json
import os
from pathlib import Path
import random
import re
import subprocess
import shutil
import time

from api import dump
from prepare_python import context_from_patch, run

PROJECTS = ["Cli", "Codec", "Csv", "Gson", "Lang", "Math", "Jsoup", "JacksonCore"]


def source(root):
    return Path(json.loads((root/"protocol/defects4j_source.json").read_text())["path"])


def freeze_candidates(root):
    output = root/"data/java_candidates.json"
    if output.exists():
        return json.loads(output.read_text())
    base = source(root)
    groups = {}
    metadata = {}
    for project in PROJECTS:
        with (base/"framework/projects"/project/"active-bugs.csv").open() as f:
            items = list(csv.DictReader(f))
        ids = [str(t["bug.id"]) for t in items]
        random.Random(f"20260922:{project}").shuffle(ids)
        groups[project] = ids
        metadata.update({f"{project}-{t['bug.id']}": t for t in items})
    projects = PROJECTS.copy()
    random.Random(20260922).shuffle(projects)
    dev = [(p, groups[p].pop(0)) for p in projects[:5]]
    formal = [(p, groups[p][i]) for i in range(max(map(len, groups.values())))
              for p in projects if i < len(groups[p])]
    record = {"seed": 20260922, "projects": PROJECTS, "development_order": dev,
              "formal_order": formal, "metadata": metadata, "per_project_formal_cap": 20,
              "selection": "Fixed eight projects, seeded project/bug order, first reproducible instances. No model scores used."}
    dump(output, record)
    return record


def prefix(root, work):
    return ["docker", "run", "--rm", "--name", "jsep-java-"+work.name.lower(),
            "--cpus", "2", "--memory", "5g", "--pids-limit", "512", "--cap-drop=ALL",
            "--user", str(os.getuid())+":"+str(os.getgid()), "-e", "HOME=/tmp", "-e", "TZ=America/Los_Angeles",
            "-e", "LANG=C.UTF-8", "-e", "LC_ALL=C.UTF-8",
            "-v", str(source(root))+":/defects4j:ro", "-v", str(work)+":/work",
            "jsep-v3/java11"]


def command(root, work, args, name, timeout=600):
    return run(prefix(root, work)+["defects4j", *args], work, work/(name+".log"), timeout)


def export(root, work, prop, version):
    name = version+"_"+prop.replace('.', '_')
    output = work/(name+".txt")
    if command(root, work, ["export", "-w", "/work/"+version, "-p", prop, "-o", "/work/"+output.name], name, 60):
        raise ValueError("export failed: "+prop)
    return output.read_text().strip()


def reproduce(pair, root):
    project, bug = pair
    tid = project+"-"+bug
    work = root/"work/java"/tid
    work.mkdir(parents=True, exist_ok=True)
    output = work/"outcome.json"
    if output.exists():
        old = json.loads(output.read_text())
        if old.get("prep_version") == 2:
            return old
        archive = work/("diagnostics-v1-"+str(time.time_ns()))
        archive.mkdir()
        for path in work.iterdir():
            if path.is_file() and path.suffix in (".log", ".json", ".txt", ".patch"):
                shutil.copy2(path, archive/path.name)
        output.rename(archive/"outcome.json")
    result = {"task_id": "Defects4J-"+tid, "repo": "Defects4J/"+project,
              "project": project, "bug": bug, "status": "excluded", "started": time.time(), "prep_version": 2}
    try:
        for version, suffix in (("buggy", "b"), ("fixed", "f")):
            if not (work/version/".defects4j.config").exists():
                if command(root, work, ["checkout", "-p", project, "-v", bug+suffix,
                                       "-w", "/work/"+version], version+"_checkout", 300):
                    raise ValueError(version+" checkout failed")
        expected = export(root, work, "tests.trigger", "buggy").splitlines()
        # The framework's exact buggy/fixed tags include Java and accompanying
        # resources. Deriving paths from class names would lose $-named classes
        # and resource changes; compare the two program versions directly.
        tags = [f"D4J_{project}_{bug}_BUGGY_VERSION", f"D4J_{project}_{bug}_FIXED_VERSION"]
        if run(prefix(root, work)+["git", "-C", "/work/buggy", "diff", "--no-ext-diff", *tags, "--"],
               work, work/"reference_fix.patch", 60):
            raise ValueError("cannot compare exact framework program tags")
        gold = (work/"reference_fix.patch").read_text()
        if not re.search(r"(?m)^diff --git a/.*\.java b/", gold):
            raise ValueError("no Java source change in reference fix")
        if not gold or len(gold)>16000:
            raise ValueError("reference patch outside input budget")
        code = context_from_patch(work/"buggy", gold)
        (work/"reference_fix.patch").write_text(gold)
        for version in ("buggy", "fixed"):
            if command(root, work, ["test", "-r", "-w", "/work/"+version], version+"_test", 600):
                raise ValueError(version+" compile/test infrastructure failed")
        buggy_log = (work/"buggy/failing_tests").read_text(errors='replace')
        fixed_log = (work/"fixed/failing_tests").read_text(errors='replace')
        failures = re.findall(r"(?m)^--- (.+)$", buggy_log)
        if not failures or not set(failures).issubset(set(expected)):
            raise ValueError("buggy failures do not match benchmark triggers")
        if fixed_log.strip():
            raise ValueError("fixed tests still fail")
        (work/"raw_failure.log").write_text(buggy_log)
        sent_log = buggy_log if len(buggy_log)<=12000 else buggy_log[:6000]+"\n[RAW LOG MIDDLE OMITTED]\n"+buggy_log[-6000:]
        result.update(status="verified", language="Java", code_context=code, gold_patch=gold,
                      hidden_defect={"benchmark": "Defects4J", "project": project, "bug_id": bug},
                      test_patch="", tests_source="Defects4J developer-written triggering tests, not author-written tests",
                      failure_log=sent_log, raw_failure_log=str(work/"raw_failure.log"),
                      log_truncated=len(buggy_log)>12000, failed_tests=failures,
                      triggering_tests=expected, evidence_dir=str(work))
    except Exception as exc:
        result["reason"] = type(exc).__name__+": "+str(exc)[:500]
        subprocess.run(["docker", "rm", "-f", "jsep-java-"+work.name.lower()], capture_output=True)
    result["ended"] = time.time()
    dump(output, result)
    print(json.dumps({k: result.get(k) for k in ("task_id", "status", "reason")}), flush=True)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--stage", choices=["development", "formal"], required=True)
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()
    root = Path(args.root)
    if not (root/"protocol/java_environment_ready.json").exists():
        raise RuntimeError("Java environment preflight required before screening")
    candidates = freeze_candidates(root)
    order = candidates[args.stage+"_order"]
    wanted = 5 if args.stage == "development" else 100
    chosen, counts, attempts = [], {}, []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for start in range(0, len(order), args.workers):
            for result in pool.map(lambda pair: reproduce(pair, root), order[start:start+args.workers]):
                attempts.append({k: result.get(k) for k in ("task_id", "status", "reason")})
                if result["status"] != "verified" or len(chosen)>=wanted:
                    continue
                if args.stage=="formal" and counts.get(result["project"],0)>=20:
                    continue
                chosen.append(result)
                counts[result["project"]] = counts.get(result["project"],0)+1
            dump(root/f"data/java_{args.stage}_progress.json", {"n":len(chosen), "target":wanted, "attempts":attempts, "tasks":chosen})
            if len(chosen)==wanted:
                break
    dump(root/f"data/java_{args.stage}.json", {"complete":len(chosen)==wanted, "tasks":chosen, "attempts":attempts})


if __name__ == "__main__":
    main()
