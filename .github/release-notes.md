Uncloud v0.4.13 improves local chat, conversation continuity and everyday controls.

- Faster warm chat dispatch: reuse the loaded model/profile and connection, and deliver streamed tokens without the old polling delay.
- Model-specific sampling from metadata, with visible per-model temperature and reply-budget overrides. Report output-limit truncation instead of silently ending a reply.
- Native-tokenizer context counter, Compact at 75%, and inspectable compacted memory while preserving the original transcript.
- Cleaner expanding composer with the model selector beside the message field; consistent spacing and quieter focus states.
- Expanded local training controls and a chat adapter selector.
- Recognize Z-Image Turbo donor profiles for appropriate starting steps and guidance.
- App-session Keep Awake protection and clearer image-edit progress/stall handling.
- Optional developer diagnostics and a direct-model baseline mode.

Validation includes backend/frontend regression tests and same-model MLX reasoning/context comparisons. See uncloud/docs/INFERENCE_AUDIT.md for measured results and limits. Cross-family and Windows/Linux runtime performance are not claimed by these Mac measurements.
