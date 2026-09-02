"""Responsive, email-safe HTML reports with explicit evidence labels.

Supports both single-leg flight offers and multi-city itinerary packages.
"""

from __future__ import annotations

from html import escape
from typing import Any, Mapping, Sequence

from .config import FlightConfig
from .engine import FlightOffer
from .google_flights import build_google_flights_url
from .trip_config import TripDefinition, TripBucket
from .pairing import combine_legs, pair_outbound_return
from .booking_links import BookingLink
from .pareto import rank_bucket_sections
from .cost_ledger import ItineraryCostLedger


def _money(value: float) -> str:
    return f"£{value:,.0f}"


def _render_flight_card(offer: FlightOffer) -> str:
    """Render a single flight offer as an email-safe table row."""
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


def _render_itinerary_card(itinerary: Mapping[str, Any]) -> str:
    """Render a multi-city itinerary as an email-safe table row."""
    out_date = itinerary.get("outbound_date", "")
    ret_date = itinerary.get("return_date", "")
    out_orig = itinerary.get("outbound_origin", "")
    out_dest = itinerary.get("outbound_destination", "")
    ret_orig = itinerary.get("return_origin", "")
    ret_dest = itinerary.get("return_destination", "")
    cash_cost = itinerary.get("cash_cost_gbp", 0)
    all_in = itinerary.get("all_in_preferred", 0)
    ticket_type = itinerary.get("ticket_type", "")
    out_carrier = itinerary.get("outbound_carrier", "")
    ret_carrier = itinerary.get("inbound_carrier", "")
    booking_data = itinerary.get("booking_data", {})
    cost_ledger = itinerary.get("cost_ledger", {})

    # Ticket type badge
    ticket_badges = {
        "PROTECTED_SINGLE_PNR": '<span style="background:#16a34a; color:#fff; padding:2px 6px; border-radius:3px; font-size:9px; font-weight:700;">✓ Single PNR</span>',
        "TWO_INDEPENDENT_PROTECTED_TICKETS": '<span style="background:#f59e0b; color:#fff; padding:2px 6px; border-radius:3px; font-size:9px; font-weight:700;">⚠ 2 Tickets</span>',
        "UNBUNDLED_SELF_TRANSFER": '<span style="background:#f59e0b; color:#fff; padding:2px 6px; border-radius:3px; font-size:9px; font-weight:700;">⚠ Self-Transfer</span>',
        "UNSAFE_SELF_TRANSFER": '<span style="background:#ef4444; color:#fff; padding:2px 6px; border-radius:3px; font-size:9px; font-weight:700;">⛔ Unsafe</span>',
    }
    ticket_badge = ticket_badges.get(ticket_type, ticket_type)

    # Build booking links
    links_html = ""
    bd = itinerary.get("booking_data", {})
    if bd:
        out_link = bd.get("outbound_link_obj")
        ret_link = bd.get("return_link_obj")
        google_link = bd.get("google_link_obj")
        kayak_link = bd.get("kayak_link_obj")
        trip_link = bd.get("trip_com_link_obj")

        if out_link and isinstance(out_link, dict):
            out_label = out_link.get("button_label", "Open Booking")
            links_html += f'<a href="{escape(out_link.get("url", ""), quote=True)}" style="background:#16a34a; color:#fff; text-decoration:none; padding:6px 10px; border-radius:4px; font-weight:700; font-size:11px; margin:2px; display:inline-block;">{escape(out_label)}</a> '
        if ret_link and isinstance(ret_link, dict):
            ret_label = ret_link.get("button_label", "Open Booking")
            links_html += f'<a href="{escape(ret_link.get("url", ""), quote=True)}" style="background:#16a34a; color:#fff; text-decoration:none; padding:6px 10px; border-radius:4px; font-weight:700; font-size:11px; margin:2px; display:inline-block;">{escape(ret_label)}</a> '
        if google_link and isinstance(google_link, dict):
            links_html += f'<a href="{escape(google_link.get("url", ""), quote=True)}" style="background:#38bdf8; color:#062033; text-decoration:none; padding:6px 10px; border-radius:4px; font-weight:700; font-size:11px; margin:2px; display:inline-block;">{escape(google_link.get("provider", "Google"))}</a> '

    cost_ledger = itinerary.get("cost_ledger", {})
    normalized = cost_ledger.get("normalized_flight_cost", 0)
    total_d2d = cost_ledger.get("total_all_in_door_to_door", 0)
    ground_total = cost_ledger.get("total_ground_cost", 0)

    return (
        f'<tr style="background:#101d30;">'
        f'<td style="padding:12px 10px; border-bottom:1px solid #1e293b; vertical-align:middle; white-space:nowrap;">'
        f'<span style="background:#1e3a5f; color:#7dd3fc; border-radius:4px; padding:2px 6px; font-size:10px; font-weight:700;">{escape(itinerary.get("outbound_date", ""))} → {escape(itinerary.get("return_date", ""))}</span>'
        f'</td>'
        f'<td style="padding:12px 10px; border-bottom:1px solid #1e293b; vertical-align:middle; color:#f8fafc; font-weight:700; font-size:13px;">'
        f'{escape(itinerary.get("outbound_origin", ""))} → {escape(itinerary.get("outbound_destination", ""))} | {escape(itinerary.get("return_origin", ""))} → {escape(itinerary.get("return_destination", ""))}'
        f'</td>'
        f'<td style="padding:12px 10px; border-bottom:1px solid #1e293b; vertical-align:middle;">{escape(ticket_badge)}</td>'
        f'<td style="padding:12px 10px; border-bottom:1px solid #1e293b; vertical-align:middle; color:#f8fafc; font-size:11px;">'
        f'Out: {escape(itinerary.get("outbound_carrier", ""))} | Ret: {escape(itinerary.get("inbound_carrier", ""))}'
        f'</td>'
        f'<td style="padding:12px 10px; border-bottom:1px solid #1e293b; vertical-align:middle; color:#6ee7b7; font-weight:800; font-size:16px; white-space:nowrap;">'
        f'{_money(itinerary.get("cash_cost_gbp", 0))}'
        f'</td>'
        f'<td style="padding:12px 10px; border-bottom:1px solid #1e293b; vertical-align:middle; color:#9eb0c7; font-size:12px;">'
        f'Air: {_money(itinerary.get("cash_cost_gbp", 0))} + Ground: {_money(itinerary.get("cost_ledger", {}).get("total_ground_cost", 0))} = <strong style="color:#fbbf24;">{_money(itinerary.get("all_in_preferred", 0))}</strong>'
        f'</td>'
        f'<td style="padding:12px 10px; border-bottom:1px solid #1e293b; vertical-align:middle; white-space:nowrap;">'
        f'{links_html}'
        f'</td>'
        f'</tr>'
    )


def render_flight_report(
    config: FlightConfig,
    offers: Mapping[str, Sequence[Any]],
    *,
    generated_at: str,
    trip_definitions: Sequence = None,
) -> str:
    """Render flight report supporting both single-leg and multi-city itineraries."""
    display_time = generated_at.replace("T", " ").replace("+00:00", " UTC")

    # Count total offers across all searches
    total_offers = sum(len(v) for v in offers.values())

    sections_html = []
    empty_labels = []

    for search in config.searches:
        search_offers = list(offers.get(search.key, ()))

        if not search_offers:
            empty_labels.append(search.label)
            continue

        # Check if these are multi-city itineraries (dicts with cost_ledger)
        is_multi_city = any(isinstance(o, dict) and "cost_ledger" in o for o in search_offers)

        if is_multi_city:
            # Render multi-city itineraries
            sections_html.append(
                f'<tr style="background:#08111f;"><td colspan="7" style="padding:16px 0 4px 0; color:#f8fafc; font-size:16px; font-weight:700;">{escape(search.label)}</td></tr>'
                f'<tr style="background:#08111f;"><td colspan="7" style="padding:0 0 12px 0; color:#94a3b8; font-size:12px;">'
                f'{", ".join(search.origins)} → {", ".join(search.destinations)} · {search.travellers} traveller(s) · {escape(search.departure_window[0])}–{escape(search.departure_window[1])}'
                f'</td></tr>'
            )

            # Summary
            prices = [o.get("cash_cost_gbp", 0) for o in search_offers if isinstance(o, dict)]
            prices = [p for p in prices if p > 0]
            if prices:
                sections_html.append(
                    f'<tr style="background:#0d1520;">'
                    f'<td colspan="7" style="padding:12px 10px; color:#9eb0c7; font-size:12px;">'
                    f'<strong style="color:#f8fafc;">{len(search_offers)} itineraries</strong> · Lowest airfare: <strong style="color:#6ee7b7;">{_money(min(prices))}</strong>'
                    f'</td></tr>'
                )

            header_html = (
                '<tr style="background:#1e293b;">'
                '<th style="padding:8px 10px; text-align:left; color:#8ca0b9; font-size:11px; font-weight:600; border-bottom:1px solid #263953;">Dates</th>'
                '<th style="padding:8px 10px; text-align:left; color:#8ca0b9; font-size:11px; font-weight:600; border-bottom:1px solid #263953;">Route</th>'
                '<th style="padding:8px 10px; text-align:left; color:#8ca0b9; font-size:11px; font-weight:600; border-bottom:1px solid #263953;">Ticket</th>'
                '<th style="padding:8px 10px; text-align:left; color:#8ca0b9; font-size:11px; font-weight:600; border-bottom:1px solid #263953;">Carriers</th>'
                '<th style="padding:8px 10px; text-align:left; color:#8ca0b9; font-size:11px; font-weight:600; border-bottom:1px solid #263953;">Airfare</th>'
                '<th style="padding:8px 10px; text-align:left; color:#8ca0b9; font-size:11px; font-weight:600; border-bottom:1px solid #263953;">All-In D2D</th>'
                '<th style="padding:8px 10px; text-align:left; color:#8ca0b9; font-size:11px; font-weight:600; border-bottom:1px solid #263953;">Action</th>'
                '</tr>'
            )

            rows_html = ""
            for itinerary in search_offers[:10]:
                if isinstance(itinerary, dict):
                    rows_html += _render_itinerary_card(itinerary)

            sections_html.append(
                f'{header_html}{rows_html}'
            )

        else:
            # Single-leg rendering (existing)
            prices = [o.price for o in search_offers]
            airlines = set(o.airline for o in search_offers)
            nonstop = sum(1 for o in search_offers if o.stops == 0)

            summary_html = (
                f'<tr style="background:#0d1520;">'
                f'<td colspan="7" style="padding:12px 10px; color:#9eb0c7; font-size:12px;">'
                f'<strong style="color:#f8fafc;">{len(search_offers)} offers</strong> · Lowest displayed fare: <strong style="color:#6ee7b7;">{_money(min(prices))}</strong> · Nonstop: <strong style="color:#6ee7b7;">{nonstop}</strong> · Airlines: <strong style="color:#6ee7b7;">{len(airlines)}</strong>'
                f'</td></tr>'
            )

            header_html = (
                '<tr style="background:#1e293b;">'
                '<th style="padding:8px 10px; text-align:left; color:#8ca0b9; font-size:11px; font-weight:600; border-bottom:1px solid #263953;">Date</th>'
                '<th style="padding:8px 10px; text-align:left; color:#8ca0b9; font-size:11px; font-weight:600; border-bottom:1px solid #263953;">Stops</th>'
                '<th style="padding:8px 10px; text-align:left; color:#8ca0b9; font-size:11px; font-weight:600; border-bottom:1px solid #263953;">Route</th>'
                '<th style="padding:8px 10px; text-align:left; color:#8ca0b9; font-size:11px; font-weight:600; border-bottom:1px solid #263953;">Displayed fare</th>'
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

    if empty_labels and total_offers:
        noun = "search" if len(empty_labels) == 1 else "searches"
        sections_html.append(
            '<tr style="background:#251f14;"><td colspan="7" style="padding:14px;color:#fde68a;">'
            f'<strong>{len(empty_labels)} {noun} returned no verified fare cards.</strong> '
            f'Coverage gap: {escape(", ".join(empty_labels))}. No price was invented.</td></tr>'
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
        f'<strong>⚠ Disclaimer:</strong> Prices and availability change instantly. Results-page cards are not checkout verification. Confirm baggage, fare rules, connection protection and final whole-party total before paying. All links open verified booking portals.'
        f'</p>'
        '</td></tr></table></body></html>'
    )


def build_google_flights_url(
    *,
    origin: str,
    destination: str,
    date: str,
    travellers: int,
    cabin_class: str,
) -> str:
    from urllib.parse import quote
    query = f"flights from {origin} to {destination} on {date} one way"
    return "https://www.google.com/travel/flights?q=" + quote(query, safe="") + "&curr=GBP&hl=en-GB"
