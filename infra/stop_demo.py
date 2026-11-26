"""Stop one recorded owned synthetic demo, retaining its volume and proof."""
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def stop(run_id: str) -> None:
    if re.fullmatch('[0-9a-f]{32}',run_id) is None:raise ValueError('Expected a recorded demo run ID')
    project='nightpoint-foundation-audit-'+run_id[:12]
    artifacts=ROOT/'.artifacts/block03_1'/run_id
    state=json.loads((artifacts/'demo-state.json').read_text(encoding='utf-8'))
    source=json.loads((artifacts/'source.json').read_text(encoding='utf-8'))
    if state.get('project')!=project or state.get('mode')!='synthetic' or source.get('project')!=project:
        raise ValueError('Synthetic demo provenance mismatch')
    port=int(source['loopback_port'])
    if not 1<=port<=65535:raise ValueError('Invalid recorded port')
    subnets=[str(ipaddress.ip_network(source[key])) for key in ('data_subnet','client_subnet')]
    environment=dict(os.environ,NP_TEST_RUN_DIR=str(ROOT/'infra/local/test-runs'/run_id),
        NP_TEST_ARTIFACT_DIR=str(artifacts),NP_TEST_API_PORT=str(port),
        NP_TEST_DATA_SUBNET=subnets[0],NP_TEST_CLIENT_SUBNET=subnets[1])
    subprocess.run(['docker','compose','-p',project,'-f',str(ROOT/'infra/compose.test.yaml'),
        '-f',str(ROOT/'infra/compose.demo.yaml'),'stop'],env=environment,cwd=ROOT,check=True,timeout=120)
    (artifacts/'demo-closure.json').write_text(json.dumps({'project':project,'state':'stopped','volume_retained':True}),encoding='utf-8')
    print('Stopped only '+project+'; volume and proof retained')


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: python infra/stop_demo.py RUN_ID')
    stop(sys.argv[1])
