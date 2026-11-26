"""Two actual API sessions: SSE invalidation after commit and REST reconciliation."""
import argparse
import json
from pathlib import Path
from queue import Queue, Empty
import sys
from threading import Thread, Event
import time
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'infra'))
from seed_demo import environment, request

def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-id',required=True)
    args=parser.parse_args();base,folder=environment(args.run_id)
    seed=json.loads((folder/'academic-seed.json').read_text(encoding='utf-8'))
    event_id=seed['events'][0]['id'];path='/api/v1/events/'+event_id
    tokens=[];stop=Event();ready=Event();frames:Queue[dict]=Queue();errors:Queue[str]=Queue()
    for _ in range(2):tokens.append(request(base,'POST','/api/v1/demo/session',body={'persona':'participant-a'})['access_token'])
    original=request(base,'GET',path,tokens[1])
    def listen() -> None:
        try:
            with urlopen(Request(base+path+'/updates',headers={'Authorization':'Bearer '+tokens[0],'Accept':'text/event-stream'}),timeout=5) as response:
                assert response.headers.get_content_type()=='text/event-stream'
                frame={}
                while not stop.is_set():
                    line=response.readline().decode().strip()
                    if not line:
                        if 'data' in frame:
                            frames.put(frame);ready.set();frame={}
                    elif line.startswith('event:'):frame['event']=line[6:].strip()
                    elif line.startswith('data:'):frame['data']=json.loads(line[5:])
        except Exception as failure:
            if not stop.is_set():errors.put(type(failure).__name__)
    thread=Thread(target=listen,daemon=True);thread.start()
    changed=None;result={}
    try:
        assert ready.wait(10),'SSE initial frame not received'
        fields=['title','category_code','starts_at','timezone','location_label','longitude','latitude','description','visibility']
        body={key:original[key] for key in fields}
        body['title']='Encontro Street — atualização ao vivo'
        changed=request(base,'PUT',path,tokens[1],body,{'If-Match':'"'+str(original['version'])+'"'})
        deadline=time.monotonic()+10;matched=None
        while time.monotonic()<deadline:
            try:frame=frames.get(timeout=.5)
            except Empty:continue
            if frame.get('event')=='changed' and frame['data'].get('version',0)>=changed['version']:
                matched=frame;break
        assert matched is not None,'Committed version not observed through SSE'
        reconciled=request(base,'GET',path,tokens[0])
        assert reconciled['title']==body['title'] and reconciled['version']==changed['version']
        result={'passed':True,'sessions':2,'transport':'HTTP text/event-stream + REST','run_id':args.run_id,
                'event_id':event_id,'initial_version':original['version'],'committed_version':changed['version'],
                'notification_kind':matched['event'],'rest_reconciled':True,
                'limitations':'single API process; not a browser test, benchmark or hard real-time guarantee'}
        print('PASS: two API sessions, committed update -> SSE frame -> authorized REST reconciliation')
    finally:
        stop.set();thread.join(timeout=6)
        if changed:
            body={key:original[key] for key in ['title','category_code','starts_at','timezone','location_label','longitude','latitude','description','visibility']}
            request(base,'PUT',path,tokens[1],body,{'If-Match':'"'+str(changed['version'])+'"'})
        for token in tokens:
            try:request(base,'POST','/api/v1/demo/logout',token)
            except Exception:pass
        (folder/('academic-sse-'+str(time.time_ns())+'.json')).write_text(json.dumps(result or {'passed':False,'run_id':args.run_id,'errors':list(errors.queue)},indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
