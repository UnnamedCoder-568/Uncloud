Fix web requests overflowing small local model context windows. Retrieved evidence is budgeted with the active model’s native tokenizer and chat template, including room for the reply. Original conversation turns are preserved; if the conversation and sources cannot fit, Chat asks for compaction or a larger supported window instead of sending an oversized request.

Web evidence is retained with its user turn for follow-up continuity and context accounting. Added a per-model GGUF context-window control with native-limit validation, explicit reload and saved preferences. Ordinary messages keep the loaded model resident. Invalid overrides are rejected before unloading the current model.

Updated the Guide. Automated regression validation and production build passed; the exact Windows Gemma model/hardware from the reported screenshot is not available on the test Mac, so target-device verification remains necessary.
