#!/usr/bin/env python3
"""
Generoi RSS-syotteen Helsingin Konservatorion uutisarkistosta.
Lahde: https://www.konservatorio.fi/arkisto/uutiset/

Koska sivuston oma /feed/-osoite palauttaa tyhjan syotteen
(WordPress + rajattu teemakysely + valimuisti), tama skripti
lukee julkisen HTML-sivun suoraan ja rakentaa syotteen itse.

HUOM VERKKOVIRHEISTA (esim. "415 Unsupported Media Type")
-----------------------------------------------------------
Sivustolla on Wordfence-suojaus. GitHub Actionsin ajoympäristöt
jakavat IP-osoitteita tuhansien muiden repojen kanssa, ja jos joku
muu on kuormittanut samaa IP-aluetta, Wordfence saattaa väliaikaisesti
torjua pyyntöjä satunnaisesti - tämä ei liity scraperin logiikkaan.
Tälle ei voi tehda mitään 100%-varmaa korjausta, mutta kaksi asiaa
auttavat: (1) lähetetään täydellisemmät, oikean selaimen kaltaiset
otsikot, (2) yritetään muutaman kerran pienellä viiveellä ennen
luovuttamista, koska torjunta on usein hetkellinen.
"""

import re
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

SOURCE_URL = "https://www.konservatorio.fi/arkisto/uutiset/"
OUTPUT_FILE = "feed.xml"
TIMEZONE = ZoneInfo("Europe/Helsinki")

FEED_TITLE = "Helsingin Konservatorio - Uutiset"
FEED_DESCRIPTION = "Helsingin Konservatorion uutisarkiston epavirallinen RSS-syote"
FEED_LANGUAGE = "fi"

MAX_ATTEMPTS = 4
RETRY_DELAY_SECONDS = 15  # kasvaa yritys yritykselta (15, 30, 45...)

# Mahdollisimman taydellinen, oikean selaimen kaltainen otsikkojoukko.
# Pelkka User-Agent nayttaa "epaaidolta" WAF:lle - lisataan Accept-*
# ja muut otsikot, joita oikea selain aina lahettaa mukana.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "fi-FI,fi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


def fetch_html(url: str) -> str:
    last_error = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(url, headers=HEADERS, timeout=20)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            status = getattr(exc.response, "status_code", None)
            print(
                f"Yritys {attempt}/{MAX_ATTEMPTS} epaonnistui "
                f"(HTTP {status}): {exc}",
                file=sys.stderr,
            )
            if attempt < MAX_ATTEMPTS:
                wait = RETRY_DELAY_SECONDS * attempt
                print(f"Odotetaan {wait} sekuntia ennen uutta yritysta...", file=sys.stderr)
                time.sleep(wait)

    raise last_error


def parse_articles(html: str):
    soup = BeautifulSoup(html, "html.parser")
    articles = []

    for tease in soup.select("article.tease-post"):
        date_span = tease.select_one(".article-date")
        title_link = tease.select_one("h1 a")
        paragraph = tease.find("p")

        if not (date_span and title_link and paragraph):
            # Rakenne ei tasmaa odotettuun -> ohitetaan tama artikkeli
            continue

        # Paivamaara on muotoa "01.07.2026:" (mahd. kellon ikoni edessa)
        date_text = date_span.get_text(strip=True)
        date_match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", date_text)
        if not date_match:
            continue
        day, month, year = (int(x) for x in date_match.groups())
        pub_date = datetime(year, month, day, 8, 0, 0, tzinfo=TIMEZONE)

        title = title_link.get_text(strip=True)
        link = title_link["href"]

        # Kuvausteksti: koko <p>:n teksti miinus "Lue lisaa" -linkin oma teksti
        read_more = paragraph.find("a", class_="read-more")
        if read_more:
            read_more_text = read_more.get_text(strip=True)
            description = paragraph.get_text(" ", strip=True)
            description = description.replace(read_more_text, "").strip()
        else:
            description = paragraph.get_text(" ", strip=True)

        # Uniikki id: kaytetaan artikkelin linkkia
        guid = link

        articles.append(
            {
                "title": title,
                "link": link,
                "description": description,
                "pub_date": pub_date,
                "guid": guid,
            }
        )

    return articles


def build_feed(articles):
    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.link(href=SOURCE_URL, rel="alternate")
    fg.description(FEED_DESCRIPTION)
    fg.language(FEED_LANGUAGE)

    for article in articles:
        fe = fg.add_entry()
        fe.id(article["guid"])
        fe.title(article["title"])
        fe.link(href=article["link"])
        fe.description(article["description"])
        fe.pubDate(article["pub_date"])

    return fg


def main():
    try:
        html = fetch_html(SOURCE_URL)
    except requests.RequestException as exc:
        print(
            f"Virhe haettaessa sivua {MAX_ATTEMPTS} yrityksen jalkeen: {exc}",
            file=sys.stderr,
        )
        # Ei kirjoiteta feed.xml:aa paalle - vanha, viimeksi onnistunut
        # versio jaa voimaan. Poistutaan virhekoodilla, jotta Actions-ajo
        # nakyy epaonnistuneena eika hiljaa onnistuneena.
        sys.exit(1)

    articles = parse_articles(html)

    if not articles:
        print(
            "Varoitus: yhtaan artikkelia ei loytynyt - sivun rakenne on "
            "saattanut muuttua. feed.xml:aa ei kirjoiteta paalle.",
            file=sys.stderr,
        )
        sys.exit(2)

    fg = build_feed(articles)
    fg.rss_file(OUTPUT_FILE, pretty=True)
    print(f"Kirjoitettu {len(articles)} uutista tiedostoon {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
