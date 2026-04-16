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
3. Kaynnista:
   - `python testi.py`

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
5. Deployn jalkeen sovellus kaynnistyy komennolla:
   - `gunicorn --bind 0.0.0.0:$PORT testi:app`

## Tarkeaa

GitHub Pages ei pysty ajamaan Flask- tai MySQL-sovellusta. Se toimii vain staattisille sivuille.
