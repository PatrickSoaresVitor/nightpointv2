"""Reuse a completed academic image only when runtime files and pinned versions match."""
import hashlib
import json
from pathlib import Path
import re
from processes import bounded_run

IMAGE='nightpoint-academic-api:local'

def verified_image(root: Path) -> dict[str,object] | None:
    inspect=bounded_run(['docker','image','inspect',IMAGE],cwd=root,capture_output=True,check=False,timeout=60)
    if inspect.returncode:return None
    info=json.loads(inspect.stdout)[0]
    if info['Config'].get('User')!='10001:10001':return None
    backend=root/'backend'
    files=[p for name in ['app','migrations','tests','tools','typings'] for p in (backend/name).rglob('*')
           if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    files += [backend/name for name in ['requirements.lock','pyproject.toml','alembic.ini']]
    expected={p.relative_to(backend).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    pins=dict(re.findall(r'^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==([^\s;]+)',(backend/'requirements.lock').read_text(),re.M))
    program="""import hashlib,json,sys
from pathlib import Path
from importlib.metadata import version
data=json.loads(sys.argv[1])
print(json.dumps({'files':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in data['files']},
                  'versions':{name:version(name) for name in data['pins']}}))
"""
    result=bounded_run(['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL',
        '--security-opt','no-new-privileges:true','--entrypoint','python',IMAGE,'-c',program,
        json.dumps({'files':list(expected),'pins':list(pins)})],cwd=root,capture_output=True,check=False,timeout=60)
    if result.returncode:return None
    observed=json.loads(result.stdout)
    if observed['files']!=expected or observed['versions']!=pins:return None
    proof={'image_id':info['Id'],'runtime_files_match':len(expected),'pinned_versions_match':len(pins),
           'nonroot_user':'10001:10001','probe':'read-only container, no network; no database access'}
    target=root/'.artifacts/academic/verified-image.json';target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')
    return proof
