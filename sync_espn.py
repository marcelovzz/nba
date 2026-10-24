from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import streamlit as st

from engine_nba import (
    DEFAULT_CSV_DATA,
    LINEUP_COLS,
    build_default_lineups_dict,
    round_to_half_point,
)

# ==============================================================================
# ENDPOINTS Y MAPEO OFICIAL DE FRANQUICIAS / LOGOS ESPN CDN
# ==============================================================================
ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
URL_NBA_LOGOS = "https://a.espncdn.com/i/teamlogos/nba/500/{}.png"
NBA_SEASON_TARGET = "2026-27"

NBA_TEAMS: List[str] = [
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
]

# Mapeo de abreviaturas cortas de ESPN API hacia el estándar oficial de 3 letras NBA
ESPN_TO_NBA_ABBR: Dict[str, str] = {
    "GS": "GSW",
    "GSW": "GSW",
    "NY": "NYK",
    "NYK": "NYK",
    "NO": "NOP",
    "NOP": "NOP",
    "SA": "SAS",
    "SAS": "SAS",
    "UTAH": "UTA",
    "UTA": "UTA",
    "WSH": "WAS",
    "WAS": "WAS",
    "PHO": "PHX",
    "PHX": "PHX",
    "BK": "BKN",
    "BKN": "BKN",
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


def normalizar_abbr_nba(team_abbr: str) -> str:
    """Normaliza cualquier abreviatura devuelta por ESPN al código estándar NBA de 3 letras."""
    raw = str(team_abbr).strip().upper()
    return ESPN_TO_NBA_ABBR.get(raw, raw)


def escudo_nba_html(team_abbr: str, size: int = 32) -> str:
    """
    Genera la etiqueta <img> usando el CDN público de ESPN:
    https://a.espncdn.com/i/teamlogos/nba/500/{abbr}.png
    """
    abbr = str(team_abbr).strip().upper()
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


def obtener_calendario_nba_hoy(fecha_yyyymmdd: Optional[str] = None) -> List[Dict[str, str]]:
    """
    Consulta el endpoint público de ESPN Scoreboard:
    https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard

    Extrae y parsea los partidos de la fecha en curso devolviendo una lista de diccionarios:
    [
        {
            'id_partido': str,
            'nombre': str,
            'away_abbr': str,
            'home_abbr': str,
            'hora': str,
            'estado': str
        }
    ]
    """
    url = ESPN_SCOREBOARD_URL
    if fecha_yyyymmdd:
        url = f"{ESPN_SCOREBOARD_URL}?dates={fecha_yyyymmdd}"

    payload: Optional[Dict] = None
    try:
        resp = requests.get(url, headers=ESPN_HEADERS, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        try:
            req = urllib.request.Request(url, headers=ESPN_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return []

    if not isinstance(payload, dict):
        return []

    eventos = payload.get("events", [])
    calendario: List[Dict[str, str]] = []

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

            calendario.append(
                {
                    "id_partido": id_partido or f"{away_abbr}_{home_abbr}",
                    "nombre": nombre_evento,
                    "away_abbr": away_abbr,
                    "home_abbr": home_abbr,
                    "hora": hora_formateada,
                    "estado": estado_partido,
                }
            )
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


@st.cache_data(ttl=43200, show_spinner=False)
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

        st.session_state.df_nba = updated_df
        st.session_state.lineups_nba = updated_lineups
        source_msg = f"NBA.com Live API ({season} Sincronizado)"
        st.session_state.data_source_label = source_msg
        st.session_state.nba_api_status = "ONLINE (NBA.com Live)"
        return updated_df, updated_lineups, source_msg, True

    except Exception as e:
        st.warning("NBA.com no disponible temporalmente. Operando con base de respaldo local.")
        st.session_state.df_nba = base_df
        if "lineups_nba" not in st.session_state:
            st.session_state.lineups_nba = base_lineups
        st.session_state.data_source_label = local_label
        st.session_state.nba_api_status = f"FALLBACK LOCAL ({type(e).__name__})"
        return base_df, st.session_state.lineups_nba, local_label, False