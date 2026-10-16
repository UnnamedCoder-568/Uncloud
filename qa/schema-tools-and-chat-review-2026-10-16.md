# Schema tools and chat verification — 2026-10-16

The local macOS build renders a requested bar graph directly in Chat from a
native `render_bar_chart` call. The visible Alpha/Beta/Gamma bars retain the
supplied values 12/8/15. Rendering ends that chart-only turn without another
model generation. Invalid data allows one structured correction, then stops.

The tool registry contains four function schemas, 924 bytes, and no description
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
- 1,143 backend tests passed; one skipped. 219 frontend tests passed.
- Python lint, production frontend build, macOS application build and resource
  manifest verification passed. Frontend lint completed with existing warnings
  in other components.
- Automated tests cover count/generation tool parity, bounded correction,
  literal-data validation, attachments and chart rendering. They do not prove
  live Windows GPU/context behavior or live Chisel execution.

## Unresolved identity behavior

On the final local build, short sequential conversations with chart tools
available reproduced a Google identity claim both with Web disabled and enabled.
The sequence was `Hello`, `Who am I speaking with?`, `What is your model name?`.
No search call occurred. Earlier fresh identity questions could identify Qwen
correctly. Sanitizing tool syntax does not establish reliable model identity
retention, and this change does not claim to fix it. No corrective identity
prompt, forced model answer, or sampling change was added.

Tool selection and generated values remain model-dependent. The renderer checks
structure and numeric values; it does not verify factual benchmark claims.
