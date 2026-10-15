Chat exposes `web_search` and `web_read` through the model's native tool format. The new `Tools.jinja` registry contains only function schemas. Removed the application-written web protocol, date and identity wording; shared search-result wrappers now contain neutral labels and source data without response instructions. Original source names and URLs are preserved. This does not guarantee that a model will identify itself correctly.

Native tool calls and results remain with saved conversations, context counting, compaction and Chisel handoffs. Web availability does not force a search, and unsupported runtimes receive no prompt-based tool fallback. Repeated lookups stay bounded and existing network permissions still apply. Chisel retains its task execution contract and approval controls, with its application identity and platform-specific example removed.

Personas is a separate, opt-in workspace for saving user-written instructions and a model choice before starting. Profiles and conversation snapshots are encrypted and separated by paired device; ordinary Chat receives no persona instructions.

Friday and Voice are combined into Jarviz, preserving Talk, Text to voice, Convert voice, Transcribe and Clips. Jarviz adds no built-in personality prompt and stops listening when hidden. Automations now includes both Agents & schedules and Recipes. Existing notification destinations open their corresponding new workspaces.

User messages now offer Copy on hover or keyboard focus, with touch access and stable message alignment. The Guide documents native tools, Personas and the consolidated workspaces.

Model weights, native chat templates and sampling recommendations are unchanged. These changes do not claim a speed improvement or a universal fix for model-generated identity claims.

Validation: 182 frontend tests and 1,112 backend tests passed, with three platform-specific backend skips. Seven backend checks initially blocked by sandbox restrictions passed when rerun with the required local socket and hardware access. Production frontend build, Python lint and release resource checks passed; existing frontend lint warnings remain. No model generations were run for this release validation.
