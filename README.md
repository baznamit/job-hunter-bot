# Job Hunter Bot

A Telegram bot that polls ATS job boards (Greenhouse, Lever, Ashby) every 30 minutes and sends alerts for new Java/backend engineering roles in Mumbai or Bengaluru.

## How it works

1. **Fetch** — queries the public ATS APIs for each company in `config/companies.json`
2. **Filter** — keeps only roles matching keyword and location rules (`config/keywords.json`, `config/settings.json`)
3. **Deduplicate** — compares against `data/seen.json` (committed back after each run)
4. **Notify** — sends a Telegram message for any new jobs

## Supported ATS

| Provider   | API endpoint                                          |
|------------|-------------------------------------------------------|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{board}/jobs`     |
| Lever      | `api.lever.co/v0/postings/{slug}?mode=json`           |
| Ashby      | `api.ashbyhq.com/posting-api/job-board/{org}`         |

## Configuration

| File                    | Purpose                                                   |
|-------------------------|-----------------------------------------------------------|
| `config/companies.json` | Company registry with ATS provider slugs                  |
| `config/keywords.json`  | Include / exclude keywords matched against job titles     |
| `config/settings.json`  | Allowed locations, excluded seniority levels, Telegram ID |

## GitHub Actions workflows

| Workflow          | Trigger               | Purpose                                              |
|-------------------|-----------------------|------------------------------------------------------|
| `ci.yml`          | Push / PR             | Run tests and validate registry                      |
| `jobs.yml`        | Every 30 min + manual | Fetch jobs, send Telegram alerts, commit seen.json   |
| `map.yml`         | Manual                | Auto-detect ATS providers for unknown companies      |

## Setup

1. Fork the repo
2. Add two repository secrets:
   - `TELEGRAM_BOT_TOKEN` — from [@BotFather](https://t.me/BotFather)
   - `TELEGRAM_CHAT_ID` — your chat or channel ID
3. Enable GitHub Actions
4. Trigger `Map Companies` once to resolve any `unknown` providers in `companies.json`

## Adding a company

Add an entry to `config/companies.json`:

```json
{
  "id": "acme",
  "name": "Acme Corp",
  "category": "startup",
  "priority": 2,
  "enabled": true,
  "career_page": "https://www.acmecorp.com/careers",
  "provider": {
    "type": "unknown",
    "status": "research_pending",
    "config": {}
  },
  "locations": ["Bengaluru"],
  "roles": ["backend"],
  "supports_remote": false,
  "notes": ""
}
```

Then run the `Map Companies` workflow to auto-detect the ATS provider.
