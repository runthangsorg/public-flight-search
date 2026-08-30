"""Responsive, email-safe HTML reports with explicit evidence labels."""

from __future__ import annotations

from html import escape
from typing import Any, Mapping, Sequence

from .config import FlightConfig
from .engine import FlightOffer
from .google_flights import build_google_flights_url


def _money(value: float) -> str:
    return f"£{value:,.0f}"


def _render_google_card(offer: FlightOffer) -> str:
    per_person = offer.price_per_traveller or offer.price
    return f"""
      <article class="card" style="background-color: #101d30; border: 1px solid #263953; border-radius: 14px; padding: 18px; margin-bottom: 14px;">
        <div class="source-badge" style="display: inline-block; background-color: #1e3a5f; color: #7dd3fc; border-radius: 6px; padding: 3px 8px; font-size: 11px; font-weight: 700; margin-bottom: 8px;">Results Page</div>
        <div class="route" style="font-weight: 700; font-size: 18px; color: #f8fafc;">{escape(offer.origin)} → {escape(offer.destination)}</div>
        <div class="price" style="font-size: 28px; color: #6ee7b7; font-weight: 800; margin: 12px 0 4px;">{_money(offer.price)} total</div>
        <div class="muted" style="color: #9eb0c7; font-size: 14px;">{_money(per_person)} per traveller · {escape(offer.airline)}</div>
        <dl style="display: grid; grid-template-columns: 72px 1fr; gap: 6px; margin: 14px 0; color: #cbd5e1; font-size: 13px;"><dt style="color: #8ca0b9;">Departs</dt><dd style="margin: 0;">{escape(offer.departure.replace('T', ' ')[:16])}</dd>
            <dt style="color: #8ca0b9;">Journey</dt><dd style="margin: 0;">{offer.duration_minutes // 60}h {offer.duration_minutes % 60:02d}m · {offer.stops} stop(s)</dd></dl>
        <div class="evidence" style="background-color: #392d14; color: #fde68a; border-radius: 8px; padding: 8px; font-size: 12px; margin: 10px 0;">Results-page evidence — recheck at checkout</div>
        <a class="button" href="{escape(offer.booking_url, quote=True)}" style="display: inline-block; margin-top: 8px; background-color: #38bdf8; color: #062033; text-decoration: none; padding: 10px 16px; border-radius: 8px; font-weight: 700; font-size: 13px;">Open official search</a>
      </article>"""


def render_flight_report(
    config: FlightConfig,
    offers: Mapping[str, Sequence[FlightOffer]],
    *,
    google_links: dict[str, dict[str, str]] | None = None,
    generated_at: str,
) -> str:
    sections: list[str] = []
    for search in config.searches:
        cards: list[str] = []

        for offer in offers.get(search.key, ()):
            cards.append(_render_google_card(offer))

        if not cards:
            links_html = ""
            if google_links:
                links_html = "".join(
                    f'<a class="button secondary" href="{escape(info["url"], quote=True)}" style="display: inline-block; margin: 6px 8px 6px 0; padding: 10px 16px; background-color: #38bdf8; color: #08111f; text-decoration: none; border-radius: 8px; font-weight: 700; font-size: 13px;">{escape(info["label"])}</a> '
                    for info in google_links.values()
                )
            else:
                links_html = "".join(
                    f'<a class="button secondary" href="{escape(build_google_flights_url(origins=search.origins, destinations=search.destinations, date=day, travellers=search.travellers, cabin_class=search.cabin_class), quote=True)}" style="display: inline-block; margin: 6px 8px 6px 0; padding: 10px 16px; background-color: #38bdf8; color: #08111f; text-decoration: none; border-radius: 8px; font-weight: 700; font-size: 13px;">Search {escape(day)}</a> '
                    for day in search.dates
                )
            cards.append(f"<article class='empty' style='background-color: #101d30; border: 1px solid #263953; border-radius: 14px; padding: 20px; margin: 12px 0;'><strong style='font-size: 16px; color: #f1f5f9;'>No parseable live fare cards.</strong><p style='color: #94a3b8; margin: 8px 0 16px 0; line-height: 1.4;'>Provider markup, consent, or availability may have blocked this scan. Use the official entry links below; no price has been invented.</p><div style='margin-top: 12px;'>{links_html}</div></article>")
        sections.append(f"""
          <section style="margin-top: 28px;">
            <h2 style="font-size: 20px; color: #f8fafc; margin-bottom: 6px;">{escape(search.label)}</h2>
            <p class="scope" style="color: #94a3b8; font-size: 13px; margin: 0 0 14px 0;">{', '.join(search.origins)} → {', '.join(search.destinations)} · {search.travellers} traveller(s) · {escape(search.departure_window[0])}–{escape(search.departure_window[1])}</p>
            <div class="grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px;">{''.join(cards)}</div>
          </section>""")
    display_time = generated_at.replace("T", " ").replace("+00:00", " UTC")
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><style>
      body{{margin:0;background:#08111f;color:#e5edf7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}}main{{max-width:920px;margin:auto;padding:28px 18px 48px}}
      h1{{font-size:28px;margin:0 0 8px;color:#f8fafc}}h2{{margin-top:28px;color:#f8fafc}}.sub,.muted,.scope{{color:#9eb0c7}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}}
      .card,.empty{{background:#101d30;border:1px solid #263953;border-radius:14px;padding:18px}}.route{{font-weight:700;font-size:18px;color:#f8fafc}}.price{{font-size:28px;color:#6ee7b7;font-weight:800;margin:12px 0 4px}}
      dl{{display:grid;grid-template-columns:72px 1fr;gap:7px;margin:16px 0}}dt{{color:#8ca0b9}}dd{{margin:0}}.evidence{{background:#392d14;color:#fde68a;border-radius:8px;padding:8px;font-size:12px}}
      .button{{display:inline-block;margin-top:14px;background:#38bdf8;color:#062033;text-decoration:none;padding:10px 14px;border-radius:9px;font-weight:700}}.secondary{{margin-right:8px;background:#38bdf8}}
      .source-badge{{display:inline-block;background:#1e3a5f;color:#7dd3fc;border-radius:6px;padding:3px 8px;font-size:11px;font-weight:700;margin-bottom:8px}}
      footer{{margin-top:36px;color:#8496ad;font-size:12px;line-height:1.5;border-top:1px solid #1e293b;padding-top:16px}}
    </style></head><body style="margin:0;background:#08111f;color:#e5edf7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"><main style="max-width:920px;margin:auto;padding:28px 18px 48px;"><h1 style="font-size:28px;margin:0 0 8px;color:#f8fafc;">{escape(config.report_title)}</h1><p class="sub" style="color:#9eb0c7;margin:0 0 24px 0;font-size:14px;">Generated {escape(display_time)} · live results-page cards where available</p>
    {''.join(sections)}<footer style="margin-top:36px;color:#8496ad;font-size:12px;line-height:1.5;border-top:1px solid #1e293b;padding-top:16px;">Prices and availability can change. A results-page card is not checkout verification. Confirm baggage, fare rules, connection protection and the final whole-party total before paying.</footer></main></body></html>"""
