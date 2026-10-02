"""Offline image LoRA jobs using the installed MFlux training contract."""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
import uuid
import zipfile
from pathlib import Path

from . import jobs


def template(model: str = 'z-image-turbo') -> dict:
    from importlib.util import find_spec
    spec = find_spec('mflux')
    if not spec or not spec.submodule_search_locations:
        raise jobs.Refused('Install Image LoRA training in Settings → Required software.')
    files = {'z-image-turbo': 'train.json', 'ernie-image': 'train_ernie_image.json',
             'ernie-image-turbo': 'train_ernie_image_turbo.json'}
    if model not in files:
        raise jobs.Refused('No verified training template for this family. Import a compatible training configuration instead.')
    path = Path(next(iter(spec.submodule_search_locations))) / 'models/common/training/_example' / files[model]
    config = json.loads(path.read_text())
    config.pop('monitoring', None)
    config['low_ram'] = True
    return {'config': config, 'source': 'Installed MFlux training example; review targets for your model.'}


def prepare(config: dict) -> dict:
    from mflux.models.common.training.state.training_spec import TrainingSpec
    from ..budget import memory_budget
    from ..library import _dir_size_gb
    if not isinstance(config, dict):
        raise jobs.Refused('Choose a valid image training configuration.')
    model = Path(str(config.get('model_path', '')))
    data = Path(str(config.get('data', '')))
    if not model.is_absolute() or not model.is_dir():
        raise jobs.Refused('Select a complete local MFlux model folder. Training does not download weights.')
    if not data.is_absolute() or not data.is_dir():
        raise jobs.Refused('Select an image folder with matching caption .txt files.')
    from mflux.models.common.config.model_config import ModelConfig
    try:
        family = ModelConfig.from_name(str(config.get('model', ''))).model_name
    except (ValueError, KeyError) as exc:
        raise jobs.Refused(f'Unknown training model family: {exc}') from exc
    supported = ('/Z-Image', '/ERNIE-Image', '/FLUX.2', '/Krea2', '/krea2')
    if not any(name in family for name in supported):
        raise jobs.Refused('This installed trainer supports Z-Image, ERNIE-Image, FLUX.2 and Krea2; Flux1 training is not supported.')
    if family == ModelConfig.z_image_turbo().model_name:
        # The native trainer always loads this assistant adapter. Check only
        # local cache entries; never turn a feasibility check into a download.
        from mflux.cli.defaults.defaults import MFLUX_LORA_CACHE_DIR
        filename = 'zimage_turbo_training_adapter_v2.safetensors'
        cache = Path(MFLUX_LORA_CACHE_DIR)
        present = cache.is_dir() and any(p.is_file() for p in cache.rglob(filename))
        if not present:
            raise jobs.Refused('Z-Image Turbo training requires its assistant adapter: zimage_turbo_training_adapter_v2.safetensors. Install it in the MFlux LoRA cache before offline training.')
    # Use a scratch output in the schema validation; never create user output here.
    resolved = {**config, 'checkpoint': {**config.get('checkpoint', {}),
        'output_path': str(jobs.TRAINING_DIR / 'image-validation')}}
    try:
        spec = TrainingSpec.from_conf(resolved, None, create_output_dir=False)
    except (ValueError, TypeError, KeyError, FileNotFoundError) as exc:
        raise jobs.Refused(f'Image dataset/configuration needs correction: {exc}') from exc
    if not spec.data or not spec.lora_layers.targets:
        raise jobs.Refused('Provide captioned images and at least one LoRA target layer.')
    if any(not item.image.is_file() or not item.prompt.strip() for item in spec.data):
        raise jobs.Refused('Every example needs a readable image and nonempty caption.')
    if spec.training_loop.num_epochs < 1 or spec.training_loop.batch_size < 1:
        raise jobs.Refused('Epochs and batch size must be positive.')
    budget = memory_budget().get('budget_gb', 0)
    needed = _dir_size_gb(model) + 2 * spec.training_loop.batch_size
    if budget <= 0 or needed > budget:
        raise jobs.Refused(f'Estimated training memory is {needed:.1f} GB; available budget is {budget:.1f} GB. Use smaller weights, batch or another machine.')
    return {'examples': len(spec.data), 'estimated_memory_gb': round(needed, 1),
        'budget_gb': budget, 'iterations': spec.training_loop.num_epochs *
        ((len(spec.data) + spec.training_loop.batch_size - 1) // spec.training_loop.batch_size),
        'note': 'Memory is an estimate. All base weights and any model-required training adapters must already be local.'}


async def start(config: dict, name: str = '') -> jobs.TrainingJob:
    plan = prepare(config)
    ident = uuid.uuid4().hex[:12]
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or 'image-lora'
    output = jobs.TRAINING_DIR / 'adapters' / f'{slug}-{ident}'
    output.mkdir(parents=True)
    resolved = {**config, 'checkpoint': {**config['checkpoint'], 'output_path': str(output / 'run')}}
    path = output / 'image-training.json'
    path.write_text(json.dumps(resolved, indent=2))
    job = jobs.TrainingJob(id=ident, model_path=config['model_path'], dataset_path=config['data'],
        preset='image-lora', output_dir=str(output), iterations=plan['iterations'], examples=plan['examples'], settings=resolved)
    jobs._jobs[ident] = job
    jobs._tasks[ident] = asyncio.create_task(_run(job, path))
    return job


async def _run(job, config_path):
    import os
    from ..power import keep_awake
    from ..engines import engine_manager
    process = None
    try:
        engine_manager.stop()
        with keep_awake('image-training'):
            job.status = 'training'
            process = await asyncio.create_subprocess_exec(sys.executable, '-m',
                'mflux.models.common.cli.train', '--config', str(config_path),
                env={**os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'},
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            async for raw in process.stdout:
                line = raw.decode(errors='replace').strip()
                job.log.append(line)
                job.log[:] = job.log[-80:]
                match = re.search(r'(?:iteration|step)\s*[:=]?\s*(\d+)', line, re.I)
                if match:
                    job.iteration = int(match[1])
            if await process.wait() != 0:
                raise RuntimeError('Image training failed. ' + '\n'.join(job.log[-5:]))
            archives = sorted(Path(job.output_dir).rglob('*checkpoint.zip'))
            if not archives:
                raise RuntimeError('Training finished without an adapter checkpoint. Reduce checkpoint interval or increase epochs.')
            with zipfile.ZipFile(archives[-1]) as archive:
                weights = [n for n in archive.namelist() if n.endswith('_lora.safetensors')]
                if not weights:
                    # Native version may call it lora_adapter rather than lora.
                    weights = [n for n in archive.namelist() if 'lora' in Path(n).name and n.endswith('.safetensors')]
                if not weights:
                    raise RuntimeError('The checkpoint contains no LoRA weights.')
                with archive.open(weights[-1]) as source, (Path(job.output_dir) / 'adapter.safetensors').open('wb') as dest:
                    import shutil
                    shutil.copyfileobj(source, dest)
            card = {'adapter': Path(job.output_dir).name, 'base_model': job.model_path,
                'dataset': job.dataset_path, 'examples': job.examples, 'kind': 'image', 'val_loss': None}
            (Path(job.output_dir) / 'uncloud-adapter.json').write_text(json.dumps(card, indent=2))
            job.iteration = job.iterations
            job.status = 'done'
    except asyncio.CancelledError:
        job.status = 'cancelled'
        raise
    except Exception as exc:
        job.status = 'error'
        job.error = str(exc)
    finally:
        job.ended_at = time.time()
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
