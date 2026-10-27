from types import SimpleNamespace

from fastapi.testclient import TestClient


def test_api_and_html_are_not_reused_from_a_browser_cache():
    from uncloud_engine import main

    client = TestClient(main.app)
    response = client.get('/api/engine/status')
    assert response.status_code == 401
    assert response.headers['cache-control'] == 'no-store'
    assert client.get('/docs').headers['cache-control'] == 'no-store'


def test_desktop_and_paired_chat_keep_the_same_native_messages_and_tools(monkeypatch):
    from uncloud_engine import main
    from uncloud_engine.chat import model_payload

    active = SimpleNamespace(engine='gguf', model_path='/selected/model', adapter_path=None,
        context_limit=8192, process=SimpleNamespace(poll=lambda: None),
        inference_profile={'capabilities': {'native_tools': True, 'fields': [],
                                           'reasoning': {'levels': ['auto']}}})
    monkeypatch.setattr(main.engine_manager, 'active', active)
    monkeypatch.setattr(main, '_check_chat_idle', lambda: None)
    captured = []

    async def run_chat(run, body, engine):
        captured.append(model_payload(engine, body.messages, inference=body.inference,
                                      web_tools=body.web_tools, chart_tools=body.chart_tools))
        run.status = 'done'

    monkeypatch.setattr(main, '_run_chat', run_chat)
    body = {'messages': [{'role': 'user', 'content': 'What is your model name?'}],
            'model_path': '/selected/model', 'inherit_defaults': False,
            'inference': {}, 'web_tools': True, 'chart_tools': True}
    with TestClient(main.app) as client:
        for owner in ('desktop', 'paired-phone'):
            monkeypatch.setattr(main, 'principal_of', lambda request, owner=owner: owner)
            response = client.post('/api/chat/runs', json=body,
                                  headers={'Authorization': f'Bearer {main.settings.token}'})
            assert response.status_code == 200
            assert client.get(f"/api/chat/runs/{response.json()['id']}", headers={
                'Authorization': f'Bearer {main.settings.token}'}).status_code == 200
    assert len(captured) == 2 and captured[0] == captured[1]
    assert captured[0]['messages'] == body['messages']
    assert {tool['function']['name'] for tool in captured[0]['tools']} == {
        'web_search', 'web_read', 'render_bar_chart'}
