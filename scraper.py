#!/usr/bin/env python3
"""
Generoi RSS-syotteen Helsingin Konservatorion uutisarkistosta.
Lahde: https://www.konservatorio.fi/arkisto/uutiset/

Koska sivuston oma /feed/-osoite palauttaa tyhjan syotteen
(WordPress + rajattu teemakysely + valimuisti), tama skripti
lukee julkisen HTML-sivun suoraan ja rakentaa syotteen itse.

HUOM: PLAYWRIGHT VAADITAAN (ei enaa pelkka requests)
------------------------------------------------------
Sivustolla on JS-pohjainen selainhaaste ("One moment, please...",
5 sekunnin setTimeout + window.location.reload()), joka nayttaa
oikean sisallon vasta kun JavaScript on suoritettu selaimessa.
Tavallinen requests.get() ei suorita JS:aa, joten se jaa jumiin
tahan haastesivuun pysyvasti - eivat auta sen enempaa otsikot
kuin uudelleenyrityksetkaan.

Ainoa toimiva ratkaisu on kayttaa oikeaa (headless) selainmoottoria,
tassa Playwright + Chromium, aivan kuten Kaapelitehdas-scraperissa.
Playwright suorittaa sivun JS:n, odottaa haastesivun automaattisen
uudelleenlatauksen, ja palauttaa lopulta oikean sisallon.
"""

import re
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

SOURCE_URL = "https://www.konservatorio.fi/arkisto/uutiset/"
OUTPUT_FILE = "feed.xml"
TIMEZONE = ZoneInfo("Europe/Helsinki")

FEED_TITLE = "Helsingin Konservatorio - Uutiset"
FEED_DESCRIPTION = "Helsingin Konservatorion uutisarkiston epavirallinen RSS-syote"
FEED_LANGUAGE = "fi"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Merkkijonoja, joiden esiintyminen sivun otsikossa/sisallossa
# paljastaa, etta ollaan yha JS-haastesivulla eika oikealla
# sisaltosivulla.
CHALLENGE_MARKERS = [
    "one moment, please",
    "just a moment",
    "checking your browser",
    "verifying you are human",
]

MAX_CHALLENGE_WAITS = 4          # montako kertaa odotetaan haasteen selvista
CHALLENGE_WAIT_MS = 7000         # haaste lataa itsensa uudelleen 5s kohdalla
MAX_FETCH_ATTEMPTS = 3           # koko selainajon uudelleenyritys (esim. aikakatkaisut)
RETRY_DELAY_SECONDS = 20


class ChallengeNotResolvedError(Exception):
    """JS-haastesivu ei selvinnyt varatussa ajassa."""


def _looks_like_challenge(title: str, html: str) -> bool:
    lowered_title = (title or "").lower()
    lowered_html = (html or "").lower()
    return any(
        marker in lowered_title or marker in lowered_html
        for marker in CHALLENGE_MARKERS
    )


def fetch_html_once(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context(
                user_agent=USER_AGENT,
                locale="fi-FI",
            )
            page = context.new_page()
            page.goto(url, wait_until="load", timeout=30000)

            for attempt in range(1, MAX_CHALLENGE_WAITS + 1):
                html = page.content()
                title = page.title()
                if not _looks_like_challenge(title, html):
                    return html

                print(
                    f"JS-haastesivu havaittu (yritys {attempt}/{MAX_CHALLENGE_WAITS}), "
                    f"odotetaan {CHALLENGE_WAIT_MS} ms automaattista uudelleenlatausta...",
                    file=sys.stderr,
                )
                page.wait_for_timeout(CHALLENGE_WAIT_MS)
                # Sivu lataa itsensa uudelleen omalla JS:llaan (window.location.reload()),
                # mutta varmuuden vuoksi odotetaan viela etta lataus on valmis.
                try:
                    page.wait_for_load_state("load", timeout=15000)
                except PlaywrightError:
                    pass  # jatketaan silti - tarkistetaan sisalto seuraavalla kierroksella

            raise ChallengeNotResolvedError(
                f"JS-haastesivu ei selvinnyt {MAX_CHALLENGE_WAITS} yrityksen jalkeen"
            )
        finally:
            browser.close()


def fetch_html(url: str) -> str:
    last_error = None

    for attempt in range(1, MAX_FETCH_ATTEMPTS + 1):
        try:
            return fetch_html_once(url)
        except (PlaywrightError, ChallengeNotResolvedError) as exc:
            last_error = exc
            print(
                f"Sivun haku epaonnistui (yritys {attempt}/{MAX_FETCH_ATTEMPTS}): {exc}",
                file=sys.stderr,
            )
            if attempt < MAX_FETCH_ATTEMPTS:
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
            continue

        date_text = date_span.get_text(strip=True)
        date_match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", date_text)
        if not date_match:
            continue
        day, month, year = (int(x) for x in date_match.groups())
        pub_date = datetime(year, month, day, 8, 0, 0, tzinfo=TIMEZONE)

        title = title_link.get_text(strip=True)
        link = title_link["href"]

        read_more = paragraph.find("a", class_="read-more")
        if read_more:
            read_more_text = read_more.get_text(strip=True)
            description = paragraph.get_text(" ", strip=True)
            description = description.replace(read_more_text, "").strip()
        else:
            description = paragraph.get_text(" ", strip=True)

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


def print_diagnostics(html: str) -> None:
    snippet = html[:500].replace("\n", " ")
    print(f"Vastauksen alku (500 merkkia): {snippet!r}", file=sys.stderr)
    if _looks_like_challenge("", html):
        print(
            "Vihje: vastaus nayttaa yha JS-haastesivulta odotusajan "
            "jalkeenkin - sivusto on saattanut kiristaa suojaustaan "
            "entisestaan.",
            file=sys.stderr,
        )


def main():
    try:
        html = fetch_html(SOURCE_URL)
    except (PlaywrightError, ChallengeNotResolvedError) as exc:
        print(
            f"Virhe haettaessa sivua {MAX_FETCH_ATTEMPTS} yrityksen jalkeen: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    articles = parse_articles(html)

    if not articles:
        print(
            "Varoitus: yhtaan artikkelia ei loytynyt - sivun rakenne on "
            "saattanut muuttua. feed.xml:aa ei kirjoiteta paalle.",
            file=sys.stderr,
        )
        print_diagnostics(html)
        sys.exit(2)

    fg = build_feed(articles)
    fg.rss_file(OUTPUT_FILE, pretty=True)
    print(f"Kirjoitettu {len(articles)} uutista tiedostoon {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
