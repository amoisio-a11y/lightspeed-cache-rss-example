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

TARKEA HUOMIO PUBDATE:STA
--------------------------
Tapahtumien omat paivamaarat ovat usein TULEVAISUUDESSA (esim.
"TIISTAITEEMAT 2026: 26.05.2026 - 25.08.2026"). Jos naita
kaytettaisiin suoraan RSS:n pubDate-kenttana, monet RSS-lukijat
tulkitsevat tulevan paivamaaran niin, etta kohde nayttaa "juuri
nyt" -tuoreelta aina siihen asti kunnes paiva koittaa - talloin
tulevat tapahtumat "floodaavat" feedin karjen pysyvasti.

Tama scraperi kayttaa siksi pubDate:na sita ajanhetkea, jolloin
tapahtuma naytettiin syotteessa ENSIMMAISTA KERTAA (state-tiedosto
state-annala.json muistaa taman ajojen valilla), ei tapahtuman
omaa kalenteripaivaa. Tapahtuman todellinen paivamaara/kellonaika
nakyy edelleen kuvauksessa.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

SOURCE_URL = "https://hyotykasviyhdistys.fi/tapahtumat-ja-kurssit/"
SECTION_ID = "Helsinki Annalan huvila"
OUTPUT_FILE = "feed-annala.xml"
STATE_FILE = "state-annala.json"
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


def load_state(path: str) -> dict:
    file = Path(path)
    if not file.exists():
        return {}
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Vioittunut/lukukelvoton state-tiedosto -> aloitetaan tyhjasta,
        # tama vain nollaa "ensi kertaa nahty" -ajat kertaalleen.
        return {}


def save_state(path: str, state: dict) -> None:
    Path(path).write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


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
        date_text = date_el.get_text(" ", strip=True)
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
                "guid": href,
            }
        )

    return events


def assign_pub_dates(events: list, state: dict, run_time: datetime) -> dict:
    """
    Palauttaa uuden state-dictin. Jokaiselle tapahtumalle:
    - jos linkki on jo state:ssa -> kaytetaan tallennettua aikaleimaa
    - jos linkki on uusi -> aikaleimaksi run_time (nyt), tallennetaan

    State rakennetaan uudelleen VAIN nyt loydetyista tapahtumista,
    jotta jo poistuneiden (menneiden) tapahtumien tiedot eivat
    kasva tiedostoa loputtomiin.
    """
    new_state = {}

    for event in events:
        key = event["guid"]
        if key in state:
            try:
                first_seen = datetime.fromisoformat(state[key])
            except ValueError:
                first_seen = run_time
        else:
            first_seen = run_time

        new_state[key] = first_seen.isoformat()
        event["pub_date"] = first_seen

    return new_state


def build_feed(events):
    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.link(href=SOURCE_URL, rel="alternate")
    fg.description(FEED_DESCRIPTION)
    fg.language(FEED_LANGUAGE)

    # Uusimmat (viimeksi ensi kertaa nahdyt) ensin
    for event in sorted(events, key=lambda e: e["pub_date"], reverse=True):
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

    run_time = datetime.now(TIMEZONE)
    state = load_state(STATE_FILE)
    new_state = assign_pub_dates(events, state, run_time)
    save_state(STATE_FILE, new_state)

    fg = build_feed(events)
    fg.rss_file(OUTPUT_FILE, pretty=True)

    new_count = sum(1 for e in events if e["guid"] not in state)
    print(
        f"Kirjoitettu {len(events)} tapahtumaa tiedostoon {OUTPUT_FILE} "
        f"({new_count} uutta)"
    )


if __name__ == "__main__":
    main()
