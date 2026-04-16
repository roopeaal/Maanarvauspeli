# Lentokonepeli

Flask + MySQL -pohjainen lentokentta-aiheinen arvauspeli.

## Aja paikallisesti

1. Luo virtuaaliymparisto ja asenna riippuvuudet:
   - `python3 -m venv venv`
   - `source venv/bin/activate`
   - `pip install -r requirements.txt`
2. Aseta ymparistomuuttujat:
   - `export DB_HOST=127.0.0.1`
   - `export DB_PORT=3306`
   - `export DB_NAME=lentopeli`
   - `export DB_USER=root`
   - `export DB_PASSWORD=oma_salasana`
   - `export FLASK_SECRET_KEY=oma_satunnainen_avain`
3. Alusta tietokanta:
   - `mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p "$DB_NAME" < sql/init.sql`
4. Kaynnista:
   - `python testi.py`

## Tietokannan init-skripti

Repo sisaltaa tiedoston `sql/init.sql`, joka:
- luo taulut `game`, `country` ja `airport`
- lisaa pienen perusdatan (maat + large_airport), jotta peli toimii heti

## Deploy Renderiin

Tama repo sisaltaa valmiin `render.yaml`-tiedoston.

1. Mene Renderissa kohtaan New + ja valitse Blueprint.
2. Valitse tama GitHub-repo.
3. Render lukee `render.yaml`-tiedoston automaattisesti.
4. Anna puuttuvat env-muuttujat deployn aikana:
   - `DB_HOST`
   - `DB_NAME`
   - `DB_USER`
   - `DB_PASSWORD`
   - (`DB_PORT` on oletuksena 3306)
5. Aja tietokannan init kerran:
   - `mysql -h <DB_HOST> -P 3306 -u <DB_USER> -p <DB_NAME> < sql/init.sql`
6. Deployn jalkeen sovellus kaynnistyy komennolla:
   - `gunicorn --bind 0.0.0.0:$PORT testi:app`

## Tarkeaa

GitHub Pages ei pysty ajamaan Flask- tai MySQL-sovellusta. Se toimii vain staattisille sivuille.
