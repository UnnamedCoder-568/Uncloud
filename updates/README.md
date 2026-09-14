# Notices for installed copies of Uncloud

`uncloud.json` is read by every installed Uncloud that has update checks on,
from `raw.githubusercontent.com/UnnamedCoder-568/Uncloud/main/updates/uncloud.json`.
A commit to `main` is how a notice reaches people — no release needed.

It is **data, never instructions**. The app validates every field, shows what
passes, executes nothing, and opens no link unless a person clicks it. A
malformed item is dropped; a malformed file leaves every install as it was.

New *versions* of the app are not announced here. Those are found by the
built-in updater from the signed `latest.json` attached to each GitHub release
(see `docs/UPDATES.md`). This file is for everything else.

## An item

```json
{
  "id": "2026-10-ltx-memory",
  "kind": "announcement",
  "severity": "recommended",
  "title": "LTX Video needs 2 GB more than it says on this machine",
  "body": "Until 0.4.1, choose Balanced rather than Sharp.",
  "url": "https://github.com/UnnamedCoder-568/Uncloud/releases",
  "appliesFrom": "0.3.0",
  "appliesTo": "0.4.0",
  "expires": "2026-12-31"
}
```

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Stable. Dismissals are remembered by it — change it and everyone sees the notice again. |
| `kind` | yes | `patch`, `minor`, `hotfix` (a newer app exists), `runtime`, `model`, `announcement`, `major_announcement` |
| `title` | yes | One line. |
| `body` | no | A few sentences. Plain text. |
| `severity` | no | `optional` (default), `recommended`, `critical`. **Critical cannot be dismissed** unless `"dismissible": true` is set. |
| `version` | for app kinds | Must be newer than the running app, or the item is dropped — a replayed old file cannot walk anyone backwards. |
| `url` | no | Only `https://github.com/…` or `https://uncloud.com/…` are shown; anything else is removed. |
| `appliesFrom` / `appliesTo` | no | Inclusive version range the notice is for. |
| `expires` | no | `YYYY-MM-DD`. After it, the notice stops showing by itself. |
| `minimumSupportedVersion` | top level | Installs below it are told they are unsupported. |
