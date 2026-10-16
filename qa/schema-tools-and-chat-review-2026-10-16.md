# Schema tools and chat verification — 2026-10-16

The local macOS build renders a requested bar graph directly in Chat from a
native `render_bar_chart` call. The visible Alpha/Beta/Gamma bars retain the
supplied values 12/8/15. Rendering ends that chart-only turn without another
model generation. Invalid data allows one structured correction, then stops.

The tool registry contains four function schemas, 838 bytes, and no description
fields. Recognized native templates retain their role boundaries and call
syntax; conversational tool preambles are replaced with schema and syntax
only. The XML example retains the native line breaks and two parameter blocks:
the earlier compressed one-line example produced malformed parameter tags in
the live Qwen test. Unknown templates remain unchanged.

No app identity, model identity reminder, persona, or date is added to ordinary
Chat. Explicit user instructions, optional spoken/media modes, compaction and
Chisel task contracts remain separate conditional paths. Graph rendering never
executes Python, HTML, JavaScript, or a model-supplied URL.

## Verified

- Qwen3.5 9B MLX Q4: one resident model, sequential live requests; Web-enabled
  graph request rendered inside the installed app with exact supplied values.
- Numeric Markdown tables retain table view and offer a bar-chart view.
- Visible attachment control accepts extracted documents/source files and adds
  image formats when the loaded runtime reports vision support. PDF extraction
  is not supported.
- Assistant messages use the shared reading-column width; hover controls stay
  outside normal layout. Generation/compaction/loading status is above input.
- 1,147 backend tests passed; one skipped. 222 frontend tests and six desktop
  tests passed.
- Python lint, production frontend build, macOS application build and resource
  manifest verification passed. Frontend lint completed with existing warnings
  in other components.
- Automated tests cover count/generation tool parity, bounded correction,
  literal-data validation, attachments and chart rendering. They do not prove
  live Windows GPU/context behavior or live Chisel execution.

## Unresolved identity behavior

On the earlier schema-only local build, short sequential conversations with chart tools
available reproduced a Google identity claim both with Web disabled and enabled.
The sequence was `Hello`, `Who am I speaking with?`, `What is your model name?`.
No search call occurred. Earlier fresh identity questions could identify Qwen
correctly. Sanitizing tool syntax does not establish reliable model identity
retention, and this change does not claim to fix it. No corrective identity
prompt, forced model answer, or sampling change was added.

Tool selection and generated values remain model-dependent. The renderer checks
structure and numeric values; it does not verify factual benchmark claims.

## Deployment and optional profiles

- First-run setup reports package archive sizes from the locked dependency
  graph, package count, recommended free-space reserve and available space on
  the destination drive. The reserve is explicitly an estimate. Missing archive
  sizes remain unknown; Python, source-build dependencies, models and optional
  runtimes are listed as additional downloads. Cache reuse can reduce transfers.
- The manifest is generated for Apple Silicon macOS, Windows x64 and Linux x64.
  It follows platform markers, dependency extras and compatible wheel tags. CI
  checks its lock hash and regeneration parity. This was not a clean-install
  bandwidth or disk-usage measurement on all three operating systems.
- The setup layout was inspected with all three platform manifests in an
  isolated preview; no dependency installation was run. The desktop free-space
  probe was exercised on macOS. Windows and Linux live installation remain
  unverified here.
- UI-only wording adds preflight, engine deployment, warm-up and mission
  language. These labels never enter the ordinary model prompt.
- Six included fictional styles are available in Personas: J.A.R.V.I.S.,
  F.R.I.D.A.Y., Vision, E.D.I.T.H., Ultron and Iron Man. They are original
  interpretations with Disney/Marvel inspiration links. Selecting a template
  opens editable instructions with no model chosen. Saving and starting remain
  explicit user actions. No preset is enabled in ordinary Chat or Chisel.

## Search recovery

The reproduced GPU benchmark lookup encountered a DuckDuckGo Lite challenge
(HTTP 202) and generic NVIDIA/RTX results from Bing RSS. The public DuckDuckGo
HTML layout returned actual RTX 5090 Blender sources, including Blender Open
Data. Search now tries HTML before falling back to Lite; provider results are
still checked rather than treating a challenge page as evidence.

Search wrappers and native lookup failures are structured data. A failed native
lookup reaches the model as `lookup_failed`, allowing a refined query within the
existing bounded round limit. Context fitting retains valid structured data and
source URLs. No provider-specific identity, date, or behaviour prompt is added.
Public provider availability remains outside the application's control.

After these changes, the installed local build answered an explicit model-name
question with Qwen3.5. This successful short exchange does not invalidate the
earlier multi-turn identity failure or establish universal identity retention.
The same installed app then searched `RTX 5090 Blender benchmark results`, read
two requested article URLs and returned a source link with a visible retrieved
sources status. No model identity instruction or second set of model weights
was used.
The supplied Alpha/Beta/Gamma values rendered as a graph with the smaller schema,
and a subsequent model-name question still returned Qwen3.5 after both web and
chart tool use. These live requests ran sequentially on one resident model.
