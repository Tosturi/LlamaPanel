from urllib.parse import quote


def test_edit_and_rename_preserve_flags_and_other_presets(client):
    flags = {"ctx_size": 4096, "future_flag": ["a", "b"], "kv_offload": False}
    client.put('/api/presets/old', json={"name": "old", "model_id": "m", "flags": flags})
    client.put('/api/presets/other', json={"name": "other", "model_id": "m", "flags": {}})
    flags['ctx_size'] = 8192
    result = client.patch('/api/presets/old', json={"name": "Новое имя", "model_id": "m", "flags": flags})
    assert result.status_code == 200
    assert result.json()['flags'] == flags
    assert result.json()['updated_at'] is not None
    assert 'future_flag' in result.json()['unsupported']
    items = client.get('/api/presets').json()
    assert [p['name'] for p in items] == ['Новое имя', 'other']
    flags.pop('ctx_size')
    result = client.patch('/api/presets/' + quote('Новое имя'), json={"name": "Новое имя", "model_id": "m", "flags": flags})
    assert result.status_code == 200
    assert result.json()['flags'] == flags


def test_edit_rejects_collision_missing_and_blank_without_mutation(client):
    for name in ['one', 'two']:
        client.put('/api/presets/' + name, json={"name": name, "model_id": "m", "flags": {"ctx_size": 4096}})
    before = client.get('/api/presets').json()
    for original, new, status in [('one', 'two', 409), ('gone', 'new', 404), ('one', '  ', 400)]:
        result = client.patch('/api/presets/' + original, json={"name": new, "model_id": "m", "flags": {}})
        assert result.status_code == status
        assert client.get('/api/presets').json() == before


def test_edit_changes_model_and_preserves_flags(client):
    client.put('/api/presets/model-test', json={"name": "model-test", "model_id": "old-model", "flags": {"ctx_size": 4096}})
    response = client.patch('/api/presets/model-test', json={"name": "model-test", "model_id": "new-model", "flags": {"ctx_size": 4096}})
    assert response.status_code == 200
    saved = client.get('/api/presets').json()[0]
    assert saved['model_id'] == 'new-model'
    assert saved['flags'] == {"ctx_size": 4096}
