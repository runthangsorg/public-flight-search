"""Responsive, email-safe HTML reports with explicit evidence labels."""

from __future__ import annotations

from html import escape
from typing import Any, Mapping, Sequence

from .config import FlightConfig
from .engine import FlightOffer
from .google_flights import build_google_flights_url


def _money(value: float) -> str:
    return f"£{value:,.0f}"


def _render_amadeus_card(offer: dict[str, Any]) -> str:
    per_person = offer.get("price_per_traveller", offer["price"])
    stops_text = "Non-stop" if offer["stops"] == 0 else f"{offer['stops']} stop(s)"
    stop_info = ""
    if offer.get("stop_airports"):
        stop_info = f" via {', '.join(offer['stop_airports'])}"
    baggage = ""
    if offer.get("baggage_included"):
        baggage = f'<div class="baggage">Baggage: {escape(offer["baggage_weight"])}</div>'
    return f"""
      <article class="card amadeus">
        <div class="source-badge">API Quote</div>
        <div class="route">{escape(offer["origin"])} → {escape(offer["destination"])}</div>
        <div class="price">{_money(offer["price"])} total</div>
        <div class="muted">{_money(per_person)} per traveller · {escape(offer.get("airline", "Unknown"))}</div>
        <dl><dt>Departs</dt><dd>{escape(offer.get("departure_time", ""))}</dd>
            <dt>Arrives</dt><dd>{escape(offer.get("arrival_time", ""))}</dd>
            <dt>Journey</dt><dd>{offer["duration_minutes"] // 60}h {offer["duration_minutes"] % 60:02d}m · {stops_text}{stop_info}</dd></dl>
        {baggage}
        <div class="evidence">Amadeus API result — recheck at checkout</div>
        <a class="button" href="{escape(offer.get("booking_url", ""), quote=True)}">Book on Google Flights</a>
      </article>"""


def _render_google_card(offer: FlightOffer) -> str:
    per_person = offer.price_per_traveller or offer.price
    return f"""
      <article class="card">
        <div class="source-badge">Results Page</div>
        <div class="route">{escape(offer.origin)} → {escape(offer.destination)}</div>
        <div class="price">{_money(offer.price)} total</div>
        <div class="muted">{_money(per_person)} per traveller · {escape(offer.airline)}</div>
        <dl><dt>Departs</dt><dd>{escape(offer.departure.replace('T', ' ')[:16])}</dd>
            <dt>Journey</dt><dd>{offer.duration_minutes // 60}h {offer.duration_minutes % 60:02d}m · {offer.stops} stop(s)</dd></dl>
        <div class="evidence">Results-page evidence — recheck at checkout</div>
        <a class="button" href="{escape(offer.booking_url, quote=True)}">Open official search</a>
      </article>"""


def render_flight_report(
    config: FlightConfig,
    offers: Mapping[str, Sequence[FlightOffer]],
    *,
    amadeus_offers: Mapping[str, Sequence[dict[str, Any]]] | None = None,
    google_links: dict[str, dict[str, str]] | None = None,
    generated_at: str,
) -> str:
    sections: list[str] = []
    for search in config.searches:
        cards: list[str] = []

        amadeus = list(amadeus_offers.get(search.key, [])) if amadeus_offers else []
        for offer in amadeus:
            cards.append(_render_amadeus_card(offer))

        for offer in offers.get(search.key, ()):
            cards.append(_render_google_card(offer))

        if not cards:
            links_html = ""
            if google_links:
                links_html = "".join(
                    f'<a class="button secondary" href="{escape(info["url"], quote=True)}">{escape(info["label"])}</a>'
                    for info in google_links.values()
                )
            else:
                links_html = "".join(
                    f'<a class="button secondary" href="{escape(build_google_flights_url(origins=search.origins, destinations=search.destinations, date=day, travellers=search.travellers, cabin_class=search.cabin_class), quote=True)}">Search {escape(day)}</a>'
                    for day in search.dates
                )
            cards.append(f"<article class='empty'><strong>No parseable live fare cards.</strong><p>Provider markup, consent, or availability may have blocked this scan. Use the official entry links; no price has been invented.</p>{links_html}</article>")
        sections.append(f"""
          <section><h2>{escape(search.label)}</h2>
            <p class="scope">{', '.join(search.origins)} → {', '.join(search.destinations)} · {search.travellers} traveller(s) · {escape(search.departure_window[0])}–{escape(search.departure_window[1])}</p>
            <div class="grid">{''.join(cards)}</div>
          </section>""")
    display_time = generated_at.replace("T", " ").replace("+00:00", " UTC")
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><style>
      body{{margin:0;background:#08111f;color:#e5edf7;font-family:Arial,sans-serif}}main{{max-width:920px;margin:auto;padding:28px 18px 48px}}
      h1{{font-size:30px;margin:0 0 8px}}h2{{margin-top:34px}}.sub,.muted,.scope{{color:#9eb0c7}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(255px,1fr));gap:14px}}
      .card,.empty{{background:#101d30;border:1px solid #263953;border-radius:14px;padding:18px}}.route{{font-weight:700;font-size:18px}}.price{{font-size:28px;color:#6ee7b7;font-weight:800;margin:12px 0 4px}}
      dl{{display:grid;grid-template-columns:72px 1fr;gap:7px;margin:16px 0}}dt{{color:#8ca0b9}}dd{{margin:0}}.evidence{{background:#392d14;color:#fde68a;border-radius:8px;padding:8px;font-size:12px}}
      .button{{display:inline-block;margin-top:14px;background:#38bdf8;color:#062033;text-decoration:none;padding:10px 14px;border-radius:9px;font-weight:700}}.secondary{{margin-right:8px;background:#cbd5e1}}
      .source-badge{{display:inline-block;background:#1e3a5f;color:#7dd3fc;border-radius:6px;padding:3px 8px;font-size:11px;font-weight:700;margin-bottom:8px}}
      .amadeus .source-badge{{background:#14432a;color:#6ee7b7}}
      .baggage{{color:#9eb0c7;font-size:13px;margin:6px 0}}
      footer{{margin-top:36px;color:#8496ad;font-size:12px;line-height:1.5}}
    </style></head><body><main><h1>{escape(config.report_title)}</h1><p class="sub">Generated {escape(display_time)} · live API quotes where configured, results-page cards otherwise</p>
    {''.join(sections)}<footer>Prices and availability can change. An API quote or results-page card is not checkout verification. Confirm baggage, fare rules, connection protection and the final whole-party total before paying.</footer></main></body></html>"""
