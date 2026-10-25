from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

try:
    import streamlit as st
except ImportError:
    st = None

from engine_nba import (
    DEFAULT_CSV_DATA,
    LINEUP_COLS,
    build_default_lineups_dict,
    round_to_half_point,
)

# ==============================================================================
# ENDPOINTS OFICIALES: THE ODDS API & ESPN SCOREBOARD + CDN DE LOGOS
# ==============================================================================
THE_ODDS_API_NBA_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds/"
ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
URL_NBA_LOGOS = "https://a.espncdn.com/i/teamlogos/nba/500/{}.png"
NBA_SEASON_TARGET = "2026-27"

NBA_TEAMS: List[str] = [
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
]

# Mapeo exhaustivo de abreviaturas cortas y nombres completos (The Odds API + ESPN) -> 3 letras NBA
ESPN_TO_NBA_ABBR: Dict[str, str] = {
    "GS": "GSW",
    "GSW": "GSW",
    "GOLDEN STATE WARRIORS": "GSW",
    "GOLDEN STATE": "GSW",
    "WARRIORS": "GSW",
    "NY": "NYK",
    "NYK": "NYK",
    "NEW YORK KNICKS": "NYK",
    "NEW YORK": "NYK",
    "KNICKS": "NYK",
    "NO": "NOP",
    "NOP": "NOP",
    "NEW ORLEANS PELICANS": "NOP",
    "NEW ORLEANS": "NOP",
    "PELICANS": "NOP",
    "SA": "SAS",
    "SAS": "SAS",
    "SAN ANTONIO SPURS": "SAS",
    "SAN ANTONIO": "SAS",
    "SPURS": "SAS",
    "UTAH": "UTA",
    "UTA": "UTA",
    "UTAH JAZZ": "UTA",
    "JAZZ": "UTA",
    "WSH": "WAS",
    "WAS": "WAS",
    "WASHINGTON WIZARDS": "WAS",
    "WASHINGTON": "WAS",
    "WIZARDS": "WAS",
    "PHO": "PHX",
    "PHX": "PHX",
    "PHOENIX SUNS": "PHX",
    "PHOENIX": "PHX",
    "SUNS": "PHX",
    "BK": "BKN",
    "BKN": "BKN",
    "BRK": "BKN",
    "BROOKLYN NETS": "BKN",
    "BROOKLYN": "BKN",
    "NETS": "BKN",
    "BOS": "BOS",
    "BOSTON CELTICS": "BOS",
    "BOSTON": "BOS",
    "CELTICS": "BOS",
    "PHI": "PHI",
    "PHILADELPHIA 76ERS": "PHI",
    "PHILADELPHIA": "PHI",
    "76ERS": "PHI",
    "TOR": "TOR",
    "TORONTO RAPTORS": "TOR",
    "TORONTO": "TOR",
    "RAPTORS": "TOR",
    "CHI": "CHI",
    "CHICAGO BULLS": "CHI",
    "CHICAGO": "CHI",
    "BULLS": "CHI",
    "CLE": "CLE",
    "CLEVELAND CAVALIERS": "CLE",
    "CLEVELAND": "CLE",
    "CAVALIERS": "CLE",
    "DET": "DET",
    "DETROIT PISTONS": "DET",
    "DETROIT": "DET",
    "PISTONS": "DET",
    "IND": "IND",
    "INDIANA PACERS": "IND",
    "INDIANA": "IND",
    "PACERS": "IND",
    "MIL": "MIL",
    "MILWAUKEE BUCKS": "MIL",
    "MILWAUKEE": "MIL",
    "BUCKS": "MIL",
    "DEN": "DEN",
    "DENVER NUGGETS": "DEN",
    "DENVER": "DEN",
    "NUGGETS": "DEN",
    "MIN": "MIN",
    "MINNESOTA TIMBERWOLVES": "MIN",
    "MINNESOTA": "MIN",
    "TIMBERWOLVES": "MIN",
    "OKC": "OKC",
    "OKLAHOMA CITY THUNDER": "OKC",
    "OKLAHOMA CITY": "OKC",
    "THUNDER": "OKC",
    "POR": "POR",
    "PORTLAND TRAIL BLAZERS": "POR",
    "PORTLAND": "POR",
    "TRAIL BLAZERS": "POR",
    "LAC": "LAC",
    "LA CLIPPERS": "LAC",
    "LOS ANGELES CLIPPERS": "LAC",
    "CLIPPERS": "LAC",
    "LAL": "LAL",
    "LOS ANGELES LAKERS": "LAL",
    "LA LAKERS": "LAL",
    "LAKERS": "LAL",
    "SAC": "SAC",
    "SACRAMENTO KINGS": "SAC",
    "SACRAMENTO": "SAC",
    "KINGS": "SAC",
    "ATL": "ATL",
    "ATLANTA HAWKS": "ATL",
    "ATLANTA": "ATL",
    "HAWKS": "ATL",
    "CHA": "CHA",
    "CHO": "CHA",
    "CHARLOTTE HORNETS": "CHA",
    "CHARLOTTE": "CHA",
    "HORNETS": "CHA",
    "MIA": "MIA",
    "MIAMI HEAT": "MIA",
    "MIAMI": "MIA",
    "HEAT": "MIA",
    "ORL": "ORL",
    "ORLANDO MAGIC": "ORL",
    "ORLANDO": "ORL",
    "MAGIC": "ORL",
    "DAL": "DAL",
    "DALLAS MAVERICKS": "DAL",
    "DALLAS": "DAL",
    "MAVERICKS": "DAL",
    "HOU": "HOU",
    "HOUSTON ROCKETS": "HOU",
    "HOUSTON": "HOU",
    "ROCKETS": "HOU",
    "MEM": "MEM",
    "MEMPHIS GRIZZLIES": "MEM",
    "MEMPHIS": "MEM",
    "GRIZZLIES": "MEM",
}

ESPN_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

CUSTOM_HEADERS: Dict[str, str] = {
    "Host": "stats.nba.com",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
    "Connection": "keep-alive",
    "Referer": "https://www.nba.com/",
}

try:
    from nba_api.stats.library.http import NBAStatsHTTP
    from nba_api.stats.endpoints import LeagueDashPlayerStats, LeagueDashTeamStats

    NBAStatsHTTP.headers = CUSTOM_HEADERS
    NBA_API_AVAILABLE = True
except Exception:
    NBAStatsHTTP = None
    LeagueDashTeamStats = None
    LeagueDashPlayerStats = None
    NBA_API_AVAILABLE = False


def normalizar_abbr_nba(team_identifier: str) -> str:
    """
    Normaliza cualquier abreviatura o nombre de franquicia (de ESPN o The Odds API)
    al estándar oficial de 3 letras de nuestro motor (GSW, NYK, SAS, NOP, BOS, etc.).
    """
    raw = str(team_identifier).strip().upper()
    if raw in ESPN_TO_NBA_ABBR:
        return ESPN_TO_NBA_ABBR[raw]
    for key_name, abbr_val in ESPN_TO_NBA_ABBR.items():
        if len(key_name) > 3 and key_name in raw:
            return abbr_val
    return raw


def convertir_americano_a_decimal(momio: Any, default_decimal: float = 1.91) -> float:
    """
    Convierte una cuota americana (ej. -110, +115, 'EVEN') o decimal a formato DECIMAL
    estricto con 2 decimales:
      - Si momio > 0 (americano): round(1 + (momio / 100), 2)
      - Si momio < 0 (americano): round(1 + (100 / abs(momio)), 2)
      - Si ya viene en decimal (1.01 <= val < 25.0): round(val, 2)
    """
    if momio is None:
        return round(float(default_decimal), 2)
    if isinstance(momio, str):
        s = momio.strip().upper()
        if s in {"EVEN", "EV", "PK", "PICK"}:
            return 2.00
        s = s.replace(",", ".")
        match = re.search(r"[-+]?\d+(?:\.\d+)?", s)
        if not match:
            return round(float(default_decimal), 2)
        try:
            val = float(match.group(0))
        except ValueError:
            return round(float(default_decimal), 2)
    else:
        try:
            val = float(momio)
        except (TypeError, ValueError):
            return round(float(default_decimal), 2)

    if np.isnan(val) or val == 0.0:
        return round(float(default_decimal), 2)

    # Si ya es cuota decimal europea (ej. 1.91, 2.15)
    if 1.01 <= val < 25.0:
        return round(val, 2)

    if val > 0:
        return round(1.0 + (val / 100.0), 2)
    return round(1.0 + (100.0 / abs(val)), 2)


def escudo_nba_html(team_abbr: str, size: int = 32) -> str:
    """
    Genera la etiqueta <img> usando el CDN público de ESPN:
    https://a.espncdn.com/i/teamlogos/nba/500/{abbr}.png
    """
    abbr = normalizar_abbr_nba(team_abbr)
    url = f"https://a.espncdn.com/i/teamlogos/nba/500/{abbr.lower()}.png"
    return (
        f'<img src="{url}" width="{size}" height="{size}" '
        f'style="object-fit: contain; vertical-align: middle; margin-right: 8px;">'
    )


def _formatear_hora_partido(iso_date_str: str, short_detail: str) -> str:
    """Convierte la fecha ISO UTC de ESPN a hora del Este (ET) en formato HH:MM ET."""
    if iso_date_str:
        try:
            clean_iso = str(iso_date_str).replace("Z", "+00:00")
            dt_utc = datetime.fromisoformat(clean_iso)
            if dt_utc.tzinfo is None:
                dt_utc = dt_utc.replace(tzinfo=timezone.utc)
            dt_et = dt_utc.astimezone(ZoneInfo("America/New_York"))
            return dt_et.strftime("%H:%M ET")
        except Exception:
            pass
    if short_detail and "-" in short_detail:
        return short_detail.split("-")[-1].strip()
    return short_detail or "TBD"


def _extraer_odds_desde_evento_espn(
    comp: Dict[str, Any], away_abbr: str, home_abbr: str
) -> Optional[Dict[str, Any]]:
    """
    Extrae las líneas de consenso que vienen directamente en `competitions[0].odds`
    del endpoint público de ESPN Scoreboard y convierte cualquier momio americano a decimal.
    """
    odds_list = comp.get("odds", [])
    if not isinstance(odds_list, list) or not odds_list:
        return None

    odds_obj = None
    for candidate in odds_list:
        if isinstance(candidate, dict) and (
            candidate.get("overUnder") is not None
            or candidate.get("spread") is not None
            or candidate.get("details")
        ):
            odds_obj = candidate
            break
    if odds_obj is None:
        return None

    # 1. Total de mercado (Over/Under)
    total_mercado: Optional[float] = None
    if odds_obj.get("overUnder") is not None:
        try:
            total_mercado = round(float(odds_obj["overUnder"]), 1)
        except (TypeError, ValueError):
            total_mercado = None

    # Cuotas Over / Under en ESPN (pueden venir en overOdds / underOdds o total.over / total.under)
    raw_over_odds = odds_obj.get("overOdds")
    raw_under_odds = odds_obj.get("underOdds")
    total_nested = odds_obj.get("total", {}) if isinstance(odds_obj.get("total"), dict) else {}
    if raw_over_odds is None and isinstance(total_nested.get("over"), dict):
        raw_over_odds = total_nested["over"].get("close", {}).get("odds") or total_nested["over"].get("odds")
    if raw_under_odds is None and isinstance(total_nested.get("under"), dict):
        raw_under_odds = total_nested["under"].get("close", {}).get("odds") or total_nested["under"].get("odds")

    cuota_over_decimal = convertir_americano_a_decimal(raw_over_odds, default_decimal=1.91)
    cuota_under_decimal = convertir_americano_a_decimal(raw_under_odds, default_decimal=1.91)

    # 2. Spread del equipo Local (spread_mercado_home)
    spread_mercado_home: Optional[float] = None
    details_str = str(odds_obj.get("details", "")).strip().upper()
    if details_str:
        # Ejemplo details: "BOS -6.5" o "NY +4.5" o "EVEN"
        if details_str in {"EVEN", "PK", "PICK"}:
            spread_mercado_home = 0.0
        else:
            parts = details_str.split()
            if len(parts) >= 2:
                fav_abbr = normalizar_abbr_nba(parts[0])
                try:
                    line_val = float(parts[1])
                    if fav_abbr == home_abbr:
                        spread_mercado_home = round(-abs(line_val), 1)
                    elif fav_abbr == away_abbr:
                        spread_mercado_home = round(abs(line_val), 1)
                except ValueError:
                    pass

    if spread_mercado_home is None and odds_obj.get("spread") is not None:
        try:
            spread_mercado_home = round(float(odds_obj["spread"]), 1)
        except (TypeError, ValueError):
            spread_mercado_home = None

    home_team_odds = odds_obj.get("homeTeamOdds", {}) if isinstance(odds_obj.get("homeTeamOdds"), dict) else {}
    away_team_odds = odds_obj.get("awayTeamOdds", {}) if isinstance(odds_obj.get("awayTeamOdds"), dict) else {}
    spread_nested = odds_obj.get("pointSpread", {}) if isinstance(odds_obj.get("pointSpread"), dict) else {}

    raw_sp_home_odds = (
        home_team_odds.get("spreadOdds")
        or (spread_nested.get("home", {}).get("close", {}).get("odds") if isinstance(spread_nested.get("home"), dict) else None)
    )
    raw_sp_away_odds = (
        away_team_odds.get("spreadOdds")
        or (spread_nested.get("away", {}).get("close", {}).get("odds") if isinstance(spread_nested.get("away"), dict) else None)
    )

    cuota_spread_home_decimal = convertir_americano_a_decimal(raw_sp_home_odds, default_decimal=1.91)
    cuota_spread_away_decimal = convertir_americano_a_decimal(raw_sp_away_odds, default_decimal=1.91)

    provider_name = (
        odds_obj.get("provider", {}).get("name", "ESPN Consensus")
        if isinstance(odds_obj.get("provider"), dict)
        else "ESPN Consensus"
    )

    if total_mercado is None and spread_mercado_home is None:
        return None

    return {
        "matchup_key": f"{away_abbr}@{home_abbr}",
        "away_abbr": away_abbr,
        "home_abbr": home_abbr,
        "total_mercado": total_mercado,
        "cuota_over_decimal": cuota_over_decimal,
        "cuota_under_decimal": cuota_under_decimal,
        "spread_mercado_home": spread_mercado_home,
        "cuota_spread_home_decimal": cuota_spread_home_decimal,
        "cuota_spread_away_decimal": cuota_spread_away_decimal,
        "bookmaker": str(provider_name),
        "fuente": "ESPN Scoreboard Consensus",
    }


def _consultar_espn_scoreboard_raw(fecha_yyyymmdd: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Realiza la petición HTTP al endpoint público de ESPN Scoreboard."""
    url = ESPN_SCOREBOARD_URL
    if fecha_yyyymmdd:
        url = f"{ESPN_SCOREBOARD_URL}?dates={fecha_yyyymmdd}"

    try:
        resp = requests.get(url, headers=ESPN_HEADERS, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        try:
            req = urllib.request.Request(url, headers=ESPN_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            return None


def obtener_lineas_mercado_nba(
    api_key: Optional[str] = None,
    fecha_yyyymmdd: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    1. Consulta The Odds API para la NBA:
       - URL: 'https://api.the-odds-api.com/v4/sports/basketball_nba/odds/'
       - Parámetros: 'regions=us', 'markets=totals,spreads', 'oddsFormat=decimal'
    2. Extrae por cada partido programado:
       - 'total_mercado': línea de puntos O/U (ej. 228.5).
       - 'cuota_over_decimal' y 'cuota_under_decimal' (ej. 1.91 / 1.91).
       - 'spread_mercado_home': línea de hándicap del local (ej. -4.5 o +3.5).
       - 'cuota_spread_home_decimal' y 'cuota_spread_away_decimal' (ej. 1.93 / 1.88).
    3. Normaliza las abreviaturas de las 30 franquicias (GSW, NYK, SAS, NOP, etc.).
    4. Módulo Fallback de Respaldo: Si no se pasa API key o falla la llamada, extrae las líneas
       de consenso directamente del endpoint público de ESPN Scoreboard ('competitions[0].odds')
       convirtiendo cualquier momio americano a decimal con 2 decimales.
    """
    lineas_por_partido: Dict[str, Dict[str, Any]] = {}
    clean_key = str(api_key).strip() if api_key else ""

    # --------------------------------------------------------------------------
    # A. INTENTO PRIMARIO: THE ODDS API (SI SE PROPORCIONA API KEY)
    # --------------------------------------------------------------------------
    if clean_key:
        params = {
            "apiKey": clean_key,
            "regions": "us",
            "markets": "totals,spreads",
            "oddsFormat": "decimal",
        }
        try:
            resp = requests.get(THE_ODDS_API_NBA_URL, params=params, headers=ESPN_HEADERS, timeout=10)
            resp.raise_for_status()
            eventos_odds = resp.json()

            if isinstance(eventos_odds, list):
                for ev in eventos_odds:
                    away_team_raw = str(ev.get("away_team", "")).strip()
                    home_team_raw = str(ev.get("home_team", "")).strip()
                    away_abbr = normalizar_abbr_nba(away_team_raw)
                    home_abbr = normalizar_abbr_nba(home_team_raw)

                    if away_abbr not in NBA_TEAMS or home_abbr not in NBA_TEAMS:
                        continue

                    bookmakers = ev.get("bookmakers", [])
                    if not isinstance(bookmakers, list) or not bookmakers:
                        continue

                    total_mercado: Optional[float] = None
                    cuota_over_dec: float = 1.91
                    cuota_under_dec: float = 1.91
                    spread_home: Optional[float] = None
                    cuota_sp_home_dec: float = 1.91
                    cuota_sp_away_dec: float = 1.91
                    book_title: str = "US Sportsbook"

                    # Priorizar casas sharp/líderes si están disponibles (Pinnacle, DraftKings, FanDuel, BetMGM)
                    preferred_keys = {"pinnacle", "draftkings", "fanduel", "betmgm", "caesars", "bovada"}
                    sorted_books = sorted(
                        bookmakers,
                        key=lambda b: 0 if str(b.get("key", "")).lower() in preferred_keys else 1,
                    )

                    for book in sorted_books:
                        markets = book.get("markets", [])
                        if not isinstance(markets, list):
                            continue
                        for mkt in markets:
                            m_key = str(mkt.get("key", "")).lower()
                            outcomes = mkt.get("outcomes", [])
                            if not isinstance(outcomes, list):
                                continue

                            if m_key == "totals" and total_mercado is None:
                                over_out = next(
                                    (o for o in outcomes if str(o.get("name", "")).lower().startswith("over")),
                                    None,
                                )
                                under_out = next(
                                    (o for o in outcomes if str(o.get("name", "")).lower().startswith("under")),
                                    None,
                                )
                                if over_out and over_out.get("point") is not None:
                                    total_mercado = round(float(over_out["point"]), 1)
                                    cuota_over_dec = convertir_americano_a_decimal(over_out.get("price"), 1.91)
                                    if under_out:
                                        cuota_under_dec = convertir_americano_a_decimal(under_out.get("price"), 1.91)
                                    book_title = str(book.get("title", book_title))

                            elif m_key == "spreads" and spread_home is None:
                                home_out = None
                                away_out = None
                                for o in outcomes:
                                    o_abbr = normalizar_abbr_nba(str(o.get("name", "")))
                                    if o_abbr == home_abbr:
                                        home_out = o
                                    elif o_abbr == away_abbr:
                                        away_out = o

                                if home_out and home_out.get("point") is not None:
                                    spread_home = round(float(home_out["point"]), 1)
                                    cuota_sp_home_dec = convertir_americano_a_decimal(home_out.get("price"), 1.91)
                                    if away_out:
                                        cuota_sp_away_dec = convertir_americano_a_decimal(away_out.get("price"), 1.91)
                                    book_title = str(book.get("title", book_title))
                                elif away_out and away_out.get("point") is not None:
                                    spread_home = round(-float(away_out["point"]), 1)
                                    cuota_sp_away_dec = convertir_americano_a_decimal(away_out.get("price"), 1.91)
                                    book_title = str(book.get("title", book_title))

                        if total_mercado is not None and spread_home is not None:
                            break

                    if total_mercado is not None or spread_home is not None:
                        matchup_key = f"{away_abbr}@{home_abbr}"
                        lineas_por_partido[matchup_key] = {
                            "matchup_key": matchup_key,
                            "away_abbr": away_abbr,
                            "home_abbr": home_abbr,
                            "total_mercado": total_mercado,
                            "cuota_over_decimal": round(float(cuota_over_dec), 2),
                            "cuota_under_decimal": round(float(cuota_under_dec), 2),
                            "spread_mercado_home": spread_home,
                            "cuota_spread_home_decimal": round(float(cuota_sp_home_dec), 2),
                            "cuota_spread_away_decimal": round(float(cuota_sp_away_dec), 2),
                            "bookmaker": book_title,
                            "fuente": f"The Odds API ({book_title})",
                        }
        except Exception:
            # Si falla la llamada a The Odds API, continúa silenciosamente al Fallback de ESPN
            pass

    # --------------------------------------------------------------------------
    # B. MÓDULO FALLBACK DE RESPALDO: ESPN SCOREBOARD ('competitions[0].odds')
    # --------------------------------------------------------------------------
    payload_espn = _consultar_espn_scoreboard_raw(fecha_yyyymmdd=fecha_yyyymmdd)
    if isinstance(payload_espn, dict):
        for ev in payload_espn.get("events", []):
            try:
                competitions = ev.get("competitions", [])
                comp = competitions[0] if competitions else {}
                competitors = comp.get("competitors", [])

                away_abbr_raw = ""
                home_abbr_raw = ""
                for team_entry in competitors:
                    side = str(team_entry.get("homeAway", "")).lower()
                    abbr_val = str(team_entry.get("team", {}).get("abbreviation", "")).strip().upper()
                    if side == "away":
                        away_abbr_raw = abbr_val
                    elif side == "home":
                        home_abbr_raw = abbr_val

                away_abbr = normalizar_abbr_nba(away_abbr_raw)
                home_abbr = normalizar_abbr_nba(home_abbr_raw)
                if not away_abbr or not home_abbr:
                    continue

                matchup_key = f"{away_abbr}@{home_abbr}"
                espn_odds = _extraer_odds_desde_evento_espn(comp, away_abbr, home_abbr)
                if espn_odds is None:
                    continue

                if matchup_key not in lineas_por_partido:
                    lineas_por_partido[matchup_key] = espn_odds
                else:
                    # Completar campos faltantes si The Odds API devolvió solo uno de los mercados
                    existing = lineas_por_partido[matchup_key]
                    if existing.get("total_mercado") is None and espn_odds.get("total_mercado") is not None:
                        existing["total_mercado"] = espn_odds["total_mercado"]
                        existing["cuota_over_decimal"] = espn_odds["cuota_over_decimal"]
                        existing["cuota_under_decimal"] = espn_odds["cuota_under_decimal"]
                    if existing.get("spread_mercado_home") is None and espn_odds.get("spread_mercado_home") is not None:
                        existing["spread_mercado_home"] = espn_odds["spread_mercado_home"]
                        existing["cuota_spread_home_decimal"] = espn_odds["cuota_spread_home_decimal"]
                        existing["cuota_spread_away_decimal"] = espn_odds["cuota_spread_away_decimal"]
            except Exception:
                continue

    return lineas_por_partido


def obtener_calendario_nba_hoy(fecha_yyyymmdd: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Consulta el endpoint público de ESPN Scoreboard:
    https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard
    Extrae y parsea los partidos de la fecha en curso incluyendo cualquier línea de consenso en `competitions[0].odds`.
    """
    payload = _consultar_espn_scoreboard_raw(fecha_yyyymmdd=fecha_yyyymmdd)
    if not isinstance(payload, dict):
        return []

    eventos = payload.get("events", [])
    calendario: List[Dict[str, Any]] = []

    for ev in eventos:
        try:
            id_partido = str(ev.get("id", "")).strip()
            competitions = ev.get("competitions", [])
            comp = competitions[0] if competitions else {}
            competitors = comp.get("competitors", [])

            away_abbr_raw = ""
            home_abbr_raw = ""
            away_name = ""
            home_name = ""

            for team_entry in competitors:
                side = str(team_entry.get("homeAway", "")).lower()
                team_obj = team_entry.get("team", {})
                abbr_val = str(team_obj.get("abbreviation", "")).strip().upper()
                disp_name = str(team_obj.get("displayName", team_obj.get("name", abbr_val))).strip()

                if side == "away":
                    away_abbr_raw = abbr_val
                    away_name = disp_name
                elif side == "home":
                    home_abbr_raw = abbr_val
                    home_name = disp_name

            if not away_abbr_raw and len(competitors) >= 2:
                away_abbr_raw = str(competitors[1].get("team", {}).get("abbreviation", "")).upper()
                home_abbr_raw = str(competitors[0].get("team", {}).get("abbreviation", "")).upper()

            away_abbr = normalizar_abbr_nba(away_abbr_raw)
            home_abbr = normalizar_abbr_nba(home_abbr_raw)

            if not away_abbr or not home_abbr:
                continue

            nombre_evento = str(ev.get("name", "")).strip()
            if not nombre_evento:
                nombre_evento = f"{away_name or away_abbr} at {home_name or home_abbr}"

            status_obj = comp.get("status", ev.get("status", {})) or {}
            status_type = status_obj.get("type", {}) or {}
            short_detail = str(status_type.get("shortDetail", "")).strip()
            description = str(status_type.get("description", "Scheduled")).strip()
            state_code = str(status_type.get("state", "pre")).lower()

            iso_date = str(comp.get("date") or ev.get("date") or "").strip()
            hora_formateada = _formatear_hora_partido(iso_date, short_detail)

            if state_code == "in":
                estado_partido = f"EN VIVO ({short_detail})" if short_detail else "EN VIVO"
            elif state_code == "post":
                estado_partido = short_detail or "FINAL"
            else:
                estado_partido = description if description else "Programado"

            espn_odds = _extraer_odds_desde_evento_espn(comp, away_abbr, home_abbr)

            item_cal: Dict[str, Any] = {
                "id_partido": id_partido or f"{away_abbr}_{home_abbr}",
                "nombre": nombre_evento,
                "away_abbr": away_abbr,
                "home_abbr": home_abbr,
                "hora": hora_formateada,
                "estado": estado_partido,
            }
            if espn_odds:
                item_cal.update(espn_odds)

            calendario.append(item_cal)
        except Exception:
            continue

    return calendario


# ==============================================================================
# CARGA LOCAL Y SINCRONIZACIÓN DE ESTADÍSTICAS AVANZADAS (NBA_API + CSV BACKUP)
# ==============================================================================
def load_clean_nba_dataframe(uploaded_file=None) -> Tuple[pd.DataFrame, str]:
    """Carga el archivo local nba_stats_completo.csv (o el respaldo embebido de 30 equipos)."""
    if uploaded_file is not None:
        df = pd.read_csv(uploaded_file)
        return df.copy(), f"Archivo CSV cargado ({len(df)} equipos)"

    candidate_paths = [
        Path("nba_stats_completo.csv"),
        Path(__file__).resolve().parent / "nba_stats_completo.csv",
        Path("/working_dir/c_ff23c4fefe14d05d/artifacts/file_generation/ttl=63d/output/nba_stats_completo.csv"),
    ]
    for path in candidate_paths:
        if path.exists():
            df = pd.read_csv(path)
            if len(df) >= 30:
                return df.copy(), f"Respaldo Local ({path.name} - {len(df)} equipos)"

    df = pd.DataFrame(DEFAULT_CSV_DATA)
    try:
        df.to_csv("nba_stats_completo.csv", index=False, encoding="utf-8")
    except OSError:
        pass
    return df.copy(), f"Respaldo Local (nba_stats_completo.csv - {len(df)} equipos)"


def _cache_decorator(func):
    if st is not None and hasattr(st, "cache_data"):
        return st.cache_data(ttl=43200, show_spinner=False)(func)
    return func


@_cache_decorator
def _query_nba_api_endpoints(season: str = NBA_SEASON_TARGET) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Descarga en dos consultas únicas cacheadas por 12h (43,200 s):
    1) Estadísticas avanzadas de los 30 equipos (`LeagueDashTeamStats`).
    2) Estadísticas base de todos los jugadores (`LeagueDashPlayerStats`).
    """
    if not NBA_API_AVAILABLE or LeagueDashTeamStats is None or LeagueDashPlayerStats is None:
        raise RuntimeError("El paquete nba_api no está disponible en este entorno.")

    NBAStatsHTTP.headers = CUSTOM_HEADERS

    team_adv_endpoint = LeagueDashTeamStats(
        season=season,
        measure_type_detailed_defense="Advanced",
        per_mode_detailed="PerGame",
        headers=CUSTOM_HEADERS,
        timeout=12,
    )
    df_team_adv = team_adv_endpoint.get_data_frames()[0]

    time.sleep(1.0)

    player_base_endpoint = LeagueDashPlayerStats(
        season=season,
        per_mode_detailed="PerGame",
        headers=CUSTOM_HEADERS,
        timeout=12,
    )
    df_players = player_base_endpoint.get_data_frames()[0]

    if df_team_adv.empty or df_players.empty:
        raise ValueError(f"NBA.com devolvió tablas vacías para la temporada {season}.")

    return df_team_adv, df_players


def sincronizar_datos_nba_api(
    season: str = NBA_SEASON_TARGET,
) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame], str, bool]:
    """
    Intenta extraer titulares, estrellas y ratings actualizados desde `nba_api`.
    Si falla, muestra `st.warning(...)` y opera con `nba_stats_completo.csv`.
    """
    base_df, local_label = load_clean_nba_dataframe()
    base_lineups = build_default_lineups_dict()

    try:
        df_team_adv, df_players = _query_nba_api_endpoints(season=season)
        updated_df = base_df.copy()
        updated_lineups = {k: v.copy() for k, v in base_lineups.items()}

        for idx, row in updated_df.iterrows():
            t_name = str(row["Team"])
            t_abbr = str(row["Team_Abbr"]).upper()

            team_match = pd.DataFrame()
            if "TEAM_ABBREVIATION" in df_team_adv.columns:
                team_match = df_team_adv[df_team_adv["TEAM_ABBREVIATION"].astype(str).str.upper() == t_abbr]
            if team_match.empty and "TEAM_NAME" in df_team_adv.columns:
                team_match = df_team_adv[
                    df_team_adv["TEAM_NAME"].astype(str).str.lower().str.contains(t_name.split()[-1].lower())
                ]

            if not team_match.empty:
                tm = team_match.iloc[0]
                if "PACE" in tm and pd.notna(tm["PACE"]):
                    updated_df.loc[idx, "Pace"] = round(float(tm["PACE"]), 1)
                if "OFF_RATING" in tm and pd.notna(tm["OFF_RATING"]):
                    updated_df.loc[idx, "Off_Rtg"] = round(float(tm["OFF_RATING"]), 1)
                if "DEF_RATING" in tm and pd.notna(tm["DEF_RATING"]):
                    updated_df.loc[idx, "Def_Rtg"] = round(float(tm["DEF_RATING"]), 1)
                if "TM_TOV_PCT" in tm and pd.notna(tm["TM_TOV_PCT"]):
                    tov_val = float(tm["TM_TOV_PCT"])
                    updated_df.loc[idx, "TOV_Pct"] = round(tov_val * 100.0 if tov_val < 1.0 else tov_val, 1)

            if "TEAM_ABBREVIATION" in df_players.columns:
                p_team = df_players[df_players["TEAM_ABBREVIATION"].astype(str).str.upper() == t_abbr].copy()
                if not p_team.empty and "PTS" in p_team.columns and "MIN" in p_team.columns:
                    p_team["PTS"] = pd.to_numeric(p_team["PTS"], errors="coerce").fillna(0.0)
                    p_team["MIN"] = pd.to_numeric(p_team["MIN"], errors="coerce").fillna(0.0)

                    top_scorers = p_team.sort_values(by=["PTS", "MIN"], ascending=False)
                    if len(top_scorers) >= 1:
                        s1 = top_scorers.iloc[0]
                        s1_ppg = round(float(s1["PTS"]), 1)
                        updated_df.loc[idx, "Star1_Name"] = str(s1["PLAYER_NAME"])
                        updated_df.loc[idx, "Star1_PPG"] = s1_ppg
                        updated_df.loc[idx, "Star1_Line"] = round_to_half_point(max(0.5, s1_ppg - 0.5))
                    if len(top_scorers) >= 2:
                        s2 = top_scorers.iloc[1]
                        s2_ppg = round(float(s2["PTS"]), 1)
                        updated_df.loc[idx, "Star2_Name"] = str(s2["PLAYER_NAME"])
                        updated_df.loc[idx, "Star2_PPG"] = s2_ppg
                        updated_df.loc[idx, "Star2_Line"] = round_to_half_point(max(0.5, s2_ppg - 0.5))

                    top_starters = p_team.sort_values(by=["MIN", "PTS"], ascending=False).head(5)
                    if len(top_starters) == 5 and t_abbr in updated_lineups:
                        lu_df = updated_lineups[t_abbr].copy()
                        starter_mins_sum = 0.0
                        for s_i in range(5):
                            pl_row = top_starters.iloc[s_i]
                            pl_mins = round(float(np.clip(pl_row["MIN"], 18.0, 40.0)), 1)
                            starter_mins_sum += pl_mins
                            lu_df.loc[s_i, "Jugador"] = str(pl_row["PLAYER_NAME"])
                            lu_df.loc[s_i, "Minutos_Esperados"] = pl_mins
                        lu_df.loc[5, "Minutos_Esperados"] = round(max(40.0, 240.0 - starter_mins_sum), 1)
                        updated_lineups[t_abbr] = lu_df

        if st is not None and hasattr(st, "session_state"):
            st.session_state.df_nba = updated_df
            st.session_state.lineups_nba = updated_lineups
            source_msg = f"NBA.com Live API ({season} Sincronizado)"
            st.session_state.data_source_label = source_msg
            st.session_state.nba_api_status = "ONLINE (NBA.com Live)"
        return updated_df, updated_lineups, f"NBA.com Live API ({season} Sincronizado)", True

    except Exception as e:
        if st is not None and hasattr(st, "warning"):
            st.warning("NBA.com no disponible temporalmente. Operando con base de respaldo local.")
        if st is not None and hasattr(st, "session_state"):
            st.session_state.df_nba = base_df
            if "lineups_nba" not in st.session_state:
                st.session_state.lineups_nba = base_lineups
            st.session_state.data_source_label = local_label
            st.session_state.nba_api_status = f"FALLBACK LOCAL ({type(e).__name__})"
            return base_df, st.session_state.lineups_nba, local_label, False
        return base_df, base_lineups, local_label, False