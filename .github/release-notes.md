Voice lifecycle stress fixes: prevent speech after Stop, restore retry after microphone denial, release late native listeners, observe immediate audio completion, and keep the microphone muted until queued speech finishes. Leaving a voice pane now stops its session.

Updated the Guide with 14 topics covering Friday, context compaction, LoRA, training, quantization, recipes, outputs and updates. Removed device-specific quantization claims.

Added a repeatable stress runner and scenario matrix. Validation: 1,008 backend, 126 frontend and 4 desktop tests; production build and release verification passed. Read-only UI smoke covered every module. A bounded offline 2B model run passed 12 basic fixed-prompt checks. Real mic, target-platform permissions, physical sleep/wake, in-place upgrading and full media/training quality are separate device checks; see qa/RESULTS.md.
