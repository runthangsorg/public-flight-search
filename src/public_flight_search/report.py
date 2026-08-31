"""Responsive, email-safe HTML reports with explicit evidence labels."""

from __future__ import annotations

from html import escape
from typing import Any, Mapping, Sequence

from .config import FlightConfig
from .engine import FlightOffer
from .google_flights import build_google_flights_url


def _money(value: float) -> str:
    return f"£{value:,.0f}"


def _render_flight_card(offer: FlightOffer) -> str:
    """Render a single flight offer as an email-safe table row."""
    per_person = offer.price_per_traveller or offer.price
    stops_text = "Nonstop" if offer.stops == 0 else f"{offer.stops} stop" if offer.stops == 1 else f"{offer.stops} stops"
    stops_color = "#16a34a" if offer.stops == 0 else "#f59e0b"
    date_str = offer.departure[:10]
    dep_short = offer.departure[11:16]
    arr_short = offer.arrival[11:16]
    dur_h = offer.duration_minutes // 60
    dur_m = offer.duration_minutes % 60
    
    row_class = "nonstop" if offer.stops == 0 else ""
    
    return (
        f'<tr class="{row_class}" style="background:#101d30;">'
        f'<td style="padding:12px 10px; border-bottom:1px solid #1e293b; vertical-align:middle; white-space:nowrap;">'
        f'<span style="background:#1e3a5f; color:#7dd3fc; border-radius:4px; padding:2px 6px; font-size:10px; font-weight:700;">{escape(date_str)}</span>'
        f'</td>'
        f'<td style="padding:12px 10px; border-bottom:1px solid #1e293b; vertical-align:middle;">'
        f'<span style="color:{stops_color}; font-size:11px; font-weight:600;">● {stops_text}</span>'
        f'</td>'
        f'<td style="padding:12px 10px; border-bottom:1px solid #1e293b; vertical-align:middle; color:#f8fafc; font-weight:700; font-size:14px;">'
        f'{escape(offer.origin)} → {escape(offer.destination)}'
        f'</td>'
        f'<td style="padding:12px 10px; border-bottom:1px solid #1e293b; vertical-align:middle; color:#6ee7b7; font-weight:800; font-size:16px; white-space:nowrap;">'
        f'{_money(offer.price)}'
        f'</td>'
        f'<td style="padding:12px 10px; border-bottom:1px solid #1e293b; vertical-align:middle; color:#9eb0c7; font-size:12px;">'
        f'{escape(offer.airline)}'
        f'</td>'
        f'<td style="padding:12px 10px; border-bottom:1px solid #1e293b; vertical-align:middle; color:#9eb0c7; font-size:12px; white-space:nowrap;">'
        f'{dep_short} → {arr_short} · {dur_h}h {dur_m:02d}m'
        f'</td>'
        f'<td style="padding:12px 10px; border-bottom:1px solid #1e293b; vertical-align:middle; white-space:nowrap;">'
        f'<a href="{escape(offer.booking_url, quote=True)}" style="background:#38bdf8; color:#062033; text-decoration:none; padding:6px 10px; border-radius:4px; font-weight:700; font-size:11px; display:inline-block;">Open Flights ↗</a>'
        f'</td>'
        f'</tr>'
    )


def render_flight_report(
    config: FlightConfig,
    offers: Mapping[str, Sequence[FlightOffer]],
    *,
    google_links: dict[str, dict[str, str]] | None = None,
    generated_at: str,
) -> str:
    display_time = generated_at.replace("T", " ").replace("+00:00", " UTC")
    total_offers = sum(len(v) for v in offers.values())
    
    sections_html = []
    for search in config.searches:
        search_offers = list(offers.get(search.key, ()))
        
        if not search_offers:
            links_html = ""
            if google_links:
                for info in google_links.values():
                    links_html += (
                        f'<a href="{escape(info["url"], quote=True)}" style="background:#38bdf8; color:#062033; text-decoration:none; padding:6px 10px; border-radius:4px; font-weight:700; font-size:12px; margin:2px; display:inline-block;">{escape(info["label"])}</a> '
                    )
            else:
                for day in search.dates:
                    url = build_google_flights_url(
                        origin=search.origins[0],
                        destination=search.destinations[0],
                        date=day,
                        travellers=search.travellers,
                        cabin_class=search.cabin_class,
                    )
                    links_html += (
                        f'<a href="{escape(url, quote=True)}" style="background:#38bdf8; color:#062033; text-decoration:none; padding:6px 10px; border-radius:4px; font-weight:700; font-size:12px; margin:2px; display:inline-block;">Search {escape(day)}</a> '
                    )
            
            sections_html.append(
                f'<tr style="background:#101d30;"><td colspan="7" style="padding:20px; text-align:center; color:#94a3b8;">'
                f'<strong>No parseable live fare cards.</strong><br>Provider markup, consent, or availability may have blocked this scan.'
                f'<div style="margin-top:10px;">{links_html}</div></td></tr>'
            )
            continue
        
        prices = [o.price for o in search_offers]
        airlines = set(o.airline for o in search_offers)
        nonstop = sum(1 for o in search_offers if o.stops == 0)
        
        summary_html = (
            f'<tr style="background:#0d1520;">'
            f'<td colspan="7" style="padding:12px 10px; color:#9eb0c7; font-size:12px;">'
            f'<strong style="color:#f8fafc;">{len(search_offers)} offers</strong> · Cheapest: <strong style="color:#6ee7b7;">{_money(min(prices))}</strong> · Nonstop: <strong style="color:#6ee7b7;">{nonstop}</strong> · Airlines: <strong style="color:#6ee7b7;">{len(airlines)}</strong>'
            f'</td></tr>'
        )
        
        header_html = (
            '<tr style="background:#1e293b;">'
            '<th style="padding:8px 10px; text-align:left; color:#8ca0b9; font-size:11px; font-weight:600; border-bottom:1px solid #263953;">Date</th>'
            '<th style="padding:8px 10px; text-align:left; color:#8ca0b9; font-size:11px; font-weight:600; border-bottom:1px solid #263953;">Stops</th>'
            '<th style="padding:8px 10px; text-align:left; color:#8ca0b9; font-size:11px; font-weight:600; border-bottom:1px solid #263953;">Route</th>'
            '<th style="padding:8px 10px; text-align:left; color:#8ca0b9; font-size:11px; font-weight:600; border-bottom:1px solid #263953;">Price</th>'
            '<th style="padding:8px 10px; text-align:left; color:#8ca0b9; font-size:11px; font-weight:600; border-bottom:1px solid #263953;">Airline</th>'
            '<th style="padding:8px 10px; text-align:left; color:#8ca0b9; font-size:11px; font-weight:600; border-bottom:1px solid #263953;">Depart → Arrive · Duration</th>'
            '<th style="padding:8px 10px; text-align:left; color:#8ca0b9; font-size:11px; font-weight:600; border-bottom:1px solid #263953;">Action</th>'
            '</tr>'
        )
        
        rows_html = ""
        for offer in search_offers[:5]:
            rows_html += _render_flight_card(offer)
        
        sections_html.append(
            f'<tr style="background:#08111f;"><td colspan="7" style="padding:16px 0 4px 0; color:#f8fafc; font-size:16px; font-weight:700;">{escape(search.label)}</td></tr>'
            f'<tr style="background:#08111f;"><td colspan="7" style="padding:0 0 12px 0; color:#94a3b8; font-size:12px;">'
            f'{", ".join(search.origins)} → {", ".join(search.destinations)} · {search.travellers} traveller(s) · {escape(search.departure_window[0])}–{escape(search.departure_window[1])} · Max {search.max_stops} stop(s) · £{search.max_price_per_traveller_gbp or "∞"}'
            f'</td></tr>'
            f'{summary_html}'
            f'{header_html}'
            f'{rows_html}'
        )
    
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">'
        f'<title>{escape(config.report_title)}</title></head><body style="margin:0; padding:0; background:#08111f; font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif; line-height:1.5;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:900px; margin:0 auto; background:#08111f;">'
        '<tr><td style="padding:24px 16px;">'
        f'<h1 style="margin:0 0 4px 0; color:#f8fafc; font-size:24px; font-weight:800;">{escape(config.report_title)}</h1>'
        f'<p style="margin:0 0 20px 0; color:#9eb0c7; font-size:13px;">Generated {escape(display_time)} · {total_offers} total unique offers across {len(config.searches)} searches</p>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; border-radius:8px; overflow:hidden;">'
        f'{"".join(sections_html)}'
        '</table>'
        f'<p style="margin:24px 0 0 0; padding:14px; background:#392d14; border-radius:6px; color:#fde68a; font-size:12px; line-height:1.5;">'
        f'<strong>⚠ Disclaimer:</strong> Prices and availability change instantly. Results-page cards are not checkout verification. Confirm baggage, fare rules, connection protection and final whole-party total before paying. All links open Google Flights for live re-verification.'
        f'</p>'
        '</td></tr></table></body></html>'
    )
