# Automatic and optional 2× image enhancement

Generate, Edit and Product now enable **Automatic 2× enhancement** by default.
The shared option remembers an opt-out. Each engine job renders, saves the
original, then enhances it inside the same queue before reporting completion.
The enlarged result is displayed automatically. The viewer's Original/Enhanced
controls compare both files without running enhancement a second time.

Closing or backgrounding the UI does not interrupt this pipeline. A failed,
oversized or stopped enhancement returns the successfully rendered original
with an explanation; the source is never discarded. Generation failures still
remain failures. First-use model setup uses the existing install approval,
separately from any generation approval, before work is queued.

The image viewer offers **Enhance 2×** for generated images in Generate, Edit,
Product and Outputs. It writes a separate PNG and keeps the source unchanged.
Original/enhanced controls compare the two; zoom remains a separate control.

The optional Real-ESRGAN x2plus model is about 64 MiB. Download requires a user
action, uses the upstream release URL, and verifies both size and SHA-256 before
loading with `weights_only=True`. Offline use works after that download. The
packaged notices are in `sidecar/uncloud_engine/third_party/`.

This is pixel-only inference. It adds no model instructions, prompt changes,
classifier, face restoration, generation filter, or replacement encoder. Models,
adapters, seeds, guidance, steps and generation resolution remain as selected.
Enhanced detail is reconstructed; the original remains the reference.

## Timing and quality evidence

Measured 2026-10-31 on a 24 GiB Apple silicon Mac using the installed native
Klein 4B 8-bit MLX model and its existing custom text encoder. Neutral teapot,
bicycle and fabric photographs were used. Background applications stayed open.

For each direct/high-resolution pair, prompts, seeds, four diffusion steps,
guidance and memory limits matched. Different resolutions necessarily use
different latent grids, so the direct larger image is not pixel-identical.

| Neutral case | Render 1024×768 | Optional 2× enhancement | Combined | Direct 2048×1536 |
| --- | ---: | ---: | ---: | ---: |
| Teapot | 21.44 s | 7.68 s | 29.12 s | 76.03 s |
| Bicycle | 17.96 s | 6.81 s | 24.77 s | 99.11 s |

These are two paired measurements, not a guaranteed speed ratio. Enhancement
alone also took 6.81 s on the fabric case. Visual inspection at equal display
sizes showed sharper bicycle edges and brick detail than Lanczos enlargement;
fabric improvement was smaller. Quality depends on the source, so enhancement
stays optional. This does **not** establish faster native-resolution diffusion
or performance on every model/device.

A compiled-predictor retention candidate gave identical pixels but inconsistent
speed and was rejected. Allocator changes were also not promoted: isolated
measurements did not establish a consistent gain. No sampling/precision/default
resolution changes are part of this feature.

## Verification

- Real GPU inference through the implementation: three complete enlargements.
- Odd dimensions, exact output dimensions, separately preserved transparency,
  original file hashes and stopping between tiles checked on hardware.
- Tile overlap inspected against untiled inference. On a 256-pixel texture crop,
  rounding/tile differences averaged 0.124 intensity levels out of 255; maximum 8.
- Enhancement uses the existing image queue, so image jobs do not overlap.
- Download cancellation, bad digest/size, output boundaries, symlink escape,
  authentication, job ownership, queued cancellation and failure paths covered.
- Viewer comparison, resume, failure and private blob cleanup covered in UI tests.

## Installed macOS preview

The installed app completed the optional model download and enlarged an image
from 1024×768 to 2048×1536 in 12 seconds including first-use setup. Enhancement
of a freshly generated image then took 7 seconds with its MLX generation model
still resident. The generated source matched the isolated API run pixel for pixel.
A subsequent, different telescope prompt also completed using the resident model.

One initial run stalled after the last diffusion step. A short native stack
sample showed a pending file-open operation. The user subsequently confirmed
that macOS was requesting external-drive access. That is consistent with the
file-access wait; models and outputs were on external drives. The next two
installed-app generations completed. No sampler or quality reduction was made
to address this incident; retain the permission prompt as a first-launch check.
Progress now distinguishes loading, prompt processing, decoding and saving,
and shows total elapsed time instead of leaving every phase labelled rendering.

Quality can be checked with the Original/Enhanced comparison. Automatic
enhancement can be disabled without changing sampling or rendering defaults.

## End-to-end timing rerun

The real before/current ImageGenerate interfaces were timed from the Generate
click until the finished image loaded plus two display frames. On the same Mac,
Klein 4B 8-bit, four steps, guidance 1, and matched prompts/seeds:

| 1024×768 case | Before | Current |
| --- | ---: | ---: |
| First render including model loading | 22.9 s | 21.2 s |
| Second prompt, model resident | 32.9 s | 32.6 s |
| Third prompt, model resident | 35.5 s | 31.7 s |

All three normal-resolution outputs were pixel-identical. The small sample's
average changed from 30.4 to 28.5 seconds; it does not prove a general diffusion
speedup. For the third scene, direct 2048×1536 generation took 88.2 seconds,
versus 31.7 + 7.3 = 39.0 seconds for generation and enhancement. That comparison
uses a different larger-image workflow; upscaling is not native larger rendering.
Those manual-stage timings exclude time between clicks. Automatic pipeline
timing is verified separately, with the enhancement model already installed.

CUDA is selected when available, then Metal, then CPU. Windows/Linux share this
implementation, but native performance and driver compatibility require tests
on those machines. A CPU fallback is reported as CPU; it is not advertised as a
GPU speedup. No universal image-quality guarantee is made.

## Automatic pipeline verification

The release candidate completed a real GPU render and automatic enhancement as
one engine job in 26.4 seconds, including model loading, on the same Mac. This
is engine timing, excluding UI display/polling. It produced a 2048×1536 PNG from
a 1024×768 source with no intermediate user action. The original's pixels matched
the before-version image for the same prompt and seed exactly. Both files remain
available. Enhancement weights were already installed.

The clean release snapshot passed 1,324 backend tests (12 optional skips),
252 UI tests, production web packaging and macOS app signature/resource checks.
Unrelated working-copy legal changes are excluded from this release.
