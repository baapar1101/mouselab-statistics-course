"""Promote data only, in a separate runner with no notebook execution."""
from pathlib import Path
import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
import nbformat
from validate_notebook import NAME, check, sources

REPO='baapar1101/mouselab-statistics-course'
def api(path,method='GET',data=None):
    request=urllib.request.Request('https://api.github.com/repos/'+REPO+'/'+path,method=method,
        data=None if data is None else json.dumps(data).encode(),
        headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json','User-Agent':'MouseLab-release'})
    with urllib.request.urlopen(request,timeout=30) as response: return json.load(response)

def main():
    source=os.environ['GITHUB_SHA']; assert re.fullmatch('[0-9a-f]{40}',source)
    if api('git/ref/heads/main')['object']['sha']!=source:
        print('Superseded by a newer main commit; not promoted.'); return
    root=Path(__file__).resolve().parent
    contract=json.loads((root/'contract.json').read_text())
    raw=(Path('release')/NAME).read_bytes(); book=nbformat.reads(raw.decode(),4)
    result=check(book,contract,executed=True)
    assert sources(book)==sources(nbformat.read(NAME,4)), 'Artifact sources differ from checked-out commit'
    report=json.loads(Path('release/validation.json').read_text())
    digest=hashlib.sha256(raw).hexdigest()
    assert report['status']=='passed' and report['source_commit']==source and report['workflow_run']==os.environ['GITHUB_RUN_ID']
    assert report['notebook_sha256']==digest and report['image_checks']==result['image_checks']
    manifest={'schema':1,'status':'passed','filename':NAME,'source_commit':source,
              'workflow_run':os.environ['GITHUB_RUN_ID'],'sha256':digest,
              'lessons':81,'figures':result['figures'],'executed_cells':result['executed_cells']}
    files={NAME:raw,'validation.json':Path('release/validation.json').read_bytes(),
           'release.json':json.dumps(manifest,ensure_ascii=False,indent=2).encode()}
    try: parent=api('git/ref/heads/published')['object']['sha']
    except urllib.error.HTTPError as error:
        if error.code!=404: raise
        parent=None
    tree=[]
    for name,data in files.items():
        blob=api('git/blobs','POST',{'encoding':'base64','content':base64.b64encode(data).decode()})
        tree.append({'path':name,'mode':'100644','type':'blob','sha':blob['sha']})
    tree_sha=api('git/trees','POST',{'tree':tree})['sha']
    commit=api('git/commits','POST',{'message':'Verified notebook from '+source,'tree':tree_sha,'parents':[parent] if parent else []})['sha']
    if api('git/ref/heads/main')['object']['sha']!=source:
        print('New source arrived before promotion; keeping previous published release.'); return
    if parent: api('git/refs/heads/published','PATCH',{'sha':commit,'force':False})
    else: api('git/refs','POST',{'ref':'refs/heads/published','sha':commit})
    print('Published verified notebook: '+commit)
    with open(os.environ.get('GITHUB_STEP_SUMMARY',os.devnull),'a',encoding='utf-8') as summary:
        summary.write(f'## Verified release\n81 lessons · {result["executed_cells"]} executed cells · {result["figures"]} PNGs\n\nSource: `{source}`\n\nPublished: `{commit}`\n\nSHA-256: `{digest}`\n\nServer pulls successful releases within about one minute.\n')

if __name__=='__main__': main()
