"""Verify, reconstruct and recompute the paper's experiment without API calls.

Python 3.11+ and the pinned requirements are needed for statistical recomputation.
Extraction/hash verification uses only the standard library.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile

HERE=Path(__file__).resolve().parent

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def compare(left,right,path='root'):
    # Metadata about subsequent human confirmation is not a numerical result.
    if isinstance(left,dict):
        assert isinstance(right,dict),path
        for key,value in left.items():compare(value,right[key],path+'/'+key)
    elif isinstance(left,list):
        assert len(left)==len(right),path
        for i,(a,b) in enumerate(zip(left,right)):compare(a,b,path+'/'+str(i))
    elif isinstance(left,(float,int)) and not isinstance(left,bool):
        assert abs(left-right)<=1e-11,path
    else:assert left==right,path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True,help='New or previously extracted local workspace')
    parser.add_argument('--include-raw',action='store_true',help='Also extract all API response archives')
    parser.add_argument('--extract-only',action='store_true')
    args=parser.parse_args()
    destination=args.output.resolve()
    destination.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((HERE/'artifacts/manifest.json').read_text())
    expected={f['path']:f for f in manifest['files']}
    extracted=0
    for archive in manifest['archives']:
        path=HERE/'artifacts'/archive['file']
        assert sha(path)==archive['sha256'],'Archive hash mismatch: '+archive['file']
        if not args.include_raw and archive['file'].startswith('api-records-'):continue
        with tarfile.open(path,'r:gz') as tf:
            for item in tf:
                relative=PurePosixPath(item.name)
                if not item.isfile() or relative.is_absolute() or '..' in relative.parts:
                    raise ValueError('Unsafe archive member: '+item.name)
                data=tf.extractfile(item).read()
                assert hashlib.sha256(data).hexdigest()==expected[item.name]['sha256'],item.name
                target=destination.joinpath(*relative.parts)
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists() and target.read_bytes()!=data:
                    raise ValueError('Refusing to overwrite modified file: '+str(target))
                target.write_bytes(data);extracted+=1
    print('Verified and extracted',extracted,'files',flush=True)
    view=destination/'supplement/20260924_audit_gaps/analysis_view_adopted_pro'
    for name in ('data','protocol'):
        target=view/name
        if not target.exists():shutil.copytree(destination/name,target)
    marker=view/'runs/formal_calls_finished.json'
    if not marker.exists():shutil.copy2(destination/'runs/formal_calls_finished.json',marker)
    if args.extract_only:return
    # Recompute in a separate analysis view; archived summaries remain unchanged.
    analysis_view=destination/'recomputed_adjudicated'
    analysis_view.mkdir(exist_ok=True)
    for name in ('data','protocol','runs','machine_review'):
        target=analysis_view/name
        if not target.exists():shutil.copytree(view/name,target)
    subprocess.run([sys.executable,str(destination/'code/analyze.py'),'--root',str(analysis_view)],check=True)
    saved=json.loads((view/'analysis/results.json').read_text())
    actual=json.loads((analysis_view/'analysis/results.json').read_text())
    compare(saved['automatic_reference']['groups'],actual['automatic_reference']['groups'])
    compare(saved['automatic_reference']['paired_tests'],actual['automatic_reference']['paired_tests'])
    compare(saved['official_pro_audit']['results'],actual['official_pro_audit']['results'])
    compare(saved['official_pro_audit']['repeated_request_agreement'],actual['official_pro_audit']['repeated_request_agreement'])
    final=json.loads((view/'protocol/final_rubrics.json').read_text())
    sys.path.insert(0,str(destination/'code'))
    import prompts
    assert len(final)==6 and all(r==prompts.RUBRIC for r in final.values())
    print('PASS: all group estimates, intervals, 38 paired tests, two Pro passes and D4 identities match saved results.')
    print('Human confirmation is documented separately in publication_state.json; no synthetic annotations are created.')

if __name__=='__main__':main()
