# Agent instructions — public-flight-search

**This repository is PUBLIC.** Everything here is world-readable, permanently,
including anything you commit by accident and later delete. That single fact
drives every rule below.

## Never commit, to this repository, in any form

- Credentials, tokens, API keys, cookies, session or browser-state files.
- PII: real names, email addresses, phone numbers, home addresses, postcodes,
  passport or ID numbers, customer or donor records.
- Tax, financial, health or benefits data.
- Private URLs, captured provider HTML, logs, screenshots, browser profiles.
- Personalised reports, raw provider data, runtime databases, archived media —
  and never upload any of these as workflow artifacts.

Refer to secrets by NAME only (`SMTP_USER`, `REPORT_RECIPIENT`); the values
live in encrypted GitHub Actions secrets. GitHub *variables* are not secret and
may hold only generic booleans and operating limits.

## What this repo is for

Recurring GitHub-hosted compute for paired flight digests and the December package-holiday finder, on free standard runners
(flight-digest.yml, holiday-planner.yml). Keep it that way: no self-hosted runners, no
credentials in the repo, no personalised output committed.

## External actions default to preview

A run must not send email, publish, or write to a third party unless that
action was explicitly asked for. Dry-run is the default and must stay the
default; `--send` (or equivalent) is opt-in per invocation.

## Before you push

- Run the tests and say what actually happened, including failures.
- Stage only the files you changed; never `git add -A` over someone else's
  work-in-progress.
- Scan the diff for the payload list above. The gate is the CONTENT, not the
  destination — pushing to a repo that is public by design is normal and
  pre-authorised, provided the payload is clean.
