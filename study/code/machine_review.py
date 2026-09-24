"""Official DeepSeek Pro audit, explicitly separate from human annotations."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from api import digest, dump, parse_reference
import prompts


def review_messages(task, review):
    messages = prompts.reference(task, review)
    messages[0]['content'] += ' The evidence value must be a nonempty string briefly explaining C, A and M. Do not add model identity or speculate about author intent.'
    return messages


def preflight(study):
    root = study.root
    record = json.loads((root/'runs/calibration_pilot.json').read_text())[0]
    data = study.dataset('python_development')
    task = next(t for t in data['tasks'] if t['task_id'] == record['task_id'])
    result = study.invoke('official-pro-preflight/v1', 'development', 'official_pro',
                          review_messages(task, record['review']), parser=parse_reference, tokens=8192)
    if result['status'] != 'ok':
        raise RuntimeError('official DeepSeek Pro preflight failed')
    pins = json.loads((root/'protocol/model_versions.json').read_text())
    actual = result['raw_response']['model']
    if 'official_pro' in pins and pins['official_pro'] != actual:
        raise RuntimeError('official model version changed')
    pins['official_pro'] = actual
    dump(root/'protocol/model_versions.json', pins)
    dump(root/'runs/official_pro_preflight.json', {'status': 'ok', 'call_id': result['id'],
                                                'returned_model': actual, 'annotator_type': 'model'})


def evaluate(study, stage):
    root = study.root
    policy = json.loads((root/'protocol/review_policy.json').read_text())
    if policy['mode'] != 'official_pro_then_author_review':
        raise RuntimeError('official model audit not authorized by current protocol')
    if stage == 'calibration':
        records = json.loads((root/'runs/calibration.json').read_text())
        if len(records) != 20:
            raise RuntimeError('twenty calibration records required')
        tasks = {t['task_id']: t for t in study.dataset('python_development')['tasks']}
        selected = [{'key': r['key'], 'inclusion_probability': 1} for r in records]
        phase = 'development'
    else:
        records = []
        selected = json.loads((root/'protocol/human_sampling.json').read_text())['selected']
        for item in selected:
            p = root/'runs/records'/(digest(item['key'])+'.json')
            records.append(json.loads(p.read_text()) if p.exists() else {'key': item['key']})
        tasks = {t['task_id']: t for name in ('python_formal', 'java_formal') for t in study.dataset(name)['tasks']}
        phase = 'formal'
    if 'official_pro' not in json.loads((root/'protocol/model_versions.json').read_text()):
        raise RuntimeError('official Pro version must be pinned before audit')
    recordmap = {r['key']: r for r in records}
    jobs = [(item, rep) for item in selected for rep in (1, 2)]

    def one(job):
        item, rep = job
        record = recordmap[item['key']]
        out = {'key': item['key'], 'pass': rep, 'annotator_type': 'model',
               'inclusion_probability': item['inclusion_probability']}
        if not record.get('review'):
            return {**out, 'status': 'review_unavailable', 'label': None}
        task = tasks[record['task_id']]
        call = study.invoke(f"official_pro/{stage}/{item['key']}/pass{rep}", phase, 'official_pro',
                            review_messages(task, record['review']), parser=parse_reference, tokens=8192)
        out.update(status=call['status'], label=call.get('parsed') if call['status'] == 'ok' else None,
                   call_id=call['id'], returned_model=call.get('raw_response', {}).get('model'))
        dump(root/'machine_review'/stage/'raw_labels'/(digest([item['key'], rep])+'.json'), out)
        return out

    results = []
    with ThreadPoolExecutor(max_workers=study.workers) as pool:
        for start in range(0, len(jobs), study.workers):
            results.extend(pool.map(one, jobs[start:start+study.workers]))
            dump(root/'machine_review'/stage/'progress.json', {'processed': len(results), 'planned': len(jobs)})
    comparisons = []
    indexed = {(r['key'], r['pass']): r for r in results}
    for item in selected:
        record = recordmap[item['key']]
        flash = (record.get('reference') or {}).get('y')
        pro = [(indexed[item['key'], rep].get('label') or {}).get('y') for rep in (1, 2)]
        if None in (flash, *pro) or len(set((flash, *pro))) != 1:
            comparisons.append({'key': item['key'], 'flash_y': flash, 'pro_y': pro})
    out = {'annotator_type': 'model', 'provider': 'DeepSeek official', 'passes': 2,
           'status': 'complete' if all(r['status'] == 'ok' for r in results) else 'completed_with_missing',
           'source_records_sha256': digest(records), 'policy_sha256': digest(policy),
           'annotations': results, 'disagreements_or_unknown': comparisons,
           'note': 'Two separate requests to one model; not two independent human reviewers. Author review remains pending.'}
    dump(root/'machine_review'/stage/'results.json', out)
    if stage == 'formal':
        study.export_formal_human()
        folder = root/'author_review/formal'
        batch = json.loads((root/'human/formal/active_batch.json').read_text())['batch']
        template = json.loads((root/f'human/formal/reviewer_1_template_{batch}.json').read_text())
        template.update(annotator_type='human', review_mode='post_experiment_author_check',
                        independent_annotation=False, review_completed=False)
        for item in template['records']:
            item['checked'] = False
        target = folder/'author_labels_template.json'
        if not target.exists():
            dump(target, template)
        dump(folder/'machine_audit.json', out)
        (folder/'README.md').write_text('作者实验后校对：填写实际检查的条目，checked=true，并填写 C/A/M 与依据。保留机器原始标签；完成后另存 author_labels.json，填写 reviewer_id、consent 和 review_completed。只报告实际校对范围，不将作者校对称为两位独立人工评价。\n')
    return out


def validate_calibration(root, records):
    root = Path(root)
    policy = json.loads((root/'protocol/review_policy.json').read_text())
    audit = json.loads((root/'machine_review/calibration/results.json').read_text())
    if (audit.get('annotator_type') != 'model' or audit.get('status') != 'complete'
            or audit['source_records_sha256'] != digest(records)
            or audit['policy_sha256'] != digest(policy)):
        raise RuntimeError('model calibration audit incomplete or stale')
    expected = {(r['key'], rep) for r in records for rep in (1, 2)}
    actual = {(a['key'], a['pass']) for a in audit['annotations']}
    if actual != expected or len(audit['annotations']) != len(expected):
        raise RuntimeError('model calibration audit coverage mismatch')
    for annotation in audit['annotations']:
        if annotation.get('annotator_type') != 'model' or annotation['status'] != 'ok':
            raise RuntimeError('invalid model audit provenance')
        parse_reference(json.dumps(annotation['label']))
    return {'type': 'official_model_audit', 'sha256': digest(audit),
            'author_review': 'pending_after_experiment',
            'disagreements_or_unknown': len(audit['disagreements_or_unknown'])}


def main():
    from workflow import Study
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--stage', choices=('preflight', 'calibration', 'formal'), required=True)
    parser.add_argument('--workers', type=int, default=6)
    args = parser.parse_args()
    study = Study(args.root, args.workers)
    if args.stage == 'preflight':
        preflight(study)
    else:
        evaluate(study, args.stage)


if __name__ == '__main__':
    main()
