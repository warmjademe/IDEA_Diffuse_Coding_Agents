"""Transport public source archives through the existing USA2 connection.

No experiment or inference runs on USA2 or this transport host. All corpus
selection, builds, regression tests, and model calls remain on NAS.
"""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

NAS = ["ssh", "-o", "BatchMode=yes", "-p", "2222", "qyb@nas.qyb.name"]
ROOT = "/home/qyb/Research/JSEP_Diffuse_Coding_Agents/revision_v3_20260922"


def manifest():
    code = f"""from pathlib import Path
import json
r=Path({ROOT!r})
d=json.loads((r/'data/python_candidates.json').read_text())
out=[]
for tid in d['development_order']+d['formal_order'][:500]:
 t=d['tasks'][tid];p=r/'work/python_v3'/tid/'outcome.json'
 old=json.loads(p.read_text()) if p.exists() else {{}}
 if old and 'download' not in old.get('reason','').lower() and 'timed out' not in old.get('reason','').lower():continue
 if (r/'data/base_archives'/(tid+'.tar.gz')).exists():continue
 out.append({{k:t[k] for k in ['task_id','repo','base_commit']}})
print(json.dumps(out))
"""
    p = subprocess.run(NAS+["python3 -"], input=code, text=True, capture_output=True, check=True)
    return json.loads(p.stdout)


def transfer(task):
    tid, repo, sha = (task[k] for k in ("task_id", "repo", "base_commit"))
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo) or not re.fullmatch(r"[0-9a-f]{40}", sha) or '/' in tid:
        return {"task_id": tid, "status": "invalid_source_metadata"}
    url = f"https://codeload.github.com/{repo}/tar.gz/{sha}"
    with tempfile.TemporaryDirectory(prefix="jsep-public-source-") as folder:
        path = Path(folder)/(tid+".tar.gz")
        p = subprocess.Popen(["ssh", "-o", "BatchMode=yes", "ubuntu@usa2.qyb.name",
                              "curl -fsSL --max-time 180 --max-filesize 80000000 "+shlex.quote(url)],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        size = 0
        with path.open('wb') as f:
            while True:
                chunk = p.stdout.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > 80_000_000:
                    p.terminate()
                    break
                f.write(chunk)
        rc = p.wait()
        if rc or size > 80_000_000:
            return {"task_id": tid, "status": "download_failed", "bytes": size}
        target = "qyb@nas.qyb.name:"+ROOT+"/data/base_archives/"
        cp = subprocess.run(["rsync", "-a", "-e", "ssh -p 2222", str(path), target], capture_output=True)
        return {"task_id": tid, "status": "cached" if cp.returncode==0 else "transfer_failed",
                "bytes": size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    subprocess.run(NAS+["mkdir -p "+shlex.quote(ROOT+"/data/base_archives")], check=True)
    tasks = manifest()
    print(json.dumps({"public_archives_requested": len(tasks)}), flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for future in concurrent.futures.as_completed([pool.submit(transfer, t) for t in tasks]):
            print(json.dumps(future.result()), flush=True)


if __name__ == "__main__":
    main()
