"""Start/reuse only this repository's isolated, attested academic demo."""
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
state_path = ROOT / '.artifacts/academic/current-demo.json'

def main() -> None:
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding='utf-8'))
        try:
            with urlopen(state['api_url'] + '/api/v1/health/ready', timeout=10) as response:
                assert response.status == 200
        except Exception:
            raise SystemExit('Retained demo is unavailable. Inspect its containers/receipt; do not recreate or discard it blindly.') from None
        print('Reusing this academic demo: ' + json.dumps(state))
        return
    previous = set((ROOT / '.artifacts/block03_1').glob('*/demo-state.json'))
    env = dict(os.environ, NP_DEMO_WEB_ORIGIN='http://127.0.0.1:5174')
    subprocess.run([sys.executable, str(ROOT/'infra/test_environment.py'), '--demo'], cwd=ROOT, env=env, check=True)
    created = set((ROOT / '.artifacts/block03_1').glob('*/demo-state.json')) - previous
    if len(created) != 1: raise RuntimeError('Expected exactly one new attested demo')
    state = json.loads(created.pop().read_text(encoding='utf-8'))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2)+'\n', encoding='utf-8')
    subprocess.run([sys.executable, str(ROOT/'infra/seed_demo.py'), '--run-id', state['run_id']], cwd=ROOT, check=True)
    print('Academic demo ready: ' + json.dumps(state))

if __name__ == '__main__': main()
