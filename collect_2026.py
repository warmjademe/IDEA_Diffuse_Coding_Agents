#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集 2026 年新鲜"修 bug PR",组装成"缺陷代码 + 隐藏答案 + 测试"三件套(抗污染,模型学不到)。
在**本机**跑(NAS 连不上 GitHub)。token 从环境变量 GITHUB_TOKEN 读,绝不硬编码。
规模对齐原论文:目标 2346 训练 + 302 验证 = 2648。断点续跑、限速自适应、增量写盘。

用法: GITHUB_TOKEN=xxx python3 collect_2026.py --target 2648 --val 302 --out data/tasks_2026.jsonl
"""
import argparse, json, os, re, sys, time, urllib.request, urllib.parse, datetime

API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
HDR = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
       "User-Agent": "diffuse-2026-collector"}
CTX = 55; CAP_FILE = 8000; CAP_TOTAL = 12000
SRC_MAX_CHANGED = 80   # 源码改动总行数上限(要"局部化"的修复)

def gh(url, params=None, is_search=False, retries=4):
    if params: url = url + "?" + urllib.parse.urlencode(params)
    for a in range(retries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=40) as r:
                rem = int(r.headers.get("X-RateLimit-Remaining", "1"))
                rst = int(r.headers.get("X-RateLimit-Reset", "0"))
                data = json.loads(r.read().decode())
            if rem <= 1:
                wait = max(2, rst - int(time.time()) + 2)
                print(f"    [限速] core余额耗尽,睡 {wait}s", flush=True); time.sleep(min(wait, 3600))
            if is_search: time.sleep(2.2)   # search 30/min
            return data
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                print(f"    [限速/403] 睡 30s", flush=True); time.sleep(30)
            else:
                if a == retries - 1: return None
                time.sleep(3 * (a + 1))
        except Exception:
            if a == retries - 1: return None
            time.sleep(3 * (a + 1))
    return None

def raw_file(owner, repo, sha, path):
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{sha}/{path}"
    for a in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "col"}), timeout=40) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception:
            time.sleep(2)
    return None

def hunk_starts(patch):
    out = []
    for line in patch.splitlines():
        m = re.search(r'@@ -(\d+)(?:,(\d+))? ', line)
        if m: out.append((int(m.group(1)), int(m.group(2) or 1)))
    return out

def windows(text, hunks):
    lines = text.splitlines(); keep = set()
    for s, c in hunks:
        keep.update(range(max(0, s - 1 - CTX), min(len(lines), s - 1 + c + CTX)))
    if not keep: return ""
    out, prev = [], None
    for i in sorted(keep):
        if prev is not None and i > prev + 1: out.append("        ...")
        out.append(lines[i]); prev = i
    return "\n".join(out)

def is_test(path):
    p = path.lower()
    return ("test" in os.path.basename(p)) or ("/test" in p) or p.startswith("test")

def changed_lines(patch):
    return sum(1 for l in patch.splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---")))

def process(item):
    """一条搜索结果 → 三件套 dict 或 None。"""
    repo_url = item.get("repository_url", "")
    m = re.search(r'repos/([^/]+)/([^/]+)$', repo_url)
    if not m: return None
    owner, repo = m.group(1), m.group(2)
    num = item["number"]
    files = gh(f"{API}/repos/{owner}/{repo}/pulls/{num}/files", {"per_page": 100})
    if not isinstance(files, list) or not files: return None
    src, tst = [], []
    for f in files:
        patch = f.get("patch")
        if not patch: continue
        if f["filename"].endswith(".py") and not is_test(f["filename"]): src.append(f)
        elif is_test(f["filename"]): tst.append(f)
    if not src or not tst: return None                       # 必须"改了源码 且 带回归测试"
    if sum(changed_lines(f["patch"]) for f in src) > SRC_MAX_CHANGED: return None  # 要局部化
    pr = gh(f"{API}/repos/{owner}/{repo}/pulls/{num}")
    if not pr: return None
    base_sha = pr["base"]["sha"]
    gold = "\n".join(f'diff --git a/{f["filename"]} b/{f["filename"]}\n{f["patch"]}' for f in src)
    added = [l[1:] for f in src for l in f["patch"].splitlines() if l.startswith("+") and not l.startswith("+++")]
    issue = ((item.get("title") or "") + "\n" + (item.get("body") or "")).strip()
    parts, total = [], 0
    for f in src:
        raw = raw_file(owner, repo, base_sha, f["filename"])
        if raw is None: continue
        win = windows(raw, hunk_starts(f["patch"]))[:CAP_FILE]
        if not win.strip(): continue
        blk = f'# file: {f["filename"]}\n{win}'[:max(0, CAP_TOTAL - total)]
        parts.append(blk); total += len(blk)
        if total >= CAP_TOTAL: break
    ctx = "\n\n".join(parts).strip()
    if not ctx: return None
    if any(a.strip() and len(a.strip()) > 10 and a.strip() in ctx for a in added): return None   # 修复行泄漏
    if issue and len(issue) >= 60 and issue[:60] in ctx: return None                              # issue 泄漏
    return {
        "task_id": f"{owner}__{repo}-{num}", "repo": f"{owner}/{repo}", "pr": num,
        "base_commit": base_sha, "merged_at": pr.get("merged_at"),
        "code_context": ctx, "ctx_chars": len(ctx),
        "hidden_defect": {"changed_files": [f["filename"] for f in src], "issue": issue[:4000]},
        "gold_patch": gold,
        "tests": {"test_files": [f["filename"] for f in tst],
                  "test_patch": "\n".join(f["patch"] for f in tst)[:8000]},
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=2648)
    ap.add_argument("--val", type=int, default=302)
    ap.add_argument("--lang", default="Python")
    ap.add_argument("--end", default="2026-07-06")
    ap.add_argument("--days", type=int, default=185, help="从 end 往前推多少天")
    ap.add_argument("--out", default="data/tasks_2026.jsonl")
    args = ap.parse_args()
    if not TOKEN: sys.exit("[ERR] 需要环境变量 GITHUB_TOKEN")
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    seen_f = args.out + ".seen"; seen = set()
    if os.path.exists(seen_f): seen = set(open(seen_f).read().split())
    kept = sum(1 for _ in open(args.out)) if os.path.exists(args.out) else 0
    print(f"[*] 已有 {kept} 条,已看 {len(seen)} 个 PR;目标 {args.target}", flush=True)

    end = datetime.date.fromisoformat(args.end)
    fout = open(args.out, "a", encoding="utf-8"); fseen = open(seen_f, "a")
    for d in range(args.days):
        if kept >= args.target: break
        day = end - datetime.timedelta(days=d)
        q = f"type:pr is:merged label:bug language:{args.lang} merged:{day.isoformat()}..{day.isoformat()}"
        page = 1
        while kept < args.target:
            res = gh(f"{API}/search/issues", {"q": q, "per_page": 100, "page": page}, is_search=True)
            items = (res or {}).get("items", [])
            if not items: break
            for it in items:
                key = f'{it.get("repository_url","")}#{it["number"]}'
                if key in seen: continue
                seen.add(key); fseen.write(key + "\n")
                try: rec = process(it)
                except Exception: rec = None
                if rec:
                    fout.write(json.dumps(rec, ensure_ascii=False) + "\n"); fout.flush()
                    kept += 1
                    if kept % 20 == 0: print(f"    收集 {kept}/{args.target}(日期 {day},已看 {len(seen)})", flush=True)
                if kept >= args.target: break
            if len(items) < 100: break
            page += 1
            if page > 10: break     # search 每查最多 1000
    fout.close(); fseen.close()
    print(f"[OK] 共 {kept} 条 → {args.out}", flush=True)
    # 时间切分:最新的 val 条作验证(最不可能被污染),其余训练
    rows = [json.loads(l) for l in open(args.out, encoding="utf-8")]
    rows.sort(key=lambda r: r.get("merged_at") or "", reverse=True)
    for i, r in enumerate(rows): r["split"] = "val" if i < args.val else "train"
    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[OK] 切分:val={min(args.val,len(rows))} 训练={max(0,len(rows)-args.val)}", flush=True)

if __name__ == "__main__":
    main()
