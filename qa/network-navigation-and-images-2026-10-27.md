# Connected-device navigation and image previews

The app shell follows the browser's visual viewport. Mobile navigation occupies a stable first header row, while the active workspace owns the second row. Desktop window sizing remains native. Back/Forward close an open navigation drawer and preserve visited workspace state.

Generated images use one shared, in-app viewer across Outputs, Image Generate, Image Edit, Product Studio and generated Chat replies. It reuses authenticated blob URLs, supports fit and zoom, and unmounts when its workspace becomes hidden. Keyboard focus returns to the trigger after closing.

Chat displays selected model metadata in the header. No changes were made to Tools.jinja, native chat templates, model weights, system prompts or inference defaults. Transport tests compare desktop and browser request bodies; backend tests compare native messages and schemas across owners. These checks establish request parity, not a guarantee about a model's self-description.

API and HTML responses now opt out of browser caching. Unauthorized engine status requests still return 401. Shared LAN routing and paired-session authentication were not modified.

## Verification

- Backend: 1,298 passed, 12 optional tests skipped, from an isolated source copy excluding unrelated working edits.
- Frontend: 247 passed; production build passed; lint completed with existing warnings.
- Python lint and bundled-runtime manifest checks passed.
- Real browser layout checks at 1360 × 860, 390 × 844 and 320 × 440 used synthetic local data. Chat navigation, retained conversation, image fit/zoom/close and keyboard focus passed.
- Automated visual-viewport resize/pan and native-desktop no-op checks passed.

Physical mobile keyboards, live model self-identification and Windows/Linux inference were not verified in these layout tests. No generation-speed improvement is claimed.
