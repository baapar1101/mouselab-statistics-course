"""Execute in an unprivileged disposable runner; validate saved results without exec."""
from pathlib import Path
import argparse
import base64
import hashlib
import io
import json
import os
import re
import sys
import time
from copy import deepcopy

NAME = 'MouseLab_Complete_81_Colab.ipynb'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def sources(book):
    return [(c['cell_type'], c.get('id'), c['source'], c.get('metadata',{}).get('mouselab')) for c in book.cells]

def check(book, contract, executed=False):
    import nbformat
    nbformat.validate(book)
    lessons=[c for c in book.cells if c.metadata.get('mouselab',{}).get('role')=='lesson']
    analyses=[c for c in book.cells if c.metadata.get('mouselab',{}).get('role')=='analysis']
    assert [c.metadata.mouselab.id for c in lessons]==contract['lesson_ids'], 'Lesson IDs/order changed; update site contract first.'
    assert [c.metadata.mouselab.lesson for c in lessons]==list(range(1,82)), 'Invalid numbering'
    assert [c.metadata.mouselab.id for c in analyses]==contract['lesson_ids'], 'Analysis coverage mismatch'
    assert len([c for c in book.cells if c.metadata.get('mouselab',{}).get('role')=='interpretation-and-exercise'])==81, 'Exercise lost'
    validations=[c for c in book.cells if 'validation' in c.metadata.get('tags',[])]
    assert [sha(c.source.encode()) for c in validations]==contract['validation_sha256'], 'Reference assertions removed/changed; review contract deliberately.'
    if not executed:
        return
    from PIL import Image, ImageStat
    code=[c for c in book.cells if c.cell_type=='code']
    assert len(code)>=86 and [c.execution_count for c in code]==list(range(1,len(code)+1)), 'Not all code executed in order'
    images=[]
    for cell in code:
        for output in cell.outputs:
            assert output.output_type!='error', 'Saved Python error'
            assert not (output.get('name')=='stderr' and output.get('text','').strip()), 'stderr/warning output'
            assert 'Traceback (most recent call last)' not in output.get('text',''), 'Traceback in text'
    for cell in analyses:
        key=cell.metadata.mouselab.id
        interpretations=[o.data['text/markdown'] for o in cell.outputs if 'text/markdown' in o.get('data',{})]
        assert interpretations and all(len(t.strip())>=40 for t in interpretations), f'{key}: missing interpretation'
        encoded=[o.data['image/png'] for o in cell.outputs if 'image/png' in o.get('data',{})]
        assert len(encoded)>=contract['minimum_figures'][key], f'{key}: missing figure'
        for value in encoded:
            raw=base64.b64decode(value,validate=False)
            assert len(raw)<8_000_000, f'{key}: oversized image'
            image=Image.open(io.BytesIO(raw)); image.load()
            assert image.format=='PNG' and image.width>=320 and image.height>=200, f'{key}: invalid plot dimensions'
            assert max(ImageStat.Stat(image.convert('RGB')).stddev)>1, f'{key}: blank plot'
            images.append({'lesson':key,'sha256':sha(raw),'width':image.width,'height':image.height})
    assert len(images)>=85, 'Missing course charts'
    return {'lessons':len(lessons),'executed_cells':len(code),'figures':len(images),'interpretations':len(analyses),
            'reference_check_cells':len(validations),'errors':[],'warnings':[],'image_checks':images}

def main():
    import nbformat
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',default=NAME); parser.add_argument('--output-dir',default='release')
    parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    contract=json.loads((root/'contract.json').read_text())
    book=nbformat.read(args.input,as_version=4); check(book,contract)
    original=deepcopy(book); started=time.monotonic()
    output=Path(args.output_dir); output.mkdir(parents=True,exist_ok=True)
    if not args.check_only:
        from nbclient import NotebookClient
        from jupyter_client import KernelManager
        for cell in book.cells:
            if cell.cell_type=='code': cell.outputs=[]; cell.execution_count=None
        if os.environ.get('EXERCISE_FAILURE_GATE')=='true':
            # Manual disaster-recovery drill: never modifies the authored notebook.
            book.cells[1].source='raise RuntimeError("Intentional CI failure-gate drill")\n'+book.cells[1].source
        km=KernelManager(kernel_name='python3')
        km.kernel_spec.argv=[sys.executable,'-m','ipykernel_launcher','-f','{connection_file}']
        try:
            NotebookClient(book,km=km,timeout=300,allow_errors=False,resources={'metadata':{'path':str(Path.cwd())}}).execute()
        except Exception:
            nbformat.write(book,output/'failed-notebook.ipynb')
            raise
    assert sources(book)==sources(original), 'Execution changed teaching text, examples or code'
    result=check(book,contract,executed=True)
    raw=nbformat.writes(book).encode('utf-8')
    (output/NAME).write_bytes(raw)
    result.update(schema=1,status='passed',source_commit=os.environ.get('GITHUB_SHA','local'),
                  workflow_run=os.environ.get('GITHUB_RUN_ID','local'),notebook_sha256=sha(raw),
                  input_sha256=sha(Path(args.input).read_bytes()),duration_seconds=round(time.monotonic()-started,2),
                  environment={p:__import__('importlib.metadata',fromlist=['version']).version(p) for p in ['numpy','pandas','scipy','matplotlib','statsmodels','scikit-learn','nbclient']},
                  limits='Automated runtime, reference assertions, coverage and PNG integrity checks; not a human review of new scientific claims.')
    (output/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ['image_checks','environment']},ensure_ascii=False))

if __name__=='__main__': main()
