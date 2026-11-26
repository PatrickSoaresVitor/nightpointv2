"""Build the academic Web entry against this repository's active demo."""
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
state = json.loads((ROOT/'.artifacts/academic/current-demo.json').read_text(encoding='utf-8'))
flutter = shutil.which('flutter') or shutil.which('flutter.bat')
if not flutter: raise SystemExit('Flutter must be available on PATH; see README')
subprocess.run([flutter, 'build', 'web', '--no-pub', '--target', 'lib/main.dart',
                '--dart-define=NP_SYNTHETIC=true', '--dart-define=NP_API_URL='+state['api_url'],
                '--no-web-resources-cdn'], cwd=ROOT/'nightpoint', check=True)
print('Build ready. Serve with: python -m http.server 5174 --bind 127.0.0.1 --directory nightpoint/build/web')
