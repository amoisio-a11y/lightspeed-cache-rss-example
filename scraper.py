#!/usr/bin/env python3
"""
Generoi RSS-syotteen Helsingin Konservatorion uutisarkistosta.
Lahde: https://www.konservatorio.fi/arkisto/uutiset/

Koska sivuston oma /feed/-osoite palauttaa tyhjan syotteen
(WordPress + rajattu teemakysely + valimuisti), tama skripti
lukee julkisen HTML-sivun suoraan ja rakentaa syotteen itse.
"""

import re
import sys
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


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; KonservatorioFeedBot/1.0; "
            "+https://github.com/) personal RSS generator"
        )
    }
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    return response.text


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
        print(f"Virhe haettaessa sivua: {exc}", file=sys.stderr)
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
