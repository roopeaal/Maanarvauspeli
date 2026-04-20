# Kristoffer Kolumbuksen jaljilla - maanarvauspeli

Selainpohjainen maanarvauspeli, jossa pelaaja etsii "kadonnutta" Kolumbusta etaisyys- ja ilmansuuntavihjeiden avulla.
Tama README on kirjoitettu julkaistun valmiin tuotteen esittelyyn.

![Python](https://img.shields.io/badge/Python-3.11-blue)
![Flask](https://img.shields.io/badge/Flask-3.x-black)
![MySQL](https://img.shields.io/badge/MySQL-8.x-0F5D9C)
![Deploy](https://img.shields.io/badge/Deploy-Render-46E3B7)

## Julkaistu versio

- Live-sivu: [https://lentokonepeli.onrender.com](https://lentokonepeli.onrender.com)
- Julkaisualusta: Render (Free Web Service)
- Tietokanta: Aiven MySQL (SSL-yhteys)

## Mitä tuotteessa on

- Interaktiivinen maailmankartta, josta voi arvata maita klikkaamalla.
- Maan arvaus myos kirjoittamalla, mukana kirjoitusvirheiden sieto ja ehdotukset.
- Dynaaminen pisteytys ja vihjejarjestelma.
- Visuaalisesti teemoitettu "antiikkikartta"-kayttoliittyma.
- Top 10 -pistetaulukko.
- Mobiilioptimoitu nakyma.

## Julkaisun tekninen kokonaisuus

- Backend: Flask + Gunicorn
- Frontend: Jinja2, CSS, JavaScript
- Kartta: Leaflet + GeoJSON
- Geolaskenta: geopy
- Tietokanta-ajuri: mysql-connector-python

## Kayttohuomiot (julkaistu tuotanto)

- Renderin ilmainen palvelu voi menna nukkumaan, jos sovellusta ei kayteta hetkeen.
- Tasta syysta ensimmainen lataus voi joskus kestaa noin 30-90 sekuntia (cold start), jonka jalkeen peli toimii normaalisti.

## Lisenssi ja attribuutiot

Sovelluksen antiikkikartta-taustakuva on public domain -kuva Wikimedia Commonsista:
https://commons.wikimedia.org/wiki/File:Antique_World_Map_of_Continents_and_Oceans_1700.png
