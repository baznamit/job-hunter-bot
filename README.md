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

## Configuration and state

| File | Purpose |
|---|---|
| `config/companies.json` | Company details, enabled flag, ATS type/configuration, career page, and job metadata |
| `config/keywords.json` | Job-title phrases to include and exclude |
| `config/settings.json` | Allowed locations, excluded seniority, worker count, recovery cooldowns, notification priority, and batch size |
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
