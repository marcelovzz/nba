from typing import Dict, List, Tuple
import streamlit as st

# Paleta oficial de colores neón/institucional para las 30 franquicias NBA
TEAM_COLORS: Dict[str, Tuple[str, str]] = {
    "BOS": ("#007A33", "#00F5D4"), "BKN": ("#1E293B", "#94A3B8"), "NYK": ("#F58426", "#006BB6"),
    "PHI": ("#006BB6", "#ED174C"), "TOR": ("#CE1141", "#A1A1AA"), "CHI": ("#CE1141", "#F43F5E"),
    "CLE": ("#860038", "#FDBB30"), "DET": ("#C8102E", "#1D42BA"), "IND": ("#002D62", "#FDBB30"),
    "MIL": ("#00471B", "#10B981"), "DEN": ("#0E2240", "#FEC524"), "MIN": ("#0C2340", "#78BE20"),
    "OKC": ("#007AC1", "#EF3B24"), "POR": ("#E03A3E", "#94A3B8"), "UTA": ("#002B5C", "#F9A01B"),
    "GSW": ("#1D428A", "#FFC72C"), "LAC": ("#C8102E", "#1D428A"), "LAL": ("#552583", "#FDB927"),
    "PHX": ("#1D1160", "#E56020"), "SAC": ("#5A2D81", "#A78BFA"), "ATL": ("#E03A3E", "#C1D32F"),
    "CHA": ("#1D1160", "#00788C"), "MIA": ("#98002E", "#F9A01B"), "ORL": ("#0077C0", "#38BDF8"),
    "WAS": ("#002B5C", "#E31837"), "DAL": ("#00538C", "#00B4D8"), "HOU": ("#CE1141", "#F43F5E"),
    "MEM": ("#5D76A9", "#12173F"), "NOP": ("#0C2340", "#C8102E"), "SAS": ("#000000", "#C4CED4"),
}

TEAM_RECENT_FORM: Dict[str, List[str]] = {
    "BOS": ["W", "W", "W", "L", "W"], "BKN": ["L", "W", "L", "L", "W"], "NYK": ["W", "W", "L", "W", "W"],
    "PHI": ["W", "L", "W", "W", "L"], "TOR": ["L", "L", "W", "L", "L"], "CHI": ["W", "L", "L", "W", "L"],
    "CLE": ["W", "W", "W", "W", "L"], "DET": ["L", "L", "L", "W", "L"], "IND": ["W", "W", "L", "W", "L"],
    "MIL": ["W", "L", "W", "W", "W"], "DEN": ["W", "W", "W", "L", "W"], "MIN": ["W", "L", "W", "W", "W"],
    "OKC": ["W", "W", "W", "W", "W"], "POR": ["L", "L", "W", "L", "L"], "UTA": ["L", "W", "L", "L", "L"],
    "GSW": ["W", "W", "L", "W", "L"], "LAC": ["W", "L", "W", "L", "W"], "LAL": ["W", "W", "L", "L", "W"],
    "PHX": ["W", "L", "W", "W", "W"], "SAC": ["L", "W", "W", "L", "W"], "ATL": ["W", "L", "L", "W", "W"],
    "CHA": ["L", "L", "W", "L", "L"], "MIA": ["W", "L", "W", "W", "L"], "ORL": ["W", "W", "W", "L", "L"],
    "WAS": ["L", "L", "L", "L", "W"], "DAL": ["W", "W", "L", "W", "W"], "HOU": ["W", "W", "L", "W", "L"],
    "MEM": ["W", "L", "W", "W", "L"], "NOP": ["L", "W", "W", "L", "W"], "SAS": ["L", "W", "L", "W", "L"],
}


def inject_cyber_quant_css() -> None:
    """Inyecta la hoja de estilos Cyber-Quant UI (Glassmorphism, Orbitron, JetBrains Mono, Scoreboard TV)."""
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

        section[data-testid="stSidebar"] {
            background: rgba(8, 13, 26, 0.92) !important;
            border-right: 1px solid rgba(0, 245, 212, 0.18);
            backdrop-filter: blur(20px);
        }
        section[data-testid="stSidebar"] * { font-family: 'Inter', sans-serif; }
        h1, h2, h3, .font-orbitron { font-family: 'Orbitron', sans-serif !important; letter-spacing: 0.06em; }
        .font-mono { font-family: 'JetBrains Mono', monospace !important; }

        .tv-master-header {
            background: linear-gradient(135deg, rgba(11, 18, 35, 0.92) 0%, rgba(18, 28, 52, 0.85) 100%);
            border: 1px solid rgba(0, 245, 212, 0.30);
            border-radius: 16px;
            padding: 20px 26px;
            margin-bottom: 18px;
            box-shadow: 0 12px 36px rgba(0, 0, 0, 0.55), 0 0 24px rgba(0, 245, 212, 0.08);
            backdrop-filter: blur(18px);
            position: relative;
            overflow: hidden;
        }
        .tv-master-header::before {
            content: ""; position: absolute; top: 0; left: 0; right: 0; height: 3px;
            background: linear-gradient(90deg, #00F5D4, #38BDF8, #8B5CF6, #00F5D4);
        }
        .tv-top-bar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
        .syndicate-badge {
            display: inline-flex; align-items: center; gap: 8px;
            background: rgba(0, 245, 212, 0.10); border: 1px solid rgba(0, 245, 212, 0.35);
            color: #00F5D4; font-family: 'JetBrains Mono', monospace; font-size: 0.75rem;
            font-weight: 700; padding: 4px 12px; border-radius: 999px;
            text-transform: uppercase; letter-spacing: 0.08em;
        }
        .pulse-dot { width: 8px; height: 8px; background-color: #00F5D4; border-radius: 50%; box-shadow: 0 0 10px #00F5D4; display: inline-block; }
        .tv-title {
            font-family: 'Orbitron', sans-serif; font-size: 1.85rem; font-weight: 900; color: #F8FAFC;
            margin: 6px 0 4px 0; text-shadow: 0 0 18px rgba(0, 245, 212, 0.25); letter-spacing: 0.07em;
        }
        .tv-subtitle { color: #94A3B8; font-size: 0.90rem; margin: 0; }
        .tv-telemetry-strip {
            display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; padding-top: 12px;
            border-top: 1px solid rgba(148, 163, 184, 0.14);
        }
        .telemetry-pill {
            background: rgba(5, 8, 17, 0.72); border: 1px solid rgba(148, 163, 184, 0.22);
            border-radius: 8px; padding: 5px 11px; font-family: 'JetBrains Mono', monospace;
            font-size: 0.74rem; color: #CBD5E1;
        }
        .telemetry-pill strong { color: #00F5D4; }

        .section-banner {
            display: flex; align-items: center; justify-content: space-between;
            margin: 22px 0 14px 0; padding-bottom: 8px; border-bottom: 1px solid rgba(0, 245, 212, 0.22);
        }
        .section-banner-title {
            font-family: 'Orbitron', sans-serif; font-size: 1.12rem; font-weight: 800; color: #F8FAFC;
            letter-spacing: 0.08em; text-transform: uppercase; display: flex; align-items: center; gap: 10px;
        }
        .section-banner-tag {
            font-family: 'JetBrains Mono', monospace; font-size: 0.73rem; color: #00F5D4;
            background: rgba(0, 245, 212, 0.08); border: 1px solid rgba(0, 245, 212, 0.25);
            padding: 3px 10px; border-radius: 6px;
        }

        .radar-card {
            background: linear-gradient(155deg, rgba(16, 25, 48, 0.85) 0%, rgba(9, 14, 28, 0.92) 100%);
            border: 1px solid rgba(0, 245, 212, 0.25); border-radius: 14px; padding: 18px 18px 16px 18px;
            backdrop-filter: blur(16px); box-shadow: 0 8px 28px rgba(0, 0, 0, 0.45);
            position: relative; overflow: hidden; height: 100%; min-height: 198px;
            display: flex; flex-direction: column; justify-content: space-between;
        }
        .radar-card.lock-card { border-top: 3px solid #00F5D4; }
        .radar-card.spread-card { border-top: 3px solid #38BDF8; }
        .radar-card.total-card { border-top: 3px solid #F59E0B; }
        .radar-card.prop-card { border-top: 3px solid #8B5CF6; }
        .radar-tag { font-family: 'Orbitron', sans-serif; font-size: 0.72rem; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; color: #94A3B8; margin-bottom: 8px; }
        .radar-pick-main { font-family: 'Orbitron', sans-serif; font-size: 1.12rem; font-weight: 800; color: #F8FAFC; line-height: 1.25; margin-bottom: 6px; }
        .radar-prob-big { font-family: 'JetBrains Mono', monospace; font-size: 1.58rem; font-weight: 800; color: #00F5D4; line-height: 1.1; margin: 4px 0 8px 0; }
        .radar-meta { font-family: 'JetBrains Mono', monospace; font-size: 0.74rem; color: #CBD5E1; background: rgba(5, 8, 17, 0.65); border: 1px solid rgba(148, 163, 184, 0.16); border-radius: 8px; padding: 7px 10px; }

        .grid-game-card {
            background: linear-gradient(155deg, rgba(14, 22, 44, 0.88) 0%, rgba(8, 13, 26, 0.94) 100%);
            border: 1px solid rgba(0, 245, 212, 0.24); border-radius: 16px; padding: 16px 18px 14px 18px;
            margin-bottom: 10px; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.50);
            backdrop-filter: blur(16px); transition: transform 0.18s ease, border-color 0.18s ease;
        }
        .grid-game-card:hover { border-color: rgba(0, 245, 212, 0.55); box-shadow: 0 12px 34px rgba(0, 245, 212, 0.12); }
        .grid-card-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid rgba(148, 163, 184, 0.14); }
        .grid-league-badge { font-family: 'Orbitron', sans-serif; font-size: 0.66rem; font-weight: 800; letter-spacing: 0.08em; color: #00F5D4; background: rgba(0, 245, 212, 0.10); border: 1px solid rgba(0, 245, 212, 0.30); padding: 3px 9px; border-radius: 999px; }
        .grid-time-badge { font-family: 'JetBrains Mono', monospace; font-size: 0.71rem; color: #94A3B8; font-weight: 600; }
        .grid-team-row { display: flex; justify-content: space-between; align-items: center; padding: 7px 10px; margin-bottom: 6px; background: rgba(5, 8, 17, 0.60); border: 1px solid rgba(148, 163, 184, 0.12); border-radius: 10px; }
        .grid-team-info { display: flex; align-items: center; gap: 4px; }
        .grid-team-abbr { font-family: 'Orbitron', sans-serif; font-size: 0.92rem; font-weight: 800; color: #F8FAFC; margin-right: 6px; }
        .grid-team-fullname { font-family: 'Inter', sans-serif; font-size: 0.78rem; color: #94A3B8; font-weight: 500; }
        .form-pills-wrap { display: flex; align-items: center; gap: 3px; }
        .form-pill-w { font-family: 'JetBrains Mono', monospace; font-size: 0.62rem; font-weight: 800; color: #050811; background: #10B981; padding: 1px 5px; border-radius: 4px; }
        .form-pill-l { font-family: 'JetBrains Mono', monospace; font-size: 0.62rem; font-weight: 800; color: #F8FAFC; background: rgba(244, 63, 94, 0.78); padding: 1px 5px; border-radius: 4px; }
        .grid-quick-forecast {
            margin-top: 10px; padding: 9px 12px;
            background: linear-gradient(90deg, rgba(0, 245, 212, 0.08) 0%, rgba(56, 189, 248, 0.08) 100%);
            border: 1px solid rgba(56, 189, 248, 0.28); border-radius: 10px;
            display: flex; justify-content: space-between; align-items: center;
            font-family: 'JetBrains Mono', monospace; font-size: 0.76rem;
        }
        .grid-forecast-lines { color: #F8FAFC; font-weight: 800; }
        .grid-forecast-win { color: #00F5D4; font-weight: 700; font-size: 0.72rem; }

        .game-glass-wrapper {
            background: linear-gradient(165deg, rgba(13, 21, 40, 0.86) 0%, rgba(7, 12, 24, 0.94) 100%);
            border: 1px solid rgba(0, 245, 212, 0.26); border-radius: 18px; padding: 22px 24px;
            margin-bottom: 28px; box-shadow: 0 14px 40px rgba(0, 0, 0, 0.55); backdrop-filter: blur(20px);
        }
        .scoreboard-tv-header {
            background: linear-gradient(90deg, rgba(6, 10, 22, 0.92) 0%, rgba(15, 25, 48, 0.92) 50%, rgba(6, 10, 22, 0.92) 100%);
            border: 1px solid rgba(56, 189, 248, 0.28); border-radius: 14px; padding: 18px 24px;
            margin-bottom: 18px; display: grid; grid-template-columns: 1.25fr 1fr 1.25fr;
            align-items: center; gap: 14px;
        }
        .sb-team-block { display: flex; align-items: center; gap: 14px; }
        .sb-team-block.right { justify-content: flex-end; text-align: right; }
        .team-logo-box-64 { width: 72px; height: 72px; border-radius: 16px; display: flex; align-items: center; justify-content: center; box-shadow: 0 6px 20px rgba(0, 0, 0, 0.50); flex-shrink: 0; padding: 4px; }
        .team-logo-box-64 img { margin-right: 0 !important; }
        .sb-team-name { font-family: 'Orbitron', sans-serif; font-size: 1.18rem; font-weight: 800; color: #F8FAFC; margin: 0; }
        .sb-team-metrics { font-family: 'JetBrains Mono', monospace; font-size: 0.75rem; color: #94A3B8; margin-top: 4px; }
        .sb-center-console { text-align: center; background: rgba(5, 8, 17, 0.78); border: 1px solid rgba(0, 245, 212, 0.26); border-radius: 12px; padding: 10px 14px; }
        .sb-proj-score { font-family: 'JetBrains Mono', monospace; font-size: 1.42rem; font-weight: 800; color: #00F5D4; letter-spacing: 0.04em; }
        .sb-lines-row { display: flex; justify-content: center; gap: 10px; flex-wrap: wrap; margin-top: 6px; font-family: 'JetBrains Mono', monospace; font-size: 0.73rem; color: #CBD5E1; }
        .sb-chip { background: rgba(56, 189, 248, 0.12); border: 1px solid rgba(56, 189, 248, 0.30); padding: 2px 8px; border-radius: 6px; color: #38BDF8; font-weight: 600; }

        .lineup-telemetry-box {
            background: linear-gradient(135deg, rgba(16, 26, 52, 0.88) 0%, rgba(8, 13, 28, 0.94) 100%);
            border: 1px solid rgba(0, 245, 212, 0.28); border-radius: 12px; padding: 12px 16px;
            margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;
        }
        .lineup-metric-pill { background: rgba(5, 8, 17, 0.75); border: 1px solid rgba(148, 163, 184, 0.20); border-radius: 8px; padding: 4px 10px; font-family: 'JetBrains Mono', monospace; font-size: 0.74rem; color: #E2E8F0; }

        .row-label-bar {
            display: flex; align-items: center; justify-content: space-between; margin: 14px 0 10px 0;
            padding: 6px 12px; background: rgba(255, 255, 255, 0.03); border-left: 3px solid #00F5D4; border-radius: 4px 8px 8px 4px;
        }
        .row-label-title { font-family: 'Orbitron', sans-serif; font-size: 0.82rem; font-weight: 700; color: #E2E8F0; letter-spacing: 0.07em; text-transform: uppercase; }
        .row-label-sub { font-family: 'JetBrains Mono', monospace; font-size: 0.72rem; color: #94A3B8; }

        .quant-subcard { background: rgba(9, 14, 28, 0.78); border: 1px solid rgba(148, 163, 184, 0.16); border-radius: 12px; padding: 14px 16px; height: 100%; }
        .quant-subcard-header { display: flex; justify-content: space-between; align-items: center; font-family: 'Orbitron', sans-serif; font-size: 0.76rem; font-weight: 700; color: #94A3B8; margin-bottom: 10px; letter-spacing: 0.06em; }
        .sim-stat-line { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; font-family: 'JetBrains Mono', monospace; }
        .sim-team-label { font-size: 0.85rem; font-weight: 700; color: #F8FAFC; }
        .sim-prob-val { font-size: 1.08rem; font-weight: 800; color: #00F5D4; }
        .sim-odds-badge { font-size: 0.72rem; color: #CBD5E1; background: rgba(255, 255, 255, 0.06); padding: 2px 7px; border-radius: 5px; margin-left: 6px; }
        .quant-bar-track { width: 100%; height: 8px; background: rgba(30, 41, 59, 0.85); border-radius: 999px; overflow: hidden; margin: 8px 0; display: flex; }
        .quant-bar-fill-left { height: 100%; background: linear-gradient(90deg, #38BDF8, #00F5D4); }
        .quant-bar-fill-right { height: 100%; background: linear-gradient(90deg, #8B5CF6, #F43F5E); }

        .win-cond-card { background: linear-gradient(135deg, rgba(16, 185, 129, 0.08) 0%, rgba(9, 14, 28, 0.85) 100%); border: 1px solid rgba(16, 185, 129, 0.28); border-radius: 11px; padding: 12px 15px; height: 100%; }
        .win-cond-title { font-family: 'JetBrains Mono', monospace; font-size: 0.72rem; color: #10B981; text-transform: uppercase; font-weight: 700; margin-bottom: 4px; }
        .win-cond-statement { font-family: 'Inter', sans-serif; font-size: 0.92rem; font-weight: 700; color: #F8FAFC; margin-bottom: 4px; }
        .win-cond-meta { font-family: 'JetBrains Mono', monospace; font-size: 0.72rem; color: #94A3B8; }

        .tactical-ppp-box { background: rgba(9, 14, 28, 0.82); border: 1px solid rgba(56, 189, 248, 0.20); border-radius: 12px; padding: 13px 16px; height: 100%; }
        .edge-pill-pos { background: rgba(16, 185, 129, 0.14); border: 1px solid rgba(16, 185, 129, 0.40); color: #10B981; font-family: 'JetBrains Mono', monospace; font-size: 0.70rem; font-weight: 700; padding: 2px 8px; border-radius: 999px; }
        .edge-pill-neg { background: rgba(244, 63, 94, 0.14); border: 1px solid rgba(244, 63, 94, 0.40); color: #F43F5E; font-family: 'JetBrains Mono', monospace; font-size: 0.70rem; font-weight: 700; padding: 2px 8px; border-radius: 999px; }
        .edge-pill-neu { background: rgba(245, 158, 11, 0.14); border: 1px solid rgba(245, 158, 11, 0.40); color: #F59E0B; font-family: 'JetBrains Mono', monospace; font-size: 0.70rem; font-weight: 700; padding: 2px 8px; border-radius: 999px; }

        .prop-player-card { background: linear-gradient(150deg, rgba(17, 24, 46, 0.86) 0%, rgba(8, 12, 24, 0.94) 100%); border: 1px solid rgba(139, 92, 246, 0.28); border-radius: 12px; padding: 13px 15px; height: 100%; }
        .prop-player-name { font-family: 'Orbitron', sans-serif; font-size: 0.88rem; font-weight: 800; color: #F8FAFC; }
        .prop-lean-over { color: #00F5D4; font-family: 'JetBrains Mono', monospace; font-weight: 800; font-size: 0.96rem; }
        .prop-lean-under { color: #F59E0B; font-family: 'JetBrains Mono', monospace; font-weight: 800; font-size: 0.96rem; }

        div[data-testid="stExpander"] { background: rgba(11, 18, 35, 0.82); border: 1px solid rgba(0, 245, 212, 0.25); border-radius: 14px; margin-bottom: 14px; }
        .slate-slot-badge { font-family: 'Orbitron', sans-serif; font-size: 0.74rem; font-weight: 800; color: #00F5D4; background: rgba(0, 245, 212, 0.10); border: 1px solid rgba(0, 245, 212, 0.28); border-radius: 6px; padding: 4px 10px; display: inline-block; margin-bottom: 6px; }

        @media (max-width: 900px) {
            .scoreboard-tv-header { grid-template-columns: 1fr; text-align: center; }
            .sb-team-block, .sb-team-block.right { justify-content: center; text-align: center; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_form_pills_html(team_abbr: str) -> str:
    """Genera las pastillas visuales W/L de forma reciente para cada equipo en el Grid 3x3."""
    form_list = TEAM_RECENT_FORM.get(str(team_abbr).upper(), ["W", "L", "W", "L", "W"])
    pills = [f'<span class="{"form-pill-w" if item == "W" else "form-pill-l"}">{item}</span>' for item in form_list]
    return f'<div class="form-pills-wrap">{"".join(pills)}</div>'


def format_edge_badge(delta_ppp: float) -> str:
    """Genera la etiqueta HTML de ventaja táctica PPP (Isolation / Pick & Roll)."""
    if delta_ppp >= 0.05:
        return f'<span class="edge-pill-pos">SHARP EDGE {delta_ppp:+.2f} PPP</span>'
    if delta_ppp <= -0.05:
        return f'<span class="edge-pill-neg">DEF WALL {delta_ppp:+.2f} PPP</span>'
    return f'<span class="edge-pill-neu">NEUTRAL {delta_ppp:+.2f} PPP</span>'