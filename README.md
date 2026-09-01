# Public Flight Search

A generic, runtime-configured flight and holiday reporting engine designed for
standard GitHub-hosted runners in a public repository. Personal routes, dates,
party details, recipients and mail credentials are never committed: production
jobs receive them through encrypted GitHub Actions secrets.

The engine has three boundaries:

- `ci.yml` runs synthetic tests on pushes and pull requests without secrets.
- `flight-digest.yml` performs bounded Google Flights results-page searches on
  schedule or manual dispatch.
- `holiday-planner.yml` creates a precise provider-entry checklist for private
  destination, date, room and flight-time preferences.

No workflow uploads reports or raw provider data as public artifacts. Reports
are delivered directly by SMTP only when a scheduled or explicitly non-dry
manual run is enabled.

## Evidence semantics

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

For a runtime-configured local dry run:

```bash
python -m pip install -e .
FLIGHT_SEARCH_CONFIG_JSON='{...}' \
  python -m public_flight_search flight-digest --dry-run
```

Dry runs print structural counts only. They do not print the private
configuration, report body or recipient.

## Runtime configuration

`FLIGHT_SEARCH_CONFIG_JSON` accepts a `report_title` and 1–20 search objects.
Each search defines a generic key/label, origin and destination airport lists,
ISO dates, traveller count, cabin, departure time window, stop/duration limits
and an optional per-traveller ceiling.

`HOLIDAY_SEARCH_CONFIG_JSON` accepts a report title, party/room occupancy,
origin airports, outbound/return ISO date lists, a preferred departure window,
and destination labels/airport lists.

The public workflow expects these encrypted secret names:

- `FLIGHT_SEARCH_CONFIG_JSON`
- `HOLIDAY_SEARCH_CONFIG_JSON`
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`
- `REPORT_RECIPIENT`
- `FLIGHT_EMAIL_SUBJECT`, `HOLIDAY_EMAIL_SUBJECT`

Schedules are controlled by non-secret booleans:

- `ENABLE_FLIGHT_DIGEST`
- `ENABLE_HOLIDAY_PLANNER`

Keep both false until a manual dry run passes and a separately approved live
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
