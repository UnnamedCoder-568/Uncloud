import json

from uncloud_engine import config, image_defaults
from uncloud_engine.library import LocalModel


def test_local_metadata_then_saved_defaults_override_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, '_data', {})
    monkeypatch.setattr(image_defaults, 'runtime_defaults', lambda *args: {'steps': 4})
    model = LocalModel('test', 'Test', 'image', 'mflux', str(tmp_path), 1)
    (tmp_path / 'generation_config.json').write_text(json.dumps({
        'num_inference_steps': 12, 'guidance_scale': 2.0}))
    values, source = image_defaults.resolve(model)
    assert values['steps'] == 12 and values['guidance'] == 2
    assert source == 'Model configuration'
    config.settings._data['image_defaults'] = {model.path: {'steps': 7, 'width': 768}}
    values, source = image_defaults.resolve(model)
    assert values['steps'] == 7 and values['width'] == 768
    assert source.startswith('Your saved')


def test_invalid_model_defaults_are_not_applied():
    assert image_defaults.validated({'steps': -1, 'guidance': 'bad', 'width': True}) == {}


def test_assembled_turbo_uses_donor_profile_and_model_override_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, '_data', {})
    monkeypatch.setattr(image_defaults, 'runtime_defaults', lambda *args: {})
    monkeypatch.setattr(image_defaults, 'pipeline_defaults', lambda *args: {
        'steps': 50, 'guidance': 5.0})
    donor = tmp_path / 'z-image-turbo'
    donor.mkdir()
    (donor / 'model_index.json').write_text(json.dumps({'_class_name': 'ZImagePipeline'}))
    weights = tmp_path / 'custom-finetune.gguf'
    weights.touch()
    model = LocalModel('test', 'Custom', 'image', 'gguf-diffusion', str(weights), 1,
                       profile_base=str(donor))
    values, source = image_defaults.resolve(model)
    assert (values['steps'], values['guidance']) == (9, 0.0)
    assert source == 'Turbo model profile'
    (tmp_path / 'generation_config.json').write_text(json.dumps({
        'num_inference_steps': 12, 'guidance_scale': 1.5}))
    values, source = image_defaults.resolve(model)
    assert (values['steps'], values['guidance']) == (12, 1.5)
    assert source == 'Model configuration'
