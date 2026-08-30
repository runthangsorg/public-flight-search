# Public Flight Search

A small provider-neutral engine that validates, filters, and ranks flight-offer
JSON. It uses only the Python standard library and never claims that a scraped
or provider-supplied result is verified.

This repository intentionally contains no personal routes, dates, party sizes,
budgets, recipients, browser profiles, API credentials, operational results, or
history from another repository. The scheduled public workflow runs only the
synthetic example. A private caller can supply its own local file or HTTPS
provider endpoint without committing that input.

## Run

Python 3.9 or newer is required.

    PYTHONPATH=src python -m unittest discover -s tests -v
    PYTHONPATH=src python -m public_flight_search \
      --source examples/offers.json \
      --origins AAA --destinations BBB --max-stops 1

The source must be a JSON list, or an object with an offers list. Each offer
uses origin, destination, departure, price, currency, stops,
duration_minutes, and provider; an HTTPS booking_url is optional. Network
sources are HTTPS-only, time-bounded, and limited to 1 MB.

Every result carries review_status: unverified_provider_result. Confirm
prices, availability, baggage, and booking terms with the provider before
purchase.

## GitHub Actions

The workflow has read-only permissions, pinned actions, a five-minute timeout,
no secrets, no artifacts, and one concurrency slot. Its daily schedule is a
health check, not a personalized search.

## License

MIT
