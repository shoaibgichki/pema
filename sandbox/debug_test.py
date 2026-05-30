import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app

async def run():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        from tests.conftest import create_test_session
        from tests.test_scenarios import _ai_turn_with_facts, _patch_ai_engine
        from app.schemas.enums import Specialty, Urgency
        from app.schemas.fact import ExtractedFacts
        
        facts = ExtractedFacts(
            chief_complaint='stomach pain with nausea',
            body_region='abdomen', age=30, sex='male',
            duration='3 days', severity='moderate',
            associated_symptoms=['nausea', 'bloating'],
        )
        ai_output = _ai_turn_with_facts(
            facts, Specialty.GASTROENTEROLOGIST, Urgency.ROUTINE,
        )
        with _patch_ai_engine(ai_output):
            session = await create_test_session(client)
            print('created session:', session)
            
            resp = await client.post(f'/sessions/{session["id"]}/messages', json={'text': 'I have stomach pain with nausea and bloating'})
            print('send message resp status:', resp.status_code)
            print('send message resp body:', resp.json())
            
            admin_resp2 = await client.get(f'/admin/sessions/{session["id"]}')
            print('admin detail:', admin_resp2.json())

if __name__ == '__main__':
    asyncio.run(run())
