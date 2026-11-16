# Job Hunter Bot

A Python application that checks company career sites for relevant software
engineering jobs and sends newly discovered matches to Telegram. Its current
filters focus on Java, backend, software engineering, and related roles in
Mumbai and Bengaluru, while also allowing configured India-wide and remote
listings.

The project runs as a command-line app, commonly through GitHub Actions. It
does not have a web interface or a database: configuration and persistent run
state are stored in JSON files in the repository.

## How a job run works

The main entry point is `python -m src.main`.

1. Load and validate company records from `config/companies.json`.
2. Select enabled companies whose provider has a supported adapter.
3. Fetch job listings concurrently from each company's ATS.
4. Convert provider-specific responses into the common `Job` model.
5. Apply title, location, and seniority filters from `config/keywords.json`
   and `config/settings.json`.
6. Optionally inspect a limited number of promising near-miss job descriptions
   for backend technology signals. Promotion is conservative and does not
   bypass the hard location, exclusion, or seniority filters.
7. Compare matching jobs against `data/seen.json`, using each job URL for
   deduplication.
8. Sort new jobs by configured location priority and posting date, split them
   into Telegram-safe batches, and send them.
9. Record successfully delivered jobs as seen. Stale ATS mappings may be
   rediscovered; retry cooldowns are stored in `data/recovery.json`.

## Technologies and project layout

- Python 3.15 is the project's only tested and supported runtime.
- Pydantic for validating and normalizing models.
- Requests for ATS, job-description, and Telegram HTTP requests.
- Beautiful Soup for HTML-based research and probing.
- pytest for automated tests.
- GitHub Actions for CI and workflow automation.

Important directories and files:

| Path | Purpose |
|---|---|
| `src/main.py` | Main job-fetch, filter, deduplication, and notification pipeline |
| `src/providers/` | ATS adapters that fetch and normalize provider listings |
| `src/filters.py` | Keyword, location, and seniority filtering |
| `src/description_diagnostics.py` | Description checks for selected near-miss jobs |
| `src/notifier.py` | Telegram delivery and message-size validation |
| `src/store.py` | Persistent seen-job state |
| `src/recovery_store.py` | Persistent stale-provider retry cooldowns |
| `models/` | Pydantic models for jobs, companies, providers, and registry |
| `research/` | ATS discovery, validation, and research probes |
| `config/` | Company registry and filtering/runtime settings |
| `data/` | JSON state carried across runs |
| `tests/` | Unit and integration-style tests with provider fixtures |

## ATS support

The application has adapters for these provider types:

**Greenhouse, Lever, Ashby, Workday, Atlassian, SmartRecruiters, Oracle,
Higher, SuccessFactors, TalentBrew, Algolia, Bank of America, PhonePe, Keka,
Kula, Eightfold, Cognizant, Zoho Recruit, Fynd, Infosys, HCLTech, and IBM.**

Provider configuration is company-specific and stored in
`config/companies.json`. The separate `research/` tools support ATS discovery
and probing for diagnostics and stale-provider recovery. Not every provider
type is automatically discoverable.

If a Workday location-detail request exhausts its retries with HTTP 429, the
company stops submitting new detail requests while in-flight requests finish.
Unresolved and unstarted locations are reported as partial enrichment.
Workday's time budget is checked before dispatch, but a thread can be delayed
after the check and in-flight requests are not cancelled at the deadline.
Per-host pacing spaces admissions, not necessarily actual HTTP start times.

Eightfold (Microsoft) honors a numeric or HTTP-date `Retry-After` up to 60
seconds (plus a 0.5-second margin); missing, negative, NaN or malformed values
use the 15-second default, and a longer or infinite request is deferred as a
temporary failure instead of being waited out or shortened. The whole company
fetch has a 420-second monotonic budget: no request or wait is scheduled that
cannot fit, request timeouts are capped by the remaining time, and a deadline
or long `Retry-After` failure never returns partial inventory. A response that
is already in flight when the budget ends is still used, so the budget can be
overshot by at most one request. Pagination and completeness checks are
unchanged.

Each Eightfold fetch prints one `[EIGHTFOLD] <company>: accounting` line with
`status` (`complete`, `failed` or `parse_failed`), pages received, raw records,
duplicate and unique job IDs, the first/last/min/max reported totals and, after
parsing, parsed and skipped records by category (`missing_id`, `missing_title`,
`missing_url`, `invalid_record`), final jobs and unique URLs. It contains counts
and category names only and adds no requests. A `failed` line reports the
progress made before the failure; the failure itself is unchanged and no
partial inventory is accepted.

IBM and HCLTech print one pagination summary per attempted search term, including
failed terms. `pages` counts responses received, `raw_records` counts records
in validated lists, and `processed_records` counts records accepted for
deduplication; these can differ on a failed page. Duplicate counts cover
processed records. The run-level `[SELECTION]` summary reports globally unique
matching and seen URLs alongside the sums of per-company unique and seen URL
counts; cross-company overlaps can make those sums larger.

## Configuration and state

| File | Purpose |
|---|---|
| `config/companies.json` | Company details, enabled flag, ATS type/configuration, career page, and job metadata |
| `config/keywords.json` | Job-title phrases to include and exclude |
| `config/settings.json` | Allowed locations, excluded seniority, worker count, recovery cooldowns, Workday pacing/retries/time budget/backoff, notification priority, and batch size |
| `data/seen.json` | URLs of jobs already notified |
| `data/recovery.json` | Provider recovery failures and retry times |

The current location settings prioritize Mumbai/Navi Mumbai and Bengaluru/
Bangalore. They also allow India-wide jobs, Remote India, and plain Remote.
The configured title exclusions include internships, mobile, QA/testing,
support, sales, management, and several other unrelated or senior roles.
Adjust the JSON configuration to change these rules.

## Running locally

Requires Python and the dependencies in `requirements.txt`.

```bash
python -m pip install -r requirements.txt
python -m pytest -q
python -m research.main
python -m src.main
```

Set these environment variables before running the bot if it needs to send a
Telegram notification:

```bash
export TELEGRAM_TOKEN="<your Telegram bot token>"
export TELEGRAM_CHAT_ID="<your chat or channel ID>"
python -m src.main
```

The application only calls Telegram when there are new matching jobs to
notify. Keep the token secret; do not put it in the repository.

## GitHub Actions

| Workflow | Trigger | Purpose |
|---|---|---|
| `ci.yml` | Pushes and pull requests to `main` or `master` | Runs tests and validates the registry |
| `jobs.yml` | Dispatched by the external Cloudflare cron job or manually | Runs the bot and commits updated `data/seen.json` and `data/recovery.json` |
| `company-probe.yml` | Manual dispatch | Runs a selected company/ATS research probe |

Cloudflare runs the external cron schedule and dispatches the `jobs.yml`
GitHub Actions workflow. The cron schedule and Cloudflare configuration live
outside this repository; this repository contains the workflow that runs the
bot. `jobs.yml` also offers a validation-only manual dispatch option for
checking that the external scheduler can reach GitHub Actions.

For a small read-only Workday rate-limit sample, run
`python -u -m research.company_probe --workday-rate-limit-sample` or manually
dispatch `company-probe.yml` with `workday-rate-limit-sample`. It checks the
verified registry mappings for Postman, BrowserStack, Baker Hughes and Duck
Creek, then sends at most one listing request per company, five seconds apart.
It stops on the first HTTP 429 or request error, does not follow redirects or
retry, and reports only a restricted set of rate-limit headers. It does not
read or write bot state or send notifications. Connect/read timeouts are 5/10
seconds per request; DNS and transport behavior can exceed these timeouts.
This mode makes real public requests only when explicitly invoked.

Each sample line also reports the listing `offset` (always 0), a coarse
`response_class` derived only from the status and media type (for example
`rate_limited/html`), the bare `content_type` and `content_length`, and an
`identification` object holding allowlisted `Server`, `Via`, `Date` and
request/CDN identifier headers. Values that are missing are omitted; values
that are too long or contain unexpected characters print as `<omitted>`.
Response bodies, cookies and credentials are never printed. These fields are
evidence only: no single header identifies who generated a response.

Unlike the production Workday client, the sample ignores environment proxies,
netrc credentials, and environment CA-bundle overrides; it does not follow
redirects and uses shorter timeouts. Its network path and outcomes can
therefore differ from production. Requests may consume a redirect response
body internally even though the sample does not print it.

Configure these GitHub repository secrets for Telegram delivery:

- `TELEGRAM_TOKEN` — bot token from [@BotFather](https://t.me/BotFather)
- `TELEGRAM_CHAT_ID` — destination chat or channel ID

## Adding a company

Add a record to the `companies` array in `config/companies.json`. Provider
mapping must be done manually: identify a supported ATS and configure its
provider type and required fields. Use a category supported by
`models/company.py` and a valid career-page URL. For example, a Greenhouse
company needs its board slug:

```json
{
  "id": "acme",
  "name": "Acme Corp",
  "category": "SaaS",
  "priority": 2,
  "enabled": true,
  "career_page": "https://www.acmecorp.com/careers",
  "provider": {
    "type": "greenhouse",
    "status": "verified",
    "config": {
      "board": "acme"
    }
  },
  "locations": ["Bengaluru"],
  "roles": ["backend"],
  "supports_remote": false,
  "notes": ""
}
```

Validate the provider configuration before enabling the company. Companies
with `unknown` providers or without an implemented adapter are not fetched by
the main job run.
