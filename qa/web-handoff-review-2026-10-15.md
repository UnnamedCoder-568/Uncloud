# Web availability and model handoff — v0.4.34

## Reproduced cause

There was no iPhone-specific production condition. The application used a
keyword classifier to prefetch searches for certain wording, including
specification questions. It missed “look it up.” The same classification also
gated both the lookup instructions and execution of model-requested lookups.
Consequently an otherwise valid model request could be discarded without ever
contacting a provider. A custom system instruction also replaced the lookup
contract. Separately, “Explain a binary search tree” caused an unwanted fetch
because its text contained “search.”

Six interface checks failed against the previous source and passed after the
fix. These are functional before/after results, not a model speed benchmark.

## Change

- Removed the search topic/keyword classifier and its greeting exceptions.
  With Web on, the current model receives a short optional search/read contract
  and its requests are processed regardless of the user's topic or wording.
- Ordinary answers finish in one model pass with zero web requests when the
  model does not request a lookup. No separate routing model or planning pass
  is introduced. An explicit source URL read still has its existing direct
  path. Natural-language search decisions, including follow-up interpretation,
  belong to the model with the actual conversation.
- The contract says to answer directly when no lookup is needed. It does not
  require every turn to search. Custom user instructions are retained beside
  the enabled capability contract.
- Completed lookups remain deduplicated. After the existing bounded lookup
  allowance, one final answer pass removes the lookup contract; another request
  cannot restart an indefinite loop. Reasoning text never executes a lookup.
- Web off and raw mode block model lookup requests. The backend's network
  permission gate remains in place. No Chisel code, model sampler, thinking
  budget, context limit or model-loading behavior was changed.
- Native-template counting includes the actual lookup contract and fitted
  evidence. Retrieved evidence remains attached to the saved user turn.

Chat currently uses its existing text-marker handoff for compatibility with
local servers. This change does not claim to implement native function calling
for every model/backend. A checkpoint must still follow the exposed contract;
the application no longer prevents it from doing so based on keywords.

## Verification

The mounted Chat view uses mocked inference and network APIs, with actual
message assembly and handoff logic. Tests cover:

- Model-requested searches for Neptune, James Webb, sourdough and iPhone topics.
- “Look it up” after an earlier conversation turn, without reconstructing the
  subject through an application keyword list.
- Zero lookups for direct model answers to greetings, coding, array search,
  specification drafting and questions about this conversation.
- Search availability alongside custom system instructions.
- Web off, raw mode and private-reasoning markers producing no network calls.
- A model-requested source read, direct supplied-URL read, duplicate lookup
  suppression, visible provider failure, evidence fitting and persistence.

Frontend: **167 tests / 21 files passed**; lint and production build passed.
Exact staged release source: **1,090 backend tests passed, 3 skipped**. The
desktop shell's five tests, Python lint and release-resource checks passed.
Raw captures are local, ignored files rather than public repository artifacts.

## Live provider checks

The configured search providers are DuckDuckGo Lite and Bing RSS. Yahoo and
Google are not configured search providers in this path. Three sequential
provider checks, without any model inference, returned readable results:

| Fixed query | Search time | Accepted hits |
|---|---:|---:|
| Python asyncio documentation | 440 ms | 1 |
| Mars orbital period NASA | 780 ms | 6 |
| Kerala tourism official | 761 ms | 8 |

A separate full Mars lookup, including destination-page reads, took 12,784 ms:
three page excerpts and one snippet-only fallback. Search availability and
destination-page latency are distinct. No reduction in that page-read latency
is claimed by this routing fix. Results describe this network at the time of
the check, not every location or future provider availability.

No model was loaded, stopped, or queried for these checks. One existing model
remained resident; the user's Chrome session was not operated. The interface
tests establish dispatch and permission behavior for supplied model outputs,
not universal model judgment or intelligence. Models may still choose a lookup
poorly; the Web switch is the absolute control over this Chat capability.
