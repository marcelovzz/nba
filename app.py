import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st

# ==============================================================================
# CONFIGURACIÓN DE PÁGINA Y CONSTANTES GLOBALES
# ==============================================================================
st.set_page_config(
    page_title="TERMINAL SHARP: NBA QUANT SCANNER",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded",
)

LEAGUE_AVG_ORTG = 115.5
LEAGUE_AVG_PACE = 99.0
LEAGUE_AVG_ISO_PPP = 1.03
LEAGUE_AVG_PNR_PPP = 1.04
LEAGUE_AVG_TOV = 13.1

# ==============================================================================
# 1. DICCIONARIO Y CDN OFICIAL DE LOGOS (ESPN CDN)
# ==============================================================================
URL_NBA_LOGOS = "https://a.espncdn.com/i/teamlogos/nba/500/{}.png"

NBA_TEAMS = [
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
]


def escudo_nba_html(team_abbr: str, size: int = 32) -> str:
    abbr = str(team_abbr).strip().upper()
    url = f"https://a.espncdn.com/i/teamlogos/nba/500/{abbr.lower()}.png"
    return (
        f'<img src="{url}" width="{size}" height="{size}" '
        f'style="object-fit: contain; vertical-align: middle; margin-right: 8px;">'
    )


# Paleta oficial de colores neón/institucional para las 30 franquicias NBA
TEAM_COLORS: Dict[str, Tuple[str, str]] = {
    # Atlántico
    "BOS": ("#007A33", "#00F5D4"),
    "BKN": ("#1E293B", "#94A3B8"),
    "NYK": ("#F58426", "#006BB6"),
    "PHI": ("#006BB6", "#ED174C"),
    "TOR": ("#CE1141", "#A1A1AA"),
    # Central
    "CHI": ("#CE1141", "#F43F5E"),
    "CLE": ("#860038", "#FDBB30"),
    "DET": ("#C8102E", "#1D42BA"),
    "IND": ("#002D62", "#FDBB30"),
    "MIL": ("#00471B", "#10B981"),
    # Noroeste
    "DEN": ("#0E2240", "#FEC524"),
    "MIN": ("#0C2340", "#78BE20"),
    "OKC": ("#007AC1", "#EF3B24"),
    "POR": ("#E03A3E", "#94A3B8"),
    "UTA": ("#002B5C", "#F9A01B"),
    # Pacífico
    "GSW": ("#1D428A", "#FFC72C"),
    "LAC": ("#C8102E", "#1D428A"),
    "LAL": ("#552583", "#FDB927"),
    "PHX": ("#1D1160", "#E56020"),
    "SAC": ("#5A2D81", "#A78BFA"),
    # Sureste
    "ATL": ("#E03A3E", "#C1D32F"),
    "CHA": ("#1D1160", "#00788C"),
    "MIA": ("#98002E", "#F9A01B"),
    "ORL": ("#0077C0", "#38BDF8"),
    "WAS": ("#002B5C", "#E31837"),
    # Suroeste
    "DAL": ("#00538C", "#00B4D8"),
    "HOU": ("#CE1141", "#F43F5E"),
    "MEM": ("#5D76A9", "#12173F"),
    "NOP": ("#0C2340", "#C8102E"),
    "SAS": ("#000000", "#C4CED4"),
}

# Racha reciente de forma (Últimos 5 juegos) para las pastillas W/L de la Cartelera
TEAM_RECENT_FORM: Dict[str, List[str]] = {
    "BOS": ["W", "W", "W", "L", "W"],
    "BKN": ["L", "W", "L", "L", "W"],
    "NYK": ["W", "W", "L", "W", "W"],
    "PHI": ["W", "L", "W", "W", "L"],
    "TOR": ["L", "L", "W", "L", "L"],
    "CHI": ["W", "L", "L", "W", "L"],
    "CLE": ["W", "W", "W", "W", "L"],
    "DET": ["L", "L", "L", "W", "L"],
    "IND": ["W", "W", "L", "W", "L"],
    "MIL": ["W", "L", "W", "W", "W"],
    "DEN": ["W", "W", "W", "L", "W"],
    "MIN": ["W", "L", "W", "W", "W"],
    "OKC": ["W", "W", "W", "W", "W"],
    "POR": ["L", "L", "W", "L", "L"],
    "UTA": ["L", "W", "L", "L", "L"],
    "GSW": ["W", "W", "L", "W", "L"],
    "LAC": ["W", "L", "W", "L", "W"],
    "LAL": ["W", "W", "L", "L", "W"],
    "PHX": ["W", "L", "W", "W", "W"],
    "SAC": ["L", "W", "W", "L", "W"],
    "ATL": ["W", "L", "L", "W", "W"],
    "CHA": ["L", "L", "W", "L", "L"],
    "MIA": ["W", "L", "W", "W", "L"],
    "ORL": ["W", "W", "W", "L", "L"],
    "WAS": ["L", "L", "L", "L", "W"],
    "DAL": ["W", "W", "L", "W", "W"],
    "HOU": ["W", "W", "L", "W", "L"],
    "MEM": ["W", "L", "W", "W", "L"],
    "NOP": ["L", "W", "W", "L", "W"],
    "SAS": ["L", "W", "L", "W", "L"],
}

GAME_SLATE_TIMES: List[str] = [
    "19:00 ET", "19:30 ET", "19:30 ET", "20:00 ET", "20:00 ET",
    "20:30 ET", "20:30 ET", "21:00 ET", "21:00 ET", "21:30 ET",
    "22:00 ET", "22:00 ET", "22:30 ET", "22:30 ET", "23:00 ET",
]

# Dataset completo embebido con los 30 equipos de la NBA por División
DEFAULT_CSV_DATA = [
    # ==================== DIVISIÓN ATLÁNTICO (EAST) ====================
    {
        "Team": "Boston Celtics",
        "Team_Abbr": "BOS",
        "Conference": "East",
        "Division": "Atlántico",
        "Pace": 98.4,
        "Off_Rtg": 122.2,
        "Def_Rtg": 110.6,
        "3PA_Rate": 0.472,
        "3P_Pct": 0.388,
        "TOV_Pct": 11.9,
        "Iso_PPP_Off": 1.12,
        "Iso_PPP_Def": 0.91,
        "PnR_PPP_Off": 1.09,
        "PnR_PPP_Def": 0.93,
        "Star1_Name": "Jayson Tatum",
        "Star1_PPG": 27.1,
        "Star1_Line": 26.5,
        "Star1_Style": "ISO",
        "Star1_Std": 5.9,
        "Star2_Name": "Jaylen Brown",
        "Star2_PPG": 23.2,
        "Star2_Line": 22.5,
        "Star2_Style": "ISO",
        "Star2_Std": 5.4,
    },
    {
        "Team": "Brooklyn Nets",
        "Team_Abbr": "BKN",
        "Conference": "East",
        "Division": "Atlántico",
        "Pace": 97.6,
        "Off_Rtg": 112.1,
        "Def_Rtg": 116.4,
        "3PA_Rate": 0.418,
        "3P_Pct": 0.362,
        "TOV_Pct": 13.8,
        "Iso_PPP_Off": 1.01,
        "Iso_PPP_Def": 1.07,
        "PnR_PPP_Off": 0.99,
        "PnR_PPP_Def": 1.08,
        "Star1_Name": "Cam Thomas",
        "Star1_PPG": 24.2,
        "Star1_Line": 23.5,
        "Star1_Style": "ISO",
        "Star1_Std": 6.3,
        "Star2_Name": "Dennis Schroder",
        "Star2_PPG": 17.6,
        "Star2_Line": 16.5,
        "Star2_Style": "PNR",
        "Star2_Std": 4.9,
    },
    {
        "Team": "New York Knicks",
        "Team_Abbr": "NYK",
        "Conference": "East",
        "Division": "Atlántico",
        "Pace": 96.2,
        "Off_Rtg": 118.5,
        "Def_Rtg": 112.4,
        "3PA_Rate": 0.405,
        "3P_Pct": 0.376,
        "TOV_Pct": 12.6,
        "Iso_PPP_Off": 1.10,
        "Iso_PPP_Def": 0.96,
        "PnR_PPP_Off": 1.11,
        "PnR_PPP_Def": 0.95,
        "Star1_Name": "Jalen Brunson",
        "Star1_PPG": 28.7,
        "Star1_Line": 27.5,
        "Star1_Style": "PNR",
        "Star1_Std": 6.1,
        "Star2_Name": "Karl-Anthony Towns",
        "Star2_PPG": 22.1,
        "Star2_Line": 21.5,
        "Star2_Style": "PNR",
        "Star2_Std": 5.3,
    },
    {
        "Team": "Philadelphia 76ers",
        "Team_Abbr": "PHI",
        "Conference": "East",
        "Division": "Atlántico",
        "Pace": 97.1,
        "Off_Rtg": 116.8,
        "Def_Rtg": 113.2,
        "3PA_Rate": 0.384,
        "3P_Pct": 0.369,
        "TOV_Pct": 12.2,
        "Iso_PPP_Off": 1.11,
        "Iso_PPP_Def": 0.99,
        "PnR_PPP_Off": 1.08,
        "PnR_PPP_Def": 0.98,
        "Star1_Name": "Joel Embiid",
        "Star1_PPG": 29.8,
        "Star1_Line": 28.5,
        "Star1_Style": "ISO",
        "Star1_Std": 6.5,
        "Star2_Name": "Tyrese Maxey",
        "Star2_PPG": 26.1,
        "Star2_Line": 25.5,
        "Star2_Style": "PNR",
        "Star2_Std": 5.8,
    },
    {
        "Team": "Toronto Raptors",
        "Team_Abbr": "TOR",
        "Conference": "East",
        "Division": "Atlántico",
        "Pace": 100.4,
        "Off_Rtg": 112.8,
        "Def_Rtg": 117.1,
        "3PA_Rate": 0.366,
        "3P_Pct": 0.351,
        "TOV_Pct": 14.4,
        "Iso_PPP_Off": 0.97,
        "Iso_PPP_Def": 1.08,
        "PnR_PPP_Off": 1.01,
        "PnR_PPP_Def": 1.09,
        "Star1_Name": "Scottie Barnes",
        "Star1_PPG": 20.6,
        "Star1_Line": 19.5,
        "Star1_Style": "ISO",
        "Star1_Std": 5.2,
        "Star2_Name": "RJ Barrett",
        "Star2_PPG": 21.4,
        "Star2_Line": 20.5,
        "Star2_Style": "PNR",
        "Star2_Std": 5.4,
    },
    # ==================== DIVISIÓN CENTRAL (EAST) ====================
    {
        "Team": "Chicago Bulls",
        "Team_Abbr": "CHI",
        "Conference": "East",
        "Division": "Central",
        "Pace": 101.2,
        "Off_Rtg": 114.2,
        "Def_Rtg": 116.5,
        "3PA_Rate": 0.412,
        "3P_Pct": 0.367,
        "TOV_Pct": 13.5,
        "Iso_PPP_Off": 1.03,
        "Iso_PPP_Def": 1.06,
        "PnR_PPP_Off": 1.04,
        "PnR_PPP_Def": 1.07,
        "Star1_Name": "Zach LaVine",
        "Star1_PPG": 22.9,
        "Star1_Line": 22.5,
        "Star1_Style": "ISO",
        "Star1_Std": 5.8,
        "Star2_Name": "Coby White",
        "Star2_PPG": 19.8,
        "Star2_Line": 19.5,
        "Star2_Style": "PNR",
        "Star2_Std": 5.3,
    },
    {
        "Team": "Cleveland Cavaliers",
        "Team_Abbr": "CLE",
        "Conference": "East",
        "Division": "Central",
        "Pace": 99.6,
        "Off_Rtg": 121.0,
        "Def_Rtg": 111.4,
        "3PA_Rate": 0.422,
        "3P_Pct": 0.386,
        "TOV_Pct": 12.1,
        "Iso_PPP_Off": 1.10,
        "Iso_PPP_Def": 0.94,
        "PnR_PPP_Off": 1.13,
        "PnR_PPP_Def": 0.94,
        "Star1_Name": "Donovan Mitchell",
        "Star1_PPG": 26.8,
        "Star1_Line": 26.5,
        "Star1_Style": "PNR",
        "Star1_Std": 6.0,
        "Star2_Name": "Darius Garland",
        "Star2_PPG": 20.4,
        "Star2_Line": 19.5,
        "Star2_Style": "PNR",
        "Star2_Std": 5.1,
    },
    {
        "Team": "Detroit Pistons",
        "Team_Abbr": "DET",
        "Conference": "East",
        "Division": "Central",
        "Pace": 100.6,
        "Off_Rtg": 110.4,
        "Def_Rtg": 118.2,
        "3PA_Rate": 0.358,
        "3P_Pct": 0.348,
        "TOV_Pct": 15.2,
        "Iso_PPP_Off": 0.94,
        "Iso_PPP_Def": 1.13,
        "PnR_PPP_Off": 0.97,
        "PnR_PPP_Def": 1.11,
        "Star1_Name": "Cade Cunningham",
        "Star1_PPG": 22.8,
        "Star1_Line": 24.5,
        "Star1_Style": "PNR",
        "Star1_Std": 5.6,
        "Star2_Name": "Jaden Ivey",
        "Star2_PPG": 16.4,
        "Star2_Line": 16.5,
        "Star2_Style": "ISO",
        "Star2_Std": 4.8,
    },
    {
        "Team": "Indiana Pacers",
        "Team_Abbr": "IND",
        "Conference": "East",
        "Division": "Central",
        "Pace": 102.4,
        "Off_Rtg": 119.8,
        "Def_Rtg": 116.8,
        "3PA_Rate": 0.395,
        "3P_Pct": 0.378,
        "TOV_Pct": 12.7,
        "Iso_PPP_Off": 1.06,
        "Iso_PPP_Def": 1.08,
        "PnR_PPP_Off": 1.14,
        "PnR_PPP_Def": 1.09,
        "Star1_Name": "Tyrese Haliburton",
        "Star1_PPG": 20.8,
        "Star1_Line": 20.5,
        "Star1_Style": "PNR",
        "Star1_Std": 5.7,
        "Star2_Name": "Pascal Siakam",
        "Star2_PPG": 21.6,
        "Star2_Line": 21.5,
        "Star2_Style": "ISO",
        "Star2_Std": 5.1,
    },
    {
        "Team": "Milwaukee Bucks",
        "Team_Abbr": "MIL",
        "Conference": "East",
        "Division": "Central",
        "Pace": 99.8,
        "Off_Rtg": 117.6,
        "Def_Rtg": 114.5,
        "3PA_Rate": 0.402,
        "3P_Pct": 0.375,
        "TOV_Pct": 12.8,
        "Iso_PPP_Off": 1.11,
        "Iso_PPP_Def": 1.03,
        "PnR_PPP_Off": 1.12,
        "PnR_PPP_Def": 1.04,
        "Star1_Name": "Giannis Antetokounmpo",
        "Star1_PPG": 30.8,
        "Star1_Line": 30.5,
        "Star1_Style": "ISO",
        "Star1_Std": 6.1,
        "Star2_Name": "Damian Lillard",
        "Star2_PPG": 25.1,
        "Star2_Line": 24.5,
        "Star2_Style": "PNR",
        "Star2_Std": 6.0,
    },
    # ==================== DIVISIÓN NOROESTE (WEST) ====================
    {
        "Team": "Denver Nuggets",
        "Team_Abbr": "DEN",
        "Conference": "West",
        "Division": "Noroeste",
        "Pace": 97.4,
        "Off_Rtg": 119.4,
        "Def_Rtg": 112.3,
        "3PA_Rate": 0.342,
        "3P_Pct": 0.374,
        "TOV_Pct": 12.1,
        "Iso_PPP_Off": 1.06,
        "Iso_PPP_Def": 0.98,
        "PnR_PPP_Off": 1.14,
        "PnR_PPP_Def": 0.97,
        "Star1_Name": "Nikola Jokic",
        "Star1_PPG": 26.6,
        "Star1_Line": 26.5,
        "Star1_Style": "PNR",
        "Star1_Std": 5.2,
        "Star2_Name": "Jamal Murray",
        "Star2_PPG": 21.2,
        "Star2_Line": 20.5,
        "Star2_Style": "PNR",
        "Star2_Std": 5.7,
    },
    {
        "Team": "Minnesota Timberwolves",
        "Team_Abbr": "MIN",
        "Conference": "West",
        "Division": "Noroeste",
        "Pace": 97.8,
        "Off_Rtg": 115.8,
        "Def_Rtg": 109.8,
        "3PA_Rate": 0.410,
        "3P_Pct": 0.382,
        "TOV_Pct": 13.9,
        "Iso_PPP_Off": 1.08,
        "Iso_PPP_Def": 0.90,
        "PnR_PPP_Off": 1.06,
        "PnR_PPP_Def": 0.91,
        "Star1_Name": "Anthony Edwards",
        "Star1_PPG": 27.6,
        "Star1_Line": 26.5,
        "Star1_Style": "ISO",
        "Star1_Std": 6.2,
        "Star2_Name": "Julius Randle",
        "Star2_PPG": 20.9,
        "Star2_Line": 20.5,
        "Star2_Style": "ISO",
        "Star2_Std": 5.2,
    },
    {
        "Team": "Oklahoma City Thunder",
        "Team_Abbr": "OKC",
        "Conference": "West",
        "Division": "Noroeste",
        "Pace": 100.5,
        "Off_Rtg": 120.4,
        "Def_Rtg": 109.2,
        "3PA_Rate": 0.398,
        "3P_Pct": 0.389,
        "TOV_Pct": 11.6,
        "Iso_PPP_Off": 1.14,
        "Iso_PPP_Def": 0.89,
        "PnR_PPP_Off": 1.11,
        "PnR_PPP_Def": 0.90,
        "Star1_Name": "Shai Gilgeous-Alexander",
        "Star1_PPG": 30.2,
        "Star1_Line": 29.5,
        "Star1_Style": "ISO",
        "Star1_Std": 5.4,
        "Star2_Name": "Jalen Williams",
        "Star2_PPG": 21.1,
        "Star2_Line": 20.5,
        "Star2_Style": "PNR",
        "Star2_Std": 4.9,
    },
    {
        "Team": "Portland Trail Blazers",
        "Team_Abbr": "POR",
        "Conference": "West",
        "Division": "Noroeste",
        "Pace": 99.1,
        "Off_Rtg": 109.6,
        "Def_Rtg": 117.4,
        "3PA_Rate": 0.372,
        "3P_Pct": 0.346,
        "TOV_Pct": 15.0,
        "Iso_PPP_Off": 0.95,
        "Iso_PPP_Def": 1.10,
        "PnR_PPP_Off": 0.98,
        "PnR_PPP_Def": 1.09,
        "Star1_Name": "Anfernee Simons",
        "Star1_PPG": 21.5,
        "Star1_Line": 21.5,
        "Star1_Style": "PNR",
        "Star1_Std": 5.9,
        "Star2_Name": "Jerami Grant",
        "Star2_PPG": 19.2,
        "Star2_Line": 18.5,
        "Star2_Style": "ISO",
        "Star2_Std": 5.1,
    },
    {
        "Team": "Utah Jazz",
        "Team_Abbr": "UTA",
        "Conference": "West",
        "Division": "Noroeste",
        "Pace": 100.2,
        "Off_Rtg": 113.2,
        "Def_Rtg": 118.9,
        "3PA_Rate": 0.408,
        "3P_Pct": 0.356,
        "TOV_Pct": 15.4,
        "Iso_PPP_Off": 0.99,
        "Iso_PPP_Def": 1.11,
        "PnR_PPP_Off": 1.02,
        "PnR_PPP_Def": 1.12,
        "Star1_Name": "Lauri Markkanen",
        "Star1_PPG": 23.1,
        "Star1_Line": 22.5,
        "Star1_Style": "PNR",
        "Star1_Std": 5.5,
        "Star2_Name": "Keyonte George",
        "Star2_PPG": 16.9,
        "Star2_Line": 16.5,
        "Star2_Style": "PNR",
        "Star2_Std": 5.2,
    },
    # ==================== DIVISIÓN PACÍFICO (WEST) ====================
    {
        "Team": "Golden State Warriors",
        "Team_Abbr": "GSW",
        "Conference": "West",
        "Division": "Pacífico",
        "Pace": 100.8,
        "Off_Rtg": 117.3,
        "Def_Rtg": 113.8,
        "3PA_Rate": 0.456,
        "3P_Pct": 0.380,
        "TOV_Pct": 14.3,
        "Iso_PPP_Off": 1.04,
        "Iso_PPP_Def": 1.00,
        "PnR_PPP_Off": 1.10,
        "PnR_PPP_Def": 1.01,
        "Star1_Name": "Stephen Curry",
        "Star1_PPG": 26.8,
        "Star1_Line": 26.5,
        "Star1_Style": "PNR",
        "Star1_Std": 6.4,
        "Star2_Name": "Jonathan Kuminga",
        "Star2_PPG": 16.8,
        "Star2_Line": 16.5,
        "Star2_Style": "ISO",
        "Star2_Std": 4.9,
    },
    {
        "Team": "LA Clippers",
        "Team_Abbr": "LAC",
        "Conference": "West",
        "Division": "Pacífico",
        "Pace": 96.9,
        "Off_Rtg": 115.6,
        "Def_Rtg": 113.1,
        "3PA_Rate": 0.389,
        "3P_Pct": 0.376,
        "TOV_Pct": 13.2,
        "Iso_PPP_Off": 1.11,
        "Iso_PPP_Def": 0.99,
        "PnR_PPP_Off": 1.09,
        "PnR_PPP_Def": 0.98,
        "Star1_Name": "James Harden",
        "Star1_PPG": 21.6,
        "Star1_Line": 20.5,
        "Star1_Style": "ISO",
        "Star1_Std": 5.8,
        "Star2_Name": "Norman Powell",
        "Star2_PPG": 22.4,
        "Star2_Line": 21.5,
        "Star2_Style": "PNR",
        "Star2_Std": 5.4,
    },
    {
        "Team": "Los Angeles Lakers",
        "Team_Abbr": "LAL",
        "Conference": "West",
        "Division": "Pacífico",
        "Pace": 101.4,
        "Off_Rtg": 115.9,
        "Def_Rtg": 115.2,
        "3PA_Rate": 0.349,
        "3P_Pct": 0.377,
        "TOV_Pct": 13.4,
        "Iso_PPP_Off": 1.07,
        "Iso_PPP_Def": 1.04,
        "PnR_PPP_Off": 1.08,
        "PnR_PPP_Def": 1.05,
        "Star1_Name": "LeBron James",
        "Star1_PPG": 25.4,
        "Star1_Line": 24.5,
        "Star1_Style": "ISO",
        "Star1_Std": 5.5,
        "Star2_Name": "Anthony Davis",
        "Star2_PPG": 24.8,
        "Star2_Line": 24.5,
        "Star2_Style": "PNR",
        "Star2_Std": 5.8,
    },
    {
        "Team": "Phoenix Suns",
        "Team_Abbr": "PHX",
        "Conference": "West",
        "Division": "Pacífico",
        "Pace": 98.2,
        "Off_Rtg": 117.9,
        "Def_Rtg": 114.4,
        "3PA_Rate": 0.392,
        "3P_Pct": 0.382,
        "TOV_Pct": 14.1,
        "Iso_PPP_Off": 1.13,
        "Iso_PPP_Def": 1.02,
        "PnR_PPP_Off": 1.09,
        "PnR_PPP_Def": 1.03,
        "Star1_Name": "Kevin Durant",
        "Star1_PPG": 27.3,
        "Star1_Line": 26.5,
        "Star1_Style": "ISO",
        "Star1_Std": 5.6,
        "Star2_Name": "Devin Booker",
        "Star2_PPG": 26.9,
        "Star2_Line": 26.5,
        "Star2_Style": "PNR",
        "Star2_Std": 6.1,
    },
    {
        "Team": "Sacramento Kings",
        "Team_Abbr": "SAC",
        "Conference": "West",
        "Division": "Pacífico",
        "Pace": 100.1,
        "Off_Rtg": 117.2,
        "Def_Rtg": 114.9,
        "3PA_Rate": 0.396,
        "3P_Pct": 0.368,
        "TOV_Pct": 12.8,
        "Iso_PPP_Off": 1.08,
        "Iso_PPP_Def": 1.04,
        "PnR_PPP_Off": 1.10,
        "PnR_PPP_Def": 1.04,
        "Star1_Name": "De'Aaron Fox",
        "Star1_PPG": 26.4,
        "Star1_Line": 25.5,
        "Star1_Style": "PNR",
        "Star1_Std": 6.0,
        "Star2_Name": "DeMar DeRozan",
        "Star2_PPG": 22.8,
        "Star2_Line": 21.5,
        "Star2_Style": "ISO",
        "Star2_Std": 5.0,
    },
    # ==================== DIVISIÓN SURESTE (EAST) ====================
    {
        "Team": "Atlanta Hawks",
        "Team_Abbr": "ATL",
        "Conference": "East",
        "Division": "Sureste",
        "Pace": 101.8,
        "Off_Rtg": 116.4,
        "Def_Rtg": 117.6,
        "3PA_Rate": 0.394,
        "3P_Pct": 0.364,
        "TOV_Pct": 13.7,
        "Iso_PPP_Off": 1.03,
        "Iso_PPP_Def": 1.09,
        "PnR_PPP_Off": 1.11,
        "PnR_PPP_Def": 1.10,
        "Star1_Name": "Trae Young",
        "Star1_PPG": 25.8,
        "Star1_Line": 25.5,
        "Star1_Style": "PNR",
        "Star1_Std": 6.3,
        "Star2_Name": "Jalen Johnson",
        "Star2_PPG": 19.4,
        "Star2_Line": 18.5,
        "Star2_Style": "PNR",
        "Star2_Std": 5.1,
    },
    {
        "Team": "Charlotte Hornets",
        "Team_Abbr": "CHA",
        "Conference": "East",
        "Division": "Sureste",
        "Pace": 98.9,
        "Off_Rtg": 111.2,
        "Def_Rtg": 117.8,
        "3PA_Rate": 0.415,
        "3P_Pct": 0.355,
        "TOV_Pct": 14.6,
        "Iso_PPP_Off": 0.98,
        "Iso_PPP_Def": 1.10,
        "PnR_PPP_Off": 1.03,
        "PnR_PPP_Def": 1.10,
        "Star1_Name": "LaMelo Ball",
        "Star1_PPG": 26.2,
        "Star1_Line": 25.5,
        "Star1_Style": "PNR",
        "Star1_Std": 6.5,
        "Star2_Name": "Brandon Miller",
        "Star2_PPG": 20.8,
        "Star2_Line": 20.5,
        "Star2_Style": "ISO",
        "Star2_Std": 5.5,
    },
    {
        "Team": "Miami Heat",
        "Team_Abbr": "MIA",
        "Conference": "East",
        "Division": "Sureste",
        "Pace": 95.8,
        "Off_Rtg": 113.6,
        "Def_Rtg": 111.5,
        "3PA_Rate": 0.388,
        "3P_Pct": 0.370,
        "TOV_Pct": 12.4,
        "Iso_PPP_Off": 1.03,
        "Iso_PPP_Def": 0.93,
        "PnR_PPP_Off": 1.01,
        "PnR_PPP_Def": 0.92,
        "Star1_Name": "Jimmy Butler",
        "Star1_PPG": 21.4,
        "Star1_Line": 20.5,
        "Star1_Style": "ISO",
        "Star1_Std": 5.1,
        "Star2_Name": "Bam Adebayo",
        "Star2_PPG": 19.6,
        "Star2_Line": 19.5,
        "Star2_Style": "PNR",
        "Star2_Std": 4.6,
    },
    {
        "Team": "Orlando Magic",
        "Team_Abbr": "ORL",
        "Conference": "East",
        "Division": "Sureste",
        "Pace": 96.8,
        "Off_Rtg": 112.9,
        "Def_Rtg": 109.9,
        "3PA_Rate": 0.354,
        "3P_Pct": 0.352,
        "TOV_Pct": 14.1,
        "Iso_PPP_Off": 1.02,
        "Iso_PPP_Def": 0.91,
        "PnR_PPP_Off": 1.01,
        "PnR_PPP_Def": 0.91,
        "Star1_Name": "Paolo Banchero",
        "Star1_PPG": 25.2,
        "Star1_Line": 24.5,
        "Star1_Style": "ISO",
        "Star1_Std": 5.7,
        "Star2_Name": "Franz Wagner",
        "Star2_PPG": 22.4,
        "Star2_Line": 21.5,
        "Star2_Style": "PNR",
        "Star2_Std": 5.3,
    },
    {
        "Team": "Washington Wizards",
        "Team_Abbr": "WAS",
        "Conference": "East",
        "Division": "Sureste",
        "Pace": 102.6,
        "Off_Rtg": 109.8,
        "Def_Rtg": 119.4,
        "3PA_Rate": 0.392,
        "3P_Pct": 0.347,
        "TOV_Pct": 15.1,
        "Iso_PPP_Off": 0.95,
        "Iso_PPP_Def": 1.14,
        "PnR_PPP_Off": 0.96,
        "PnR_PPP_Def": 1.13,
        "Star1_Name": "Jordan Poole",
        "Star1_PPG": 20.4,
        "Star1_Line": 19.5,
        "Star1_Style": "PNR",
        "Star1_Std": 6.1,
        "Star2_Name": "Kyle Kuzma",
        "Star2_PPG": 18.8,
        "Star2_Line": 18.5,
        "Star2_Style": "ISO",
        "Star2_Std": 5.4,
    },
    # ==================== DIVISIÓN SUROESTE (WEST) ====================
    {
        "Team": "Dallas Mavericks",
        "Team_Abbr": "DAL",
        "Conference": "West",
        "Division": "Suroeste",
        "Pace": 100.2,
        "Off_Rtg": 118.1,
        "Def_Rtg": 114.6,
        "3PA_Rate": 0.441,
        "3P_Pct": 0.372,
        "TOV_Pct": 12.3,
        "Iso_PPP_Off": 1.15,
        "Iso_PPP_Def": 1.03,
        "PnR_PPP_Off": 1.12,
        "PnR_PPP_Def": 1.02,
        "Star1_Name": "Luka Doncic",
        "Star1_PPG": 32.4,
        "Star1_Line": 31.5,
        "Star1_Style": "ISO",
        "Star1_Std": 6.6,
        "Star2_Name": "Kyrie Irving",
        "Star2_PPG": 25.3,
        "Star2_Line": 24.5,
        "Star2_Style": "ISO",
        "Star2_Std": 5.9,
    },
    {
        "Team": "Houston Rockets",
        "Team_Abbr": "HOU",
        "Conference": "West",
        "Division": "Suroeste",
        "Pace": 99.4,
        "Off_Rtg": 115.2,
        "Def_Rtg": 111.2,
        "3PA_Rate": 0.378,
        "3P_Pct": 0.358,
        "TOV_Pct": 12.6,
        "Iso_PPP_Off": 1.04,
        "Iso_PPP_Def": 0.94,
        "PnR_PPP_Off": 1.05,
        "PnR_PPP_Def": 0.93,
        "Star1_Name": "Alperen Sengun",
        "Star1_PPG": 21.3,
        "Star1_Line": 20.5,
        "Star1_Style": "PNR",
        "Star1_Std": 5.2,
        "Star2_Name": "Jalen Green",
        "Star2_PPG": 21.8,
        "Star2_Line": 21.5,
        "Star2_Style": "ISO",
        "Star2_Std": 6.2,
    },
    {
        "Team": "Memphis Grizzlies",
        "Team_Abbr": "MEM",
        "Conference": "West",
        "Division": "Suroeste",
        "Pace": 101.6,
        "Off_Rtg": 116.1,
        "Def_Rtg": 113.0,
        "3PA_Rate": 0.382,
        "3P_Pct": 0.366,
        "TOV_Pct": 13.8,
        "Iso_PPP_Off": 1.06,
        "Iso_PPP_Def": 0.97,
        "PnR_PPP_Off": 1.09,
        "PnR_PPP_Def": 0.96,
        "Star1_Name": "Ja Morant",
        "Star1_PPG": 25.6,
        "Star1_Line": 24.5,
        "Star1_Style": "PNR",
        "Star1_Std": 5.9,
        "Star2_Name": "Jaren Jackson Jr.",
        "Star2_PPG": 22.1,
        "Star2_Line": 21.5,
        "Star2_Style": "ISO",
        "Star2_Std": 5.4,
    },
    {
        "Team": "New Orleans Pelicans",
        "Team_Abbr": "NOP",
        "Conference": "West",
        "Division": "Suroeste",
        "Pace": 98.3,
        "Off_Rtg": 114.8,
        "Def_Rtg": 113.9,
        "3PA_Rate": 0.371,
        "3P_Pct": 0.369,
        "TOV_Pct": 13.4,
        "Iso_PPP_Off": 1.07,
        "Iso_PPP_Def": 1.01,
        "PnR_PPP_Off": 1.04,
        "PnR_PPP_Def": 1.00,
        "Star1_Name": "Zion Williamson",
        "Star1_PPG": 23.6,
        "Star1_Line": 22.5,
        "Star1_Style": "ISO",
        "Star1_Std": 5.5,
        "Star2_Name": "Brandon Ingram",
        "Star2_PPG": 21.9,
        "Star2_Line": 21.5,
        "Star2_Style": "ISO",
        "Star2_Std": 5.2,
    },
    {
        "Team": "San Antonio Spurs",
        "Team_Abbr": "SAS",
        "Conference": "West",
        "Division": "Suroeste",
        "Pace": 100.9,
        "Off_Rtg": 113.1,
        "Def_Rtg": 113.4,
        "3PA_Rate": 0.391,
        "3P_Pct": 0.359,
        "TOV_Pct": 14.5,
        "Iso_PPP_Off": 1.02,
        "Iso_PPP_Def": 0.96,
        "PnR_PPP_Off": 1.05,
        "PnR_PPP_Def": 0.95,
        "Star1_Name": "Victor Wembanyama",
        "Star1_PPG": 24.4,
        "Star1_Line": 23.5,
        "Star1_Style": "PNR",
        "Star1_Std": 5.8,
        "Star2_Name": "Devin Vassell",
        "Star2_PPG": 18.9,
        "Star2_Line": 18.5,
        "Star2_Style": "PNR",
        "Star2_Std": 5.0,
    },
]

# Plantilla de cruces por defecto para inicializar selectores dinámicos (1 a 15 juegos)
FULL_30_TEAM_SLATE: List[Tuple[str, str]] = [
    ("Detroit Pistons", "Boston Celtics"),
    ("New York Knicks", "Miami Heat"),
    ("Dallas Mavericks", "Denver Nuggets"),
    ("Golden State Warriors", "Los Angeles Lakers"),
    ("Minnesota Timberwolves", "Oklahoma City Thunder"),
    ("Philadelphia 76ers", "Cleveland Cavaliers"),
    ("Milwaukee Bucks", "Indiana Pacers"),
    ("Phoenix Suns", "LA Clippers"),
    ("Sacramento Kings", "Memphis Grizzlies"),
    ("Houston Rockets", "San Antonio Spurs"),
    ("Orlando Magic", "Atlanta Hawks"),
    ("New Orleans Pelicans", "Chicago Bulls"),
    ("Brooklyn Nets", "Toronto Raptors"),
    ("Charlotte Hornets", "Washington Wizards"),
    ("Portland Trail Blazers", "Utah Jazz"),
]

ROSTER_EDITOR_COLS = [
    "Team_Abbr",
    "Star1_Name",
    "Star1_PPG",
    "Star2_Name",
    "Star2_PPG",
    "Pace",
    "Off_Rtg",
    "Def_Rtg",
]


# ==============================================================================
# INYECCIÓN DE CSS: ESTÉTICA "CYBER-QUANT UI" (ROTOBOT / SHARP SYNDICATE)
# ==============================================================================
def inject_cyber_quant_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700;800&family=Orbitron:wght@500;700;800;900&display=swap');

        :root {
            --bg-void: #050811;
            --bg-panel: rgba(13, 20, 38, 0.78);
            --bg-card: rgba(15, 24, 44, 0.72);
            --neon-cyan: #00F5D4;
            --neon-emerald: #10B981;
            --neon-amber: #F59E0B;
            --neon-crimson: #F43F5E;
            --neon-purple: #8B5CF6;
            --neon-blue: #38BDF8;
            --text-primary: #F8FAFC;
            --text-secondary: #94A3B8;
            --text-muted: #64748B;
            --border-glass: rgba(0, 245, 212, 0.20);
            --border-subtle: rgba(148, 163, 184, 0.14);
        }

        /* Fondo principal Cyber-Quant */
        .stApp {
            background-color: var(--bg-void);
            background-image:
                radial-gradient(circle at 12% 8%, rgba(0, 245, 212, 0.08) 0%, transparent 38%),
                radial-gradient(circle at 88% 15%, rgba(139, 92, 246, 0.08) 0%, transparent 40%),
                radial-gradient(circle at 50% 90%, rgba(56, 189, 248, 0.05) 0%, transparent 45%),
                linear-gradient(180deg, #050811 0%, #080D1A 50%, #050811 100%);
            color: var(--text-primary);
            font-family: 'Inter', sans-serif;
        }

        /* Sidebar Glassmorphism */
        section[data-testid="stSidebar"] {
            background: rgba(8, 13, 26, 0.92) !important;
            border-right: 1px solid rgba(0, 245, 212, 0.18);
            backdrop-filter: blur(20px);
        }

        section[data-testid="stSidebar"] * {
            font-family: 'Inter', sans-serif;
        }

        /* Tipografías Globales */
        h1, h2, h3, .font-orbitron {
            font-family: 'Orbitron', sans-serif !important;
            letter-spacing: 0.06em;
        }

        .font-mono {
            font-family: 'JetBrains Mono', monospace !important;
        }

        /* Scoreboard TV Master Header */
        .tv-master-header {
            background: linear-gradient(135deg, rgba(11, 18, 35, 0.92) 0%, rgba(18, 28, 52, 0.85) 100%);
            border: 1px solid rgba(0, 245, 212, 0.30);
            border-radius: 16px;
            padding: 20px 26px;
            margin-bottom: 18px;
            box-shadow: 0 12px 36px rgba(0, 0, 0, 0.55), 0 0 24px rgba(0, 245, 212, 0.08);
            backdrop-filter: blur(18px);
            -webkit-backdrop-filter: blur(18px);
            position: relative;
            overflow: hidden;
        }

        .tv-master-header::before {
            content: "";
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: linear-gradient(90deg, #00F5D4, #38BDF8, #8B5CF6, #00F5D4);
        }

        .tv-top-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
        }

        .syndicate-badge {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: rgba(0, 245, 212, 0.10);
            border: 1px solid rgba(0, 245, 212, 0.35);
            color: #00F5D4;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.75rem;
            font-weight: 700;
            padding: 4px 12px;
            border-radius: 999px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }

        .pulse-dot {
            width: 8px;
            height: 8px;
            background-color: #00F5D4;
            border-radius: 50%;
            box-shadow: 0 0 10px #00F5D4;
            display: inline-block;
        }

        .tv-title {
            font-family: 'Orbitron', sans-serif;
            font-size: 1.85rem;
            font-weight: 900;
            color: #F8FAFC;
            margin: 6px 0 4px 0;
            text-shadow: 0 0 18px rgba(0, 245, 212, 0.25);
            letter-spacing: 0.07em;
        }

        .tv-subtitle {
            color: #94A3B8;
            font-size: 0.90rem;
            margin: 0;
        }

        .tv-telemetry-strip {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-top: 14px;
            padding-top: 12px;
            border-top: 1px solid rgba(148, 163, 184, 0.14);
        }

        .telemetry-pill {
            background: rgba(5, 8, 17, 0.72);
            border: 1px solid rgba(148, 163, 184, 0.22);
            border-radius: 8px;
            padding: 5px 11px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.74rem;
            color: #CBD5E1;
        }

        .telemetry-pill strong {
            color: #00F5D4;
        }

        /* Sección Header */
        .section-banner {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin: 22px 0 14px 0;
            padding-bottom: 8px;
            border-bottom: 1px solid rgba(0, 245, 212, 0.22);
        }

        .section-banner-title {
            font-family: 'Orbitron', sans-serif;
            font-size: 1.12rem;
            font-weight: 800;
            color: #F8FAFC;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .section-banner-tag {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.73rem;
            color: #00F5D4;
            background: rgba(0, 245, 212, 0.08);
            border: 1px solid rgba(0, 245, 212, 0.25);
            padding: 3px 10px;
            border-radius: 6px;
        }

        /* Tarjetas de Radar Ejecutivo (Top Picks) */
        .radar-card {
            background: linear-gradient(155deg, rgba(16, 25, 48, 0.85) 0%, rgba(9, 14, 28, 0.92) 100%);
            border: 1px solid rgba(0, 245, 212, 0.25);
            border-radius: 14px;
            padding: 18px 18px 16px 18px;
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            box-shadow: 0 8px 28px rgba(0, 0, 0, 0.45);
            position: relative;
            overflow: hidden;
            height: 100%;
            min-height: 198px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }

        .radar-card.lock-card { border-top: 3px solid #00F5D4; }
        .radar-card.spread-card { border-top: 3px solid #38BDF8; }
        .radar-card.total-card { border-top: 3px solid #F59E0B; }
        .radar-card.prop-card { border-top: 3px solid #8B5CF6; }

        .radar-tag {
            font-family: 'Orbitron', sans-serif;
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #94A3B8;
            margin-bottom: 8px;
        }

        .radar-pick-main {
            font-family: 'Orbitron', sans-serif;
            font-size: 1.12rem;
            font-weight: 800;
            color: #F8FAFC;
            line-height: 1.25;
            margin-bottom: 6px;
        }

        .radar-prob-big {
            font-family: 'JetBrains Mono', monospace;
            font-size: 1.58rem;
            font-weight: 800;
            color: #00F5D4;
            line-height: 1.1;
            margin: 4px 0 8px 0;
        }

        .radar-meta {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.74rem;
            color: #CBD5E1;
            background: rgba(5, 8, 17, 0.65);
            border: 1px solid rgba(148, 163, 184, 0.16);
            border-radius: 8px;
            padding: 7px 10px;
        }

        /* =====================================================================
           VISTA A: TARJETAS DE CUADRÍCULA 3x3 (GRID GLASSMORPHISM CYBER-QUANT)
           ===================================================================== */
        .grid-game-card {
            background: linear-gradient(155deg, rgba(14, 22, 44, 0.88) 0%, rgba(8, 13, 26, 0.94) 100%);
            border: 1px solid rgba(0, 245, 212, 0.24);
            border-radius: 16px;
            padding: 16px 18px 14px 18px;
            margin-bottom: 10px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.50), inset 0 1px 0 rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            transition: transform 0.18s ease, border-color 0.18s ease;
        }

        .grid-game-card:hover {
            border-color: rgba(0, 245, 212, 0.55);
            box-shadow: 0 12px 34px rgba(0, 245, 212, 0.12);
        }

        .grid-card-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid rgba(148, 163, 184, 0.14);
        }

        .grid-league-badge {
            font-family: 'Orbitron', sans-serif;
            font-size: 0.66rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            color: #00F5D4;
            background: rgba(0, 245, 212, 0.10);
            border: 1px solid rgba(0, 245, 212, 0.30);
            padding: 3px 9px;
            border-radius: 999px;
        }

        .grid-time-badge {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.71rem;
            color: #94A3B8;
            font-weight: 600;
        }

        .grid-team-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 7px 10px;
            margin-bottom: 6px;
            background: rgba(5, 8, 17, 0.60);
            border: 1px solid rgba(148, 163, 184, 0.12);
            border-radius: 10px;
        }

        .grid-team-info {
            display: flex;
            align-items: center;
            gap: 4px;
        }

        .grid-team-abbr {
            font-family: 'Orbitron', sans-serif;
            font-size: 0.92rem;
            font-weight: 800;
            color: #F8FAFC;
            margin-right: 6px;
        }

        .grid-team-fullname {
            font-family: 'Inter', sans-serif;
            font-size: 0.78rem;
            color: #94A3B8;
            font-weight: 500;
        }

        .form-pills-wrap {
            display: flex;
            align-items: center;
            gap: 3px;
        }

        .form-pill-w {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.62rem;
            font-weight: 800;
            color: #050811;
            background: #10B981;
            padding: 1px 5px;
            border-radius: 4px;
        }

        .form-pill-l {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.62rem;
            font-weight: 800;
            color: #F8FAFC;
            background: rgba(244, 63, 94, 0.78);
            padding: 1px 5px;
            border-radius: 4px;
        }

        .grid-quick-forecast {
            margin-top: 10px;
            padding: 9px 12px;
            background: linear-gradient(90deg, rgba(0, 245, 212, 0.08) 0%, rgba(56, 189, 248, 0.08) 100%);
            border: 1px solid rgba(56, 189, 248, 0.28);
            border-radius: 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.76rem;
        }

        .grid-forecast-lines {
            color: #F8FAFC;
            font-weight: 800;
        }

        .grid-forecast-win {
            color: #00F5D4;
            font-weight: 700;
            font-size: 0.72rem;
        }

        /* =====================================================================
           VISTA B: EXPEDIENTE DETALLADO Y SCOREBOARD TV HEADER (LOGOS 64PX)
           ===================================================================== */
        .game-glass-wrapper {
            background: linear-gradient(165deg, rgba(13, 21, 40, 0.86) 0%, rgba(7, 12, 24, 0.94) 100%);
            border: 1px solid rgba(0, 245, 212, 0.26);
            border-radius: 18px;
            padding: 22px 24px;
            margin-bottom: 28px;
            box-shadow: 0 14px 40px rgba(0, 0, 0, 0.55), inset 0 1px 0 rgba(255, 255, 255, 0.06);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
        }

        .scoreboard-tv-header {
            background: linear-gradient(90deg, rgba(6, 10, 22, 0.92) 0%, rgba(15, 25, 48, 0.92) 50%, rgba(6, 10, 22, 0.92) 100%);
            border: 1px solid rgba(56, 189, 248, 0.28);
            border-radius: 14px;
            padding: 18px 24px;
            margin-bottom: 18px;
            display: grid;
            grid-template-columns: 1.25fr 1fr 1.25fr;
            align-items: center;
            gap: 14px;
        }

        .sb-team-block {
            display: flex;
            align-items: center;
            gap: 14px;
        }

        .sb-team-block.right {
            justify-content: flex-end;
            text-align: right;
        }

        .team-logo-box-64 {
            width: 72px;
            height: 72px;
            border-radius: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 6px 20px rgba(0, 0, 0, 0.50);
            flex-shrink: 0;
            padding: 4px;
        }

        .team-logo-box-64 img {
            margin-right: 0 !important;
        }

        .sb-team-name {
            font-family: 'Orbitron', sans-serif;
            font-size: 1.18rem;
            font-weight: 800;
            color: #F8FAFC;
            margin: 0;
        }

        .sb-team-metrics {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.75rem;
            color: #94A3B8;
            margin-top: 4px;
        }

        .sb-center-console {
            text-align: center;
            background: rgba(5, 8, 17, 0.78);
            border: 1px solid rgba(0, 245, 212, 0.26);
            border-radius: 12px;
            padding: 10px 14px;
        }

        .sb-proj-score {
            font-family: 'JetBrains Mono', monospace;
            font-size: 1.42rem;
            font-weight: 800;
            color: #00F5D4;
            letter-spacing: 0.04em;
        }

        .sb-lines-row {
            display: flex;
            justify-content: center;
            gap: 10px;
            flex-wrap: wrap;
            margin-top: 6px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.73rem;
            color: #CBD5E1;
        }

        .sb-chip {
            background: rgba(56, 189, 248, 0.12);
            border: 1px solid rgba(56, 189, 248, 0.30);
            padding: 2px 8px;
            border-radius: 6px;
            color: #38BDF8;
            font-weight: 600;
        }

        /* Sub-filas dentro del partido */
        .row-label-bar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin: 14px 0 10px 0;
            padding: 6px 12px;
            background: rgba(255, 255, 255, 0.03);
            border-left: 3px solid #00F5D4;
            border-radius: 4px 8px 8px 4px;
        }

        .row-label-title {
            font-family: 'Orbitron', sans-serif;
            font-size: 0.82rem;
            font-weight: 700;
            color: #E2E8F0;
            letter-spacing: 0.07em;
            text-transform: uppercase;
        }

        .row-label-sub {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.72rem;
            color: #94A3B8;
        }

        /* Tarjetas internas de simulación y táctica */
        .quant-subcard {
            background: rgba(9, 14, 28, 0.78);
            border: 1px solid rgba(148, 163, 184, 0.16);
            border-radius: 12px;
            padding: 14px 16px;
            height: 100%;
        }

        .quant-subcard-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-family: 'Orbitron', sans-serif;
            font-size: 0.76rem;
            font-weight: 700;
            color: #94A3B8;
            margin-bottom: 10px;
            letter-spacing: 0.06em;
        }

        .sim-stat-line {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            margin-bottom: 6px;
            font-family: 'JetBrains Mono', monospace;
        }

        .sim-team-label {
            font-size: 0.85rem;
            font-weight: 700;
            color: #F8FAFC;
        }

        .sim-prob-val {
            font-size: 1.08rem;
            font-weight: 800;
            color: #00F5D4;
        }

        .sim-odds-badge {
            font-size: 0.72rem;
            color: #CBD5E1;
            background: rgba(255, 255, 255, 0.06);
            padding: 2px 7px;
            border-radius: 5px;
            margin-left: 6px;
        }

        /* Barra de progreso cuantitativa */
        .quant-bar-track {
            width: 100%;
            height: 8px;
            background: rgba(30, 41, 59, 0.85);
            border-radius: 999px;
            overflow: hidden;
            margin: 8px 0;
            display: flex;
        }

        .quant-bar-fill-left {
            height: 100%;
            background: linear-gradient(90deg, #38BDF8, #00F5D4);
        }

        .quant-bar-fill-right {
            height: 100%;
            background: linear-gradient(90deg, #8B5CF6, #F43F5E);
        }

        /* Fila 2: Condiciones de Victoria */
        .win-cond-card {
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.08) 0%, rgba(9, 14, 28, 0.85) 100%);
            border: 1px solid rgba(16, 185, 129, 0.28);
            border-radius: 11px;
            padding: 12px 15px;
            height: 100%;
        }

        .win-cond-title {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.72rem;
            color: #10B981;
            text-transform: uppercase;
            font-weight: 700;
            margin-bottom: 4px;
        }

        .win-cond-statement {
            font-family: 'Inter', sans-serif;
            font-size: 0.92rem;
            font-weight: 700;
            color: #F8FAFC;
            margin-bottom: 4px;
        }

        .win-cond-meta {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.72rem;
            color: #94A3B8;
        }

        /* Fila 3: Matchup Táctico PPP */
        .tactical-ppp-box {
            background: rgba(9, 14, 28, 0.82);
            border: 1px solid rgba(56, 189, 248, 0.20);
            border-radius: 12px;
            padding: 13px 16px;
            height: 100%;
        }

        .edge-pill-pos {
            background: rgba(16, 185, 129, 0.14);
            border: 1px solid rgba(16, 185, 129, 0.40);
            color: #10B981;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.70rem;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 999px;
        }

        .edge-pill-neg {
            background: rgba(244, 63, 94, 0.14);
            border: 1px solid rgba(244, 63, 94, 0.40);
            color: #F43F5E;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.70rem;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 999px;
        }

        .edge-pill-neu {
            background: rgba(245, 158, 11, 0.14);
            border: 1px solid rgba(245, 158, 11, 0.40);
            color: #F59E0B;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.70rem;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 999px;
        }

        /* Fila 4: Player Props Cards */
        .prop-player-card {
            background: linear-gradient(150deg, rgba(17, 24, 46, 0.86) 0%, rgba(8, 12, 24, 0.94) 100%);
            border: 1px solid rgba(139, 92, 246, 0.28);
            border-radius: 12px;
            padding: 13px 15px;
            height: 100%;
        }

        .prop-player-name {
            font-family: 'Orbitron', sans-serif;
            font-size: 0.88rem;
            font-weight: 800;
            color: #F8FAFC;
        }

        .prop-lean-over {
            color: #00F5D4;
            font-family: 'JetBrains Mono', monospace;
            font-weight: 800;
            font-size: 0.96rem;
        }

        .prop-lean-under {
            color: #F59E0B;
            font-family: 'JetBrains Mono', monospace;
            font-weight: 800;
            font-size: 0.96rem;
        }

        /* Estilo para los expanders */
        div[data-testid="stExpander"] {
            background: rgba(11, 18, 35, 0.82);
            border: 1px solid rgba(0, 245, 212, 0.25);
            border-radius: 14px;
            margin-bottom: 14px;
        }

        .slate-slot-badge {
            font-family: 'Orbitron', sans-serif;
            font-size: 0.74rem;
            font-weight: 800;
            color: #00F5D4;
            background: rgba(0, 245, 212, 0.10);
            border: 1px solid rgba(0, 245, 212, 0.28);
            border-radius: 6px;
            padding: 4px 10px;
            display: inline-block;
            margin-bottom: 6px;
        }

        @media (max-width: 900px) {
            .scoreboard-tv-header {
                grid-template-columns: 1fr;
                text-align: center;
            }
            .sb-team-block, .sb-team-block.right {
                justify-content: center;
                text-align: center;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ==============================================================================
# UTILIDADES DE CARGA DE DATOS Y CONVERSIÓN DE CUOTAS (FAIR ODDS)
# ==============================================================================
def prob_to_fair_odds(prob: float) -> Tuple[str, str]:
    """Convierte una probabilidad (0-1) a cuota justa Decimal y Americana."""
    p = float(np.clip(prob, 0.01, 0.99))
    dec_odds = 1.0 / p
    if p >= 0.5:
        amer = -int(round((p / (1.0 - p)) * 100))
        amer_str = f"{amer}"
    else:
        amer = int(round(((1.0 - p) / p) * 100))
        amer_str = f"+{amer}"
    return f"{dec_odds:.2f}", amer_str


def round_to_half_point(val: float) -> float:
    """Redondea cualquier línea proyectada al medio punto (.5) más cercano estilo Sportsbook."""
    return float(np.floor(val) + 0.5)


def load_clean_nba_dataframe(uploaded_file=None) -> Tuple[pd.DataFrame, str]:
    """Carga el CSV original limpio nba_stats_completo.csv (30 equipos)."""
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
                return df.copy(), f"CSV Oficial ({path.name} - {len(df)} equipos)"

    df = pd.DataFrame(DEFAULT_CSV_DATA)
    try:
        df.to_csv("nba_stats_completo.csv", index=False, encoding="utf-8")
    except OSError:
        pass
    return df.copy(), f"Dataset Oficial nba_stats_completo.csv ({len(df)} equipos)"


def render_form_pills_html(team_abbr: str) -> str:
    """Genera las pastillas visuales W/L de forma reciente para cada equipo en el Grid 3x3."""
    form_list = TEAM_RECENT_FORM.get(str(team_abbr).upper(), ["W", "L", "W", "L", "W"])
    pills = []
    for item in form_list:
        cls = "form-pill-w" if item == "W" else "form-pill-l"
        pills.append(f'<span class="{cls}">{item}</span>')
    return f'<div class="form-pills-wrap">{"".join(pills)}</div>'


# ==============================================================================
# MOTOR CUANTITATIVO MONTE CARLO BASADO EN POSESIONES (5,000 ITERACIONES)
# ==============================================================================
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
) -> Dict:
    """
    Motor de varianza para Player Props:
    Ajusta la proyección de puntos de la estrella según:
    1) El ritmo proyectado del partido vs el ritmo habitual del equipo.
    2) La eficiencia defensiva del rival contra el estilo primario del jugador (ISO o PNR).
    3) El Def_Rtg global del rival frente a la media NBA.
    """
    n_sims = len(poss_sim)
    pace_factor = exp_pace / max(team_pace, 85.0)

    league_style_avg = LEAGUE_AVG_ISO_PPP if style.upper() == "ISO" else LEAGUE_AVG_PNR_PPP
    style_def_ratio = opp_style_def_ppp / league_style_avg
    off_synergy_ratio = team_style_off_ppp / league_style_avg
    style_multiplier = 1.0 + 0.58 * (style_def_ratio - 1.0) + 0.18 * (off_synergy_ratio - 1.0)

    team_def_multiplier = 1.0 + 0.30 * ((opp_def_rtg - LEAGUE_AVG_ORTG) / LEAGUE_AVG_ORTG)

    adjusted_ppg = base_ppg * pace_factor * style_multiplier * team_def_multiplier

    # Escalamos cada iteración por la fluctuación de posesiones del partido simulado
    iter_pace_scale = poss_sim / exp_pace
    iter_mean = adjusted_ppg * iter_pace_scale

    eff_std = player_std * np.sqrt(pace_factor)
    sim_pts = rng.normal(loc=iter_mean, scale=eff_std, size=n_sims)
    sim_pts = np.clip(sim_pts, 0.0, None)

    prob_over = float(np.mean(sim_pts > prop_line))
    prob_under = 1.0 - prob_over

    if prob_over >= prob_under:
        lean_side = "OVER"
        lean_prob = prob_over
    else:
        lean_side = "UNDER"
        lean_prob = prob_under

    dec_odds, amer_odds = prob_to_fair_odds(lean_prob)
    edge_pts = adjusted_ppg - prop_line

    style_label = "Iso_PPP_Def" if style.upper() == "ISO" else "PnR_PPP_Def"
    matchup_note = (
        f"vs {opp_abbr} {style_label} ({opp_style_def_ppp:.2f} PPP) | "
        f"DefRtg {opp_def_rtg:.1f}"
    )

    return {
        "player_name": player_name,
        "team_abbr": team_abbr,
        "opp_abbr": opp_abbr,
        "style": style.upper(),
        "base_ppg": float(base_ppg),
        "proj_ppg": float(np.mean(sim_pts)),
        "prop_line": float(prop_line),
        "prob_over": prob_over,
        "prob_under": prob_under,
        "lean_side": lean_side,
        "lean_prob": lean_prob,
        "fair_dec": dec_odds,
        "fair_amer": amer_odds,
        "edge_pts": float(edge_pts),
        "p25": float(np.percentile(sim_pts, 25)),
        "p75": float(np.percentile(sim_pts, 75)),
        "matchup_note": matchup_note,
    }


def run_monte_carlo_matchup(
    away_row: pd.Series,
    home_row: pd.Series,
    n_sims: int = 5000,
    hfa_pts: float = 2.5,
    custom_spread_home: Optional[float] = None,
    custom_total_line: Optional[float] = None,
    seed: int = 42,
) -> Dict:
    """
    Ejecuta 5,000 iteraciones de Monte Carlo basadas en posesiones para un partido NBA
    consumiendo estrictamente las filas vigentes de st.session_state.df_nba.
    """
    rng = np.random.default_rng(seed)

    # 1. Calcular Posesiones Esperadas (Promedio de Pace de ambos equipos)
    away_pace = float(away_row["Pace"])
    home_pace = float(home_row["Pace"])
    exp_possessions = (away_pace + home_pace) / 2.0

    # 2. Calcular Eficiencia Base (Off_Rtg ajustado contra Def_Rtg rival con regresión NBA)
    away_base_ortg = float(away_row["Off_Rtg"]) + 0.58 * (float(home_row["Def_Rtg"]) - LEAGUE_AVG_ORTG)
    home_base_ortg = float(home_row["Off_Rtg"]) + 0.58 * (float(away_row["Def_Rtg"]) - LEAGUE_AVG_ORTG)

    # Línea de apertura del mercado (basada en ratings macro vigentes)
    mkt_away_pts = (exp_possessions / 100.0) * away_base_ortg - (hfa_pts / 2.0)
    mkt_home_pts = (exp_possessions / 100.0) * home_base_ortg + (hfa_pts / 2.0)
    default_market_spread_home = np.floor(-(mkt_home_pts - mkt_away_pts)) + 0.5
    default_market_total = np.floor(mkt_home_pts + mkt_away_pts) + 0.5

    # Ajuste Táctico Sharp: Estilos (Iso PPP & PnR PPP) + Cuidado de Balón (TOV_Pct)
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

    spread_line_home = (
        float(custom_spread_home)
        if custom_spread_home is not None
        else float(default_market_spread_home)
    )
    spread_line_away = -spread_line_home

    total_line = (
        float(custom_total_line)
        if custom_total_line is not None
        else float(default_market_total)
    )

    # 3. Simulación Monte Carlo de 5,000 iteraciones en NumPy
    poss_sim = rng.normal(loc=exp_possessions, scale=2.75, size=n_sims)
    poss_sim = np.clip(poss_sim, 86.0, 114.0)

    # Varianza de eficiencia por 100 posesiones (mayor 3PA_Rate incrementa la desviación estándar)
    away_ortg_std = 9.2 * (1.0 + 0.35 * (float(away_row["3PA_Rate"]) - 0.38))
    home_ortg_std = 9.2 * (1.0 + 0.35 * (float(home_row["3PA_Rate"]) - 0.38))

    away_ortg_sim = rng.normal(loc=away_adj_ortg, scale=away_ortg_std, size=n_sims)
    home_ortg_sim = rng.normal(loc=home_adj_ortg, scale=home_ortg_std, size=n_sims)

    away_pts_sim = (poss_sim / 100.0) * away_ortg_sim - (hfa_pts / 2.0)
    home_pts_sim = (poss_sim / 100.0) * home_ortg_sim + (hfa_pts / 2.0)

    # Simulación explícita de triples anotados (3PM) y pérdidas (TOV) correlacionados con la eficiencia
    away_3pa_sim = np.clip(
        rng.normal(poss_sim * float(away_row["3PA_Rate"]) * 0.92, 4.0, size=n_sims),
        18,
        60,
    ).astype(int)
    home_3pa_sim = np.clip(
        rng.normal(poss_sim * float(home_row["3PA_Rate"]) * 0.92, 4.0, size=n_sims),
        18,
        60,
    ).astype(int)

    away_3p_pct_base = float(away_row.get("3P_Pct", 0.368))
    home_3p_pct_base = float(home_row.get("3P_Pct", 0.368))

    away_z = (away_ortg_sim - away_adj_ortg) / away_ortg_std
    home_z = (home_ortg_sim - home_adj_ortg) / home_ortg_std

    away_3p_prob_sim = np.clip(away_3p_pct_base + 0.032 * away_z, 0.18, 0.58)
    home_3p_prob_sim = np.clip(home_3p_pct_base + 0.032 * home_z, 0.18, 0.58)

    away_3pm_sim = rng.binomial(n=away_3pa_sim, p=away_3p_prob_sim)
    home_3pm_sim = rng.binomial(n=home_3pa_sim, p=home_3p_prob_sim)

    away_tov_sim = np.clip(
        rng.normal(
            loc=(poss_sim / 100.0) * float(away_row["TOV_Pct"]) - 0.85 * away_z,
            scale=2.2,
            size=n_sims,
        ),
        4.0,
        28.0,
    )
    home_tov_sim = np.clip(
        rng.normal(
            loc=(poss_sim / 100.0) * float(home_row["TOV_Pct"]) - 0.85 * home_z,
            scale=2.2,
            size=n_sims,
        ),
        4.0,
        28.0,
    )

    # Resolución de empates en regulación (Prórroga / OT en NBA)
    margin_sim = home_pts_sim - away_pts_sim
    ties_mask = np.abs(margin_sim) < 0.5
    if np.any(ties_mask):
        ot_diff = rng.normal(loc=0.35, scale=4.2, size=int(np.sum(ties_mask)))
        ot_diff = np.where(ot_diff >= 0, np.maximum(ot_diff, 1.0), np.minimum(ot_diff, -1.0))
        home_pts_sim[ties_mask] += np.maximum(ot_diff, 0) + 8.0
        away_pts_sim[ties_mask] += np.maximum(-ot_diff, 0) + 8.0
        margin_sim = home_pts_sim - away_pts_sim

    total_pts_sim = home_pts_sim + away_pts_sim

    # Probabilidades Moneyline
    home_win_prob = float(np.mean(margin_sim > 0))
    away_win_prob = 1.0 - home_win_prob
    home_ml_dec, home_ml_amer = prob_to_fair_odds(home_win_prob)
    away_ml_dec, away_ml_amer = prob_to_fair_odds(away_win_prob)

    # Probabilidades de cubrir el Spread (home_pts + spread_line_home > away_pts)
    home_cover_prob = float(np.mean((home_pts_sim + spread_line_home) > away_pts_sim))
    away_cover_prob = 1.0 - home_cover_prob
    home_sp_dec, home_sp_amer = prob_to_fair_odds(home_cover_prob)
    away_sp_dec, away_sp_amer = prob_to_fair_odds(away_cover_prob)

    # Probabilidades de Over / Under
    over_prob = float(np.mean(total_pts_sim > total_line))
    under_prob = 1.0 - over_prob
    over_dec, over_amer = prob_to_fair_odds(over_prob)
    under_dec, under_amer = prob_to_fair_odds(under_prob)

    # Identificación del Favorito y Condiciones de Victoria (Fila 2)
    fav_is_home = home_win_prob >= away_win_prob
    fav_abbr = str(home_row["Team_Abbr"]) if fav_is_home else str(away_row["Team_Abbr"])
    fav_name = str(home_row["Team"]) if fav_is_home else str(away_row["Team"])
    fav_base_win = home_win_prob if fav_is_home else away_win_prob
    fav_win_mask = (margin_sim > 0) if fav_is_home else (margin_sim < 0)
    fav_3pm_arr = home_3pm_sim if fav_is_home else away_3pm_sim
    fav_tov_arr = home_tov_sim if fav_is_home else away_tov_sim
    fav_ortg_arr = home_ortg_sim if fav_is_home else away_ortg_sim

    # Umbral de triples (mediana redonda de triples del favorito)
    threepm_threshold = int(np.round(np.percentile(fav_3pm_arr, 52)))
    mask_3pm = fav_3pm_arr > threepm_threshold
    win_given_3pm = float(np.mean(fav_win_mask[mask_3pm])) if np.any(mask_3pm) else fav_base_win

    # Umbral de pérdidas (percentil 48 de TOV del favorito)
    tov_threshold = int(np.round(np.percentile(fav_tov_arr, 48)))
    mask_tov = fav_tov_arr < tov_threshold
    win_given_tov = float(np.mean(fav_win_mask[mask_tov])) if np.any(mask_tov) else fav_base_win

    # Umbral de Eficiencia Ofensiva en el juego
    ortg_threshold = round(float(np.percentile(fav_ortg_arr, 50)), 1)
    mask_ortg = fav_ortg_arr > ortg_threshold
    win_given_ortg = float(np.mean(fav_win_mask[mask_ortg])) if np.any(mask_ortg) else fav_base_win

    # 4. Simulación de Player Props para Star1 y Star2 de ambos equipos (Fila 4)
    props_list = []
    for side_row, opp_row, is_home_player in [(away_row, home_row, False), (home_row, away_row, True)]:
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

            if s_style == "ISO":
                t_style_off = float(side_row["Iso_PPP_Off"])
                o_style_def = float(opp_row["Iso_PPP_Def"])
            else:
                t_style_off = float(side_row["PnR_PPP_Off"])
                o_style_def = float(opp_row["PnR_PPP_Def"])

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
            )
            prop_res["matchup_label"] = f"{away_row['Team_Abbr']} @ {home_row['Team_Abbr']}"
            props_list.append(prop_res)

    return {
        "matchup_id": f"{away_row['Team_Abbr']}@{home_row['Team_Abbr']}",
        "matchup_title": f"{away_row['Team']} @ {home_row['Team']}",
        "away_team": str(away_row["Team"]),
        "away_abbr": str(away_row["Team_Abbr"]),
        "home_team": str(home_row["Team"]),
        "home_abbr": str(home_row["Team_Abbr"]),
        "away_row": away_row,
        "home_row": home_row,
        "n_sims": n_sims,
        "exp_possessions": exp_possessions,
        "exp_away_pts": float(np.mean(away_pts_sim)),
        "exp_home_pts": float(np.mean(home_pts_sim)),
        "exp_margin_home": float(np.mean(margin_sim)),
        "exp_total_pts": float(np.mean(total_pts_sim)),
        "proj_spread_home": -float(np.mean(margin_sim)),
        "spread_line_home": spread_line_home,
        "spread_line_away": spread_line_away,
        "total_line": total_line,
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
        "props": props_list,
    }


# ==============================================================================
# COMPONENTES DE RENDERIZADO VISUAL (RADAR EJECUTIVO, GRID 3x3 & VISTA DETALLE)
# ==============================================================================
def extract_executive_radar(sim_results: List[Dict]) -> Dict:
    """Extrae los 4 Top Picks automáticos evaluando únicamente los partidos seleccionados en la jornada."""
    best_ml = None
    for res in sim_results:
        candidates = [
            (
                res["home_team"],
                res["home_abbr"],
                res["home_win_prob"],
                res["home_ml_dec"],
                res["home_ml_amer"],
                f"vs {res['away_abbr']} (Local)",
                res["exp_home_pts"] - res["exp_away_pts"],
            ),
            (
                res["away_team"],
                res["away_abbr"],
                res["away_win_prob"],
                res["away_ml_dec"],
                res["away_ml_amer"],
                f"@ {res['home_abbr']} (Visita)",
                res["exp_away_pts"] - res["exp_home_pts"],
            ),
        ]
        for cand in candidates:
            if best_ml is None or cand[2] > best_ml["prob"]:
                best_ml = {
                    "team": cand[0],
                    "abbr": cand[1],
                    "prob": cand[2],
                    "dec": cand[3],
                    "amer": cand[4],
                    "context": cand[5],
                    "proj_margin": cand[6],
                }

    best_spread = None
    for res in sim_results:
        h_line_str = f"{res['spread_line_home']:+.1f}"
        a_line_str = f"{res['spread_line_away']:+.1f}"
        candidates = [
            (
                f"{res['home_team']} {h_line_str}",
                res["home_abbr"],
                res["home_cover_prob"],
                res["home_sp_dec"],
                res["home_sp_amer"],
                f"{res['away_abbr']} @ {res['home_abbr']} | Margen Proy: {-res['proj_spread_home']:+.1f}",
            ),
            (
                f"{res['away_team']} {a_line_str}",
                res["away_abbr"],
                res["away_cover_prob"],
                res["away_sp_dec"],
                res["away_sp_amer"],
                f"{res['away_abbr']} @ {res['home_abbr']} | Margen Proy: {res['proj_spread_home']:+.1f}",
            ),
        ]
        for cand in candidates:
            if best_spread is None or cand[2] > best_spread["prob"]:
                best_spread = {
                    "pick": cand[0],
                    "abbr": cand[1],
                    "prob": cand[2],
                    "dec": cand[3],
                    "amer": cand[4],
                    "context": cand[5],
                }

    best_total = None
    for res in sim_results:
        candidates = [
            (
                f"OVER {res['total_line']:.1f} Pts",
                res["home_abbr"],
                res["over_prob"],
                res["over_dec"],
                res["over_amer"],
                f"{res['away_abbr']} @ {res['home_abbr']} | Total Proy: {res['exp_total_pts']:.1f}",
            ),
            (
                f"UNDER {res['total_line']:.1f} Pts",
                res["home_abbr"],
                res["under_prob"],
                res["under_dec"],
                res["under_amer"],
                f"{res['away_abbr']} @ {res['home_abbr']} | Total Proy: {res['exp_total_pts']:.1f}",
            ),
        ]
        for cand in candidates:
            if best_total is None or cand[2] > best_total["prob"]:
                best_total = {
                    "pick": cand[0],
                    "abbr": cand[1],
                    "prob": cand[2],
                    "dec": cand[3],
                    "amer": cand[4],
                    "context": cand[5],
                }

    best_prop = None
    for res in sim_results:
        for prop in res["props"]:
            if best_prop is None or prop["lean_prob"] > best_prop["lean_prob"]:
                best_prop = prop

    return {
        "lock": best_ml,
        "spread": best_spread,
        "total": best_total,
        "prop": best_prop,
    }


def render_executive_radar(radar: Dict, games_count: int, n_sims: int) -> None:
    st.markdown(
        f"""
        <div class="section-banner">
            <div class="section-banner-title">📡 RADAR EJECUTIVO DE LA JORNADA // TOP SYNDICATE PICKS</div>
            <div class="section-banner-tag">EVALUANDO {games_count} PARTIDO(S) &bull; {games_count * n_sims:,} SIMULACIONES</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)

    lock = radar["lock"]
    with c1:
        st.markdown(
            f"""
            <div class="radar-card lock-card">
                <div>
                    <div class="radar-tag">🔒 1. EL LOCK DE LA NOCHE</div>
                    <div class="radar-pick-main">{escudo_nba_html(lock['abbr'], 26)}{lock['team']} ML</div>
                    <div class="radar-prob-big">{lock['prob'] * 100:.1f}% WIN</div>
                </div>
                <div class="radar-meta">
                    Fair Odds: <strong>{lock['dec']} ({lock['amer']})</strong><br/>
                    {lock['context']} | Dif: {lock['proj_margin']:+.1f} pts
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    sp = radar["spread"]
    with c2:
        st.markdown(
            f"""
            <div class="radar-card spread-card">
                <div>
                    <div class="radar-tag">⚡ 2. EL REY DEL SPREAD</div>
                    <div class="radar-pick-main">{escudo_nba_html(sp['abbr'], 26)}{sp['pick']}</div>
                    <div class="radar-prob-big" style="color: #38BDF8;">{sp['prob'] * 100:.1f}% COVER</div>
                </div>
                <div class="radar-meta">
                    Fair Odds: <strong>{sp['dec']} ({sp['amer']})</strong><br/>
                    {sp['context']}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    tot = radar["total"]
    with c3:
        st.markdown(
            f"""
            <div class="radar-card total-card">
                <div>
                    <div class="radar-tag">🎯 3. LA FIJA DE PUNTOS</div>
                    <div class="radar-pick-main">{escudo_nba_html(tot['abbr'], 26)}{tot['pick']}</div>
                    <div class="radar-prob-big" style="color: #F59E0B;">{tot['prob'] * 100:.1f}% HIT</div>
                </div>
                <div class="radar-meta">
                    Fair Odds: <strong>{tot['dec']} ({tot['amer']})</strong><br/>
                    {tot['context']}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    pr = radar["prop"]
    with c4:
        lean_word = "Over" if pr["lean_side"] == "OVER" else "Under"
        st.markdown(
            f"""
            <div class="radar-card prop-card">
                <div>
                    <div class="radar-tag">🏀 4. PLAYER PROP LEAN</div>
                    <div class="radar-pick-main">{escudo_nba_html(pr['team_abbr'], 26)}{pr['player_name']} {lean_word} {pr['prop_line']:.1f}</div>
                    <div class="radar-prob-big" style="color: #A78BFA;">{pr['lean_prob'] * 100:.1f}% ({pr['lean_side']})</div>
                </div>
                <div class="radar-meta">
                    Proyección: <strong>{pr['proj_ppg']:.1f} Pts</strong> | Fair: {pr['fair_dec']} ({pr['fair_amer']})<br/>
                    {pr['matchup_note']}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_slate_grid_3x3(sim_results: List[Dict]) -> None:
    """
    3. VISTA A: CARTELERA EN CUADRÍCULA (Grid de 3 Columnas)
    Renderiza cada partido con diseño Glassmorphism Cyber-Quant, escudos oficiales de 32px,
    pastillas W/L, pronóstico rápido de Spread y Total y botón "LEER ANÁLISIS →".
    """
    st.markdown(
        f"""
        <div class="section-banner">
            <div class="section-banner-title">🗓️ CARTELERA NBA EN CUADRÍCULA // {len(sim_results)} JUEGO(S) EN ESCANEO</div>
            <div class="section-banner-tag">SELECCIONA UN PARTIDO PARA ABRIR SU EXPEDIENTE CUANTITATIVO</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    for row_start in range(0, len(sim_results), 3):
        cols = st.columns(3)
        row_slice = sim_results[row_start : row_start + 3]

        for col_idx, res in enumerate(row_slice):
            global_idx = row_start + col_idx
            away_abbr = res["away_abbr"]
            home_abbr = res["home_abbr"]
            est_time = GAME_SLATE_TIMES[global_idx % len(GAME_SLATE_TIMES)]

            # Línea de Spread proyectada redondeada a .5 para el pronóstico rápido
            proj_spread_half = round_to_half_point(abs(res["proj_spread_home"]) - 0.5)
            if res["proj_spread_home"] <= 0:
                quick_spread_str = f"{home_abbr} -{proj_spread_half:.1f}"
            else:
                quick_spread_str = f"{away_abbr} -{proj_spread_half:.1f}"

            quick_total_half = round_to_half_point(res["exp_total_pts"])
            fav_win_pct = res["fav_base_win"] * 100.0

            away_logo_32 = escudo_nba_html(away_abbr, size=32)
            home_logo_32 = escudo_nba_html(home_abbr, size=32)
            away_pills = render_form_pills_html(away_abbr)
            home_pills = render_form_pills_html(home_abbr)

            with cols[col_idx]:
                st.markdown(
                    f"""
                    <div class="grid-game-card">
                        <div class="grid-card-top">
                            <span class="grid-league-badge">NBA &middot; REGULAR SEASON</span>
                            <span class="grid-time-badge">🕒 {est_time}</span>
                        </div>
                        <div class="grid-team-row">
                            <div class="grid-team-info">
                                {away_logo_32}
                                <div>
                                    <span class="grid-team-abbr">{away_abbr}</span>
                                    <span class="grid-team-fullname">{res['away_team']}</span>
                                </div>
                            </div>
                            {away_pills}
                        </div>
                        <div class="grid-team-row">
                            <div class="grid-team-info">
                                {home_logo_32}
                                <div>
                                    <span class="grid-team-abbr">{home_abbr}</span>
                                    <span class="grid-team-fullname">{res['home_team']}</span>
                                </div>
                            </div>
                            {home_pills}
                        </div>
                        <div class="grid-quick-forecast">
                            <span class="grid-forecast-lines">{quick_spread_str} &nbsp;|&nbsp; O/U {quick_total_half:.1f}</span>
                            <span class="grid-forecast-win">{res['fav_abbr']} {fav_win_pct:.1f}% WIN</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if st.button(
                    "LEER ANÁLISIS →",
                    key=f"btn_open_game_{global_idx}_{away_abbr}_{home_abbr}",
                    use_container_width=True,
                ):
                    st.session_state.nba_partido_activo = {
                        "idx": global_idx,
                        "away_team": res["away_team"],
                        "home_team": res["home_team"],
                    }
                    st.rerun()


def format_edge_badge(delta_ppp: float) -> str:
    if delta_ppp >= 0.05:
        return f'<span class="edge-pill-pos">SHARP EDGE {delta_ppp:+.2f} PPP</span>'
    if delta_ppp <= -0.05:
        return f'<span class="edge-pill-neg">DEF WALL {delta_ppp:+.2f} PPP</span>'
    return f'<span class="edge-pill-neu">NEUTRAL {delta_ppp:+.2f} PPP</span>'


def render_detailed_matchup_dossier(res: Dict) -> None:
    """
    4. VISTA B: EXPEDIENTE CUANTITATIVO DETALLADO
    Despliega el Scoreboard TV Header con logos oficiales de 64px y las 4 filas
    del análisis cuantitativo de 5,000 simulaciones de Monte Carlo.
    """
    away_abbr = res["away_abbr"]
    home_abbr = res["home_abbr"]
    away_row = res["away_row"]
    home_row = res["home_row"]

    away_div = away_row.get("Division", away_row.get("Conference", "NBA"))
    home_div = home_row.get("Division", home_row.get("Conference", "NBA"))

    away_c1, away_c2 = TEAM_COLORS.get(away_abbr, ("#1E293B", "#38BDF8"))
    home_c1, home_c2 = TEAM_COLORS.get(home_abbr, ("#1E293B", "#00F5D4"))

    away_logo_64 = escudo_nba_html(away_abbr, size=64)
    home_logo_64 = escudo_nba_html(home_abbr, size=64)

    proj_spread_str = (
        f"{home_abbr} {res['proj_spread_home']:+.1f}"
        if res["proj_spread_home"] <= 0
        else f"{away_abbr} {-res['proj_spread_home']:+.1f}"
    )
    mkt_spread_str = f"{home_abbr} {res['spread_line_home']:+.1f}"

    # Scoreboard TV Header con Logos Oficiales ESPN en 64px
    st.markdown(
        f"""
        <div class="game-glass-wrapper">
            <div class="scoreboard-tv-header">
                <div class="sb-team-block">
                    <div class="team-logo-box-64" style="background: linear-gradient(135deg, {away_c1}55, {away_c2}33); border: 1px solid {away_c2};">
                        {away_logo_64}
                    </div>
                    <div>
                        <div class="sb-team-name">{res['away_team']} <span style="font-size:0.72rem; color:#94A3B8;">(AWAY &bull; {away_div.upper()})</span></div>
                        <div class="sb-team-metrics">
                            ORTG: <strong>{away_row['Off_Rtg']:.1f}</strong> | DRTG: <strong>{away_row['Def_Rtg']:.1f}</strong> | PACE: <strong>{away_row['Pace']:.1f}</strong> | 3PA: <strong>{away_row['3PA_Rate']*100:.1f}%</strong>
                        </div>
                        <div class="sb-team-metrics" style="color:#CBD5E1;">
                            Estrellas: <strong>{away_row['Star1_Name']} ({away_row['Star1_PPG']:.1f})</strong> &bull; <strong>{away_row['Star2_Name']} ({away_row['Star2_PPG']:.1f})</strong>
                        </div>
                    </div>
                </div>
                <div class="sb-center-console">
                    <div style="font-family:'Orbitron',sans-serif; font-size:0.68rem; color:#94A3B8; letter-spacing:0.10em;">
                        PROYECCIÓN MEDIA ({res['n_sims']:,} SIMS)
                    </div>
                    <div class="sb-proj-score">
                        {away_abbr} {res['exp_away_pts']:.1f} &nbsp;—&nbsp; {res['exp_home_pts']:.1f} {home_abbr}
                    </div>
                    <div class="sb-lines-row">
                        <span class="sb-chip">PACE ESP: {res['exp_possessions']:.1f} POS</span>
                        <span class="sb-chip">SPREAD PROY: {proj_spread_str}</span>
                        <span class="sb-chip">MKT LINE: {mkt_spread_str}</span>
                        <span class="sb-chip">TOTAL PROY: {res['exp_total_pts']:.1f} (MKT {res['total_line']:.1f})</span>
                    </div>
                </div>
                <div class="sb-team-block right">
                    <div>
                        <div class="sb-team-name"><span style="font-size:0.72rem; color:#00F5D4;">(HOME &bull; {home_div.upper()})</span> {res['home_team']}</div>
                        <div class="sb-team-metrics">
                            ORTG: <strong>{home_row['Off_Rtg']:.1f}</strong> | DRTG: <strong>{home_row['Def_Rtg']:.1f}</strong> | PACE: <strong>{home_row['Pace']:.1f}</strong> | 3PA: <strong>{home_row['3PA_Rate']*100:.1f}%</strong>
                        </div>
                        <div class="sb-team-metrics" style="color:#CBD5E1;">
                            Estrellas: <strong>{home_row['Star1_Name']} ({home_row['Star1_PPG']:.1f})</strong> &bull; <strong>{home_row['Star2_Name']} ({home_row['Star2_PPG']:.1f})</strong>
                        </div>
                    </div>
                    <div class="team-logo-box-64" style="background: linear-gradient(135deg, {home_c1}55, {home_c2}33); border: 1px solid {home_c2};">
                        {home_logo_64}
                    </div>
                </div>
            </div>
        """,
        unsafe_allow_html=True,
    )

    # ------------------------------------------------------------------
    # FILA 1: RESUMEN DE SIMULACIÓN (5,000 ITERACIONES)
    # ------------------------------------------------------------------
    st.markdown(
        f"""
        <div class="row-label-bar">
            <span class="row-label-title">📊 FILA 1 // RESUMEN DE SIMULACIÓN MONTE CARLO ({res['n_sims']:,} ITERACIONES)</span>
            <span class="row-label-sub">WIN % &bull; SPREAD COVER % &bull; TOTAL OVER/UNDER &bull; FAIR ODDS</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    f1_c1, f1_c2, f1_c3 = st.columns(3)

    with f1_c1:
        st.markdown(
            f"""
            <div class="quant-subcard">
                <div class="quant-subcard-header">
                    <span>🏆 MONEYLINE (PROB. VICTORIA)</span>
                    <span style="color:#00F5D4;">NO-VIG FAIR ODDS</span>
                </div>
                <div class="sim-stat-line">
                    <span class="sim-team-label">{escudo_nba_html(away_abbr, 20)}{away_abbr} (Visita)</span>
                    <span>
                        <span class="sim-prob-val">{res['away_win_prob']*100:.1f}%</span>
                        <span class="sim-odds-badge">{res['away_ml_dec']} / {res['away_ml_amer']}</span>
                    </span>
                </div>
                <div class="sim-stat-line">
                    <span class="sim-team-label">{escudo_nba_html(home_abbr, 20)}{home_abbr} (Local)</span>
                    <span>
                        <span class="sim-prob-val">{res['home_win_prob']*100:.1f}%</span>
                        <span class="sim-odds-badge">{res['home_ml_dec']} / {res['home_ml_amer']}</span>
                    </span>
                </div>
                <div class="quant-bar-track">
                    <div class="quant-bar-fill-left" style="width: {res['away_win_prob']*100:.1f}%;"></div>
                    <div class="quant-bar-fill-right" style="width: {res['home_win_prob']*100:.1f}%;"></div>
                </div>
                <div style="font-family:'JetBrains Mono',monospace; font-size:0.72rem; color:#94A3B8; margin-top:4px;">
                    Diferencial Esperado: <strong style="color:#F8FAFC;">{home_abbr} {-res['proj_spread_home']:+.1f} pts</strong>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with f1_c2:
        st.markdown(
            f"""
            <div class="quant-subcard">
                <div class="quant-subcard-header">
                    <span>⚡ SPREAD / HÁNDICAP DINÁMICO</span>
                    <span style="color:#38BDF8;">LÍNEA: {home_abbr} {res['spread_line_home']:+.1f}</span>
                </div>
                <div class="sim-stat-line">
                    <span class="sim-team-label">{escudo_nba_html(away_abbr, 20)}{away_abbr} ({res['spread_line_away']:+.1f})</span>
                    <span>
                        <span class="sim-prob-val" style="color:#38BDF8;">{res['away_cover_prob']*100:.1f}%</span>
                        <span class="sim-odds-badge">{res['away_sp_dec']} / {res['away_sp_amer']}</span>
                    </span>
                </div>
                <div class="sim-stat-line">
                    <span class="sim-team-label">{escudo_nba_html(home_abbr, 20)}{home_abbr} ({res['spread_line_home']:+.1f})</span>
                    <span>
                        <span class="sim-prob-val" style="color:#38BDF8;">{res['home_cover_prob']*100:.1f}%</span>
                        <span class="sim-odds-badge">{res['home_sp_dec']} / {res['home_sp_amer']}</span>
                    </span>
                </div>
                <div class="quant-bar-track">
                    <div class="quant-bar-fill-left" style="width: {res['away_cover_prob']*100:.1f}%;"></div>
                    <div class="quant-bar-fill-right" style="width: {res['home_cover_prob']*100:.1f}%;"></div>
                </div>
                <div style="font-family:'JetBrains Mono',monospace; font-size:0.72rem; color:#94A3B8; margin-top:4px;">
                    Edge vs Línea: <strong style="color:#00F5D4;">{abs(res['proj_spread_home'] - res['spread_line_home']):.1f} pts de valor</strong>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with f1_c3:
        st.markdown(
            f"""
            <div class="quant-subcard">
                <div class="quant-subcard-header">
                    <span>🎯 PUNTOS TOTALES (O/U)</span>
                    <span style="color:#F59E0B;">LÍNEA: {res['total_line']:.1f} PTS</span>
                </div>
                <div class="sim-stat-line">
                    <span class="sim-team-label">OVER {res['total_line']:.1f}</span>
                    <span>
                        <span class="sim-prob-val" style="color:#F59E0B;">{res['over_prob']*100:.1f}%</span>
                        <span class="sim-odds-badge">{res['over_dec']} / {res['over_amer']}</span>
                    </span>
                </div>
                <div class="sim-stat-line">
                    <span class="sim-team-label">UNDER {res['total_line']:.1f}</span>
                    <span>
                        <span class="sim-prob-val" style="color:#F59E0B;">{res['under_prob']*100:.1f}%</span>
                        <span class="sim-odds-badge">{res['under_dec']} / {res['under_amer']}</span>
                    </span>
                </div>
                <div class="quant-bar-track">
                    <div class="quant-bar-fill-left" style="width: {res['over_prob']*100:.1f}%;"></div>
                    <div class="quant-bar-fill-right" style="width: {res['under_prob']*100:.1f}%;"></div>
                </div>
                <div style="font-family:'JetBrains Mono',monospace; font-size:0.72rem; color:#94A3B8; margin-top:4px;">
                    Banda Sim (P10 / P50 / P90): <strong style="color:#F8FAFC;">{res['total_p10']:.0f} / {res['total_p50']:.0f} / {res['total_p90']:.0f} pts</strong>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ------------------------------------------------------------------
    # FILA 2: "CÓMO GANA EL FAVORITO" (CONDICIONES DE VICTORIA)
    # ------------------------------------------------------------------
    delta_3pm = (res["win_given_3pm"] - res["fav_base_win"]) * 100
    delta_tov = (res["win_given_tov"] - res["fav_base_win"]) * 100
    delta_ortg = (res["win_given_ortg"] - res["fav_base_win"]) * 100

    st.markdown(
        f"""
        <div class="row-label-bar" style="border-left-color: #10B981;">
            <span class="row-label-title">🔑 FILA 2 // "CÓMO GANA EL FAVORITO" ({res['fav_name'].upper()} - WIN BASE {res['fav_base_win']*100:.1f}%)</span>
            <span class="row-label-sub">GATILLOS DE PROBABILIDAD CONDICIONAL EN LAS {res['n_sims']:,} SIMULACIONES</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    f2_c1, f2_c2, f2_c3 = st.columns(3)
    with f2_c1:
        st.markdown(
            f"""
            <div class="win-cond-card">
                <div class="win-cond-title">🎯 GATILLO DE VOLUMEN PERIMETRAL (3PM)</div>
                <div class="win-cond-statement">
                    {res['fav_abbr']} gana el <span style="color:#00F5D4;">{res['win_given_3pm']*100:.1f}%</span> si anota &gt;{res['threepm_threshold']} triples
                </div>
                <div class="win-cond-meta">
                    Impulso Condicional: <strong>{delta_3pm:+.1f}% vs Win % Base</strong> | 3PA Rate: {float((home_row if res['fav_abbr']==home_abbr else away_row)['3PA_Rate'])*100:.1f}%
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with f2_c2:
        st.markdown(
            f"""
            <div class="win-cond-card">
                <div class="win-cond-title">🛡️ GATILLO DE PROTECCIÓN DE BALÓN (TOV)</div>
                <div class="win-cond-statement">
                    {res['fav_abbr']} gana el <span style="color:#00F5D4;">{res['win_given_tov']*100:.1f}%</span> si comete &lt;{res['tov_threshold']} pérdidas
                </div>
                <div class="win-cond-meta">
                    Impulso Condicional: <strong>{delta_tov:+.1f}% vs Win % Base</strong> | TOV% Base: {float((home_row if res['fav_abbr']==home_abbr else away_row)['TOV_Pct']):.1f}%
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with f2_c3:
        st.markdown(
            f"""
            <div class="win-cond-card">
                <div class="win-cond-title">⚡ GATILLO DE EFICIENCIA POR 100 POS (ORTG)</div>
                <div class="win-cond-statement">
                    {res['fav_abbr']} gana el <span style="color:#00F5D4;">{res['win_given_ortg']*100:.1f}%</span> si supera {res['ortg_threshold']:.1f} OffRtg
                </div>
                <div class="win-cond-meta">
                    Impulso Condicional: <strong>{delta_ortg:+.1f}% vs Win % Base</strong> | Pace Proy: {res['exp_possessions']:.1f} pos
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ------------------------------------------------------------------
    # FILA 3: MATCHUP TÁCTICO SYNERGY (ISO PPP & PNR PPP VS DEFENSA RIVAL)
    # ------------------------------------------------------------------
    st.markdown(
        """
        <div class="row-label-bar" style="border-left-color: #38BDF8;">
            <span class="row-label-title">♟️ FILA 3 // ANÁLISIS TÁCTICO SYNERGY (ISO PPP &amp; PNR PPP VS DEFENSAS RIVALES)</span>
            <span class="row-label-sub">PUNTOS POR POSESIÓN (SYNERGY PLAYTYPE MATRIX)</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    f3_c1, f3_c2 = st.columns(2)
    with f3_c1:
        st.markdown(
            f"""
            <div class="tactical-ppp-box">
                <div class="quant-subcard-header">
                    <span>⚔️ ATAQUE {away_abbr} vs DEFENSA {home_abbr}</span>
                    <span>IMPACTO POR ESTILO</span>
                </div>
                <div class="sim-stat-line">
                    <span class="sim-team-label" style="font-size:0.80rem;">
                        ISOLATION: {away_abbr} Off ({away_row['Iso_PPP_Off']:.2f}) vs {home_abbr} Def ({home_row['Iso_PPP_Def']:.2f})
                    </span>
                    {format_edge_badge(res['away_iso_delta'])}
                </div>
                <div class="sim-stat-line" style="margin-top:8px;">
                    <span class="sim-team-label" style="font-size:0.80rem;">
                        PICK &amp; ROLL: {away_abbr} Off ({away_row['PnR_PPP_Off']:.2f}) vs {home_abbr} Def ({home_row['PnR_PPP_Def']:.2f})
                    </span>
                    {format_edge_badge(res['away_pnr_delta'])}
                </div>
                <div style="font-family:'JetBrains Mono',monospace; font-size:0.72rem; color:#94A3B8; margin-top:8px;">
                    Ajuste Neto Táctico {away_abbr}: <strong style="color:#F8FAFC;">{res['away_tactical_ortg_adj']:+.2f} pts / 100 pos</strong>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with f3_c2:
        st.markdown(
            f"""
            <div class="tactical-ppp-box">
                <div class="quant-subcard-header">
                    <span>⚔️ ATAQUE {home_abbr} vs DEFENSA {away_abbr}</span>
                    <span>IMPACTO POR ESTILO</span>
                </div>
                <div class="sim-stat-line">
                    <span class="sim-team-label" style="font-size:0.80rem;">
                        ISOLATION: {home_abbr} Off ({home_row['Iso_PPP_Off']:.2f}) vs {away_abbr} Def ({away_row['Iso_PPP_Def']:.2f})
                    </span>
                    {format_edge_badge(res['home_iso_delta'])}
                </div>
                <div class="sim-stat-line" style="margin-top:8px;">
                    <span class="sim-team-label" style="font-size:0.80rem;">
                        PICK &amp; ROLL: {home_abbr} Off ({home_row['PnR_PPP_Off']:.2f}) vs {away_abbr} Def ({away_row['PnR_PPP_Def']:.2f})
                    </span>
                    {format_edge_badge(res['home_pnr_delta'])}
                </div>
                <div style="font-family:'JetBrains Mono',monospace; font-size:0.72rem; color:#94A3B8; margin-top:8px;">
                    Ajuste Neto Táctico {home_abbr}: <strong style="color:#F8FAFC;">{res['home_tactical_ortg_adj']:+.2f} pts / 100 pos</strong>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ------------------------------------------------------------------
    # FILA 4: PLAYER PROPS LEANS (ESTRELLAS VIGENTES DE st.session_state.df_nba)
    # ------------------------------------------------------------------
    st.markdown(
        """
        <div class="row-label-bar" style="border-left-color: #8B5CF6;">
            <span class="row-label-title">🏀 FILA 4 // PLAYER PROPS LEANS (SINCRONIZADO EN VIVO CON ROSTER EDITOR)</span>
            <span class="row-label-sub">SIMULACIÓN INDIVIDUAL AJUSTADA POR ESTILO DE DEFENSA RIVAL (ISO / PNR)</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    prop_cols = st.columns(4)
    for idx, prop in enumerate(res["props"]):
        lean_cls = "prop-lean-over" if prop["lean_side"] == "OVER" else "prop-lean-under"
        with prop_cols[idx]:
            st.markdown(
                f"""
                <div class="prop-player-card">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                        <span class="prop-player-name">{escudo_nba_html(prop['team_abbr'], 22)}{prop['player_name']}</span>
                        <span class="sb-chip" style="font-size:0.66rem;">{prop['team_abbr']} &bull; {prop['style']}</span>
                    </div>
                    <div style="font-family:'JetBrains Mono',monospace; font-size:0.73rem; color:#94A3B8; margin-bottom:6px;">
                        PPG Vigente: <strong>{prop['base_ppg']:.1f}</strong> &rarr; Proy: <strong style="color:#F8FAFC;">{prop['proj_ppg']:.1f} Pts</strong>
                    </div>
                    <div style="background:rgba(5,8,17,0.72); border:1px solid rgba(148,163,184,0.16); border-radius:8px; padding:7px 10px; margin-bottom:6px;">
                        <div class="{lean_cls}">
                            {prop['lean_side']} {prop['prop_line']:.1f} PTS ({prop['lean_prob']*100:.1f}%)
                        </div>
                        <div style="font-family:'JetBrains Mono',monospace; font-size:0.70rem; color:#CBD5E1; margin-top:2px;">
                            Fair Odds: <strong>{prop['fair_dec']} ({prop['fair_amer']})</strong> | IQR: {prop['p25']:.0f}-{prop['p75']:.0f}
                        </div>
                    </div>
                    <div style="font-family:'JetBrains Mono',monospace; font-size:0.68rem; color:#94A3B8;">
                        {prop['matchup_note']}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("</div>", unsafe_allow_html=True)


# ==============================================================================
# 2. GESTIÓN DE ROSTER Y PERSISTENCIA EN SESIÓN (st.session_state + st.data_editor)
# ==============================================================================
def init_session_state() -> None:
    if "df_nba" not in st.session_state:
        clean_df, source_label = load_clean_nba_dataframe()
        st.session_state.df_nba = clean_df
        st.session_state.data_source_label = source_label
    if "roster_editor_version" not in st.session_state:
        st.session_state.roster_editor_version = 0
    if "nba_partido_activo" not in st.session_state:
        st.session_state.nba_partido_activo = None
    if "config_expanded" not in st.session_state:
        st.session_state.config_expanded = False
    if "num_games" not in st.session_state:
        st.session_state.num_games = 6
    if "active_matchups" not in st.session_state:
        st.session_state.active_matchups = list(FULL_30_TEAM_SLATE[:6])
    if "active_custom_lines" not in st.session_state:
        st.session_state.active_custom_lines = {}


def keep_config_open() -> None:
    """Abre el configurador de cruces y vuelve a la Cartelera cuando cambia el número de juegos."""
    st.session_state.config_expanded = True
    st.session_state.nba_partido_activo = None


def reopen_config_panel() -> None:
    """Permite abrir el configurador de cruces con un clic."""
    st.session_state.config_expanded = True
    st.session_state.nba_partido_activo = None


def sync_edited_roster_to_session(edited_subset: pd.DataFrame) -> None:
    """
    Sincroniza cualquier edición de nombres, PPG, Pace, Off_Rtg o Def_Rtg realizada en
    st.data_editor directamente sobre st.session_state.df_nba y ajusta las líneas
    de Player Props cuando el usuario cambia un jugador o su PPG base.
    """
    master_df = st.session_state.df_nba.copy()

    for idx in edited_subset.index:
        if idx not in master_df.index:
            continue

        old_s1_name = str(master_df.loc[idx, "Star1_Name"])
        old_s1_ppg = float(master_df.loc[idx, "Star1_PPG"])
        old_s2_name = str(master_df.loc[idx, "Star2_Name"])
        old_s2_ppg = float(master_df.loc[idx, "Star2_PPG"])

        new_s1_name = str(edited_subset.loc[idx, "Star1_Name"])
        new_s1_ppg = float(edited_subset.loc[idx, "Star1_PPG"])
        new_s2_name = str(edited_subset.loc[idx, "Star2_Name"])
        new_s2_ppg = float(edited_subset.loc[idx, "Star2_PPG"])

        for col in ROSTER_EDITOR_COLS:
            master_df.loc[idx, col] = edited_subset.loc[idx, col]

        # Si el usuario editó la estrella o su PPG por traspaso/lesión, actualizamos su línea vigente
        if new_s1_name != old_s1_name or abs(new_s1_ppg - old_s1_ppg) > 1e-4:
            master_df.loc[idx, "Star1_Line"] = round_to_half_point(max(0.5, new_s1_ppg - 0.5))
        if new_s2_name != old_s2_name or abs(new_s2_ppg - old_s2_ppg) > 1e-4:
            master_df.loc[idx, "Star2_Line"] = round_to_half_point(max(0.5, new_s2_ppg - 0.5))

    st.session_state.df_nba = master_df


def render_live_roster_manager() -> None:
    """
    Renderiza el st.expander('⚙️ Gestor de Roster & Traspasos (Live Trades / Injuries)', expanded=False)
    con st.data_editor sincronizado en tiempo real con st.session_state.df_nba y botón de restablecimiento.
    """
    with st.expander("⚙️ Gestor de Roster & Traspasos (Live Trades / Injuries)", expanded=False):
        top_c1, top_c2 = st.columns([3.4, 1.2])
        with top_c1:
            st.markdown(
                """
                <div style="font-family:'JetBrains Mono',monospace; font-size:0.77rem; color:#CBD5E1; margin-bottom:6px;">
                    Edita en vivo bajas por lesión, traspasos de último minuto, minutos/PPG proyectados (`Star1_PPG`, `Star2_PPG`) o ajustes de ritmo y eficiencia (`Pace`, `Off_Rtg`, `Def_Rtg`). Tanto el motor Monte Carlo de 5,000 posesiones como los Player Props se recalculan instantáneamente con estos valores.
                </div>
                """,
                unsafe_allow_html=True,
            )
        with top_c2:
            if st.button("🔄 Restablecer Roster Oficial", use_container_width=True):
                clean_df, src_label = load_clean_nba_dataframe()
                st.session_state.df_nba = clean_df
                st.session_state.data_source_label = src_label
                st.session_state.roster_editor_version += 1
                st.rerun()

        current_subset = st.session_state.df_nba[ROSTER_EDITOR_COLS].copy()
        edited_df = st.data_editor(
            current_subset,
            key=f"nba_roster_data_editor_{st.session_state.roster_editor_version}",
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            disabled=["Team_Abbr"],
            column_config={
                "Team_Abbr": st.column_config.TextColumn("Franquicia", width="small"),
                "Star1_Name": st.column_config.TextColumn("Estrella 1 (Líder)", width="medium"),
                "Star1_PPG": st.column_config.NumberColumn(
                    "Star1 PPG", min_value=0.0, max_value=60.0, step=0.5, format="%.1f"
                ),
                "Star2_Name": st.column_config.TextColumn("Estrella 2 (Co-Líder)", width="medium"),
                "Star2_PPG": st.column_config.NumberColumn(
                    "Star2 PPG", min_value=0.0, max_value=60.0, step=0.5, format="%.1f"
                ),
                "Pace": st.column_config.NumberColumn(
                    "Pace (48m)", min_value=85.0, max_value=115.0, step=0.2, format="%.1f"
                ),
                "Off_Rtg": st.column_config.NumberColumn(
                    "Off_Rtg", min_value=95.0, max_value=135.0, step=0.2, format="%.1f"
                ),
                "Def_Rtg": st.column_config.NumberColumn(
                    "Def_Rtg", min_value=95.0, max_value=135.0, step=0.2, format="%.1f"
                ),
            },
        )

        if not edited_df.equals(current_subset):
            sync_edited_roster_to_session(edited_df)
            st.rerun()


# ==============================================================================
# APLICACIÓN PRINCIPAL STREAMLIT
# ==============================================================================
def main() -> None:
    inject_cyber_quant_css()
    init_session_state()

    # Sidebar: Parámetros Globales del Motor y Control Dinámico de Cantidad de Juegos
    with st.sidebar:
        st.markdown(
            """
            <div style="font-family:'Orbitron',sans-serif; font-size:1.05rem; font-weight:900; color:#00F5D4; letter-spacing:0.08em; margin-bottom:4px;">
                ⚡ SHARP SYNDICATE
            </div>
            <div style="font-family:'JetBrains Mono',monospace; font-size:0.72rem; color:#94A3B8; margin-bottom:14px;">
                NBA 30-TEAM MONTE CARLO ENGINE v6.0
            </div>
            """,
            unsafe_allow_html=True,
        )

        uploaded_csv = st.file_uploader(
            "Cargar nba_stats_completo.csv (Opcional)",
            type=["csv"],
            help="Si subes un archivo CSV propio, se actualizará st.session_state.df_nba.",
        )
        if uploaded_csv is not None:
            custom_df, custom_label = load_clean_nba_dataframe(uploaded_csv)
            st.session_state.df_nba = custom_df
            st.session_state.data_source_label = custom_label

        # Consumir estrictamente st.session_state.df_nba
        df_teams = st.session_state.df_nba
        team_list = df_teams["Team"].tolist()

        st.markdown("---")
        st.markdown("### 🏀 VOLUMEN DE LA CARTELERA")
        num_games = st.slider(
            "¿Cuántos juegos hay en la cartelera de hoy?",
            min_value=1,
            max_value=15,
            key="num_games",
            on_change=keep_config_open,
            help="Elige de 1 a 15 partidos. La Cartelera en Cuadrícula (Grid 3x3) se adaptará automáticamente.",
        )

        st.button(
            "🎛️ Configurar Cruces de Hoy",
            on_click=reopen_config_panel,
            use_container_width=True,
        )

        if st.session_state.nba_partido_activo is not None:
            if st.button("← Volver a la Cartelera NBA", key="sidebar_back_btn", use_container_width=True):
                st.session_state.nba_partido_activo = None
                st.rerun()

        st.markdown("---")
        st.markdown("### ⚙️ PARÁMETROS DEL MOTOR")
        n_sims = st.select_slider(
            "Iteraciones Monte Carlo / Partido",
            options=[1000, 2500, 5000, 10000, 20000],
            value=5000,
        )
        hfa_pts = st.slider(
            "Factor de Localía (HFA Puntos)",
            min_value=0.0,
            max_value=5.0,
            value=2.5,
            step=0.1,
        )
        base_seed = st.number_input(
            "Semilla Cuantitativa (RNG Seed)",
            min_value=1,
            max_value=999999,
            value=2026,
            step=1,
        )

        st.markdown("---")
        st.caption(f"📂 Fuente activa: {st.session_state.data_source_label}")

    # Scoreboard TV Header Principal
    st.markdown(
        f"""
        <div class="tv-master-header">
            <div class="tv-top-bar">
                <div class="syndicate-badge">
                    <span class="pulse-dot"></span> SHARP SYNDICATE // LIVE ROSTER &amp; 3x3 GRID SCANNER
                </div>
                <div class="font-mono" style="font-size:0.76rem; color:#94A3B8;">
                    ENGINE STATUS: <strong style="color:#00F5D4;">ONLINE</strong> &nbsp;|&nbsp;
                    SIMULATIONS: <strong style="color:#F8FAFC;">{n_sims:,} / GAME</strong> &nbsp;|&nbsp;
                    HFA: <strong style="color:#38BDF8;">+{hfa_pts:.1f} PTS</strong>
                </div>
            </div>
            <div class="tv-title">TERMINAL SHARP: NBA QUANT SCANNER</div>
            <div class="tv-subtitle">
                Cartelera interactiva 3x3 con escudos oficiales ESPN HD, Gestor de Rosters y Traspasos en Vivo (<code>st.data_editor</code>) y motor Monte Carlo de 5,000 posesiones.
            </div>
            <div class="tv-telemetry-strip">
                <div class="telemetry-pill">FRANQUICIAS EN SESIÓN: <strong>{len(df_teams)} / 30</strong></div>
                <div class="telemetry-pill">CARTELERA ACTIVA: <strong>{num_games} PARTIDO(S)</strong></div>
                <div class="telemetry-pill">ITERACIONES TOTALES: <strong>{num_games * n_sims:,}</strong></div>
                <div class="telemetry-pill">VISTA ACTUAL: <strong>{"EXPEDIENTE DETALLADO" if st.session_state.nba_partido_activo else "CARTELERA GRID 3x3"}</strong></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Panel de Edición en Vivo de Rosters, Traspasos y Bajas (disponible en ambas vistas)
    render_live_roster_manager()

    # Sincronizar lista activa de partidos con num_games
    df_teams = st.session_state.df_nba
    team_list = df_teams["Team"].tolist()

    selected_matchups: List[Tuple[str, str]] = list(st.session_state.active_matchups[:num_games])
    if len(selected_matchups) < num_games:
        for extra_idx in range(len(selected_matchups), num_games):
            fallback_pair = FULL_30_TEAM_SLATE[extra_idx % len(FULL_30_TEAM_SLATE)]
            if fallback_pair[0] in team_list and fallback_pair[1] in team_list:
                selected_matchups.append(fallback_pair)

    # ==========================================================================
    # NAVEGACIÓN PRINCIPAL: VISTA A (GRID 3x3) vs VISTA B (EXPEDIENTE DETALLADO)
    # ==========================================================================
    if st.session_state.nba_partido_activo is None:
        # ----------------------------------------------------------------------
        # VISTA A: SELECTOR DE CRUCES + RADAR EJECUTIVO + CARTELERA EN CUADRÍCULA 3x3
        # ----------------------------------------------------------------------
        with st.expander(
            f"🎛️ CONFIGURADOR DINÁMICO DE CRUCES ({num_games} JUEGO{'S' if num_games > 1 else ''} EN LA CARTELERA DE HOY)",
            expanded=st.session_state.config_expanded,
        ):
            st.markdown(
                f"""
                <div style="font-family:'JetBrains Mono',monospace; font-size:0.78rem; color:#CBD5E1; margin-bottom:10px;">
                    Elige el equipo <strong>Visitante (Away)</strong> y <strong>Local (Home)</strong> de entre las <strong>30 franquicias NBA</strong> para cada uno de los <strong>{num_games}</strong> juegos. Al pulsar el botón de escanear, este panel se colapsará automáticamente y actualizará la cuadrícula 3x3.
                </div>
                """,
                unsafe_allow_html=True,
            )

            with st.form("dynamic_slate_form", clear_on_submit=False):
                form_selections: List[Tuple[str, str]] = []
                form_custom_lines: Dict[int, Tuple[ Optional[float], Optional[float] ]] = {}

                for i in range(num_games):
                    default_away, default_home = FULL_30_TEAM_SLATE[i % len(FULL_30_TEAM_SLATE)]
                    if i < len(selected_matchups):
                        prev_away, prev_home = selected_matchups[i]
                        if prev_away in team_list and prev_home in team_list:
                            default_away, default_home = prev_away, prev_home

                    away_idx = team_list.index(default_away) if default_away in team_list else (i * 2) % len(team_list)
                    home_idx = team_list.index(default_home) if default_home in team_list else (i * 2 + 1) % len(team_list)

                    st.markdown(
                        f'<div class="slate-slot-badge">🏀 JUEGO #{i + 1} DE {num_games}</div>',
                        unsafe_allow_html=True,
                    )
                    col_a, col_h, col_sp, col_tot = st.columns([2.2, 2.2, 1.1, 1.1])

                    with col_a:
                        sel_away = st.selectbox(
                            f"Visitante (Juego #{i + 1})",
                            options=team_list,
                            index=away_idx,
                            key=f"form_away_{i}",
                        )
                    with col_h:
                        sel_home = st.selectbox(
                            f"Local (Juego #{i + 1})",
                            options=team_list,
                            index=home_idx,
                            key=f"form_home_{i}",
                        )
                    with col_sp:
                        sel_sp = st.number_input(
                            f"Spread Local #{i + 1} (0=Auto)",
                            value=0.0,
                            step=0.5,
                            key=f"form_sp_{i}",
                        )
                    with col_tot:
                        sel_tot = st.number_input(
                            f"Total O/U #{i + 1} (0=Auto)",
                            value=0.0,
                            step=0.5,
                            key=f"form_tot_{i}",
                        )

                    form_selections.append((sel_away, sel_home))
                    form_custom_lines[i] = (
                        sel_sp if sel_sp != 0.0 else None,
                        sel_tot if sel_tot != 0.0 else None,
                    )

                submitted = st.form_submit_button(
                    f"⚡ ESCANEAR {num_games} PARTIDO(S) DE HOY ({num_games * n_sims:,} SIMULACIONES MONTE CARLO)",
                    use_container_width=True,
                )

                if submitted:
                    valid_matchups: List[Tuple[str, str]] = []
                    valid_lines: Dict[int, Tuple[Optional[float], Optional[float]]] = {}
                    duplicate_team_games: List[int] = []

                    for idx, (away_t, home_t) in enumerate(form_selections):
                        if away_t == home_t:
                            duplicate_team_games.append(idx + 1)
                        else:
                            valid_idx = len(valid_matchups)
                            valid_matchups.append((away_t, home_t))
                            valid_lines[valid_idx] = form_custom_lines[idx]

                    if duplicate_team_games:
                        st.warning(
                            f"Atención: El Juego #{', #'.join(map(str, duplicate_team_games))} tenía el mismo equipo como Visitante y Local y fue omitido."
                        )

                    if valid_matchups:
                        st.session_state.active_matchups = valid_matchups
                        st.session_state.active_custom_lines = valid_lines
                        st.session_state.config_expanded = False
                        st.rerun()

        if not selected_matchups:
            st.info("Configura al menos un partido válido para visualizar la Cartelera NBA.")
            return

        # Ejecutar las 5,000 simulaciones consumiendo estrictamente st.session_state.df_nba
        sim_results: List[Dict] = []
        for idx, (away_name, home_name) in enumerate(selected_matchups):
            away_row = df_teams[df_teams["Team"] == away_name].iloc[0]
            home_row = df_teams[df_teams["Team"] == home_name].iloc[0]
            c_sp, c_tot = st.session_state.active_custom_lines.get(idx, (None, None))

            res = run_monte_carlo_matchup(
                away_row=away_row,
                home_row=home_row,
                n_sims=n_sims,
                hfa_pts=hfa_pts,
                custom_spread_home=c_sp,
                custom_total_line=c_tot,
                seed=int(base_seed) + idx * 101,
            )
            sim_results.append(res)

        # Renderizar Radar Ejecutivo de la Jornada
        radar_picks = extract_executive_radar(sim_results)
        render_executive_radar(radar_picks, games_count=len(sim_results), n_sims=n_sims)

        # Renderizar Cartelera en Cuadrícula (Grid de 3 Columnas)
        render_slate_grid_3x3(sim_results)

    else:
        # ----------------------------------------------------------------------
        # VISTA B: EXPEDIENTE CUANTITATIVO DETALLADO DEL PARTIDO SELECCIONADO
        # ----------------------------------------------------------------------
        active_info = st.session_state.nba_partido_activo
        game_idx = int(active_info.get("idx", 0))
        away_name = str(active_info["away_team"])
        home_name = str(active_info["home_team"])

        nav_c1, nav_c2 = st.columns([1.4, 3.6])
        with nav_c1:
            if st.button("← Volver a la Cartelera NBA", key="top_back_to_grid_btn", use_container_width=True):
                st.session_state.nba_partido_activo = None
                st.rerun()
        with nav_c2:
            st.markdown(
                f"""
                <div style="display:flex; align-items:center; height:38px; font-family:'JetBrains Mono',monospace; font-size:0.80rem; color:#00F5D4;">
                    📂 EXPEDIENTE ACTIVO: <strong style="color:#F8FAFC; margin-left:8px;">{away_name.upper()} @ {home_name.upper()}</strong> &nbsp;|&nbsp; Datos sincronizados en vivo con <code>st.session_state.df_nba</code>
                </div>
                """,
                unsafe_allow_html=True,
            )

        # Consumir estrictamente st.session_state.df_nba para recalcular con cualquier cambio en vivo
        away_row = df_teams[df_teams["Team"] == away_name].iloc[0]
        home_row = df_teams[df_teams["Team"] == home_name].iloc[0]
        c_sp, c_tot = st.session_state.active_custom_lines.get(game_idx, (None, None))

        detailed_res = run_monte_carlo_matchup(
            away_row=away_row,
            home_row=home_row,
            n_sims=n_sims,
            hfa_pts=hfa_pts,
            custom_spread_home=c_sp,
            custom_total_line=c_tot,
            seed=int(base_seed) + game_idx * 101,
        )

        render_detailed_matchup_dossier(detailed_res)


if __name__ == "__main__":
    main()