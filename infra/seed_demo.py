"""Seed only a marked, independently attested academic demo through its API."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import UUID, uuid5

ROOT = Path(__file__).resolve().parents[1]


def environment(run_id: str) -> tuple[str, Path]:
    if not (ROOT / 'ACADEMIC-PROVENANCE.json').is_file():
        raise RuntimeError('Academic package marker required; never seed the main environment')
    if len(run_id) != 32 or UUID(hex=run_id).hex != run_id:
        raise ValueError('Explicit demo run ID required')
    folder = ROOT / '.artifacts/block03_1' / run_id
    state = json.loads((folder / 'demo-state.json').read_text(encoding='utf-8'))
    proof = json.loads((folder / 'preparation.json').read_text(encoding='utf-8'))
    if state['run_id'] != run_id or state['mode'] != 'synthetic' or proof['attested'] is not True:
        raise ValueError('Attested synthetic demo required')
    base = state['api_url']
    parsed = urlsplit(base)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.username or parsed.password or parsed.path:
        raise ValueError('Loopback API required')
    return str(base), folder


def request(base: str, method: str, path: str, token: str | None = None,
            body: Any = None, headers: dict[str, str] | None = None) -> Any:
    if not path.startswith('/api/v1/') or '..' in path:
        raise ValueError('API path required')
    fields = {'Accept': 'application/json', **(headers or {})}
    if token: fields['Authorization'] = 'Bearer ' + token
    data = None if body is None else json.dumps(body).encode('utf-8')
    if data is not None: fields['Content-Type'] = 'application/json'
    with urlopen(Request(base + path, data=data, headers=fields, method=method), timeout=10) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    base, folder = environment(args.run_id)
    receipt = folder / 'academic-seed.json'
    if receipt.exists():
        print('Academic seed already recorded; retained without rewriting data')
        return
    assert request(base, 'GET', '/api/v1/health/ready')['status'] == 'ok'
    tokens: list[str] = []
    events: list[dict[str, Any]] = []
    try:
        for persona, nickname in [('participant-a', 'Organizador Demo'), ('participant-b', 'Piloto Demo')]:
            token = str(request(base, 'POST', '/api/v1/demo/session', body={'persona': persona})['access_token'])
            tokens.append(token)
            try:
                profile = request(base, 'GET', '/api/v1/me/profile', token)
                if profile['nickname'] != nickname:
                    raise RuntimeError('Existing unrelated profile; seed refused')
            except HTTPError as failure:
                if failure.code not in (404, 409): raise
                request(base, 'PUT', '/api/v1/me/profile', token, {'nickname': nickname, 'avatar_style': 'np-car'})
        for i, (title, category) in enumerate([
            ('Encontro Street', 'street'), ('Cars & Coffee', 'premium'), ('Encontro JDM', 'jdm')]):
            # Stable body across recovery attempts, tied to the demo start date.
            day = datetime.fromtimestamp((folder / 'demo-state.json').stat().st_mtime, timezone.utc).replace(hour=18, minute=0, second=0, microsecond=0)
            body = {'title': title, 'category_code': category, 'starts_at': (day + timedelta(days=i+1)).isoformat(),
                    'timezone': 'UTC', 'location_label': 'Ponto fictício de demonstração — Franca',
                    'longitude': -47.4009 + i*.004, 'latitude': -20.5386 + i*.004,
                    'description': 'Encontro exclusivamente fictício para o protótipo acadêmico. Não é um evento real.', 'visibility': 'listed'}
            saved = request(base, 'POST', '/api/v1/events', tokens[0], body,
                            {'Idempotency-Key': str(uuid5(UUID(hex=args.run_id), 'academic-event-'+str(i)))})
            events.append({'id': saved['id'], 'title': saved['title']})
        for i, (brand, model) in enumerate([('BMW', '320i'), ('Nissan', '350Z')]):
            request(base, 'POST', '/api/v1/me/vehicles', tokens[0],
                    {'brand': brand, 'model': model, 'year': 2020, 'color': 'Prata', 'category': 'car', 'primary': i == 0},
                    {'Idempotency-Key': str(uuid5(UUID(hex=args.run_id), 'academic-vehicle-'+str(i)))})
        request(base, 'POST', '/api/v1/me/vehicles', tokens[1],
                {'brand': 'Volkswagen', 'model': 'Golf GTI', 'year': 2021, 'category': 'car', 'primary': True},
                {'Idempotency-Key': str(uuid5(UUID(hex=args.run_id), 'academic-vehicle-b'))})
        receipt.write_text(json.dumps({'run_id': args.run_id, 'users': ['Organizador Demo', 'Piloto Demo'],
                                      'events': events, 'vehicles': 3, 'scope': 'fictional; API only; no real addresses'}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print('Academic seed completed: 2 fictional profiles, 3 events and 3 private vehicles')
    finally:
        for token in tokens:
            try: request(base, 'POST', '/api/v1/demo/logout', token)
            except Exception: pass  # Nonces also expire; never print token/body.


if __name__ == '__main__': main()
