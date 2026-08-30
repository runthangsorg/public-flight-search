"""Responsive, email-safe HTML reports with explicit evidence labels."""

from __future__ import annotations

from html import escape
from typing import Mapping, Sequence

from .config import FlightConfig
from .engine import FlightOffer
from .google_flights import build_google_flights_url


def _money(value: float) -> str:
    return f"£{value:,.0f}"


def render_flight_report(
    config: FlightConfig, offers: Mapping[str, Sequence[FlightOffer]], *, generated_at: str
) -> str:
    sections: list[str] = []
    for search in config.searches:
        cards: list[str] = []
        for offer in offers.get(search.key, ()):
            per_person = offer.price_per_traveller or offer.price / search.travellers
            cards.append(f"""
              <article class="card">
                <div class="route">{escape(offer.origin)} → {escape(offer.destination)}</div>
                <div class="price">{_money(offer.price)} total</div>
                <div class="muted">{_money(per_person)} per traveller · {escape(offer.airline)}</div>
                <dl><dt>Departs</dt><dd>{escape(offer.departure.replace('T', ' ')[:16])}</dd>
                    <dt>Journey</dt><dd>{offer.duration_minutes // 60}h {offer.duration_minutes % 60:02d}m · {offer.stops} stop(s)</dd></dl>
                <div class="evidence">Results-page evidence — recheck at checkout</div>
                <a class="button" href="{escape(offer.booking_url, quote=True)}">Open official search</a>
              </article>""")
        if not cards:
            links = "".join(
                f'<a class="button secondary" href="{escape(build_google_flights_url(origins=search.origins, destinations=search.destinations, date=day, travellers=search.travellers, cabin_class=search.cabin_class), quote=True)}">Search {escape(day)}</a>'
                for day in search.dates
            )
            cards.append(f"<article class='empty'><strong>No parseable live fare cards.</strong><p>Provider markup, consent, or availability may have blocked this scan. Use the official entry links; no price has been invented.</p>{links}</article>")
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
      footer{{margin-top:36px;color:#8496ad;font-size:12px;line-height:1.5}}
    </style></head><body><main><h1>{escape(config.report_title)}</h1><p class="sub">Generated {escape(display_time)} · live result cards where available</p>
    {''.join(sections)}<footer>Prices and availability can change. A results-page card is not checkout verification. Confirm baggage, fare rules, connection protection and the final whole-party total before paying.</footer></main></body></html>"""
