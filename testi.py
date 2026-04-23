from flask import Flask, render_template, request, redirect, url_for, flash, make_response, jsonify
from geopy.distance import geodesic
import difflib
import json
import math
import os
import random
import threading
import time
import urllib.error
import urllib.request
import mysql.connector
from mysql.connector import pooling
from urllib.parse import urlparse, unquote, quote

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

# Varalista tunnetuista kartalla ei-klikattavista maista/alueista.
# Tätä käytetään, jos selain ei ole vielä ehtinyt lähettää klikattavien maiden listaa.
KARTTA_EI_KLIKATTAVAT_ISO_FALLBACK = {
    "GP",  # Guadeloupe
}


def laske_arvauksen_pistevahennys(points):
    pisteet = max(0, int(points or 0))
    if pisteet > 500:
        return 100
    if pisteet > 400:
        return 50
    if pisteet > 300:
        return 25
    if pisteet > 200:
        return 10
    if pisteet > 100:
        return 5
    if pisteet > 0:
        return 1
    return 0


def laske_vihjeen_pistehinta(points):
    pisteet = max(0, int(points or 0))
    # Vihjeen hinta = kahden arvauksen verran nykyisellä pistealueella.
    return min(pisteet, laske_arvauksen_pistevahennys(pisteet) * 2)


DB_POOL = None
DB_POOL_SIG = None
AIVEN_WAKE_LOCK = threading.Lock()
AIVEN_LAST_WAKE_ATTEMPT_TS = 0.0
AIVEN_WAKE_CONFIG_WARNED = False

# Tietokantayhteyden avausfunktio
def _build_db_connection_config():
    db_url = os.getenv('DB_URL') or os.getenv('DATABASE_URL') or os.getenv('DB_URI')
    parsed = urlparse(db_url) if db_url else None

    host = (os.getenv('DB_HOST') or (parsed.hostname if parsed else '') or '127.0.0.1').strip()
    port_raw = (os.getenv('DB_PORT') or (str(parsed.port) if parsed and parsed.port else '') or '3306').strip()
    database = (os.getenv('DB_NAME') or (parsed.path.lstrip('/') if parsed and parsed.path else '') or 'lentopeli').strip()
    user = (os.getenv('DB_USER') or (unquote(parsed.username) if parsed and parsed.username else '') or 'root').strip()
    password = os.getenv('DB_PASSWORD')
    if password is None:
        password = unquote(parsed.password) if parsed and parsed.password else ''

    # Tue myös muotoa "host:port" DB_HOST-arvossa.
    if ":" in host and host.rsplit(":", 1)[1].isdigit():
        host, host_port = host.rsplit(":", 1)
        if not os.getenv('DB_PORT'):
            port_raw = host_port

    # Jos DB_NAME:ksi on vahingossa annettu portti, käytä sitä porttina.
    if database.isdigit() and (not os.getenv('DB_PORT') or port_raw == '3306'):
        port_raw = database
        database = os.getenv('DB_DATABASE', 'defaultdb')

    try:
        port = int(port_raw)
    except ValueError:
        port = 3306

    conn_kwargs = {
        'host': host,
        'port': port,
        'database': database,
        'user': user,
        'password': password,
        'autocommit': True,
        'connection_timeout': 10,
    }

    ssl_mode = (os.getenv('DB_SSL_MODE') or '').strip().upper()
    if not ssl_mode and host.endswith('aivencloud.com'):
        ssl_mode = 'REQUIRED'

    if ssl_mode not in ('', 'DISABLED', 'OFF', 'FALSE', '0'):
        conn_kwargs['ssl_disabled'] = False
        ssl_ca_path = (os.getenv('DB_SSL_CA_PATH') or os.getenv('DB_SSL_CA') or '').strip()
        if ssl_ca_path and os.path.exists(ssl_ca_path):
            conn_kwargs['ssl_ca'] = ssl_ca_path
    elif ssl_mode in ('DISABLED', 'OFF', 'FALSE', '0'):
        conn_kwargs['ssl_disabled'] = True

    return conn_kwargs


def _config_signature(conn_kwargs):
    return (
        conn_kwargs.get('host'),
        conn_kwargs.get('port'),
        conn_kwargs.get('database'),
        conn_kwargs.get('user'),
        conn_kwargs.get('password'),
        conn_kwargs.get('ssl_disabled', None),
        conn_kwargs.get('ssl_ca', None),
    )


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def _aiven_service_name_from_host(host):
    host = (host or '').strip()
    if not host:
        return ''
    # Esim. "mysql-18002453-metropolia-7188.i.aivencloud.com" -> "mysql-18002453"
    first_label = host.split('.', 1)[0]
    if not first_label:
        return ''
    return first_label.split('-', 2)[0] + '-' + first_label.split('-', 2)[1] if '-' in first_label else first_label


def _should_try_aiven_wakeup(conn_kwargs, error):
    host = (conn_kwargs.get('host') or '').lower()
    if not host.endswith('aivencloud.com'):
        return False
    errno = getattr(error, 'errno', None)
    if errno in (2003, 2005, 2013):
        return True
    message = str(error).lower()
    return any(fragment in message for fragment in (
        'unknown mysql server host',
        'can\'t connect',
        'connection refused',
        'timed out',
        'name or service not known',
        'temporary failure in name resolution',
    ))


def _aiven_api_request(method, url, token, payload=None, timeout=10):
    headers = {
        'Authorization': f'aivenv1 {token}',
        'Content-Type': 'application/json',
    }
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url=url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
            parsed = json.loads(raw) if raw else {}
            return resp.getcode(), parsed, ''
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', errors='replace')
        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {}
        return e.code, parsed, raw
    except urllib.error.URLError as e:
        return None, {}, str(e)
    except Exception as e:
        return None, {}, str(e)


def _maybe_power_on_aiven_service(conn_kwargs):
    global AIVEN_LAST_WAKE_ATTEMPT_TS, AIVEN_WAKE_CONFIG_WARNED

    if not _env_bool('AIVEN_AUTO_POWER_ON', True):
        return False

    host = (conn_kwargs.get('host') or '').strip().lower()
    if not host.endswith('aivencloud.com'):
        return False

    token = (os.getenv('AIVEN_API_TOKEN') or os.getenv('AIVEN_TOKEN') or '').strip()
    project = (os.getenv('AIVEN_PROJECT') or os.getenv('AIVEN_PROJECT_NAME') or '').strip()
    service_name = (os.getenv('AIVEN_SERVICE_NAME') or _aiven_service_name_from_host(host) or '').strip()
    api_base = (os.getenv('AIVEN_API_BASE_URL') or 'https://api.aiven.io/v1').strip().rstrip('/')

    if not token or not project or not service_name:
        if not AIVEN_WAKE_CONFIG_WARNED:
            app.logger.warning(
                'Aiven auto power-on ohitettu: aseta env-muuttujat AIVEN_API_TOKEN, '
                'AIVEN_PROJECT ja AIVEN_SERVICE_NAME.'
            )
            AIVEN_WAKE_CONFIG_WARNED = True
        return False

    cooldown_raw = os.getenv('AIVEN_WAKE_COOLDOWN_SECONDS', '90')
    try:
        cooldown = max(15, int(cooldown_raw))
    except ValueError:
        cooldown = 90

    now = time.time()
    with AIVEN_WAKE_LOCK:
        if now - AIVEN_LAST_WAKE_ATTEMPT_TS < cooldown:
            return False
        AIVEN_LAST_WAKE_ATTEMPT_TS = now

    project_q = quote(project, safe='')
    service_q = quote(service_name, safe='')
    service_url = f'{api_base}/project/{project_q}/service/{service_q}'

    # Jos palvelu on jo käynnissä, ei tehdä mitään.
    status, response_json, _ = _aiven_api_request('GET', service_url, token, timeout=8)
    if status and 200 <= status < 300:
        state = ((response_json or {}).get('service') or {}).get('state', '')
        if str(state).lower() == 'running':
            return False

    for payload in ({'powered': True}, {'power_on': True}):
        status, _, error_text = _aiven_api_request('PUT', service_url, token, payload=payload, timeout=12)
        if status and 200 <= status < 300:
            app.logger.info('Aiven-palvelun käynnistys pyydetty API:n kautta (%s).', service_name)
            return True
        if status in (409, 422):
            # Muutos on jo käynnissä tai palvelu on käytännössä jo tulossa ylös.
            app.logger.info('Aiven-palvelun käynnistys on jo käynnissä (%s).', service_name)
            return True
        if error_text:
            app.logger.warning('Aiven auto power-on epäonnistui (%s): %s', service_name, error_text)

    return False


def _get_db_pool():
    global DB_POOL, DB_POOL_SIG
    conn_kwargs = _build_db_connection_config()
    nykyinen_sig = _config_signature(conn_kwargs)
    pool_size_raw = os.getenv('DB_POOL_SIZE', '8')
    try:
        pool_size = max(1, int(pool_size_raw))
    except ValueError:
        pool_size = 8

    if DB_POOL is None or DB_POOL_SIG != nykyinen_sig:
        DB_POOL = pooling.MySQLConnectionPool(
            pool_name='lentokonepeli_pool',
            pool_size=pool_size,
            pool_reset_session=True,
            **conn_kwargs
        )
        DB_POOL_SIG = nykyinen_sig

    return DB_POOL


def get_db_connection():
    global DB_POOL
    conn_kwargs = _build_db_connection_config()
    try:
        conn = _get_db_pool().get_connection()
    except mysql.connector.Error as first_error:
        # Jos pooli meni epäkuntoon, luodaan se seuraavalla kutsulla uudestaan.
        DB_POOL = None
        wake_requested = False
        if _should_try_aiven_wakeup(conn_kwargs, first_error):
            wake_requested = _maybe_power_on_aiven_service(conn_kwargs)
            if wake_requested:
                retry_delay_raw = os.getenv('AIVEN_WAKE_RETRY_DELAY_SECONDS', '4')
                try:
                    retry_delay = min(20, max(0, int(retry_delay_raw)))
                except ValueError:
                    retry_delay = 4
                if retry_delay:
                    time.sleep(retry_delay)
        try:
            conn = _get_db_pool().get_connection()
        except mysql.connector.Error as second_error:
            if wake_requested:
                raise RuntimeError(
                    'Aiven-tietokantaa heratellaan parhaillaan. '
                    'Odota noin 30-90 sekuntia ja yrita uudelleen.'
                ) from second_error
            raise
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
        cursor.execute("SELECT 1 FROM game WHERE username = %s", (username,))
        loytyi = cursor.fetchone()
        if not loytyi:
            _lisaa_uusi_pelaaja_yhteensopivasti(cursor, conn, username)
    finally:
        cursor.close()
        conn.close()


def _suorita_insert_yhteensopivasti(cursor, conn, yritykset):
    viimeisin_virhe = None
    for query, values in yritykset:
        try:
            cursor.execute(query, values)
            conn.commit()
            return
        except mysql.connector.IntegrityError as e:
            conn.rollback()
            # Rinnakkaisissa pyynnöissä käyttäjä voi ehtiä syntyä toisaalla.
            if e.errno == 1062:
                return
            viimeisin_virhe = e
        except mysql.connector.Error as e:
            conn.rollback()
            viimeisin_virhe = e

    if viimeisin_virhe:
        raise viimeisin_virhe
    raise RuntimeError("Pelaajan lisääminen epäonnistui ilman tarkempaa virhettä.")


def _lisaa_uusi_pelaaja_yhteensopivasti(cursor, conn, username):
    yritykset = []
    dynaaminen_insert_lisatty = False

    try:
        cursor.execute("SHOW COLUMNS FROM game")
        sarakkeet = cursor.fetchall()
        if sarakkeet:
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

            if "username" in sarake_meta:
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
                    if any(numeerinen in tyyppi for numeerinen in (
                        "int", "decimal", "float", "double", "numeric", "real", "bit", "bool"
                    )):
                        insert_sarakkeet.append(sarake)
                        insert_arvot.append(0)
                    elif any(merkkityyppi in tyyppi for merkkityyppi in ("char", "text", "enum", "set")):
                        insert_sarakkeet.append(sarake)
                        insert_arvot.append("")
                    elif "datetime" in tyyppi or "timestamp" in tyyppi:
                        insert_sarakkeet.append(sarake)
                        insert_arvot.append("1970-01-01 00:00:00")
                    elif tyyppi.startswith("date"):
                        insert_sarakkeet.append(sarake)
                        insert_arvot.append("1970-01-01")
                    elif tyyppi.startswith("time"):
                        insert_sarakkeet.append(sarake)
                        insert_arvot.append("00:00:00")
                    elif "json" in tyyppi:
                        insert_sarakkeet.append(sarake)
                        insert_arvot.append("{}")
                    else:
                        raise RuntimeError(
                            f"game-taulussa vaaditaan sarake '{sarake}', jolle ei osattu antaa oletusarvoa."
                        )

                if insert_sarakkeet:
                    placeholders = ", ".join(["%s"] * len(insert_sarakkeet))
                    sarakkeet_sql = ", ".join(insert_sarakkeet)
                    yritykset.append((
                        f"INSERT INTO game ({sarakkeet_sql}) VALUES ({placeholders})",
                        tuple(insert_arvot)
                    ))
                    dynaaminen_insert_lisatty = True
    except Exception:
        # Jos dynaaminen tunnistus epäonnistuu, jatketaan fallback-yrityksillä.
        pass

    # Fallback: yritetään yleisimpiä skeemoja järjestyksessä.
    yritykset.extend([
        ("INSERT INTO game (username, password, points, hiscore) VALUES (%s, %s, %s, %s)", (username, "", 1000, 0)),
        ("INSERT INTO game (username, points, hiscore) VALUES (%s, %s, %s)", (username, 1000, 0)),
        ("INSERT INTO game (username, points) VALUES (%s, %s)", (username, 1000)),
        ("INSERT INTO game (username) VALUES (%s)", (username,)),
    ])

    if not dynaaminen_insert_lisatty and not yritykset:
        raise RuntimeError("Pelaajan lisäämiseen ei löytynyt yhtään käyttökelpoista insert-vaihtoehtoa.")

    _suorita_insert_yhteensopivasti(cursor, conn, yritykset)


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
    except Exception as e:
        app.logger.exception("Nimen asetus epäonnistui /set_name-reitillä.")
        virhe = str(e)
        db_host = os.getenv('DB_HOST', '')
        db_port = os.getenv('DB_PORT', '')
        if (
            'aivencloud.com' in db_host
            and (db_port in ('', '3306'))
        ):
            flash(
                'Pelin aloitus epäonnistui: tietokannan portti näyttää väärältä. '
                'Aseta Renderiin DB_PORT = Aivenin portti (esim. 13734).',
                'danger'
            )
        elif virhe:
            flash(f'Pelin aloitus epäonnistui: {virhe}', 'danger')
        else:
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


# Arvotaan uusi maa ja kenttä ja tallennetaan koordinaatit evästeisiin.
# Parametri sallitut_iso_koodit rajaa arvonnan vain kartalta klikattaviin maihin.
def arvo_uusi_maa_ja_kentta(sallitut_iso_koodit=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        query = """
            SELECT
                country.name,
                MAX(airport.name) AS largest_airport,
                country.latitude,
                country.longitude,
                country.iso_country
            FROM country
            INNER JOIN airport ON country.iso_country = airport.iso_country
            WHERE airport.type = 'large_airport'
        """
        values = []

        if sallitut_iso_koodit:
            placeholders = ", ".join(["%s"] * len(sallitut_iso_koodit))
            query += f" AND country.iso_country IN ({placeholders})"
            values.extend(list(sallitut_iso_koodit))

        if KARTTA_EI_KLIKATTAVAT_ISO_FALLBACK:
            placeholders = ", ".join(["%s"] * len(KARTTA_EI_KLIKATTAVAT_ISO_FALLBACK))
            query += f" AND country.iso_country NOT IN ({placeholders})"
            values.extend(sorted(KARTTA_EI_KLIKATTAVAT_ISO_FALLBACK))

        query += """
            GROUP BY country.iso_country, country.name, country.latitude, country.longitude;
        """

        cursor.execute(query, tuple(values))
        tiedot = cursor.fetchall()
        if not tiedot:
            return None
        # Palautetaan (maa, lentokenttä, latitude, longitude, iso_country)
        return random.choice(tiedot)
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
        vihje_hinta = 0
        if username:
            points = hae_kayttajan_pisteet(username)
            vihje_hinta = laske_vihjeen_pistehinta(points)
            if not vihje_kaytetty and not kierros_voitettu and vihje_hinta > 0:
                points = max(0, points - vihje_hinta)
                lisaa_pisteet(username, points)

        response = make_response(jsonify({
            'largest_airport_name': largest_airport_name,
            'points': points,
            'hint_cost': vihje_hinta
        }))
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

def hae_lahin_maaehdotus(maa, maat=None):
    syote = (maa or "").strip()
    if not syote or not any(char.isalpha() for char in syote):
        return None

    if maat is None:
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


def hae_maiden_konteksti():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT iso_country, name, latitude, longitude FROM country")
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    sallitut_iso_koodit = []
    iso_maa_nimi_map = {}
    maa_nimi_map = {}
    maa_tiedot_norm_map = {}
    maat_nimet = []

    for row in rows:
        if not row:
            continue

        iso_raaka = (row[0] or "").strip().upper()
        nimi = (row[1] or "").strip()
        lat = row[2]
        lng = row[3]

        if not nimi:
            continue

        maat_nimet.append(nimi)
        norm = _normalisoi_maa_syote(nimi)
        if norm:
            maa_nimi_map[norm] = nimi
            if lat is not None and lng is not None:
                maa_tiedot_norm_map[norm] = {
                    'name': nimi,
                    'iso_country': iso_raaka,
                    'latitude': float(lat),
                    'longitude': float(lng),
                }

        if len(iso_raaka) == 2 and iso_raaka.isalpha():
            sallitut_iso_koodit.append(iso_raaka)
            iso_maa_nimi_map[iso_raaka] = nimi

    return {
        'sallitut_iso_koodit': sorted(set(sallitut_iso_koodit)),
        'iso_maa_nimi_map': iso_maa_nimi_map,
        'maa_nimi_map': maa_nimi_map,
        'maa_tiedot_norm_map': maa_tiedot_norm_map,
        'maat_nimet': maat_nimet,
    }

def _hae_arvatut_maat_cookie():
    arvatut_maat_raaka = request.cookies.get('arvatut_maat', '')
    arvatut_maat = []
    for arvo in arvatut_maat_raaka.split(','):
        koodi = arvo.strip().upper()
        if len(koodi) == 2 and koodi.isalpha() and koodi not in arvatut_maat:
            arvatut_maat.append(koodi)
    return arvatut_maat


def _hae_klikattavat_maat_cookie():
    klikattavat_raaka = request.cookies.get('klikattavat_maat', '')
    klikattavat = []
    for arvo in klikattavat_raaka.split(','):
        koodi = arvo.strip().upper()
        if len(koodi) == 2 and koodi.isalpha() and koodi not in klikattavat:
            klikattavat.append(koodi)
    return klikattavat


def _hae_arvottavat_iso_koodit(sallitut_iso_koodit=None):
    klikattavat = _hae_klikattavat_maat_cookie()
    if sallitut_iso_koodit:
        sallitut_set = set(sallitut_iso_koodit)
        klikattavat = [koodi for koodi in klikattavat if koodi in sallitut_set]
    return klikattavat if klikattavat else None

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
    maiden_konteksti = hae_maiden_konteksti()
    sallitut_iso_koodit = maiden_konteksti['sallitut_iso_koodit']
    iso_maa_nimi_map = maiden_konteksti['iso_maa_nimi_map']
    maa_nimi_map = maiden_konteksti['maa_nimi_map']
    maa_tiedot_norm_map = maiden_konteksti['maa_tiedot_norm_map']
    maat_nimet = maiden_konteksti['maat_nimet']
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
        arvottava_iso_lista = _hae_arvottavat_iso_koodit(sallitut_iso_koodit=sallitut_iso_koodit)
        arvottu_tieto = arvo_uusi_maa_ja_kentta(arvottava_iso_lista)
        if arvottu_tieto is None:
            tulos = "Tietokannassa ei ole maita/lentokenttia. Aja sql/init.sql ensin."
            result_category = 'danger'
            return make_response(render_template(
                'game.html',
                result=tulos,
                result_category=result_category,
                points=0,
                vihje_hinta=laske_vihjeen_pistehinta(0),
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
            vihje_hinta=laske_vihjeen_pistehinta(user_points),
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
        pelaajan_maa_syote = request.form.get('pelaajan_maa')
        if pelaajan_maa_syote:
            syote_norm = _normalisoi_maa_syote(pelaajan_maa_syote)
            maan_tiedot = maa_tiedot_norm_map.get(syote_norm)
            if maan_tiedot:
                pelaajan_maa = maan_tiedot['name']
                pelaajan_maa_koord = (maan_tiedot['latitude'], maan_tiedot['longitude'])
                pisteet = 0
                maan_iso_koodi = (maan_tiedot['iso_country'] or "").upper()
                onko_jo_arvattu = bool(maan_iso_koodi and maan_iso_koodi in arvatut_maat)
                if maan_iso_koodi and not onko_jo_arvattu:
                    arvatut_maat.append(maan_iso_koodi)
                arvottu_latitude = float(arvottu_latitude)
                arvottu_longitude = float(arvottu_longitude)
                etaisyys, ilmansuunta = laske_etaisyys_ja_ilmansuunta(
                    pelaajan_maa_koord,
                    (arvottu_latitude, arvottu_longitude)
                )

                if onko_jo_arvattu:
                    result_category = 'info'
                    tulos = f'Olet jo arvannut jo maata "{pelaajan_maa}". Kolumbus on {etaisyys} km päässä {ilmansuunta}.'
                elif _normalisoi_maa_syote(pelaajan_maa) == _normalisoi_maa_syote(arvottu_maa):
                    pisteet = 0
                    lisaa_pisteet(username, user_points)
                    tulos = (
                        f'Arvasit oikein! Oikea maa on: {arvottu_maa}. Keräsit {user_points} pistettä! '
                        'Aloita uusi peli "Aloita uusi peli" napista.'
                    )
                    paivita_hiscore(username, user_points)
                    oikea_osuma = True
                    oikea_maa_iso = maan_iso_koodi
                else:
                    vahennys = laske_arvauksen_pistevahennys(user_points)
                    uusi_pistemaara = max(0, user_points - vahennys)
                    pisteet = uusi_pistemaara - user_points
                    lisaa_pisteet(username, uusi_pistemaara)
                    user_points = uusi_pistemaara
                    result_category = 'info'
                    tulos = f'Arvauksesi "{pelaajan_maa}" on väärin. Kolumbus on {etaisyys} km päässä {ilmansuunta}.'

                kierros_voitettu = bool(oikea_maa_iso and oikea_maa_iso in arvatut_maat)

                response = make_response(
                    render_template(
                        'game.html',
                        result=tulos,
                        result_category=result_category,
                        points=user_points,
                        pisteet=pisteet,
                        pelaajan_maa_koord=pelaajan_maa_koord,
                        vihje_hinta=laske_vihjeen_pistehinta(user_points),
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
                    )
                )
                _tallenna_arvatut_maat_cookie(response, arvatut_maat)
                if oikea_osuma and oikea_maa_iso:
                    response.set_cookie('oikea_maa_iso', oikea_maa_iso)
                return response
            else:
                ehdotus = hae_lahin_maaehdotus(pelaajan_maa_syote, maat=maat_nimet)
                if ehdotus:
                    tulos = f'Maa on kirjoitettu väärin, tarkoititko {ehdotus}?'
                else:
                    tulos = "Maa on kirjoitettu väärin tai sitä ei ole olemassa."
                result_category = 'danger'
        else:
            tulos = "Syötä arvaus."

    # Tallenna pisteet evästeisiin (GET / invalid syöte käyttää nykyistä arvoa)
    response = make_response(render_template(
        'game.html',
        result=tulos,
        result_category=result_category,
        points=user_points,
        vihje_hinta=laske_vihjeen_pistehinta(user_points),
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
        arvottu_tieto = arvo_uusi_maa_ja_kentta(_hae_arvottavat_iso_koodit())
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

    new_correct_country = arvo_uusi_maa_ja_kentta(_hae_arvottavat_iso_koodit())  # Arvotaan uusi oikea maa
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
        arvottu_tieto = arvo_uusi_maa_ja_kentta(_hae_arvottavat_iso_koodit())
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
