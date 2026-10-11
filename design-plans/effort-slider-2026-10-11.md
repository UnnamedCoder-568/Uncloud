# A visible, truthful thinking-effort slider

Written against: eb204e413a1810c46a275e54da0a8e3b7bbe0ef7

## Evidence chain

- Surface: `uncloud/src/components/InferenceControls.tsx`, reached from Chat settings and Chisel.
- Problem: the user requested a slider; the previous selector exposed a binary model toggle as High without a separate thinking allowance.
- Design evidence: existing shared Model controls, range controls elsewhere in the app, and `--accent`, `--text-dim`, `--text-faint` tokens.
- Owner: the shared InferenceControls component.
- Scope and affected surfaces: Chat settings, Chisel model controls, Guide.
- Uncertainty: adjustable effort depends on discovered native runtime support; unavailable modes must not appear enabled.

## Design decision

Use a native range input with discrete levels supplied by the active backend. Show the selected level beside its label, and the effective thinking allowance below it. A binary backend exposes Auto / Off / On. An unsupported backend remains disabled. Selecting effort clears an explicit thinking-token override and says so; it must actually change the request.

## Reuse

- Existing shared component and theme tokens; no new control panel or color system.
- Exemplar: native range inputs used by the app's media controls.

## Changes

1. `uncloud/src/components/InferenceControls.tsx`
   - Change: replace the reasoning selector with the capability-driven range and accessible current value.
   - Preserve: saved model/conversation settings, explicit overrides, presets and native-template ownership.
   - Verify: bounded, binary and unsupported profiles; no fabricated native graded modes.
2. `uncloud/src/index.css`
   - Change: small shared effort-slider styling using the existing accent.
   - Preserve: focus behavior and native keyboard interaction.
3. `uncloud/src/views/GuideView.tsx`
   - Change: explain where the slider is and how explicit limits interact with it.

## Scope

- Inherit: Chat and Chisel.
- Verify: compact and full control layouts.
- Exclude: unrelated legal edits and earlier sidebar/design proposals.

## Validation

- Product: selected effort reaches the actual model request; High leaves room for a completed answer.
- Interface: readable current value, keyboard-adjustable native range, unsupported levels disabled.
- System: shared component remains the single owner; token counts come from the request budget and native boundary.
- Repository: `npm test`, `npm run build`, backend reasoning/capability regression tests.

## Stop conditions

- If native budget support cannot be verified, retain only verified binary or native controls.

## Design documentation

- Record measured device checks and limitations in `qa/reasoning-effort-audit-2026-10-11.md`.
