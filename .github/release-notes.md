Chat and Chisel now share native model controls, supported thinking settings, sampling overrides, presets and an inspectable effective configuration. Unsupported model/backend settings are disabled or rejected rather than simulated.

Context accounting uses the active model's native tokenizer/template and effective runtime window. Compact preserves structured conversation memory, decisions, constraints and references. A live MiniCPM test reduced context from 2,191 to 314 native tokens while preserving 10/10 continuity checks, including an explicit prohibition against deleting original data.

Added a private persistent notification inbox, category/sound preferences, native OS notification adapters, real user-question pauses and safer Chisel recovery. Old approvals cannot be reused after restart; ambiguous side effects are not automatically repeated. Background close-to-tray is an explicit opt-in.

Validated locally with 1,050 backend tests, 135 frontend tests and 5 desktop-shell tests. MiniCPM, Llama and Qwen produced matching quality scores through native transport and Uncloud. No universal intelligence or speed improvement is claimed. Native visible notification delivery/click behavior on Windows/Linux and macOS packaged-device behavior still require verification; the tested QA bundle rejected macOS notification authorization and retained the request in the inbox.

The complete A–V audit and raw benchmark evidence are in [qa/UNIFIED_ENGINE_AUDIT.md](https://github.com/UnnamedCoder-568/Uncloud/blob/main/qa/UNIFIED_ENGINE_AUDIT.md). Existing native context-budgeting and GGUF window controls remain included.
