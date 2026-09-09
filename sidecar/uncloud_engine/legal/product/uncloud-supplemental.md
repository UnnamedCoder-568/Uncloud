---
id: uncloud-supplemental
title: Uncloud Supplemental Terms
version: 1
effective: [[EFFECTIVE_DATE]]
accepted_from: 1
product: uncloud
requires_agreement: true
---

> **This is an unreviewed draft.** Every `[[PLACEHOLDER]]` must be supplied
> before publication, and the whole document needs a lawyer. What it says about
> the software's behaviour was checked against the code.

These terms add to the Uncloud Core Terms for the **Uncloud** application.

## 1. The agent, and what it can reach

Uncloud includes an agent that can act on your computer on your behalf. Given
permission it can read and write files, run shell commands, control a browser,
and reach the network.

This is the most consequential thing in the software, so it is stated plainly:

* **Every category of action is under your control**, and the defaults are
  conservative. Reading is allowed; writing asks the first time; deleting and
  running shell commands ask **every** time and cannot be granted for a
  session. That last restriction is deliberate and is not a setting — a
  standing "yes" to arbitrary shell commands is not something this software
  will offer.
* **Agreeing to these terms grants none of it.** Consent to a document and
  approval of an action are separate systems. Accepting this page authorises
  nothing.
* **A record is kept.** Consequential actions are written to an audit log on
  your machine, describing what was done rather than the content it was done
  to. It is yours, it is local, and it is not transmitted.

## 2. What the agent does is your responsibility

An agent acting on instructions can still do the wrong thing: models
misunderstand, and a plausible plan can be a bad one. Approval prompts exist so
that a person is between the model and anything that is hard to undo, and you
should read them.

Do not grant permissions you would not grant a new colleague on their first
day, and keep backups of anything you would mind losing. We are not liable for
the consequences of actions you approved.

## 3. Skills

Skills are reusable procedures, written in plain language, that you or somebody
else can add. A skill is instructions, never code, and it cannot grant itself
anything: what it may do is decided by your permissions at the moment it runs,
and a skill that needs a shell command will prompt exactly as anything else
would.

A skill you obtained from somebody else is text they wrote and you are running.
Read it first.

## 4. Training

Uncloud can fine-tune a language model on your own data, locally. Your training
data stays on your machine; nothing about a training run is transmitted.

An adapter produced this way is yours. It is derived from the base model, and
the base model's licence governs what you may do with the result — a permissive
base does not become restrictive, and a restrictive one does not become
permissive because you trained on it.

## 5. Support

**[[SUPPORT_EMAIL]]**. **[[SUPPORT_TERMS]]**.
