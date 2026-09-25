Uncloud 0.4.12 — macOS Apple silicon, Linux x64 and Windows x64

- Web search removes conversational scaffolding before querying providers and checking relevance. Natural questions and short follow-ups no longer fail because polite wording is mistaken for the subject.
- Model deletion now carries an exact, expiring, single-use confirmation across the HTTP retry. Approving one model never approves deleting another, and each deletion still requires confirmation.
- Errors show readable messages instead of raw HTTP/JSON approval data.
- Image defaults come from installed runtime declarations, model configuration and saved per-model preferences. Engine-wide frontend guesses have been removed. The source of the defaults is shown; users can save their settings or restore model recommendations.
- Includes v0.4.11 page-reading search, persistent download pause/resume, model removal menus, outside-click dismissal, accurate version display and white app icon.

Source availability still varies. Uncloud labels unavailable web pages instead of treating snippets as fully verified content. Models without recommendations use explicitly labeled general starting settings.
