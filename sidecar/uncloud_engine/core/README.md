# Uncloud Core

The layer both products are built on. **Every file in this directory is
byte-identical in the Uncloud and Uncloud Studio repositories.**

```
python scripts/sync_core.py --check   # what has drifted
python scripts/sync_core.py           # copy this repository's over the other's
```

`tests/test_core.py` fails the build if they diverge. It walks the tree rather
than checking a list of filenames, because a list is the thing nobody updates
when they add a module.

## The rule

**Core may be imported by a product. Core may never import one.** A test
asserts this by parsing, in both directions. It is what lets the same bytes run
under two applications with different databases, different config locations,
and different ways of asking a person a question.

Where Core genuinely cannot know something, the product installs it:

| Seam | Installed by | Why Core cannot know |
| ---- | ------------ | -------------------- |
| `integrations.credentials.configure(dir)` | each product at start-up | Uncloud keeps state in `~/.uncloud`, Studio in its own app-data directory |
| `integrations.registry.install_approver(fn)` | each product at start-up | asking a person is an HTTP 428 here and something else elsewhere |
| `recipes.Store` | each product | Studio has a per-project database; Uncloud has a settings file |
| `legal.terms.Store` | each product | same |

Core **raises** rather than allowing when a seam was never wired. A framework
whose approval hook was never installed would execute everything silently and
look exactly like the system working.

## What is here, and what is deliberately not

| Module | Holds | Does not hold |
| ------ | ----- | ------------- |
| `capability.py` | the model vocabulary — what a model can do, costs, licence terms | any catalogue; each product projects its own onto this |
| `permission.py` | risk categories, policy, the gate, the audit log | how a person is asked |
| `effort.py` | how hard to try, translated per model | which model |
| `evaluation.py` | evaluators, weighting, floors, coverage, regression | what to measure — Studio scores logos, Uncloud scores task success |
| `hardware.py` | what this computer **is** | what it is **for** — Studio's tier and Uncloud's generation budget are product policy |
| `recipes.py` | identity, provenance and trust for a saved thing | its shape; Studio's are learned settings, Uncloud's are written steps |
| `legal/` | terms, versioned consent, model-licence disclosure, notices | any grant of permission — see below |
| `auth/` | OAuth, tokens, refresh, connection state | any provider's OAuth client. Uncloud ships none |
| `integrations/` | the capability vocabulary, the registry, the providers | Studio-specific creative actions |
| `mcp/` | MCP client, lifecycle, risk inference | a second security model |

## Three separations worth understanding

**Consent is not permission.** Agreeing to the terms grants the agent nothing.
`legal/` and `permission.py` never import each other, and a test holds them
apart — both are a recorded yes, which is exactly why the wall has to be
structural rather than remembered.

**A connection is not a permission.** Connecting an account says the provider
will answer. Whether the agent may send an email is decided by the gate, at the
moment of the action, every time. A skill or recipe naming an integration
inherits nothing.

**Detection is not policy.** Core says a machine has 24 GB of unified memory.
What that means — which models to suggest, how large a render to plan — belongs
to whichever product is asking.

## Capabilities

Integrations expose capabilities; capabilities are implemented by actions;
actions are governed by the gate and, where they change something, previewed
first.

```
orchestrator asks for   email.send
registry answers with   whoever is connected and able
gate is asked about     that provider's action, at its own risk category
```

Risk is **derived from the capability**, so two providers implementing the same
thing cannot end up under different policies. Anything reaching another person
is `MESSAGE` rather than `WRITE`: an email cannot be unsent, and the recipient
is not the user.

MCP tools do not map onto this vocabulary — a server can do anything — so they
are registered under a coarse capability and classified individually, with an
override that can only ever tighten.

## Adding a provider

1. Subclass `Integration` in `integrations/providers/`.
2. Declare `Action`s, each naming a `Capability`. Do not declare a risk; it is
   derived.
3. Implement `run()`, and `preview()` for anything that writes.
4. Add it to `registry._providers()`.

Nothing else changes. No planning code learns its name, and that is the point.
