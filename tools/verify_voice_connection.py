"""Opt-in paid transport smoke test with synthetic text, no microphone or broker data.

By default usage records are isolated in a temporary SQLite database. --hosted
uses the deployed API, its grounding and actual voice allowance. One short response.
"""
import argparse
import asyncio
import json
import os
import tempfile
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from ai_trader.config import load_dotenv

p=argparse.ArgumentParser()
p.add_argument('--env',type=Path,required=True)
p.add_argument('--confirm-spend',action='store_true')
p.add_argument('--hosted', action='store_true', help='Use deployed API and its actual voice allowance instead of local service')
a=p.parse_args()
if not a.confirm_spend:
    raise SystemExit('Pass --confirm-spend for one short paid connection test')
load_dotenv(a.env)
key=os.environ['OPENAI_API_KEY']
os.environ['AI_TRADER_DATABASE_BACKEND']='sqlite'
os.environ.pop('DATABASE_URL',None)
os.environ.pop('RENDER',None)
os.environ['AI_TRADER_REQUIRE_POSTGRES_IN_HOSTED']='false'


def remote(path, body=None):
    headers={'Authorization':'Bearer '+os.environ['AI_TRADER_API_TOKEN']}
    if body is not None:
        headers['Content-Type']='application/json'
    request=Request('https://trader-no0f.onrender.com/trader-voice/'+path,
                    data=json.dumps(body).encode() if body is not None else None, headers=headers)
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read())


async def main():
    from aiortc import RTCPeerConnection,RTCConfiguration,RTCSessionDescription
    from ai_trader import experiments as e, trader_voice as v
    with tempfile.TemporaryDirectory(prefix='trader-voice-smoke-') as directory:
        db=Path(directory)/'test.sqlite3'
        e.migrate(db)
        pc=RTCPeerConnection(RTCConfiguration(iceServers=[]))
        pc.addTransceiver('audio',direction='recvonly')
        channel=pc.createDataChannel('oai-events')
        done=asyncio.Event()
        seen=[]
        @channel.on('open')
        def opened():
            channel.send(json.dumps({'type':'conversation.item.create','item':{'type':'message','role':'user',
                'content':[{'type':'input_text','text':'This is a synthetic connection test. Say only: Voice test connected.'}]}}))
            channel.send(json.dumps({'type':'response.create'}))
        @channel.on('message')
        def message(raw):
            msg=json.loads(raw)
            if msg.get('type') in ('response.done','error'):
                seen.append({'type':msg['type'],'status':(msg.get('response') or {}).get('status'),
                             'usage':(msg.get('response') or {}).get('usage'), 'error':msg.get('error')})
                done.set()
        await pc.setLocalDescription(await pc.createOffer())
        service=SimpleNamespace(settings=SimpleNamespace(openai_api_key=key,db_path=db))
        result=None
        try:
            body=dict(mode='trader',confirmed=True,sdp=pc.localDescription.sdp)
            if a.hosted:
                result=await asyncio.to_thread(remote,'start',body)
            else:
                with patch('ai_trader.self_assessment.input_inventory',return_value={'synthetic_test':True}):
                    result=await asyncio.to_thread(v.start,service,body)
            await pc.setRemoteDescription(RTCSessionDescription(sdp=result['sdp'],type='answer'))
            await asyncio.wait_for(done.wait(),30)
            if not seen or seen[-1]['type']=='error' or seen[-1]['status']!='completed':
                raise RuntimeError(json.dumps(seen))
            print(json.dumps({'voice_transport':'completed','events':seen}))
        finally:
            if result:
                if a.hosted:
                    await asyncio.to_thread(remote,'end',{'session_id':result['session_id']})
                else:
                    v.end(db,result['session_id'])
                for _ in range(20):
                    account=await asyncio.to_thread(remote,'budget') if a.hosted else v.budget(db)
                    if account['session_id'] is None:
                        break
                    await asyncio.sleep(.5)
                print(json.dumps({'final_budget':account,'hosted':a.hosted}))
            await pc.close()

try:
    asyncio.run(main())
except HTTPError as exc:
    try:
        error=json.loads(exc.read()).get('error',{})
        print(json.dumps({'provider_status':exc.code,'code':error.get('code'),'type':error.get('type'),'message':error.get('message')}))
    except ValueError:
        print(json.dumps({'provider_status':exc.code,'message':'Non-JSON provider error'}))
    raise SystemExit(1)
