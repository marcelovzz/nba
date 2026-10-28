from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.request
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

try:
    import requests
except ImportError:
    requests = None

try:
    import streamlit as st
except ImportError:
    st = None

try:
    from nba_api.stats.endpoints import LeagueDashPlayerStats, LeagueDashTeamStats
    from nba_api.stats.library.http import NBAStatsHTTP

    NBA_API_AVAILABLE = True
except Exception:
    NBAStatsHTTP = None
    LeagueDashTeamStats = None
    LeagueDashPlayerStats = None
    NBA_API_AVAILABLE = False

from engine_nba import (
    DEFAULT_CSV_DATA,
    build_default_lineups_dict,
    round_to_half_point,
)

# ==============================================================================
# 1. CLIENTE HTTP ROBUSTO CON HEADERS (PROTECCIÓN ANTI-BLOQUEO NBA_API & ESPN)
# ==============================================================================
NBA_SEASON_TARGET = "2026-27"

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

if NBAStatsHTTP is not None:
    NBAStatsHTTP.headers = CUSTOM_HEADERS

# ==============================================================================
# 2. ENDPOINTS OFICIALES: ESPN SCOREBOARD API + THE ODDS API (NBA DECIMAL)
# ==============================================================================
ESPN_NBA_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
)
THE_ODDS_API_NBA_URL = (
    "https://api.the-odds-api.com/v4/sports/basketball_nba/odds/"
)

ESPN_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

URL_NBA_LOGOS = "https://a.espncdn.com/i/teamlogos/nba/500/{}.png"

NBA_TEAMS: List[str] = [
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
]

# Diccionario de nombres en español para formatear la fecha en la cabecera principal
DIAS_SEMANA_ES: Dict[int, str] = {
    0: "Lunes",
    1: "Martes",
    2: "Miércoles",
    3: "Jueves",
    4: "Viernes",
    5: "Sábado",
    6: "Domingo",
}

MESES_ES: Dict[int, str] = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}

# Mapa estático de ratings base por franquicia para cálculo de respaldo del ESPN BPI Predictor
_TEAM_BASE_NET_RTG: Dict[str, float] = {
    str(r["Team_Abbr"]).upper(): float(r["Off_Rtg"]) - float(r["Def_Rtg"])
    for r in DEFAULT_CSV_DATA
}

# Nombre corto de ciudad/franquicia para etiquetas legibles en el bloque de desglose (ej. 'Boston')
TEAM_SHORT_DISPLAY_NAME: Dict[str, str] = {
    "ATL": "Atlanta",
    "BOS": "Boston",
    "BKN": "Brooklyn",
    "CHA": "Charlotte",
    "CHI": "Chicago",
    "CLE": "Cleveland",
    "DAL": "Dallas",
    "DEN": "Denver",
    "DET": "Detroit",
    "GSW": "Golden State",
    "HOU": "Houston",
    "IND": "Indiana",
    "LAC": "LA Clippers",
    "LAL": "LA Lakers",
    "MEM": "Memphis",
    "MIA": "Miami",
    "MIL": "Milwaukee",
    "MIN": "Minnesota",
    "NOP": "New Orleans",
    "NYK": "New York",
    "OKC": "Oklahoma City",
    "ORL": "Orlando",
    "PHI": "Philadelphia",
    "PHX": "Phoenix",
    "POR": "Portland",
    "SAC": "Sacramento",
    "SAS": "San Antonio",
    "TOR": "Toronto",
    "UTA": "Utah",
    "WAS": "Washington",
}


def formatear_fecha_larga_es(fecha_obj: Optional[date] = None) -> str:
    """
    Convierte un objeto `date` o `datetime` a formato largo en español para la cabecera:
    Ejemplo: `date(2026, 10, 28)` -> `'Miércoles, 28 de Octubre'`
    """
    target = fecha_obj or date.today()
    if isinstance(target, datetime):
        target = target.date()
    dia_nombre = DIAS_SEMANA_ES.get(target.weekday(), "Miércoles")
    mes_nombre = MESES_ES.get(target.month, "Octubre")
    return f"{dia_nombre}, {target.day} de {mes_nombre}"


# Mapeo exhaustivo de códigos cortos de ESPN y nombres completos de The Odds API
# hacia nuestras 30 abreviaturas estándar del motor ('GSW', 'NYK', 'SAS', 'NOP', 'UTA', 'WAS', etc.)
ESPN_TO_NBA_ABBR: Dict[str, str] = {
    # Códigos cortos ESPN
    "GS": "GSW",
    "GSW": "GSW",
    "NY": "NYK",
    "NYK": "NYK",
    "SA": "SAS",
    "SAS": "SAS",
    "NO": "NOP",
    "NOP": "NOP",
    "NOH": "NOP",
    "UTAH": "UTA",
    "UTA": "UTA",
    "WSH": "WAS",
    "WAS": "WAS",
    "PHX": "PHX",
    "PHO": "PHX",
    "BKN": "BKN",
    "BRK": "BKN",
    "CHA": "CHA",
    "CHO": "CHA",
    # Nombres completos de las 30 franquicias (The Odds API / ESPN)
    "ATLANTA HAWKS": "ATL",
    "HAWKS": "ATL",
    "BOSTON CELTICS": "BOS",
    "CELTICS": "BOS",
    "BROOKLYN NETS": "BKN",
    "NETS": "BKN",
    "CHARLOTTE HORNETS": "CHA",
    "HORNETS": "CHA",
    "CHICAGO BULLS": "CHI",
    "BULLS": "CHI",
    "CLEVELAND CAVALIERS": "CLE",
    "CAVALIERS": "CLE",
    "CAVS": "CLE",
    "DALLAS MAVERICKS": "DAL",
    "MAVERICKS": "DAL",
    "MAVS": "DAL",
    "DENVER NUGGETS": "DEN",
    "NUGGETS": "DEN",
    "DETROIT PISTONS": "DET",
    "PISTONS": "DET",
    "GOLDEN STATE WARRIORS": "GSW",
    "WARRIORS": "GSW",
    "HOUSTON ROCKETS": "HOU",
    "ROCKETS": "HOU",
    "INDIANA PACERS": "IND",
    "PACERS": "IND",
    "LOS ANGELES CLIPPERS": "LAC",
    "LA CLIPPERS": "LAC",
    "L.A. CLIPPERS": "LAC",
    "CLIPPERS": "LAC",
    "LOS ANGELES LAKERS": "LAL",
    "LA LAKERS": "LAL",
    "L.A. LAKERS": "LAL",
    "LAKERS": "LAL",
    "MEMPHIS GRIZZLIES": "MEM",
    "GRIZZLIES": "MEM",
    "MIAMI HEAT": "MIA",
    "HEAT": "MIA",
    "MILWAUKEE BUCKS": "MIL",
    "BUCKS": "MIL",
    "MINNESOTA TIMBERWOLVES": "MIN",
    "TIMBERWOLVES": "MIN",
    "WOLVES": "MIN",
    "NEW ORLEANS PELICANS": "NOP",
    "PELICANS": "NOP",
    "NEW YORK KNICKS": "NYK",
    "KNICKS": "NYK",
    "OKLAHOMA CITY THUNDER": "OKC",
    "THUNDER": "OKC",
    "ORLANDO MAGIC": "ORL",
    "MAGIC": "ORL",
    "PHILADELPHIA 76ERS": "PHI",
    "76ERS": "PHI",
    "SIXERS": "PHI",
    "PHOENIX SUNS": "PHX",
    "SUNS": "PHX",
    "PORTLAND TRAIL BLAZERS": "POR",
    "TRAIL BLAZERS": "POR",
    "BLAZERS": "POR",
    "SACRAMENTO KINGS": "SAC",
    "KINGS": "SAC",
    "SAN ANTONIO SPURS": "SAS",
    "SPURS": "SAS",
    "TORONTO RAPTORS": "TOR",
    "RAPTORS": "TOR",
    "UTAH JAZZ": "UTA",
    "JAZZ": "UTA",
    "WASHINGTON WIZARDS": "WAS",
    "WIZARDS": "WAS",
}

NBA_ABBR_TO_ESPN_LOGO: Dict[str, str] = {
    "GSW": "gs",
    "NOP": "no",
    "NYK": "ny",
    "SAS": "sa",
    "UTA": "utah",
    "WAS": "wsh",
}


def normalizar_abbr_nba(team_identifier: str) -> str:
    """
    Traduce cualquier abreviatura de ESPN ('GS', 'NY', 'NO', 'SA', 'UTAH', 'WSH')
    o nombre completo de franquicia de The Odds API ('Boston Celtics', 'Los Angeles Lakers')
    al estándar oficial de 3 letras de nuestro motor (GSW, NYK, SAS, NOP, BOS, etc.).
    """
    raw = str(team_identifier).strip().upper()
    if raw in ESPN_TO_NBA_ABBR:
        return ESPN_TO_NBA_ABBR[raw]
    for key_name, abbr_val in ESPN_TO_NBA_ABBR.items():
        if len(key_name) > 3 and key_name in raw:
            return abbr_val
    return raw


def _normal_cdf_sync(x: float) -> float:
    """Función de distribución acumulada normal estándar."""
    return 0.5 * (1.0 + math.erf(float(x) / math.sqrt(2.0)))


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

    if 1.01 <= val < 25.0:
        return round(val, 2)

    if val > 0:
        return round(1.0 + (val / 100.0), 2)
    return round(1.0 + (100.0 / abs(val)), 2)


def calcular_probabilidades_implicitas_casas(
    cuota_home_dec: Optional[float],
    cuota_away_dec: Optional[float],
    spread_mercado_home: Optional[float] = None,
) -> Tuple[float, float, float, float]:
    """
    Calcula las cuotas decimales de Moneyline (Local y Visita) y las probabilidades implícitas
    de las casas de apuestas (normalizadas sin vig para comparación directa 0-100%, además de
    conservar la cuota decimal real):
      Retorna: (cuota_ml_home_dec, cuota_ml_away_dec, prob_casas_home_pct, prob_casas_away_pct)
    """
    if (
        cuota_home_dec is not None
        and cuota_away_dec is not None
        and float(cuota_home_dec) > 1.01
        and float(cuota_away_dec) > 1.01
    ):
        c_home = round(float(cuota_home_dec), 2)
        c_away = round(float(cuota_away_dec), 2)
        inv_h = 1.0 / c_home
        inv_a = 1.0 / c_away
        overround = inv_h + inv_a
        if overround > 0:
            p_home = (inv_h / overround) * 100.0
            p_away = (inv_a / overround) * 100.0
            return c_home, c_away, round(p_home, 1), round(p_away, 1)

    # Si el feed solo reportó el spread de mercado, derivamos la probabilidad implícita de las casas
    sp_home = float(spread_mercado_home) if spread_mercado_home is not None else -2.5
    p_home_fair = float(np.clip(_normal_cdf_sync(-sp_home / 11.5), 0.05, 0.95))
    p_away_fair = 1.0 - p_home_fair
    vig_factor = 1.022
    c_home = round(max(1.04, 1.0 / min(0.96, p_home_fair * vig_factor)), 2)
    c_away = round(max(1.04, 1.0 / min(0.96, p_away_fair * vig_factor)), 2)
    return c_home, c_away, round(p_home_fair * 100.0, 1), round(p_away_fair * 100.0, 1)


def estimar_espn_bpi_probabilidades(
    away_abbr: str,
    home_abbr: str,
    comp: Optional[Dict[str, Any]] = None,
    spread_mercado_home: Optional[float] = None,
) -> Tuple[float, float]:
    """
    Extrae el Índice Predictor de ESPN (ESPN BPI) desde el bloque del evento de ESPN (`predictor`,
    `probabilities`, `winPercentage` o `situation.lastPlay.probability`).
    Si el endpoint público de Scoreboard no incluye el nodo `predictor` explícito en ese momento,
    calcula el índice predictor BPI institucional combinando el diferencial de Net Rating BPI base
    de las franquicias (+2.7 HFA) con la línea de consenso de ESPN.
    Retorna `(espn_bpi_away_pct, espn_bpi_home_pct)` sumando 100.0%.
    """
    if isinstance(comp, dict):
        # 1. Intentar desde comp['predictor']
        pred = comp.get("predictor")
        if isinstance(pred, dict):
            h_proj = pred.get("homeTeam", {}).get("gameProjection") if isinstance(pred.get("homeTeam"), dict) else None
            a_proj = pred.get("awayTeam", {}).get("gameProjection") if isinstance(pred.get("awayTeam"), dict) else None
            if h_proj is not None:
                try:
                    hp = float(h_proj)
                    if hp <= 1.0:
                        hp *= 100.0
                    hp = float(np.clip(hp, 2.0, 98.0))
                    return round(100.0 - hp, 1), round(hp, 1)
                except (TypeError, ValueError):
                    pass
            if a_proj is not None:
                try:
                    ap = float(a_proj)
                    if ap <= 1.0:
                        ap *= 100.0
                    ap = float(np.clip(ap, 2.0, 98.0))
                    return round(ap, 1), round(100.0 - ap, 1)
                except (TypeError, ValueError):
                    pass

        # 2. Intentar desde situation.lastPlay.probability
        sit_prob = (
            comp.get("situation", {}).get("lastPlay", {}).get("probability", {})
            if isinstance(comp.get("situation"), dict)
            else {}
        )
        if isinstance(sit_prob, dict) and sit_prob.get("homeWinPercentage") is not None:
            try:
                hp = float(sit_prob["homeWinPercentage"])
                if hp <= 1.0:
                    hp *= 100.0
                hp = float(np.clip(hp, 2.0, 98.0))
                return round(100.0 - hp, 1), round(hp, 1)
            except (TypeError, ValueError):
                pass

        # 3. Intentar desde odds[0].homeTeamOdds.winPercentage
        odds_list = comp.get("odds", [])
        if isinstance(odds_list, list) and odds_list and isinstance(odds_list[0], dict):
            hto = odds_list[0].get("homeTeamOdds", {})
            if isinstance(hto, dict) and hto.get("winPercentage") is not None:
                try:
                    hp = float(hto["winPercentage"])
                    if hp <= 1.0:
                        hp *= 100.0
                    hp = float(np.clip(hp, 2.0, 98.0))
                    return round(100.0 - hp, 1), round(hp, 1)
                except (TypeError, ValueError):
                    pass

    # 4. Cálculo analítico BPI (Basketball Power Index) basado en Net Rating institucional + HFA
    away_net = _TEAM_BASE_NET_RTG.get(str(away_abbr).upper(), 0.0)
    home_net = _TEAM_BASE_NET_RTG.get(str(home_abbr).upper(), 0.0)
    bpi_expected_margin_home = (home_net - away_net) * 0.92 + 2.75

    if spread_mercado_home is not None:
        mkt_expected_margin_home = -float(spread_mercado_home)
        bpi_blended_margin_home = 0.68 * bpi_expected_margin_home + 0.32 * mkt_expected_margin_home
    else:
        bpi_blended_margin_home = bpi_expected_margin_home

    home_bpi_prob = float(np.clip(_normal_cdf_sync(bpi_blended_margin_home / 11.6), 0.04, 0.96)) * 100.0
    away_bpi_prob = 100.0 - home_bpi_prob
    return round(away_bpi_prob, 1), round(home_bpi_prob, 1)


def escudo_nba_html(team_abbr: str, size: int = 32) -> str:
    """
    Genera la etiqueta <img> usando el CDN público de ESPN:
    https://a.espncdn.com/i/teamlogos/nba/500/{abbr}.png
    """
    abbr = normalizar_abbr_nba(team_abbr)
    logo_code = NBA_ABBR_TO_ESPN_LOGO.get(abbr, abbr.lower())
    url = f"https://a.espncdn.com/i/teamlogos/nba/500/{logo_code}.png"
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


def _extraer_posesiones_boxscore_competitor(team_entry: Dict[str, Any]) -> Optional[float]:
    """
    Intenta calcular las posesiones reales de un equipo a partir de las estadísticas
    de boxscore incluidas en el bloque `competitors[i].statistics` de ESPN:
        Poss = 0.96 * (FGA - ORB + TOV + 0.44 * FTA)
    """
    stats_list = team_entry.get("statistics", [])
    if not isinstance(stats_list, list) or not stats_list:
        return None

    stat_map: Dict[str, float] = {}
    for st_item in stats_list:
        if not isinstance(st_item, dict):
            continue
        name = str(st_item.get("name", st_item.get("abbreviation", ""))).strip().upper()
        val_raw = st_item.get("displayValue", st_item.get("value"))
        if val_raw is None:
            continue
        if isinstance(val_raw, str) and "-" in val_raw:
            parts = val_raw.split("-")
            if len(parts) == 2:
                try:
                    made = float(parts[0])
                    att = float(parts[1])
                    stat_map[f"{name}_MADE"] = made
                    stat_map[f"{name}_ATT"] = att
                except ValueError:
                    pass
        else:
            try:
                stat_map[name] = float(val_raw)
            except (TypeError, ValueError):
                pass

    fga = stat_map.get("FIELDGOALSATTEMPTED") or stat_map.get("FGA") or stat_map.get("FG_ATT")
    fta = stat_map.get("FREETHROWSATTEMPTED") or stat_map.get("FTA") or stat_map.get("FT_ATT")
    orb = stat_map.get("OFFENSIVEREBOUNDS") or stat_map.get("OREB") or stat_map.get("ORB") or 10.5
    tov = stat_map.get("TURNOVERS") or stat_map.get("TO") or stat_map.get("TOV") or 13.5

    if fga is not None and fta is not None and fga > 40:
        poss = 0.96 * (float(fga) - float(orb) + float(tov) + 0.44 * float(fta))
        if 82.0 <= poss <= 122.0:
            return round(poss, 1)
    return None


def _extraer_odds_desde_evento_espn(
    comp: Dict[str, Any], away_abbr: str, home_abbr: str
) -> Optional[Dict[str, Any]]:
    """
    Extrae las líneas en vivo de Over/Under (`total_mercado`), Spread (`spread_mercado_home`),
    Moneyline (`cuota_ml_home_decimal`, `cuota_ml_away_decimal`), probabilidades implícitas
    de las casas de apuestas y el Índice Predictor ESPN BPI directamente desde `competitions[0]`
    del endpoint público de ESPN Scoreboard, convirtiendo todo momio a formato decimal.
    """
    odds_list = comp.get("odds", [])
    odds_obj = None
    if isinstance(odds_list, list):
        for candidate in odds_list:
            if isinstance(candidate, dict) and (
                candidate.get("overUnder") is not None
                or candidate.get("spread") is not None
                or candidate.get("details")
            ):
                odds_obj = candidate
                break

    espn_bpi_away_pct, espn_bpi_home_pct = estimar_espn_bpi_probabilidades(
        away_abbr=away_abbr,
        home_abbr=home_abbr,
        comp=comp,
        spread_mercado_home=None,
    )

    if odds_obj is None:
        return {
            "matchup_key": f"{away_abbr}@{home_abbr}",
            "away_abbr": away_abbr,
            "home_abbr": home_abbr,
            "total_mercado": None,
            "cuota_over_decimal": 1.91,
            "cuota_under_decimal": 1.91,
            "spread_mercado_home": None,
            "cuota_spread_home_decimal": 1.91,
            "cuota_spread_away_decimal": 1.91,
            "cuota_ml_home_decimal": None,
            "cuota_ml_away_decimal": None,
            "prob_casas_home_pct": None,
            "prob_casas_away_pct": None,
            "espn_bpi_home_pct": espn_bpi_home_pct,
            "espn_bpi_away_pct": espn_bpi_away_pct,
            "bookmaker": "ESPN BPI Feed",
            "fuente": "ESPN Scoreboard Feed",
        }

    total_mercado: Optional[float] = None
    if odds_obj.get("overUnder") is not None:
        try:
            total_mercado = round(float(odds_obj["overUnder"]), 1)
        except (TypeError, ValueError):
            total_mercado = None

    raw_over_odds = odds_obj.get("overOdds")
    raw_under_odds = odds_obj.get("underOdds")
    total_nested = odds_obj.get("total", {}) if isinstance(odds_obj.get("total"), dict) else {}
    if raw_over_odds is None and isinstance(total_nested.get("over"), dict):
        raw_over_odds = total_nested["over"].get("close", {}).get("odds") or total_nested["over"].get("odds")
    if raw_under_odds is None and isinstance(total_nested.get("under"), dict):
        raw_under_odds = total_nested["under"].get("close", {}).get("odds") or total_nested["under"].get("odds")

    cuota_over_decimal = convertir_americano_a_decimal(raw_over_odds, default_decimal=1.91)
    cuota_under_decimal = convertir_americano_a_decimal(raw_under_odds, default_decimal=1.91)

    spread_mercado_home: Optional[float] = None
    details_str = str(odds_obj.get("details", "")).strip().upper()
    if details_str:
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
    ml_nested = odds_obj.get("moneyline", {}) if isinstance(odds_obj.get("moneyline"), dict) else {}

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

    raw_ml_home = (
        home_team_odds.get("moneyLine")
        or home_team_odds.get("odds")
        or (ml_nested.get("home", {}).get("close", {}).get("odds") if isinstance(ml_nested.get("home"), dict) else None)
    )
    raw_ml_away = (
        away_team_odds.get("moneyLine")
        or away_team_odds.get("odds")
        or (ml_nested.get("away", {}).get("close", {}).get("odds") if isinstance(ml_nested.get("away"), dict) else None)
    )

    c_ml_home_raw = convertir_americano_a_decimal(raw_ml_home, default_decimal=0.0) if raw_ml_home is not None else None
    c_ml_away_raw = convertir_americano_a_decimal(raw_ml_away, default_decimal=0.0) if raw_ml_away is not None else None

    cuota_ml_home_dec, cuota_ml_away_dec, prob_casas_home_pct, prob_casas_away_pct = (
        calcular_probabilidades_implicitas_casas(
            cuota_home_dec=c_ml_home_raw,
            cuota_away_dec=c_ml_away_raw,
            spread_mercado_home=spread_mercado_home,
        )
    )

    espn_bpi_away_pct, espn_bpi_home_pct = estimar_espn_bpi_probabilidades(
        away_abbr=away_abbr,
        home_abbr=home_abbr,
        comp=comp,
        spread_mercado_home=spread_mercado_home,
    )

    provider_name = (
        odds_obj.get("provider", {}).get("name", "ESPN Consensus")
        if isinstance(odds_obj.get("provider"), dict)
        else "ESPN Consensus"
    )

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
        "cuota_ml_home_decimal": cuota_ml_home_dec,
        "cuota_ml_away_decimal": cuota_ml_away_dec,
        "prob_casas_home_pct": prob_casas_home_pct,
        "prob_casas_away_pct": prob_casas_away_pct,
        "espn_bpi_home_pct": espn_bpi_home_pct,
        "espn_bpi_away_pct": espn_bpi_away_pct,
        "bookmaker": str(provider_name),
        "fuente": "ESPN Scoreboard Consensus",
    }


def _consultar_espn_scoreboard_raw(fecha_str: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Realiza la petición HTTP al endpoint público de ESPN Scoreboard concatenando `?dates={fecha_str}`.
    Si no se pasa `fecha_str`, usa por defecto la fecha actual del sistema en formato 'YYYYMMDD'.
    """
    target_date_str = str(fecha_str).strip() if fecha_str else datetime.now().strftime("%Y%m%d")
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={target_date_str}"

    try:
        if requests is not None:
            resp = requests.get(url, headers=ESPN_HEADERS, timeout=10)
            resp.raise_for_status()
            return resp.json()
    except Exception:
        pass

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
       - Parámetros: 'regions=us', 'markets=h2h,totals,spreads', 'oddsFormat=decimal'
    2. Módulo Fallback de Respaldo: Extrae las líneas de consenso de Over/Under, Spread,
       Moneyline e Índice Predictor ESPN BPI directamente desde el endpoint público de ESPN
       Scoreboard ('competitions[0].odds') para la fecha solicitada (`?dates={fecha_yyyymmdd}`)
       en formato decimal.
    """
    lineas_por_partido: Dict[str, Dict[str, Any]] = {}
    clean_key = str(api_key).strip() if api_key else ""

    if clean_key and requests is not None:
        params = {
            "apiKey": clean_key,
            "regions": "us",
            "markets": "h2h,totals,spreads",
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
                    cuota_ml_home_dec: Optional[float] = None
                    cuota_ml_away_dec: Optional[float] = None
                    book_title: str = "US Sportsbook"

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

                            elif m_key == "h2h" and cuota_ml_home_dec is None:
                                h_ml_out = None
                                a_ml_out = None
                                for o in outcomes:
                                    o_abbr = normalizar_abbr_nba(str(o.get("name", "")))
                                    if o_abbr == home_abbr:
                                        h_ml_out = o
                                    elif o_abbr == away_abbr:
                                        a_ml_out = o
                                if h_ml_out and a_ml_out:
                                    cuota_ml_home_dec = convertir_americano_a_decimal(h_ml_out.get("price"), 1.91)
                                    cuota_ml_away_dec = convertir_americano_a_decimal(a_ml_out.get("price"), 1.91)

                        if total_mercado is not None and spread_home is not None and cuota_ml_home_dec is not None:
                            break

                    if total_mercado is not None or spread_home is not None or cuota_ml_home_dec is not None:
                        c_ml_h, c_ml_a, p_casas_h, p_casas_a = calcular_probabilidades_implicitas_casas(
                            cuota_home_dec=cuota_ml_home_dec,
                            cuota_away_dec=cuota_ml_away_dec,
                            spread_mercado_home=spread_home,
                        )
                        espn_bpi_a, espn_bpi_h = estimar_espn_bpi_probabilidades(
                            away_abbr=away_abbr,
                            home_abbr=home_abbr,
                            comp=None,
                            spread_mercado_home=spread_home,
                        )
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
                            "cuota_ml_home_decimal": c_ml_h,
                            "cuota_ml_away_decimal": c_ml_a,
                            "prob_casas_home_pct": p_casas_h,
                            "prob_casas_away_pct": p_casas_a,
                            "espn_bpi_home_pct": espn_bpi_h,
                            "espn_bpi_away_pct": espn_bpi_a,
                            "bookmaker": book_title,
                            "fuente": f"The Odds API ({book_title})",
                        }
        except Exception:
            pass

    payload_espn = _consultar_espn_scoreboard_raw(fecha_str=fecha_yyyymmdd)
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
                    existing = lineas_por_partido[matchup_key]
                    if existing.get("total_mercado") is None and espn_odds.get("total_mercado") is not None:
                        existing["total_mercado"] = espn_odds["total_mercado"]
                        existing["cuota_over_decimal"] = espn_odds["cuota_over_decimal"]
                        existing["cuota_under_decimal"] = espn_odds["cuota_under_decimal"]
                    if existing.get("spread_mercado_home") is None and espn_odds.get("spread_mercado_home") is not None:
                        existing["spread_mercado_home"] = espn_odds["spread_mercado_home"]
                        existing["cuota_spread_home_decimal"] = espn_odds["cuota_spread_home_decimal"]
                        existing["cuota_spread_away_decimal"] = espn_odds["cuota_spread_away_decimal"]
                    if existing.get("espn_bpi_home_pct") is None and espn_odds.get("espn_bpi_home_pct") is not None:
                        existing["espn_bpi_home_pct"] = espn_odds["espn_bpi_home_pct"]
                        existing["espn_bpi_away_pct"] = espn_odds["espn_bpi_away_pct"]
            except Exception:
                continue

    return lineas_por_partido


def obtener_calendario_nba(fecha_str: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Consulta el endpoint público de ESPN Scoreboard para una fecha específica en formato 'YYYYMMDD':
        `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={fecha_str}`
    - Si `fecha_str` es None o vacío, utiliza por defecto la fecha actual del sistema (`datetime.now().strftime("%Y%m%d")`).
    - Extrae en vivo las líneas de Over/Under (`total_mercado`), Spread (`spread_mercado_home`),
      probabilidades implícitas de las casas (`prob_casas_home_pct`, `prob_casas_away_pct`) y
      el Índice Predictor de ESPN BPI (`espn_bpi_home_pct`, `espn_bpi_away_pct`).
    - Si el status del partido es 'STATUS_FINAL' o 'Final' (o `state == 'post'`), extrae:
      * 'score_away_real' y 'score_home_real'
      * 'pace_real' (desde estadísticas de boxscore o vía `(puntos_totales) / 2.25`)
      * Marca la bandera `'finalizado': True`.
    """
    target_fecha = str(fecha_str).strip() if fecha_str else datetime.now().strftime("%Y%m%d")
    payload = _consultar_espn_scoreboard_raw(fecha_str=target_fecha)
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
            away_score_raw: Optional[float] = None
            home_score_raw: Optional[float] = None
            away_poss_box: Optional[float] = None
            home_poss_box: Optional[float] = None

            for team_entry in competitors:
                side = str(team_entry.get("homeAway", "")).lower()
                team_obj = team_entry.get("team", {})
                abbr_val = str(team_obj.get("abbreviation", "")).strip().upper()
                disp_name = str(team_obj.get("displayName", team_obj.get("name", abbr_val))).strip()
                score_val = team_entry.get("score")
                parsed_score: Optional[float] = None
                if score_val is not None and str(score_val).strip() != "":
                    try:
                        parsed_score = float(score_val)
                    except (TypeError, ValueError):
                        parsed_score = None

                poss_est = _extraer_posesiones_boxscore_competitor(team_entry)

                if side == "away":
                    away_abbr_raw = abbr_val
                    away_name = disp_name
                    away_score_raw = parsed_score
                    away_poss_box = poss_est
                elif side == "home":
                    home_abbr_raw = abbr_val
                    home_name = disp_name
                    home_score_raw = parsed_score
                    home_poss_box = poss_est

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
            status_name = str(status_type.get("name", "")).strip().upper()
            short_detail = str(status_type.get("shortDetail", "")).strip()
            description = str(status_type.get("description", "Scheduled")).strip()
            state_code = str(status_type.get("state", "pre")).lower()
            completed_flag = bool(status_type.get("completed", False))

            iso_date = str(comp.get("date") or ev.get("date") or "").strip()
            hora_formateada = _formatear_hora_partido(iso_date, short_detail)

            es_final = (
                status_name == "STATUS_FINAL"
                or description.lower().startswith("final")
                or short_detail.lower().startswith("final")
                or state_code == "post"
                or completed_flag
            )

            if state_code == "in" and not es_final:
                estado_partido = f"EN VIVO ({short_detail})" if short_detail else "EN VIVO"
            elif es_final:
                estado_partido = short_detail or "Final"
            else:
                estado_partido = description if description else "Programado"

            score_away_real = float(away_score_raw) if away_score_raw is not None else 0.0
            score_home_real = float(home_score_raw) if home_score_raw is not None else 0.0
            puntos_totales_real = score_away_real + score_home_real

            if away_poss_box is not None and home_poss_box is not None:
                pace_real = round((away_poss_box + home_poss_box) / 2.0, 1)
            elif away_poss_box is not None:
                pace_real = round(away_poss_box, 1)
            elif home_poss_box is not None:
                pace_real = round(home_poss_box, 1)
            elif puntos_totales_real > 0:
                pace_real = round(puntos_totales_real / 2.25, 1)
            else:
                pace_real = 99.0

            espn_odds = _extraer_odds_desde_evento_espn(comp, away_abbr, home_abbr)

            item_cal: Dict[str, Any] = {
                "id_partido": id_partido or f"{away_abbr}_{home_abbr}",
                "fecha_str": target_fecha,
                "nombre": nombre_evento,
                "away_abbr": away_abbr,
                "home_abbr": home_abbr,
                "hora": hora_formateada,
                "estado": estado_partido,
                "status_name": status_name or ("STATUS_FINAL" if es_final else "STATUS_SCHEDULED"),
                "finalizado": bool(es_final and puntos_totales_real > 0),
                "score_away_real": round(score_away_real, 1),
                "score_home_real": round(score_home_real, 1),
                "pace_real": round(pace_real, 1),
            }
            if espn_odds:
                item_cal.update(espn_odds)

            calendario.append(item_cal)
        except Exception:
            continue

    return calendario


# Alias de retrocompatibilidad para llamadas existentes
def obtener_calendario_nba_hoy(fecha_yyyymmdd: Optional[str] = None) -> List[Dict[str, Any]]:
    return obtener_calendario_nba(fecha_str=fecha_yyyymmdd)


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