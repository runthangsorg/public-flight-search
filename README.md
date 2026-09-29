# Public Flight Search

A generic, runtime-configured flight and holiday reporting engine designed for
standard GitHub-hosted runners in a public repository. Personal routes, dates,
party details, recipients and mail credentials are never committed: production
jobs receive them through encrypted GitHub Actions secrets.

The engine has three workflows:

- `ci.yml` runs synthetic tests on pushes and pull requests without secrets.
- `holiday-planner.yml` runs the December package-holiday deal engine:
  benchmark-priced resorts with real discount intelligence versus each
  resort's summer-peak price, the recovered winter-tracker value model
  (mosque access, food-reality, luxury, winter facilities, activities,
  flight quality on a 0-10 scale, weighted into a 0-100 value score with
  honesty caps), per-person deal classification, property-targeted
  Booking.com / Google Hotels / Expedia deep links with exact dates and
  party, per-deal price history with trend chips, and direct SMTP delivery.
- `july-holiday-planner.yml` runs the same engine for the July 2027 trip,
  pricing the committed `examples/july_holiday_config.json` unless a
  `JULY_HOLIDAY_SEARCH_CONFIG_JSON` secret exists.

The September Muscat/UAE flight digest workflow was deleted on 2026-09-28;
its trips had expired.

## Cabin rule and the Far East watch

Owner rule, 2026-09-28: Business class only when the flight is over 8 hours
from London, otherwise Economy; never premium economy. The cabin is derived in
code (`src/public_flight_search/cabin.py`) from each destination's
`flight_hours`: the nonstop block time, or the fastest standard one-stop
journey where no nonstop exists. 8.0 hours exactly is Economy. A config's own
`cabin_class` / `cabin_classes` fields are legacy: still validated, never
priced.

Far East destinations are listed first in both example configs and lead the
report. A destination with no resort in the catalogue is a destination watch:
its row is priced from a Business fare and a family-suite night that are
labelled **benchmark, unverified** until live whole-party evidence exists, with
dated Google Flights, Booking.com and Google Hotels searches.

## July: long-haul, Lombok and Thailand

Owner direction, 2026-09-29: nothing within 6 hours of London; Lombok and
Thailand mostly; no Singapore or Malaysia. The July report therefore prices
`SUMMER_RESORT_CATALOG` (in `holidays.py`): resorts in Lombok, on the Gulf of
Thailand (Koh Samui, Koh Phangan — the drier coast in July) and one on the
Andaman coast (Khao Lak, flagged as monsoon season). A summer trip selects it
in `resort_catalog(config)`, layered over the winter catalogue; a December trip
never sees it, so the December cards and hunt contract are unchanged.

Each summer resort's room rate was read from the hotel's own booking engine or
Google Hotels for the whole party (source and date beside every entry), and is
labelled `estimate` where July 2027 was not yet on sale. Flight benchmarks are
observed whole-party Economy fares; the Business figure is the engine's 2.5x
estimate until a live Business fare replaces it. A long-haul resort that is over
budget is listed with its cheapest price instead of silently dropped, and the
report names every resort whose TripAdvisor rating could not be checked.

Emails are change-driven, not scheduled spam: before building, the job seeds
prior price history from the private data repo and computes a change digest
(drops / rises / new resorts vs the last report). A flat re-quote is
suppressed — it is still tracked and persisted, just not emailed. Sends fire
when something moved, when a new resort enters, on the first ever run, or
when `--force-send` (CLI / workflow_dispatch input) is used deliberately.

No workflow uploads reports or raw provider data as public artifacts. Reports
are delivered directly by SMTP only when a scheduled or explicitly non-dry
manual run is enabled.

## Evidence semantics

Resort prices are market-supported BENCHMARKS (badge: BENCHMARK PRICE) or
live observations (badge: LIVE VERIFIED); discount percentages compare the
December benchmark to the same resort's July/August peak benchmark for the
identical rooms, nights and party. Criteria scores are curated benchmarks
requiring verification — never presented as live observations. Price history
is appended (day-deduped) to the PRIVATE `runthangsorg/dealsearch` data repo
via a write-scoped deploy key; this public tree never gains write access and
never stores personalised data.

Google Flights cards are labelled `results_page_only`. They are useful fare
observations, not checkout verification. The displayed-fare basis can vary, so
the engine preserves the observed amount and never invents a multiplied
whole-party total. Every report states that price, availability, baggage,
connection protection and the final total must be rechecked before purchase.
If provider markup, consent or bot controls prevent
parsing, the report shows official search-entry links and never invents a
price.

The holiday job currently provides official provider entry points and an exact
search brief. It deliberately does not claim a live package price until a
provider adapter has captured valid whole-party evidence.

## Local verification

Python 3.10 or newer is required for the provider-neutral engine; Python 3.12 is
used by Actions.

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m public_flight_search \
  --source examples/offers.json --max-results 2
```

Dry runs print structural counts only. They do not print the private
configuration, report body or recipient.

## Runtime configuration

`HOLIDAY_SEARCH_CONFIG_JSON` accepts a report title, party/room occupancy,
origin airports, outbound/return ISO date lists, a preferred departure window,
a budget, and 1–24 destinations, each with a key, label, airport list,
`flight_hours` and a `flight_hours_source` citation. A destination without
`flight_hours` loads only if its key has a built-in value in `cabin.py`.

The holiday workflows expect these encrypted secret names:

- `HOLIDAY_SEARCH_CONFIG_JSON` (December), optionally
  `JULY_HOLIDAY_SEARCH_CONFIG_JSON` (July)
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`
- `REPORT_RECIPIENT`
- `HOLIDAY_EMAIL_SUBJECT`, optionally `JULY_HOLIDAY_EMAIL_SUBJECT`
- `HISTORY_DEPLOY_KEY`

Schedules are controlled by non-secret booleans:

- `ENABLE_HOLIDAY_PLANNER`
- `ENABLE_JULY_HOLIDAY_PLANNER`

Keep them false until a manual dry run passes and a separately approved live
email has been inspected.

## Security model

- Read-only workflow permissions and SHA-pinned third-party actions.
- Secrets are scoped only to delivery steps. Production workflows have no pull
  request trigger, and fork pull requests run only the secret-free CI workflow.
- No self-modifying commits, caches, uploaded artifacts or captured provider HTML.
- Bounded search count, network deadline, workflow timeout and concurrency.
- Synthetic policy tests reject hard-coded email addresses and postcode-like
  identifiers in production files.

## License

MIT
