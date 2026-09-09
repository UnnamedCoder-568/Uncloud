---
id: privacy
title: Privacy Notice
version: 1
effective: [[EFFECTIVE_DATE]]
accepted_from: 1
product:
requires_agreement: false
---

> **This is an unreviewed draft.** Every `[[PLACEHOLDER]]` is a fact that must
> be supplied before publication, and the whole document needs review against
> the privacy law of the jurisdiction it will be published in. What it says
> about the software's behaviour is accurate as of this version and was checked
> against the code, not assumed.

This notice is required reading rather than an agreement. There is no box to
tick: consenting to a description of what software does is meaningless, and
asking you to do it would only teach you to click through the things that
matter.

Published by **[[LEGAL_ENTITY_NAME]]**, **[[REGISTERED_ADDRESS]]**. Privacy
contact: **[[PRIVACY_CONTACT_EMAIL]]**.

## The short version

Uncloud runs on your computer. Your prompts, your files, your projects and
everything the models produce stay on it. We do not collect them, we cannot see
them, and there is no account to attach them to.

**There is no analytics or telemetry in this software.** No usage reporting, no
crash reporting, no error collection, no product analytics. This is not a
setting you have to find and turn off; the code to do it does not exist. You
can verify this — every network destination the software can reach is listed
below.

## What is stored, and where

Everything is on your own computer, in your user directory:

* your projects, and the files in them;
* models you have downloaded;
* settings, including permissions you have granted;
* the record of which terms you have agreed to, and when;
* an audit log of consequential actions the software took, kept so you can see
  what happened. It records what was done, not the content it was done to.

None of this is transmitted. Deleting the application's data directory removes
all of it. Your project files are wherever you put them and are not touched by
that.

## When the software uses the network

Nothing below happens on its own. Each is either something you asked for or
something you switched on.

**Downloading a model.** Contacts the publisher's host — usually
`huggingface.co` — and sends what any download sends: the file being requested,
your IP address, and an access token if you have configured one for a gated
model. Their privacy policy applies to that request, not ours.

**Searching the web.** Only when you have enabled research and a task calls for
it. The search text is sent to the search provider — currently DuckDuckGo. Do
not enable it if your prompts contain anything you would not put in a search
box, because that is exactly what happens to them.

**A remote model, if you configure one.** The software works entirely locally
and ships with no remote provider configured. If you add one, your prompt and
any context the task needs are sent to that provider under their terms. The
interface says when a remote model is being used; it is never a silent fallback
from a local one.

**Software updates.** Checks for a new version and downloads it. Sends the
current version and your IP address.

That is the complete list for the shared software. Where an application adds
its own — activation, for instance — it says so in its own notice, shown
beside this one.

## What we would collect if you contacted us

If you email support, we have whatever you send us: your address, your message,
and any logs or files you choose to attach. Nothing is collected from your
machine automatically to accompany it — if a log would help, you are asked, and
you can read it first.

Retention: **[[SUPPORT_RETENTION_PERIOD]]**.

## Children

The software is not directed at children under **[[MINIMUM_AGE]]**.

## Your rights

Because we do not hold your content, most data-protection rights have nothing
of yours for us to act on — there is no export to give you and no account to
delete. Where we do hold something, such as support correspondence, you can ask
for a copy or ask us to delete it: **[[PRIVACY_CONTACT_EMAIL]]**.

Your legal rights, and the authority you can complain to, depend on where you
live: **[[SUPERVISORY_AUTHORITY]]**.

## Changes

When this notice changes you will be shown what changed. Every version is kept
readable in Settings, so you can see what was true when.
