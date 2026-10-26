# Business-class deal watch

`python -m public_flight_search business-deals [--config FILE] [--history FILE] [--offers FILE] [--dry-run]`

A daily job that watches long-haul (strictly over 8 hours) business-class fares from home airports and from cheaper
positioning airports, and sends an e-mail only when a fare is a special deal. No deal means no e-mail and one log line.

* **Fares** are read with the package's existing Google Flights reader, one way, per person, GBP, at least ten
  seconds apart. A challenge page is recorded as a wall; after `stop_after_blocked` consecutive walls or failures the
  run stops. Nothing is solved, no account is used.
* **Rotation.** Each run reads `max_searches_per_run` searches from the origin x destination x date grid, advancing
  one slice per day, so the whole grid is covered every `ceil(grid / max_searches_per_run)` days (the log line prints
  it). Keep the grid small enough that a route-month is read at least `min_observations` times in a few weeks.
* **History** is append-only JSONL (`BUSINESS_DEALS_HISTORY`, default `data/business_deals_history.jsonl`), at most one
  row per route and day. Alerts sent are kept beside it in `<name>_alerts.jsonl`. Neither file is shipped.
* **A deal** is a total (fare plus the origin's `positioning_gbp`) that is at least `median_drop_pct` below the median
  for the same origin, destination and departure month over `median_window_days` (needs `min_observations` earlier
  readings), or at/below the `absolute_caps_gbp` for its region. A positioning origin must also beat the best
  home-airport total for the same destination and date by `away_min_saving_pct`; with no home price to compare it can
  only fire on the cap. Until the history is warm, only caps can fire and the e-mail says so.
* **De-duplication.** The same route and date is not mailed again within `dedupe_days` unless the total drops by at
  least `redrop_pct`. A failed send records nothing, so the next run retries.
* **Delivery** uses `mailer.send_html`: `SMTP_USER`, `SMTP_PASSWORD`, `REPORT_RECIPIENT` (and optionally `SMTP_HOST`,
  `SMTP_PORT`) come from the runtime environment. The real origins, positioning costs and caps belong in the
  `BUSINESS_DEALS_CONFIG_JSON` secret; `examples/business_deals_config.json` is illustrative.
* `--dry-run` prints the e-mail that would be sent and writes and sends nothing (in GitHub Actions with a private
  config, the `BUSINESS_DEALS_CONFIG_JSON` secret or a `--config` file, it prints only the deal count: the Actions log is public); `--offers FILE` serves fares from a
  local JSON list instead of the network. Exit code 2 means a deal was found but the mail failed.

**Schedule.** `.github/workflows/business-deals.yml` runs it daily at 06:17 UTC on a standard runner. History and
the sent-alerts log are seeded from and committed back to the private data repo over `HISTORY_DEPLOY_KEY` (as the
July planner does), so de-duplication holds across days. Without the `BUSINESS_DEALS_CONFIG_JSON` secret it watches
the committed example config. Set the repository variable `ENABLE_BUSINESS_DEALS` to `false` to stop it; a manual
dispatch defaults to a dry run.
