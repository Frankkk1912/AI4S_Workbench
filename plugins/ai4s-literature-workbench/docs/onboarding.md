# API onboarding

AI4S Literature Workbench can run its basic literature workflow without API
credentials. The first Agent interaction reports the local configuration
status and offers three optional enhancements:

| Provider | Application page | Enhancement |
| --- | --- | --- |
| Zotero Web API | <https://www.zotero.org/settings/keys> | Cloud library identity and permitted item, tag, note, or file operations |
| PubMed / NCBI | <https://www.ncbi.nlm.nih.gov/datasets/docs/v2/api/api-keys/> | Higher E-utilities allowance and more stable batch retrieval |
| EasyScholar | <https://www.easyscholar.cc/> | Journal rank and metric enrichment; after login use the personal dashboard's `开放接口` entry |

For Zotero, enable library access. Enable write access when the Agent should
create or update items, tags, or notes; enable file access when attachment
upload is required. Group-library permissions are reported separately from the
personal-library capabilities returned by Zotero.

## Zotero Desktop XPI reminder

The credential wizard and MCP do **not** install Zotero Desktop add-ons. To
show AI4S metrics, Agent Tags, AI Summary, and the interactive Priority column,
build the separate `source/literature-metrics` add-on from a repository clone, then in
Zotero Desktop choose **Tools → Add-ons → gear menu → Install Add-on From
File…** and select `source/literature-metrics/dist/literature-metrics-<version>.xpi`.
The redacted onboarding status reports this as `zotero_desktop_xpi`; the Agent
must remind the user during first-run onboarding.

## Safe local setup

Never paste an API key into Agent chat or pass it as a command argument. From
the installed plugin directory, run:

```bash
node scripts/onboard.mjs setup --output onboarding-result.json
```

PowerShell uses the same arguments:

```powershell
node .\scripts\onboard.mjs setup --output .\onboarding-result.json
```

The terminal masks input. Each credential is validated once before it replaces
an existing setting. An invalid credential is not saved. A temporary network
failure does not invalidate or overwrite an existing setting. Every provider
can be skipped.

The JSON result contains only configuration and capability status; it never
contains credential values. Reconfigure one provider later with:

```bash
node scripts/onboard.mjs reconfigure --provider zotero --output onboarding-result.json
node scripts/onboard.mjs reconfigure --provider pubmed --output onboarding-result.json
node scripts/onboard.mjs reconfigure --provider easyscholar --output onboarding-result.json
```

Inspect status without making a network request:

```bash
node scripts/onboard.mjs status --output onboarding-status.json
```
