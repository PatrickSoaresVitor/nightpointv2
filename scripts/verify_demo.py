"""Small real-API checks for the academic spatial flow and private ownership."""
import argparse
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'infra'))
from seed_demo import environment,request

def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-id',required=True)
    args=parser.parse_args();base,folder=environment(args.run_id)
    seed=json.loads((folder/'academic-seed.json').read_text(encoding='utf-8'))
    tokens=[];result={'passed':False,'run_id':args.run_id,'checks':[]}
    try:
        assert request(base,'GET','/api/v1/health/ready')['status']=='ok'
        for persona in ['participant-a','participant-b']:
            tokens.append(request(base,'POST','/api/v1/demo/session',body={'persona':persona})['access_token'])
        start=datetime.now(timezone.utc)-timedelta(days=1)
        query={'longitude':-47.4009,'latitude':-20.5386,'radius_m':10000.0,'from_ts':start.isoformat(),
               'until_ts':(start+timedelta(days=7)).isoformat(),'limit':25}
        near=request(base,'POST','/api/v1/discovery/nearby',tokens[0],query)
        assert {item['id'] for item in near['items']} >= {item['id'] for item in seed['events']}
        far=request(base,'POST','/api/v1/discovery/nearby',tokens[0],{**query,'longitude':0.0,'latitude':0.0})
        assert not far['items']
        result['checks'].append({'spatial_near':len(near['items']),'spatial_far':0,'scope':'fictional test points only; real PostGIS via API'})
        a=request(base,'GET','/api/v1/me/vehicles',tokens[0]);b=request(base,'GET','/api/v1/me/vehicles',tokens[1])
        assert len(a['items'])==2 and len(b['items'])==1
        assert not ({x['id'] for x in a['items']} & {x['id'] for x in b['items']})
        try:request(base,'GET','/api/v1/me/vehicles/'+a['items'][0]['id'],tokens[1])
        except HTTPError as failure:assert failure.code==404
        else:raise AssertionError('Private vehicle exposed to another persona')
        result['checks'].append({'private_garages':'2 and 1 vehicles; disjoint','foreign_vehicle_http':404})
        result['passed']=True
        print('PASS: ready API/PostGIS, nearby=3 or more, remote region empty, private ownership enforced')
    finally:
        for token in tokens:
            try:request(base,'POST','/api/v1/demo/logout',token)
            except Exception:pass
        (folder/('academic-spatial-'+str(time.time_ns())+'.json')).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
