Uncloud v0.4.14 fixes chat status handling and exposes image LoRA controls.

- Keep application errors out of model history; preserve partial answers and show status below the reply without duplicate action rows.
- Surface the backend rejection reason and retain bounded diagnostic details instead of a generic HTTP client traceback.
- Use one native llama.cpp chat slot and read the effective runtime context at startup.
- Use native GGUF output defaults rather than automatically limiting replies to a quarter of the context window. Explicit model recommendations and user overrides remain authoritative.
- Style the chat temperature and reply-budget fields consistently.
- Add a LoRA file picker and strength control to supported MFlux image generation.
- Clarify that Recipes are reusable action workflows, separate from model training.

Validation: backend regression suite and frontend tests/build. The first Windows Gemma request failure and live adapter generation require verification on the target machine; this release improves diagnostics without claiming those hardware cases have been reproduced. Expanded desktop computer use and provider-assisted training are follow-up work.
