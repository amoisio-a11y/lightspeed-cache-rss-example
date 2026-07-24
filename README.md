# Helsingin Konservatorio – RSS-syote

Epavirallinen RSS-syote osoitteelle
https://www.konservatorio.fi/arkisto/uutiset/, koska sivuston oma
`/feed/`-osoite palauttaa tyhjan syotteen.

Scraperi lukee julkisen HTML-sivun ja rakentaa validin RSS 2.0
-syotteen (`feed.xml`) BeautifulSoupilla ja feedgenilla.

## Kayttoonotto (kertaalleen)

1. Luo uusi **julkinen** GitHub-repo, esim. `konservatorio-feed`.
2. Lataa tama kansio sinne (tiedostot: `scraper.py`,
   `requirements.txt`, `.github/workflows/update-feed.yml`,
   tama README).
   ```
   git init
   git add .
   git commit -m "Alkuperustus"
   git branch -M main
   git remote add origin https://github.com/<kayttajanimi>/konservatorio-feed.git
   git push -u origin main
   ```
3. Aja scraperi kertaalleen paikallisesti, jotta `feed.xml` on
   olemassa ennen ensimmaista GitHub Actions -ajoa:
   ```
   pip install -r requirements.txt
   python scraper.py
   git add feed.xml
   git commit -m "Ensimmainen feed.xml"
   git push
   ```
4. Ota GitHub Pages kayttoon: repo -> Settings -> Pages ->
   Source: "Deploy from a branch" -> Branch: `main`, kansio `/`
   (juuri). Tallenna.
5. Muutaman minuutin kuluttua syote loytyy osoitteesta:
   ```
   https://<kayttajanimi>.github.io/konservatorio-feed/feed.xml
   ```
   Tama on osoite, jonka lisaat RSS-lukijaan.

## Miten se pysyy ajan tasalla

`.github/workflows/update-feed.yml` ajaa scraperin automaattisesti
GitHub Actionsissa n. 6 kertaa vuorokaudessa ja committaa
paivittyneen `feed.xml`:n, jos sisalto on muuttunut. Talla
aikataululla GitHub Actionsin ilmaiskiintio (2000 min/kk
julkisille repoille rajaton) riittaa reilusti.

Ajon voi kaynnistaa myos kasin: repo -> Actions ->
"Paivita RSS-syote" -> "Run workflow".

## Jos sivun rakenne joskus muuttuu

Scraperi hakee artikkelit CSS-valitsimella `article.tease-post`.
Jos Helsingin Konservatorio joskus uudistaa sivunsa ulkoasun ja
syote lakkaa taas tuottamasta uutisia, GitHub Actions -ajo
paattyy virheeseen (koodi 2: "yhtaan artikkelia ei loytynyt"),
jolloin vanha `feed.xml` sailyy koskemattomana eika rikkoonnu
tyhjaksi. Talloin `scraper.py`:n `parse_articles()`-funktion
CSS-valitsimet pitaa paivittaa vastaamaan uutta HTML-rakennetta.
