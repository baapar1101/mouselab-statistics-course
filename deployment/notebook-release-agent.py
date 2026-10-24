"""Pull only completed successful GitHub releases. Never execute notebook code."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import time
import urllib.request

REPO='baapar1101/mouselab-statistics-course'
RAW='https://raw.githubusercontent.com/'+REPO+'/'
NAME='MouseLab_Complete_81_Colab.ipynb'

def fetch(url,limit=12_000_000):
    request=urllib.request.Request(url,headers={'User-Agent':'MouseLab-verified-release','Cache-Control':'no-cache'})
    with urllib.request.urlopen(request,timeout=30) as response:
        data=response.read(limit+1)
    if len(data)>limit: raise ValueError('Release resource too large')
    return data

def digest(raw): return hashlib.sha256(raw).hexdigest()
def joined(value): return ''.join(value) if isinstance(value,list) else str(value or '')

def verify(raw,manifest,report,contract):
    assert manifest['schema']==1 and manifest['status']=='passed' and manifest['filename']==NAME
    assert re.fullmatch('[0-9a-f]{40}',manifest['source_commit'])
    assert str(manifest['workflow_run']).isdigit()
    assert digest(raw)==manifest['sha256']==report['notebook_sha256'], 'Notebook checksum mismatch'
    assert report['status']=='passed' and report['errors']==[] and report['warnings']==[]
    assert report['source_commit']==manifest['source_commit'] and report['workflow_run']==manifest['workflow_run']
    book=json.loads(raw)
    lessons=[c for c in book['cells'] if c.get('metadata',{}).get('mouselab',{}).get('role')=='lesson']
    analyses=[c for c in book['cells'] if c.get('metadata',{}).get('mouselab',{}).get('role')=='analysis']
    assert [c['metadata']['mouselab']['id'] for c in lessons]==contract['lesson_ids']
    assert [c['metadata']['mouselab']['lesson'] for c in lessons]==list(range(1,82))
    assert [c['metadata']['mouselab']['id'] for c in analyses]==contract['lesson_ids']
    exercises=[c for c in book['cells'] if c.get('metadata',{}).get('mouselab',{}).get('role')=='interpretation-and-exercise']
    assert len(exercises)==81
    validations=[c for c in book['cells'] if 'validation' in c.get('metadata',{}).get('tags',[])]
    assert [digest(joined(c['source']).encode()) for c in validations]==contract['validation_sha256']
    codes=[c for c in book['cells'] if c['cell_type']=='code']
    assert len(codes)>=86 and [c['execution_count'] for c in codes]==list(range(1,len(codes)+1))
    figures=0
    for cell in codes:
        for output in cell['outputs']:
            assert output['output_type']!='error'
            assert not (output.get('name')=='stderr' and joined(output.get('text')).strip())
    for cell in analyses:
        key=cell['metadata']['mouselab']['id']
        assert any(len(joined(o.get('data',{}).get('text/markdown')).strip())>=40 for o in cell['outputs'])
        images=[o['data']['image/png'] for o in cell['outputs'] if 'image/png' in o.get('data',{})]
        assert len(images)>=contract['minimum_figures'][key]
        for encoded in images:
            picture=base64.b64decode(joined(encoded)); assert picture[:8]==b'\x89PNG\r\n\x1a\n'
            width,height=struct.unpack('>II',picture[16:24]); assert width>=320 and height>=200
            figures+=1
    assert figures>=85 and figures==manifest['figures']==report['figures']
    assert len(codes)==manifest['executed_cells']==report['executed_cells']
    assert manifest['lessons']==report['lessons']==81
    return book

def atomic(path,data):
    fd,temp=tempfile.mkstemp(prefix='pending-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.chmod(temp,0o644)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp): os.unlink(temp)

def json_bytes(value): return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()

def normalized_outputs(cell):
    """Compare displayed values, not execution counters, timing or output metadata."""
    result=[]
    for output in cell.get('outputs',[]):
        if output['output_type']=='stream':
            item={'type':'stream','name':output.get('name'),'text':joined(output.get('text'))}
            if result and result[-1].get('type')=='stream' and result[-1]['name']==item['name']:
                result[-1]['text']+=item['text']; continue
        else:
            item={key:joined(value) for key,value in sorted(output.get('data',{}).items())}
        result.append(item)
    return result

def signatures(book):
    groups={}; shared=[]
    for cell in book['cells']:
        meta=cell.get('metadata',{}).get('mouselab',{}); key=meta.get('id')
        if not key:
            shared.append({'type':cell['cell_type'],'source':joined(cell['source']),'outputs':normalized_outputs(cell)}); continue
        group=groups.setdefault(key,{'code':[],'text':[],'outputs':[],'figures':[]})
        group['code' if cell['cell_type']=='code' else 'text'].append(joined(cell['source']))
        for output in normalized_outputs(cell):
            image=output.pop('image/png',None)
            if image is not None: group['figures'].append(digest(base64.b64decode(image)))
            if output: group['outputs'].append(output)
    return groups,shared

def compare_books(old,new):
    groups,shared=signatures(new)
    if old is None: return {'baseline':True,'lessons':[],'counts':{},'shared_changed':False,'metadata_only':False}
    before,prior_shared=signatures(old); changes=[]
    for key in dict.fromkeys([*before,*groups]):
        flags=[category for category in ['code','text','outputs','figures'] if before.get(key,{}).get(category)!=groups.get(key,{}).get(category)]
        if flags: changes.append({'id':key,'categories':flags})
    shared_changed=shared!=prior_shared
    return {'baseline':False,'lessons':changes,'counts':{category:sum(category in x['categories'] for x in changes) for category in ['code','text','outputs','figures']},
            'shared_changed':shared_changed,'metadata_only':not changes and not shared_changed}

def verify_workflow(manifest):
    run=json.loads(fetch('https://api.github.com/repos/'+REPO+'/actions/runs/'+str(manifest['workflow_run']),500_000))
    assert run['repository']['full_name']==REPO and run['head_branch']=='main'
    assert run['head_sha']==manifest['source_commit'] and run['path']=='.github/workflows/notebook-release.yml'
    assert run['event'] in ['push','workflow_dispatch']
    assert run['status']=='completed' and run['conclusion']=='success', 'Workflow not successfully completed'

def sync_history(root,resolved,contract):
    """Backfill reachable verified publications, including releases skipped by the timer.

    Persist progress after each complete version; never replace a healthy active pointer
    on a failed/partial backfill. Immutable files are written before their index entry.
    """
    path=root/'history.json'
    history=json.loads(path.read_text()) if path.exists() else {'schema':1,'head':None,'releases':[]}
    if history['head']==resolved: return history
    commits=[]; page=1; found=False
    while not found:
        batch=json.loads(fetch('https://api.github.com/repos/'+REPO+'/commits?sha='+resolved+'&per_page=100&page='+str(page),2_000_000))
        assert isinstance(batch,list) and batch
        for commit in batch:
            if commit['sha']==history['head']: found=True; break
            assert re.fullmatch('[0-9a-f]{40}',commit['sha'])
            commits.append(commit)
        if found or len(batch)<100: break
        page+=1
    assert not history['head'] or found, 'Published history diverged; preserving existing history and active release'
    previous=None
    if history['releases']:
        entry=history['releases'][0]
        previous_raw=(root/'releases'/entry['published_commit']/NAME).read_bytes()
        assert digest(previous_raw)==entry['sha256']
        previous=json.loads(previous_raw)
    for commit in reversed(commits):
        ref=commit['sha']; folder=root/'releases'/ref; folder.mkdir(parents=True,exist_ok=True)
        manifest=json.loads(fetch(RAW+ref+'/release.json',100_000)); verify_workflow(manifest)
        raw=(folder/NAME).read_bytes() if (folder/NAME).exists() else fetch(RAW+ref+'/'+NAME)
        report_raw=(folder/'validation.json').read_bytes() if (folder/'validation.json').exists() else fetch(RAW+ref+'/validation.json',500_000)
        book=verify(raw,manifest,json.loads(report_raw),contract)
        manifest.update(published_commit=ref,canonicalURL=RAW+ref+'/'+NAME,
                        localURL='notebook-live/releases/'+ref+'/'+NAME,
                        validationURL='notebook-live/releases/'+ref+'/validation.json',
                        released_at=commit['commit']['committer']['date'],previous_commit=history['head'])
        changes=compare_books(previous,book)
        changes.update(schema=1,from_commit=history['head'],to_commit=ref)
        atomic(folder/NAME,raw); atomic(folder/'validation.json',report_raw)
        atomic(folder/'release.json',json_bytes(manifest)); atomic(folder/'changes.json',json_bytes(changes))
        entry={**manifest,'changes':changes}
        history['releases'].insert(0,entry); history['head']=ref
        atomic(path,json_bytes(history)); previous=book
        print('Archived verified publication '+ref,flush=True)
    return history

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',default='/opt/mouselab-atlas/notebook-live')
    parser.add_argument('--contract',default='/usr/local/lib/mouselab-release/contract.json')
    args=parser.parse_args(); root=Path(args.root)
    # The systemd timer and a manual backfill must never interleave writers.
    import fcntl
    lock=(root/'.release.lock').open('a')
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        print('Another release sync is running.'); return
    contract=json.loads(Path(args.contract).read_text())
    current=root/'release.json'
    previous=json.loads(current.read_text()) if current.exists() else None
    resolved=subprocess.check_output(['git','ls-remote','https://github.com/'+REPO+'.git','refs/heads/published'],text=True,timeout=30).split()[0]
    assert re.fullmatch('[0-9a-f]{40}',resolved)
    history=sync_history(root,resolved,contract)
    if previous and previous.get('published_commit')==resolved:
        print('No new verified release.'); return
    manifest={key:value for key,value in history['releases'][0].items() if key!='changes'}
    release=root/'releases'/resolved
    raw=(release/NAME).read_bytes(); report_raw=(release/'validation.json').read_bytes(); report=json.loads(report_raw)
    verify(raw,manifest,report,contract)
    manifest.update(published_commit=resolved,canonicalURL=RAW+resolved+'/'+NAME,
                    localURL='notebook-live/releases/'+resolved+'/'+NAME,
                    validationURL='notebook-live/releases/'+resolved+'/validation.json',
                    deployed_at=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
    # Only the final pointer changes; every reader gets one immutable tested file.
    atomic(current,(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode())
    print('Activated verified release '+resolved+'; SHA-256 '+manifest['sha256'])

if __name__=='__main__': main()
