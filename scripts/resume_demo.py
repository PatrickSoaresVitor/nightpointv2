"""Recover an owned interrupted bootstrap without discarding its volume or bypassing attestation."""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from uuid import UUID

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'infra'))
from private_files import verify_private

def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-id',required=True)
    args=parser.parse_args();run_id=UUID(hex=args.run_id).hex
    if run_id!=args.run_id or not (ROOT/'ACADEMIC-PROVENANCE.json').is_file():raise ValueError('Academic marker and exact run ID required')
    project='nightpoint-foundation-audit-'+run_id[:12]
    folder=ROOT/'.artifacts/block03_1'/run_id;private=ROOT/'infra/local/test-runs'/run_id
    initial=json.loads((folder/'preparation.json').read_text())
    if initial['run_id']!=run_id or initial['project']!=project or (folder/'demo-state.json').exists():
        raise ValueError('Only the explicitly interrupted incomplete run may be resumed')
    if initial['attested'] is not False and not (folder/'preparation-initial.json').is_file():
        raise ValueError('Interrupted bootstrap provenance required for attested-stage recovery')
    def command(argv: list[str], capture: bool=True) -> str:
        result=subprocess.run(argv,cwd=ROOT,env=env,capture_output=capture,text=True,check=True,timeout=600)
        return result.stdout if capture else ''
    env=dict(os.environ)
    for name in ['admin_password','runtime_password','migrator_password','test_token','run.json','receipt.json']:
        verify_private(private/name)
    owner=json.loads((private/'run.json').read_text())
    if owner['project']!=project or Path(owner['directory']).resolve()!=private.resolve():raise ValueError('Private run ownership mismatch')
    metadata=json.loads(command(['docker','inspect',project+'-db-1']))[0]
    volumes=[m for m in metadata['Mounts'] if m['Type']=='volume']
    if metadata['Config']['Labels'].get('com.docker.compose.project')!=project or len(volumes)!=1 or volumes[0]['Name']!=project+'_pgdata':
        raise ValueError('Existing container or volume provenance mismatch')
    volume=json.loads(command(['docker','volume','inspect',volumes[0]['Name']]))[0]
    if volume['Labels'].get('com.docker.compose.project')!=project:raise ValueError('Volume owner mismatch')
    network=json.loads(command(['docker','network','inspect',project+'_data']))[0]
    data_subnet=network['IPAM']['Config'][0]['Subnet']
    all_ids=command(['docker','network','ls','-q']).split()
    all_networks=json.loads(command(['docker','network','inspect',*all_ids]))
    occupied=[ipaddress.ip_network(c['Subnet']) for n in all_networks for c in n['IPAM'].get('Config') or [] if c.get('Subnet')]
    client=next(n for n in ipaddress.ip_network('10.254.0.0/16').subnets(new_prefix=28) if not any(n.overlaps(other) for other in occupied if other.version==4))
    with socket.socket() as listener:listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    env.update(NP_TEST_RUN_DIR=str(private),NP_TEST_API_PORT=str(port),NP_TEST_DATA_SUBNET=data_subnet,
               NP_TEST_CLIENT_SUBNET=str(client),NP_TEST_ARTIFACT_DIR=str(folder),NP_DEMO_WEB_ORIGIN='http://127.0.0.1:5174')
    compose=['docker','compose','-p',project,'-f',str(ROOT/'infra/compose.test.yaml'),'-f',str(ROOT/'infra/compose.demo.yaml')]
    if command(['git','status','--porcelain','--','backend','infra','scripts']).strip():raise RuntimeError('Commit recovery code before startup')
    commit=command(['git','rev-parse','HEAD']).strip();retained=False
    try:
        # Same startup budget; this resumes the existing cluster, not a fresh retry.
        command(compose+['up','-d','--wait','--wait-timeout','180','db'],False)
        proof=command(compose+['exec','-T','db','psql','-U','np_admin','-d','nightpoint_test','-Atc',
                      "SELECT system_identifier||'|'||database_oid||'|'||token_hash FROM test_guard.identity_proof()"])
        identifier,oid,digest=proof.strip().split('|')
        if digest!=hashlib.sha256((private/'test_token').read_bytes()).hexdigest():raise ValueError('Bootstrap attestation mismatch')
        complete=command(compose+['exec','-T','db','psql','-U','np_admin','-d','nightpoint_test','-Atc','SELECT test_guard.bootstrap_complete()']).strip()
        if complete!='t':raise ValueError('Bootstrap did not complete; no manual marker or schema repair permitted')
        (private/'receipt.json').write_text(json.dumps({'environment':'disposable-test','system_identifier':identifier,'database_oid':int(oid),'token_hash':digest}),encoding='utf-8')
        if not (folder/'preparation-initial.json').exists():
            (folder/'preparation-initial.json').write_text(json.dumps(initial),encoding='utf-8')
        (folder/'preparation.json').write_text(json.dumps({**initial,'stage':'attested','attested':True,'resumed_commit':commit}),encoding='utf-8')
        command(compose+['up','--build','-d','--wait','--wait-timeout','180','api'],False)
        api=json.loads(command(['docker','inspect',project+'-api-1']))[0]
        db=json.loads(command(['docker','inspect',project+'-db-1']))[0]
        bindings=api['HostConfig']['PortBindings']
        if set(bindings)!={'8000/tcp'} or len(bindings['8000/tcp'])!=1 or bindings['8000/tcp'][0]['HostIp']!='127.0.0.1' or db['HostConfig']['PortBindings']:
            raise ValueError('Loopback API/unpublished database isolation required')
        state={'mode':'synthetic','project':project,'run_id':run_id,'commit':commit,'api_url':f'http://127.0.0.1:{port}',
               'web_origin':'http://127.0.0.1:5174','initial_state':'ready-attested','recovered_existing_volume':True,
               'stop_command':f'python infra/stop_demo.py {run_id}'}
        (folder/'demo-state.json').write_text(json.dumps(state,indent=2)+'\n',encoding='utf-8')
        (folder/'source.json').write_text(json.dumps({'commit':commit,'project':project,'run_id':run_id,'api_image_id':api['Image'],'db_image_id':db['Image'],
                         'loopback_port':port,'resume_initial_commit':initial['commit'],'existing_volume_preserved':True}),encoding='utf-8')
        target=ROOT/'.artifacts/academic/current-demo.json';target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(state,indent=2)+'\n',encoding='utf-8');retained=True
        command([sys.executable,str(ROOT/'infra/seed_demo.py'),'--run-id',run_id],False)
        print('Recovered owned academic demo: '+json.dumps(state))
    finally:
        if not retained:command(compose+['stop'],False)

if __name__=='__main__':main()
