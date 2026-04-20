# Lentokonepeli

Selainpohjainen maanarvauspeli, jossa tavoitteena on loytaa satunnainen maa mahdollisimman vahilla pistevahennyksilla.  
Sovellus on toteutettu Flaskilla, MySQL:lla ja Leaflet-kartalla.

![Python](https://img.shields.io/badge/Python-3.11-blue)
![Flask](https://img.shields.io/badge/Flask-3.x-black)
![MySQL](https://img.shields.io/badge/MySQL-8.x-0F5D9C)
![Deploy](https://img.shields.io/badge/Deploy-Render-46E3B7)

## Live-demo

- Peli verkossa: https://lentokonepeli.onrender.com
- Sovellus on julkaistu Renderin ilmaisella (`Free`) web service -tasolla.
- Free-tasolla palvelu menee valilla nukkumaan inaktiivisena, jolloin ensimmainen pyynto voi herattaa palvelun ja lataus kestaa hetken (yleensa noin 30-90 sekuntia).

## Projektin idea

Pelaaja syottaa maan nimen, jonka jalkeen peli kertoo etaisyyden ja ilmansuunnan oikeaan maahan.  
Jokainen vaarin arvattu maa laskee pisteita progressiivisesti. Pelaaja voi ostaa vihjeen pisteilla, jolloin paljastetaan oikean maan suurin lentokentta.

## Ominaisuudet

- Interaktiivinen maailmankartta (Leaflet) ja klikattavat maat.
- Dynaaminen pisteytys: vahennys riippuu nykyisesta pistemaarasta.
- Vihjejarjestelma: vihjeen hinta skaalautuu pistealueen mukaan.
- Kirjoitusvirheiden sieto maanimille (aliasit + ehdotukset).
- Top 10 -pistetaulukko (`/leaderboard`).
- Evastepohjainen pelitilan hallinta (kayttaja, arvotut maat, kierrosstatus).

## Teknologiat

- Backend: Flask
- Tietokanta: MySQL (`mysql-connector-python`)
- Geolaskenta: `geopy`
- Frontend: Jinja2-templatet, CSS, JavaScript
- Kartta: Leaflet + GeoJSON-maadata
- Production: Gunicorn
- Deploy: Render (`render.yaml`)

## Projektirakenne

```text
.
|-- testi.py
|-- requirements.txt
|-- render.yaml
|-- sql/
|   `-- init.sql
|-- templates/
|   |-- index.html
|   |-- game.html
|   `-- leaderboard.html
`-- static/
    |-- css/antique-theme.css
    `-- images/
```

## Paikallinen kaynnistys

### 1. Esivaatimukset

- Python 3.11+
- MySQL 8+

### 2. Asenna riippuvuudet

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Aseta ymparistomuuttujat

```bash
export FLASK_SECRET_KEY="oma_satunnainen_avain"
export DB_HOST="127.0.0.1"
export DB_PORT="3306"
export DB_NAME="lentopeli"
export DB_USER="root"
export DB_PASSWORD="oma_salasana"
```

Vaihtoehtoisesti voit kayttaa myos `DB_URL`/`DATABASE_URL`-muuttujaa.

### 4. Alusta tietokanta

```bash
mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p "$DB_NAME" < sql/init.sql
```

`sql/init.sql` luo taulut `game`, `country` ja `airport` seka perusdatan, jolla peli toimii heti.

### 5. Kaynnista sovellus

```bash
python testi.py
```

Sovellus kaynnistyy oletuksena osoitteeseen `http://localhost:5000`.

## Deploy Renderiin

Tama repo sisaltaa valmiin `render.yaml`-konfiguraation.

1. Renderissa: `New +` -> `Blueprint`.
2. Valitse tama GitHub-repo.
3. Render lukee `render.yaml`-tiedoston automaattisesti.
4. Aseta palveluun tietokantaan liittyvat env-muuttujat:
   - `DB_HOST`
   - `DB_PORT`
   - `DB_NAME`
   - `DB_USER`
   - `DB_PASSWORD`
   - tarvittaessa `DB_SSL_CA_PATH`
5. Aja tietokannan alustus kerran:
   ```bash
   mysql -h <DB_HOST> -P <DB_PORT> -u <DB_USER> -p <DB_NAME> < sql/init.sql
   ```
6. Render kaynnistaa sovelluksen komennolla:
   ```bash
   gunicorn --bind 0.0.0.0:$PORT testi:app
   ```

## Huomioitavaa

- GitHub Pages ei tue Flask- tai MySQL-sovelluksia (vain staattinen sisalto).
- Jos kaytat hallittua MySQL-palvelua (esim. Aiven), varmista oikea `DB_PORT` ja TLS-asetukset.
- Render Free -palvelussa kylmakaynnistys on normaalia: jos sivu on ollut pitkiaan kayttamatta, ensilataus voi olla hitaampi.

## Lisenssi ja attribuutiot

Sovelluksen antiikkikartta-taustakuva on public domain -kuva Wikimedia Commonsista:  
https://commons.wikimedia.org/wiki/File:Antique_World_Map_of_Continents_and_Oceans_1700.png
