import secrets

import pytest

from uncloud_engine import conversations, personas


@pytest.fixture(autouse=True)
def private_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(personas, 'DIR', tmp_path / 'personas')
    monkeypatch.setattr(conversations, 'DIR', tmp_path / 'conversations')
    key = secrets.token_bytes(32)
    monkeypatch.setattr(conversations.vault, 'key', lambda: key)


def test_saved_persona_is_encrypted_editable_and_scoped_to_its_device():
    saved = personas.save('Storyteller', 'Describe a quiet woodland.', '/model', owner='desktop')
    assert personas.listing('phone') == []
    assert personas.listing('desktop') == [saved]
    path = personas._path(saved['id'], 'desktop')
    assert b'woodland' not in path.read_bytes()
    edited = personas.save('Storyteller', 'Use short sentences.', '/other',
                           owner='desktop', persona_id=saved['id'])
    assert edited['created'] == saved['created']
    assert personas.listing('desktop') == [edited]


@pytest.mark.parametrize('bad', ['', '../private', '/tmp/anything', 'A' * 16])
def test_persona_id_cannot_escape_its_owner_shelf(bad):
    with pytest.raises(ValueError):
        personas.save('Name', 'Instructions', None, owner='desktop', persona_id=bad)


def test_empty_persona_does_not_create_a_profile():
    with pytest.raises(ValueError):
        personas.save('Name', '   ', None, owner='desktop')
    assert personas.listing('desktop') == []


def test_persona_snapshot_and_normal_chat_history_remain_distinct():
    saved = personas.save('Storyteller', 'Original instructions.', '/model', owner='desktop')
    c = conversations.create([{'role': 'user', 'content': 'Start the story.'}])
    c.persona = {k: saved[k] for k in ('id', 'name', 'instructions')}
    conversations.save(c)
    personas.save('Updated', 'New instructions.', '/model', owner='desktop', persona_id=saved['id'])
    plain = conversations.save(conversations.create([{'role': 'user', 'content': 'Hello.'}]))
    assert conversations.load(c.id).persona['instructions'] == 'Original instructions.'
    assert conversations.load(plain.id).persona is None
    summaries = {x['id']: x for x in conversations.listing().conversations}
    assert summaries[c.id]['persona_id'] == saved['id']
    assert summaries[plain.id]['persona_id'] is None


def test_persona_api_requires_auth_and_prevents_cross_workspace_overwrites(monkeypatch):
    from fastapi.testclient import TestClient

    from uncloud_engine import main

    client = TestClient(main.app)
    assert client.get('/api/personas').status_code == 401
    headers = {'Authorization': f'Bearer {main.settings.token}'}
    body = {'name': 'Editor', 'instructions': 'Use my chosen style.', 'model_path': '/model'}
    saved = client.post('/api/personas', headers=headers, json=body).json()
    assert client.get('/api/personas', headers=headers).json() == [saved]
    changed = client.put(f"/api/personas/{saved['id']}", headers=headers,
                         json={**body, 'instructions': 'Edited style.'})
    assert changed.status_code == 200
    assert changed.json()['created'] == saved['created']
    snapshot = {k: saved[k] for k in ('id', 'name', 'instructions')}
    conversation = {'messages': [{'role': 'user', 'content': 'Draft it.'}], 'persona': snapshot}
    cid = 'abcdef0123456789'
    assert client.put(f'/api/conversations/{cid}', headers=headers,
                      json=conversation).status_code == 200
    assert client.put(f'/api/conversations/{cid}', headers=headers,
                      json={'messages': []}).status_code == 409
    assert client.get(f'/api/conversations/{cid}', headers=headers).json()['persona'] == snapshot
    monkeypatch.setattr(main, 'principal_of', lambda request: 'phone')
    assert client.get('/api/personas', headers=headers).json() == []
    assert client.put(f"/api/personas/{saved['id']}", headers=headers, json=body).status_code == 404
