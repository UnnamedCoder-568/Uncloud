# Optional image enhancement

Real-ESRGAN x2plus weights: Copyright (c) 2021, Xintao Wang.
Source: https://github.com/xinntao/Real-ESRGAN
License: BSD-3-Clause, reproduced in Real-ESRGAN.txt.

RRDBNet architecture reference: BasicSR, Copyright 2018-2022 BasicSR Authors.
Source: https://github.com/XPixelGroup/BasicSR
License: Apache-2.0, reproduced in BasicSR.txt.

Uncloud implements tiled inference separately in image_upscale.py. No upstream
Python package is required, and no face-restoration or content classifier is used.
The optional weights are downloaded unchanged from the upstream GitHub release
only when requested. The expected size and SHA-256 are pinned in image_upscale.py.
