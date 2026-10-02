# Speech runtime comparison — 2026-10-02

Local Apple Silicon, same AF Heart voice, speed 1, same short text:
“Welcome to Uncloud. Your models run locally, and your work stays on this device.”
The reference uses cached hexgrad/Kokoro-82M PyTorch weights; MLX uses the
mlx-community/Kokoro-82M-bf16 conversion. ONNX uses the maintainer's official
model-files-v1.1 INT8 export. These are different formats/precisions, not identical files.

| Path | First request including worker startup | Warm requests | Audio duration |
| --- | ---: | ---: | ---: |
| Existing Kokoro CPU worker | 4.284 s | 0.473 / 0.472 s | 5.33 s |
| New Kokoro MLX worker, mlx-audio 0.5.7 | 20.433 s | 0.292 / 0.292 s | 5.33 s |

MLX reduced warm worker time by approximately 38% for this fixture. Its first
request was substantially slower; it is an explicit option, not the default.
This includes worker IPC and audio-file writing but excludes frontend, playback,
and text-model generation. Two warm repetitions of one sentence do not establish
performance across every voice, long script, hardware configuration or concurrent GPU load.

Separate in-process measurements (not directly interchangeable with worker timings):

| Runtime | Import/load | Warm synthesis | Peak process RSS |
| --- | ---: | ---: | ---: |
| Existing PyTorch Kokoro | 4.886 s | 0.474 / 0.477 s | 1576.4 MiB |
| Kokoro ONNX INT8, default threads | 1.110 s | 2.221 / 2.271 s | 496.3 MiB |
| Kokoro ONNX INT8, four threads | 0.340 s | 2.191 / 2.206 s | 488.4 MiB |
| Kokoro MLX | 0.153 s | 0.286 / 0.293 s | 757.1 MiB |

MLX separately reported 1453.9 MiB peak allocator memory. Process RSS alone is
not total unified-memory consumption, so these numbers do **not** prove MLX
uses less total memory. ONNX is lighter in this CPU comparison but considerably
slower; it was not added as a default. Single/two-thread INT8 experiments produced
an empty-audio error and were rejected rather than shipped.

The PyTorch and MLX sample outputs have matching 24 kHz sample rate and 127800
samples, finite audio, no clipping, and waveform correlation 0.972. This is a
technical regression check, not a listening-quality evaluation or proof of
better pronunciation. No live microphone or speaker playback was tested.

## Setup changes

Fresh macOS setup no longer eagerly creates both VibeVoice environments. Their
measured combined installed footprint was about 2.7 GB on this development
machine, excluding model weights/caches. Existing environments are not deleted.
Advanced narration, music and voice cloning can still be selected during setup
or installed through their existing feature gates. First-run readiness avoids
probing those optional environments unless selected.

The main locked environment already carried mlx-audio transitively; this change
pins the tested 0.5.7 version and exposes its native Kokoro path. Training,
image/video generation, Linux CUDA package selection, and streamed audio playback
have not been optimized by this change. Studio's shared core stays synchronized;
its separate UI and installers are not released by the Uncloud workflow.

## Reproduce

Use the Python installed for the selected engine, with local model files:

```
python scripts/benchmark_speech.py --engine kokoro --model /path/to/Kokoro --output /tmp/speech-cpu
python scripts/benchmark_speech.py --engine kokoro-mlx --model /path/to/Kokoro-MLX --output /tmp/speech-mlx
```

The benchmark disables Hub access and never downloads weights. Use fresh output
folders; clips are preserved for listening comparisons. Metal access is required
for the MLX path. Compare longer and multilingual fixtures before changing the
product's default engine.
