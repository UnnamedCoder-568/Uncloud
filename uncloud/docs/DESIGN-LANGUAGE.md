# The shared chassis

Uncloud and Uncloud Ad Studio are separate products with separate codebases.
They are not separate *interfaces*. Someone who has used one should be able to
sit down at the other and already know where everything is.

This document is the contract. `chassis.css` is its executable half and is
**byte-identical in both repositories**. Change it in one place and copy it to
the other in the same commit; never edit one copy alone.

That is enforced, not merely asked for: `engine/tests/unit/test_chassis.py` in
Ad Studio compares the two files whenever both products are checked out side by
side, and *skips loudly* when they are not, rather than passing quietly.

## What we are matching, and what we are not

The reference points are ChatGPT's desktop app and Unsloth's. They do not share
a template — nobody is shipping an "AI app starter". They converge because they
independently reached for the same four things:

| Layer      | What                                                            |
| ---------- | --------------------------------------------------------------- |
| Utilities  | Tailwind CSS                                                     |
| Primitives | Radix UI, usually through shadcn/ui                              |
| Icons      | Lucide — Unsloth's sidebar is Lucide glyph for glyph             |
| Type       | Inter / Geist / SF Pro, 14px for interface text                  |

On top of that sits a layout convention this document calls the **chat shell**.
That is the part worth copying, and it is not anybody's property: a fixed left
rail, an overlay title bar, a centred empty state, and a composer that is a
card rather than a bare input.

What we do **not** copy is identity. The neutral greys below are a chassis, the
same way every car has four wheels. The accent, the wordmark and the voice stay
each product's own — Uncloud's amber, Ad Studio's green. An interface that
matched ChatGPT down to the accent would not read as "familiar", it would read
as "counterfeit", and it is the one thing here that could actually get us sued.

## Ground rules

**Separation is by tint, not by line.** Surfaces differ by a few percent of
lightness. Borders exist but are nearly invisible; they define an edge, they do
not draw one. If you can see a border before you notice the content, it is too
strong.

**Nothing is pure.** No `#000`, no `#fff`. Pure black on an OLED panel makes
every edge vibrate, and pure white text at 14px blooms.

**One accent, used rarely.** In the reference apps the accent appears roughly
twice per screen: the send button, and the user's avatar. Everything else is
grey. An accent that appears eight times has stopped pointing at anything.

**Compact, not cramped.** 36px rows, 14px text, 8px gutters. The density comes
from tight rows, not from small text — shrinking the type to fit more in is how
an interface becomes unreadable at the exact moment it becomes impressive.

## The palette

Dark is the ground state. Both apps run dark by default because both reference
apps do, because generated imagery reads better against it, and because these
are tools people have open at midnight.

| Token             | Dark      | Light     | What it is                        |
| ----------------- | --------- | --------- | --------------------------------- |
| `--sidebar`       | `#171717` | `#F5F5F3` | the left rail                     |
| `--bg`            | `#212121` | `#FFFFFF` | the working area                  |
| `--surface`       | `#303030` | `#F0F0EE` | composer, cards, active nav row   |
| `--surface-hover` | `#3A3A3A` | `#E7E7E4` | hover only — never a resting state |
| `--border`        | `#2F2F2F` | `#E4E4E0` | the invisible edge                |
| `--border-strong` | `#4A4A4A` | `#CFCFC9` | edges that must be seen           |
| `--text`          | `#ECECEC` | `#1B1D1C` | 13.6:1 dark, 16.9:1 light         |
| `--text-2`        | `#B4B4B4` | `#5E6664` | 7.8:1 dark, 5.9:1 light — AA      |
| `--text-3`        | `#8F8F8F` | `#767D7B` | 5.0:1 / 4.2:1 — labels, icons     |
| `--rail-hover`    | `#232323` | `#ECECE8` | a hovered row in the rail          |
| `--rail-active`   | `#303030` | `#DEDED9` | the selected row                   |

The rail has its own hover and active steps because it sits on its own
background. The first version of this reused `--surface` for both, which made
hover and selection render identically, and in light mode made the selected row
almost invisible against the rail. Hover is a hint; active is a statement, and
they must not be the same colour.

Menus are the mirror image: `.menu-row` sits on `--surface`, so it *lightens*
on hover where a rail row darkens. Using a rail row inside a dropdown looks
subtly wrong for exactly that reason.

Light is not an inversion. It is a second palette held to the same contrast
standard, and it must keep working: some people cannot use dark interfaces at
all, and shipping a broken light mode quietly excludes them.

## Geometry

These are the numbers that make two different apps feel like one.

```
sidebar width      260px          collapsed 60px
title bar          44px           drag region, clears the traffic lights
nav row            36px           2px apart, 8px radius
section label      12px           uppercase, --text-3, 8px above its group
icons              18px sidebar   16px inline, 1.75 stroke
composer           768px max      26px radius, 16px padding
composer centred   flex:1, floor 52vh   — the floor is for block parents
composer button    32px circle    accent fill, arrow-up
greeting           30px / 500     centred, ~120px above the composer
content column     768px          the same width as the composer, deliberately
```

The composer and the reading column share a width on purpose. When the first
answer appears, nothing shifts sideways — the text simply arrives above where
the question was typed.

## The chat shell

**Empty**: greeting and composer sit together in the optical centre, which is
slightly above the true centre. There is no scroll region yet, no header rules,
nothing to suggest the page is a form to be filled in.

**Occupied**: the composer docks to the bottom, the greeting is gone, and the
content scrolls behind it. The composer does not move between these two states
by animating across the screen — it is the same component in a different
position, and the transition is a fade.

The composer grows with what is typed, to 40% of the window height, then
scrolls internally. Unbounded growth pushes the user's own work off screen,
which is the opposite of what a bigger field is for.

Enter sends. Shift+Enter is a newline. This is the convention every one of
these apps follows and users have it in their fingers.

## The title bar

macOS gets `titleBarStyle: "Overlay"` and `hiddenTitle: true`, so the traffic
lights float over our own chrome. That leaves a 44px strip we own, laid out as:

```
[ traffic lights ] [ ☰ ] [ ← → ]      [ centre slot ]      [ actions ]
```

The centre slot is the app's current context — the model in Uncloud, the
project in Ad Studio. It is a button, not a label; if it names something the
user can change, it should change it.

The whole strip is `-webkit-app-region: drag`, and every control inside it is
`no-drag`. Forget the second half and the buttons stop being clickable, which
looks exactly like a hung app.

## Where the two apps legitimately differ

Ad Studio carries a project. Its sidebar names the open project at the top and
groups navigation under Project / Create / Library, because the work is
organised around a client. Uncloud has no such object — its rail is a flat list
of capabilities.

That difference is real and should stay. The chassis holds the metrics, the
palette and the shell; it does not flatten the products into each other.
