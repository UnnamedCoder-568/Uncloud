import json

from uncloud_engine.context_profile import describe
from uncloud_engine.core.models.headers import GgufHeader


def test_gguf_context_is_native_window_bounded_by_kv_budget(tmp_path, monkeypatch):
    weights = tmp_path / 'model.gguf'
    weights.write_bytes(b'weights')
    fields = {
        'general.architecture': 'qwen3',
        'qwen3.context_length': 131072,
        'qwen3.block_count': 40,
        'qwen3.embedding_length': 4096,
        'qwen3.attention.head_count': 32,
        'qwen3.attention.head_count_kv': 8,
    }
    monkeypatch.setattr('uncloud_engine.context_profile.read_gguf',
                        lambda path: GgufHeader(3, 1, fields))
    profile = describe(str(weights), 'gguf', 8.0)
    assert profile['native_limit'] == 131072
    assert 1024 <= profile['effective_limit'] < 131072
    assert profile['limited_by_memory']


def test_mlx_context_comes_from_nested_text_config(tmp_path):
    (tmp_path / 'config.json').write_text(json.dumps({
        'text_config': {'max_position_embeddings': 32768,
                        'num_hidden_layers': 24, 'num_attention_heads': 16,
                        'num_key_value_heads': 4, 'hidden_size': 2048},
    }))
    profile = describe(str(tmp_path), 'mlx', 24.0)
    assert profile['native_limit'] == 32768
    assert profile['effective_limit'] == 32768
    assert profile['source'] == 'Model config.json'
