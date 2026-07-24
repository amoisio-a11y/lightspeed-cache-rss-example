#!/usr/bin/env python3
"""
Generoi RSS-syotteen Hyotykasviyhdistyksen tapahtumasivulta,
mutta VAIN Annalan Huvilan tapahtumista.

Lahde: https://hyotykasviyhdistys.fi/tapahtumat-ja-kurssit/

Sivu renderoi palvelinpuolella kaikki paikkakuntaryhmat samalle
sivulle valmiiksi (JS vain nayttaa/piilottaa niita valilehtina),
joten "Helsinki Annalan huvila" -ryhma on suoraan poimittavissa
omasta <div id="Helsinki Annalan huvila">-lohkostaan ilman
erillista sivupyyntoa tai taksonomia-URL:a.
"""

import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

SOURCE_URL = "https://hyotykasviyhdistys.fi/tapahtumat-ja-kurssit/"
SECTION_ID = "Helsinki Annalan huvila"
OUTPUT_FILE = "feed-annala.xml"
TIMEZONE = ZoneInfo("Europe/Helsinki")

FEED_TITLE = "Hyötykasviyhdistys - Annalan Huvilan tapahtumat"
FEED_DESCRIPTION = (
    "Epavirallinen, Annalan Huvilaan suodatettu RSS-syote "
    "Hyötykasviyhdistyksen tapahtumasivulta"
)
FEED_LANGUAGE = "fi"


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; AnnalaFeedBot/1.0; "
            "+https://github.com/) personal RSS generator"
        )
    }
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    return response.text


def parse_events(html: str):
    soup = BeautifulSoup(html, "html.parser")
    section = soup.find("div", id=SECTION_ID)

    if section is None:
        return []

    row = section.find("div", class_="row")
    if row is None:
        return []

    events = []

    for link in row.find_all("a", recursive=False):
        href = link.get("href")
        title_el = link.select_one(".event .title")
        date_el = link.select_one(".event .date")
        time_el = link.select_one(".event .time")

        if not (href and title_el and date_el):
            continue

        title = title_el.get_text(strip=True)

        # Paivamaara voi olla "26.05.2026" tai "26.05.2026 - 25.08.2026"
        date_text = date_el.get_text(" ", strip=True)
        date_matches = re.findall(r"(\d{2})\.(\d{2})\.(\d{4})", date_text)
        if not date_matches:
            continue
        day, month, year = (int(x) for x in date_matches[0])
        pub_date = datetime(year, month, day, 8, 0, 0, tzinfo=TIMEZONE)

        time_text = time_el.get_text(" ", strip=True) if time_el else ""

        description_parts = [date_text]
        if time_text:
            description_parts.append(f"Klo: {time_text}")
        description = " | ".join(description_parts)

        events.append(
            {
                "title": title,
                "link": href,
                "description": description,
                "pub_date": pub_date,
                "guid": href,
            }
        )

    return events


def build_feed(events):
    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.link(href=SOURCE_URL, rel="alternate")
    fg.description(FEED_DESCRIPTION)
    fg.language(FEED_LANGUAGE)

    for event in events:
        fe = fg.add_entry()
        fe.id(event["guid"])
        fe.title(event["title"])
        fe.link(href=event["link"])
        fe.description(event["description"])
        fe.pubDate(event["pub_date"])

    return fg


def main():
    try:
        html = fetch_html(SOURCE_URL)
    except requests.RequestException as exc:
        print(f"Virhe haettaessa sivua: {exc}", file=sys.stderr)
        sys.exit(1)

    events = parse_events(html)

    if not events:
        print(
            f"Varoitus: yhtaan tapahtumaa ei loytynyt lohkosta "
            f"'{SECTION_ID}' - sivun rakenne on saattanut muuttua. "
            f"{OUTPUT_FILE}:aa ei kirjoiteta paalle.",
            file=sys.stderr,
        )
        sys.exit(2)

    fg = build_feed(events)
    fg.rss_file(OUTPUT_FILE, pretty=True)
    print(f"Kirjoitettu {len(events)} tapahtumaa tiedostoon {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
