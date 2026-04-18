from flask import Flask, render_template, request, redirect, url_for, flash, make_response, jsonify
from geopy.distance import geodesic
import difflib
import math
import os
import random
import mysql.connector

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'change-me-in-production')

YLEISET_MAA_ALIAKSET = {
    "usa": "united states",
    "us": "united states",
    "unitedstates": "united states",
    "unitedstatesofamerica": "united states",
    "u.s.a": "united states",
    "u.s": "united states",
    "swuden": "sweden",
    "sweeden": "sweden",
    "swedn": "sweden",
    "gremany": "germany",
    "geramny": "germany",
    "frnace": "france",
    "spainn": "spain",
    "itlay": "italy",
    "norawy": "norway",
    "finlad": "finland",
    "republicofserbia": "serbia",
}
VIHJE_HINTA = 300

# Tietokantayhteyden avausfunktio
def get_db_connection():
    conn = mysql.connector.connect(
        host=os.getenv('DB_HOST', '127.0.0.1'),
        port=int(os.getenv('DB_PORT', '3306')),
        database=os.getenv('DB_NAME', 'lentopeli'),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD', ''),
        autocommit=True
    )
    return conn

# Tietokantayhteyden avaaminen ja sulkeminen tietokantakäsittelyissä
def execute_query(query, values=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if values:
            cursor.execute(query, values)
        else:
            cursor.execute(query)
        result = cursor.fetchall()
        conn.commit()
        return result
    except Exception as e:
        flash(str(e), 'danger')
        return None
    finally:
        cursor.close()
        conn.close()

@app.route('/')
def index():
    username = request.cookies.get('username', '')
    return render_template('index.html', username=username)

def _varmista_pelaaja(username):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM game WHERE username = %s", (username,))
        loytyi = cursor.fetchone()
        if not loytyi:
            _lisaa_uusi_pelaaja_yhteensopivasti(cursor, conn, username)
    finally:
        cursor.close()
        conn.close()


def _lisaa_uusi_pelaaja_yhteensopivasti(cursor, conn, username):
    cursor.execute("SHOW COLUMNS FROM game")
    sarakkeet = cursor.fetchall()
    if not sarakkeet:
        raise RuntimeError("game-taulun sarakkeita ei löytynyt.")

    sarake_meta = {}
    for row in sarakkeet:
        nimi = row[0]
        tyyppi = (row[1] or "").lower()
        nullable = (row[2] or "").upper()
        oletus = row[4]
        extra = (row[5] or "").lower()
        sarake_meta[nimi] = {
            "type": tyyppi,
            "null": nullable,
            "default": oletus,
            "extra": extra
        }

    if "username" not in sarake_meta:
        raise RuntimeError("game-taulusta puuttuu username-sarake.")

    tunnetut_oletusarvot = {
        "username": username,
        "password": "",
        "points": 1000,
        "hiscore": 0,
        "kierroksen_Maa": None,
        "arvottu_latitude": None,
        "arvottu_longitude": None,
    }

    insert_sarakkeet = []
    insert_arvot = []

    for sarake, arvo in tunnetut_oletusarvot.items():
        if sarake in sarake_meta:
            insert_sarakkeet.append(sarake)
            insert_arvot.append(arvo)

    for sarake, meta in sarake_meta.items():
        if sarake in insert_sarakkeet:
            continue
        if "auto_increment" in meta["extra"]:
            continue
        if meta["null"] == "YES":
            continue
        if meta["default"] is not None:
            continue

        tyyppi = meta["type"]
        if any(numerinen in tyyppi for numeerinen in ("int", "decimal", "float", "double")):
            insert_sarakkeet.append(sarake)
            insert_arvot.append(0)
        elif "char" in tyyppi or "text" in tyyppi:
            insert_sarakkeet.append(sarake)
            insert_arvot.append("")
        else:
            raise RuntimeError(
                f"game-taulussa vaaditaan sarake '{sarake}', jolle ei osattu antaa oletusarvoa."
            )

    placeholders = ", ".join(["%s"] * len(insert_sarakkeet))
    sarakkeet_sql = ", ".join(insert_sarakkeet)
    cursor.execute(
        f"INSERT INTO game ({sarakkeet_sql}) VALUES ({placeholders})",
        tuple(insert_arvot)
    )
    conn.commit()


@app.route('/set_name', methods=['POST'])
def set_name():
    username = request.form.get('username', '').strip()
    if not username:
        flash('Anna nimi ennen pelaamisen aloitusta.', 'danger')
        return redirect(url_for('index'))

    if len(username) > 50:
        username = username[:50]

    try:
        _varmista_pelaaja(username)
        lisaa_pisteet(username, 1000)
    except Exception:
        app.logger.exception("Nimen asetus epäonnistui /set_name-reitillä.")
        flash('Pelin aloitus epäonnistui palvelimella. Yritä hetken päästä uudelleen.', 'danger')
        return redirect(url_for('index'))

    response = make_response(redirect(url_for('game')))
    response.set_cookie('username', username)
    response.delete_cookie('vihje_kaytetty')
    response.delete_cookie('arvatut_maat')
    response.delete_cookie('arvottu_maa')
    response.delete_cookie('arvottu_latitude')
    response.delete_cookie('arvottu_longitude')
    response.delete_cookie('oikea_maa_iso')
    return response


@app.route('/register', methods=['GET', 'POST'])
def register():
    return redirect(url_for('index'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    return redirect(url_for('index'))


def check_login(username, password):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, password FROM game WHERE username=%s", (username,))
    user_data = cursor.fetchone()
    conn.close()

    # Tarkista onko user_data olemassa ja onko salasana oikea
    if user_data and user_data['password'] == password:
        return True
    else:
        flash("Virheellinen käyttäjätunnus tai salasana.", 'danger')
        return False

@app.route('/logout')
def logout():
    response = make_response(redirect(url_for('index')))
    response.delete_cookie('username')
    response.delete_cookie('vihje_kaytetty')
    response.delete_cookie('arvatut_maat')
    response.delete_cookie('arvottu_maa')
    response.delete_cookie('arvottu_latitude')
    response.delete_cookie('arvottu_longitude')
    response.delete_cookie('oikea_maa_iso')
    return response


# Arvotaan uusi maa ja kenttä ja tallennetaan koordinaatit evästeisiin
def arvo_uusi_maa_ja_kentta():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Haetaan satunnainen maa ja sen suurin lentokenttä
        cursor.execute("""
            SELECT country.name, MAX(airport.name) AS largest_airport, country.latitude, country.longitude 
            FROM country 
            INNER JOIN airport ON country.iso_country = airport.iso_country 
            WHERE airport.type = 'large_airport' 
            GROUP BY country.name, country.latitude, country.longitude;
        """)
        tiedot = cursor.fetchall()
        if not tiedot:
            return None
        return random.choice(tiedot)  # Palautetaan (maa, lentokenttä, latitude, longitude)
    except Exception as e:
        print("Virhe uutta maata ja kenttää arvottaessa:", e)
        return None
    finally:
        cursor.close()
        conn.close()


def hae_suurimman_lentokentan_nimi(maa):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT MAX(airport.name) AS largest_airport
            FROM country
            INNER JOIN airport ON country.iso_country = airport.iso_country
            WHERE airport.type = 'large_airport' AND country.name = %s
        """, (maa,))
        tulos = cursor.fetchone()
        return tulos[0] if tulos else None
    finally:
        cursor.close()
        conn.close()


@app.route('/get_largest_airport_name')
def get_largest_airport_name():
    arvottu_maa = request.cookies.get('arvottu_maa')
    username = request.cookies.get('username')
    vihje_kaytetty = request.cookies.get('vihje_kaytetty') == '1'
    arvatut_maat = _hae_arvatut_maat_cookie()
    oikea_maa_iso = request.cookies.get('oikea_maa_iso', '').strip().upper()
    kierros_voitettu = (
        len(oikea_maa_iso) == 2 and oikea_maa_iso.isalpha() and oikea_maa_iso in arvatut_maat
    )

    # Tarkista, että kierroksen_Maa on asetettu evästeisiin
    if arvottu_maa:
        largest_airport_name = hae_suurimman_lentokentan_nimi(arvottu_maa)
        if not largest_airport_name:
            return jsonify({'largest_airport_name': 'Arvaa ensin maa.'})

        points = None
        if username:
            points = hae_kayttajan_pisteet(username)
            if not vihje_kaytetty and not kierros_voitettu:
                points -= VIHJE_HINTA
                lisaa_pisteet(username, points)

        response = make_response(jsonify({'largest_airport_name': largest_airport_name, 'points': points}))
        response.set_cookie('vihje_kaytetty', '1')
        return response
    else:
        return jsonify({'largest_airport_name': 'Arvaa ensin maa.'})


def laske_etaisyys_ja_ilmansuunta(koordinaatit1, koordinaatit2):
    if None in koordinaatit1 or None in koordinaatit2:
        return None, None  # Palauta None, jos jompikumpi koordinaatti on None

    # Laske etäisyys ja pyöristä se kokonaisluvuksi
    etaisyys = round(geodesic(koordinaatit1, koordinaatit2).kilometers)

    # Laske ilmansuunta
    suunta = math.degrees(
        math.atan2(koordinaatit2[1] - koordinaatit1[1], koordinaatit2[0] - koordinaatit1[0]))
    if suunta < 0:
        suunta += 360  # Muuta negatiiviset suunnat positiivisiksi

    ilmansuunta = None
    if 24 <= suunta < 69:
        ilmansuunta = "koillisessa"
    elif 69 <= suunta < 114:
        ilmansuunta = "idässä"
    elif 114 <= suunta < 159:
        ilmansuunta = "kaakossa"
    elif 159 <= suunta < 204:
        ilmansuunta = "etelässä"
    elif 204 <= suunta < 249:
        ilmansuunta = "lounaassa"
    elif 249 <= suunta < 294:
        ilmansuunta = "lännessä"
    elif 294 <= suunta < 337:
        ilmansuunta = "luoteessa"
    elif 337 <= suunta < 360 or 0 <= suunta < 24:
        ilmansuunta = "pohjoisessa"

    return etaisyys, ilmansuunta

def lisaa_pisteet(username, points):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE game SET points = %s WHERE username = %s", (points, username))
        conn.commit()
    except Exception as e:
        print("Virhe päivittäessä pistetilannetta:", e)
    finally:
        cursor.close()
        conn.close()


def tarkista_maa_tietokannasta(maa):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, latitude, longitude FROM country WHERE name = %s", (maa,))
    tulos = cursor.fetchone()
    cursor.close()
    conn.close()
    return bool(tulos)

def _normalisoi_maa_syote(teksti):
    return "".join(char for char in (teksti or "").lower().strip() if char.isalnum())

def _ehdotuksen_minimiraja(pituus):
    if pituus <= 4:
        return 0.85
    if pituus <= 7:
        return 0.75
    return 0.70

def hae_lahin_maaehdotus(maa):
    syote = (maa or "").strip()
    if not syote or not any(char.isalpha() for char in syote):
        return None

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name FROM country")
        maat = [row[0] for row in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()

    if not maat:
        return None

    syote_normalisoitu = _normalisoi_maa_syote(syote)
    if len(syote_normalisoitu) < 2:
        return None

    maat_normalisoitu_map = {_normalisoi_maa_syote(maa_nimi): maa_nimi for maa_nimi in maat}

    alias_osuma = YLEISET_MAA_ALIAKSET.get(syote_normalisoitu)
    if alias_osuma:
        alias_avain = _normalisoi_maa_syote(alias_osuma)
        if alias_avain in maat_normalisoitu_map:
            return maat_normalisoitu_map[alias_avain]

    if syote_normalisoitu in maat_normalisoitu_map:
        return maat_normalisoitu_map[syote_normalisoitu]

    pisteet = []
    for maa_normalisoitu in maat_normalisoitu_map:
        samankaltaisuus = difflib.SequenceMatcher(None, syote_normalisoitu, maa_normalisoitu).ratio()
        pisteet.append((maa_normalisoitu, samankaltaisuus))

    pisteet.sort(key=lambda osuma: osuma[1], reverse=True)
    if not pisteet:
        return None

    paras_maa, paras_piste = pisteet[0]
    toiseksi_paras_piste = pisteet[1][1] if len(pisteet) > 1 else 0.0
    minimiraja = _ehdotuksen_minimiraja(len(syote_normalisoitu))

    if paras_piste < minimiraja:
        return None
    if len(pisteet) > 1 and (paras_piste - toiseksi_paras_piste) < 0.08:
        return None

    return maat_normalisoitu_map[paras_maa]

def hae_maan_koordinaatit(maa):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT latitude, longitude FROM country WHERE name = %s", (maa,))
        koordinaatit = cursor.fetchone()
        return koordinaatit
    finally:
        cursor.close()
        conn.close()

def hae_maan_iso_koodi(maa):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT iso_country FROM country WHERE name = %s", (maa,))
        tulos = cursor.fetchone()
        if not tulos:
            return None
        return tulos[0]
    finally:
        cursor.close()
        conn.close()

def hae_sallitut_iso_koodit():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT iso_country FROM country")
        koodit = []
        for row in cursor.fetchall():
            if not row:
                continue
            koodi = (row[0] or "").strip().upper()
            if len(koodi) == 2 and koodi.isalpha():
                koodit.append(koodi)
        return sorted(set(koodit))
    finally:
        cursor.close()
        conn.close()

def hae_iso_maa_nimi_map():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT iso_country, name FROM country")
        iso_map = {}
        for row in cursor.fetchall():
            if not row:
                continue
            iso_koodi = (row[0] or "").strip().upper()
            nimi = (row[1] or "").strip()
            if len(iso_koodi) == 2 and iso_koodi.isalpha() and nimi:
                iso_map[iso_koodi] = nimi
        return iso_map
    finally:
        cursor.close()
        conn.close()

def hae_normalisoitu_maa_nimi_map():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name FROM country")
        nimi_map = {}
        for row in cursor.fetchall():
            if not row:
                continue
            nimi = (row[0] or "").strip()
            if not nimi:
                continue
            avain = _normalisoi_maa_syote(nimi)
            if avain:
                nimi_map[avain] = nimi
        return nimi_map
    finally:
        cursor.close()
        conn.close()

def hae_kartta_aliasit():
    alias_map = {}
    for alias, kohde in YLEISET_MAA_ALIAKSET.items():
        alias_avain = _normalisoi_maa_syote(alias)
        kohde_avain = _normalisoi_maa_syote(kohde)
        if alias_avain and kohde_avain:
            alias_map[alias_avain] = kohde_avain
    return alias_map

def _hae_arvatut_maat_cookie():
    arvatut_maat_raaka = request.cookies.get('arvatut_maat', '')
    arvatut_maat = []
    for arvo in arvatut_maat_raaka.split(','):
        koodi = arvo.strip().upper()
        if len(koodi) == 2 and koodi.isalpha() and koodi not in arvatut_maat:
            arvatut_maat.append(koodi)
    return arvatut_maat

def _tallenna_arvatut_maat_cookie(response, arvatut_maat):
    if arvatut_maat:
        response.set_cookie('arvatut_maat', ",".join(arvatut_maat))
    else:
        response.delete_cookie('arvatut_maat')

@app.route('/game', methods=['GET', 'POST'])
def game():
    username = request.cookies.get('username')
    if not username:
        return redirect(url_for('index'))
    _varmista_pelaaja(username)
    sallitut_iso_koodit = hae_sallitut_iso_koodit()
    iso_maa_nimi_map = hae_iso_maa_nimi_map()
    maa_nimi_map = hae_normalisoitu_maa_nimi_map()
    kartta_aliasit = hae_kartta_aliasit()

    # Tarkistetaan, onko arvottu maa ja koordinaatit jo tallennettu evästeisiin
    arvottu_maa = request.cookies.get('arvottu_maa')
    arvottu_latitude = request.cookies.get('arvottu_latitude')
    arvottu_longitude = request.cookies.get('arvottu_longitude')
    vihje_kaytetty = request.cookies.get('vihje_kaytetty') == '1'
    arvatut_maat = _hae_arvatut_maat_cookie()
    oikea_maa_iso = request.cookies.get('oikea_maa_iso', '').strip().upper()
    if not (len(oikea_maa_iso) == 2 and oikea_maa_iso.isalpha()):
        oikea_maa_iso = None
    kierros_voitettu = bool(oikea_maa_iso and oikea_maa_iso in arvatut_maat)
    vihje_teksti = None

    if vihje_kaytetty and arvottu_maa:
        largest_airport_name = hae_suurimman_lentokentan_nimi(arvottu_maa)
        if largest_airport_name:
            vihje_teksti = f"Maan suurin lentokenttä on: {largest_airport_name}"

    # Jos koordinaatit puuttuvat, arvotaan uudet maat ja koordinaatit
    if arvottu_maa is None or arvottu_latitude is None or arvottu_longitude is None:
        arvottu_tieto = arvo_uusi_maa_ja_kentta()
        if arvottu_tieto is None:
            tulos = "Tietokannassa ei ole maita/lentokenttia. Aja sql/init.sql ensin."
            result_category = 'danger'
            return make_response(render_template(
                'game.html',
                result=tulos,
                result_category=result_category,
                points=0,
                vihje_teksti=vihje_teksti,
                vihje_kaytetty=vihje_kaytetty,
                arvatut_maat=arvatut_maat,
                sallitut_iso_koodit=sallitut_iso_koodit,
                iso_maa_nimi_map=iso_maa_nimi_map,
                maa_nimi_map=maa_nimi_map,
                kartta_aliasit=kartta_aliasit,
                kierros_voitettu=False,
                oikea_maa_iso=oikea_maa_iso,
                oikea_osuma=False
            ))
        arvottu_maa = arvottu_tieto[0]
        arvottu_latitude = str(arvottu_tieto[2])
        arvottu_longitude = str(arvottu_tieto[3])

        # Tallennetaan uudet koordinaatit evästeisiin
        user_points = hae_kayttajan_pisteet(username) if username else 0
        response = make_response(render_template(
            'game.html',
            points=user_points,
            vihje_teksti=vihje_teksti,
            vihje_kaytetty=vihje_kaytetty,
            arvatut_maat=[],
            sallitut_iso_koodit=sallitut_iso_koodit,
            iso_maa_nimi_map=iso_maa_nimi_map,
            maa_nimi_map=maa_nimi_map,
            kartta_aliasit=kartta_aliasit,
            kierros_voitettu=False,
            oikea_maa_iso=None,
            oikea_osuma=False
        ))
        response.set_cookie('arvottu_maa', arvottu_maa)
        response.set_cookie('arvottu_latitude', arvottu_latitude)
        response.set_cookie('arvottu_longitude', arvottu_longitude)
        response.delete_cookie('arvatut_maat')
        response.delete_cookie('oikea_maa_iso')
        return response

    user_points = hae_kayttajan_pisteet(username)  # Hae käyttäjän pistemäärä

    tulos = None
    result_category = None
    etaisyys = None
    ilmansuunta = None
    pelaajan_maa_koord = None
    oikea_osuma = False

    if request.method == 'POST':
        pelaajan_maa = request.form.get('pelaajan_maa')
        if pelaajan_maa:
            if tarkista_maa_tietokannasta(pelaajan_maa):
                pelaajan_maa_koord = hae_maan_koordinaatit(pelaajan_maa)
                pelaajan_maa_koord = tuple(map(float, pelaajan_maa_koord))  # Muuta merkkijonoista liukuluvuiksi
                pisteet = 0
                maan_iso_koodi = hae_maan_iso_koodi(pelaajan_maa)
                if maan_iso_koodi:
                    maan_iso_koodi = maan_iso_koodi.upper()
                onko_jo_arvattu = bool(maan_iso_koodi and maan_iso_koodi in arvatut_maat)
                if maan_iso_koodi and not onko_jo_arvattu:
                    arvatut_maat.append(maan_iso_koodi)
                arvottu_latitude = float(arvottu_latitude)  # Muuta merkkijono liukuluvaksi
                arvottu_longitude = float(arvottu_longitude)  # Muuta merkkijono liukuluvaksi
                etaisyys, ilmansuunta = laske_etaisyys_ja_ilmansuunta(pelaajan_maa_koord,
                                                                      (arvottu_latitude, arvottu_longitude))
                if onko_jo_arvattu:
                    result_category = 'info'
                    tulos = f'Olet jo arvannut jo maata "{pelaajan_maa}". Kolumbus on {etaisyys} km päässä {ilmansuunta}.'
                elif pelaajan_maa.lower() == arvottu_maa.lower():
                    # Lisää pisteet käyttäjälle
                    pisteet = 0
                    lisaa_pisteet(username, user_points)  # Päivitä pisteet tietokantaan
                    user_points += pisteet  # Päivitä käyttäjän pistemäärä
                    tulos = (
                        f'Arvasit oikein! Oikea maa on: {arvottu_maa}. Keräsit {user_points} pistettä! Aloita uusi peli "Aloita uusi peli" napista.')
                    paivita_hiscore(username, user_points)
                    oikea_osuma = True
                    oikea_maa_iso = maan_iso_koodi
                else:
                    # Vähennä 100 pistettä väärästä arvauksesta
                    pisteet = -100
                    lisaa_pisteet(username, user_points + pisteet)  # Päivitä pisteet tietokantaan
                    user_points += pisteet  # Päivitä käyttäjän pistemäärä
                    result_category = 'info'
                    tulos = f'Arvauksesi "{pelaajan_maa}" on väärin. Kolumbus on {etaisyys} km päässä {ilmansuunta}.'

                kierros_voitettu = bool(oikea_maa_iso and oikea_maa_iso in arvatut_maat)

                # Tallenna pisteet evästeisiin
                response = make_response(
                    render_template('game.html', result=tulos, result_category=result_category, points=user_points,
                                    pisteet=pisteet, pelaajan_maa_koord=pelaajan_maa_koord,
                                    vihje_teksti=vihje_teksti, vihje_kaytetty=vihje_kaytetty,
                                    arvatut_maat=arvatut_maat, sallitut_iso_koodit=sallitut_iso_koodit,
                                    iso_maa_nimi_map=iso_maa_nimi_map,
                                    maa_nimi_map=maa_nimi_map, kartta_aliasit=kartta_aliasit,
                                    kierros_voitettu=kierros_voitettu,
                                    oikea_maa_iso=oikea_maa_iso,
                                    oikea_osuma=oikea_osuma))
                _tallenna_arvatut_maat_cookie(response, arvatut_maat)
                if oikea_osuma and oikea_maa_iso:
                    response.set_cookie('oikea_maa_iso', oikea_maa_iso)
                return response
            else:
                ehdotus = hae_lahin_maaehdotus(pelaajan_maa)
                if ehdotus:
                    tulos = f'Maa on kirjoitettu väärin, tarkoititko {ehdotus}?'
                else:
                    tulos = "Maa on kirjoitettu väärin tai sitä ei ole olemassa."
                result_category = 'danger'
        else:
            tulos = "Syötä arvaus."

    # Tallenna pisteet evästeisiin
    user_points = hae_kayttajan_pisteet(username)
    response = make_response(render_template(
        'game.html',
        result=tulos,
        result_category=result_category,
        points=user_points,
        vihje_teksti=vihje_teksti,
        vihje_kaytetty=vihje_kaytetty,
        arvatut_maat=arvatut_maat,
        sallitut_iso_koodit=sallitut_iso_koodit,
        iso_maa_nimi_map=iso_maa_nimi_map,
        maa_nimi_map=maa_nimi_map,
        kartta_aliasit=kartta_aliasit,
        kierros_voitettu=kierros_voitettu,
        oikea_maa_iso=oikea_maa_iso,
        oikea_osuma=oikea_osuma
    ))
    return response




def hae_kayttajan_pisteet(username):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT points FROM game WHERE username = %s", (username,))
        rivi = cursor.fetchone()
        if not rivi or rivi[0] is None:
            return 1000
        return int(rivi[0])
    finally:
        cursor.close()
        conn.close()


@app.route('/start_new_game', methods=['GET'])
def start_new_game():
    try:
        username = request.cookies.get('username')

        # Nollaa käyttäjän pisteet
        lisaa_pisteet(username, 1000)

        # Arvotaan uusi oikea maa ja tallennetaan se tietokantaan käyttäjänimen perusteella
        arvottu_tieto = arvo_uusi_maa_ja_kentta()
        if arvottu_tieto:
            arvottu_maa = arvottu_tieto[0]
            arvottu_latitude = arvottu_tieto[2]
            arvottu_longitude = arvottu_tieto[3]

            # Päivitä uusi maa, koordinaatit ja pistemäärä tietokantaan käyttäjänimen perusteella
            query = "UPDATE game SET kierroksen_Maa = %s, arvottu_latitude = %s, arvottu_longitude = %s WHERE username = %s"
            values = (arvottu_maa, arvottu_latitude, arvottu_longitude, username)
            execute_query(query, values)

            # Poista evästeistä oikean maan koordinaatit
            response = make_response(jsonify({'success': True, 'arvottu_maa': arvottu_maa}))
            response.delete_cookie('arvottu_latitude')
            response.delete_cookie('arvottu_longitude')
            response.delete_cookie('vihje_kaytetty')
            response.delete_cookie('arvatut_maat')
            response.delete_cookie('oikea_maa_iso')
            return response
        else:
            response = jsonify({'success': False})
    except Exception as e:
        print("Virhe uutta maata arvottaessa:", e)
        response = jsonify({'success': False})

    return response


@app.route('/leaderboard')
def leaderboard():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, IFNULL(hiscore, 0) as hiscore FROM game ORDER BY hiscore DESC LIMIT 10;")
    top_10_scores = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('leaderboard.html', top_10_scores=top_10_scores)

@app.route('/highscores')
def highscores():
    return redirect(url_for('leaderboard'))

@app.route('/update_correct_answer', methods=['GET'])
def update_correct_answer():
    username = request.cookies.get('username')
    if not username:
        return jsonify({'success': False, 'message': 'Käyttäjää ei löytynyt.'}), 401

    new_correct_country = arvo_uusi_maa_ja_kentta()  # Arvotaan uusi oikea maa
    if new_correct_country:
        # Tallennetaan uusi oikea maa tietokantaan
        query = "UPDATE game SET kierroksen_Maa = %s WHERE username = %s"
        execute_query(query, (new_correct_country[0], username))
        return jsonify({'success': True, 'message': 'Uusi oikea maa päivitetty onnistuneesti.'})
    else:
        return jsonify({'success': False, 'message': 'Uuden oikean maan päivittäminen epäonnistui.'})


@app.route('/new_game', methods=['GET'])
def new_game():
    try:
        username = request.cookies.get('username')
        arvottu_tieto = arvo_uusi_maa_ja_kentta()
        if arvottu_tieto:
            arvottu_maa = arvottu_tieto[0]
            arvottu_latitude = arvottu_tieto[2]
            arvottu_longitude = arvottu_tieto[3]

            # Päivitä uusi maa, koordinaatit ja pistemäärä tietokantaan käyttäjänimen perusteella
            query = "UPDATE game SET kierroksen_Maa = %s, arvottu_latitude = %s, arvottu_longitude = %s, points = 1000 WHERE username = %s"
            values = (arvottu_maa, arvottu_latitude, arvottu_longitude, username)
            execute_query(query, values)

            # Poista evästeistä oikean maan koordinaatit
            response = make_response(jsonify({'success': True, 'arvottu_maa': arvottu_maa}))
            response.delete_cookie('arvottu_latitude')
            response.delete_cookie('arvottu_longitude')
            response.delete_cookie('vihje_kaytetty')
            response.delete_cookie('arvatut_maat')
            response.delete_cookie('oikea_maa_iso')
            return response
        else:
            response = jsonify({'success': False})
    except Exception as e:
        print("Virhe uutta maata arvottaessa:", e)
        response = jsonify({'success': False})

    return response


def paivita_hiscore(username, points):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT hiscore FROM game WHERE username = %s", (username,))
        hiscore = cursor.fetchone()[0]

        if points > hiscore:
            cursor.execute("UPDATE game SET hiscore = %s WHERE username = %s", (points, username))
            conn.commit()
    except Exception as e:
        print("Virhe päivittäessä hiscorea:", e)
    finally:
        cursor.close()
        conn.close()


if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.getenv('PORT', '5000')),
        debug=os.getenv('FLASK_DEBUG', '0') == '1'
    )
