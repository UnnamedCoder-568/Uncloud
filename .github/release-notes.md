Uncloud 0.4.15 makes local training and creative workflows easier to navigate. Text adapters and image LoRAs have separate training panels; advanced image configuration remains accessible alongside engine-derived training controls. Chisel model selection is beside the goal field, creative options consistently sit on the right, and Settings are grouped by purpose.

Adds offline MFlux image LoRA jobs, local MLX text adapter fusion/export, cancellable staged quantization, and desktop computer-use tools. Workspace mode blocks shell commands, desktop input and app launches; full device access and action permissions are required for those tools.

Validation: 982 backend tests passed, one skipped; 121 frontend tests passed; production build passed. Native text LoRA training and 4-bit fusion/export were exercised. Full diffusion training, physical desktop input and GGUF quantization were not end-to-end validated on all platforms. API-teacher training is not included.
