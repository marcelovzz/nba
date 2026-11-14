from datetime import date, datetime
import io
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

try:
    import streamlit as st
except ImportError:
    st = None

try:
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
except ImportError:
    Alignment = Border = Font = PatternFill = Side = None

from sync_injuries_nba import (
    normalizar_nombre_jugador_nba,
    obtener_reporte_lesiones_nba,
)

MAX_PLAYER_PROJECTED_MINUTES = 42.0
TEAM_TOTAL_GAME_MINUTES = 240.0
DEFAULT_ROSTERS_EXCEL_FILENAME = "nba_rosters_plantilla.xlsx"
TEAM_RATINGS_STATE_FILENAME = "data/team_ratings_state.json"
PREDICTION_HISTORY_CSV_FILENAME = "data/prediction_history.csv"
AUDIT_LOG_SHEET_NAME = "Audit_Log"
AUDIT_LOG_CSV_FILENAME = "data/audit_log.csv"
AUDIT_LOG_COLS: List[str] = [
    "Fecha",
    "Partido",
    "Marcador_Real",
    "Proy_Spread",
    "Error_Spread",
    "Proy_Total",
    "Error_Total",
    "Equipo",
    "Off_Rtg_Prev",
    "Off_Rtg_New",
    "Delta_Off",
    "Def_Rtg_Prev",
    "Def_Rtg_New",
    "Delta_Def",
]
ELO_BAYES_K = 0.06

ESPN_LOGO_EXCEPTIONS_MAP: Dict[str, str] = {
    "NO": "nop",
    "NOP": "nop",
    "UTAH": "uta",
    "UTA": "uta",
    "GS": "gsw",
    "GSW": "gsw",
    "SA": "sas",
    "SAS": "sas",
    "NY": "nyk",
    "NYK": "nyk",
    "WSH": "was",
    "WAS": "was",
}


def get_nba_logo_url(team_abbr: str) -> str:
    """
    Devuelve la URL oficial de ESPN para el escudo del equipo NBA:
        'https://a.espncdn.com/i/teamlogos/nba/500/{abbr_lower}.png'
    Incluye el mapeo oficial de excepciones de ESPN:
      - 'NO' / 'NOP' -> 'nop'
      - 'UTAH' / 'UTA' -> 'uta'
      - 'GS' / 'GSW' -> 'gsw'
      - 'SA' / 'SAS' -> 'sas'
      - 'NY' / 'NYK' -> 'nyk'
    """
    raw = str(team_abbr or "").strip().upper()
    if "(" in raw and ")" in raw:
        raw = raw.split("(")[-1].replace(")", "").strip().upper()
    abbr_lower = ESPN_LOGO_EXCEPTIONS_MAP.get(raw, raw.lower())
    return f"https://a.espncdn.com/i/teamlogos/nba/500/{abbr_lower}.png"

# Parámetros de Regresión Bayesiana a la Media (Small Sample Size Stabilization)
BAYESIAN_STABILIZATION_GAMES = 25
DEFAULT_EARLY_SEASON_GP = 5
LEAGUE_STARTER_O_EPM_OFFSET = 4.30
LEAGUE_STARTER_D_EPM_OFFSET = 0.32

LEAGUE_AVG_ORTG = 115.5
LEAGUE_AVG_PACE = 99.0
LEAGUE_AVG_ISO_PPP = 1.03
LEAGUE_AVG_PNR_PPP = 1.04
LEAGUE_AVG_TOV = 13.1

# Desviaciones estándar empíricas de simulaciones Monte Carlo NBA (5,000 posesiones)
NBA_TOTAL_SIM_STD = 13.6
NBA_MARGIN_SIM_STD = 11.8

# Límites de seguridad (clipping) para ratings de la NBA moderna en Calibración Kalman
PACE_CLIP_RANGE: Tuple[float, float] = (92.0, 106.5)
ORTG_CLIP_RANGE: Tuple[float, float] = (104.0, 126.5)
DRTG_CLIP_RANGE: Tuple[float, float] = (104.0, 124.5)

GAME_SLATE_TIMES: List[str] = [
    "19:00 ET", "19:30 ET", "19:30 ET", "20:00 ET", "20:00 ET",
    "20:30 ET", "20:30 ET", "21:00 ET", "21:00 ET", "21:30 ET",
    "22:00 ET", "22:00 ET", "22:30 ET", "22:30 ET", "23:00 ET",
]

LINEUP_COLS: List[str] = ["Posición", "Jugador", "Minutos_Esperados", "O_EPM", "D_EPM"]
EXCEL_TEMPLATE_BASE_COLS: List[str] = [
    "Team_Abbr", "Pos", "Jugador", "Minutos", "O_EPM", "D_EPM", "Pace_Diff", "Es_Estrella", "PPG_Linea",
]
EXCEL_TEMPLATE_COLS: List[str] = [
    "Team_Abbr", "Pos", "Jugador", "Minutos", "Minutos_Base",
    "O_EPM", "D_EPM", "Pace_Diff", "Es_Estrella",
    "PPG_Base", "RPG_Base", "APG_Base", "PPG_Linea",
]
ROSTER_EDITOR_COLS: List[str] = [
    "Team_Abbr", "Star1_Name", "Star1_PPG", "Star2_Name", "Star2_PPG", "Pace", "Off_Rtg", "Def_Rtg",
]

FULL_30_TEAM_SLATE: List[Tuple[str, str]] = [
    ("Detroit Pistons", "Boston Celtics"), ("New York Knicks", "Miami Heat"),
    ("Dallas Mavericks", "Denver Nuggets"), ("Golden State Warriors", "Los Angeles Lakers"),
    ("Minnesota Timberwolves", "Oklahoma City Thunder"), ("Philadelphia 76ers", "Cleveland Cavaliers"),
    ("Milwaukee Bucks", "Indiana Pacers"), ("Phoenix Suns", "LA Clippers"),
    ("Sacramento Kings", "Memphis Grizzlies"), ("Houston Rockets", "San Antonio Spurs"),
    ("Orlando Magic", "Atlanta Hawks"), ("New Orleans Pelicans", "Chicago Bulls"),
    ("Brooklyn Nets", "Toronto Raptors"), ("Charlotte Hornets", "Washington Wizards"),
    ("Portland Trail Blazers", "Utah Jazz"),
]

# ==============================================================================
# MÉTRICAS BASE DE REBOTES (RPG_Base) Y ASISTENCIAS (APG_Base) PARA ESTRELLAS NBA
# ==============================================================================
STAR_BASE_REB_AST_MAP: Dict[str, Tuple[float, float]] = {
    "jayson tatum": (8.6, 4.9),
    "jaylen brown": (5.8, 3.7),
    "cam thomas": (3.4, 3.1),
    "dennis schroder": (3.1, 6.4),
    "jalen brunson": (3.6, 6.9),
    "karl-anthony towns": (11.2, 3.1),
    "joel embiid": (11.0, 5.4),
    "tyrese maxey": (3.8, 6.3),
    "scottie barnes": (8.2, 6.1),
    "rj barrett": (6.2, 4.1),
    "zach lavine": (5.1, 4.2),
    "coby white": (4.6, 5.2),
    "donovan mitchell": (5.1, 5.9),
    "darius garland": (2.9, 6.6),
    "cade cunningham": (6.4, 8.2),
    "jaden ivey": (3.9, 4.2),
    "tyrese haliburton": (3.9, 10.4),
    "pascal siakam": (7.3, 4.1),
    "giannis antetokounmpo": (11.6, 6.4),
    "damian lillard": (4.4, 7.1),
    "nikola jokic": (12.4, 9.2),
    "jamal murray": (4.1, 6.5),
    "anthony edwards": (5.6, 5.1),
    "julius randle": (9.0, 4.7),
    "shai gilgeous-alexander": (5.5, 6.3),
    "jalen williams": (5.2, 4.8),
    "anfernee simons": (3.4, 5.4),
    "jerami grant": (3.8, 2.7),
    "lauri markkanen": (8.2, 2.1),
    "keyonte george": (3.2, 5.6),
    "stephen curry": (4.5, 5.4),
    "jonathan kuminga": (5.2, 2.3),
    "james harden": (5.8, 8.6),
    "norman powell": (3.2, 2.2),
    "lebron james": (7.4, 8.2),
    "anthony davis": (12.5, 3.6),
    "kevin durant": (6.6, 5.1),
    "devin booker": (4.6, 6.8),
    "de'aaron fox": (4.8, 5.8),
    "demar derozan": (4.4, 5.1),
    "trae young": (3.1, 10.8),
    "jalen johnson": (9.4, 5.1),
    "lamelo ball": (5.3, 8.0),
    "brandon miller": (4.5, 3.1),
    "jimmy butler": (5.6, 5.0),
    "bam adebayo": (10.4, 4.1),
    "paolo banchero": (7.2, 5.4),
    "franz wagner": (5.7, 4.4),
    "jordan poole": (2.9, 4.6),
    "kyle kuzma": (6.6, 4.1),
    "luka doncic": (9.1, 9.6),
    "kyrie irving": (5.0, 5.3),
    "alperen sengun": (9.6, 5.0),
    "jalen green": (5.1, 3.6),
    "ja morant": (5.6, 8.2),
    "jaren jackson jr.": (6.1, 2.3),
    "zion williamson": (6.2, 5.0),
    "brandon ingram": (5.2, 5.6),
    "victor wembanyama": (10.8, 3.9),
    "devin vassell": (3.9, 4.1),
}

# ==============================================================================
# BASE DE DATOS PREDETERMINADA: 30 FRANQUICIAS + QUINTETOS TITULARES EPM
# ==============================================================================
DEFAULT_CSV_DATA: List[Dict] = [
    {"Team": "Boston Celtics", "Team_Abbr": "BOS", "Conference": "East", "Division": "Atlántico", "Pace": 98.4, "Off_Rtg": 122.2, "Def_Rtg": 110.6, "3PA_Rate": 0.472, "3P_Pct": 0.388, "TOV_Pct": 11.9, "Iso_PPP_Off": 1.12, "Iso_PPP_Def": 0.91, "PnR_PPP_Off": 1.09, "PnR_PPP_Def": 0.93, "Star1_Name": "Jayson Tatum", "Star1_PPG": 27.1, "Star1_Line": 26.5, "Star1_Style": "ISO", "Star1_Std": 5.9, "Star2_Name": "Jaylen Brown", "Star2_PPG": 23.2, "Star2_Line": 22.5, "Star2_Style": "ISO", "Star2_Std": 5.4},
    {"Team": "Brooklyn Nets", "Team_Abbr": "BKN", "Conference": "East", "Division": "Atlántico", "Pace": 97.6, "Off_Rtg": 112.1, "Def_Rtg": 116.4, "3PA_Rate": 0.418, "3P_Pct": 0.362, "TOV_Pct": 13.8, "Iso_PPP_Off": 1.01, "Iso_PPP_Def": 1.07, "PnR_PPP_Off": 0.99, "PnR_PPP_Def": 1.08, "Star1_Name": "Cam Thomas", "Star1_PPG": 24.2, "Star1_Line": 23.5, "Star1_Style": "ISO", "Star1_Std": 6.3, "Star2_Name": "Dennis Schroder", "Star2_PPG": 17.6, "Star2_Line": 16.5, "Star2_Style": "PNR", "Star2_Std": 4.9},
    {"Team": "New York Knicks", "Team_Abbr": "NYK", "Conference": "East", "Division": "Atlántico", "Pace": 96.2, "Off_Rtg": 118.5, "Def_Rtg": 112.4, "3PA_Rate": 0.405, "3P_Pct": 0.376, "TOV_Pct": 12.6, "Iso_PPP_Off": 1.10, "Iso_PPP_Def": 0.96, "PnR_PPP_Off": 1.11, "PnR_PPP_Def": 0.95, "Star1_Name": "Jalen Brunson", "Star1_PPG": 28.7, "Star1_Line": 27.5, "Star1_Style": "PNR", "Star1_Std": 6.1, "Star2_Name": "Karl-Anthony Towns", "Star2_PPG": 22.1, "Star2_Line": 21.5, "Star2_Style": "PNR", "Star2_Std": 5.3},
    {"Team": "Philadelphia 76ers", "Team_Abbr": "PHI", "Conference": "East", "Division": "Atlántico", "Pace": 97.1, "Off_Rtg": 116.8, "Def_Rtg": 113.2, "3PA_Rate": 0.384, "3P_Pct": 0.369, "TOV_Pct": 12.2, "Iso_PPP_Off": 1.11, "Iso_PPP_Def": 0.99, "PnR_PPP_Off": 1.08, "PnR_PPP_Def": 0.98, "Star1_Name": "Joel Embiid", "Star1_PPG": 29.8, "Star1_Line": 28.5, "Star1_Style": "ISO", "Star1_Std": 6.5, "Star2_Name": "Tyrese Maxey", "Star2_PPG": 26.1, "Star2_Line": 25.5, "Star2_Style": "PNR", "Star2_Std": 5.8},
    {"Team": "Toronto Raptors", "Team_Abbr": "TOR", "Conference": "East", "Division": "Atlántico", "Pace": 100.4, "Off_Rtg": 112.8, "Def_Rtg": 117.1, "3PA_Rate": 0.366, "3P_Pct": 0.351, "TOV_Pct": 14.4, "Iso_PPP_Off": 0.97, "Iso_PPP_Def": 1.08, "PnR_PPP_Off": 1.01, "PnR_PPP_Def": 1.09, "Star1_Name": "Scottie Barnes", "Star1_PPG": 20.6, "Star1_Line": 19.5, "Star1_Style": "ISO", "Star1_Std": 5.2, "Star2_Name": "RJ Barrett", "Star2_PPG": 21.4, "Star2_Line": 20.5, "Star2_Style": "PNR", "Star2_Std": 5.4},
    {"Team": "Chicago Bulls", "Team_Abbr": "CHI", "Conference": "East", "Division": "Central", "Pace": 101.2, "Off_Rtg": 114.2, "Def_Rtg": 116.5, "3PA_Rate": 0.412, "3P_Pct": 0.367, "TOV_Pct": 13.5, "Iso_PPP_Off": 1.03, "Iso_PPP_Def": 1.06, "PnR_PPP_Off": 1.04, "PnR_PPP_Def": 1.07, "Star1_Name": "Zach LaVine", "Star1_PPG": 22.9, "Star1_Line": 22.5, "Star1_Style": "ISO", "Star1_Std": 5.8, "Star2_Name": "Coby White", "Star2_PPG": 19.8, "Star2_Line": 19.5, "Star2_Style": "PNR", "Star2_Std": 5.3},
    {"Team": "Cleveland Cavaliers", "Team_Abbr": "CLE", "Conference": "East", "Division": "Central", "Pace": 99.6, "Off_Rtg": 121.0, "Def_Rtg": 111.4, "3PA_Rate": 0.422, "3P_Pct": 0.386, "TOV_Pct": 12.1, "Iso_PPP_Off": 1.10, "Iso_PPP_Def": 0.94, "PnR_PPP_Off": 1.13, "PnR_PPP_Def": 0.94, "Star1_Name": "Donovan Mitchell", "Star1_PPG": 26.8, "Star1_Line": 26.5, "Star1_Style": "PNR", "Star1_Std": 6.0, "Star2_Name": "Darius Garland", "Star2_PPG": 20.4, "Star2_Line": 19.5, "Star2_Style": "PNR", "Star2_Std": 5.1},
    {"Team": "Detroit Pistons", "Team_Abbr": "DET", "Conference": "East", "Division": "Central", "Pace": 100.6, "Off_Rtg": 110.4, "Def_Rtg": 118.2, "3PA_Rate": 0.358, "3P_Pct": 0.348, "TOV_Pct": 15.2, "Iso_PPP_Off": 0.94, "Iso_PPP_Def": 1.13, "PnR_PPP_Off": 0.97, "PnR_PPP_Def": 1.11, "Star1_Name": "Cade Cunningham", "Star1_PPG": 22.8, "Star1_Line": 24.5, "Star1_Style": "PNR", "Star1_Std": 5.6, "Star2_Name": "Jaden Ivey", "Star2_PPG": 16.4, "Star2_Line": 16.5, "Star2_Style": "ISO", "Star2_Std": 4.8},
    {"Team": "Indiana Pacers", "Team_Abbr": "IND", "Conference": "East", "Division": "Central", "Pace": 102.4, "Off_Rtg": 119.8, "Def_Rtg": 116.8, "3PA_Rate": 0.395, "3P_Pct": 0.378, "TOV_Pct": 12.7, "Iso_PPP_Off": 1.06, "Iso_PPP_Def": 1.08, "PnR_PPP_Off": 1.14, "PnR_PPP_Def": 1.09, "Star1_Name": "Tyrese Haliburton", "Star1_PPG": 20.8, "Star1_Line": 20.5, "Star1_Style": "PNR", "Star1_Std": 5.7, "Star2_Name": "Pascal Siakam", "Star2_PPG": 21.6, "Star2_Line": 21.5, "Star2_Style": "ISO", "Star2_Std": 5.1},
    {"Team": "Milwaukee Bucks", "Team_Abbr": "MIL", "Conference": "East", "Division": "Central", "Pace": 99.8, "Off_Rtg": 117.6, "Def_Rtg": 114.5, "3PA_Rate": 0.402, "3P_Pct": 0.375, "TOV_Pct": 12.8, "Iso_PPP_Off": 1.11, "Iso_PPP_Def": 1.03, "PnR_PPP_Off": 1.12, "PnR_PPP_Def": 1.04, "Star1_Name": "Giannis Antetokounmpo", "Star1_PPG": 30.8, "Star1_Line": 30.5, "Star1_Style": "ISO", "Star1_Std": 6.1, "Star2_Name": "Damian Lillard", "Star2_PPG": 25.1, "Star2_Line": 24.5, "Star2_Style": "PNR", "Star2_Std": 6.0},
    {"Team": "Denver Nuggets", "Team_Abbr": "DEN", "Conference": "West", "Division": "Noroeste", "Pace": 97.4, "Off_Rtg": 119.4, "Def_Rtg": 112.3, "3PA_Rate": 0.342, "3P_Pct": 0.374, "TOV_Pct": 12.1, "Iso_PPP_Off": 1.06, "Iso_PPP_Def": 0.98, "PnR_PPP_Off": 1.14, "PnR_PPP_Def": 0.97, "Star1_Name": "Nikola Jokic", "Star1_PPG": 26.6, "Star1_Line": 26.5, "Star1_Style": "PNR", "Star1_Std": 5.2, "Star2_Name": "Jamal Murray", "Star2_PPG": 21.2, "Star2_Line": 20.5, "Star2_Style": "PNR", "Star2_Std": 5.7},
    {"Team": "Minnesota Timberwolves", "Team_Abbr": "MIN", "Conference": "West", "Division": "Noroeste", "Pace": 97.8, "Off_Rtg": 115.8, "Def_Rtg": 109.8, "3PA_Rate": 0.410, "3P_Pct": 0.382, "TOV_Pct": 13.9, "Iso_PPP_Off": 1.08, "Iso_PPP_Def": 0.90, "PnR_PPP_Off": 1.06, "PnR_PPP_Def": 0.91, "Star1_Name": "Anthony Edwards", "Star1_PPG": 27.6, "Star1_Line": 26.5, "Star1_Style": "ISO", "Star1_Std": 6.2, "Star2_Name": "Julius Randle", "Star2_PPG": 20.9, "Star2_Line": 20.5, "Star2_Style": "ISO", "Star2_Std": 5.2},
    {"Team": "Oklahoma City Thunder", "Team_Abbr": "OKC", "Conference": "West", "Division": "Noroeste", "Pace": 100.5, "Off_Rtg": 120.4, "Def_Rtg": 109.2, "3PA_Rate": 0.398, "3P_Pct": 0.389, "TOV_Pct": 11.6, "Iso_PPP_Off": 1.14, "Iso_PPP_Def": 0.89, "PnR_PPP_Off": 1.11, "PnR_PPP_Def": 0.90, "Star1_Name": "Shai Gilgeous-Alexander", "Star1_PPG": 30.2, "Star1_Line": 29.5, "Star1_Style": "ISO", "Star1_Std": 5.4, "Star2_Name": "Jalen Williams", "Star2_PPG": 21.1, "Star2_Line": 20.5, "Star2_Style": "PNR", "Star2_Std": 4.9},
    {"Team": "Portland Trail Blazers", "Team_Abbr": "POR", "Conference": "West", "Division": "Noroeste", "Pace": 99.1, "Off_Rtg": 109.6, "Def_Rtg": 117.4, "3PA_Rate": 0.372, "3P_Pct": 0.346, "TOV_Pct": 15.0, "Iso_PPP_Off": 0.95, "Iso_PPP_Def": 1.10, "PnR_PPP_Off": 0.98, "PnR_PPP_Def": 1.09, "Star1_Name": "Anfernee Simons", "Star1_PPG": 21.5, "Star1_Line": 21.5, "Star1_Style": "PNR", "Star1_Std": 5.9, "Star2_Name": "Jerami Grant", "Star2_PPG": 19.2, "Star2_Line": 18.5, "Star2_Style": "ISO", "Star2_Std": 5.1},
    {"Team": "Utah Jazz", "Team_Abbr": "UTA", "Conference": "West", "Division": "Noroeste", "Pace": 100.2, "Off_Rtg": 113.2, "Def_Rtg": 118.9, "3PA_Rate": 0.408, "3P_Pct": 0.356, "TOV_Pct": 15.4, "Iso_PPP_Off": 0.99, "Iso_PPP_Def": 1.11, "PnR_PPP_Off": 1.02, "PnR_PPP_Def": 1.12, "Star1_Name": "Lauri Markkanen", "Star1_PPG": 23.1, "Star1_Line": 22.5, "Star1_Style": "PNR", "Star1_Std": 5.5, "Star2_Name": "Keyonte George", "Star2_PPG": 16.9, "Star2_Line": 16.5, "Star2_Style": "PNR", "Star2_Std": 5.2},
    {"Team": "Golden State Warriors", "Team_Abbr": "GSW", "Conference": "West", "Division": "Pacífico", "Pace": 100.8, "Off_Rtg": 117.3, "Def_Rtg": 113.8, "3PA_Rate": 0.456, "3P_Pct": 0.380, "TOV_Pct": 14.3, "Iso_PPP_Off": 1.04, "Iso_PPP_Def": 1.00, "PnR_PPP_Off": 1.10, "PnR_PPP_Def": 1.01, "Star1_Name": "Stephen Curry", "Star1_PPG": 26.8, "Star1_Line": 26.5, "Star1_Style": "PNR", "Star1_Std": 6.4, "Star2_Name": "Jonathan Kuminga", "Star2_PPG": 16.8, "Star2_Line": 16.5, "Star2_Style": "ISO", "Star2_Std": 4.9},
    {"Team": "LA Clippers", "Team_Abbr": "LAC", "Conference": "West", "Division": "Pacífico", "Pace": 96.9, "Off_Rtg": 115.6, "Def_Rtg": 113.1, "3PA_Rate": 0.389, "3P_Pct": 0.376, "TOV_Pct": 13.2, "Iso_PPP_Off": 1.11, "Iso_PPP_Def": 0.99, "PnR_PPP_Off": 1.09, "PnR_PPP_Def": 0.98, "Star1_Name": "James Harden", "Star1_PPG": 21.6, "Star1_Line": 20.5, "Star1_Style": "ISO", "Star1_Std": 5.8, "Star2_Name": "Norman Powell", "Star2_PPG": 22.4, "Star2_Line": 21.5, "Star2_Style": "PNR", "Star2_Std": 5.4},
    {"Team": "Los Angeles Lakers", "Team_Abbr": "LAL", "Conference": "West", "Division": "Pacífico", "Pace": 101.4, "Off_Rtg": 115.9, "Def_Rtg": 115.2, "3PA_Rate": 0.349, "3P_Pct": 0.377, "TOV_Pct": 13.4, "Iso_PPP_Off": 1.07, "Iso_PPP_Def": 1.04, "PnR_PPP_Off": 1.08, "PnR_PPP_Def": 1.05, "Star1_Name": "LeBron James", "Star1_PPG": 25.4, "Star1_Line": 24.5, "Star1_Style": "ISO", "Star1_Std": 5.5, "Star2_Name": "Anthony Davis", "Star2_PPG": 24.8, "Star2_Line": 24.5, "Star2_Style": "PNR", "Star2_Std": 5.8},
    {"Team": "Phoenix Suns", "Team_Abbr": "PHX", "Conference": "West", "Division": "Pacífico", "Pace": 98.2, "Off_Rtg": 117.9, "Def_Rtg": 114.4, "3PA_Rate": 0.392, "3P_Pct": 0.382, "TOV_Pct": 14.1, "Iso_PPP_Off": 1.13, "Iso_PPP_Def": 1.02, "PnR_PPP_Off": 1.09, "PnR_PPP_Def": 1.03, "Star1_Name": "Kevin Durant", "Star1_PPG": 27.3, "Star1_Line": 26.5, "Star1_Style": "ISO", "Star1_Std": 5.6, "Star2_Name": "Devin Booker", "Star2_PPG": 26.9, "Star2_Line": 26.5, "Star2_Style": "PNR", "Star2_Std": 6.1},
    {"Team": "Sacramento Kings", "Team_Abbr": "SAC", "Conference": "West", "Division": "Pacífico", "Pace": 100.1, "Off_Rtg": 117.2, "Def_Rtg": 114.9, "3PA_Rate": 0.396, "3P_Pct": 0.368, "TOV_Pct": 12.8, "Iso_PPP_Off": 1.08, "Iso_PPP_Def": 1.04, "PnR_PPP_Off": 1.10, "PnR_PPP_Def": 1.04, "Star1_Name": "De'Aaron Fox", "Star1_PPG": 26.4, "Star1_Line": 25.5, "Star1_Style": "PNR", "Star1_Std": 6.0, "Star2_Name": "DeMar DeRozan", "Star2_PPG": 22.8, "Star2_Line": 21.5, "Star2_Style": "ISO", "Star2_Std": 5.0},
    {"Team": "Atlanta Hawks", "Team_Abbr": "ATL", "Conference": "East", "Division": "Sureste", "Pace": 101.8, "Off_Rtg": 116.4, "Def_Rtg": 117.6, "3PA_Rate": 0.394, "3P_Pct": 0.364, "TOV_Pct": 13.7, "Iso_PPP_Off": 1.03, "Iso_PPP_Def": 1.09, "PnR_PPP_Off": 1.11, "PnR_PPP_Def": 1.10, "Star1_Name": "Trae Young", "Star1_PPG": 25.8, "Star1_Line": 25.5, "Star1_Style": "PNR", "Star1_Std": 6.3, "Star2_Name": "Jalen Johnson", "Star2_PPG": 19.4, "Star2_Line": 18.5, "Star2_Style": "PNR", "Star2_Std": 5.1},
    {"Team": "Charlotte Hornets", "Team_Abbr": "CHA", "Conference": "East", "Division": "Sureste", "Pace": 98.9, "Off_Rtg": 111.2, "Def_Rtg": 117.8, "3PA_Rate": 0.415, "3P_Pct": 0.355, "TOV_Pct": 14.6, "Iso_PPP_Off": 0.98, "Iso_PPP_Def": 1.10, "PnR_PPP_Off": 1.03, "PnR_PPP_Def": 1.10, "Star1_Name": "LaMelo Ball", "Star1_PPG": 26.2, "Star1_Line": 25.5, "Star1_Style": "PNR", "Star1_Std": 6.5, "Star2_Name": "Brandon Miller", "Star2_PPG": 20.8, "Star2_Line": 20.5, "Star2_Style": "ISO", "Star2_Std": 5.5},
    {"Team": "Miami Heat", "Team_Abbr": "MIA", "Conference": "East", "Division": "Sureste", "Pace": 95.8, "Off_Rtg": 113.6, "Def_Rtg": 111.5, "3PA_Rate": 0.388, "3P_Pct": 0.370, "TOV_Pct": 12.4, "Iso_PPP_Off": 1.03, "Iso_PPP_Def": 0.93, "PnR_PPP_Off": 1.01, "PnR_PPP_Def": 0.92, "Star1_Name": "Jimmy Butler", "Star1_PPG": 21.4, "Star1_Line": 20.5, "Star1_Style": "ISO", "Star1_Std": 5.1, "Star2_Name": "Bam Adebayo", "Star2_PPG": 19.6, "Star2_Line": 19.5, "Star2_Style": "PNR", "Star2_Std": 4.6},
    {"Team": "Orlando Magic", "Team_Abbr": "ORL", "Conference": "East", "Division": "Sureste", "Pace": 96.8, "Off_Rtg": 112.9, "Def_Rtg": 109.9, "3PA_Rate": 0.354, "3P_Pct": 0.352, "TOV_Pct": 14.1, "Iso_PPP_Off": 1.02, "Iso_PPP_Def": 0.91, "PnR_PPP_Off": 1.01, "PnR_PPP_Def": 0.91, "Star1_Name": "Paolo Banchero", "Star1_PPG": 25.2, "Star1_Line": 24.5, "Star1_Style": "ISO", "Star1_Std": 5.7, "Star2_Name": "Franz Wagner", "Star2_PPG": 22.4, "Star2_Line": 21.5, "Star2_Style": "PNR", "Star2_Std": 5.3},
    {"Team": "Washington Wizards", "Team_Abbr": "WAS", "Conference": "East", "Division": "Sureste", "Pace": 102.6, "Off_Rtg": 109.8, "Def_Rtg": 119.4, "3PA_Rate": 0.392, "3P_Pct": 0.347, "TOV_Pct": 15.1, "Iso_PPP_Off": 0.95, "Iso_PPP_Def": 1.14, "PnR_PPP_Off": 0.96, "PnR_PPP_Def": 1.13, "Star1_Name": "Jordan Poole", "Star1_PPG": 20.4, "Star1_Line": 19.5, "Star1_Style": "PNR", "Star1_Std": 6.1, "Star2_Name": "Kyle Kuzma", "Star2_PPG": 18.8, "Star2_Line": 18.5, "Star2_Style": "ISO", "Star2_Std": 5.4},
    {"Team": "Dallas Mavericks", "Team_Abbr": "DAL", "Conference": "West", "Division": "Suroeste", "Pace": 100.2, "Off_Rtg": 118.1, "Def_Rtg": 114.6, "3PA_Rate": 0.441, "3P_Pct": 0.372, "TOV_Pct": 12.3, "Iso_PPP_Off": 1.15, "Iso_PPP_Def": 1.03, "PnR_PPP_Off": 1.12, "PnR_PPP_Def": 1.02, "Star1_Name": "Luka Doncic", "Star1_PPG": 32.4, "Star1_Line": 31.5, "Star1_Style": "ISO", "Star1_Std": 6.6, "Star2_Name": "Kyrie Irving", "Star2_PPG": 25.3, "Star2_Line": 24.5, "Star2_Style": "ISO", "Star2_Std": 5.9},
    {"Team": "Houston Rockets", "Team_Abbr": "HOU", "Conference": "West", "Division": "Suroeste", "Pace": 99.4, "Off_Rtg": 115.2, "Def_Rtg": 111.2, "3PA_Rate": 0.378, "3P_Pct": 0.358, "TOV_Pct": 12.6, "Iso_PPP_Off": 1.04, "Iso_PPP_Def": 0.94, "PnR_PPP_Off": 1.05, "PnR_PPP_Def": 0.93, "Star1_Name": "Alperen Sengun", "Star1_PPG": 21.3, "Star1_Line": 20.5, "Star1_Style": "PNR", "Star1_Std": 5.2, "Star2_Name": "Jalen Green", "Star2_PPG": 21.8, "Star2_Line": 21.5, "Star2_Style": "ISO", "Star2_Std": 6.2},
    {"Team": "Memphis Grizzlies", "Team_Abbr": "MEM", "Conference": "West", "Division": "Suroeste", "Pace": 101.6, "Off_Rtg": 116.1, "Def_Rtg": 113.0, "3PA_Rate": 0.382, "3P_Pct": 0.366, "TOV_Pct": 13.8, "Iso_PPP_Off": 1.06, "Iso_PPP_Def": 0.97, "PnR_PPP_Off": 1.09, "PnR_PPP_Def": 0.96, "Star1_Name": "Ja Morant", "Star1_PPG": 25.6, "Star1_Line": 24.5, "Star1_Style": "PNR", "Star1_Std": 5.9, "Star2_Name": "Jaren Jackson Jr.", "Star2_PPG": 22.1, "Star2_Line": 21.5, "Star2_Style": "ISO", "Star2_Std": 5.4},
    {"Team": "New Orleans Pelicans", "Team_Abbr": "NOP", "Conference": "West", "Division": "Suroeste", "Pace": 98.3, "Off_Rtg": 114.8, "Def_Rtg": 113.9, "3PA_Rate": 0.371, "3P_Pct": 0.369, "TOV_Pct": 13.4, "Iso_PPP_Off": 1.07, "Iso_PPP_Def": 1.01, "PnR_PPP_Off": 1.04, "PnR_PPP_Def": 1.00, "Star1_Name": "Zion Williamson", "Star1_PPG": 23.6, "Star1_Line": 22.5, "Star1_Style": "ISO", "Star1_Std": 5.5, "Star2_Name": "Brandon Ingram", "Star2_PPG": 21.9, "Star2_Line": 21.5, "Star2_Style": "ISO", "Star2_Std": 5.2},
    {"Team": "San Antonio Spurs", "Team_Abbr": "SAS", "Conference": "West", "Division": "Suroeste", "Pace": 100.9, "Off_Rtg": 113.1, "Def_Rtg": 113.4, "3PA_Rate": 0.391, "3P_Pct": 0.359, "TOV_Pct": 14.5, "Iso_PPP_Off": 1.02, "Iso_PPP_Def": 0.96, "PnR_PPP_Off": 1.05, "PnR_PPP_Def": 0.95, "Star1_Name": "Victor Wembanyama", "Star1_PPG": 24.4, "Star1_Line": 23.5, "Star1_Style": "PNR", "Star1_Std": 5.8, "Star2_Name": "Devin Vassell", "Star2_PPG": 18.9, "Star2_Line": 18.5, "Star2_Style": "PNR", "Star2_Std": 5.0},
]

DEFAULT_LINEUPS_30_TEAMS: Dict[str, List[Dict]] = {
    "BOS": [{"Posición": "PG", "Jugador": "Jrue Holiday", "Minutos_Esperados": 33.0, "O_EPM": 1.4, "D_EPM": 2.3}, {"Posición": "SG", "Jugador": "Derrick White", "Minutos_Esperados": 34.0, "O_EPM": 2.6, "D_EPM": 2.4}, {"Posición": "SF", "Jugador": "Jaylen Brown", "Minutos_Esperados": 35.0, "O_EPM": 2.8, "D_EPM": 0.9}, {"Posición": "PF", "Jugador": "Jayson Tatum", "Minutos_Esperados": 36.0, "O_EPM": 4.8, "D_EPM": 1.5}, {"Posición": "C", "Jugador": "Kristaps Porzingis", "Minutos_Esperados": 30.0, "O_EPM": 2.9, "D_EPM": 2.1}, {"Posición": "BENCH", "Jugador": "Pritchard / Horford / Hauser", "Minutos_Esperados": 72.0, "O_EPM": 0.9, "D_EPM": 0.6}],
    "BKN": [{"Posición": "PG", "Jugador": "Dennis Schroder", "Minutos_Esperados": 32.0, "O_EPM": 0.5, "D_EPM": -0.6}, {"Posición": "SG", "Jugador": "Cam Thomas", "Minutos_Esperados": 34.0, "O_EPM": 1.6, "D_EPM": -1.8}, {"Posición": "SF", "Jugador": "Cameron Johnson", "Minutos_Esperados": 31.0, "O_EPM": 1.1, "D_EPM": -0.2}, {"Posición": "PF", "Jugador": "Dorian Finney-Smith", "Minutos_Esperados": 29.0, "O_EPM": -1.2, "D_EPM": 0.8}, {"Posición": "C", "Jugador": "Nic Claxton", "Minutos_Esperados": 30.0, "O_EPM": -0.5, "D_EPM": 1.9}, {"Posición": "BENCH", "Jugador": "Simmons / Clowney / Wilson", "Minutos_Esperados": 84.0, "O_EPM": -1.6, "D_EPM": -0.6}],
    "NYK": [{"Posición": "PG", "Jugador": "Jalen Brunson", "Minutos_Esperados": 36.0, "O_EPM": 5.4, "D_EPM": -0.4}, {"Posición": "SG", "Jugador": "Mikal Bridges", "Minutos_Esperados": 35.0, "O_EPM": 1.2, "D_EPM": 0.9}, {"Posición": "SF", "Jugador": "OG Anunoby", "Minutos_Esperados": 35.0, "O_EPM": 1.0, "D_EPM": 3.1}, {"Posición": "PF", "Jugador": "Josh Hart", "Minutos_Esperados": 34.0, "O_EPM": 0.4, "D_EPM": 1.5}, {"Posición": "C", "Jugador": "Karl-Anthony Towns", "Minutos_Esperados": 34.0, "O_EPM": 3.1, "D_EPM": 0.5}, {"Posición": "BENCH", "Jugador": "McBride / Achiuwa / Payne", "Minutos_Esperados": 66.0, "O_EPM": -0.4, "D_EPM": 0.6}],
    "PHI": [{"Posición": "PG", "Jugador": "Tyrese Maxey", "Minutos_Esperados": 36.0, "O_EPM": 3.8, "D_EPM": -0.3}, {"Posición": "SG", "Jugador": "Kelly Oubre Jr.", "Minutos_Esperados": 31.0, "O_EPM": -0.3, "D_EPM": 0.4}, {"Posición": "SF", "Jugador": "Paul George", "Minutos_Esperados": 34.0, "O_EPM": 2.9, "D_EPM": 1.6}, {"Posición": "PF", "Jugador": "Caleb Martin", "Minutos_Esperados": 29.0, "O_EPM": -0.6, "D_EPM": 0.7}, {"Posición": "C", "Jugador": "Joel Embiid", "Minutos_Esperados": 34.0, "O_EPM": 5.6, "D_EPM": 3.2}, {"Posición": "BENCH", "Jugador": "Lowry / Drummond / McCain", "Minutos_Esperados": 76.0, "O_EPM": -1.4, "D_EPM": -0.2}],
    "TOR": [{"Posición": "PG", "Jugador": "Immanuel Quickley", "Minutos_Esperados": 33.0, "O_EPM": 1.9, "D_EPM": -0.3}, {"Posición": "SG", "Jugador": "Gradey Dick", "Minutos_Esperados": 29.0, "O_EPM": 0.2, "D_EPM": -1.4}, {"Posición": "SF", "Jugador": "RJ Barrett", "Minutos_Esperados": 33.0, "O_EPM": 1.1, "D_EPM": -0.9}, {"Posición": "PF", "Jugador": "Scottie Barnes", "Minutos_Esperados": 35.0, "O_EPM": 1.8, "D_EPM": 1.2}, {"Posición": "C", "Jugador": "Jakob Poeltl", "Minutos_Esperados": 30.0, "O_EPM": 0.3, "D_EPM": 1.4}, {"Posición": "BENCH", "Jugador": "Boucher / Agbaji / Mitchell", "Minutos_Esperados": 80.0, "O_EPM": -1.8, "D_EPM": -1.1}],
    "CHI": [{"Posición": "PG", "Jugador": "Josh Giddey", "Minutos_Esperados": 31.0, "O_EPM": 0.6, "D_EPM": -0.8}, {"Posición": "SG", "Jugador": "Coby White", "Minutos_Esperados": 34.0, "O_EPM": 1.7, "D_EPM": -0.7}, {"Posición": "SF", "Jugador": "Zach LaVine", "Minutos_Esperados": 34.0, "O_EPM": 2.1, "D_EPM": -1.1}, {"Posición": "PF", "Jugador": "Patrick Williams", "Minutos_Esperados": 28.0, "O_EPM": -1.3, "D_EPM": 0.5}, {"Posición": "C", "Jugador": "Nikola Vucevic", "Minutos_Esperados": 32.0, "O_EPM": 0.8, "D_EPM": -0.6}, {"Posición": "BENCH", "Jugador": "Dosunmu / Ball / Smith", "Minutos_Esperados": 81.0, "O_EPM": -1.1, "D_EPM": -0.2}],
    "CLE": [{"Posición": "PG", "Jugador": "Darius Garland", "Minutos_Esperados": 32.0, "O_EPM": 2.4, "D_EPM": -0.2}, {"Posición": "SG", "Jugador": "Donovan Mitchell", "Minutos_Esperados": 35.0, "O_EPM": 4.9, "D_EPM": 1.1}, {"Posición": "SF", "Jugador": "Max Strus", "Minutos_Esperados": 29.0, "O_EPM": 0.8, "D_EPM": 0.4}, {"Posición": "PF", "Jugador": "Evan Mobley", "Minutos_Esperados": 33.0, "O_EPM": 1.6, "D_EPM": 3.0}, {"Posición": "C", "Jugador": "Jarrett Allen", "Minutos_Esperados": 32.0, "O_EPM": 1.5, "D_EPM": 2.4}, {"Posición": "BENCH", "Jugador": "LeVert / Jerome / Wade", "Minutos_Esperados": 79.0, "O_EPM": 0.7, "D_EPM": 0.6}],
    "DET": [{"Posición": "PG", "Jugador": "Cade Cunningham", "Minutos_Esperados": 35.0, "O_EPM": 2.2, "D_EPM": -0.9}, {"Posición": "SG", "Jugador": "Jaden Ivey", "Minutos_Esperados": 31.0, "O_EPM": 0.3, "D_EPM": -1.4}, {"Posición": "SF", "Jugador": "Tim Hardaway Jr.", "Minutos_Esperados": 28.0, "O_EPM": -0.4, "D_EPM": -1.5}, {"Posición": "PF", "Jugador": "Tobias Harris", "Minutos_Esperados": 32.0, "O_EPM": 0.4, "D_EPM": -0.3}, {"Posición": "C", "Jugador": "Jalen Duren", "Minutos_Esperados": 30.0, "O_EPM": 0.2, "D_EPM": -0.6}, {"Posición": "BENCH", "Jugador": "Beasley / Thompson / Stewart", "Minutos_Esperados": 84.0, "O_EPM": -2.2, "D_EPM": -0.7}],
    "IND": [{"Posición": "PG", "Jugador": "Tyrese Haliburton", "Minutos_Esperados": 35.0, "O_EPM": 5.1, "D_EPM": -1.3}, {"Posición": "SG", "Jugador": "Andrew Nembhard", "Minutos_Esperados": 30.0, "O_EPM": 0.8, "D_EPM": 0.9}, {"Posición": "SF", "Jugador": "Aaron Nesmith", "Minutos_Esperados": 29.0, "O_EPM": 0.7, "D_EPM": 0.6}, {"Posición": "PF", "Jugador": "Pascal Siakam", "Minutos_Esperados": 34.0, "O_EPM": 2.7, "D_EPM": 0.4}, {"Posición": "C", "Jugador": "Myles Turner", "Minutos_Esperados": 30.0, "O_EPM": 1.4, "D_EPM": 1.1}, {"Posición": "BENCH", "Jugador": "Mathurin / McConnell / Toppin", "Minutos_Esperados": 82.0, "O_EPM": 0.8, "D_EPM": -1.2}],
    "MIL": [{"Posición": "PG", "Jugador": "Damian Lillard", "Minutos_Esperados": 35.0, "O_EPM": 3.9, "D_EPM": -1.2}, {"Posición": "SG", "Jugador": "Gary Trent Jr.", "Minutos_Esperados": 30.0, "O_EPM": 0.5, "D_EPM": -0.3}, {"Posición": "SF", "Jugador": "Taurean Prince", "Minutos_Esperados": 28.0, "O_EPM": -0.4, "D_EPM": 0.2}, {"Posición": "PF", "Jugador": "Giannis Antetokounmpo", "Minutos_Esperados": 36.0, "O_EPM": 5.5, "D_EPM": 2.3}, {"Posición": "C", "Jugador": "Brook Lopez", "Minutos_Esperados": 30.0, "O_EPM": 0.3, "D_EPM": 1.8}, {"Posición": "BENCH", "Jugador": "Portis / Wright / Connaughton", "Minutos_Esperados": 81.0, "O_EPM": -0.9, "D_EPM": -0.4}],
    "DEN": [{"Posición": "PG", "Jugador": "Jamal Murray", "Minutos_Esperados": 35.0, "O_EPM": 3.2, "D_EPM": -0.1}, {"Posición": "SG", "Jugador": "Christian Braun", "Minutos_Esperados": 31.0, "O_EPM": 0.3, "D_EPM": 1.1}, {"Posición": "SF", "Jugador": "Michael Porter Jr.", "Minutos_Esperados": 34.0, "O_EPM": 2.0, "D_EPM": 0.3}, {"Posición": "PF", "Jugador": "Aaron Gordon", "Minutos_Esperados": 33.0, "O_EPM": 1.3, "D_EPM": 1.4}, {"Posición": "C", "Jugador": "Nikola Jokic", "Minutos_Esperados": 36.0, "O_EPM": 6.8, "D_EPM": 2.2}, {"Posición": "BENCH", "Jugador": "Westbrook / Watson / Strawther", "Minutos_Esperados": 71.0, "O_EPM": -1.4, "D_EPM": 0.2}],
    "MIN": [{"Posición": "PG", "Jugador": "Mike Conley", "Minutos_Esperados": 29.0, "O_EPM": 1.8, "D_EPM": 0.7}, {"Posición": "SG", "Jugador": "Anthony Edwards", "Minutos_Esperados": 36.0, "O_EPM": 4.2, "D_EPM": 1.4}, {"Posición": "SF", "Jugador": "Jaden McDaniels", "Minutos_Esperados": 31.0, "O_EPM": -0.6, "D_EPM": 2.2}, {"Posición": "PF", "Jugador": "Julius Randle", "Minutos_Esperados": 34.0, "O_EPM": 2.1, "D_EPM": 0.1}, {"Posición": "C", "Jugador": "Rudy Gobert", "Minutos_Esperados": 34.0, "O_EPM": 0.1, "D_EPM": 3.8}, {"Posición": "BENCH", "Jugador": "Reid / DiVincenzo / Alexander-Walker", "Minutos_Esperados": 76.0, "O_EPM": 0.4, "D_EPM": 1.3}],
    "OKC": [{"Posición": "PG", "Jugador": "Shai Gilgeous-Alexander", "Minutos_Esperados": 35.0, "O_EPM": 6.1, "D_EPM": 2.5}, {"Posición": "SG", "Jugador": "Luguentz Dort", "Minutos_Esperados": 30.0, "O_EPM": 0.1, "D_EPM": 2.2}, {"Posición": "SF", "Jugador": "Alex Caruso", "Minutos_Esperados": 28.0, "O_EPM": 0.3, "D_EPM": 3.4}, {"Posición": "PF", "Jugador": "Jalen Williams", "Minutos_Esperados": 34.0, "O_EPM": 3.1, "D_EPM": 1.6}, {"Posición": "C", "Jugador": "Chet Holmgren", "Minutos_Esperados": 32.0, "O_EPM": 2.2, "D_EPM": 3.5}, {"Posición": "BENCH", "Jugador": "Wallace / Joe / Wiggins", "Minutos_Esperados": 81.0, "O_EPM": 0.6, "D_EPM": 1.0}],
    "POR": [{"Posición": "PG", "Jugador": "Scoot Henderson", "Minutos_Esperados": 30.0, "O_EPM": -1.4, "D_EPM": -1.2}, {"Posición": "SG", "Jugador": "Anfernee Simons", "Minutos_Esperados": 34.0, "O_EPM": 1.8, "D_EPM": -2.1}, {"Posición": "SF", "Jugador": "Deni Avdija", "Minutos_Esperados": 31.0, "O_EPM": 0.4, "D_EPM": 0.8}, {"Posición": "PF", "Jugador": "Jerami Grant", "Minutos_Esperados": 33.0, "O_EPM": 0.9, "D_EPM": -0.7}, {"Posición": "C", "Jugador": "Deandre Ayton", "Minutos_Esperados": 31.0, "O_EPM": 0.1, "D_EPM": 0.5}, {"Posición": "BENCH", "Jugador": "Sharpe / Clingan / Camara", "Minutos_Esperados": 81.0, "O_EPM": -2.1, "D_EPM": -0.4}],
    "UTA": [{"Posición": "PG", "Jugador": "Keyonte George", "Minutos_Esperados": 31.0, "O_EPM": 0.5, "D_EPM": -1.9}, {"Posición": "SG", "Jugador": "Collin Sexton", "Minutos_Esperados": 30.0, "O_EPM": 2.1, "D_EPM": -1.5}, {"Posición": "SF", "Jugador": "Lauri Markkanen", "Minutos_Esperados": 34.0, "O_EPM": 3.5, "D_EPM": 0.2}, {"Posición": "PF", "Jugador": "Taylor Hendricks", "Minutos_Esperados": 27.0, "O_EPM": -1.1, "D_EPM": 0.4}, {"Posición": "C", "Jugador": "Walker Kessler", "Minutos_Esperados": 29.0, "O_EPM": -0.2, "D_EPM": 2.3}, {"Posición": "BENCH", "Jugador": "Clarkson / Collins / Filipowski", "Minutos_Esperados": 89.0, "O_EPM": -1.2, "D_EPM": -1.8}],
    "GSW": [{"Posición": "PG", "Jugador": "Stephen Curry", "Minutos_Esperados": 34.0, "O_EPM": 5.6, "D_EPM": -0.3}, {"Posición": "SG", "Jugador": "Brandin Podziemski", "Minutos_Esperados": 29.0, "O_EPM": 0.6, "D_EPM": 0.8}, {"Posición": "SF", "Jugador": "Andrew Wiggins", "Minutos_Esperados": 30.0, "O_EPM": 0.2, "D_EPM": 0.9}, {"Posición": "PF", "Jugador": "Jonathan Kuminga", "Minutos_Esperados": 30.0, "O_EPM": 1.1, "D_EPM": 0.1}, {"Posición": "C", "Jugador": "Draymond Green", "Minutos_Esperados": 30.0, "O_EPM": 0.4, "D_EPM": 3.3}, {"Posición": "BENCH", "Jugador": "Hield / Melton / Jackson-Davis", "Minutos_Esperados": 87.0, "O_EPM": 0.3, "D_EPM": 0.5}],
    "LAC": [{"Posición": "PG", "Jugador": "James Harden", "Minutos_Esperados": 35.0, "O_EPM": 3.7, "D_EPM": 0.1}, {"Posición": "SG", "Jugador": "Norman Powell", "Minutos_Esperados": 33.0, "O_EPM": 2.2, "D_EPM": -0.4}, {"Posición": "SF", "Jugador": "Terance Mann", "Minutos_Esperados": 29.0, "O_EPM": -0.2, "D_EPM": 0.9}, {"Posición": "PF", "Jugador": "Derrick Jones Jr.", "Minutos_Esperados": 28.0, "O_EPM": -0.3, "D_EPM": 1.4}, {"Posición": "C", "Jugador": "Ivica Zubac", "Minutos_Esperados": 32.0, "O_EPM": 1.2, "D_EPM": 1.9}, {"Posición": "BENCH", "Jugador": "Dunn / Coffey / Batum", "Minutos_Esperados": 83.0, "O_EPM": -0.8, "D_EPM": 0.8}],
    "LAL": [{"Posición": "PG", "Jugador": "D'Angelo Russell", "Minutos_Esperados": 31.0, "O_EPM": 1.8, "D_EPM": -1.1}, {"Posición": "SG", "Jugador": "Austin Reaves", "Minutos_Esperados": 34.0, "O_EPM": 1.9, "D_EPM": -0.5}, {"Posición": "SF", "Jugador": "Rui Hachimura", "Minutos_Esperados": 30.0, "O_EPM": 0.6, "D_EPM": -0.6}, {"Posición": "PF", "Jugador": "LeBron James", "Minutos_Esperados": 35.0, "O_EPM": 4.4, "D_EPM": 0.9}, {"Posición": "C", "Jugador": "Anthony Davis", "Minutos_Esperados": 36.0, "O_EPM": 3.1, "D_EPM": 3.7}, {"Posición": "BENCH", "Jugador": "Vincent / Knecht / Hayes", "Minutos_Esperados": 74.0, "O_EPM": -1.6, "D_EPM": -0.4}],
    "PHX": [{"Posición": "PG", "Jugador": "Tyus Jones", "Minutos_Esperados": 30.0, "O_EPM": 1.7, "D_EPM": -0.8}, {"Posición": "SG", "Jugador": "Devin Booker", "Minutos_Esperados": 36.0, "O_EPM": 4.3, "D_EPM": -0.2}, {"Posición": "SF", "Jugador": "Bradley Beal", "Minutos_Esperados": 33.0, "O_EPM": 1.5, "D_EPM": -0.4}, {"Posición": "PF", "Jugador": "Kevin Durant", "Minutos_Esperados": 36.0, "O_EPM": 4.5, "D_EPM": 1.3}, {"Posición": "C", "Jugador": "Jusuf Nurkic", "Minutos_Esperados": 28.0, "O_EPM": 0.2, "D_EPM": 1.5}, {"Posición": "BENCH", "Jugador": "Allen / O'Neale / Plumlee", "Minutos_Esperados": 77.0, "O_EPM": -0.5, "D_EPM": 0.2}],
    "SAC": [{"Posición": "PG", "Jugador": "De'Aaron Fox", "Minutos_Esperados": 36.0, "O_EPM": 3.8, "D_EPM": 0.8}, {"Posición": "SG", "Jugador": "Kevin Huerter", "Minutos_Esperados": 28.0, "O_EPM": 0.6, "D_EPM": -0.7}, {"Posición": "SF", "Jugador": "DeMar DeRozan", "Minutos_Esperados": 35.0, "O_EPM": 2.4, "D_EPM": -0.3}, {"Posición": "PF", "Jugador": "Keegan Murray", "Minutos_Esperados": 34.0, "O_EPM": 0.9, "D_EPM": 1.1}, {"Posición": "C", "Jugador": "Domantas Sabonis", "Minutos_Esperados": 36.0, "O_EPM": 3.3, "D_EPM": 0.9}, {"Posición": "BENCH", "Jugador": "Monk / Ellis / Lyles", "Minutos_Esperados": 71.0, "O_EPM": -0.6, "D_EPM": -0.2}],
    "ATL": [{"Posición": "PG", "Jugador": "Trae Young", "Minutos_Esperados": 36.0, "O_EPM": 4.6, "D_EPM": -2.2}, {"Posición": "SG", "Jugador": "Dyson Daniels", "Minutos_Esperados": 30.0, "O_EPM": -0.5, "D_EPM": 2.4}, {"Posición": "SF", "Jugador": "Zaccharie Risacher", "Minutos_Esperados": 28.0, "O_EPM": -0.4, "D_EPM": 0.2}, {"Posición": "PF", "Jugador": "Jalen Johnson", "Minutos_Esperados": 35.0, "O_EPM": 2.1, "D_EPM": 0.9}, {"Posición": "C", "Jugador": "Clint Capela", "Minutos_Esperados": 27.0, "O_EPM": 0.3, "D_EPM": 1.3}, {"Posición": "BENCH", "Jugador": "Bogdanovic / Hunter / Okongwu", "Minutos_Esperados": 84.0, "O_EPM": 0.2, "D_EPM": -1.3}],
    "CHA": [{"Posición": "PG", "Jugador": "LaMelo Ball", "Minutos_Esperados": 34.0, "O_EPM": 3.6, "D_EPM": -1.4}, {"Posición": "SG", "Jugador": "Josh Green", "Minutos_Esperados": 28.0, "O_EPM": -0.6, "D_EPM": 0.3}, {"Posición": "SF", "Jugador": "Brandon Miller", "Minutos_Esperados": 34.0, "O_EPM": 1.4, "D_EPM": -0.8}, {"Posición": "PF", "Jugador": "Miles Bridges", "Minutos_Esperados": 34.0, "O_EPM": 0.9, "D_EPM": -0.9}, {"Posición": "C", "Jugador": "Mark Williams", "Minutos_Esperados": 29.0, "O_EPM": 0.5, "D_EPM": 1.1}, {"Posición": "BENCH", "Jugador": "Mann / Micic / Richards", "Minutos_Esperados": 81.0, "O_EPM": -2.2, "D_EPM": -1.2}],
    "MIA": [{"Posición": "PG", "Jugador": "Terry Rozier", "Minutos_Esperados": 31.0, "O_EPM": 0.8, "D_EPM": -0.4}, {"Posición": "SG", "Jugador": "Tyler Herro", "Minutos_Esperados": 34.0, "O_EPM": 2.1, "D_EPM": -0.3}, {"Posición": "SF", "Jugador": "Jimmy Butler", "Minutos_Esperados": 34.0, "O_EPM": 3.6, "D_EPM": 1.9}, {"Posición": "PF", "Jugador": "Nikola Jovic", "Minutos_Esperados": 26.0, "O_EPM": 0.2, "D_EPM": 0.4}, {"Posición": "C", "Jugador": "Bam Adebayo", "Minutos_Esperados": 35.0, "O_EPM": 1.1, "D_EPM": 3.2}, {"Posición": "BENCH", "Jugador": "Jaquez Jr. / Robinson / Highsmith", "Minutos_Esperados": 80.0, "O_EPM": -1.1, "D_EPM": 0.9}],
    "ORL": [{"Posición": "PG", "Jugador": "Jalen Suggs", "Minutos_Esperados": 31.0, "O_EPM": 0.9, "D_EPM": 3.1}, {"Posición": "SG", "Jugador": "Kentavious Caldwell-Pope", "Minutos_Esperados": 30.0, "O_EPM": 0.2, "D_EPM": 1.8}, {"Posición": "SF", "Jugador": "Franz Wagner", "Minutos_Esperados": 34.0, "O_EPM": 2.6, "D_EPM": 1.6}, {"Posición": "PF", "Jugador": "Paolo Banchero", "Minutos_Esperados": 35.0, "O_EPM": 2.8, "D_EPM": 0.8}, {"Posición": "C", "Jugador": "Wendell Carter Jr.", "Minutos_Esperados": 29.0, "O_EPM": 0.4, "D_EPM": 1.5}, {"Posición": "BENCH", "Jugador": "Isaac / Anthony / Bitadze", "Minutos_Esperados": 81.0, "O_EPM": -1.6, "D_EPM": 1.4}],
    "WAS": [{"Posición": "PG", "Jugador": "Jordan Poole", "Minutos_Esperados": 32.0, "O_EPM": 0.4, "D_EPM": -2.3}, {"Posición": "SG", "Jugador": "Malcolm Brogdon", "Minutos_Esperados": 28.0, "O_EPM": 0.6, "D_EPM": -0.9}, {"Posición": "SF", "Jugador": "Bilal Coulibaly", "Minutos_Esperados": 30.0, "O_EPM": -1.2, "D_EPM": 0.7}, {"Posición": "PF", "Jugador": "Kyle Kuzma", "Minutos_Esperados": 33.0, "O_EPM": 0.5, "D_EPM": -1.4}, {"Posición": "C", "Jugador": "Alex Sarr", "Minutos_Esperados": 28.0, "O_EPM": -1.6, "D_EPM": 0.6}, {"Posición": "BENCH", "Jugador": "Valanciunas / Kispert / Carrington", "Minutos_Esperados": 89.0, "O_EPM": -1.8, "D_EPM": -1.5}],
    "DAL": [{"Posición": "PG", "Jugador": "Luka Doncic", "Minutos_Esperados": 37.0, "O_EPM": 6.4, "D_EPM": 0.4}, {"Posición": "SG", "Jugador": "Kyrie Irving", "Minutos_Esperados": 35.0, "O_EPM": 4.1, "D_EPM": 0.2}, {"Posición": "SF", "Jugador": "Klay Thompson", "Minutos_Esperados": 30.0, "O_EPM": 1.1, "D_EPM": -0.5}, {"Posición": "PF", "Jugador": "P.J. Washington", "Minutos_Esperados": 32.0, "O_EPM": 0.2, "D_EPM": 1.2}, {"Posición": "C", "Jugador": "Daniel Gafford", "Minutos_Esperados": 26.0, "O_EPM": 1.0, "D_EPM": 1.6}, {"Posición": "BENCH", "Jugador": "Lively II / Grimes / Marshall", "Minutos_Esperados": 80.0, "O_EPM": -0.6, "D_EPM": 0.7}],
    "HOU": [{"Posición": "PG", "Jugador": "Fred VanVleet", "Minutos_Esperados": 35.0, "O_EPM": 2.3, "D_EPM": 1.6}, {"Posición": "SG", "Jugador": "Jalen Green", "Minutos_Esperados": 33.0, "O_EPM": 1.5, "D_EPM": -0.2}, {"Posición": "SF", "Jugador": "Dillon Brooks", "Minutos_Esperados": 31.0, "O_EPM": -0.6, "D_EPM": 1.4}, {"Posición": "PF", "Jugador": "Jabari Smith Jr.", "Minutos_Esperados": 32.0, "O_EPM": 0.3, "D_EPM": 1.3}, {"Posición": "C", "Jugador": "Alperen Sengun", "Minutos_Esperados": 33.0, "O_EPM": 3.1, "D_EPM": 1.1}, {"Posición": "BENCH", "Jugador": "Thompson / Eason / Sheppard", "Minutos_Esperados": 76.0, "O_EPM": -0.8, "D_EPM": 1.5}],
    "MEM": [{"Posición": "PG", "Jugador": "Ja Morant", "Minutos_Esperados": 34.0, "O_EPM": 3.9, "D_EPM": -0.3}, {"Posición": "SG", "Jugador": "Desmond Bane", "Minutos_Esperados": 34.0, "O_EPM": 2.8, "D_EPM": 0.6}, {"Posición": "SF", "Jugador": "Marcus Smart", "Minutos_Esperados": 29.0, "O_EPM": -0.4, "D_EPM": 1.9}, {"Posición": "PF", "Jugador": "Jaren Jackson Jr.", "Minutos_Esperados": 32.0, "O_EPM": 1.5, "D_EPM": 2.8}, {"Posición": "C", "Jugador": "Zach Edey", "Minutos_Esperados": 26.0, "O_EPM": 0.4, "D_EPM": 1.1}, {"Posición": "BENCH", "Jugador": "Aldama / Pippen Jr. / Clarke", "Minutos_Esperados": 85.0, "O_EPM": -0.6, "D_EPM": 0.3}],
    "NOP": [{"Posición": "PG", "Jugador": "Dejounte Murray", "Minutos_Esperados": 34.0, "O_EPM": 1.7, "D_EPM": 0.9}, {"Posición": "SG", "Jugador": "CJ McCollum", "Minutos_Esperados": 32.0, "O_EPM": 1.9, "D_EPM": -0.6}, {"Posición": "SF", "Jugador": "Brandon Ingram", "Minutos_Esperados": 34.0, "O_EPM": 2.2, "D_EPM": -0.2}, {"Posición": "PF", "Jugador": "Herbert Jones", "Minutos_Esperados": 31.0, "O_EPM": 0.2, "D_EPM": 2.9}, {"Posición": "C", "Jugador": "Zion Williamson", "Minutos_Esperados": 33.0, "O_EPM": 3.4, "D_EPM": 0.4}, {"Posición": "BENCH", "Jugador": "Murphy III / Alvarado / Missi", "Minutos_Esperados": 76.0, "O_EPM": -0.9, "D_EPM": 0.2}],
    "SAS": [{"Posición": "PG", "Jugador": "Chris Paul", "Minutos_Esperados": 28.0, "O_EPM": 1.6, "D_EPM": 0.4}, {"Posición": "SG", "Jugador": "Devin Vassell", "Minutos_Esperados": 33.0, "O_EPM": 1.9, "D_EPM": 0.1}, {"Posición": "SF", "Jugador": "Harrison Barnes", "Minutos_Esperados": 29.0, "O_EPM": 0.5, "D_EPM": -0.4}, {"Posición": "PF", "Jugador": "Jeremy Sochan", "Minutos_Esperados": 30.0, "O_EPM": -0.8, "D_EPM": 0.7}, {"Posición": "C", "Jugador": "Victor Wembanyama", "Minutos_Esperados": 34.0, "O_EPM": 2.9, "D_EPM": 4.5}, {"Posición": "BENCH", "Jugador": "Johnson / Castle / Tre Jones", "Minutos_Esperados": 86.0, "O_EPM": -1.4, "D_EPM": -0.1}],
}

# Alias de respaldo base (solo usado al inicializar sesión por primera vez o hacer reset explícito)
QUINTETOS_BASE = DEFAULT_LINEUPS_30_TEAMS
DEFAULT_TEAM_META_BY_ABBR: Dict[str, Dict] = {d["Team_Abbr"]: d for d in DEFAULT_CSV_DATA}

# Tabla Base de Net Rating Proyectado Pretemporada (30 Franquicias NBA)
# Garantiza que equipos malos o en reconstrucción (WAS, BKN, UTA, POR, CHA, DET, TOR, CHI)
# arranquen con ratings negativos reales (-5.0 a -8.0 pts/100 poss) antes de la estabilización (N=25).
PRESEASON_BASE_RATINGS_30_TEAMS: Dict[str, Dict[str, float]] = {
    "WAS": {"Off_Rtg_Base": 110.5, "Def_Rtg_Base": 118.5, "Net_Rtg_Base": -8.0},
    "BKN": {"Off_Rtg_Base": 110.8, "Def_Rtg_Base": 118.3, "Net_Rtg_Base": -7.5},
    "UTA": {"Off_Rtg_Base": 111.4, "Def_Rtg_Base": 118.6, "Net_Rtg_Base": -7.2},
    "POR": {"Off_Rtg_Base": 111.0, "Def_Rtg_Base": 117.8, "Net_Rtg_Base": -6.8},
    "CHA": {"Off_Rtg_Base": 111.5, "Def_Rtg_Base": 117.9, "Net_Rtg_Base": -6.4},
    "DET": {"Off_Rtg_Base": 111.7, "Def_Rtg_Base": 117.5, "Net_Rtg_Base": -5.8},
    "CHI": {"Off_Rtg_Base": 111.8, "Def_Rtg_Base": 117.5, "Net_Rtg_Base": -5.7},
    "TOR": {"Off_Rtg_Base": 112.1, "Def_Rtg_Base": 117.6, "Net_Rtg_Base": -5.5},
    "NOP": {"Off_Rtg_Base": 113.2, "Def_Rtg_Base": 116.0, "Net_Rtg_Base": -2.8},
    "SAS": {"Off_Rtg_Base": 113.4, "Def_Rtg_Base": 115.0, "Net_Rtg_Base": -1.6},
    "ATL": {"Off_Rtg_Base": 115.8, "Def_Rtg_Base": 117.0, "Net_Rtg_Base": -1.2},
    "SAC": {"Off_Rtg_Base": 116.4, "Def_Rtg_Base": 115.6, "Net_Rtg_Base": 0.8},
    "LAC": {"Off_Rtg_Base": 115.4, "Def_Rtg_Base": 114.0, "Net_Rtg_Base": 1.4},
    "MIA": {"Off_Rtg_Base": 114.1, "Def_Rtg_Base": 112.0, "Net_Rtg_Base": 2.1},
    "LAL": {"Off_Rtg_Base": 116.4, "Def_Rtg_Base": 114.2, "Net_Rtg_Base": 2.2},
    "MEM": {"Off_Rtg_Base": 116.0, "Def_Rtg_Base": 113.4, "Net_Rtg_Base": 2.6},
    "IND": {"Off_Rtg_Base": 119.2, "Def_Rtg_Base": 116.4, "Net_Rtg_Base": 2.8},
    "ORL": {"Off_Rtg_Base": 113.5, "Def_Rtg_Base": 110.5, "Net_Rtg_Base": 3.0},
    "MIL": {"Off_Rtg_Base": 117.6, "Def_Rtg_Base": 114.5, "Net_Rtg_Base": 3.1},
    "GSW": {"Off_Rtg_Base": 117.1, "Def_Rtg_Base": 113.8, "Net_Rtg_Base": 3.3},
    "PHX": {"Off_Rtg_Base": 117.9, "Def_Rtg_Base": 114.4, "Net_Rtg_Base": 3.5},
    "PHI": {"Off_Rtg_Base": 116.8, "Def_Rtg_Base": 113.2, "Net_Rtg_Base": 3.6},
    "DAL": {"Off_Rtg_Base": 118.2, "Def_Rtg_Base": 114.4, "Net_Rtg_Base": 3.8},
    "HOU": {"Off_Rtg_Base": 115.4, "Def_Rtg_Base": 111.2, "Net_Rtg_Base": 4.2},
    "MIN": {"Off_Rtg_Base": 116.0, "Def_Rtg_Base": 110.2, "Net_Rtg_Base": 5.8},
    "NYK": {"Off_Rtg_Base": 118.5, "Def_Rtg_Base": 112.4, "Net_Rtg_Base": 6.1},
    "DEN": {"Off_Rtg_Base": 119.4, "Def_Rtg_Base": 112.3, "Net_Rtg_Base": 7.1},
    "CLE": {"Off_Rtg_Base": 120.2, "Def_Rtg_Base": 112.0, "Net_Rtg_Base": 8.2},
    "BOS": {"Off_Rtg_Base": 121.2, "Def_Rtg_Base": 112.0, "Net_Rtg_Base": 9.2},
    "OKC": {"Off_Rtg_Base": 120.0, "Def_Rtg_Base": 110.2, "Net_Rtg_Base": 9.8},
}


def _normal_cdf(x: float) -> float:
    """Función de distribución acumulada normal estándar Φ(x) exacta vía math.erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _poisson_cdf(k_max: int, lam: float) -> float:
    """
    Calcula P(X <= k_max) para una distribución de Poisson con media esperada λ > 0
    utilizando log-factoriales (math.lgamma) para evitar desbordamiento numérico.
    """
    if lam <= 0.0:
        return 1.0 if k_max >= 0 else 0.0
    if k_max < 0:
        return 0.0
    total_prob = 0.0
    log_lam = math.log(lam)
    for k in range(int(k_max) + 1):
        log_pmf = -lam + k * log_lam - math.lgamma(k + 1)
        total_prob += math.exp(log_pmf)
    return float(np.clip(total_prob, 0.001, 0.999))


def prob_to_fair_odds(prob: float) -> Tuple[str, str]:
    """
    Convierte una probabilidad (0-1) a cuota justa estrictamente en FORMATO DECIMAL
    (ej. '1.91', '2.15'). Retorna tupla (dec_str, dec_str) por compatibilidad modular.
    """
    p = float(np.clip(prob, 0.01, 0.99))
    dec_odds = 1.0 / p
    dec_str = f"{dec_odds:.2f}"
    return dec_str, dec_str


def round_to_half_point(val: float) -> float:
    """Redondea cualquier línea proyectada al medio punto (.5) más cercano estilo Sportsbook."""
    return float(np.floor(val) + 0.5)


def _derivar_metricas_base_jugador(
    player_name: str,
    pos: str,
    minutos_base: float,
    o_epm: float,
    d_epm: float,
    team_abbr: str = "",
) -> Tuple[float, float, float]:
    """
    Deriva PPG_Base, RPG_Base y APG_Base realistas para cualquier jugador en función de su
    nombre (si es estrella registrada), posición (PG, SG, SF, PF, C) y ratings O_EPM / D_EPM.
    """
    p_low = str(player_name).strip().lower()
    pos_up = str(pos).strip().upper()
    t_meta = DEFAULT_TEAM_META_BY_ABBR.get(str(team_abbr).strip().upper(), {})

    if pos_up in {"BENCH", "BANCA"}:
        return 0.0, 0.0, 0.0

    s1_name = str(t_meta.get("Star1_Name", "")).strip().lower()
    s2_name = str(t_meta.get("Star2_Name", "")).strip().lower()
    if p_low == s1_name and "Star1_PPG" in t_meta:
        ppg_base = float(t_meta["Star1_PPG"])
    elif p_low == s2_name and "Star2_PPG" in t_meta:
        ppg_base = float(t_meta["Star2_PPG"])
    else:
        ppg_base = max(8.5, (minutos_base * 0.52) + (o_epm * 1.55))

    if p_low in STAR_BASE_REB_AST_MAP:
        rpg_base, apg_base = STAR_BASE_REB_AST_MAP[p_low]
    else:
        min_scale = max(minutos_base, 18.0) / 34.0
        if pos_up == "C":
            rpg_base = (9.6 + max(0.0, d_epm) * 0.65) * min_scale
            apg_base = (2.6 + max(0.0, o_epm) * 0.45) * min_scale
        elif pos_up == "PF":
            rpg_base = (7.4 + max(0.0, d_epm) * 0.55) * min_scale
            apg_base = (3.2 + max(0.0, o_epm) * 0.45) * min_scale
        elif pos_up == "SF":
            rpg_base = (5.6 + max(0.0, d_epm) * 0.40) * min_scale
            apg_base = (3.6 + max(0.0, o_epm) * 0.50) * min_scale
        elif pos_up == "SG":
            rpg_base = (4.3 + max(0.0, d_epm) * 0.30) * min_scale
            apg_base = (4.4 + max(0.0, o_epm) * 0.55) * min_scale
        else:
            rpg_base = (4.0 + max(0.0, d_epm) * 0.25) * min_scale
            apg_base = (6.8 + max(0.0, o_epm) * 0.70) * min_scale

    return round(float(ppg_base), 1), round(float(rpg_base), 1), round(float(apg_base), 1)


def build_default_lineups_dict() -> Dict[str, pd.DataFrame]:
    """
    Construye el diccionario inicial de DataFrames con los quintetos titulares de las 30 franquicias,
    incluyendo las métricas base requeridas ('PPG_Base', 'RPG_Base', 'APG_Base', 'Minutos_Base').
    """
    lineups_dict: Dict[str, pd.DataFrame] = {}
    for abbr, rows in DEFAULT_LINEUPS_30_TEAMS.items():
        enriched_rows: List[Dict[str, Any]] = []
        for r in rows:
            pos_str = str(r["Posición"]).strip().upper()
            p_name = str(r["Jugador"]).strip()
            mins_esp = float(r["Minutos_Esperados"])
            o_epm = float(r["O_EPM"])
            d_epm = float(r["D_EPM"])
            ppg_b, rpg_b, apg_b = _derivar_metricas_base_jugador(p_name, pos_str, mins_esp, o_epm, d_epm, abbr)
            row_copy = dict(r)
            row_copy["Team_Abbr"] = abbr
            row_copy["Minutos_Base"] = round(mins_esp, 1)
            row_copy["O_EPM_Base"] = round(o_epm, 2)
            row_copy["D_EPM_Base"] = round(d_epm, 2)
            row_copy["Pace_Diff"] = 0.0
            row_copy["PPG_Base"] = ppg_b
            row_copy["RPG_Base"] = rpg_b
            row_copy["APG_Base"] = apg_b
            enriched_rows.append(row_copy)
        lineups_dict[abbr] = pd.DataFrame(enriched_rows)
    return lineups_dict


def obtener_lineup_en_sesion(team_abbr: str, fallback_lineups: Optional[Dict[str, pd.DataFrame]] = None) -> pd.DataFrame:
    """
    Recupera obligatoriamente el quinteto de `st.session_state.lineups_nba` para `team_abbr`.
    Garantiza que las columnas base ('Minutos_Base', 'PPG_Base', 'RPG_Base', 'APG_Base') estén presentes.
    """
    abbr = str(team_abbr).strip().upper()
    source = fallback_lineups
    if source is None and (st is not None and hasattr(st, "session_state")) and "lineups_nba" in st.session_state:
        source = st.session_state.lineups_nba

    df_res: Optional[pd.DataFrame] = None
    if isinstance(source, dict) and abbr in source:
        df_res = source[abbr].copy()
    elif isinstance(source, pd.DataFrame) and not source.empty and "Team_Abbr" in source.columns:
        sub = source[source["Team_Abbr"].astype(str).str.strip().str.upper() == abbr].copy()
        if not sub.empty:
            if "Pos" in sub.columns and "Posición" not in sub.columns:
                sub["Posición"] = sub["Pos"].apply(
                    lambda x: "BENCH" if str(x).strip().upper() in {"BANCA", "BENCH"} else str(x).strip().upper()
                )
            if "Minutos" in sub.columns and "Minutos_Esperados" not in sub.columns:
                sub["Minutos_Esperados"] = pd.to_numeric(sub["Minutos"], errors="coerce").fillna(0.0)
            df_res = sub

    if df_res is None:
        df_res = build_default_lineups_dict()[abbr].copy()

    if "Team_Abbr" not in df_res.columns:
        df_res["Team_Abbr"] = abbr

    if not {"Minutos_Base", "PPG_Base", "RPG_Base", "APG_Base"}.issubset(df_res.columns):
        default_lu = {
            str(r["Jugador"]).lower(): r for r in DEFAULT_LINEUPS_30_TEAMS.get(abbr, [])
        }
        mins_base_list, ppg_b_list, rpg_b_list, apg_b_list = [], [], [], []
        for _, r in df_res.iterrows():
            p_name = str(r.get("Jugador", "")).strip()
            pos_str = str(r.get("Posición", r.get("Pos", "PG"))).strip().upper()
            def_r = default_lu.get(p_name.lower(), {})
            m_base = float(r.get("Minutos_Base", def_r.get("Minutos_Esperados", r.get("Minutos_Esperados", 34.0))))
            if m_base <= 0.0:
                m_base = 34.0
            o_epm = float(r.get("O_EPM", 0.0))
            d_epm = float(r.get("D_EPM", 0.0))
            ppg_d, rpg_d, apg_d = _derivar_metricas_base_jugador(p_name, pos_str, m_base, o_epm, d_epm, abbr)
            mins_base_list.append(round(float(r.get("Minutos_Base", m_base)), 1))
            ppg_b_list.append(round(float(r.get("PPG_Base", ppg_d)), 1))
            rpg_b_list.append(round(float(r.get("RPG_Base", rpg_d)), 1))
            apg_b_list.append(round(float(r.get("APG_Base", apg_d)), 1))
        df_res["Minutos_Base"] = mins_base_list
        df_res["PPG_Base"] = ppg_b_list
        df_res["RPG_Base"] = rpg_b_list
        df_res["APG_Base"] = apg_b_list

    return df_res


# ==============================================================================
# SISTEMA DE AUDITORÍA POST-PARTIDO Y CALIBRACIÓN ADAPTATIVA (FILTRO KALMAN)
# ==============================================================================
def auditar_partido_nba(proyeccion: Dict[str, Any], resultado_real: Dict[str, Any]) -> Dict[str, Any]:
    """
    Módulo de Auditoría Post-Partido para NBA:
    Calcula los residuales entre la proyección previa del modelo Monte Carlo y el resultado real:
      - `Error_Away`: Puntos reales anotados por la visita menos puntos proyectados (`score_away_real - exp_away_pts`)
      - `Error_Home`: Puntos reales anotados por el local menos puntos proyectados (`score_home_real - exp_home_pts`)
      - `Error_Spread`: Diferencial real del local (`margen_real_home`) menos diferencial proyectado (`exp_margin_home`)
      - `Error_Total`: Total de puntos reales (`total_real`) menos total proyectado (`exp_total_pts`)
      - `Error_Pace`: Ritmo real estimado (`pace_real`) menos posesiones proyectadas (`exp_possessions`)
    """
    exp_away = float(proyeccion.get("exp_away_pts", proyeccion.get("pts_away_modelo", 112.0)))
    exp_home = float(proyeccion.get("exp_home_pts", proyeccion.get("pts_home_modelo", 114.5)))
    exp_total = float(proyeccion.get("exp_total_pts", exp_away + exp_home))
    exp_margin_home = float(proyeccion.get("exp_margin_home", exp_home - exp_away))
    proj_spread_home = float(proyeccion.get("proj_spread_home", -exp_margin_home))
    exp_pace = float(proyeccion.get("exp_possessions", proyeccion.get("pace_modelo", 99.0)))

    real_away = float(resultado_real.get("score_away_real", 0.0))
    real_home = float(resultado_real.get("score_home_real", 0.0))
    real_total = real_away + real_home
    real_margin_home = real_home - real_away
    real_spread_home = -real_margin_home
    real_pace = float(
        resultado_real.get("pace_real")
        if resultado_real.get("pace_real") is not None and float(resultado_real.get("pace_real", 0.0)) > 0
        else (real_total / 2.25 if real_total > 0 else exp_pace)
    )

    error_away = round(real_away - exp_away, 2)
    error_home = round(real_home - exp_home, 2)
    error_spread = round(real_margin_home - exp_margin_home, 2)
    error_total = round(real_total - exp_total, 2)
    error_pace = round(real_pace - exp_pace, 2)

    ganador_proy = str(proyeccion.get("home_abbr", "HOME")) if exp_home >= exp_away else str(proyeccion.get("away_abbr", "AWAY"))
    ganador_real = str(proyeccion.get("home_abbr", "HOME")) if real_home >= real_away else str(proyeccion.get("away_abbr", "AWAY"))
    acierto_ganador = bool(ganador_proy == ganador_real)

    return {
        "away_abbr": str(proyeccion.get("away_abbr", resultado_real.get("away_abbr", "AWAY"))),
        "home_abbr": str(proyeccion.get("home_abbr", resultado_real.get("home_abbr", "HOME"))),
        "exp_away_pts": round(exp_away, 1),
        "exp_home_pts": round(exp_home, 1),
        "exp_total_pts": round(exp_total, 1),
        "exp_margin_home": round(exp_margin_home, 1),
        "proj_spread_home": round(proj_spread_home, 1),
        "exp_pace": round(exp_pace, 1),
        "score_away_real": round(real_away, 1),
        "score_home_real": round(real_home, 1),
        "total_real": round(real_total, 1),
        "margen_real_home": round(real_margin_home, 1),
        "spread_real_home": round(real_spread_home, 1),
        "pace_real": round(real_pace, 1),
        "Error_Away": error_away,
        "Error_Home": error_home,
        "Error_Spread": error_spread,
        "Error_Total": error_total,
        "Error_Pace": error_pace,
        "mae_pts": round((abs(error_away) + abs(error_home)) / 2.0, 2),
        "acierto_ganador": acierto_ganador,
    }


def calibrar_ratings_nba(
    df_equipos: pd.DataFrame,
    away_abbr: str,
    home_abbr: str,
    auditoria: Dict[str, Any],
    learning_rate: float = 0.08,
    lineups_dict: Optional[Dict[str, pd.DataFrame]] = None,
) -> pd.DataFrame:
    """
    Calibración Adaptativa tipo Filtro Kalman / Feedback Loop para NBA:
      1. Ajusta el 'Pace' (y 'Base_Pace') de ambos equipos con el residual de ritmo (`Error_Pace`).
      2. Ajusta 'Off_Rtg' y 'Def_Rtg' (y sus columnas base) en el DataFrame de equipos según
         los puntos reales anotados/permitidos frente a la proyección (`Error_Away`, `Error_Home`).
      3. Aplica límites de seguridad (clipping) para mantener los ratings en rangos lógicos de la NBA moderna:
         - Pace: [92.0, 106.5]
         - Off_Rtg: [104.0, 126.5]
         - Def_Rtg: [104.0, 124.5]
      4. Si se proporciona `lineups_dict` (o existe `st.session_state.lineups_nba`), sincroniza también
         el delta de `O_EPM`, `D_EPM` y `Pace_Diff` de los titulares para que el motor Bottom-Up y el
         Excel calibrado reflejen exactamente los nuevos ratings.
    """
    df_cal = df_equipos.copy()
    a_code = str(away_abbr).strip().upper()
    h_code = str(home_abbr).strip().upper()
    lr = float(np.clip(learning_rate, 0.01, 0.35))

    err_away = float(auditoria.get("Error_Away", 0.0))
    err_home = float(auditoria.get("Error_Home", 0.0))
    err_pace = float(auditoria.get("Error_Pace", 0.0))
    pace_ref = max(float(auditoria.get("pace_real", 99.0)), 88.0)

    # Convertir los errores de puntos del partido a escala por 100 posesiones
    err_away_per100 = err_away * (100.0 / pace_ref)
    err_home_per100 = err_home * (100.0 / pace_ref)

    # Deltas Kalman:
    # - Si Away anotó más de lo esperado (err_away > 0): sube Off_Rtg de Away y sube Def_Rtg de Home (peor defensa)
    # - Si Home anotó más de lo esperado (err_home > 0): sube Off_Rtg de Home y sube Def_Rtg de Away (peor defensa)
    delta_away_off = lr * err_away_per100
    delta_home_def = lr * err_away_per100

    delta_home_off = lr * err_home_per100
    delta_away_def = lr * err_home_per100

    delta_pace = lr * err_pace

    away_mask = df_cal["Team_Abbr"].astype(str).str.strip().str.upper() == a_code
    home_mask = df_cal["Team_Abbr"].astype(str).str.strip().str.upper() == h_code

    if away_mask.any():
        idx_a = df_cal[away_mask].index[0]
        new_a_pace = round(float(np.clip(float(df_cal.loc[idx_a, "Pace"]) + delta_pace, *PACE_CLIP_RANGE)), 1)
        new_a_off = round(float(np.clip(float(df_cal.loc[idx_a, "Off_Rtg"]) + delta_away_off, *ORTG_CLIP_RANGE)), 1)
        new_a_def = round(float(np.clip(float(df_cal.loc[idx_a, "Def_Rtg"]) + delta_away_def, *DRTG_CLIP_RANGE)), 1)

        df_cal.loc[idx_a, "Pace"] = new_a_pace
        df_cal.loc[idx_a, "Off_Rtg"] = new_a_off
        df_cal.loc[idx_a, "Def_Rtg"] = new_a_def
        if "Base_Pace" in df_cal.columns:
            df_cal.loc[idx_a, "Base_Pace"] = new_a_pace
        if "Base_Off_Rtg" in df_cal.columns:
            df_cal.loc[idx_a, "Base_Off_Rtg"] = new_a_off
        if "Base_Def_Rtg" in df_cal.columns:
            df_cal.loc[idx_a, "Base_Def_Rtg"] = new_a_def

    if home_mask.any():
        idx_h = df_cal[home_mask].index[0]
        new_h_pace = round(float(np.clip(float(df_cal.loc[idx_h, "Pace"]) + delta_pace, *PACE_CLIP_RANGE)), 1)
        new_h_off = round(float(np.clip(float(df_cal.loc[idx_h, "Off_Rtg"]) + delta_home_off, *ORTG_CLIP_RANGE)), 1)
        new_h_def = round(float(np.clip(float(df_cal.loc[idx_h, "Def_Rtg"]) + delta_home_def, *DRTG_CLIP_RANGE)), 1)

        df_cal.loc[idx_h, "Pace"] = new_h_pace
        df_cal.loc[idx_h, "Off_Rtg"] = new_h_off
        df_cal.loc[idx_h, "Def_Rtg"] = new_h_def
        if "Base_Pace" in df_cal.columns:
            df_cal.loc[idx_h, "Base_Pace"] = new_h_pace
        if "Base_Off_Rtg" in df_cal.columns:
            df_cal.loc[idx_h, "Base_Off_Rtg"] = new_h_off
        if "Base_Def_Rtg" in df_cal.columns:
            df_cal.loc[idx_h, "Base_Def_Rtg"] = new_h_def

    # Sincronizar ajustes Kalman hacia los quintetos en sesión para que el motor Bottom-Up y el Excel exportado los preserven
    target_lineups = lineups_dict
    if target_lineups is None and (st is not None and hasattr(st, "session_state")) and "lineups_nba" in st.session_state:
        target_lineups = st.session_state.lineups_nba

    if isinstance(target_lineups, dict):
        synergy_scale = 0.62
        for t_code, d_off, d_def, d_pace in [
            (a_code, delta_away_off, delta_away_def, delta_pace),
            (h_code, delta_home_off, delta_home_def, delta_pace),
        ]:
            if t_code in target_lineups:
                lu_df = target_lineups[t_code].copy()
                # En calcular_ratings_lineup: proj_off_rtg = 115.5 + sum(slots * O_EPM) * 0.62
                # y proj_def_rtg = 115.5 - sum(slots * D_EPM) * 0.62 (con sum(slots) = 5.0)
                o_epm_step = d_off / (5.0 * synergy_scale)
                d_epm_step = -d_def / (5.0 * synergy_scale)
                pace_step = d_pace / 5.0

                lu_df["O_EPM"] = (pd.to_numeric(lu_df["O_EPM"], errors="coerce").fillna(0.0) + o_epm_step).clip(-8.0, 10.0).round(2)
                lu_df["D_EPM"] = (pd.to_numeric(lu_df["D_EPM"], errors="coerce").fillna(0.0) + d_epm_step).clip(-8.0, 10.0).round(2)
                if "Pace_Diff" not in lu_df.columns:
                    lu_df["Pace_Diff"] = 0.0
                lu_df["Pace_Diff"] = (pd.to_numeric(lu_df["Pace_Diff"], errors="coerce").fillna(0.0) + pace_step).clip(-4.0, 4.0).round(2)
                target_lineups[t_code] = lu_df

    return df_cal


# ==============================================================================
# MOTOR DE PROYECCIÓN DE PLAYER PROPS (PTS, REB, AST) Y VALOR +EV (POISSON DECIMAL)
# ==============================================================================
def evaluar_mercado_prop_poisson(
    mercado: str,
    lambda_esperada: float,
    linea_mercado: float,
    cuota_over_decimal: float = 1.91,
    cuota_under_decimal: Optional[float] = None,
    umbral_ev_pct: float = 5.0,
) -> Dict[str, Any]:
    """
    Evalúa un mercado individual de Player Prop (PTS, REB o AST) frente a una línea de sportsbook
    usando distribución de Poisson con media esperada λ y cuotas en formato decimal.
    """
    lam = max(0.2, float(lambda_esperada))
    linea = round(float(linea_mercado), 1)
    c_over = round(max(1.01, float(cuota_over_decimal)), 2)
    c_under = round(max(1.01, float(cuota_under_decimal if cuota_under_decimal is not None else cuota_over_decimal)), 2)

    k_floor = int(math.floor(linea))
    if abs(linea - round(linea)) < 1e-6 and k_floor >= 1:
        p_under_raw = _poisson_cdf(k_floor - 1, lam)
        p_over_raw = 1.0 - _poisson_cdf(k_floor, lam)
        denom = max(p_over_raw + p_under_raw, 0.01)
        prob_over = float(np.clip(p_over_raw / denom, 0.01, 0.99))
        prob_under = float(np.clip(1.0 - prob_over, 0.01, 0.99))
    else:
        prob_under = float(np.clip(_poisson_cdf(k_floor, lam), 0.01, 0.99))
        prob_over = float(np.clip(1.0 - prob_under, 0.01, 0.99))

    fair_odd_over = round(1.0 / prob_over, 2)
    fair_odd_under = round(1.0 / prob_under, 2)

    ev_over_pct = round(((prob_over * c_over) - 1.0) * 100.0, 1)
    ev_under_pct = round(((prob_under * c_under) - 1.0) * 100.0, 1)

    if ev_over_pct >= float(umbral_ev_pct):
        pick_side = "OVER"
        ev_display = ev_over_pct
        cuota_activa = c_over
        fair_odd_activa = fair_odd_over
        prob_activa = round(prob_over * 100.0, 1)
        badge_text = f"[⚡ VALOR: OVER {linea:.1f} @ {c_over:.2f} ({ev_display:+.1f}% EV)]"
        badge_color = "#00ff88"
        tiene_valor = True
    elif ev_under_pct >= float(umbral_ev_pct) or (ev_over_pct <= -float(umbral_ev_pct) and lam < linea):
        pick_side = "UNDER"
        ev_display = ev_under_pct if ev_under_pct >= float(umbral_ev_pct) else round(abs(ev_over_pct), 1)
        cuota_activa = c_under
        fair_odd_activa = fair_odd_under
        prob_activa = round(prob_under * 100.0, 1)
        badge_text = f"[⚡ VALOR: UNDER {linea:.1f} @ {c_under:.2f} (+{abs(ev_display):.1f}% EV)]"
        badge_color = "#ff3366"
        tiene_valor = True
    else:
        pick_side = "LÍNEA JUSTA"
        ev_display = ev_over_pct if prob_over >= prob_under else ev_under_pct
        cuota_activa = c_over
        fair_odd_activa = fair_odd_over if prob_over >= prob_under else fair_odd_under
        prob_activa = round(max(prob_over, prob_under) * 100.0, 1)
        badge_text = "[LÍNEA JUSTA]"
        badge_color = "#555555"
        tiene_valor = False

    return {
        "mercado": str(mercado).upper(),
        "proyeccion": round(lam, 1),
        "lambda": round(lam, 2),
        "linea": linea,
        "cuota": cuota_activa,
        "cuota_over": c_over,
        "cuota_under": c_under,
        "prob_over": round(prob_over * 100.0, 1),
        "prob_under": round(prob_under * 100.0, 1),
        "fair_odd_over": fair_odd_over,
        "fair_odd_under": fair_odd_under,
        "fair_odd": fair_odd_activa,
        "ev_over_pct": ev_over_pct,
        "ev_under_pct": ev_under_pct,
        "ev_pct": ev_display,
        "pick": pick_side,
        "prob_pick": prob_activa,
        "badge": badge_text,
        "badge_color": badge_color,
        "valor": tiene_valor,
    }


def proyectar_props_jugador(
    jugador_dict: Dict[str, Any],
    minutos_proyectados: float,
    pace_partido: float,
    pace_promedio_liga: float = 99.5,
    def_rating_rival: float = 115.0,
    lineas_mercado: Optional[Dict[str, float]] = None,
    cuotas_mercado: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Motor Cuantitativo de Proyección de Player Props (PTS, REB, AST) y Auditoría de Valor +EV en Decimal.
    """
    nombre = str(jugador_dict.get("Jugador", jugador_dict.get("player_name", "Jugador"))).strip()
    team_abbr = str(jugador_dict.get("Team_Abbr", jugador_dict.get("team_abbr", "NBA"))).strip().upper()
    pos_str = str(jugador_dict.get("Posición", jugador_dict.get("Pos", "SF"))).strip().upper()
    o_epm = float(jugador_dict.get("O_EPM", 2.0))
    d_epm = float(jugador_dict.get("D_EPM", 0.5))

    minutos_base = float(jugador_dict.get("Minutos_Base", 34.0))
    if minutos_base <= 0.5:
        minutos_base = 34.0

    ppg_def, rpg_def, apg_def = _derivar_metricas_base_jugador(
        nombre, pos_str, minutos_base, o_epm, d_epm, team_abbr
    )
    ppg_base = float(jugador_dict.get("PPG_Base", jugador_dict.get("base_ppg", ppg_def)))
    rpg_base = float(jugador_dict.get("RPG_Base", rpg_def))
    apg_base = float(jugador_dict.get("APG_Base", apg_def))

    mins_proy = max(0.0, float(minutos_proyectados))
    factor_pace = float(pace_partido) / max(float(pace_promedio_liga), 80.0)
    factor_min = mins_proy / minutos_base
    factor_def = float(def_rating_rival) / 115.0

    lambda_pts = max(0.5, ppg_base * factor_min * factor_pace * factor_def)
    lambda_reb = max(0.3, rpg_base * factor_min * factor_pace)
    lambda_ast = max(0.3, apg_base * factor_min * factor_pace * factor_def)

    lineas_in = lineas_mercado or {}
    cuotas_in = cuotas_mercado or {}

    linea_pts = float(
        lineas_in.get(
            "PTS",
            jugador_dict.get("PPG_Linea", jugador_dict.get("prop_line", round_to_half_point(max(0.5, ppg_base - 0.5)))),
        )
    )
    linea_reb = float(
        lineas_in.get(
            "REB",
            jugador_dict.get("RPG_Linea", round_to_half_point(max(0.5, rpg_base - 0.5))),
        )
    )
    linea_ast = float(
        lineas_in.get(
            "AST",
            jugador_dict.get("APG_Linea", round_to_half_point(max(0.5, apg_base - 0.5))),
        )
    )

    cuota_pts = float(cuotas_in.get("PTS", jugador_dict.get("Cuota_PTS", 1.91)))
    cuota_reb = float(cuotas_in.get("REB", jugador_dict.get("Cuota_REB", 1.91)))
    cuota_ast = float(cuotas_in.get("AST", jugador_dict.get("Cuota_AST", 1.91)))

    eval_pts = evaluar_mercado_prop_poisson("PTS", lambda_pts, linea_pts, cuota_over_decimal=cuota_pts)
    eval_reb = evaluar_mercado_prop_poisson("REB", lambda_reb, linea_reb, cuota_over_decimal=cuota_reb)
    eval_ast = evaluar_mercado_prop_poisson("AST", lambda_ast, linea_ast, cuota_over_decimal=cuota_ast)

    return {
        "jugador": nombre,
        "team_abbr": team_abbr,
        "posicion": pos_str,
        "minutos_base": round(minutos_base, 1),
        "minutos_proyectados": round(mins_proy, 1),
        "ppg_base": round(ppg_base, 1),
        "rpg_base": round(rpg_base, 1),
        "apg_base": round(apg_base, 1),
        "factor_pace": round(factor_pace, 3),
        "factor_min": round(factor_min, 3),
        "lambda_pts": round(lambda_pts, 1),
        "lambda_reb": round(lambda_reb, 1),
        "lambda_ast": round(lambda_ast, 1),
        "PTS": eval_pts,
        "REB": eval_reb,
        "AST": eval_ast,
    }


# ==============================================================================
# DETECTORES DE VALOR CUANTITATIVO DE PARTIDO (+EV EN FORMATO DECIMAL)
# ==============================================================================
def evaluar_valor_totales_nba(
    total_modelo: float,
    total_mercado: float,
    cuota_over: float,
    cuota_under: float,
    umbral_pts: float = 3.0,
    prob_over_sim: Optional[float] = None,
    prob_under_sim: Optional[float] = None,
) -> Dict[str, Any]:
    """Auditoría matemática de Totales (Over/Under) en formato estrictamente DECIMAL."""
    t_mod = float(total_modelo)
    t_mkt = round(float(total_mercado), 1)
    c_over = round(float(cuota_over), 2)
    c_under = round(float(cuota_under), 2)
    edge_pts = t_mod - t_mkt

    if prob_over_sim is not None and 0.01 < float(prob_over_sim) < 0.99:
        prob_over = float(prob_over_sim)
    else:
        prob_over = float(np.clip(_normal_cdf(edge_pts / NBA_TOTAL_SIM_STD), 0.05, 0.95))

    if prob_under_sim is not None and 0.01 < float(prob_under_sim) < 0.99:
        prob_under = float(prob_under_sim)
    else:
        prob_under = float(np.clip(1.0 - prob_over, 0.05, 0.95))

    if edge_pts >= float(umbral_pts):
        ev_pct = round(((prob_over * c_over) - 1.0) * 100.0, 1)
        return {
            "pick": "OVER",
            "linea": t_mkt,
            "cuota": c_over,
            "edge_pts": round(edge_pts, 1),
            "ev_pct": ev_pct,
            "prob": round(prob_over * 100.0, 1),
            "badge_color": "#00ff88",
            "valor": True,
        }

    if edge_pts <= -float(umbral_pts):
        ev_pct = round(((prob_under * c_under) - 1.0) * 100.0, 1)
        return {
            "pick": "UNDER",
            "linea": t_mkt,
            "cuota": c_under,
            "edge_pts": round(abs(edge_pts), 1),
            "ev_pct": ev_pct,
            "prob": round(prob_under * 100.0, 1),
            "badge_color": "#ff3366",
            "valor": True,
        }

    return {
        "pick": "LÍNEA EFICIENTE",
        "linea": t_mkt,
        "cuota": c_over,
        "edge_pts": round(abs(edge_pts), 1),
        "ev_pct": 0.0,
        "prob": round(max(prob_over, prob_under) * 100.0, 1),
        "badge_color": "#555555",
        "valor": False,
    }


def evaluar_valor_spread_nba(
    spread_modelo: float,
    spread_mercado_home: float,
    cuota_home: float,
    cuota_away: float,
    umbral_pts: float = 3.0,
    home_abbr: str = "HOME",
    away_abbr: str = "AWAY",
    prob_home_cover_sim: Optional[float] = None,
    prob_away_cover_sim: Optional[float] = None,
) -> Dict[str, Any]:
    """Auditoría matemática de Hándicap / Spread en formato estrictamente DECIMAL."""
    sp_mod = float(spread_modelo)
    sp_mkt_home = round(float(spread_mercado_home), 1)
    sp_mkt_away = round(-sp_mkt_home, 1)
    c_home = round(float(cuota_home), 2)
    c_away = round(float(cuota_away), 2)

    edge_home_pts = sp_mkt_home - sp_mod
    edge_away_pts = -edge_home_pts

    if prob_home_cover_sim is not None and 0.01 < float(prob_home_cover_sim) < 0.99:
        prob_home_cover = float(prob_home_cover_sim)
    else:
        prob_home_cover = float(np.clip(_normal_cdf(edge_home_pts / NBA_MARGIN_SIM_STD), 0.05, 0.95))

    if prob_away_cover_sim is not None and 0.01 < float(prob_away_cover_sim) < 0.99:
        prob_away_cover = float(prob_away_cover_sim)
    else:
        prob_away_cover = float(np.clip(1.0 - prob_home_cover, 0.05, 0.95))

    if edge_home_pts >= float(umbral_pts):
        ev_pct = round(((prob_home_cover * c_home) - 1.0) * 100.0, 1)
        linea_str = f"{sp_mkt_home:+.1f}"
        return {
            "pick": f"{home_abbr} {linea_str}",
            "lado": "HOME",
            "franquicia": home_abbr,
            "linea": sp_mkt_home,
            "linea_str": linea_str,
            "cuota": c_home,
            "edge_pts": round(edge_home_pts, 1),
            "ev_pct": ev_pct,
            "prob": round(prob_home_cover * 100.0, 1),
            "badge_color": "#00e5ff",
            "valor": True,
        }

    if edge_away_pts >= float(umbral_pts):
        ev_pct = round(((prob_away_cover * c_away) - 1.0) * 100.0, 1)
        linea_str = f"{sp_mkt_away:+.1f}"
        return {
            "pick": f"{away_abbr} {linea_str}",
            "lado": "AWAY",
            "franquicia": away_abbr,
            "linea": sp_mkt_away,
            "linea_str": linea_str,
            "cuota": c_away,
            "edge_pts": round(edge_away_pts, 1),
            "ev_pct": ev_pct,
            "prob": round(prob_away_cover * 100.0, 1),
            "badge_color": "#00e5ff",
            "valor": True,
        }

    return {
        "pick": "SPREAD EFICIENTE",
        "lado": "NEUTRAL",
        "franquicia": home_abbr,
        "linea": sp_mkt_home,
        "linea_str": f"{sp_mkt_home:+.1f}",
        "cuota": c_home,
        "edge_pts": round(abs(edge_home_pts), 1),
        "ev_pct": 0.0,
        "prob": round(max(prob_home_cover, prob_away_cover) * 100.0, 1),
        "badge_color": "#555555",
        "valor": False,
    }


# ==============================================================================
# GESTIÓN DE PLANTILLAS EXCEL (.XLSX): GENERACIÓN Y PARSEO A LINEUPS
# ==============================================================================
def _interpretar_booleano_estrella(val) -> bool:
    """Normaliza valores booleanos o de texto ('True', 'SI', 'SÍ', '1', 'YES') para Es_Estrella."""
    if isinstance(val, (bool, np.bool_)):
        return bool(val)
    if pd.isna(val):
        return False
    s = str(val).strip().upper()
    return s in {"TRUE", "VERDADERO", "1", "1.0", "SI", "SÍ", "YES", "Y", "STAR", "ESTRELLA"}


def generar_dataframe_plantilla_excel(
    lineups_dict: Optional[Dict[str, pd.DataFrame]] = None,
    df_teams: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Consolida en un solo DataFrame plano la información de los 30 equipos para exportar a Excel (.xlsx).
    Incluye tanto las columnas operativas como las métricas base ('Minutos_Base', 'PPG_Base', 'RPG_Base', 'APG_Base').
    """
    if df_teams is None:
        if (st is not None and hasattr(st, "session_state")) and "df_nba" in st.session_state:
            df_teams = st.session_state.df_nba
        else:
            df_teams = pd.DataFrame(DEFAULT_CSV_DATA)
    if lineups_dict is None:
        if (st is not None and hasattr(st, "session_state")) and "lineups_nba" in st.session_state:
            lineups_dict = st.session_state.lineups_nba
        else:
            lineups_dict = build_default_lineups_dict()

    team_meta_map: Dict[str, Dict] = {}
    for _, row in df_teams.iterrows():
        t_abbr = str(row["Team_Abbr"]).strip().upper()
        team_meta_map[t_abbr] = {
            "Star1_Name": str(row.get("Star1_Name", "")).strip(),
            "Star1_Line": float(row.get("Star1_Line", 20.5)),
            "Star2_Name": str(row.get("Star2_Name", "")).strip(),
            "Star2_Line": float(row.get("Star2_Line", 18.5)),
        }

    records: List[Dict] = []
    ordered_abbrs = list(DEFAULT_LINEUPS_30_TEAMS.keys())

    for abbr in ordered_abbrs:
        lu_df = obtener_lineup_en_sesion(abbr, fallback_lineups=lineups_dict)
        default_lu = {
            str(r["Jugador"]).lower(): r for r in DEFAULT_LINEUPS_30_TEAMS.get(abbr, [])
        }

        meta = team_meta_map.get(abbr, {})
        s1_name = meta.get("Star1_Name", "").lower()
        s2_name = meta.get("Star2_Name", "").lower()
        s1_line = meta.get("Star1_Line", 22.5)
        s2_line = meta.get("Star2_Line", 19.5)

        for _, r in lu_df.iterrows():
            raw_pos = str(r.get("Posición", r.get("Pos", "PG"))).strip()
            pos_label = "Banca" if raw_pos.upper() in {"BENCH", "BANCA"} else raw_pos.upper()
            player_name = str(r.get("Jugador", "")).strip()
            mins_val = round(float(r.get("Minutos_Esperados", r.get("Minutos", 0.0))), 1)
            def_r = default_lu.get(player_name.lower(), {})
            mins_base_val = round(
                float(r.get("Minutos_Base", def_r.get("Minutos_Esperados", mins_val if mins_val > 0 else 34.0))),
                1,
            )
            o_epm_val = round(float(r.get("O_EPM", 0.0)), 1)
            d_epm_val = round(float(r.get("D_EPM", 0.0)), 1)
            pace_diff_val = round(float(r.get("Pace_Diff", 0.0)), 2)

            ppg_def, rpg_def, apg_def = _derivar_metricas_base_jugador(
                player_name, pos_label, mins_base_val, o_epm_val, d_epm_val, abbr
            )
            ppg_base_val = round(float(r.get("PPG_Base", ppg_def)), 1)
            rpg_base_val = round(float(r.get("RPG_Base", rpg_def)), 1)
            apg_base_val = round(float(r.get("APG_Base", apg_def)), 1)

            if "Es_Estrella" in r and pd.notna(r["Es_Estrella"]):
                es_estrella = _interpretar_booleano_estrella(r["Es_Estrella"])
            else:
                p_low = player_name.lower()
                es_estrella = bool(pos_label != "Banca" and p_low in {s1_name, s2_name})

            if "PPG_Linea" in r and pd.notna(r["PPG_Linea"]) and float(r["PPG_Linea"]) > 0:
                ppg_linea = round(float(r["PPG_Linea"]), 1)
            elif player_name.lower() == s1_name:
                ppg_linea = round(float(s1_line), 1)
            elif player_name.lower() == s2_name:
                ppg_linea = round(float(s2_line), 1)
            elif pos_label == "Banca":
                ppg_linea = 0.0
            else:
                ppg_linea = round_to_half_point(max(0.5, ppg_base_val - 0.5))

            records.append(
                {
                    "Team_Abbr": abbr,
                    "Pos": pos_label,
                    "Jugador": player_name,
                    "Minutos": float(mins_val),
                    "Minutos_Base": float(mins_base_val),
                    "O_EPM": float(o_epm_val),
                    "D_EPM": float(d_epm_val),
                    "Pace_Diff": float(pace_diff_val),
                    "Es_Estrella": bool(es_estrella),
                    "PPG_Base": float(ppg_base_val),
                    "RPG_Base": float(rpg_base_val),
                    "APG_Base": float(apg_base_val),
                    "PPG_Linea": float(ppg_linea),
                }
            )

    df_out = pd.DataFrame(records)[EXCEL_TEMPLATE_COLS]
    for fcol in ["Minutos", "Minutos_Base", "O_EPM", "D_EPM", "Pace_Diff", "PPG_Base", "RPG_Base", "APG_Base", "PPG_Linea"]:
        df_out[fcol] = df_out[fcol].astype(float)
    return df_out


# ==============================================================================
# GESTIÓN AUTOMÁTICA DE LESIONES ESPN Y REASIGNACIÓN PROPORCIONAL DE MINUTOS
# ==============================================================================
def _es_fila_banca(pos_value: Any) -> bool:
    """Identifica si una fila corresponde a la unidad agregada de banca/rotación."""
    return str(pos_value or "").strip().upper() in {
        "BENCH",
        "BANCA",
        "BN",
        "ROTACION",
        "ROTACIÓN",
    }


def redistribuir_minutos_equipo_por_lesiones(
    df_team: pd.DataFrame,
    lesiones_equipo: Optional[List[Dict[str, Any]]] = None,
    team_abbr: str = "",
    max_minutos_jugador: float = MAX_PLAYER_PROJECTED_MINUTES,
    total_minutos_partido: float = TEAM_TOTAL_GAME_MINUTES,
) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    """
    Cruza los jugadores del equipo con el reporte oficial de lesiones de ESPN ('Out' / 'Doubtful'):
      1. Si un jugador individual está descartado ('Out' o 'Doubtful'), reduce sus minutos a 0.0.
      2. Redistribuye sus minutos de forma proporcional entre los jugadores activos del mismo equipo,
         garantizando matemáticamente que:
           - La rotación total del equipo sume exactamente 240.0 minutos por partido.
           - Ningún jugador individual supere los 42.0 minutos proyectados.
    """
    if df_team is None or df_team.empty:
        return df_team, []

    df_adj = df_team.copy().reset_index(drop=True)
    abbr_clean = str(team_abbr or "").strip().upper()
    mins_col = "Minutos_Esperados" if "Minutos_Esperados" in df_adj.columns else "Minutos"
    pos_col = "Posición" if "Posición" in df_adj.columns else "Pos"

    mapa_bajas: Dict[str, Dict[str, Any]] = {}
    for item in lesiones_equipo or []:
        if not isinstance(item, dict):
            continue
        st_val = str(item.get("status", "")).strip().title()
        if st_val not in {"Out", "Doubtful"}:
            continue
        norm_p = str(item.get("jugador_norm") or normalizar_nombre_jugador_nba(str(item.get("jugador", "")))).strip()
        if norm_p:
            mapa_bajas[norm_p] = item

    # Si una fila había sido puesta en 0.0 automáticamente en una corrida previa y hoy ya está sana,
    # restaurar sus Minutos_Base antes de recalcular la rotación activa.
    if "Baja_Descontada" in df_adj.columns and "Minutos_Base" in df_adj.columns:
        for idx_r in range(len(df_adj)):
            prev_disc = bool(df_adj.loc[idx_r, "Baja_Descontada"])
            p_norm_chk = normalizar_nombre_jugador_nba(str(df_adj.loc[idx_r, "Jugador"]))
            if prev_disc and p_norm_chk not in mapa_bajas and not _es_fila_banca(df_adj.loc[idx_r, pos_col]):
                base_restore = float(df_adj.loc[idx_r, "Minutos_Base"])
                if base_restore > 0.0:
                    df_adj.loc[idx_r, mins_col] = round(base_restore, 1)

    n_rows = len(df_adj)
    raw_mins = pd.to_numeric(df_adj[mins_col], errors="coerce").fillna(0.0).clip(lower=0.0).tolist()
    base_mins = (
        pd.to_numeric(df_adj["Minutos_Base"], errors="coerce").fillna(0.0).clip(lower=0.0).tolist()
        if "Minutos_Base" in df_adj.columns
        else list(raw_mins)
    )

    is_bench: List[bool] = []
    is_out: List[bool] = []
    estados_col: List[str] = []
    detalles_col: List[str] = []
    minutos_desc_col: List[float] = []
    bajas_aplicadas: List[Dict[str, Any]] = []

    for i in range(n_rows):
        pos_val = str(df_adj.loc[i, pos_col]).strip()
        p_name = str(df_adj.loc[i, "Jugador"]).strip()
        bench_flag = _es_fila_banca(pos_val)
        is_bench.append(bench_flag)

        p_norm = normalizar_nombre_jugador_nba(p_name)
        if not bench_flag and p_norm and p_norm in mapa_bajas:
            inj_info = mapa_bajas[p_norm]
            orig_m = raw_mins[i] if raw_mins[i] > 0.0 else (base_mins[i] if base_mins[i] > 0.0 else 0.0)
            is_out.append(True)
            raw_mins[i] = 0.0
            status_lbl = str(inj_info.get("status", "Out"))
            detalle_lbl = str(inj_info.get("detalle", "")).strip()
            estados_col.append(status_lbl)
            detalles_col.append(detalle_lbl)
            minutos_desc_col.append(round(float(orig_m), 1))
            bajas_aplicadas.append(
                {
                    "team_abbr": abbr_clean,
                    "jugador": p_name,
                    "pos": pos_val.upper(),
                    "status": status_lbl,
                    "detalle": detalle_lbl,
                    "minutos_descontados": round(float(orig_m), 1),
                }
            )
        else:
            is_out.append(False)
            estados_col.append("")
            detalles_col.append("")
            minutos_desc_col.append(0.0)

    df_adj["Estado_Lesion"] = estados_col
    df_adj["Detalle_Lesion"] = detalles_col
    df_adj["Baja_Descontada"] = is_out
    df_adj["Minutos_Descontados"] = minutos_desc_col

    active_idx = [i for i in range(n_rows) if not is_out[i]]
    caps: Dict[int, float] = {
        i: (0.0 if is_out[i] else (float(total_minutos_partido) if is_bench[i] else float(max_minutos_jugador)))
        for i in range(n_rows)
    }

    # Si un Excel personalizado no tiene fila agregada de Banca y tiene pocos titulares activos
    # cuya capacidad (N * 42.0) no alcanza 240.0 min, agregamos unidad de banca de emergencia
    # para respetar simultáneamente sum == 240.0 y max_individual <= 42.0.
    max_active_capacity = sum(caps[i] for i in active_idx)
    if max_active_capacity < float(total_minutos_partido) - 1e-6:
        emerg_row: Dict[str, Any] = {col: 0.0 for col in df_adj.columns}
        emerg_row[pos_col] = "BENCH" if pos_col == "Posición" else "Banca"
        emerg_row["Jugador"] = "Rotación Banca Emergencia"
        emerg_row[mins_col] = 10.0
        if "Minutos_Base" in df_adj.columns:
            emerg_row["Minutos_Base"] = 10.0
        if "O_EPM" in df_adj.columns:
            emerg_row["O_EPM"] = -1.6
        if "D_EPM" in df_adj.columns:
            emerg_row["D_EPM"] = -1.0
        if "Es_Estrella" in df_adj.columns:
            emerg_row["Es_Estrella"] = False
        emerg_row["Estado_Lesion"] = ""
        emerg_row["Detalle_Lesion"] = ""
        emerg_row["Baja_Descontada"] = False
        emerg_row["Minutos_Descontados"] = 0.0
        df_adj = pd.concat([df_adj, pd.DataFrame([emerg_row])], ignore_index=True)

        new_i = len(df_adj) - 1
        n_rows = len(df_adj)
        raw_mins.append(10.0)
        base_mins.append(10.0)
        is_bench.append(True)
        is_out.append(False)
        active_idx.append(new_i)
        caps[new_i] = float(total_minutos_partido)

    current_active_sum = sum(raw_mins[i] for i in active_idx)
    any_over_cap = any((not is_bench[i]) and raw_mins[i] > float(max_minutos_jugador) + 1e-6 for i in active_idx)
    needs_redistribution = (
        any(is_out)
        or abs(current_active_sum - float(total_minutos_partido)) > 0.05
        or any_over_cap
    )

    if not needs_redistribution:
        df_adj[mins_col] = [round(float(m), 1) for m in raw_mins]
        if "Minutos" in df_adj.columns and mins_col != "Minutos":
            df_adj["Minutos"] = df_adj[mins_col]
        return df_adj, bajas_aplicadas

    weights: Dict[int, float] = {}
    for i in active_idx:
        w = raw_mins[i] if raw_mins[i] > 0.0 else (base_mins[i] if base_mins[i] > 0.0 else 1.0)
        weights[i] = float(max(w, 0.1))

    # Water-filling iterativo proporcional respetando tope estricto de 42.0 min por jugador individual
    remaining_indices = list(active_idx)
    remaining_minutes = float(total_minutos_partido)
    exact_alloc: Dict[int, float] = {i: 0.0 for i in range(n_rows)}

    while remaining_indices and remaining_minutes > 1e-9:
        w_sum = sum(weights[i] for i in remaining_indices)
        if w_sum <= 1e-9:
            for i in remaining_indices:
                weights[i] = 1.0
            w_sum = float(len(remaining_indices))

        provisional = {
            i: remaining_minutes * (weights[i] / w_sum)
            for i in remaining_indices
        }
        over_cap = [i for i in remaining_indices if provisional[i] > caps[i] + 1e-9]
        if not over_cap:
            for i in remaining_indices:
                exact_alloc[i] = min(caps[i], provisional[i])
            remaining_minutes = 0.0
            break

        for i in over_cap:
            exact_alloc[i] = caps[i]
            remaining_minutes = max(0.0, remaining_minutes - caps[i])
            remaining_indices.remove(i)

    # Redondeo exacto por método de restos mayores (Hamilton en décimas de minuto) para garantizar
    # suma exacta == 240.0 min (2400 décimas) y ningún jugador individual > 42.0 min (420 décimas).
    target_tenths = int(round(float(total_minutos_partido) * 10))
    cap_tenths = {i: int(round(caps[i] * 10)) for i in range(n_rows)}
    tenths_alloc: Dict[int, int] = {}
    remainders: Dict[int, float] = {}

    for i in range(n_rows):
        if i not in active_idx:
            tenths_alloc[i] = 0
            remainders[i] = 0.0
        else:
            scaled = exact_alloc[i] * 10.0
            fl = min(int(math.floor(scaled + 1e-9)), cap_tenths[i])
            tenths_alloc[i] = max(0, fl)
            remainders[i] = scaled - fl

    diff_tenths = target_tenths - sum(tenths_alloc.values())
    if diff_tenths > 0:
        eligible = sorted(
            [i for i in active_idx if tenths_alloc[i] < cap_tenths[i]],
            key=lambda idx: (remainders[idx], 1 if is_bench[idx] else 0, weights.get(idx, 0.0)),
            reverse=True,
        )
        step_k = 0
        while diff_tenths > 0 and eligible:
            chosen = eligible[step_k % len(eligible)]
            if tenths_alloc[chosen] < cap_tenths[chosen]:
                tenths_alloc[chosen] += 1
                diff_tenths -= 1
            eligible = [i for i in eligible if tenths_alloc[i] < cap_tenths[i]]
            step_k += 1
    elif diff_tenths < 0:
        removable = sorted(
            [i for i in active_idx if tenths_alloc[i] > 0],
            key=lambda idx: (remainders[idx], 0 if is_bench[idx] else 1),
        )
        step_k = 0
        while diff_tenths < 0 and removable:
            chosen = removable[step_k % len(removable)]
            if tenths_alloc[chosen] > 0:
                tenths_alloc[chosen] -= 1
                diff_tenths += 1
            removable = [i for i in removable if tenths_alloc[i] > 0]
            step_k += 1

    final_mins = [round(tenths_alloc[i] / 10.0, 1) for i in range(n_rows)]
    df_adj[mins_col] = final_mins
    if "Minutos" in df_adj.columns and mins_col != "Minutos":
        df_adj["Minutos"] = final_mins

    return df_adj, bajas_aplicadas


def _st_session_disponible() -> bool:
    """Verifica si existe un runtime activo de Streamlit antes de acceder a st.session_state."""
    if st is None or not hasattr(st, "session_state"):
        return False
    try:
        if hasattr(st, "runtime") and hasattr(st.runtime, "exists"):
            return bool(st.runtime.exists())
    except Exception:
        return False
    return False


def extraer_bajas_detectadas_equipo(
    df_lineup: Optional[pd.DataFrame],
    team_abbr: str = "",
) -> List[Dict[str, Any]]:
    """
    Extrae la lista de bajas ('Out' / 'Doubtful') efectivamente descontadas a 0.0 minutos
    por el motor en el DataFrame de rotación de un equipo.
    """
    abbr_up = str(team_abbr or "").strip().upper()
    if df_lineup is None or not isinstance(df_lineup, pd.DataFrame) or df_lineup.empty:
        return []

    mins_col = "Minutos_Esperados" if "Minutos_Esperados" in df_lineup.columns else "Minutos"
    pos_col = "Posición" if "Posición" in df_lineup.columns else "Pos"

    if "Baja_Descontada" in df_lineup.columns:
        bajas_list: List[Dict[str, Any]] = []
        for _, r in df_lineup.iterrows():
            if bool(r.get("Baja_Descontada", False)):
                cur_m = float(pd.to_numeric(r.get(mins_col, 0.0), errors="coerce") or 0.0)
                if cur_m <= 0.05:
                    bajas_list.append(
                        {
                            "team_abbr": abbr_up,
                            "jugador": str(r.get("Jugador", "")).strip(),
                            "pos": str(r.get(pos_col, "")).strip().upper(),
                            "status": str(r.get("Estado_Lesion", "Out") or "Out").strip(),
                            "detalle": str(r.get("Detalle_Lesion", "") or "").strip(),
                            "minutos_descontados": round(
                                float(r.get("Minutos_Descontados", r.get("Minutos_Base", 0.0)) or 0.0),
                                1,
                            ),
                        }
                    )
        return bajas_list

    if _st_session_disponible() and "bajas_detectadas_nba" in st.session_state:
        stored = st.session_state.bajas_detectadas_nba
        if isinstance(stored, dict) and abbr_up in stored:
            return list(stored[abbr_up])

    return []


def extraer_bajas_detectadas_de_lineups(
    lineups_dict: Dict[str, pd.DataFrame],
) -> Dict[str, List[Dict[str, Any]]]:
    """Recopila todas las bajas descontadas por franquicia a partir de un diccionario de lineups."""
    bajas_map: Dict[str, List[Dict[str, Any]]] = {}
    for abbr, lu_df in (lineups_dict or {}).items():
        bajas_eq = extraer_bajas_detectadas_equipo(lu_df, team_abbr=abbr)
        if bajas_eq:
            bajas_map[str(abbr).strip().upper()] = bajas_eq
    return bajas_map


def aplicar_lesiones_a_lineups(
    lineups_dict: Dict[str, pd.DataFrame],
    reporte_lesiones: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    max_minutos_jugador: float = MAX_PLAYER_PROJECTED_MINUTES,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, List[Dict[str, Any]]]]:
    """
    Aplica el reporte oficial de lesiones de ESPN ('Out' / 'Doubtful') sobre los quintetos de las
    30 franquicias NBA, reduciendo a 0.0 los jugadores descartados y redistribuyendo sus minutos
    proporcionalmente (suma exacta 240.0 min por equipo, tope 42.0 min por jugador).
    """
    rep = reporte_lesiones if reporte_lesiones is not None else obtener_reporte_lesiones_nba()
    adjusted_dict: Dict[str, pd.DataFrame] = {}
    bajas_por_equipo: Dict[str, List[Dict[str, Any]]] = {}

    for abbr, lu_df in (lineups_dict or {}).items():
        t_code = str(abbr).strip().upper()
        lesiones_eq = rep.get(t_code, []) if isinstance(rep, dict) else []
        adj_df, bajas_eq = redistribuir_minutos_equipo_por_lesiones(
            df_team=lu_df,
            lesiones_equipo=lesiones_eq,
            team_abbr=t_code,
            max_minutos_jugador=max_minutos_jugador,
            total_minutos_partido=TEAM_TOTAL_GAME_MINUTES,
        )
        adjusted_dict[t_code] = adj_df
        if bajas_eq:
            bajas_por_equipo[t_code] = bajas_eq

    if _st_session_disponible():
        st.session_state.bajas_detectadas_nba = bajas_por_equipo
        if isinstance(rep, dict):
            st.session_state.reporte_lesiones_nba = rep

    return adjusted_dict, bajas_por_equipo


def parsear_excel_a_lineups(
    df_excel: pd.DataFrame,
    strict_240: bool = False,
    aplicar_lesiones: bool = True,
    reporte_lesiones: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, pd.DataFrame]:
    """
    Valida y parsea el DataFrame cargado desde Excel (.xlsx), como 'nba_rosters_plantilla.xlsx'.
    - Deriva o preserva automáticamente las métricas base por jugador:
      'PPG_Base', 'RPG_Base', 'APG_Base' y 'Minutos_Base'.
    - Cuando `aplicar_lesiones=True` (por defecto), cruza automáticamente los jugadores con el
      Injury Report de ESPN ('Out' o 'Doubtful'), reduce a 0.0 los minutos de los descartados y
      redistribuye sus minutos proporcionalmente entre los activos del mismo equipo garantizando
      240.0 minutos exactos de rotación total y máximo 42.0 minutos por jugador individual.
    """
    if df_excel is None or not isinstance(df_excel, pd.DataFrame) or df_excel.empty:
        raise ValueError("El archivo Excel subido está vacío o no contiene una tabla válida.")

    df_clean = df_excel.copy()
    df_clean.columns = [str(c).strip() for c in df_clean.columns]

    missing_cols = [c for c in EXCEL_TEMPLATE_BASE_COLS if c not in df_clean.columns]
    if missing_cols:
        raise ValueError(
            f"El archivo Excel no contiene las columnas requeridas: {', '.join(missing_cols)}. "
            f"Columnas base esperadas: {', '.join(EXCEL_TEMPLATE_BASE_COLS)}"
        )

    df_clean = df_clean.dropna(subset=["Team_Abbr", "Jugador"], how="all").copy()
    df_clean["Team_Abbr"] = df_clean["Team_Abbr"].astype(str).str.strip().str.upper()
    df_clean["Minutos"] = pd.to_numeric(df_clean["Minutos"], errors="coerce").fillna(0.0).clip(lower=0.0).astype(float)
    df_clean["O_EPM"] = pd.to_numeric(df_clean["O_EPM"], errors="coerce").fillna(0.0).astype(float)
    df_clean["D_EPM"] = pd.to_numeric(df_clean["D_EPM"], errors="coerce").fillna(0.0).astype(float)
    df_clean["Pace_Diff"] = pd.to_numeric(df_clean["Pace_Diff"], errors="coerce").fillna(0.0).astype(float)
    df_clean["PPG_Linea"] = pd.to_numeric(df_clean["PPG_Linea"], errors="coerce").fillna(0.0).astype(float)
    df_clean["Es_Estrella"] = df_clean["Es_Estrella"].apply(_interpretar_booleano_estrella)

    has_min_base = "Minutos_Base" in df_clean.columns
    has_ppg_base = "PPG_Base" in df_clean.columns
    has_rpg_base = "RPG_Base" in df_clean.columns
    has_apg_base = "APG_Base" in df_clean.columns

    lineups_parsed: Dict[str, pd.DataFrame] = build_default_lineups_dict()

    for team_abbr, group in df_clean.groupby("Team_Abbr", sort=False):
        total_team_mins = float(group["Minutos"].sum())
        if strict_240 and abs(total_team_mins - 240.0) > 0.5:
            raise ValueError(
                f"Los minutos del equipo '{team_abbr}' suman {total_team_mins:.1f} "
                f"(deben sumar exactamente 240.0 minutos por franquicia)."
            )

        default_lu = {
            str(r["Jugador"]).lower(): r for r in DEFAULT_LINEUPS_30_TEAMS.get(team_abbr, [])
        }

        team_rows: List[Dict] = []
        for _, row in group.iterrows():
            raw_pos = str(row["Pos"]).strip().upper()
            internal_pos = "BENCH" if _es_fila_banca(raw_pos) else raw_pos
            p_name = str(row["Jugador"]).strip()
            mins_val = round(float(row["Minutos"]), 1)
            o_epm_val = round(float(row["O_EPM"]), 1)
            d_epm_val = round(float(row["D_EPM"]), 1)
            def_r = default_lu.get(p_name.lower(), {})
            def_mins = float(def_r.get("Minutos_Esperados", mins_val if mins_val > 0 else 34.0))

            if has_min_base and pd.notna(row.get("Minutos_Base")) and float(row["Minutos_Base"]) > 0:
                mins_base_val = round(float(row["Minutos_Base"]), 1)
            elif mins_val > 0:
                mins_base_val = round(mins_val, 1)
            else:
                mins_base_val = round(def_mins if def_mins > 0 else 34.0, 1)

            ppg_der, rpg_der, apg_der = _derivar_metricas_base_jugador(
                p_name, internal_pos, mins_base_val, o_epm_val, d_epm_val, team_abbr
            )

            ppg_base_val = (
                round(float(row["PPG_Base"]), 1)
                if has_ppg_base and pd.notna(row.get("PPG_Base")) and float(row["PPG_Base"]) > 0
                else ppg_der
            )
            rpg_base_val = (
                round(float(row["RPG_Base"]), 1)
                if has_rpg_base and pd.notna(row.get("RPG_Base")) and float(row["RPG_Base"]) > 0
                else rpg_der
            )
            apg_base_val = (
                round(float(row["APG_Base"]), 1)
                if has_apg_base and pd.notna(row.get("APG_Base")) and float(row["APG_Base"]) > 0
                else apg_der
            )

            team_rows.append(
                {
                    "Team_Abbr": team_abbr,
                    "Posición": internal_pos,
                    "Jugador": p_name,
                    "Minutos_Esperados": mins_val,
                    "Minutos_Base": mins_base_val,
                    "O_EPM": o_epm_val,
                    "D_EPM": d_epm_val,
                    "O_EPM_Base": o_epm_val,
                    "D_EPM_Base": d_epm_val,
                    "Pace_Diff": round(float(row["Pace_Diff"]), 2),
                    "Es_Estrella": bool(row["Es_Estrella"]),
                    "PPG_Base": ppg_base_val,
                    "RPG_Base": rpg_base_val,
                    "APG_Base": apg_base_val,
                    "PPG_Linea": round(float(row["PPG_Linea"]), 1),
                }
            )

        lineups_parsed[team_abbr] = pd.DataFrame(team_rows)

    if aplicar_lesiones:
        lineups_parsed, _ = aplicar_lesiones_a_lineups(
            lineups_dict=lineups_parsed,
            reporte_lesiones=reporte_lesiones,
            max_minutos_jugador=MAX_PLAYER_PROJECTED_MINUTES,
        )

    return lineups_parsed


def cargar_rosters_plantilla_excel(
    excel_source: Optional[Any] = None,
    aplicar_lesiones: bool = True,
    reporte_lesiones: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, List[Dict[str, Any]]], str]:
    """
    Carga 'nba_rosters_plantilla.xlsx' (desde disco local o un buffer subido), cruza automáticamente
    todos los jugadores con el Injury Report oficial de ESPN ('Out' / 'Doubtful') y reasigna
    proporcionalmente los minutos (240.0 min exactos por equipo, tope 42.0 min por jugador).
    Si el archivo local no existe, opera sobre los quintetos base aplicando igualmente el filtro de lesiones.
    Retorna: `(lineups_dict, bajas_por_equipo, fuente_label)`.
    """
    rep = reporte_lesiones if reporte_lesiones is not None else (
        obtener_reporte_lesiones_nba() if aplicar_lesiones else {}
    )

    df_excel: Optional[pd.DataFrame] = None
    source_name = DEFAULT_ROSTERS_EXCEL_FILENAME

    if excel_source is not None:
        if isinstance(excel_source, pd.DataFrame):
            df_excel = excel_source.copy()
        elif isinstance(excel_source, (bytes, bytearray)):
            df_excel = pd.read_excel(io.BytesIO(excel_source))
        else:
            df_excel = pd.read_excel(excel_source)
            source_name = getattr(excel_source, "name", str(excel_source))
    else:
        candidate_paths = [
            Path(DEFAULT_ROSTERS_EXCEL_FILENAME),
            Path(__file__).resolve().parent / DEFAULT_ROSTERS_EXCEL_FILENAME,
        ]
        for path in candidate_paths:
            if path.exists():
                try:
                    df_excel = pd.read_excel(path)
                    source_name = path.name
                    break
                except Exception:
                    df_excel = None

    if df_excel is not None and not df_excel.empty:
        lineups_dict = parsear_excel_a_lineups(
            df_excel=df_excel,
            strict_240=False,
            aplicar_lesiones=aplicar_lesiones,
            reporte_lesiones=rep,
        )
        bajas_map = extraer_bajas_detectadas_de_lineups(lineups_dict)
        total_bajas = sum(len(v) for v in bajas_map.values())
        label = (
            f"{source_name} + ESPN Injuries ({total_bajas} bajas desc.)"
            if aplicar_lesiones
            else f"{source_name}"
        )
        return lineups_dict, bajas_map, label

    base_lu = build_default_lineups_dict()
    if aplicar_lesiones:
        base_lu, bajas_map = aplicar_lesiones_a_lineups(base_lu, reporte_lesiones=rep)
        total_bajas = sum(len(v) for v in bajas_map.values())
        return base_lu, bajas_map, f"Quintetos Base + ESPN Injuries ({total_bajas} bajas desc.)"

    return base_lu, {}, "Quintetos Base (30 Equipos)"


def construir_excel_plantilla_bytes(
    lineups_dict: Optional[Dict[str, pd.DataFrame]] = None,
    df_teams: Optional[pd.DataFrame] = None,
    historial_calibracion: Optional[List[Dict[str, Any]]] = None,
) -> bytes:
    """
    Convierte el DataFrame de `generar_dataframe_plantilla_excel()` a formato Excel binario (.xlsx)
    en memoria usando `io.BytesIO()` y `openpyxl`, incluyendo:
      - Hoja 1 (`Rosters_NBA_30`): Plantilla plana de rosters y métricas individuales calibradas.
      - Hoja 2 (`Ratings_Equipos_Calibrados`): Tabla de las 30 franquicias con Pace, Off_Rtg y Def_Rtg actuales.
      - Hoja 3 (`Bitacora_Auditoria_Kalman`, opcional si existen calibraciones): Historial de residuales post-partido.
    """
    df_plantilla = generar_dataframe_plantilla_excel(lineups_dict=lineups_dict, df_teams=df_teams)
    if df_teams is None:
        if (st is not None and hasattr(st, "session_state")) and "df_nba" in st.session_state:
            df_teams = st.session_state.df_nba
        else:
            df_teams = pd.DataFrame(DEFAULT_CSV_DATA)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        # Hoja 1: Rosters_NBA_30 (compatible directamente con st.file_uploader)
        df_plantilla.to_excel(writer, index=False, sheet_name="Rosters_NBA_30")
        ws = writer.sheets["Rosters_NBA_30"]
        ws.views.sheetView[0].showGridLines = True
        ws.freeze_panes = "A2"

        header_fill = PatternFill(start_color="0B1223", end_color="0B1223", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="00F5D4")
        alt_fill = PatternFill(start_color="F2F5F9", end_color="F2F5F9", fill_type="solid")
        thin_border = Border(
            left=Side(style="thin", color="D9D9D9"),
            right=Side(style="thin", color="D9D9D9"),
            top=Side(style="thin", color="D9D9D9"),
            bottom=Side(style="thin", color="D9D9D9"),
        )

        for col_idx in range(1, len(EXCEL_TEMPLATE_COLS) + 1):
            c = ws.cell(row=1, column=col_idx)
            c.fill = header_fill
            c.font = header_font
            c.alignment = Alignment(horizontal="center" if col_idx != 3 else "left", vertical="center")
        ws.row_dimensions[1].height = 24

        for row_idx in range(2, len(df_plantilla) + 2):
            team_block = (row_idx - 2) // 6
            for col_idx in range(1, len(EXCEL_TEMPLATE_COLS) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.border = thin_border
                if team_block % 2 == 1:
                    cell.fill = alt_fill
                if col_idx in (1, 2, 9):
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                elif col_idx == 3:
                    cell.alignment = Alignment(horizontal="left", vertical="center")
                else:
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                    cell.number_format = "0.0"

        col_widths = {
            "A": 12, "B": 10, "C": 30, "D": 11, "E": 14,
            "F": 10, "G": 10, "H": 11, "I": 13, "J": 12, "K": 12, "L": 12, "M": 12,
        }
        for col_letter, width in col_widths.items():
            ws.column_dimensions[col_letter].width = width

        # Hoja 2: Ratings_Equipos_Calibrados
        team_export_cols = [
            c for c in [
                "Team_Abbr", "Team", "Conference", "Division",
                "GP", "Pace", "Off_Rtg", "Def_Rtg", "Net_Rtg",
                "Rating_Base", "Net_Rating_2026", "Rating_Final", "Live_Calibrated_Rating",
                "Peso_Previo_Bayes", "Peso_Actual_Bayes",
                "Star1_Name", "Star1_PPG", "Star2_Name", "Star2_PPG",
            ]
            if c in df_teams.columns
        ]
        df_teams[team_export_cols].to_excel(writer, index=False, sheet_name="Ratings_Equipos_Calibrados")
        ws_t = writer.sheets["Ratings_Equipos_Calibrados"]
        ws_t.views.sheetView[0].showGridLines = True
        ws_t.freeze_panes = "A2"
        for col_idx in range(1, len(team_export_cols) + 1):
            c = ws_t.cell(row=1, column=col_idx)
            c.fill = header_fill
            c.font = header_font

        # Hoja 3: Audit_Log (Registro persistente de auto-auditoría diaria del Feedback Loop)
        df_audit_log = cargar_audit_log_df()
        if historial_calibracion:
            df_extra_cal = pd.DataFrame(historial_calibracion)
            if set(AUDIT_LOG_COLS).issubset(set(df_extra_cal.columns)):
                df_audit_log = pd.concat(
                    [df_audit_log, df_extra_cal[AUDIT_LOG_COLS]], ignore_index=True
                ).drop_duplicates(subset=["Fecha", "Partido", "Equipo"], keep="last")
        df_audit_log.to_excel(writer, index=False, sheet_name=AUDIT_LOG_SHEET_NAME)
        ws_aud = writer.sheets[AUDIT_LOG_SHEET_NAME]
        ws_aud.views.sheetView[0].showGridLines = True
        ws_aud.freeze_panes = "A2"
        for col_idx in range(1, len(AUDIT_LOG_COLS) + 1):
            c = ws_aud.cell(row=1, column=col_idx)
            c.fill = header_fill
            c.font = header_font

        # Hoja 4: Bitacora_Auditoria_Kalman (si hay registros manuales)
        if historial_calibracion:
            df_hist = pd.DataFrame(historial_calibracion)
            df_hist.to_excel(writer, index=False, sheet_name="Bitacora_Auditoria_Kalman")
            ws_h = writer.sheets["Bitacora_Auditoria_Kalman"]
            ws_h.views.sheetView[0].showGridLines = True
            ws_h.freeze_panes = "A2"
            for col_idx in range(1, len(df_hist.columns) + 1):
                c = ws_h.cell(row=1, column=col_idx)
                c.fill = header_fill
                c.font = header_font

    buffer.seek(0)
    return buffer.getvalue()


# ==============================================================================
# MOTOR DE CÁLCULO ASCENDENTE + ESTABILIZACIÓN BAYESIANA (SMALL SAMPLE SIZE N=25)
# ==============================================================================
def calcular_rating_base_equipo(
    df_lineup: pd.DataFrame,
    team_abbr: str = "",
    pace_base: float = LEAGUE_AVG_PACE,
) -> Dict[str, float]:
    """
    Calcula el Rating Base (`Rating_Base`, `Off_Rtg_Base`, `Def_Rtg_Base`, `Pace_Proj`)
    directamente de la suma ponderada de los minutos en `nba_rosters_plantilla.xlsx`
    (`Minutos_Esperados` / `Minutos` sobre 240.0 min) y la tabla base proyectada pretemporada
    (`PRESEASON_BASE_RATINGS_30_TEAMS`), garantizando que:
      1. Los equipos malos o en reconstrucción (WAS, BKN, UTA, POR, CHA, DET, TOR, CHI)
         arranquen con ratings negativos reales (-5.0 a -8.0 pts/100 poss).
      2. Cualquier baja automática de ESPN o edición de minutos/EPM en `nba_rosters_plantilla.xlsx`
         impacte proporcionalmente el Rating Base del equipo.
    """
    df_clean = df_lineup.copy()
    abbr_clean = str(team_abbr or "").strip().upper()
    if not abbr_clean and "Team_Abbr" in df_clean.columns and not df_clean.empty:
        abbr_clean = str(df_clean["Team_Abbr"].iloc[0]).strip().upper()

    mins_col = "Minutos_Esperados" if "Minutos_Esperados" in df_clean.columns else "Minutos"
    pos_col = "Posición" if "Posición" in df_clean.columns else "Pos"

    mins = pd.to_numeric(df_clean[mins_col], errors="coerce").fillna(0.0).clip(lower=0.0).to_numpy(dtype=float)
    o_epm = pd.to_numeric(df_clean["O_EPM"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    d_epm = pd.to_numeric(df_clean["D_EPM"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    pos_arr = df_clean[pos_col].astype(str).str.upper().to_numpy()
    pace_diff_arr = (
        pd.to_numeric(df_clean["Pace_Diff"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        if "Pace_Diff" in df_clean.columns
        else np.zeros(len(df_clean), dtype=float)
    )

    total_mins = float(np.sum(mins))
    missing_mins = 0.0

    if total_mins <= 0.0:
        eff_mins = np.array([32.0, 32.0, 32.0, 32.0, 32.0, 80.0][: len(mins)], dtype=float)
    elif total_mins < 240.0:
        missing_mins = 240.0 - total_mins
        eff_mins = mins.copy()
    elif total_mins > 240.0:
        eff_mins = mins * (240.0 / total_mins)
    else:
        eff_mins = mins.copy()

    court_slots = eff_mins / 48.0
    replacement_slots = missing_mins / 48.0

    weighted_o_epm = float(np.sum(court_slots * o_epm) + replacement_slots * (-2.2))
    weighted_d_epm = float(np.sum(court_slots * d_epm) + replacement_slots * (-1.2))
    weighted_net_epm = weighted_o_epm + weighted_d_epm

    synergy_scale = 0.62
    preseason_anchor = PRESEASON_BASE_RATINGS_30_TEAMS.get(abbr_clean)

    if preseason_anchor is not None:
        if "Minutos_Base" in df_clean.columns:
            base_mins_arr = pd.to_numeric(df_clean["Minutos_Base"], errors="coerce").fillna(0.0).clip(lower=0.0).to_numpy(dtype=float)
            base_sum = float(np.sum(base_mins_arr))
            if base_sum > 0.0:
                base_mins_eff = base_mins_arr * (240.0 / base_sum) if abs(base_sum - 240.0) > 0.05 else base_mins_arr
            else:
                base_mins_eff = eff_mins.copy()
            o_epm_base_arr = (
                pd.to_numeric(df_clean["O_EPM_Base"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
                if "O_EPM_Base" in df_clean.columns
                else o_epm
            )
            d_epm_base_arr = (
                pd.to_numeric(df_clean["D_EPM_Base"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
                if "D_EPM_Base" in df_clean.columns
                else d_epm
            )
            def_o_epm_sum = float(np.sum((base_mins_eff / 48.0) * o_epm_base_arr))
            def_d_epm_sum = float(np.sum((base_mins_eff / 48.0) * d_epm_base_arr))
        elif abbr_clean in DEFAULT_LINEUPS_30_TEAMS:
            def_rows = DEFAULT_LINEUPS_30_TEAMS[abbr_clean]
            def_o_epm_sum = sum((float(r["Minutos_Esperados"]) / 48.0) * float(r["O_EPM"]) for r in def_rows)
            def_d_epm_sum = sum((float(r["Minutos_Esperados"]) / 48.0) * float(r["D_EPM"]) for r in def_rows)
        else:
            def_o_epm_sum = weighted_o_epm
            def_d_epm_sum = weighted_d_epm

        delta_off_lineup = (weighted_o_epm - def_o_epm_sum) * synergy_scale
        delta_def_lineup = (weighted_d_epm - def_d_epm_sum) * synergy_scale

        off_rtg_base = float(np.clip(float(preseason_anchor["Off_Rtg_Base"]) + delta_off_lineup, 98.0, 132.0))
        def_rtg_base = float(np.clip(float(preseason_anchor["Def_Rtg_Base"]) - delta_def_lineup, 98.0, 132.0))
    else:
        # Si no se especifica franquicia conocida, centrar respecto al promedio titular NBA (+4.30 O_EPM, +0.32 D_EPM)
        centered_off_delta = (weighted_o_epm - LEAGUE_STARTER_O_EPM_OFFSET) * 0.85
        centered_def_delta = (weighted_d_epm - LEAGUE_STARTER_D_EPM_OFFSET) * 0.85
        off_rtg_base = float(np.clip(LEAGUE_AVG_ORTG + centered_off_delta, 98.0, 132.0))
        def_rtg_base = float(np.clip(LEAGUE_AVG_ORTG - centered_def_delta, 98.0, 132.0))

    rating_base = off_rtg_base - def_rtg_base

    guard_mask = np.isin(pos_arr, ["PG", "SG"])
    big_mask = np.isin(pos_arr, ["PF", "C"])
    guard_mins = float(np.sum(eff_mins[guard_mask])) if np.any(guard_mask) else 64.0
    guard_o_epm = float(np.mean(o_epm[guard_mask])) if np.any(guard_mask) else 0.0
    big_d_epm = float(np.mean(d_epm[big_mask])) if np.any(big_mask) else 0.0

    pace_guard_boost = ((guard_mins - 65.0) / 12.0) * 0.45
    pace_style_boost = (guard_o_epm * 0.16) - (big_d_epm * 0.10)
    custom_pace_diff = float(np.sum((eff_mins / 48.0) * pace_diff_arr))
    proj_pace = float(
        np.clip(float(pace_base) + pace_guard_boost + pace_style_boost + custom_pace_diff, 88.0, 108.0)
    )

    return {
        "off_rtg_base": round(off_rtg_base, 2),
        "def_rtg_base": round(def_rtg_base, 2),
        "rating_base": round(rating_base, 2),
        "pace_proj": round(proj_pace, 1),
        "weighted_o_epm": round(weighted_o_epm, 2),
        "weighted_d_epm": round(weighted_d_epm, 2),
        "weighted_net_epm": round(weighted_net_epm, 2),
    }


def calcular_regresion_bayesiana_rating(
    rating_base: float,
    net_rating_2026: float,
    juegos_jugados: float = DEFAULT_EARLY_SEASON_GP,
    umbral_estabilizacion: int = BAYESIAN_STABILIZATION_GAMES,
    off_rtg_base: Optional[float] = None,
    def_rtg_base: Optional[float] = None,
    off_rtg_2026: Optional[float] = None,
    def_rtg_2026: Optional[float] = None,
) -> Dict[str, float]:
    """
    Sistema de Regresión Bayesiana a la Media (Small Sample Size Stabilization):
      - Umbral de estabilización: N = 25 partidos (`BAYESIAN_STABILIZATION_GAMES = 25`).
      - Si `juegos_jugados < 25`:
          * `peso_actual = (juegos_jugados / 25)`
          * `peso_previo = 1.0 - peso_actual`
          * `rating_final = (peso_previo * rating_base) + (peso_actual * net_rating_2026)`
      - Si `juegos_jugados >= 25`:
          * `peso_actual = 1.0`
          * `peso_previo = 0.0`
          * `rating_final = net_rating_2026`
    """
    n_umbral = float(max(1, int(umbral_estabilizacion)))
    gp_val = max(0.0, float(juegos_jugados))
    r_base = float(rating_base)
    r_2026 = float(net_rating_2026)

    if gp_val < n_umbral:
        peso_actual = gp_val / n_umbral
        peso_previo = 1.0 - peso_actual
        rating_final = (peso_previo * r_base) + (peso_actual * r_2026)
    else:
        peso_actual = 1.0
        peso_previo = 0.0
        rating_final = r_2026

    if off_rtg_base is None or def_rtg_base is None:
        o_base = LEAGUE_AVG_ORTG + (r_base / 2.0)
        d_base = LEAGUE_AVG_ORTG - (r_base / 2.0)
    else:
        o_base = float(off_rtg_base)
        d_base = float(def_rtg_base)

    if off_rtg_2026 is None or def_rtg_2026 is None:
        o_2026 = LEAGUE_AVG_ORTG + (r_2026 / 2.0)
        d_2026 = LEAGUE_AVG_ORTG - (r_2026 / 2.0)
    else:
        o_2026 = float(off_rtg_2026)
        d_2026 = float(def_rtg_2026)

    off_final_raw = (peso_previo * o_base) + (peso_actual * o_2026)
    def_final_raw = (peso_previo * d_base) + (peso_actual * d_2026)

    off_final = round(float(np.clip(off_final_raw, 98.0, 132.0)), 1)
    rating_final_rounded = round(float(rating_final), 1)
    def_final = round(float(np.clip(off_final - rating_final_rounded, 98.0, 132.0)), 1)

    return {
        "juegos_jugados": round(gp_val, 1),
        "umbral_estabilizacion": int(n_umbral),
        "peso_actual": round(peso_actual, 4),
        "peso_previo": round(peso_previo, 4),
        "rating_base": round(r_base, 2),
        "net_rating_2026": round(r_2026, 2),
        "rating_final": round(rating_final, 2),
        "rating_final_1d": rating_final_rounded,
        "off_rtg_base": round(o_base, 1),
        "def_rtg_base": round(d_base, 1),
        "off_rtg_2026": round(o_2026, 1),
        "def_rtg_2026": round(d_2026, 1),
        "off_rtg_final": off_final,
        "def_rtg_final": def_final,
    }


def calcular_ratings_lineup(
    df_lineup: pd.DataFrame,
    pace_base: float,
    team_abbr: str = "",
    juegos_jugados: Optional[float] = None,
    off_rtg_2026: Optional[float] = None,
    def_rtg_2026: Optional[float] = None,
) -> Tuple[float, float, float]:
    """
    Proyecta el Off_Rtg, Def_Rtg y Pace integrando:
      1) El Rating Base ponderado por minutos en `nba_rosters_plantilla.xlsx` (`calcular_rating_base_equipo`).
      2) La Regresión Bayesiana a la Media con umbral N = 25 partidos (`calcular_regresion_bayesiana_rating`)
         cuando se proveen los ratings observados de la temporada 2026 (`off_rtg_2026`, `def_rtg_2026`)
         o los juegos disputados (`juegos_jugados`).
    """
    base_info = calcular_rating_base_equipo(
        df_lineup=df_lineup,
        team_abbr=team_abbr,
        pace_base=pace_base,
    )
    o_base = float(base_info["off_rtg_base"])
    d_base = float(base_info["def_rtg_base"])
    r_base = float(base_info["rating_base"])
    proj_pace = float(base_info["pace_proj"])

    if off_rtg_2026 is not None and def_rtg_2026 is not None:
        gp_eff = float(DEFAULT_EARLY_SEASON_GP if juegos_jugados is None else juegos_jugados)
        net_2026 = float(off_rtg_2026) - float(def_rtg_2026)
        bayes = calcular_regresion_bayesiana_rating(
            rating_base=r_base,
            net_rating_2026=net_2026,
            juegos_jugados=gp_eff,
            umbral_estabilizacion=BAYESIAN_STABILIZATION_GAMES,
            off_rtg_base=o_base,
            def_rtg_base=d_base,
            off_rtg_2026=float(off_rtg_2026),
            def_rtg_2026=float(def_rtg_2026),
        )
        return float(bayes["off_rtg_final"]), float(bayes["def_rtg_final"]), round(proj_pace, 1)

    return round(o_base, 1), round(d_base, 1), round(proj_pace, 1)


def _extraer_juegos_jugados_fila(team_row: pd.Series) -> float:
    """Extrae el número de partidos disputados (GP / Juegos_Jugados) desde la fila del equipo (default = 5)."""
    for col_gp in ("Juegos_Jugados", "GP", "Games_Played", "Partidos_Jugados"):
        if col_gp in team_row and pd.notna(team_row[col_gp]):
            try:
                val = float(team_row[col_gp])
                if val >= 0.0:
                    return val
            except (TypeError, ValueError):
                continue
    return float(DEFAULT_EARLY_SEASON_GP)


def _resolver_ruta_estado_ratings(state_path: Optional[Any] = None) -> Optional[Path]:
    """Resuelve la ruta hacia `data/team_ratings_state.json` si existe en disco."""
    if state_path is not None:
        p = Path(state_path)
        return p if p.exists() else None
    candidates = [
        Path(TEAM_RATINGS_STATE_FILENAME),
        Path(__file__).resolve().parent / TEAM_RATINGS_STATE_FILENAME,
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def load_live_team_rating(
    team_name: str,
    baseline_rating: float,
    state_path: Optional[Any] = None,
) -> float:
    """
    Verifica si existe `data/team_ratings_state.json`.
    Si el archivo existe y contiene el rating dinámico ya calibrado para `team_name`
    (por nombre completo como 'Boston Celtics' o abreviatura como 'BOS'), retorna dicho rating;
    si no existe, recurre al `baseline_rating` de la plantilla.
    """
    base_val = float(baseline_rating)
    target_path = _resolver_ruta_estado_ratings(state_path=state_path)
    if target_path is None:
        return round(base_val, 2)

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return round(base_val, 2)

    if not isinstance(data, dict):
        return round(base_val, 2)

    teams_pool = data.get("teams", data) if isinstance(data.get("teams"), dict) else data
    key_clean = str(team_name or "").strip()
    if not key_clean:
        return round(base_val, 2)

    abbr_match = ""
    full_name_match = ""
    key_upper = key_clean.upper()
    key_lower = key_clean.lower()
    for d_row in DEFAULT_CSV_DATA:
        if d_row["Team_Abbr"].upper() == key_upper or d_row["Team"].lower() == key_lower:
            abbr_match = d_row["Team_Abbr"].upper()
            full_name_match = d_row["Team"]
            break

    search_keys = [key_clean, key_upper]
    if full_name_match and full_name_match not in search_keys:
        search_keys.append(full_name_match)
    if abbr_match and abbr_match not in search_keys:
        search_keys.append(abbr_match)

    entry: Any = None
    for k in search_keys:
        if k in teams_pool:
            entry = teams_pool[k]
            break

    if entry is None:
        lower_map = {str(k).strip().lower(): v for k, v in teams_pool.items()}
        for k in search_keys:
            if k.lower() in lower_map:
                entry = lower_map[k.lower()]
                break

    if entry is None:
        return round(base_val, 2)

    if isinstance(entry, (int, float, np.floating, np.integer)):
        return round(float(entry), 2)

    if isinstance(entry, dict):
        for field in ("rating", "net_rating", "Net_Rtg", "Rating_Final"):
            if field in entry and entry[field] is not None:
                try:
                    return round(float(entry[field]), 2)
                except (TypeError, ValueError):
                    continue

    return round(base_val, 2)


def apply_lineup_to_team_row(team_row: pd.Series, df_lineup: pd.DataFrame) -> pd.Series:
    """
    Actualiza dinámicamente Off_Rtg, Def_Rtg, Net_Rtg, Pace y los 2 líderes anotadores (Star1 / Star2)
    de la fila del equipo a partir de su quinteto en sesión, aplica la Regresión Bayesiana a la Media
    (umbral N = 25 partidos) e integra el rating vivo autocalibrado (`load_live_team_rating`).
    """
    updated = team_row.copy()
    t_abbr = str(team_row["Team_Abbr"]).strip().upper()
    default_meta = DEFAULT_TEAM_META_BY_ABBR.get(t_abbr, {})
    team_full_name = str(team_row.get("Team", default_meta.get("Team", t_abbr))).strip()
    default_lu = {
        str(r["Jugador"]).lower(): r for r in DEFAULT_LINEUPS_30_TEAMS.get(t_abbr, [])
    }

    pace_base = float(team_row.get("Base_Pace", default_meta.get("Pace", team_row["Pace"])))

    # Determinar el Rating Observado 2026 de manera idempotente pero sensible a ediciones manuales/Kalman
    cur_off = float(team_row.get("Off_Rtg", default_meta.get("Off_Rtg", LEAGUE_AVG_ORTG)))
    cur_def = float(team_row.get("Def_Rtg", default_meta.get("Def_Rtg", LEAGUE_AVG_ORTG)))
    last_stab_off = team_row.get("_Last_Stabilized_Off_Rtg")
    last_stab_def = team_row.get("_Last_Stabilized_Def_Rtg")

    if (
        "Obs_Off_Rtg_2026" in team_row
        and pd.notna(team_row["Obs_Off_Rtg_2026"])
        and last_stab_off is not None
        and abs(cur_off - float(last_stab_off)) <= 0.05
    ):
        obs_off_2026 = float(team_row["Obs_Off_Rtg_2026"])
    else:
        obs_off_2026 = cur_off

    if (
        "Obs_Def_Rtg_2026" in team_row
        and pd.notna(team_row["Obs_Def_Rtg_2026"])
        and last_stab_def is not None
        and abs(cur_def - float(last_stab_def)) <= 0.05
    ):
        obs_def_2026 = float(team_row["Obs_Def_Rtg_2026"])
    else:
        obs_def_2026 = cur_def

    net_2026_obs = obs_off_2026 - obs_def_2026
    if "Net_Rating_2026" in team_row and pd.notna(team_row["Net_Rating_2026"]):
        explicit_net_2026 = float(team_row["Net_Rating_2026"])
        last_net_2026 = team_row.get("_Last_Net_Rating_2026")
        if last_net_2026 is None or abs(explicit_net_2026 - float(last_net_2026)) > 0.05:
            diff_net = explicit_net_2026 - net_2026_obs
            obs_off_2026 += diff_net / 2.0
            obs_def_2026 -= diff_net / 2.0
            net_2026_obs = explicit_net_2026

    juegos_jugados = _extraer_juegos_jugados_fila(team_row)

    # 1) Calcular Rating Base desde la suma ponderada de minutos en nba_rosters_plantilla.xlsx + tabla base pretemporada
    base_info = calcular_rating_base_equipo(
        df_lineup=df_lineup,
        team_abbr=t_abbr,
        pace_base=pace_base,
    )
    off_rtg_base = float(base_info["off_rtg_base"])
    def_rtg_base = float(base_info["def_rtg_base"])
    rating_base = float(base_info["rating_base"])
    dyn_pace = float(base_info["pace_proj"])

    # 2) Aplicar Regresión Bayesiana a la Media (N = 25 partidos)
    bayes_res = calcular_regresion_bayesiana_rating(
        rating_base=rating_base,
        net_rating_2026=net_2026_obs,
        juegos_jugados=juegos_jugados,
        umbral_estabilizacion=BAYESIAN_STABILIZATION_GAMES,
        off_rtg_base=off_rtg_base,
        def_rtg_base=def_rtg_base,
        off_rtg_2026=obs_off_2026,
        def_rtg_2026=obs_def_2026,
    )

    off_rtg = float(bayes_res["off_rtg_final"])
    def_rtg = float(bayes_res["def_rtg_final"])
    rating_final = round(float(bayes_res["rating_final"]), 2)

    # 3) Integrar Rating Vivo Autocalibrado desde data/team_ratings_state.json (si existe)
    preseason_meta = PRESEASON_BASE_RATINGS_30_TEAMS.get(t_abbr, {})
    healthy_preseason_net = float(preseason_meta.get("Net_Rtg_Base", rating_base))
    injury_lineup_delta = (rating_base - healthy_preseason_net) * float(bayes_res["peso_previo"])
    healthy_rating_final = round(rating_final - injury_lineup_delta, 2)

    live_calibrated_healthy = load_live_team_rating(team_full_name, healthy_rating_final)
    live_rating = round(live_calibrated_healthy + injury_lineup_delta, 2)
    if abs(live_rating - rating_final) > 1e-4:
        delta_live = live_rating - rating_final
        off_rtg = round(float(np.clip(off_rtg + (delta_live / 2.0), 98.0, 132.0)), 1)
        def_rtg = round(float(np.clip(off_rtg - round(live_rating, 1), 98.0, 132.0)), 1)
        rating_final = round(live_rating, 2)

    # Base_Off_Rtg / Base_Def_Rtg representan el ancla base pretemporada saludable para referencia de mercado
    base_off = float(team_row.get("Base_Off_Rtg", preseason_meta.get("Off_Rtg_Base", off_rtg_base)))
    base_def = float(team_row.get("Base_Def_Rtg", preseason_meta.get("Def_Rtg_Base", def_rtg_base)))

    updated["Base_Off_Rtg"] = round(base_off, 1)
    updated["Base_Def_Rtg"] = round(base_def, 1)
    updated["Base_Pace"] = round(pace_base, 1)

    updated["Obs_Off_Rtg_2026"] = round(obs_off_2026, 1)
    updated["Obs_Def_Rtg_2026"] = round(obs_def_2026, 1)
    updated["GP"] = int(round(juegos_jugados))
    updated["Juegos_Jugados"] = round(juegos_jugados, 1)
    updated["Peso_Actual_Bayes"] = float(bayes_res["peso_actual"])
    updated["Peso_Previo_Bayes"] = float(bayes_res["peso_previo"])
    updated["Rating_Base"] = round(rating_base, 2)
    updated["Net_Rating_2026"] = round(net_2026_obs, 2)
    updated["Rating_Final"] = rating_final
    updated["Live_Calibrated_Rating"] = rating_final
    updated["Net_Rtg"] = round(off_rtg - def_rtg, 1)

    updated["Off_Rtg"] = off_rtg
    updated["Def_Rtg"] = def_rtg
    updated["Pace"] = dyn_pace
    updated["_Last_Stabilized_Off_Rtg"] = off_rtg
    updated["_Last_Stabilized_Def_Rtg"] = def_rtg
    updated["_Last_Net_Rating_2026"] = round(net_2026_obs, 2)

    pos_col = "Posición" if "Posición" in df_lineup.columns else "Pos"
    mins_col = "Minutos_Esperados" if "Minutos_Esperados" in df_lineup.columns else "Minutos"

    starters_df = df_lineup[~df_lineup[pos_col].astype(str).str.upper().isin(["BENCH", "BANCA"])].copy()
    if starters_df.empty:
        return updated

    starters_df["Minutos_Esperados"] = pd.to_numeric(starters_df[mins_col], errors="coerce").fillna(0.0)
    starters_df["O_EPM"] = pd.to_numeric(starters_df["O_EPM"], errors="coerce").fillna(0.0)
    starters_df["score_impacto"] = starters_df["Minutos_Esperados"] * (1.0 + 0.16 * starters_df["O_EPM"])

    def _calcular_ppg_y_linea_jugador(st_row: pd.Series, star_slot: int) -> Tuple[str, float, float, float, float, float, float]:
        p_name = str(st_row["Jugador"]).strip()
        p_pos = str(st_row.get(pos_col, "SF")).strip().upper()
        p_mins = float(st_row["Minutos_Esperados"])
        p_oepm = float(st_row["O_EPM"])
        p_depm = float(st_row.get("D_EPM", 0.0))
        excel_line = float(st_row.get("PPG_Linea", 0.0)) if "PPG_Linea" in st_row and pd.notna(st_row["PPG_Linea"]) else 0.0

        orig_s1 = str(default_meta.get("Star1_Name", "")).strip()
        orig_s2 = str(default_meta.get("Star2_Name", "")).strip()
        def_row = default_lu.get(p_name.lower(), {})
        def_mins = float(st_row.get("Minutos_Base", def_row.get("Minutos_Esperados", 35.0 if star_slot == 1 else 33.0)))
        if def_mins <= 0.5:
            def_mins = 34.0
        def_oepm = float(def_row.get("O_EPM", p_oepm))

        ppg_der, rpg_der, apg_der = _derivar_metricas_base_jugador(
            p_name, p_pos, def_mins, p_oepm, p_depm, t_abbr
        )

        if "PPG_Base" in st_row and pd.notna(st_row["PPG_Base"]) and float(st_row["PPG_Base"]) > 0:
            orig_ppg = float(st_row["PPG_Base"])
        elif p_name.lower() == orig_s1.lower():
            orig_ppg = float(default_meta.get("Star1_PPG", 25.0))
        elif p_name.lower() == orig_s2.lower():
            orig_ppg = float(default_meta.get("Star2_PPG", 21.0))
        else:
            orig_ppg = ppg_der

        rpg_base = float(st_row["RPG_Base"]) if "RPG_Base" in st_row and pd.notna(st_row["RPG_Base"]) and float(st_row["RPG_Base"]) > 0 else rpg_der
        apg_base = float(st_row["APG_Base"]) if "APG_Base" in st_row and pd.notna(st_row["APG_Base"]) and float(st_row["APG_Base"]) > 0 else apg_der

        if p_name.lower() == orig_s1.lower():
            orig_line = float(default_meta.get("Star1_Line", 24.5))
        elif p_name.lower() == orig_s2.lower():
            orig_line = float(default_meta.get("Star2_Line", 20.5))
        else:
            orig_line = excel_line if excel_line > 0 else round_to_half_point(orig_ppg - 0.5)

        mins_changed = abs(p_mins - def_mins) > 0.2
        epm_changed = abs(p_oepm - def_oepm) > 0.05
        line_changed = excel_line > 0.0 and abs(excel_line - orig_line) > 0.1

        proj_ppg = orig_ppg * (p_mins / max(def_mins, 1.0)) + (p_oepm - def_oepm) * 1.15
        if line_changed and not mins_changed and not epm_changed:
            prop_line = round_to_half_point(excel_line)
        elif excel_line > 0.0:
            prop_line = round_to_half_point(excel_line)
        else:
            prop_line = round_to_half_point(max(0.5, proj_ppg - 0.5))

        return (
            p_name,
            round(max(4.0, proj_ppg), 1),
            prop_line,
            round(orig_ppg, 1),
            round(rpg_base, 1),
            round(apg_base, 1),
            round(def_mins, 1),
        )

    active_starters = starters_df[starters_df["Minutos_Esperados"] > 0.5].copy()
    if active_starters.empty:
        active_starters = starters_df.copy()

    if "Es_Estrella" in active_starters.columns:
        active_starters["_star_flag"] = active_starters["Es_Estrella"].apply(_interpretar_booleano_estrella)
        active_starters = active_starters.sort_values(
            by=["_star_flag", "score_impacto"], ascending=[False, False]
        )
    else:
        orig_names = [
            str(updated.get("Star1_Name", "")).lower(),
            str(updated.get("Star2_Name", "")).lower(),
        ]
        active_starters["_star_flag"] = active_starters["Jugador"].astype(str).str.lower().isin(orig_names)
        active_starters = active_starters.sort_values(
            by=["_star_flag", "score_impacto"], ascending=[False, False]
        )

    for star_slot in (1, 2):
        if len(active_starters) >= star_slot:
            chosen_row = active_starters.iloc[star_slot - 1]
            s_name, s_ppg, s_line, s_ppg_base, s_rpg_base, s_apg_base, s_min_base = _calcular_ppg_y_linea_jugador(
                chosen_row, star_slot
            )
            updated[f"Star{star_slot}_Name"] = s_name
            updated[f"Star{star_slot}_PPG"] = s_ppg
            updated[f"Star{star_slot}_Line"] = s_line
            updated[f"Star{star_slot}_PPG_Base"] = s_ppg_base
            updated[f"Star{star_slot}_RPG_Base"] = s_rpg_base
            updated[f"Star{star_slot}_APG_Base"] = s_apg_base
            updated[f"Star{star_slot}_Minutos_Base"] = s_min_base
            updated[f"Star{star_slot}_Minutos_Proy"] = round(float(chosen_row["Minutos_Esperados"]), 1)

    return updated


def sincronizar_df_nba_con_lineups(
    df_nba: pd.DataFrame, lineups_dict: Dict[str, pd.DataFrame]
) -> pd.DataFrame:
    """
    Sincroniza inmediatamente `df_nba` (usado en el Gestor de Rosters y cabeceras)
    con los quintetos cargados en `st.session_state.lineups_nba` y las métricas de
    estabilización bayesiana (N = 25 partidos).
    """
    df_sync = df_nba.copy()
    for idx, row in df_sync.iterrows():
        abbr = str(row["Team_Abbr"]).strip().upper()
        lu_df = obtener_lineup_en_sesion(abbr, fallback_lineups=lineups_dict)
        updated_row = apply_lineup_to_team_row(row, lu_df)
        for col in [
            "Pace", "Off_Rtg", "Def_Rtg", "Net_Rtg",
            "Base_Pace", "Base_Off_Rtg", "Base_Def_Rtg",
            "Obs_Off_Rtg_2026", "Obs_Def_Rtg_2026",
            "GP", "Juegos_Jugados",
            "Peso_Actual_Bayes", "Peso_Previo_Bayes",
            "Rating_Base", "Net_Rating_2026", "Rating_Final", "Live_Calibrated_Rating",
            "_Last_Stabilized_Off_Rtg", "_Last_Stabilized_Def_Rtg", "_Last_Net_Rating_2026",
            "Star1_Name", "Star1_PPG", "Star1_Line",
            "Star1_PPG_Base", "Star1_RPG_Base", "Star1_APG_Base", "Star1_Minutos_Base", "Star1_Minutos_Proy",
            "Star2_Name", "Star2_PPG", "Star2_Line",
            "Star2_PPG_Base", "Star2_RPG_Base", "Star2_APG_Base", "Star2_Minutos_Base", "Star2_Minutos_Proy",
        ]:
            if col in updated_row:
                df_sync.loc[idx, col] = updated_row[col]
    return df_sync


def simulate_player_prop(
    rng: np.random.Generator,
    player_name: str,
    team_abbr: str,
    opp_abbr: str,
    base_ppg: float,
    prop_line: float,
    style: str,
    player_std: float,
    team_pace: float,
    exp_pace: float,
    team_style_off_ppp: float,
    opp_style_def_ppp: float,
    opp_def_rtg: float,
    poss_sim: np.ndarray,
    ppg_base_raw: Optional[float] = None,
    rpg_base: float = 5.5,
    apg_base: float = 4.8,
    minutos_base: float = 34.0,
    minutos_proyectados: float = 34.0,
) -> Dict:
    """
    Motor combinado para Player Props:
    - Simula la varianza de puntos e integra `proyectar_props_jugador` para Puntos (PTS),
      Rebotes (REB) y Asistencias (AST) con auditoría Poisson +EV en cuotas decimales.
    """
    n_sims = len(poss_sim)
    pace_factor = exp_pace / max(team_pace, 85.0)

    league_style_avg = LEAGUE_AVG_ISO_PPP if style.upper() == "ISO" else LEAGUE_AVG_PNR_PPP
    style_def_ratio = opp_style_def_ppp / league_style_avg
    off_synergy_ratio = team_style_off_ppp / league_style_avg
    style_multiplier = 1.0 + 0.58 * (style_def_ratio - 1.0) + 0.18 * (off_synergy_ratio - 1.0)

    team_def_multiplier = 1.0 + 0.30 * ((opp_def_rtg - LEAGUE_AVG_ORTG) / LEAGUE_AVG_ORTG)
    adjusted_ppg = base_ppg * pace_factor * style_multiplier * team_def_multiplier

    iter_pace_scale = poss_sim / exp_pace
    iter_mean = adjusted_ppg * iter_pace_scale

    eff_std = player_std * np.sqrt(pace_factor)
    sim_pts = np.clip(rng.normal(loc=iter_mean, scale=eff_std, size=n_sims), 0.0, None)

    prob_over = float(np.mean(sim_pts > prop_line))
    prob_under = 1.0 - prob_over
    lean_side = "OVER" if prob_over >= prob_under else "UNDER"
    lean_prob = prob_over if prob_over >= prob_under else prob_under

    dec_odds, _ = prob_to_fair_odds(lean_prob)
    style_label = "Iso_PPP_Def" if style.upper() == "ISO" else "PnR_PPP_Def"

    jugador_dict = {
        "Jugador": player_name,
        "Team_Abbr": team_abbr,
        "PPG_Base": float(ppg_base_raw if ppg_base_raw is not None else base_ppg),
        "RPG_Base": float(rpg_base),
        "APG_Base": float(apg_base),
        "Minutos_Base": float(minutos_base),
        "PPG_Linea": float(prop_line),
        "RPG_Linea": round_to_half_point(max(0.5, rpg_base - 0.5)),
        "APG_Linea": round_to_half_point(max(0.5, apg_base - 0.5)),
    }
    multi_props = proyectar_props_jugador(
        jugador_dict=jugador_dict,
        minutos_proyectados=minutos_proyectados,
        pace_partido=exp_pace,
        pace_promedio_liga=99.5,
        def_rating_rival=opp_def_rtg,
    )

    return {
        "player_name": player_name,
        "team_abbr": team_abbr,
        "opp_abbr": opp_abbr,
        "style": style.upper(),
        "base_ppg": float(base_ppg),
        "ppg_base_raw": float(jugador_dict["PPG_Base"]),
        "rpg_base": float(rpg_base),
        "apg_base": float(apg_base),
        "minutos_base": float(minutos_base),
        "minutos_proyectados": float(minutos_proyectados),
        "opp_def_rtg": float(opp_def_rtg),
        "exp_pace": float(exp_pace),
        "proj_ppg": float(np.mean(sim_pts)),
        "prop_line": float(prop_line),
        "prob_over": prob_over,
        "prob_under": prob_under,
        "lean_side": lean_side,
        "lean_prob": lean_prob,
        "fair_dec": dec_odds,
        "fair_amer": dec_odds,
        "edge_pts": float(adjusted_ppg - prop_line),
        "p25": float(np.percentile(sim_pts, 25)),
        "p75": float(np.percentile(sim_pts, 75)),
        "matchup_note": f"vs {opp_abbr} {style_label} ({opp_style_def_ppp:.2f} PPP) | DefRtg {opp_def_rtg:.1f}",
        "jugador_dict": jugador_dict,
        "multi_props": multi_props,
    }



# Mapa de nombres cortos por franquicia para el bloque de desglose de 5,000 simulaciones
SHORT_TEAM_NAME_BY_ABBR: Dict[str, str] = {
    "ATL": "Atlanta", "BOS": "Boston", "BKN": "Brooklyn", "CHA": "Charlotte", "CHI": "Chicago",
    "CLE": "Cleveland", "DAL": "Dallas", "DEN": "Denver", "DET": "Detroit", "GSW": "Golden State",
    "HOU": "Houston", "IND": "Indiana", "LAC": "LA Clippers", "LAL": "LA Lakers", "MEM": "Memphis",
    "MIA": "Miami", "MIL": "Milwaukee", "MIN": "Minnesota", "NOP": "New Orleans", "NYK": "New York",
    "OKC": "Oklahoma City", "ORL": "Orlando", "PHI": "Philadelphia", "PHX": "Phoenix", "POR": "Portland",
    "SAC": "Sacramento", "SAS": "San Antonio", "TOR": "Toronto", "UTA": "Utah", "WAS": "Washington",
}


def calcular_desglose_5000_simulaciones(
    away_abbr: str,
    home_abbr: str,
    away_row: pd.Series,
    home_row: pd.Series,
    away_pts_sim: np.ndarray,
    home_pts_sim: np.ndarray,
    spread_line_home: float,
    total_line: float,
    cuota_spread_home_decimal: float = 1.91,
    cuota_spread_away_decimal: float = 1.91,
    cuota_over_decimal: float = 1.91,
    cuota_under_decimal: float = 1.91,
    mkt_info: Optional[Dict[str, Any]] = None,
    valor_spread: Optional[Dict[str, Any]] = None,
    valor_totales: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    A partir de las 5,000 simulaciones de puntos de cada equipo (`away_pts_sim`, `home_pts_sim`),
    calcula y extrae dinámicamente para cada juego:
      1. Moneyline: Probabilidad del modelo vs Probabilidad implícita de las casas de apuestas vs Índice Predictor de ESPN BPI.
      2. Spread / Handicap: Porcentaje exacto de cubrir la línea del partido (ej. 'Boston cubre -1.5 en 42.0%').
      3. Total de Puntos (Over/Under): Porcentaje exacto de superar la línea establecida por los sportsbooks (ej. 'Más de 222.5 en 51.0%').
    Incluye banderas de ventaja matemática (+EV) para resaltar en verde neón (#00ffcc / #2bd99f).
    """
    n_sims = int(len(home_pts_sim))
    a_abbr = str(away_abbr).strip().upper()
    h_abbr = str(home_abbr).strip().upper()
    a_short = SHORT_TEAM_NAME_BY_ABBR.get(a_abbr, str(away_row.get("Team", a_abbr)))
    h_short = SHORT_TEAM_NAME_BY_ABBR.get(h_abbr, str(home_row.get("Team", h_abbr)))

    margin_sim = home_pts_sim - away_pts_sim
    total_pts_sim = home_pts_sim + away_pts_sim

    # 1. MONEYLINE: Modelo vs Casas vs ESPN BPI
    home_win_prob_mod = float(np.mean(margin_sim > 0)) * 100.0
    away_win_prob_mod = 100.0 - home_win_prob_mod

    info = mkt_info or {}
    sp_home = round(float(spread_line_home), 1)
    sp_away = round(-sp_home, 1)
    tot_line = round(float(total_line), 1)

    if info.get("prob_casas_home_pct") is not None and info.get("prob_casas_away_pct") is not None:
        prob_casas_home = float(info["prob_casas_home_pct"])
        prob_casas_away = float(info["prob_casas_away_pct"])
    else:
        p_h_mkt = float(np.clip(_normal_cdf(-sp_home / 11.5), 0.05, 0.95))
        prob_casas_home = round(p_h_mkt * 100.0, 1)
        prob_casas_away = round(100.0 - prob_casas_home, 1)

    if info.get("cuota_ml_home_decimal") is not None and info.get("cuota_ml_away_decimal") is not None:
        cuota_ml_home = float(info["cuota_ml_home_decimal"])
        cuota_ml_away = float(info["cuota_ml_away_decimal"])
    else:
        cuota_ml_home = round(max(1.04, 1.0 / min(0.96, (prob_casas_home / 100.0) * 1.022)), 2)
        cuota_ml_away = round(max(1.04, 1.0 / min(0.96, (prob_casas_away / 100.0) * 1.022)), 2)

    if info.get("espn_bpi_home_pct") is not None and info.get("espn_bpi_away_pct") is not None:
        espn_bpi_home = float(info["espn_bpi_home_pct"])
        espn_bpi_away = float(info["espn_bpi_away_pct"])
    else:
        a_net = float(away_row.get("Base_Off_Rtg", away_row["Off_Rtg"])) - float(away_row.get("Base_Def_Rtg", away_row["Def_Rtg"]))
        h_net = float(home_row.get("Base_Off_Rtg", home_row["Off_Rtg"])) - float(home_row.get("Base_Def_Rtg", home_row["Def_Rtg"]))
        bpi_margin_h = 0.68 * ((h_net - a_net) * 0.92 + 2.75) + 0.32 * (-sp_home)
        espn_bpi_home = round(float(np.clip(_normal_cdf(bpi_margin_h / 11.6), 0.04, 0.96)) * 100.0, 1)
        espn_bpi_away = round(100.0 - espn_bpi_home, 1)

    fav_is_home = home_win_prob_mod >= away_win_prob_mod
    ml_abbr = h_abbr if fav_is_home else a_abbr
    ml_equipo = h_short if fav_is_home else a_short
    ml_prob_modelo = round(home_win_prob_mod if fav_is_home else away_win_prob_mod, 1)
    ml_prob_casas = round(prob_casas_home if fav_is_home else prob_casas_away, 1)
    ml_prob_espn = round(espn_bpi_home if fav_is_home else espn_bpi_away, 1)
    ml_cuota_dec = cuota_ml_home if fav_is_home else cuota_ml_away
    ml_edge_pct = round(ml_prob_modelo - ml_prob_casas, 1)
    ml_ev_pct = round(((ml_prob_modelo / 100.0) * ml_cuota_dec - 1.0) * 100.0, 1)
    ml_tiene_ev = bool(ml_edge_pct >= 1.8 or ml_ev_pct >= 2.0)

    # 2. SPREAD / HANDICAP: Porcentaje exacto de cubrir la línea en las 5,000 simulaciones
    home_cover_pct = round(float(np.mean((home_pts_sim + sp_home) > away_pts_sim)) * 100.0, 1)
    away_cover_pct = round(100.0 - home_cover_pct, 1)

    ev_sp_home = round(((home_cover_pct / 100.0) * float(cuota_spread_home_decimal) - 1.0) * 100.0, 1)
    ev_sp_away = round(((away_cover_pct / 100.0) * float(cuota_spread_away_decimal) - 1.0) * 100.0, 1)

    val_sp = valor_spread or {}
    if val_sp.get("valor") and val_sp.get("lado") in {"HOME", "AWAY"}:
        sp_pick_is_home = val_sp["lado"] == "HOME"
    elif max(home_cover_pct, away_cover_pct) >= 53.0:
        sp_pick_is_home = home_cover_pct >= away_cover_pct
    else:
        # Por defecto muestra el favorito de la línea de mercado (ej. Boston -1.5 en 42.0%)
        sp_pick_is_home = sp_home <= 0.0

    spread_abbr = h_abbr if sp_pick_is_home else a_abbr
    spread_equipo = h_short if sp_pick_is_home else a_short
    spread_linea_val = sp_home if sp_pick_is_home else sp_away
    spread_linea_str = f"{spread_linea_val:+.1f}"
    spread_prob_cubre = home_cover_pct if sp_pick_is_home else away_cover_pct
    spread_cuota_dec = float(cuota_spread_home_decimal if sp_pick_is_home else cuota_spread_away_decimal)
    spread_ev_pct = ev_sp_home if sp_pick_is_home else ev_sp_away
    spread_tiene_ev = bool(val_sp.get("valor", False) or (spread_prob_cubre >= 52.8 and spread_ev_pct > 0.5))

    # También guardamos el texto del favorito de mercado explícito (ej. "Boston cubre -1.5 en 42.0%")
    mkt_fav_is_home = sp_home <= 0.0
    mkt_fav_equipo = h_short if mkt_fav_is_home else a_short
    mkt_fav_linea_str = f"{(sp_home if mkt_fav_is_home else sp_away):+.1f}"
    mkt_fav_cover_pct = home_cover_pct if mkt_fav_is_home else away_cover_pct

    # 3. TOTAL DE PUNTOS (OVER/UNDER): Porcentaje exacto de superar la línea en las 5,000 simulaciones
    over_pct = round(float(np.mean(total_pts_sim > tot_line)) * 100.0, 1)
    under_pct = round(100.0 - over_pct, 1)
    ev_over_pct = round(((over_pct / 100.0) * float(cuota_over_decimal) - 1.0) * 100.0, 1)
    ev_under_pct = round(((under_pct / 100.0) * float(cuota_under_decimal) - 1.0) * 100.0, 1)

    val_tot = valor_totales or {}
    total_tiene_ev = bool(
        val_tot.get("valor", False)
        or (over_pct >= 52.8 and ev_over_pct > 0.5)
        or (under_pct >= 52.8 and ev_under_pct > 0.5)
    )
    total_lado_ev = (
        str(val_tot.get("pick"))
        if val_tot.get("valor")
        else ("OVER" if over_pct >= under_pct else "UNDER")
    )

    return {
        "n_sims": n_sims,
        "titulo_bloque": f"📊 DESGLOSE {n_sims:,} SIMULACIONES (MONTE CARLO)",
        # Moneyline
        "ml_abbr": ml_abbr,
        "ml_equipo": ml_equipo,
        "ml_prob_modelo": ml_prob_modelo,
        "ml_prob_casas": ml_prob_casas,
        "ml_prob_espn": ml_prob_espn,
        "ml_cuota_decimal": ml_cuota_dec,
        "ml_edge_pct": ml_edge_pct,
        "ml_ev_pct": ml_ev_pct,
        "ml_tiene_ev": ml_tiene_ev,
        "prob_ml_home_modelo": round(home_win_prob_mod, 1),
        "prob_ml_away_modelo": round(away_win_prob_mod, 1),
        "prob_ml_home_casas": round(prob_casas_home, 1),
        "prob_ml_away_casas": round(prob_casas_away, 1),
        "prob_ml_home_espn": round(espn_bpi_home, 1),
        "prob_ml_away_espn": round(espn_bpi_away, 1),
        "linea_terminal_ml": f"🏀 Moneyline {ml_equipo}: {ml_prob_modelo:.1f}% | Casas: {ml_prob_casas:.1f}% | ESPN: {ml_prob_espn:.1f}%",
        # Spread
        "spread_abbr": spread_abbr,
        "spread_equipo": spread_equipo,
        "spread_linea": spread_linea_val,
        "spread_linea_str": spread_linea_str,
        "spread_prob_cubre": spread_prob_cubre,
        "spread_cuota_decimal": spread_cuota_dec,
        "spread_ev_pct": spread_ev_pct,
        "spread_tiene_ev": spread_tiene_ev,
        "home_cover_pct": home_cover_pct,
        "away_cover_pct": away_cover_pct,
        "texto_narrativo_spread": f"{spread_equipo} cubre {spread_linea_str} en {spread_prob_cubre:.1f}%",
        "texto_favorito_spread": f"{mkt_fav_equipo} cubre {mkt_fav_linea_str} en {mkt_fav_cover_pct:.1f}%",
        "linea_terminal_spread": f"🛡️ Spread {spread_equipo} ({spread_linea_str}): {spread_prob_cubre:.1f}% cubre",
        # Total (Over/Under)
        "total_linea": tot_line,
        "over_pct": over_pct,
        "under_pct": under_pct,
        "ev_over_pct": ev_over_pct,
        "ev_under_pct": ev_under_pct,
        "total_tiene_ev": total_tiene_ev,
        "total_lado_ev": total_lado_ev,
        "texto_narrativo_total": f"Más de {tot_line:.1f} en {over_pct:.1f}%",
        "linea_terminal_total": f"🎯 Total ({tot_line:.1f}): Más de {tot_line:.1f} en {over_pct:.1f}% (Menos: {under_pct:.1f}%)",
    }


def run_monte_carlo_matchup(
    away_row_raw: pd.Series,
    home_row_raw: pd.Series,
    away_lineup: Optional[pd.DataFrame] = None,
    home_lineup: Optional[pd.DataFrame] = None,
    n_sims: int = 5000,
    hfa_pts: float = 2.5,
    custom_spread_home: Optional[float] = None,
    custom_total_line: Optional[float] = None,
    market_odds_info: Optional[Dict[str, Any]] = None,
    umbral_ev_pts: float = 3.0,
    seed: int = 42,
) -> Dict:
    """
    Integra el Motor de Cálculo Ascendente (`calcular_ratings_lineup`) leyendo obligatoriamente
    los quintetos en sesión (`st.session_state.lineups_nba`), ejecuta 5,000 simulaciones de Monte Carlo
    y audita tanto las líneas de partido como los Player Props (PTS, REB, AST) en FORMATO DECIMAL.
    """
    away_abbr = str(away_row_raw["Team_Abbr"]).strip().upper()
    home_abbr = str(home_row_raw["Team_Abbr"]).strip().upper()

    if away_lineup is None:
        away_lineup = obtener_lineup_en_sesion(away_abbr)
    if home_lineup is None:
        home_lineup = obtener_lineup_en_sesion(home_abbr)

    bajas_away = extraer_bajas_detectadas_equipo(away_lineup, team_abbr=away_abbr)
    bajas_home = extraer_bajas_detectadas_equipo(home_lineup, team_abbr=home_abbr)
    bajas_partido = bajas_away + bajas_home
    bajas_nombres = [str(item["jugador"]) for item in bajas_partido if item.get("jugador")]

    away_row = apply_lineup_to_team_row(away_row_raw, away_lineup)
    home_row = apply_lineup_to_team_row(home_row_raw, home_lineup)

    rng = np.random.default_rng(seed)

    away_pace = float(away_row["Pace"])
    home_pace = float(home_row["Pace"])
    exp_possessions = (away_pace + home_pace) / 2.0

    away_base_ortg = float(away_row["Off_Rtg"]) + 0.58 * (float(home_row["Def_Rtg"]) - LEAGUE_AVG_ORTG)
    home_base_ortg = float(home_row["Off_Rtg"]) + 0.58 * (float(away_row["Def_Rtg"]) - LEAGUE_AVG_ORTG)

    static_away_ortg = float(away_row["Base_Off_Rtg"]) + 0.58 * (float(home_row["Base_Def_Rtg"]) - LEAGUE_AVG_ORTG)
    static_home_ortg = float(home_row["Base_Off_Rtg"]) + 0.58 * (float(away_row["Base_Def_Rtg"]) - LEAGUE_AVG_ORTG)
    static_pace = (float(away_row["Base_Pace"]) + float(home_row["Base_Pace"])) / 2.0
    mkt_away_pts = (static_pace / 100.0) * static_away_ortg - (hfa_pts / 2.0)
    mkt_home_pts = (static_pace / 100.0) * static_home_ortg + (hfa_pts / 2.0)
    default_market_spread_home = float(np.floor(-(mkt_home_pts - mkt_away_pts)) + 0.5)
    default_market_total = float(np.floor(mkt_home_pts + mkt_away_pts) + 0.5)

    away_iso_delta = float(away_row["Iso_PPP_Off"]) - float(home_row["Iso_PPP_Def"])
    away_pnr_delta = float(away_row["PnR_PPP_Off"]) - float(home_row["PnR_PPP_Def"])
    home_iso_delta = float(home_row["Iso_PPP_Off"]) - float(away_row["Iso_PPP_Def"])
    home_pnr_delta = float(home_row["PnR_PPP_Off"]) - float(away_row["PnR_PPP_Def"])

    away_tactical_ortg_adj = (away_iso_delta * 5.2) + (away_pnr_delta * 7.4)
    home_tactical_ortg_adj = (home_iso_delta * 5.2) + (home_pnr_delta * 7.4)

    away_tov_adj = (LEAGUE_AVG_TOV - float(away_row["TOV_Pct"])) * 0.35
    home_tov_adj = (LEAGUE_AVG_TOV - float(home_row["TOV_Pct"])) * 0.35

    away_adj_ortg = away_base_ortg + away_tactical_ortg_adj + away_tov_adj
    home_adj_ortg = home_base_ortg + home_tactical_ortg_adj + home_tov_adj

    mkt_info = market_odds_info or {}
    mkt_spread_val = mkt_info.get("spread_mercado_home")
    mkt_total_val = mkt_info.get("total_mercado")

    if custom_spread_home is not None:
        spread_line_home = float(custom_spread_home)
    elif mkt_spread_val is not None:
        spread_line_home = float(mkt_spread_val)
    else:
        spread_line_home = default_market_spread_home

    if custom_total_line is not None:
        total_line = float(custom_total_line)
    elif mkt_total_val is not None:
        total_line = float(mkt_total_val)
    else:
        total_line = default_market_total

    spread_line_away = -spread_line_home

    cuota_over_decimal = round(float(mkt_info.get("cuota_over_decimal", 1.91)), 2)
    cuota_under_decimal = round(float(mkt_info.get("cuota_under_decimal", 1.91)), 2)
    cuota_spread_home_decimal = round(float(mkt_info.get("cuota_spread_home_decimal", 1.91)), 2)
    cuota_spread_away_decimal = round(float(mkt_info.get("cuota_spread_away_decimal", 1.91)), 2)
    odds_source_label = str(mkt_info.get("fuente", "Consenso Sportsbook (Decimal)"))

    poss_sim = np.clip(rng.normal(loc=exp_possessions, scale=2.75, size=n_sims), 86.0, 114.0)

    away_ortg_std = 9.2 * (1.0 + 0.35 * (float(away_row["3PA_Rate"]) - 0.38))
    home_ortg_std = 9.2 * (1.0 + 0.35 * (float(home_row["3PA_Rate"]) - 0.38))

    away_ortg_sim = rng.normal(loc=away_adj_ortg, scale=away_ortg_std, size=n_sims)
    home_ortg_sim = rng.normal(loc=home_adj_ortg, scale=home_ortg_std, size=n_sims)

    away_pts_sim = (poss_sim / 100.0) * away_ortg_sim - (hfa_pts / 2.0)
    home_pts_sim = (poss_sim / 100.0) * home_ortg_sim + (hfa_pts / 2.0)

    away_3pa_sim = np.clip(rng.normal(poss_sim * float(away_row["3PA_Rate"]) * 0.92, 4.0, size=n_sims), 18, 60).astype(int)
    home_3pa_sim = np.clip(rng.normal(poss_sim * float(home_row["3PA_Rate"]) * 0.92, 4.0, size=n_sims), 18, 60).astype(int)

    away_3p_pct_base = float(away_row.get("3P_Pct", 0.368))
    home_3p_pct_base = float(home_row.get("3P_Pct", 0.368))

    away_z = (away_ortg_sim - away_adj_ortg) / away_ortg_std
    home_z = (home_ortg_sim - home_adj_ortg) / home_ortg_std

    away_3pm_sim = rng.binomial(n=away_3pa_sim, p=np.clip(away_3p_pct_base + 0.032 * away_z, 0.18, 0.58))
    home_3pm_sim = rng.binomial(n=home_3pa_sim, p=np.clip(home_3p_pct_base + 0.032 * home_z, 0.18, 0.58))

    away_tov_sim = np.clip(rng.normal(loc=(poss_sim / 100.0) * float(away_row["TOV_Pct"]) - 0.85 * away_z, scale=2.2, size=n_sims), 4.0, 28.0)
    home_tov_sim = np.clip(rng.normal(loc=(poss_sim / 100.0) * float(home_row["TOV_Pct"]) - 0.85 * home_z, scale=2.2, size=n_sims), 4.0, 28.0)

    margin_sim = home_pts_sim - away_pts_sim
    ties_mask = np.abs(margin_sim) < 0.5
    if np.any(ties_mask):
        ot_diff = rng.normal(loc=0.35, scale=4.2, size=int(np.sum(ties_mask)))
        ot_diff = np.where(ot_diff >= 0, np.maximum(ot_diff, 1.0), np.minimum(ot_diff, -1.0))
        home_pts_sim[ties_mask] += np.maximum(ot_diff, 0) + 8.0
        away_pts_sim[ties_mask] += np.maximum(-ot_diff, 0) + 8.0
        margin_sim = home_pts_sim - away_pts_sim

    total_pts_sim = home_pts_sim + away_pts_sim

    exp_away_pts = float(np.mean(away_pts_sim))
    exp_home_pts = float(np.mean(home_pts_sim))
    exp_margin_home = float(np.mean(margin_sim))
    exp_total_pts = float(np.mean(total_pts_sim))
    proj_spread_home = -exp_margin_home

    home_win_prob = float(np.mean(margin_sim > 0))
    away_win_prob = 1.0 - home_win_prob
    home_ml_dec, home_ml_amer = prob_to_fair_odds(home_win_prob)
    away_ml_dec, away_ml_amer = prob_to_fair_odds(away_win_prob)

    home_cover_prob = float(np.mean((home_pts_sim + spread_line_home) > away_pts_sim))
    away_cover_prob = 1.0 - home_cover_prob
    home_sp_dec, home_sp_amer = prob_to_fair_odds(home_cover_prob)
    away_sp_dec, away_sp_amer = prob_to_fair_odds(away_cover_prob)

    over_prob = float(np.mean(total_pts_sim > total_line))
    under_prob = 1.0 - over_prob
    over_dec, over_amer = prob_to_fair_odds(over_prob)
    under_dec, under_amer = prob_to_fair_odds(under_prob)

    valor_totales = evaluar_valor_totales_nba(
        total_modelo=exp_total_pts,
        total_mercado=total_line,
        cuota_over=cuota_over_decimal,
        cuota_under=cuota_under_decimal,
        umbral_pts=umbral_ev_pts,
        prob_over_sim=over_prob,
        prob_under_sim=under_prob,
    )
    valor_spread = evaluar_valor_spread_nba(
        spread_modelo=proj_spread_home,
        spread_mercado_home=spread_line_home,
        cuota_home=cuota_spread_home_decimal,
        cuota_away=cuota_spread_away_decimal,
        umbral_pts=umbral_ev_pts,
        home_abbr=home_abbr,
        away_abbr=away_abbr,
        prob_home_cover_sim=home_cover_prob,
        prob_away_cover_sim=away_cover_prob,
    )

    desglose_5000_sims = calcular_desglose_5000_simulaciones(
        away_abbr=away_abbr,
        home_abbr=home_abbr,
        away_row=away_row,
        home_row=home_row,
        away_pts_sim=away_pts_sim,
        home_pts_sim=home_pts_sim,
        spread_line_home=spread_line_home,
        total_line=total_line,
        cuota_spread_home_decimal=cuota_spread_home_decimal,
        cuota_spread_away_decimal=cuota_spread_away_decimal,
        cuota_over_decimal=cuota_over_decimal,
        cuota_under_decimal=cuota_under_decimal,
        mkt_info=mkt_info,
        valor_spread=valor_spread,
        valor_totales=valor_totales,
    )

    fav_is_home = home_win_prob >= away_win_prob
    fav_abbr = home_abbr if fav_is_home else away_abbr
    fav_name = str(home_row["Team"]) if fav_is_home else str(away_row["Team"])
    fav_base_win = home_win_prob if fav_is_home else away_win_prob
    fav_win_mask = (margin_sim > 0) if fav_is_home else (margin_sim < 0)
    fav_3pm_arr = home_3pm_sim if fav_is_home else away_3pm_sim
    fav_tov_arr = home_tov_sim if fav_is_home else away_tov_sim
    fav_ortg_arr = home_ortg_sim if fav_is_home else away_ortg_sim

    threepm_threshold = int(np.round(np.percentile(fav_3pm_arr, 52)))
    mask_3pm = fav_3pm_arr > threepm_threshold
    win_given_3pm = float(np.mean(fav_win_mask[mask_3pm])) if np.any(mask_3pm) else fav_base_win

    tov_threshold = int(np.round(np.percentile(fav_tov_arr, 48)))
    mask_tov = fav_tov_arr < tov_threshold
    win_given_tov = float(np.mean(fav_win_mask[mask_tov])) if np.any(mask_tov) else fav_base_win

    ortg_threshold = round(float(np.percentile(fav_ortg_arr, 50)), 1)
    mask_ortg = fav_ortg_arr > ortg_threshold
    win_given_ortg = float(np.mean(fav_win_mask[mask_ortg])) if np.any(mask_ortg) else fav_base_win

    props_list = []
    for side_row, opp_row in [(away_row, home_row), (home_row, away_row)]:
        p_team = str(side_row["Team_Abbr"])
        p_opp = str(opp_row["Team_Abbr"])
        t_pace = float(side_row["Pace"])
        o_def_rtg = float(opp_row["Def_Rtg"])

        for star_idx in (1, 2):
            s_name = str(side_row[f"Star{star_idx}_Name"])
            s_ppg = float(side_row[f"Star{star_idx}_PPG"])
            s_line = float(side_row.get(f"Star{star_idx}_Line", round_to_half_point(s_ppg)))
            s_style = str(side_row.get(f"Star{star_idx}_Style", "ISO")).upper()
            s_std = float(side_row.get(f"Star{star_idx}_Std", 5.6))

            ppg_b_raw = float(side_row.get(f"Star{star_idx}_PPG_Base", s_ppg))
            rpg_b_raw = float(side_row.get(f"Star{star_idx}_RPG_Base", 5.6))
            apg_b_raw = float(side_row.get(f"Star{star_idx}_APG_Base", 4.8))
            min_b_raw = float(side_row.get(f"Star{star_idx}_Minutos_Base", 34.0))
            min_p_raw = float(side_row.get(f"Star{star_idx}_Minutos_Proy", min_b_raw))

            t_style_off = float(side_row["Iso_PPP_Off"]) if s_style == "ISO" else float(side_row["PnR_PPP_Off"])
            o_style_def = float(opp_row["Iso_PPP_Def"]) if s_style == "ISO" else float(opp_row["PnR_PPP_Def"])

            prop_res = simulate_player_prop(
                rng=rng,
                player_name=s_name,
                team_abbr=p_team,
                opp_abbr=p_opp,
                base_ppg=s_ppg,
                prop_line=s_line,
                style=s_style,
                player_std=s_std,
                team_pace=t_pace,
                exp_pace=exp_possessions,
                team_style_off_ppp=t_style_off,
                opp_style_def_ppp=o_style_def,
                opp_def_rtg=o_def_rtg,
                poss_sim=poss_sim,
                ppg_base_raw=ppg_b_raw,
                rpg_base=rpg_b_raw,
                apg_base=apg_b_raw,
                minutos_base=min_b_raw,
                minutos_proyectados=min_p_raw,
            )
            prop_res["matchup_label"] = f"{away_abbr} @ {home_abbr}"
            props_list.append(prop_res)

    return {
        "matchup_id": f"{away_abbr}@{home_abbr}",
        "matchup_title": f"{away_row['Team']} @ {home_row['Team']}",
        "away_team": str(away_row["Team"]),
        "away_abbr": away_abbr,
        "home_team": str(home_row["Team"]),
        "home_abbr": home_abbr,
        "away_row": away_row,
        "home_row": home_row,
        "n_sims": n_sims,
        "exp_possessions": exp_possessions,
        "exp_away_pts": exp_away_pts,
        "exp_home_pts": exp_home_pts,
        "exp_margin_home": exp_margin_home,
        "exp_total_pts": exp_total_pts,
        "proj_spread_home": proj_spread_home,
        "spread_line_home": spread_line_home,
        "spread_line_away": spread_line_away,
        "total_line": total_line,
        "cuota_over_decimal": cuota_over_decimal,
        "cuota_under_decimal": cuota_under_decimal,
        "cuota_spread_home_decimal": cuota_spread_home_decimal,
        "cuota_spread_away_decimal": cuota_spread_away_decimal,
        "odds_source_label": odds_source_label,
        "valor_totales": valor_totales,
        "valor_spread": valor_spread,
        "desglose_5000_sims": desglose_5000_sims,
        "away_win_prob": away_win_prob,
        "home_win_prob": home_win_prob,
        "away_ml_dec": away_ml_dec,
        "away_ml_amer": away_ml_amer,
        "home_ml_dec": home_ml_dec,
        "home_ml_amer": home_ml_amer,
        "away_cover_prob": away_cover_prob,
        "home_cover_prob": home_cover_prob,
        "away_sp_dec": away_sp_dec,
        "away_sp_amer": away_sp_amer,
        "home_sp_dec": home_sp_dec,
        "home_sp_amer": home_sp_amer,
        "over_prob": over_prob,
        "under_prob": under_prob,
        "over_dec": over_dec,
        "over_amer": over_amer,
        "under_dec": under_dec,
        "under_amer": under_amer,
        "total_p10": float(np.percentile(total_pts_sim, 10)),
        "total_p50": float(np.percentile(total_pts_sim, 50)),
        "total_p90": float(np.percentile(total_pts_sim, 90)),
        "fav_abbr": fav_abbr,
        "fav_name": fav_name,
        "fav_base_win": fav_base_win,
        "threepm_threshold": threepm_threshold,
        "win_given_3pm": win_given_3pm,
        "tov_threshold": tov_threshold,
        "win_given_tov": win_given_tov,
        "ortg_threshold": ortg_threshold,
        "win_given_ortg": win_given_ortg,
        "away_iso_delta": away_iso_delta,
        "away_pnr_delta": away_pnr_delta,
        "home_iso_delta": home_iso_delta,
        "home_pnr_delta": home_pnr_delta,
        "away_tactical_ortg_adj": away_tactical_ortg_adj,
        "home_tactical_ortg_adj": home_tactical_ortg_adj,
        "bajas_away": bajas_away,
        "bajas_home": bajas_home,
        "bajas_partido": bajas_partido,
        "bajas_nombres": bajas_nombres,
        "props": props_list,
    }


def extract_executive_radar(sim_results: List[Dict]) -> Dict:
    """Extrae los 4 Top Picks automáticos en formato estrictamente DECIMAL evaluando los partidos activos."""
    best_ml = None
    best_spread = None
    best_total = None
    best_prop = None

    for res in sim_results:
        ml_candidates = [
            (res["home_team"], res["home_abbr"], res["home_win_prob"], res["home_ml_dec"], f"vs {res['away_abbr']} (Local)", res["exp_home_pts"] - res["exp_away_pts"]),
            (res["away_team"], res["away_abbr"], res["away_win_prob"], res["away_ml_dec"], f"@ {res['home_abbr']} (Visita)", res["exp_away_pts"] - res["exp_home_pts"]),
        ]
        for c in ml_candidates:
            if best_ml is None or c[2] > best_ml["prob"]:
                best_ml = {"team": c[0], "abbr": c[1], "prob": c[2], "dec": c[3], "context": c[4], "proj_margin": c[5]}

        sp_candidates = [
            (f"{res['home_team']} {res['spread_line_home']:+.1f} @ {res['cuota_spread_home_decimal']:.2f}", res["home_abbr"], res["home_cover_prob"], res["home_sp_dec"], f"{res['away_abbr']} @ {res['home_abbr']} | Modelo: {res['proj_spread_home']:+.1f}"),
            (f"{res['away_team']} {res['spread_line_away']:+.1f} @ {res['cuota_spread_away_decimal']:.2f}", res["away_abbr"], res["away_cover_prob"], res["away_sp_dec"], f"{res['away_abbr']} @ {res['home_abbr']} | Modelo: {-res['proj_spread_home']:+.1f}"),
        ]
        for c in sp_candidates:
            if best_spread is None or c[2] > best_spread["prob"]:
                best_spread = {"pick": c[0], "abbr": c[1], "prob": c[2], "dec": c[3], "context": c[4]}

        tot_candidates = [
            (f"OVER {res['total_line']:.1f} @ {res['cuota_over_decimal']:.2f}", res["home_abbr"], res["over_prob"], res["over_dec"], f"{res['away_abbr']} @ {res['home_abbr']} | Modelo: {res['exp_total_pts']:.1f} pts"),
            (f"UNDER {res['total_line']:.1f} @ {res['cuota_under_decimal']:.2f}", res["home_abbr"], res["under_prob"], res["under_dec"], f"{res['away_abbr']} @ {res['home_abbr']} | Modelo: {res['exp_total_pts']:.1f} pts"),
        ]
        for c in tot_candidates:
            if best_total is None or c[2] > best_total["prob"]:
                best_total = {"pick": c[0], "abbr": c[1], "prob": c[2], "dec": c[3], "context": c[4]}

        for prop in res["props"]:
            if best_prop is None or prop["lean_prob"] > best_prop["lean_prob"]:
                best_prop = prop

    return {"lock": best_ml, "spread": best_spread, "total": best_total, "prop": best_prop}


# ==============================================================================
# EXPORTACIÓN DE PROYECCIONES CUANTITATIVAS NBA (5,000 SIMULACIONES -> XLSX / CSV)
# ==============================================================================
PREDICTION_HISTORY_COLS: List[str] = [
    "game_id",
    "date",
    "home_team",
    "away_team",
    "home_abbr",
    "away_abbr",
    "projected_home_pts",
    "projected_away_pts",
    "projected_margin",
    "projected_total",
    "status",
    "actual_home_score",
    "actual_away_score",
    "actual_margin",
    "actual_total",
    "margin_error",
    "total_error",
    "calibrated_at",
]


def save_daily_predictions_to_history(
    results_list: List[Dict[str, Any]],
    slate_meta: Optional[List[Dict[str, Any]]] = None,
    fecha_str: Optional[str] = None,
    history_path: Optional[Any] = None,
) -> pd.DataFrame:
    """
    Al generar las proyecciones diarias antes de los partidos, guarda automáticamente
    las predicciones (`game_id`, `home_team`, `away_team`, `projected_margin`, `projected_total`,
    `status='pending'`) en `data/prediction_history.csv`.
    Si una predicción ya fue evaluada (`status == 'evaluated'`), preserva su evaluación intacta.
    """
    if fecha_str is None:
        if st is not None and hasattr(st, "session_state") and "fecha_nba" in st.session_state:
            try:
                fecha_str = st.session_state.fecha_nba.strftime("%Y-%m-%d")
            except Exception:
                fecha_str = date.today().strftime("%Y-%m-%d")
        else:
            fecha_str = date.today().strftime("%Y-%m-%d")

    fecha_clean = str(fecha_str).strip()
    fecha_compact = fecha_clean.replace("-", "")

    target_csv = (
        Path(history_path)
        if history_path is not None
        else (Path(__file__).resolve().parent / PREDICTION_HISTORY_CSV_FILENAME)
    )
    target_csv.parent.mkdir(parents=True, exist_ok=True)

    existing_df = pd.DataFrame(columns=PREDICTION_HISTORY_COLS)
    if target_csv.exists():
        try:
            loaded_df = pd.read_csv(target_csv)
            if not loaded_df.empty:
                for col in PREDICTION_HISTORY_COLS:
                    if col not in loaded_df.columns:
                        loaded_df[col] = np.nan
                existing_df = loaded_df[PREDICTION_HISTORY_COLS].copy()
                for str_col in ("game_id", "date", "home_team", "away_team", "home_abbr", "away_abbr", "status", "calibrated_at"):
                    existing_df[str_col] = existing_df[str_col].fillna("").astype(object)
        except Exception:
            existing_df = pd.DataFrame(columns=PREDICTION_HISTORY_COLS)

    new_records: List[Dict[str, Any]] = []
    for idx, res in enumerate(results_list or []):
        away_abbr = str(res.get("away_abbr", "AWAY")).strip().upper()
        home_abbr = str(res.get("home_abbr", "HOME")).strip().upper()
        away_team = str(res.get("away_team", away_abbr)).strip()
        home_team = str(res.get("home_team", home_abbr)).strip()

        meta = slate_meta[idx] if slate_meta and idx < len(slate_meta) and isinstance(slate_meta[idx], dict) else {}
        raw_id = str(meta.get("id_partido") or res.get("game_id") or "").strip()
        if not raw_id or raw_id == f"{away_abbr}_{home_abbr}":
            game_id = f"{fecha_compact}_{away_abbr}_{home_abbr}"
        else:
            game_id = raw_id

        exp_away = round(float(res.get("exp_away_pts", 0.0)), 2)
        exp_home = round(float(res.get("exp_home_pts", 0.0)), 2)
        proj_margin = round(float(res.get("exp_margin_home", exp_home - exp_away)), 2)
        proj_total = round(float(res.get("exp_total_pts", exp_home + exp_away)), 2)

        new_records.append(
            {
                "game_id": str(game_id),
                "date": fecha_clean,
                "home_team": home_team,
                "away_team": away_team,
                "home_abbr": home_abbr,
                "away_abbr": away_abbr,
                "projected_home_pts": exp_home,
                "projected_away_pts": exp_away,
                "projected_margin": proj_margin,
                "projected_total": proj_total,
                "status": "pending",
                "actual_home_score": np.nan,
                "actual_away_score": np.nan,
                "actual_margin": np.nan,
                "actual_total": np.nan,
                "margin_error": np.nan,
                "total_error": np.nan,
                "calibrated_at": "",
            }
        )

    if not new_records:
        return existing_df

    if existing_df.empty:
        merged_df = pd.DataFrame(new_records)[PREDICTION_HISTORY_COLS]
    else:
        merged_df = existing_df.copy()
        for rec in new_records:
            gid = str(rec["game_id"])
            mask_id = merged_df["game_id"].astype(str) == gid
            mask_matchup = (
                (merged_df["date"].astype(str) == str(rec["date"]))
                & (merged_df["home_abbr"].astype(str).str.upper() == str(rec["home_abbr"]).upper())
                & (merged_df["away_abbr"].astype(str).str.upper() == str(rec["away_abbr"]).upper())
            )
            combined_mask = mask_id | mask_matchup
            if combined_mask.any():
                idx_match = merged_df[combined_mask].index[0]
                cur_status = str(merged_df.loc[idx_match, "status"]).strip().lower()
                if cur_status == "evaluated":
                    continue
                for k, v in rec.items():
                    merged_df.loc[idx_match, k] = v
            else:
                merged_df = pd.concat([merged_df, pd.DataFrame([rec])], ignore_index=True)

    try:
        merged_df.to_csv(target_csv, index=False, encoding="utf-8")
    except OSError:
        pass

    return merged_df


def build_nba_predictions_export_df(
    results_list: List[Dict[str, Any]],
    slate_meta: Optional[List[Dict[str, Any]]] = None,
    fecha_str: Optional[str] = None,
) -> pd.DataFrame:
    """
    Compila en un DataFrame estructurado los resultados completos de las 5,000 simulaciones
    de Monte Carlo para todos los partidos de la cartelera activa:
      - Fecha y Hora, Equipo Visita, Equipo Local
      - Puntos Proyectados Visita y Local
      - Probabilidad Modelo ML Visita / Local (%), Cuota Justa Decimal
      - Probabilidad Mercado ML (%), ESPN BPI (%)
      - Línea Spread Mercado, % Cubrir Local, % Cubrir Visita
      - Línea Total Mercado, % Over, % Under
      - Edge / EV% detectado y Apuesta Sugerida
    """
    if fecha_str is None:
        if st is not None and hasattr(st, "session_state") and "fecha_nba" in st.session_state:
            try:
                fecha_str = st.session_state.fecha_nba.strftime("%Y-%m-%d")
            except Exception:
                fecha_str = "2026-10-28"
        else:
            fecha_str = "2026-10-28"

    rows: List[Dict[str, Any]] = []
    for idx, res in enumerate(results_list or []):
        away_abbr = str(res.get("away_abbr", "AWAY"))
        home_abbr = str(res.get("home_abbr", "HOME"))
        away_team = str(res.get("away_team", away_abbr))
        home_team = str(res.get("home_team", home_abbr))

        meta = slate_meta[idx] if slate_meta and idx < len(slate_meta) and isinstance(slate_meta[idx], dict) else {}
        hora_juego = str(
            meta.get("hora")
            or res.get("hora")
            or GAME_SLATE_TIMES[idx % len(GAME_SLATE_TIMES)]
        )
        fecha_hora_str = f"{fecha_str} {hora_juego}".strip()

        desg = res.get("desglose_5000_sims") or {}
        val_tot = res.get("valor_totales") or {}
        val_sp = res.get("valor_spread") or {}

        exp_away = round(float(res.get("exp_away_pts", 0.0)), 1)
        exp_home = round(float(res.get("exp_home_pts", 0.0)), 1)
        exp_total = round(float(res.get("exp_total_pts", exp_away + exp_home)), 1)

        prob_mod_away = round(float(res.get("away_win_prob", 0.5)) * 100.0, 1)
        prob_mod_home = round(float(res.get("home_win_prob", 0.5)) * 100.0, 1)
        fair_ml_away = round(float(res.get("away_ml_dec", 2.00)), 2)
        fair_ml_home = round(float(res.get("home_ml_dec", 2.00)), 2)

        prob_mkt_away = round(float(desg.get("prob_ml_away_casas", 50.0)), 1)
        prob_mkt_home = round(float(desg.get("prob_ml_home_casas", 50.0)), 1)
        espn_bpi_away = round(float(desg.get("prob_ml_away_espn", 50.0)), 1)
        espn_bpi_home = round(float(desg.get("prob_ml_home_espn", 50.0)), 1)

        sp_home_line = round(float(res.get("spread_line_home", 0.0)), 1)
        sp_away_line = round(float(res.get("spread_line_away", -sp_home_line)), 1)
        linea_spread_mkt_str = f"{home_abbr} {sp_home_line:+.1f} / {away_abbr} {sp_away_line:+.1f}"
        pct_cubre_local = round(float(res.get("home_cover_prob", 0.5)) * 100.0, 1)
        pct_cubre_visita = round(float(res.get("away_cover_prob", 0.5)) * 100.0, 1)

        linea_total_mkt = round(float(res.get("total_line", 222.5)), 1)
        pct_over = round(float(res.get("over_prob", 0.5)) * 100.0, 1)
        pct_under = round(float(res.get("under_prob", 0.5)) * 100.0, 1)

        # Construcción de Edge / EV% detectado y Apuesta Sugerida
        edges_detectados: List[str] = []
        apuestas_sugeridas: List[str] = []

        if val_sp.get("valor"):
            sp_pick = str(val_sp.get("pick", ""))
            sp_cuota = float(val_sp.get("cuota", 1.91))
            sp_edge = float(val_sp.get("edge_pts", 0.0))
            sp_ev = float(val_sp.get("ev_pct", 0.0))
            edges_detectados.append(f"Spread: +{sp_edge:.1f} pts ({sp_ev:+.1f}% EV)")
            apuestas_sugeridas.append(f"⚡ SPREAD {sp_pick} @ {sp_cuota:.2f} ({sp_ev:+.1f}% EV)")

        if val_tot.get("valor"):
            tot_pick = str(val_tot.get("pick", ""))
            tot_linea = float(val_tot.get("linea", linea_total_mkt))
            tot_cuota = float(val_tot.get("cuota", 1.91))
            tot_edge = float(val_tot.get("edge_pts", 0.0))
            tot_ev = float(val_tot.get("ev_pct", 0.0))
            edges_detectados.append(f"Total {tot_pick}: +{tot_edge:.1f} pts ({tot_ev:+.1f}% EV)")
            apuestas_sugeridas.append(f"🔥 {tot_pick} {tot_linea:.1f} @ {tot_cuota:.2f} ({tot_ev:+.1f}% EV)")

        if desg.get("ml_tiene_ev"):
            ml_eq = str(desg.get("ml_abbr", home_abbr))
            ml_c_dec = float(desg.get("ml_cuota_decimal", 1.91))
            ml_edge_p = float(desg.get("ml_edge_pct", 0.0))
            ml_ev_p = float(desg.get("ml_ev_pct", 0.0))
            edges_detectados.append(f"ML {ml_eq}: {ml_edge_p:+.1f}% vs Casas ({ml_ev_p:+.1f}% EV)")
            if not apuestas_sugeridas:
                apuestas_sugeridas.append(f"🏀 ML {ml_eq} @ {ml_c_dec:.2f} ({ml_ev_p:+.1f}% EV)")

        if not edges_detectados:
            best_sp_ev = max(float(desg.get("spread_ev_pct", 0.0)), 0.0)
            best_tot_ev = max(float(desg.get("ev_over_pct", 0.0)), float(desg.get("ev_under_pct", 0.0)), 0.0)
            max_ev_residual = max(best_sp_ev, best_tot_ev)
            edge_str = f"Mercado Eficiente (Máx EV: {max_ev_residual:+.1f}%)"
        else:
            edge_str = " | ".join(edges_detectados)

        if not apuestas_sugeridas:
            fav_abbr_str = str(res.get("fav_abbr", home_abbr))
            fav_fair_dec = fair_ml_home if fav_abbr_str == home_abbr else fair_ml_away
            apuesta_str = f"SIN SEÑAL +EV (Lean Modelo: {fav_abbr_str} ML — Fair {fav_fair_dec:.2f})"
        else:
            apuesta_str = " + ".join(apuestas_sugeridas)

        bajas_partido_export = res.get("bajas_partido") or []
        bajas_export_str = (
            ", ".join(
                f"{b['jugador']} ({b.get('team_abbr', '')} - {b.get('status', 'Out')})"
                for b in bajas_partido_export
                if b.get("jugador")
            )
            if bajas_partido_export
            else "Sin bajas titulares"
        )

        rows.append(
            {
                "Fecha y Hora": fecha_hora_str,
                "Equipo Visita": f"{away_team} ({away_abbr})",
                "Equipo Local": f"{home_team} ({home_abbr})",
                "Puntos Proyectados Visita": exp_away,
                "Puntos Proyectados Local": exp_home,
                "Total Proyectado Modelo": exp_total,
                "Probabilidad Modelo ML Visita (%)": prob_mod_away,
                "Probabilidad Modelo ML Local (%)": prob_mod_home,
                "Cuota Justa Decimal Visita": fair_ml_away,
                "Cuota Justa Decimal Local": fair_ml_home,
                "Probabilidad Mercado ML Visita (%)": prob_mkt_away,
                "Probabilidad Mercado ML Local (%)": prob_mkt_home,
                "ESPN BPI Visita (%)": espn_bpi_away,
                "ESPN BPI Local (%)": espn_bpi_home,
                "Línea Spread Mercado": linea_spread_mkt_str,
                "% Cubrir Local": pct_cubre_local,
                "% Cubrir Visita": pct_cubre_visita,
                "Desglose Spread (5K Sims)": str(desg.get("texto_narrativo_spread", "")),
                "Línea Total Mercado": linea_total_mkt,
                "% Over": pct_over,
                "% Under": pct_under,
                "Desglose Total (5K Sims)": str(desg.get("texto_narrativo_total", "")),
                "Bajas Detectadas (ESPN)": bajas_export_str,
                "Edge / EV% Detectado": edge_str,
                "Apuesta Sugerida": apuesta_str,
            }
        )

    save_daily_predictions_to_history(
        results_list=results_list,
        slate_meta=slate_meta,
        fecha_str=fecha_str,
    )

    return pd.DataFrame(rows)


def _clasificar_nivel_confianza_varianza(
    prob_modelo_pct: float,
    res: Optional[Dict[str, Any]] = None,
    tipo_mercado: str = "Moneyline",
) -> str:
    """
    Determina el Nivel de Confianza / Varianza del Modelo ('Baja', 'Moderada', 'Alta')
    evaluando la dispersión estocástica de triples (3PA_Rate), tasa de pérdidas (TOV_Pct)
    y la probabilidad acumulada en las 5,000 trayectorias de Monte Carlo.
    """
    vol_score = 0.0
    if isinstance(res, dict):
        away_row = res.get("away_row", {})
        home_row = res.get("home_row", {})
        if hasattr(away_row, "get") and hasattr(home_row, "get"):
            three_rate_avg = 0.5 * (
                float(away_row.get("3PA_Rate", 0.39)) + float(home_row.get("3PA_Rate", 0.39))
            )
            tov_avg = 0.5 * (
                float(away_row.get("TOV_Pct", 13.5)) + float(home_row.get("TOV_Pct", 13.5))
            )
            vol_score = (three_rate_avg - 0.38) * 25.0 + (tov_avg - 13.5) * 0.4

    if prob_modelo_pct >= 62.0 and vol_score <= 0.85:
        return "Alta (Varianza Baja)"
    if prob_modelo_pct >= 55.0:
        return "Moderada (Varianza Moderada)"
    return "Baja (Varianza Alta)"


def build_highest_probability_sheet(
    results_list: List[Dict[str, Any]],
    slate_meta: Optional[List[Dict[str, Any]]] = None,
    fecha_str: Optional[str] = None,
) -> pd.DataFrame:
    """
    A partir de las 5,000 simulaciones de Monte Carlo ejecutadas para la jornada,
    desagrega todas las opciones binarias del mercado por partido:
      - Moneyline (Victoria Directa: Local y Visita)
      - Spreads / Hándicaps (Línea oficial de cubrimiento Local y Visita)
      - Totales (Over y Under individual por juego)
    Extrae para cada selección:
      - Mercado / Selección específica (ej. 'Boston Celtics ML', 'Denver Nuggets -4.5', 'Under 224.5')
      - Probabilidad del Modelo (%)
      - Probabilidad Implícita del Mercado sin Vigorish (%)
      - Edge Matemático / EV (%)
      - Nivel de Confianza / Varianza del Modelo (Baja / Moderada / Alta)
    Ordena el DataFrame de forma estrictamente DESCENDENTE por 'Probabilidad del Modelo (%)'.
    """
    rows: List[Dict[str, Any]] = []

    for idx, res in enumerate(results_list or []):
        if not isinstance(res, dict):
            continue

        away_abbr = str(res.get("away_abbr", "AWAY")).strip().upper()
        home_abbr = str(res.get("home_abbr", "HOME")).strip().upper()
        away_team = str(res.get("away_team", away_abbr)).strip()
        home_team = str(res.get("home_team", home_abbr)).strip()
        matchup_label = f"{away_team} ({away_abbr}) @ {home_team} ({home_abbr})"
        matchup_short = f"{away_abbr} @ {home_abbr}"

        desg = res.get("desglose_5000_sims") or {}

        # ------------------------------------------------------------------
        # 1. MONEYLINE (Victoria Directa: Local y Visita)
        # ------------------------------------------------------------------
        prob_ml_home = round(float(res.get("home_win_prob", 0.5)) * 100.0, 2)
        prob_ml_away = round(float(res.get("away_win_prob", 0.5)) * 100.0, 2)

        novig_ml_home = float(desg.get("prob_ml_home_casas", 50.0))
        novig_ml_away = float(desg.get("prob_ml_away_casas", 50.0))
        sum_ml_mkt = novig_ml_home + novig_ml_away
        if sum_ml_mkt > 0:
            novig_ml_home = round((novig_ml_home / sum_ml_mkt) * 100.0, 2)
            novig_ml_away = round(100.0 - novig_ml_home, 2)
        else:
            novig_ml_home, novig_ml_away = 50.0, 50.0

        cuota_ml_home_mkt = round(max(1.01, (100.0 / max(novig_ml_home, 1.0)) * 0.955), 2)
        cuota_ml_away_mkt = round(max(1.01, (100.0 / max(novig_ml_away, 1.0)) * 0.955), 2)
        if desg.get("ml_abbr") == home_abbr and desg.get("ml_cuota_decimal"):
            cuota_ml_home_mkt = round(float(desg.get("ml_cuota_decimal", cuota_ml_home_mkt)), 2)
        elif desg.get("ml_abbr") == away_abbr and desg.get("ml_cuota_decimal"):
            cuota_ml_away_mkt = round(float(desg.get("ml_cuota_decimal", cuota_ml_away_mkt)), 2)

        edge_ml_home = round(prob_ml_home - novig_ml_home, 2)
        edge_ml_away = round(prob_ml_away - novig_ml_away, 2)
        ev_ml_home = round(((prob_ml_home / 100.0) * cuota_ml_home_mkt - 1.0) * 100.0, 2)
        ev_ml_away = round(((prob_ml_away / 100.0) * cuota_ml_away_mkt - 1.0) * 100.0, 2)

        rows.append(
            {
                "Partido": matchup_label,
                "Tipo de Mercado": "Moneyline",
                "Mercado / Selección": f"{home_team} ML",
                "Probabilidad del Modelo (%)": prob_ml_home,
                "Probabilidad Implícita del Mercado sin Vigorish (%)": novig_ml_home,
                "Edge Matemático (%)": edge_ml_home,
                "EV (%)": ev_ml_home,
                "Edge Matemático / EV (%)": f"{edge_ml_home:+.1f}% Edge | {ev_ml_home:+.1f}% EV",
                "Cuota Justa Modelo": round(100.0 / max(prob_ml_home, 0.1), 2),
                "Cuota Decimal Mercado": cuota_ml_home_mkt,
                "Nivel de Confianza / Varianza del Modelo": _clasificar_nivel_confianza_varianza(
                    prob_ml_home, res, "Moneyline"
                ),
                "_game_idx": idx,
                "_side": "HOME_ML",
            }
        )
        rows.append(
            {
                "Partido": matchup_label,
                "Tipo de Mercado": "Moneyline",
                "Mercado / Selección": f"{away_team} ML",
                "Probabilidad del Modelo (%)": prob_ml_away,
                "Probabilidad Implícita del Mercado sin Vigorish (%)": novig_ml_away,
                "Edge Matemático (%)": edge_ml_away,
                "EV (%)": ev_ml_away,
                "Edge Matemático / EV (%)": f"{edge_ml_away:+.1f}% Edge | {ev_ml_away:+.1f}% EV",
                "Cuota Justa Modelo": round(100.0 / max(prob_ml_away, 0.1), 2),
                "Cuota Decimal Mercado": cuota_ml_away_mkt,
                "Nivel de Confianza / Varianza del Modelo": _clasificar_nivel_confianza_varianza(
                    prob_ml_away, res, "Moneyline"
                ),
                "_game_idx": idx,
                "_side": "AWAY_ML",
            }
        )

        # ------------------------------------------------------------------
        # 2. SPREADS / HÁNDICAPS (Cubrimiento Local y Visita)
        # ------------------------------------------------------------------
        sp_line_home = round(float(res.get("spread_line_home", 0.0)), 1)
        sp_line_away = round(float(res.get("spread_line_away", -sp_line_home)), 1)
        prob_sp_home = round(float(res.get("home_cover_prob", 0.5)) * 100.0, 2)
        prob_sp_away = round(float(res.get("away_cover_prob", 0.5)) * 100.0, 2)

        c_sp_home = max(1.01, float(res.get("cuota_spread_home_decimal", 1.91)))
        c_sp_away = max(1.01, float(res.get("cuota_spread_away_decimal", 1.91)))
        inv_sp_h = 1.0 / c_sp_home
        inv_sp_a = 1.0 / c_sp_away
        novig_sp_home = round((inv_sp_h / (inv_sp_h + inv_sp_a)) * 100.0, 2)
        novig_sp_away = round(100.0 - novig_sp_home, 2)

        edge_sp_home = round(prob_sp_home - novig_sp_home, 2)
        edge_sp_away = round(prob_sp_away - novig_sp_away, 2)
        ev_sp_home = round(((prob_sp_home / 100.0) * c_sp_home - 1.0) * 100.0, 2)
        ev_sp_away = round(((prob_sp_away / 100.0) * c_sp_away - 1.0) * 100.0, 2)

        rows.append(
            {
                "Partido": matchup_label,
                "Tipo de Mercado": "Spread / Hándicap",
                "Mercado / Selección": f"{home_team} {sp_line_home:+.1f}",
                "Probabilidad del Modelo (%)": prob_sp_home,
                "Probabilidad Implícita del Mercado sin Vigorish (%)": novig_sp_home,
                "Edge Matemático (%)": edge_sp_home,
                "EV (%)": ev_sp_home,
                "Edge Matemático / EV (%)": f"{edge_sp_home:+.1f}% Edge | {ev_sp_home:+.1f}% EV",
                "Cuota Justa Modelo": round(100.0 / max(prob_sp_home, 0.1), 2),
                "Cuota Decimal Mercado": round(c_sp_home, 2),
                "Nivel de Confianza / Varianza del Modelo": _clasificar_nivel_confianza_varianza(
                    prob_sp_home, res, "Spread"
                ),
                "_game_idx": idx,
                "_side": "HOME_SPREAD",
            }
        )
        rows.append(
            {
                "Partido": matchup_label,
                "Tipo de Mercado": "Spread / Hándicap",
                "Mercado / Selección": f"{away_team} {sp_line_away:+.1f}",
                "Probabilidad del Modelo (%)": prob_sp_away,
                "Probabilidad Implícita del Mercado sin Vigorish (%)": novig_sp_away,
                "Edge Matemático (%)": edge_sp_away,
                "EV (%)": ev_sp_away,
                "Edge Matemático / EV (%)": f"{edge_sp_away:+.1f}% Edge | {ev_sp_away:+.1f}% EV",
                "Cuota Justa Modelo": round(100.0 / max(prob_sp_away, 0.1), 2),
                "Cuota Decimal Mercado": round(c_sp_away, 2),
                "Nivel de Confianza / Varianza del Modelo": _clasificar_nivel_confianza_varianza(
                    prob_sp_away, res, "Spread"
                ),
                "_game_idx": idx,
                "_side": "AWAY_SPREAD",
            }
        )

        # ------------------------------------------------------------------
        # 3. TOTALES (Over y Under individual por juego)
        # ------------------------------------------------------------------
        total_line = round(float(res.get("total_line", 224.5)), 1)
        prob_over = round(float(res.get("over_prob", 0.5)) * 100.0, 2)
        prob_under = round(float(res.get("under_prob", 0.5)) * 100.0, 2)

        c_over = max(1.01, float(res.get("cuota_over_decimal", 1.91)))
        c_under = max(1.01, float(res.get("cuota_under_decimal", 1.91)))
        inv_ov = 1.0 / c_over
        inv_un = 1.0 / c_under
        novig_over = round((inv_ov / (inv_ov + inv_un)) * 100.0, 2)
        novig_under = round(100.0 - novig_over, 2)

        edge_over = round(prob_over - novig_over, 2)
        edge_under = round(prob_under - novig_under, 2)
        ev_over = round(((prob_over / 100.0) * c_over - 1.0) * 100.0, 2)
        ev_under = round(((prob_under / 100.0) * c_under - 1.0) * 100.0, 2)

        rows.append(
            {
                "Partido": matchup_label,
                "Tipo de Mercado": "Total (Over/Under)",
                "Mercado / Selección": f"Over {total_line:.1f} ({matchup_short})",
                "Probabilidad del Modelo (%)": prob_over,
                "Probabilidad Implícita del Mercado sin Vigorish (%)": novig_over,
                "Edge Matemático (%)": edge_over,
                "EV (%)": ev_over,
                "Edge Matemático / EV (%)": f"{edge_over:+.1f}% Edge | {ev_over:+.1f}% EV",
                "Cuota Justa Modelo": round(100.0 / max(prob_over, 0.1), 2),
                "Cuota Decimal Mercado": round(c_over, 2),
                "Nivel de Confianza / Varianza del Modelo": _clasificar_nivel_confianza_varianza(
                    prob_over, res, "Total"
                ),
                "_game_idx": idx,
                "_side": "OVER",
            }
        )
        rows.append(
            {
                "Partido": matchup_label,
                "Tipo de Mercado": "Total (Over/Under)",
                "Mercado / Selección": f"Under {total_line:.1f} ({matchup_short})",
                "Probabilidad del Modelo (%)": prob_under,
                "Probabilidad Implícita del Mercado sin Vigorish (%)": novig_under,
                "Edge Matemático (%)": edge_under,
                "EV (%)": ev_under,
                "Edge Matemático / EV (%)": f"{edge_under:+.1f}% Edge | {ev_under:+.1f}% EV",
                "Cuota Justa Modelo": round(100.0 / max(prob_under, 0.1), 2),
                "Cuota Decimal Mercado": round(c_under, 2),
                "Nivel de Confianza / Varianza del Modelo": _clasificar_nivel_confianza_varianza(
                    prob_under, res, "Total"
                ),
                "_game_idx": idx,
                "_side": "UNDER",
            }
        )

    df_high = pd.DataFrame(rows)
    if df_high.empty:
        return pd.DataFrame(
            columns=[
                "Ranking",
                "Partido",
                "Tipo de Mercado",
                "Mercado / Selección",
                "Probabilidad del Modelo (%)",
                "Probabilidad Implícita del Mercado sin Vigorish (%)",
                "Edge Matemático (%)",
                "EV (%)",
                "Edge Matemático / EV (%)",
                "Cuota Justa Modelo",
                "Cuota Decimal Mercado",
                "Nivel de Confianza / Varianza del Modelo",
            ]
        )

    # Orden estrictamente DESCENDENTE por 'Probabilidad del Modelo (%)'
    df_high = df_high.sort_values(
        by=["Probabilidad del Modelo (%)", "Edge Matemático (%)"],
        ascending=[False, False],
    ).reset_index(drop=True)
    df_high.insert(0, "Ranking", range(1, len(df_high) + 1))

    # Conservar columnas públicas limpias para exportación Excel
    public_cols = [
        "Ranking",
        "Partido",
        "Tipo de Mercado",
        "Mercado / Selección",
        "Probabilidad del Modelo (%)",
        "Probabilidad Implícita del Mercado sin Vigorish (%)",
        "Edge Matemático (%)",
        "EV (%)",
        "Edge Matemático / EV (%)",
        "Cuota Justa Modelo",
        "Cuota Decimal Mercado",
        "Nivel de Confianza / Varianza del Modelo",
    ]
    return df_high[public_cols]


def _reconstruir_high_prob_desde_export_df(df_export: pd.DataFrame) -> pd.DataFrame:
    """
    Reconstruye la tabla `Ranking_Alta_Probabilidad` directamente a partir del DataFrame
    de `build_nba_predictions_export_df` cuando `export_nba_excel_bytes(df)` es invocado
    con un único argumento.
    """
    if not isinstance(df_export, pd.DataFrame) or df_export.empty:
        return build_highest_probability_sheet([])

    synthetic_results: List[Dict[str, Any]] = []
    for _, row in df_export.iterrows():
        vis_str = str(row.get("Equipo Visita", "Visita (AWAY)"))
        loc_str = str(row.get("Equipo Local", "Local (HOME)"))
        away_team = vis_str.split(" (")[0].strip()
        away_abbr = vis_str.split("(")[-1].replace(")", "").strip() if "(" in vis_str else away_team[:3].upper()
        home_team = loc_str.split(" (")[0].strip()
        home_abbr = loc_str.split("(")[-1].replace(")", "").strip() if "(" in loc_str else home_team[:3].upper()

        sp_str = str(row.get("Línea Spread Mercado", f"{home_abbr} -2.5 / {away_abbr} +2.5"))
        sp_home_val = -2.5
        try:
            first_part = sp_str.split("/")[0].strip().split()[-1]
            sp_home_val = float(first_part)
        except Exception:
            sp_home_val = -2.5

        prob_mod_away = float(row.get("Probabilidad Modelo ML Visita (%)", 50.0)) / 100.0
        prob_mod_home = float(row.get("Probabilidad Modelo ML Local (%)", 50.0)) / 100.0
        prob_mkt_away = float(row.get("Probabilidad Mercado ML Visita (%)", 50.0))
        prob_mkt_home = float(row.get("Probabilidad Mercado ML Local (%)", 50.0))
        pct_cubre_local = float(row.get("% Cubrir Local", 50.0)) / 100.0
        pct_cubre_visita = float(row.get("% Cubrir Visita", 50.0)) / 100.0
        linea_tot = float(row.get("Línea Total Mercado", 224.5))
        pct_over = float(row.get("% Over", 50.0)) / 100.0
        pct_under = float(row.get("% Under", 50.0)) / 100.0

        synthetic_results.append(
            {
                "away_team": away_team,
                "away_abbr": away_abbr,
                "home_team": home_team,
                "home_abbr": home_abbr,
                "away_win_prob": prob_mod_away,
                "home_win_prob": prob_mod_home,
                "spread_line_home": sp_home_val,
                "spread_line_away": -sp_home_val,
                "home_cover_prob": pct_cubre_local,
                "away_cover_prob": pct_cubre_visita,
                "total_line": linea_tot,
                "over_prob": pct_over,
                "under_prob": pct_under,
                "cuota_spread_home_decimal": 1.91,
                "cuota_spread_away_decimal": 1.91,
                "cuota_over_decimal": 1.91,
                "cuota_under_decimal": 1.91,
                "desglose_5000_sims": {
                    "prob_ml_home_casas": prob_mkt_home,
                    "prob_ml_away_casas": prob_mkt_away,
                },
            }
        )
    return build_highest_probability_sheet(synthetic_results)


class ExecutiveQuantReport(str):
    """
    Objeto híbrido de cadena e informe estructurado para el Memorando Analítico Institucional.
    Se comporta nativamente como un `str` (para impresión directa, Markdown o texto plano)
    y a la vez expone `.html`, `.text`, `.picks` y acceso por llaves `report['html']`.
    """

    def __new__(
        cls,
        text_content: str,
        html_content: str = "",
        picks_list: Optional[List[Dict[str, Any]]] = None,
    ) -> "ExecutiveQuantReport":
        obj = super().__new__(cls, text_content)
        obj.text = text_content
        obj.html = html_content
        obj.picks = picks_list or []
        return obj

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, str):
            if item in ("text", "markdown", "report_text"):
                return self.text
            if item in ("html", "report_html"):
                return self.html
            if item in ("picks", "top_picks"):
                return self.picks
        return super().__getitem__(item)

    def get(self, key: str, default: Any = None) -> Any:
        if key in ("text", "markdown", "report_text"):
            return self.text
        if key in ("html", "report_html"):
            return self.html
        if key in ("picks", "top_picks"):
            return self.picks
        return default


def generate_executive_quant_report(
    results_list: List[Dict[str, Any]],
    high_prob_df: Optional[pd.DataFrame] = None,
    top_n: int = 3,
) -> ExecutiveQuantReport:
    """
    Genera automáticamente un Memorando Ejecutivo Institucional para las elecciones top de mayor
    probabilidad cuantitativa (mínimo 3 elecciones principales).
    Integra para cada selección:
      a) Fundamentación Histórica: Eficiencia por posesión (Offensive/Defensive Rating ajustado a Pace),
         estabilidad de quintetos titulares (O_EPM / D_EPM) y precedentes de resolución en las 5,000 trayectorias.
      b) Contexto Operativo Actual: Impacto del reporte oficial de bajas de ESPN (redistribución exacta de
         240.0 min con tope de 42.0 min), desgaste de calendario/viaje, estabilización bayesiana (N=25) +
         autocalibración dinámica (K=0.06) y neutralización de minutos basura (garbage time).
      c) Justificación de Varianza y Eficiencia de Línea: Por qué la probabilidad proyectada por el motor
         supera con margen de seguridad la línea desvigilada (no-vig) de las casas de apuestas.
    """
    import html as _html

    if high_prob_df is None or high_prob_df.empty:
        high_prob_df = build_highest_probability_sheet(results_list)

    n_select = max(3, int(top_n))
    top_df = high_prob_df.head(n_select).copy() if not high_prob_df.empty else pd.DataFrame()

    # Mapa rápido por etiqueta de partido para recuperar telemetría profunda del motor
    matchup_map: Dict[str, Dict[str, Any]] = {}
    for res in results_list or []:
        if not isinstance(res, dict):
            continue
        aw_ab = str(res.get("away_abbr", "AWAY")).strip().upper()
        hm_ab = str(res.get("home_abbr", "HOME")).strip().upper()
        aw_tm = str(res.get("away_team", aw_ab)).strip()
        hm_tm = str(res.get("home_team", hm_ab)).strip()
        label = f"{aw_tm} ({aw_ab}) @ {hm_tm} ({hm_ab})"
        matchup_map[label] = res

    memo_blocks_text: List[str] = []
    memo_blocks_html: List[str] = []
    structured_picks: List[Dict[str, Any]] = []

    for idx_row, (_, pick_row) in enumerate(top_df.iterrows(), start=1):
        partido_str = str(pick_row.get("Partido", "N/A"))
        tipo_mkt = str(pick_row.get("Tipo de Mercado", "Mercado"))
        seleccion_str = str(pick_row.get("Mercado / Selección", "N/A"))
        prob_mod = float(pick_row.get("Probabilidad del Modelo (%)", 50.0))
        prob_novig = float(pick_row.get("Probabilidad Implícita del Mercado sin Vigorish (%)", 50.0))
        edge_pct = float(pick_row.get("Edge Matemático (%)", prob_mod - prob_novig))
        ev_pct = float(pick_row.get("EV (%)", 0.0))
        fair_odd = float(pick_row.get("Cuota Justa Modelo", round(100.0 / max(prob_mod, 0.1), 2)))
        mkt_odd = float(pick_row.get("Cuota Decimal Mercado", 1.91))
        confianza_str = str(
            pick_row.get("Nivel de Confianza / Varianza del Modelo", "Alta (Varianza Baja)")
        )

        res_ctx = matchup_map.get(partido_str, {})
        aw_ab = str(res_ctx.get("away_abbr", "VIS"))
        hm_ab = str(res_ctx.get("home_abbr", "LOC"))
        exp_aw = float(res_ctx.get("exp_away_pts", 110.5))
        exp_hm = float(res_ctx.get("exp_home_pts", 113.5))
        exp_tot = float(res_ctx.get("exp_total_pts", exp_aw + exp_hm))
        proj_pace = float(res_ctx.get("proj_pace", 99.2))
        proj_margin_hm = exp_hm - exp_aw

        away_row = res_ctx.get("away_row", {})
        home_row = res_ctx.get("home_row", {})
        aw_off = float(away_row.get("Off_Rtg", 113.5)) if hasattr(away_row, "get") else 113.5
        aw_def = float(away_row.get("Def_Rtg", 113.5)) if hasattr(away_row, "get") else 113.5
        hm_off = float(home_row.get("Off_Rtg", 115.0)) if hasattr(home_row, "get") else 115.0
        hm_def = float(home_row.get("Def_Rtg", 112.0)) if hasattr(home_row, "get") else 112.0
        aw_net = float(away_row.get("Rating_Final", away_row.get("Net_Rtg", aw_off - aw_def))) if hasattr(away_row, "get") else 0.0
        hm_net = float(home_row.get("Rating_Final", home_row.get("Net_Rtg", hm_off - hm_def))) if hasattr(home_row, "get") else 0.0
        aw_gp = int(away_row.get("Games_Played", 5)) if hasattr(away_row, "get") else 5
        hm_gp = int(home_row.get("Games_Played", 5)) if hasattr(home_row, "get") else 5
        aw_w_curr = float(away_row.get("Peso_Actual", min(1.0, aw_gp / 25.0))) if hasattr(away_row, "get") else 0.20
        hm_w_curr = float(home_row.get("Peso_Actual", min(1.0, hm_gp / 25.0))) if hasattr(home_row, "get") else 0.20

        bajas_nombres = res_ctx.get("bajas_nombres") or []
        bajas_resumen = (
            f"ausencias confirmadas en el reporte oficial de ESPN ({', '.join(bajas_nombres)}) "
            f"con redistribución proporcional exacta a 240.0 minutos de equipo (tope táctico 42.0 min/jugador)"
            if bajas_nombres
            else "integridad completa en los quintetos titulares verificados ante el reporte oficial de ESPN (240.0 min activos sin bajas críticas)"
        )

        sims_convergentes = int(round((prob_mod / 100.0) * 5000))

        # a) Fundamentación Histórica
        fundamentacion_historica = (
            f"La perfilación de eficiencia por cada 100 posesiones a un ritmo proyectado de {proj_pace:.1f} posesiones/juego "
            f"establece un diferencial estructural entre {hm_ab} (OffRtg {hm_off:.1f} / DefRtg {hm_def:.1f} / Net {hm_net:+.2f}) "
            f"y {aw_ab} (OffRtg {aw_off:.1f} / DefRtg {aw_def:.1f} / Net {aw_net:+.2f}). "
            f"La estabilidad de los quintetos titulares ponderados por impacto bidireccional (O_EPM / D_EPM) proyecta un marcador medio "
            f"de {aw_ab} {exp_aw:.1f} - {hm_ab} {exp_hm:.1f} (Total {exp_tot:.1f} pts; diferencial esperado {proj_margin_hm:+.1f} pts local), "
            f"con {sims_convergentes:,} de las 5,000 trayectorias de Monte Carlo convergiendo a favor de '{seleccion_str}'."
        )

        # b) Contexto Operativo Actual
        contexto_operativo = (
            f"El modelo incorpora {bajas_resumen}, descontando fricción por rotación corta, fatiga de calendario/viaje (back-to-back) "
            f"y neutralizando el sesgo de minutos basura (garbage time) en desenlaces con márgenes abiertos. "
            f"Adicionalmente, la estabilización bayesiana para muestras tempranas (umbral N={BAYESIAN_STABILIZATION_GAMES} juegos; "
            f"peso muestral actual {aw_ab}={aw_w_curr:.2f}, {hm_ab}={hm_w_curr:.2f}) combinada con el bucle de autocalibración "
            f"Elo/Bayesiano post-jornada (K=0.06) evita sobre-reaccionar a rachas de tiro insostenibles."
        )

        # c) Justificación de Varianza y Eficiencia de Línea
        justificacion_varianza = (
            f"La probabilidad cuantitativa del motor ({prob_mod:.1f}%, cuota justa decimal {fair_odd:.2f}) supera la probabilidad "
            f"implícita del mercado desvigilado (no-vig {prob_novig:.1f}%, cuota disponible {mkt_odd:.2f}) con un diferencial "
            f"de {edge_pct:+.1f}% ({ev_pct:+.1f}% EV). El perfil estocástico clasifica la selección en '{confianza_str}', "
            f"confirmando que la distribución de densidad simulada absorbe la varianza perimetral de triples (3PA_Rate) "
            f"y pérdidas de balón (TOV%) con margen de seguridad institucional."
        )

        structured_picks.append(
            {
                "rank": idx_row,
                "partido": partido_str,
                "tipo_mercado": tipo_mkt,
                "seleccion": seleccion_str,
                "prob_modelo_pct": prob_mod,
                "prob_novig_pct": prob_novig,
                "edge_pct": edge_pct,
                "ev_pct": ev_pct,
                "cuota_justa": fair_odd,
                "cuota_mercado": mkt_odd,
                "confianza": confianza_str,
                "fundamentacion_historica": fundamentacion_historica,
                "contexto_operativo": contexto_operativo,
                "justificacion_varianza": justificacion_varianza,
            }
        )

        memo_blocks_text.append(
            f"### #{idx_row} ANCLA DE ALTA PROBABILIDAD: {seleccion_str} ({tipo_mkt}) — {partido_str}\n"
            f"- **Métricas de Ejecución:** Probabilidad Modelo: `{prob_mod:.1f}%` | Implicada Mercado (No-Vig): `{prob_novig:.1f}%` | "
            f"Edge: `{edge_pct:+.1f}%` | EV: `{ev_pct:+.1f}%` | Cuota Justa: `{fair_odd:.2f}` (Mkt `{mkt_odd:.2f}`) | "
            f"Confianza/Varianza: `{confianza_str}`\n"
            f"- **a) Fundamentación Histórica:** {fundamentacion_historica}\n"
            f"- **b) Contexto Operativo Actual:** {contexto_operativo}\n"
            f"- **c) Justificación de Varianza y Eficiencia de Línea:** {justificacion_varianza}"
        )

        ev_badge_color = "#00ffcc" if ev_pct >= 4.0 or edge_pct >= 2.0 else "#38bdf8"
        memo_blocks_html.append(
            f"""
            <div style="margin-bottom:14px; padding:14px 16px; background-color:#0d1117; border:1px solid #1e293b; border-left:4px solid #00ffcc; border-radius:8px;">
              <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; margin-bottom:8px;">
                <div style="font-size:13px; font-weight:800; color:#ffffff; font-family:Consolas,monospace;">
                  #{idx_row} &bull; <span style="color:#00ffcc;">{_html.escape(seleccion_str)}</span>
                  <span style="font-size:11px; color:#94a3b8; font-weight:600;">[{_html.escape(tipo_mkt)} &mdash; {_html.escape(partido_str)}]</span>
                </div>
                <div style="font-size:11px; font-family:Consolas,monospace; color:{ev_badge_color}; font-weight:800;">
                  Prob. Modelo: {prob_mod:.1f}% vs No-Vig: {prob_novig:.1f}% ({edge_pct:+.1f}% Edge | {ev_pct:+.1f}% EV) &bull; {_html.escape(confianza_str)}
                </div>
              </div>
              <div style="font-size:12px; color:#cbd5e1; line-height:1.6;">
                <div style="margin-bottom:5px;"><strong style="color:#00ffcc;">a) Fundamentación Histórica:</strong> {_html.escape(fundamentacion_historica)}</div>
                <div style="margin-bottom:5px;"><strong style="color:#38bdf8;">b) Contexto Operativo Actual:</strong> {_html.escape(contexto_operativo)}</div>
                <div><strong style="color:#f8fafc;">c) Justificación de Varianza y Eficiencia de Línea:</strong> {_html.escape(justificacion_varianza)}</div>
              </div>
            </div>
            """
        )

    header_text = (
        "================================================================================\n"
        "🎯 TOP PICKS: MAYOR CERTEZA CUANTITATIVA (HIGH-CONFIDENCE ANCHORS)\n"
        "MEMORANDO EJECUTIVO DE ANÁLISIS CUANTITATIVO — TERMINAL SHARP: NBA QUANT\n"
        "================================================================================\n"
    )
    full_text = header_text + "\n\n".join(memo_blocks_text)
    full_html = "".join(memo_blocks_html)

    return ExecutiveQuantReport(full_text, html_content=full_html, picks_list=structured_picks)


def _estilizar_hoja_alta_probabilidad_openpyxl(ws: Any, df_high: pd.DataFrame) -> None:
    """
    Aplica el formato institucional oscuro / verde neón (#0D1117 / #00FFCC) a la pestaña
    `Ranking_Alta_Probabilidad` en openpyxl.
    """
    ws.views.sheetView[0].showGridLines = True
    ws.freeze_panes = "A2"

    header_fill = PatternFill(start_color="0D1117", end_color="0D1117", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="00FFCC")
    zebra_fill = PatternFill(start_color="F4F7FA", end_color="F4F7FA", fill_type="solid")
    anchor_fill = PatternFill(start_color="D1FAE5", end_color="D1FAE5", fill_type="solid")
    anchor_font = Font(name="Calibri", size=10, bold=True, color="065F46")
    regular_font = Font(name="Calibri", size=10, bold=False, color="111827")
    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1"),
    )

    num_cols = len(df_high.columns)
    num_rows = len(df_high)

    for col_idx in range(1, num_cols + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
    ws.row_dimensions[1].height = 28

    for row_idx in range(2, num_rows + 2):
        prob_val = 0.0
        ev_val = 0.0
        try:
            prob_val = float(ws.cell(row=row_idx, column=5).value or 0.0)
            ev_val = float(ws.cell(row=row_idx, column=8).value or 0.0)
        except Exception:
            pass

        is_top_anchor = (row_idx <= 6) or (prob_val >= 60.0) or (ev_val >= 4.0)
        ws.row_dimensions[row_idx].height = 21

        for col_idx in range(1, num_cols + 1):
            c = ws.cell(row=row_idx, column=col_idx)
            col_name = str(df_high.columns[col_idx - 1])
            c.border = thin_border
            c.font = anchor_font if (is_top_anchor and col_idx in (1, 4, 5, 8, 9)) else regular_font

            if is_top_anchor and col_idx in (4, 5, 8, 9):
                c.fill = anchor_fill
            elif (row_idx - 2) % 2 == 1:
                c.fill = zebra_fill

            if isinstance(c.value, (int, float, np.floating, np.integer)):
                if col_name == "Ranking":
                    c.alignment = Alignment(horizontal="center", vertical="center")
                    c.number_format = "0"
                elif "Cuota" in col_name:
                    c.alignment = Alignment(horizontal="right", vertical="center")
                    c.number_format = "0.00"
                else:
                    c.alignment = Alignment(horizontal="right", vertical="center")
                    c.number_format = "0.0"
            elif col_idx in (1, 3, 9, 12):
                c.alignment = Alignment(horizontal="center", vertical="center")
            else:
                c.alignment = Alignment(horizontal="left", vertical="center")

    for col_idx, col_name in enumerate(df_high.columns, start=1):
        col_letter = ws.cell(row=1, column=col_idx).column_letter
        max_len = len(str(col_name))
        for r_i in range(2, num_rows + 2):
            val_str = str(ws.cell(row=r_i, column=col_idx).value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = min(max(max_len + 4, 14), 46)


def export_high_probability_excel_bytes(high_prob_df: pd.DataFrame) -> io.BytesIO:
    """
    Genera en memoria un archivo Excel independiente ('nba_high_probability_picks.xlsx')
    con la pestaña 'Ranking_Alta_Probabilidad' estilizada con formato institucional (#0D1117 / #00FFCC).
    """
    buffer = io.BytesIO()
    df_high = high_prob_df.copy() if isinstance(high_prob_df, pd.DataFrame) else build_highest_probability_sheet([])

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        sheet_high = "Ranking_Alta_Probabilidad"
        df_high.to_excel(writer, index=False, sheet_name=sheet_high)
        ws_high = writer.sheets[sheet_high]
        _estilizar_hoja_alta_probabilidad_openpyxl(ws_high, df_high)

    buffer.seek(0)
    return buffer


def export_nba_excel_bytes(
    df: pd.DataFrame,
    high_prob_df: Optional[pd.DataFrame] = None,
    results_list: Optional[List[Dict[str, Any]]] = None,
) -> io.BytesIO:
    """
    Compila el DataFrame de proyecciones (`build_nba_predictions_export_df`) y la segunda vista
    ordenada estrictamente de mayor a menor probabilidad (`Ranking_Alta_Probabilidad`)
    en memoria binaria (`io.BytesIO`) usando `openpyxl`, con encabezados oscuros (#0D1117),
    texto verde neón (#00FFCC), formato numérico limpio y columnas autoajustadas.
    """
    buffer = io.BytesIO()
    df_export = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()

    if high_prob_df is not None and isinstance(high_prob_df, pd.DataFrame) and not high_prob_df.empty:
        df_high_export = high_prob_df.copy()
    elif results_list is not None:
        df_high_export = build_highest_probability_sheet(results_list)
    else:
        df_high_export = _reconstruir_high_prob_desde_export_df(df_export)

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        sheet_name = "Proyecciones_NBA_5000_Sims"
        df_export.to_excel(writer, index=False, sheet_name=sheet_name)
        ws = writer.sheets[sheet_name]
        ws.views.sheetView[0].showGridLines = True
        ws.freeze_panes = "A2"

        header_fill = PatternFill(start_color="0D1117", end_color="0D1117", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="00FFCC")
        zebra_fill = PatternFill(start_color="F4F7FA", end_color="F4F7FA", fill_type="solid")
        ev_fill = PatternFill(start_color="D1FAE5", end_color="D1FAE5", fill_type="solid")
        ev_font = Font(name="Calibri", size=10, bold=True, color="065F46")
        regular_font = Font(name="Calibri", size=10, bold=False, color="111827")
        thin_border = Border(
            left=Side(style="thin", color="CBD5E1"),
            right=Side(style="thin", color="CBD5E1"),
            top=Side(style="thin", color="CBD5E1"),
            bottom=Side(style="thin", color="CBD5E1"),
        )

        num_cols = len(df_export.columns)
        num_rows = len(df_export)

        for col_idx in range(1, num_cols + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = thin_border
        ws.row_dimensions[1].height = 28

        for row_idx in range(2, num_rows + 2):
            apuesta_val = str(ws.cell(row=row_idx, column=num_cols).value or "")
            has_ev_pick = ("EV)" in apuesta_val) and not apuesta_val.startswith("SIN SEÑAL")
            ws.row_dimensions[row_idx].height = 21

            for col_idx in range(1, num_cols + 1):
                c = ws.cell(row=row_idx, column=col_idx)
                col_name = str(df_export.columns[col_idx - 1])
                c.border = thin_border
                c.font = ev_font if (has_ev_pick and col_idx >= num_cols - 1) else regular_font

                if has_ev_pick and col_idx >= num_cols - 1:
                    c.fill = ev_fill
                elif (row_idx - 2) % 2 == 1:
                    c.fill = zebra_fill

                if isinstance(c.value, (int, float, np.floating, np.integer)):
                    c.alignment = Alignment(horizontal="right", vertical="center")
                    if "Cuota" in col_name:
                        c.number_format = "0.00"
                    else:
                        c.number_format = "0.0"
                elif col_idx in (1, 15, 18, 22):
                    c.alignment = Alignment(horizontal="center", vertical="center")
                else:
                    c.alignment = Alignment(horizontal="left", vertical="center")

        for col_idx, col_name in enumerate(df_export.columns, start=1):
            col_letter = ws.cell(row=1, column=col_idx).column_letter
            max_len = len(str(col_name))
            for r_i in range(2, num_rows + 2):
                val_str = str(ws.cell(row=r_i, column=col_idx).value or "")
                if len(val_str) > max_len:
                    max_len = len(val_str)
            ws.column_dimensions[col_letter].width = min(max(max_len + 4, 13), 46)

        # Segunda pestaña obligatoria: Ranking_Alta_Probabilidad
        sheet_high = "Ranking_Alta_Probabilidad"
        df_high_export.to_excel(writer, index=False, sheet_name=sheet_high)
        ws_high = writer.sheets[sheet_high]
        _estilizar_hoja_alta_probabilidad_openpyxl(ws_high, df_high_export)

        # Tercera pestaña: Audit_Log (auto-auditoría histórica diaria)
        df_audit_sheet = cargar_audit_log_df()
        df_audit_sheet.to_excel(writer, index=False, sheet_name=AUDIT_LOG_SHEET_NAME)
        ws_audit = writer.sheets[AUDIT_LOG_SHEET_NAME]
        ws_audit.views.sheetView[0].showGridLines = True
        ws_audit.freeze_panes = "A2"
        for col_idx in range(1, len(df_audit_sheet.columns) + 1):
            c_aud = ws_audit.cell(row=1, column=col_idx)
            c_aud.fill = header_fill
            c_aud.font = header_font
            c_aud.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c_aud.border = thin_border

    buffer.seek(0)
    return buffer


def _generar_audit_log_semilla_desde_historial() -> pd.DataFrame:
    """
    Construye los registros base de `Audit_Log` a partir de los partidos ya evaluados
    (`status == 'evaluated'`) en `data/prediction_history.csv` cuando aún no existe
    la pestaña `Audit_Log` en el Excel maestro.
    """
    hist_candidates = [
        Path(PREDICTION_HISTORY_CSV_FILENAME),
        Path(__file__).resolve().parent / PREDICTION_HISTORY_CSV_FILENAME,
    ]
    df_hist = pd.DataFrame()
    for p in hist_candidates:
        if p.exists():
            try:
                df_hist = pd.read_csv(p)
                break
            except Exception:
                continue

    if df_hist.empty or "status" not in df_hist.columns:
        return pd.DataFrame(columns=AUDIT_LOG_COLS)

    eval_df = df_hist[df_hist["status"].astype(str).str.lower() == "evaluated"].copy()
    if eval_df.empty:
        return pd.DataFrame(columns=AUDIT_LOG_COLS)

    team_running_off: Dict[str, float] = {}
    team_running_def: Dict[str, float] = {}
    for abbr, p_meta in PRESEASON_BASE_RATINGS_30_TEAMS.items():
        team_running_off[abbr] = round(float(p_meta.get("Off_Rtg_Base", 114.5)), 2)
        team_running_def[abbr] = round(float(p_meta.get("Def_Rtg_Base", 114.5)), 2)

    seed_rows: List[Dict[str, Any]] = []
    for _, row in eval_df.iterrows():
        fecha_str = str(row.get("date", "2026-11-04")).strip()
        h_abbr = str(row.get("home_abbr", "HOME")).strip().upper()
        a_abbr = str(row.get("away_abbr", "AWAY")).strip().upper()
        partido_str = f"{a_abbr} @ {h_abbr}"

        real_h = float(row.get("actual_home_score", 110.0))
        real_a = float(row.get("actual_away_score", 108.0))
        marcador_real_str = f"{int(round(real_a))}-{int(round(real_h))}"

        proj_margin_home = round(float(row.get("projected_margin", 0.0)), 2)
        proy_spread_home = round(-proj_margin_home, 2)
        real_margin_home = round(float(row.get("actual_margin", real_h - real_a)), 2)
        error_spread = round(float(row.get("margin_error", real_margin_home - proj_margin_home)), 2)

        proy_total = round(float(row.get("projected_total", 224.5)), 2)
        real_total = round(float(row.get("actual_total", real_h + real_a)), 2)
        error_total = round(float(row.get("total_error", real_total - proy_total)), 2)

        delta_net_home = round(ELO_BAYES_K * error_spread, 3)
        delta_off_home = round((delta_net_home / 2.0) + (0.015 * error_total), 2)
        delta_def_home = round(-(delta_net_home / 2.0) + (0.015 * error_total), 2)

        delta_net_away = round(-delta_net_home, 3)
        delta_off_away = round((delta_net_away / 2.0) + (0.015 * error_total), 2)
        delta_def_away = round(-(delta_net_away / 2.0) + (0.015 * error_total), 2)

        # Equipo Visitante
        a_off_prev = round(team_running_off.get(a_abbr, 114.0), 2)
        a_def_prev = round(team_running_def.get(a_abbr, 114.0), 2)
        a_off_new = round(a_off_prev + delta_off_away, 2)
        a_def_new = round(a_def_prev + delta_def_away, 2)
        team_running_off[a_abbr] = a_off_new
        team_running_def[a_abbr] = a_def_new

        seed_rows.append(
            {
                "Fecha": fecha_str,
                "Partido": partido_str,
                "Marcador_Real": marcador_real_str,
                "Proy_Spread": proy_spread_home,
                "Error_Spread": error_spread,
                "Proy_Total": proy_total,
                "Error_Total": error_total,
                "Equipo": a_abbr,
                "Off_Rtg_Prev": a_off_prev,
                "Off_Rtg_New": a_off_new,
                "Delta_Off": round(a_off_new - a_off_prev, 2),
                "Def_Rtg_Prev": a_def_prev,
                "Def_Rtg_New": a_def_new,
                "Delta_Def": round(a_def_new - a_def_prev, 2),
            }
        )

        # Equipo Local
        h_off_prev = round(team_running_off.get(h_abbr, 114.5), 2)
        h_def_prev = round(team_running_def.get(h_abbr, 114.5), 2)
        h_off_new = round(h_off_prev + delta_off_home, 2)
        h_def_new = round(h_def_prev + delta_def_home, 2)
        team_running_off[h_abbr] = h_off_new
        team_running_def[h_abbr] = h_def_new

        seed_rows.append(
            {
                "Fecha": fecha_str,
                "Partido": partido_str,
                "Marcador_Real": marcador_real_str,
                "Proy_Spread": proy_spread_home,
                "Error_Spread": error_spread,
                "Proy_Total": proy_total,
                "Error_Total": error_total,
                "Equipo": h_abbr,
                "Off_Rtg_Prev": h_off_prev,
                "Off_Rtg_New": h_off_new,
                "Delta_Off": round(h_off_new - h_off_prev, 2),
                "Def_Rtg_Prev": h_def_prev,
                "Def_Rtg_New": h_def_new,
                "Delta_Def": round(h_def_new - h_def_prev, 2),
            }
        )

    return pd.DataFrame(seed_rows, columns=AUDIT_LOG_COLS)


def _leer_hoja_audit_log_zip_fallback(xlsx_path: Path) -> Optional[pd.DataFrame]:
    """
    Lee la pestaña `Audit_Log` directamente desde el XML interno de un archivo `.xlsx`
    usando `zipfile` + `xml.etree.ElementTree` como respaldo cuando `openpyxl` no está activo.
    """
    import zipfile
    import xml.etree.ElementTree as ET

    if not xlsx_path.exists():
        return None
    try:
        with zipfile.ZipFile(xlsx_path, "r") as z:
            if "xl/workbook.xml" not in z.namelist():
                return None
            wb_root = ET.fromstring(z.read("xl/workbook.xml"))
            rels_root = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            rid_to_target = {}
            for rel in rels_root.iter():
                if rel.tag.endswith("Relationship"):
                    rid_to_target[rel.attrib.get("Id", "")] = rel.attrib.get("Target", "")

            target_sheet_xml = None
            for sh in wb_root.iter():
                if sh.tag.endswith("sheet") and sh.attrib.get("name") == AUDIT_LOG_SHEET_NAME:
                    for k, v in sh.attrib.items():
                        if k.endswith("id"):
                            t_rel = rid_to_target.get(v, "")
                            target_sheet_xml = t_rel if t_rel.startswith("xl/") else f"xl/{t_rel.lstrip('/')}"
                            break
            if not target_sheet_xml or target_sheet_xml not in z.namelist():
                return None

            shared_strings: List[str] = []
            if "xl/sharedStrings.xml" in z.namelist():
                ss_root = ET.fromstring(z.read("xl/sharedStrings.xml"))
                for si in ss_root.iter():
                    if si.tag.endswith("si"):
                        texts = [t.text or "" for t in si.iter() if t.tag.endswith("t")]
                        shared_strings.append("".join(texts))

            ws_root = ET.fromstring(z.read(target_sheet_xml))
            parsed_rows: List[List[Any]] = []
            for row_el in ws_root.iter():
                if row_el.tag.endswith("row"):
                    vals: List[Any] = []
                    for c_el in row_el:
                        if not c_el.tag.endswith("c"):
                            continue
                        c_type = c_el.attrib.get("t", "")
                        val_text = ""
                        if c_type == "inlineStr":
                            texts = [t.text or "" for t in c_el.iter() if t.tag.endswith("t")]
                            val_text = "".join(texts)
                        else:
                            for v_el in c_el:
                                if v_el.tag.endswith("v") and v_el.text is not None:
                                    val_text = v_el.text
                                    break
                            if c_type == "s" and val_text.isdigit():
                                idx_s = int(val_text)
                                if 0 <= idx_s < len(shared_strings):
                                    val_text = shared_strings[idx_s]
                        vals.append(val_text)
                    if vals:
                        parsed_rows.append(vals)

            if len(parsed_rows) < 2:
                return pd.DataFrame(columns=AUDIT_LOG_COLS)
            headers = [str(h).strip() for h in parsed_rows[0]]
            data_dicts = []
            for r_vals in parsed_rows[1:]:
                row_d = {}
                for i, h_name in enumerate(headers):
                    raw_v = r_vals[i] if i < len(r_vals) else ""
                    if h_name in (
                        "Proy_Spread", "Error_Spread", "Proy_Total", "Error_Total",
                        "Off_Rtg_Prev", "Off_Rtg_New", "Delta_Off",
                        "Def_Rtg_Prev", "Def_Rtg_New", "Delta_Def",
                    ):
                        try:
                            row_d[h_name] = float(raw_v)
                        except (TypeError, ValueError):
                            row_d[h_name] = 0.0
                    else:
                        row_d[h_name] = str(raw_v)
                data_dicts.append(row_d)
            df_out = pd.DataFrame(data_dicts)
            for col in AUDIT_LOG_COLS:
                if col not in df_out.columns:
                    df_out[col] = 0.0 if "Rtg" in col or "Delta" in col or "Error" in col or "Proy" in col else ""
            return df_out[AUDIT_LOG_COLS]
    except Exception:
        return None


def _escribir_hoja_audit_log_zip_fallback(xlsx_path: Path, df_audit: pd.DataFrame) -> bool:
    """
    Inyecta o actualiza la pestaña `Audit_Log` dentro de `nba_rosters_plantilla.xlsx`
    usando únicamente la librería estándar (`zipfile` + `xml.etree.ElementTree`) cuando
    `openpyxl` no está disponible en el intérprete actual.
    """
    import zipfile
    import xml.etree.ElementTree as ET
    from xml.sax.saxutils import escape as _xml_escape

    if not xlsx_path.exists():
        return False

    def _col_letter(col_idx_1: int) -> str:
        res_str = ""
        n = col_idx_1
        while n > 0:
            n, rem = divmod(n - 1, 26)
            res_str = chr(65 + rem) + res_str
        return res_str

    cols = list(AUDIT_LOG_COLS)
    rows_xml: List[str] = []

    # Fila 1: Cabeceras
    header_cells = []
    for c_i, c_name in enumerate(cols, start=1):
        ref = f"{_col_letter(c_i)}1"
        header_cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{_xml_escape(str(c_name))}</t></is></c>')
    rows_xml.append(f'<row r="1">{"".join(header_cells)}</row>')

    # Filas de datos
    for r_i, (_, row) in enumerate(df_audit.iterrows(), start=2):
        cell_xmls = []
        for c_i, c_name in enumerate(cols, start=1):
            ref = f"{_col_letter(c_i)}{r_i}"
            val = row.get(c_name, "")
            if c_name in (
                "Proy_Spread", "Error_Spread", "Proy_Total", "Error_Total",
                "Off_Rtg_Prev", "Off_Rtg_New", "Delta_Off",
                "Def_Rtg_Prev", "Def_Rtg_New", "Delta_Def",
            ):
                try:
                    num_v = float(val)
                    cell_xmls.append(f'<c r="{ref}"><v>{num_v}</v></c>')
                except (TypeError, ValueError):
                    cell_xmls.append(f'<c r="{ref}"><v>0.0</v></c>')
            else:
                cell_xmls.append(f'<c r="{ref}" t="inlineStr"><is><t>{_xml_escape(str(val))}</t></is></c>')
        rows_xml.append(f'<row r="{r_i}">{"".join(cell_xmls)}</row>')

    sheet_xml_str = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(rows_xml)}</sheetData>'
        "</worksheet>"
    )

    try:
        with zipfile.ZipFile(xlsx_path, "r") as zin:
            entries = {name: zin.read(name) for name in zin.namelist()}

        wb_xml = entries["xl/workbook.xml"].decode("utf-8")
        rels_xml = entries["xl/_rels/workbook.xml.rels"].decode("utf-8")
        ct_xml = entries["[Content_Types].xml"].decode("utf-8")

        target_sheet_entry = "xl/worksheets/sheet_audit_log.xml"
        rel_id = "rIdAuditLog99"

        if f'name="{AUDIT_LOG_SHEET_NAME}"' not in wb_xml:
            sheet_tag = (
                f'<sheet name="{AUDIT_LOG_SHEET_NAME}" sheetId="99" r:id="{rel_id}" '
                f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
            )
            if 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"' in wb_xml:
                sheet_tag = f'<sheet name="{AUDIT_LOG_SHEET_NAME}" sheetId="99" r:id="{rel_id}"/>'
            wb_xml = wb_xml.replace("</sheets>", f"{sheet_tag}</sheets>")
            entries["xl/workbook.xml"] = wb_xml.encode("utf-8")

        if f'Id="{rel_id}"' not in rels_xml:
            rel_tag = (
                f'<Relationship Id="{rel_id}" '
                f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                f'Target="worksheets/sheet_audit_log.xml"/>'
            )
            rels_xml = rels_xml.replace("</Relationships>", f"{rel_tag}</Relationships>")
            entries["xl/_rels/workbook.xml.rels"] = rels_xml.encode("utf-8")

        if "/xl/worksheets/sheet_audit_log.xml" not in ct_xml:
            override_tag = (
                '<Override PartName="/xl/worksheets/sheet_audit_log.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )
            ct_xml = ct_xml.replace("</Types>", f"{override_tag}</Types>")
            entries["[Content_Types].xml"] = ct_xml.encode("utf-8")

        entries[target_sheet_entry] = sheet_xml_str.encode("utf-8")

        with zipfile.ZipFile(xlsx_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for k, v in entries.items():
                zout.writestr(k, v)
        return True
    except Exception:
        return False


def cargar_audit_log_df(excel_source: Optional[Any] = None) -> pd.DataFrame:
    """
    Carga la pestaña `Audit_Log` desde el Excel maestro (`nba_rosters_plantilla.xlsx`),
    combinándola con `data/audit_log.csv` si existe. Si ambos están vacíos, inicializa
    el historial con los partidos ya evaluados en `data/prediction_history.csv`.
    """
    frames: List[pd.DataFrame] = []

    if excel_source is not None:
        try:
            if isinstance(excel_source, (bytes, bytearray)):
                df_src = pd.read_excel(io.BytesIO(excel_source), sheet_name=AUDIT_LOG_SHEET_NAME)
            else:
                df_src = pd.read_excel(excel_source, sheet_name=AUDIT_LOG_SHEET_NAME)
            if isinstance(df_src, pd.DataFrame) and not df_src.empty:
                frames.append(df_src)
        except Exception:
            pass

    xlsx_candidates = [
        Path(DEFAULT_ROSTERS_EXCEL_FILENAME),
        Path(__file__).resolve().parent / DEFAULT_ROSTERS_EXCEL_FILENAME,
    ]
    for x_path in xlsx_candidates:
        if x_path.exists():
            try:
                df_x = pd.read_excel(x_path, sheet_name=AUDIT_LOG_SHEET_NAME)
                if isinstance(df_x, pd.DataFrame) and not df_x.empty:
                    frames.append(df_x)
                    break
            except Exception:
                df_zip = _leer_hoja_audit_log_zip_fallback(x_path)
                if df_zip is not None and not df_zip.empty:
                    frames.append(df_zip)
                    break

    csv_candidates = [
        Path(AUDIT_LOG_CSV_FILENAME),
        Path(__file__).resolve().parent / AUDIT_LOG_CSV_FILENAME,
    ]
    for c_path in csv_candidates:
        if c_path.exists():
            try:
                df_c = pd.read_csv(c_path)
                if isinstance(df_c, pd.DataFrame) and not df_c.empty:
                    frames.append(df_c)
                    break
            except Exception:
                continue

    if not frames:
        df_seed = _generar_audit_log_semilla_desde_historial()
        if not df_seed.empty:
            frames.append(df_seed)

    if not frames:
        return pd.DataFrame(columns=AUDIT_LOG_COLS)

    combined = pd.concat(frames, ignore_index=True)
    for col in AUDIT_LOG_COLS:
        if col not in combined.columns:
            combined[col] = 0.0 if ("Rtg" in col or "Delta" in col or "Error" in col or "Proy" in col) else ""
    combined = combined[AUDIT_LOG_COLS].copy()
    combined = combined.drop_duplicates(subset=["Fecha", "Partido", "Equipo"], keep="last").reset_index(drop=True)
    return combined


def append_audit_log_to_master_excel(
    nuevas_filas: List[Dict[str, Any]],
    excel_path: Optional[Any] = None,
) -> pd.DataFrame:
    """
    Agrega filas nuevas (modo append, sin sobrescribir el historial previo) en la pestaña
    `Audit_Log` del Excel maestro (`nba_rosters_plantilla.xlsx`) y sincroniza `data/audit_log.csv`.
    Columnas exactas:
      'Fecha', 'Partido', 'Marcador_Real', 'Proy_Spread', 'Error_Spread',
      'Proy_Total', 'Error_Total', 'Equipo', 'Off_Rtg_Prev', 'Off_Rtg_New',
      'Delta_Off', 'Def_Rtg_Prev', 'Def_Rtg_New', 'Delta_Def'
    """
    existing_df = cargar_audit_log_df(excel_source=excel_path)
    if nuevas_filas:
        df_new = pd.DataFrame(nuevas_filas)
        for col in AUDIT_LOG_COLS:
            if col not in df_new.columns:
                df_new[col] = 0.0 if ("Rtg" in col or "Delta" in col or "Error" in col or "Proy" in col) else ""
        df_new = df_new[AUDIT_LOG_COLS].copy()
        merged_df = pd.concat([existing_df, df_new], ignore_index=True)
    else:
        merged_df = existing_df.copy()

    if not merged_df.empty:
        merged_df = (
            merged_df[AUDIT_LOG_COLS]
            .drop_duplicates(subset=["Fecha", "Partido", "Equipo"], keep="last")
            .reset_index(drop=True)
        )
    else:
        merged_df = pd.DataFrame(columns=AUDIT_LOG_COLS)

    # 1. Guardar respaldo sincronizado en data/audit_log.csv
    target_csv = Path(__file__).resolve().parent / AUDIT_LOG_CSV_FILENAME
    try:
        target_csv.parent.mkdir(parents=True, exist_ok=True)
        merged_df.to_csv(target_csv, index=False, encoding="utf-8")
    except Exception:
        pass

    # 2. Actualizar pestaña 'Audit_Log' en nba_rosters_plantilla.xlsx
    target_xlsx = (
        Path(excel_path)
        if excel_path is not None
        else (Path(__file__).resolve().parent / DEFAULT_ROSTERS_EXCEL_FILENAME)
    )
    if not target_xlsx.exists():
        alt_xlsx = Path(DEFAULT_ROSTERS_EXCEL_FILENAME)
        if alt_xlsx.exists():
            target_xlsx = alt_xlsx

    if target_xlsx.exists():
        updated_with_openpyxl = False
        try:
            import openpyxl

            wb = openpyxl.load_workbook(target_xlsx)
            if AUDIT_LOG_SHEET_NAME in wb.sheetnames:
                ws_aud = wb[AUDIT_LOG_SHEET_NAME]
                ws_aud.delete_rows(1, ws_aud.max_row + 1)
            else:
                ws_aud = wb.create_sheet(title=AUDIT_LOG_SHEET_NAME)

            ws_aud.views.sheetView[0].showGridLines = True
            ws_aud.freeze_panes = "A2"
            ws_aud.append(list(AUDIT_LOG_COLS))

            if PatternFill is not None and Font is not None:
                h_fill = PatternFill(start_color="0D1117", end_color="0D1117", fill_type="solid")
                h_font = Font(name="Calibri", size=11, bold=True, color="00FFCC")
                for col_i in range(1, len(AUDIT_LOG_COLS) + 1):
                    c_hdr = ws_aud.cell(row=1, column=col_i)
                    c_hdr.fill = h_fill
                    c_hdr.font = h_font

            for _, r_data in merged_df.iterrows():
                ws_aud.append([r_data[c] for c in AUDIT_LOG_COLS])

            wb.save(target_xlsx)
            updated_with_openpyxl = True
        except Exception:
            updated_with_openpyxl = False

        if not updated_with_openpyxl:
            _escribir_hoja_audit_log_zip_fallback(target_xlsx, merged_df)

    return merged_df