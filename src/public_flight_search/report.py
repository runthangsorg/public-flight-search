"""Rich, comprehensive flight digest reports with deep links and analysis."""

from __future__ import annotations

from html import escape
from typing import Any, Mapping, Sequence

from .config import FlightConfig
from .engine import FlightOffer
from .google_flights import build_google_flights_url


def _money(value: float) -> str:
    return f"£{value:,.0f}"


def _render_flight_card(offer: FlightOffer, idx: int) -> str:
    per_person = offer.price_per_traveller or offer.price
    stops_badge = "🟢 Nonstop" if offer.stops == 0 else f"🔴 {offer.stops} stop(s)"
    nonstop_class = "nonstop" if offer.stops == 0 else ""

    return f"""
      <article class="card {nonstop_class}" style="background: linear-gradient(135deg, #101d30 0%, #1a2a42 100%); border: 1px solid #263953; border-radius: 16px; padding: 20px; margin-bottom: 16px; transition: transform 0.2s;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
          <span class="source-badge" style="display: inline-block; background: linear-gradient(135deg, #1e3a5f, #2d4a6f); color: #7dd3fc; border-radius: 8px; padding: 4px 10px; font-size: 11px; font-weight: 700;">#{idx+1}</span>
          <span style="color: {'#4ade80' if offer.stops == 0 else '#fbbf24'}; font-size: 12px; font-weight: 600;">{stops_badge}</span>
        </div>
        <div class="route" style="font-weight: 700; font-size: 20px; color: #f8fafc; margin-bottom: 8px;">
          <span style="color: #38bdf8;">{escape(offer.origin)}</span>
          <span style="color: #6ee7b7; margin: 0 8px;">→</span>
          <span style="color: #38bdf8;">{escape(offer.destination)}</span>
        </div>
        <div class="price" style="font-size: 32px; color: #6ee7b7; font-weight: 800; margin: 16px 0 4px;">
          {_money(offer.price)}
          <span style="font-size: 14px; color: #9eb0c7; font-weight: 400; margin-left: 8px;">total</span>
        </div>
        <div class="muted" style="color: #9eb0c7; font-size: 14px; margin-bottom: 12px;">
          {_money(per_person)} per traveller · {escape(offer.airline)}
        </div>
        <div style="background: #0d1520; border-radius: 10px; padding: 12px; margin: 12px 0;">
          <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
            <div style="text-align: center; flex: 1;">
              <div style="color: #6ee7b7; font-size: 18px; font-weight: 700;">{offer.departure[11:16]}</div>
              <div style="color: #8ca0b9; font-size: 12px;">Depart</div>
            </div>
            <div style="text-align: center; flex: 1; padding-top: 4px;">
              <div style="color: #9eb0c7; font-size: 14px;">✈️ {offer.duration_minutes // 60}h {offer.duration_minutes % 60:02d}m</div>
            </div>
            <div style="text-align: center; flex: 1;">
              <div style="color: #6ee7b7; font-size: 18px; font-weight: 700;">{offer.arrival[11:16]}</div>
              <div style="color: #8ca0b9; font-size: 12px;">Arrive</div>
            </div>
          </div>
        </div>
        <div class="evidence" style="background: linear-gradient(135deg, #392d14, #4a3a1a); color: #fde68a; border-radius: 8px; padding: 8px; font-size: 12px; margin: 10px 0;">
          📋 {escape(offer.review_status)}
        </div>
        <a class="button" href="{escape(offer.booking_url, quote=True)}" style="display: inline-block; margin-top: 8px; background: linear-gradient(135deg, #38bdf8, #0ea5e9); color: #062033; text-decoration: none; padding: 10px 16px; border-radius: 8px; font-weight: 700; font-size: 13px; transition: background 0.2s;">
          Open Google Flights ↗
        </a>
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
        search_offers = offers.get(search.key, ())
        cards: list[str] = []

        for idx, offer in enumerate(search_offers):
            cards.append(_render_flight_card(offer, idx))

        if not cards:
            links_html = ""
            if google_links:
                links_html = "".join(
                    f'<a class="button secondary" href="{escape(info["url"], quote=True)}" style="display: inline-block; margin: 6px 8px 6px 0; padding: 10px 16px; background: linear-gradient(135deg, #38bdf8, #0ea5e9); color: #08111f; text-decoration: none; border-radius: 8px; font-weight: 700; font-size: 13px;">{escape(info["label"])}</a> '
                    for info in google_links.values()
                )
            else:
                links_html = "".join(
                    f'<a class="button secondary" href="{escape(build_google_flights_url(origin=search.origins[0], destination=search.destinations[0], date=day, travellers=search.travellers, cabin_class=search.cabin_class), quote=True)}" style="display: inline-block; margin: 6px 8px 6px 0; padding: 10px 16px; background: linear-gradient(135deg, #38bdf8, #0ea5e9); color: #08111f; text-decoration: none; border-radius: 8px; font-weight: 700; font-size: 13px;">Search {escape(day)}</a> '
                    for day in search.dates
                )
            cards.append(f"""<article class='empty' style='background: linear-gradient(135deg, #101d30 0%, #1a2a42 100%); border: 1px solid #263953; border-radius: 16px; padding: 24px; margin: 12px 0;'>
              <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 12px;">
                <span style="font-size: 24px;">🔍</span>
                <strong style='font-size: 16px; color: #f1f5f9;'>No live fare cards found</strong>
              </div>
              <p style='color: #94a3b8; margin: 8px 0 16px 0; line-height: 1.4; font-size: 14px;'>No results were parsed from the results page. This may be due to rate limiting, consent walls, or Google serving the Explore page. Use the official entry links below.</p>
              <div style='margin-top: 12px;'>{links_html}</div>
            </article>""")

        best_offer = min(search_offers, key=lambda o: o.price) if search_offers else None
        summary_stats = ""
        if search_offers:
            prices = [o.price for o in search_offers]
            stops = [o.stops for o in search_offers]
            airlines = set(o.airline for o in search_offers)
            nonstop_count = sum(1 for s in stops if s == 0)
            summary_stats = f"""<div style="background: #0d1520; border-radius: 12px; padding: 16px; margin: 16px 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 16px;">
              <div style="text-align: center;">
                <div style="color: #6ee7b7; font-size: 24px; font-weight: 800;">{len(search_offers)}</div>
                <div style="color: #8ca0b9; font-size: 12px;">Offers Found</div>
              </div>
              <div style="text-align: center;">
                <div style="color: #6ee7b7; font-size: 24px; font-weight: 800;">{_money(prices[0])}</div>
                <div style="color: #8ca0b9; font-size: 12px;">Cheapest</div>
              </div>
              <div style="text-align: center;">
                <div style="color: #6ee7b7; font-size: 24px; font-weight: 800;">{nonstop_count}/{len(search_offers)}</div>
                <div style="color: #8ca0b9; font-size: 12px;">Nonstop</div>
              </div>
              <div style="text-align: center;">
                <div style="color: #6ee7b7; font-size: 24px; font-weight: 800;">{len(airlines)}</div>
                <div style="color: #8ca0b9; font-size: 12px;">Airlines</div>
              </div>
            </div>"""

        sections.append(f"""
          <section style="margin-top: 32px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
              <h2 style="font-size: 22px; color: #f8fafc; margin: 0;">{escape(search.label)}</h2>
              <span style="background: #1e3a5f; color: #7dd3fc; border-radius: 8px; padding: 4px 12px; font-size: 12px; font-weight: 600;">{search.max_stops} max stop(s)</span>
            </div>
            <p class="scope" style="color: #94a3b8; font-size: 13px; margin: 0 0 14px 0;">
              {', '.join(search.origins)} → {', '.join(search.destinations)} · {search.travellers} traveller(s) · {escape(search.departure_window[0])}–{escape(search.departure_window[1])} · £{search.max_price_per_traveller_gbp or '∞'} max
            </p>
            {summary_stats}
            <div class="grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px;">{''.join(cards)}</div>
          </section>""")

    display_time = generated_at.replace("T", " ").replace("+00:00", " UTC")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape(config.report_title)}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ margin: 0; background: #08111f; color: #e5edf7; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.5; }}
    main {{ max-width: 960px; margin: auto; padding: 32px 20px 48px; }}
    h1 {{ font-size: 32px; margin: 0 0 8px; color: #f8fafc; font-weight: 800; }}
    h2 {{ margin-top: 32px; color: #f8fafc; font-weight: 700; }}
    .sub, .muted, .scope {{ color: #9eb0c7; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }}
    .card {{ background: linear-gradient(135deg, #101d30 0%, #1a2a42 100%); border: 1px solid #263953; border-radius: 16px; padding: 20px; transition: transform 0.2s; }}
    .card:hover {{ transform: translateY(-2px); }}
    .card.nonstop {{ border-color: #4ade80; box-shadow: 0 0 0 1px #4ade8033; }}
    .route {{ font-weight: 700; font-size: 20px; color: #f8fafc; }}
    .price {{ font-size: 32px; color: #6ee7b7; font-weight: 800; margin: 16px 0 4px; }}
    dl {{ display: grid; grid-template-columns: 72px 1fr; gap: 7px; margin: 16px 0; }}
    dt {{ color: #8ca0b9; }}
    dd {{ margin: 0; }}
    .evidence {{ background: linear-gradient(135deg, #392d14, #4a3a1a); color: #fde68a; border-radius: 8px; padding: 8px; font-size: 12px; }}
    .button {{ display: inline-block; margin-top: 14px; background: linear-gradient(135deg, #38bdf8, #0ea5e9); color: #062033; text-decoration: none; padding: 10px 14px; border-radius: 9px; font-weight: 700; transition: background 0.2s; }}
    .button:hover {{ background: linear-gradient(135deg, #7dd3fc, #38bdf8); }}
    .secondary {{ margin-right: 8px; }}
    .source-badge {{ display: inline-block; background: linear-gradient(135deg, #1e3a5f, #2d4a6f); color: #7dd3fc; border-radius: 6px; padding: 3px 8px; font-size: 11px; font-weight: 700; }}
    footer {{ margin-top: 40px; color: #8496ad; font-size: 12px; line-height: 1.5; border-top: 1px solid #1e293b; padding-top: 16px; }}
    @media (max-width: 640px) {{
      .grid {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 24px; }}
      .price {{ font-size: 24px; }}
    }}
  </style>
</head>
<body>
  <main style="max-width: 960px; margin: auto; padding: 32px 20px 48px;">
    <h1 style="font-size: 32px; margin: 0 0 8px; color: #f8fafc; font-weight: 800;">{escape(config.report_title)}</h1>
    <p class="sub" style="color: #9eb0c7; margin: 0 0 24px 0; font-size: 14px;">
      🕐 Generated {escape(display_time)} · {sum(len(v) for v in offers.values())} total offers across {len(config.searches)} searches
    </p>
    {''.join(sections)}
    <footer style="margin-top: 40px; color: #8496ad; font-size: 12px; line-height: 1.5; border-top: 1px solid #1e293b; padding-top: 16px;">
      <strong style="color: #94a3b8;">⚠️ Important:</strong> Prices and availability can change instantly. A results-page card is not checkout verification. Confirm baggage allowance, fare rules, connection protection and the final whole-party total before paying. All links point to Google Flights for live re-verification.
    </footer>
  </main>
</body>
</html>"""
