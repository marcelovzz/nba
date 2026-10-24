import hashlib
import io
from typing import Dict, List, Optional, Tuple
import pandas as pd
import streamlit as st

from styles import (
    TEAM_COLORS,
    format_edge_badge,
    inject_cyber_quant_css,
    render_form_pills_html,
)
from sync_espn import (
    NBA_SEASON_TARGET,
    escudo_nba_html,
    load_clean_nba_dataframe,
    obtener_calendario_nba_hoy,
    sincronizar_datos_nba_api,
)
from engine_nba import (
    FULL_30_TEAM_SLATE,
    GAME_SLATE_TIMES,
    LINEUP_COLS,
    ROSTER_EDITOR_COLS,
    build_default_lineups_dict,
    calcular_ratings_lineup,
    construir_excel_plantilla_bytes,
    extract_executive_radar,
    generar_dataframe_plantilla_excel,
    obtener_lineup_en_sesion,
    parsear_excel_a_lineups,
    round_to_half_point,
    run_monte_carlo_matchup,
    sincronizar_df_nba_con_lineups,
)

st.set_page_config(
    page_title="TERMINAL SHARP: NBA QUANT SCANNER",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded",
)


def render_executive_radar(radar: Dict, games_count: int, n_sims: int) -> None:
    st.markdown(
        f'<div class="section-banner"><div class="section-banner-title">📡 RADAR EJECUTIVO DE LA JORNADA // TOP SYNDICATE PICKS</div>'
        f'<div class="section-banner-tag">QUINTETOS EN SESIÓN ACTIVOS &bull; {games_count} PARTIDO(S) &bull; {games_count * n_sims:,} SIMS</div></div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4 = st.columns(4)
    lock, sp, tot, pr = radar["lock"], radar["spread"], radar["total"], radar["prop"]

    with c1:
        st.markdown(
            f'<div class="radar-card lock-card"><div><div class="radar-tag">🔒 1. EL LOCK DE LA NOCHE</div>'
            f'<div class="radar-pick-main">{escudo_nba_html(lock["abbr"], 26)}{lock["team"]} ML</div>'
            f'<div class="radar-prob-big">{lock["prob"] * 100:.1f}% WIN</div></div>'
            f'<div class="radar-meta">Fair Odds: <strong>{lock["dec"]} ({lock["amer"]})</strong><br/>{lock["context"]} | Dif: {lock["proj_margin"]:+.1f} pts</div></div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f'<div class="radar-card spread-card"><div><div class="radar-tag">⚡ 2. EL REY DEL SPREAD</div>'
            f'<div class="radar-pick-main">{escudo_nba_html(sp["abbr"], 26)}{sp["pick"]}</div>'
            f'<div class="radar-prob-big" style="color: #38BDF8;">{sp["prob"] * 100:.1f}% COVER</div></div>'
            f'<div class="radar-meta">Fair Odds: <strong>{sp["dec"]} ({sp["amer"]})</strong><br/>{sp["context"]}</div></div>',
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f'<div class="radar-card total-card"><div><div class="radar-tag">🎯 3. LA FIJA DE PUNTOS</div>'
            f'<div class="radar-pick-main">{escudo_nba_html(tot["abbr"], 26)}{tot["pick"]}</div>'
            f'<div class="radar-prob-big" style="color: #F59E0B;">{tot["prob"] * 100:.1f}% HIT</div></div>'
            f'<div class="radar-meta">Fair Odds: <strong>{tot["dec"]} ({tot["amer"]})</strong><br/>{tot["context"]}</div></div>',
            unsafe_allow_html=True,
        )
    with c4:
        lean_word = "Over" if pr["lean_side"] == "OVER" else "Under"
        st.markdown(
            f'<div class="radar-card prop-card"><div><div class="radar-tag">🏀 4. PLAYER PROP LEAN</div>'
            f'<div class="radar-pick-main">{escudo_nba_html(pr["team_abbr"], 26)}{pr["player_name"]} {lean_word} {pr["prop_line"]:.1f}</div>'
            f'<div class="radar-prob-big" style="color: #A78BFA;">{pr["lean_prob"] * 100:.1f}% ({pr["lean_side"]})</div></div>'
            f'<div class="radar-meta">Proyección: <strong>{pr["proj_ppg"]:.1f} Pts</strong> | Fair: {pr["fair_dec"]} ({pr["fair_amer"]})<br/>{pr["matchup_note"]}</div></div>',
            unsafe_allow_html=True,
        )


def render_slate_grid_3x3(sim_results: List[Dict], slate_meta: Optional[List[Dict]] = None) -> None:
    """
    VISTA A: CARTELERA EN CUADRÍCULA (Grid de 3 Columnas)
    Renderiza los partidos del día consumiendo estrictamente las métricas de `st.session_state.lineups_nba`.
    """
    st.markdown(
        f'<div class="section-banner"><div class="section-banner-title">🗓️ CARTELERA NBA EN CUADRÍCULA // {len(sim_results)} JUEGO(S) EN ESCANEO</div>'
        f'<div class="section-banner-tag">HAZ CLIC EN "LEER ANÁLISIS &rarr;" PARA EDITAR QUINTETOS Y VER EL EXPEDIENTE</div></div>',
        unsafe_allow_html=True,
    )

    for row_start in range(0, len(sim_results), 3):
        cols = st.columns(3)
        row_slice = sim_results[row_start : row_start + 3]

        for col_idx, res in enumerate(row_slice):
            global_idx = row_start + col_idx
            away_abbr, home_abbr = res["away_abbr"], res["home_abbr"]
            away_row, home_row = res["away_row"], res["home_row"]

            meta = slate_meta[global_idx] if slate_meta and global_idx < len(slate_meta) else {}
            hora_str = meta.get("hora") or GAME_SLATE_TIMES[global_idx % len(GAME_SLATE_TIMES)]
            estado_str = meta.get("estado") or f"NBA · {NBA_SEASON_TARGET}"
            game_id = meta.get("id_partido") or f"{global_idx}_{away_abbr}_{home_abbr}"

            proj_spread_half = round_to_half_point(abs(res["proj_spread_home"]) - 0.5)
            quick_spread_str = f"{home_abbr} -{proj_spread_half:.1f}" if res["proj_spread_home"] <= 0 else f"{away_abbr} -{proj_spread_half:.1f}"
            quick_total_half = round_to_half_point(res["exp_total_pts"])
            fav_win_pct = res["fav_base_win"] * 100.0

            with cols[col_idx]:
                st.markdown(
                    f"""
                    <div class="grid-game-card">
                        <div class="grid-card-top">
                            <span class="grid-league-badge">{estado_str}</span>
                            <span class="grid-time-badge">🕒 {hora_str} &bull; PACE {res['exp_possessions']:.1f}</span>
                        </div>
                        <div class="grid-team-row">
                            <div class="grid-team-info">
                                {escudo_nba_html(away_abbr, size=32)}
                                <div><span class="grid-team-abbr">{away_abbr}</span><span class="grid-team-fullname">ORTG {away_row['Off_Rtg']:.1f} &middot; DRTG {away_row['Def_Rtg']:.1f}</span></div>
                            </div>
                            {render_form_pills_html(away_abbr)}
                        </div>
                        <div class="grid-team-row">
                            <div class="grid-team-info">
                                {escudo_nba_html(home_abbr, size=32)}
                                <div><span class="grid-team-abbr">{home_abbr}</span><span class="grid-team-fullname">ORTG {home_row['Off_Rtg']:.1f} &middot; DRTG {home_row['Def_Rtg']:.1f}</span></div>
                            </div>
                            {render_form_pills_html(home_abbr)}
                        </div>
                        <div class="grid-quick-forecast">
                            <span class="grid-forecast-lines">{quick_spread_str} &nbsp;|&nbsp; O/U {quick_total_half:.1f}</span>
                            <span class="grid-forecast-win">{res['fav_abbr']} {fav_win_pct:.1f}% WIN</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if st.button("LEER ANÁLISIS →", key=f"btn_open_game_{game_id}_{global_idx}", use_container_width=True):
                    st.session_state.nba_partido_activo = {
                        "idx": global_idx,
                        "id_partido": game_id,
                        "away_team": res["away_team"],
                        "home_team": res["home_team"],
                        "hora": hora_str,
                        "estado": estado_str,
                    }
                    st.rerun()


def render_team_lineup_editor_panel(team_name: str, team_abbr: str, pace_base: float, key_prefix: str) -> None:
    """
    GESTOR INTERACTIVO DE QUINTETOS (st.data_editor)
    Lee y actualiza obligatoriamente `st.session_state.lineups_nba[team_abbr]` y sincroniza `st.session_state.df_nba`.
    """
    full_team_df = obtener_lineup_en_sesion(team_abbr)
    current_lineup = full_team_df[LINEUP_COLS].copy()
    proj_off, proj_def, proj_pace = calcular_ratings_lineup(full_team_df, pace_base)
    total_mins = float(pd.to_numeric(current_lineup["Minutos_Esperados"], errors="coerce").fillna(0.0).sum())

    st.markdown(
        f"""
        <div class="lineup-telemetry-box">
            <div style="display:flex; align-items:center;">
                {escudo_nba_html(team_abbr, 32)}
                <div>
                    <div style="font-family:'Orbitron',sans-serif; font-size:0.92rem; font-weight:800; color:#F8FAFC;">QUINTETO {team_name.upper()} ({team_abbr})</div>
                    <div style="font-family:'JetBrains Mono',monospace; font-size:0.70rem; color:#94A3B8;">Minutos Asignados: <strong>{total_mins:.0f} / 240 min</strong> (Fuente: <code>st.session_state.lineups_nba</code>)</div>
                </div>
            </div>
            <div style="display:flex; gap:6px; flex-wrap:wrap;">
                <span class="lineup-metric-pill">ORTG: <strong style="color:#00F5D4;">{proj_off:.1f}</strong></span>
                <span class="lineup-metric-pill">DRTG: <strong style="color:#38BDF8;">{proj_def:.1f}</strong></span>
                <span class="lineup-metric-pill">PACE: <strong style="color:#F59E0B;">{proj_pace:.1f}</strong></span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    v_key = st.session_state.lineup_editor_version
    edited_lineup = st.data_editor(
        current_lineup,
        key=f"{key_prefix}_lineup_editor_{team_abbr}_{v_key}",
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        disabled=["Posición"],
        column_config={
            "Posición": st.column_config.TextColumn("Posición", width="small"),
            "Jugador": st.column_config.TextColumn("Jugador (Titular / Rotación)", width="medium"),
            "Minutos_Esperados": st.column_config.NumberColumn("Minutos_Esperados", min_value=0.0, max_value=120.0, step=1.0, format="%.1f"),
            "O_EPM": st.column_config.NumberColumn("O_EPM", min_value=-8.0, max_value=10.0, step=0.1, format="%+.1f"),
            "D_EPM": st.column_config.NumberColumn("D_EPM", min_value=-8.0, max_value=10.0, step=0.1, format="%+.1f"),
        },
    )

    if not edited_lineup.equals(current_lineup):
        updated_full = full_team_df.copy()
        for col in LINEUP_COLS:
            updated_full[col] = edited_lineup[col].values
        st.session_state.lineups_nba[team_abbr] = updated_full
        st.session_state.df_nba = sincronizar_df_nba_con_lineups(st.session_state.df_nba, st.session_state.lineups_nba)
        st.rerun()


def render_detailed_matchup_dossier(res: Dict) -> None:
    """
    VISTA B: EXPEDIENTE CUANTITATIVO DETALLADO
    Consume obligatoriamente `st.session_state.lineups_nba` tanto en las tablas de quintetos como en las 4 filas Monte Carlo.
    """
    away_abbr, home_abbr = res["away_abbr"], res["home_abbr"]
    away_row, home_row = res["away_row"], res["home_row"]
    away_div = away_row.get("Division", away_row.get("Conference", "NBA"))
    home_div = home_row.get("Division", home_row.get("Conference", "NBA"))

    away_c1, away_c2 = TEAM_COLORS.get(away_abbr, ("#1E293B", "#38BDF8"))
    home_c1, home_c2 = TEAM_COLORS.get(home_abbr, ("#1E293B", "#00F5D4"))

    proj_spread_str = f"{home_abbr} {res['proj_spread_home']:+.1f}" if res["proj_spread_home"] <= 0 else f"{away_abbr} {-res['proj_spread_home']:+.1f}"
    mkt_spread_str = f"{home_abbr} {res['spread_line_home']:+.1f}"

    st.markdown(
        '<div class="section-banner"><div class="section-banner-title">♟️ GESTOR INTERACTIVO DE QUINTETOS TITULARES (BOTTOM-UP EPM AGGREGATOR)</div>'
        '<div class="section-banner-tag">SINCRONIZADO EN TIEMPO REAL CON st.session_state.lineups_nba</div></div>',
        unsafe_allow_html=True,
    )

    lu_c1, lu_c2 = st.columns(2)
    with lu_c1:
        render_team_lineup_editor_panel(res["away_team"], away_abbr, float(away_row["Base_Pace"]), "detail_away")
    with lu_c2:
        render_team_lineup_editor_panel(res["home_team"], home_abbr, float(home_row["Base_Pace"]), "detail_home")

    away_ortg_diff = float(away_row["Off_Rtg"]) - float(away_row["Base_Off_Rtg"])
    away_drtg_diff = float(away_row["Def_Rtg"]) - float(away_row["Base_Def_Rtg"])
    home_ortg_diff = float(home_row["Off_Rtg"]) - float(home_row["Base_Off_Rtg"])
    home_drtg_diff = float(home_row["Def_Rtg"]) - float(home_row["Base_Def_Rtg"])

    st.markdown(
        f"""
        <div class="game-glass-wrapper">
            <div class="scoreboard-tv-header">
                <div class="sb-team-block">
                    <div class="team-logo-box-64" style="background: linear-gradient(135deg, {away_c1}55, {away_c2}33); border: 1px solid {away_c2};">{escudo_nba_html(away_abbr, size=64)}</div>
                    <div>
                        <div class="sb-team-name">{res['away_team']} <span style="font-size:0.72rem; color:#94A3B8;">(AWAY &bull; {away_div.upper()})</span></div>
                        <div class="sb-team-metrics">ORTG QUINTETO: <strong style="color:#00F5D4;">{away_row['Off_Rtg']:.1f} ({away_ortg_diff:+.1f})</strong> | DRTG: <strong style="color:#38BDF8;">{away_row['Def_Rtg']:.1f} ({away_drtg_diff:+.1f})</strong> | PACE: <strong>{away_row['Pace']:.1f}</strong></div>
                        <div class="sb-team-metrics" style="color:#CBD5E1;">Líderes Activos: <strong>{away_row['Star1_Name']} ({away_row['Star1_PPG']:.1f})</strong> &bull; <strong>{away_row['Star2_Name']} ({away_row['Star2_PPG']:.1f})</strong></div>
                    </div>
                </div>
                <div class="sb-center-console">
                    <div style="font-family:'Orbitron',sans-serif; font-size:0.68rem; color:#94A3B8; letter-spacing:0.10em;">PROYECCIÓN MEDIA ({res['n_sims']:,} SIMS)</div>
                    <div class="sb-proj-score">{away_abbr} {res['exp_away_pts']:.1f} &nbsp;—&nbsp; {res['exp_home_pts']:.1f} {home_abbr}</div>
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
                        <div class="sb-team-metrics">ORTG QUINTETO: <strong style="color:#00F5D4;">{home_row['Off_Rtg']:.1f} ({home_ortg_diff:+.1f})</strong> | DRTG: <strong style="color:#38BDF8;">{home_row['Def_Rtg']:.1f} ({home_drtg_diff:+.1f})</strong> | PACE: <strong>{home_row['Pace']:.1f}</strong></div>
                        <div class="sb-team-metrics" style="color:#CBD5E1;">Líderes Activos: <strong>{home_row['Star1_Name']} ({home_row['Star1_PPG']:.1f})</strong> &bull; <strong>{home_row['Star2_Name']} ({home_row['Star2_PPG']:.1f})</strong></div>
                    </div>
                    <div class="team-logo-box-64" style="background: linear-gradient(135deg, {home_c1}55, {home_c2}33); border: 1px solid {home_c2};">{escudo_nba_html(home_abbr, size=64)}</div>
                </div>
            </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f'<div class="row-label-bar"><span class="row-label-title">📊 FILA 1 // RESUMEN DE SIMULACIÓN MONTE CARLO ({res["n_sims"]:,} ITERACIONES)</span>'
        f'<span class="row-label-sub">WIN % &bull; SPREAD COVER % &bull; TOTAL OVER/UNDER &bull; FAIR ODDS</span></div>',
        unsafe_allow_html=True,
    )

    f1_c1, f1_c2, f1_c3 = st.columns(3)
    with f1_c1:
        st.markdown(
            f'<div class="quant-subcard"><div class="quant-subcard-header"><span>🏆 MONEYLINE (PROB. VICTORIA)</span><span style="color:#00F5D4;">NO-VIG FAIR ODDS</span></div>'
            f'<div class="sim-stat-line"><span class="sim-team-label">{escudo_nba_html(away_abbr, 20)}{away_abbr} (Visita)</span><span><span class="sim-prob-val">{res["away_win_prob"]*100:.1f}%</span><span class="sim-odds-badge">{res["away_ml_dec"]} / {res["away_ml_amer"]}</span></span></div>'
            f'<div class="sim-stat-line"><span class="sim-team-label">{escudo_nba_html(home_abbr, 20)}{home_abbr} (Local)</span><span><span class="sim-prob-val">{res["home_win_prob"]*100:.1f}%</span><span class="sim-odds-badge">{res["home_ml_dec"]} / {res["home_ml_amer"]}</span></span></div>'
            f'<div class="quant-bar-track"><div class="quant-bar-fill-left" style="width: {res["away_win_prob"]*100:.1f}%;"></div><div class="quant-bar-fill-right" style="width: {res["home_win_prob"]*100:.1f}%;"></div></div>'
            f'<div style="font-family:\'JetBrains Mono\',monospace; font-size:0.72rem; color:#94A3B8; margin-top:4px;">Diferencial Esperado: <strong style="color:#F8FAFC;">{home_abbr} {-res["proj_spread_home"]:+.1f} pts</strong></div></div>',
            unsafe_allow_html=True,
        )
    with f1_c2:
        st.markdown(
            f'<div class="quant-subcard"><div class="quant-subcard-header"><span>⚡ SPREAD / HÁNDICAP DINÁMICO</span><span style="color:#38BDF8;">LÍNEA: {home_abbr} {res["spread_line_home"]:+.1f}</span></div>'
            f'<div class="sim-stat-line"><span class="sim-team-label">{escudo_nba_html(away_abbr, 20)}{away_abbr} ({res["spread_line_away"]:+.1f})</span><span><span class="sim-prob-val" style="color:#38BDF8;">{res["away_cover_prob"]*100:.1f}%</span><span class="sim-odds-badge">{res["away_sp_dec"]} / {res["away_sp_amer"]}</span></span></div>'
            f'<div class="sim-stat-line"><span class="sim-team-label">{escudo_nba_html(home_abbr, 20)}{home_abbr} ({res["spread_line_home"]:+.1f})</span><span><span class="sim-prob-val" style="color:#38BDF8;">{res["home_cover_prob"]*100:.1f}%</span><span class="sim-odds-badge">{res["home_sp_dec"]} / {res["home_sp_amer"]}</span></span></div>'
            f'<div class="quant-bar-track"><div class="quant-bar-fill-left" style="width: {res["away_cover_prob"]*100:.1f}%;"></div><div class="quant-bar-fill-right" style="width: {res["home_cover_prob"]*100:.1f}%;"></div></div>'
            f'<div style="font-family:\'JetBrains Mono\',monospace; font-size:0.72rem; color:#94A3B8; margin-top:4px;">Edge vs Línea: <strong style="color:#00F5D4;">{abs(res["proj_spread_home"] - res["spread_line_home"]):.1f} pts de valor</strong></div></div>',
            unsafe_allow_html=True,
        )
    with f1_c3:
        st.markdown(
            f'<div class="quant-subcard"><div class="quant-subcard-header"><span>🎯 PUNTOS TOTALES (O/U)</span><span style="color:#F59E0B;">LÍNEA: {res["total_line"]:.1f} PTS</span></div>'
            f'<div class="sim-stat-line"><span class="sim-team-label">OVER {res["total_line"]:.1f}</span><span><span class="sim-prob-val" style="color:#F59E0B;">{res["over_prob"]*100:.1f}%</span><span class="sim-odds-badge">{res["over_dec"]} / {res["over_amer"]}</span></span></div>'
            f'<div class="sim-stat-line"><span class="sim-team-label">UNDER {res["total_line"]:.1f}</span><span><span class="sim-prob-val" style="color:#F59E0B;">{res["under_prob"]*100:.1f}%</span><span class="sim-odds-badge">{res["under_dec"]} / {res["under_amer"]}</span></span></div>'
            f'<div class="quant-bar-track"><div class="quant-bar-fill-left" style="width: {res["over_prob"]*100:.1f}%;"></div><div class="quant-bar-fill-right" style="width: {res["under_prob"]*100:.1f}%;"></div></div>'
            f'<div style="font-family:\'JetBrains Mono\',monospace; font-size:0.72rem; color:#94A3B8; margin-top:4px;">Banda Sim (P10 / P50 / P90): <strong style="color:#F8FAFC;">{res["total_p10"]:.0f} / {res["total_p50"]:.0f} / {res["total_p90"]:.0f} pts</strong></div></div>',
            unsafe_allow_html=True,
        )

    delta_3pm = (res["win_given_3pm"] - res["fav_base_win"]) * 100
    delta_tov = (res["win_given_tov"] - res["fav_base_win"]) * 100
    delta_ortg = (res["win_given_ortg"] - res["fav_base_win"]) * 100
    fav_row = home_row if res["fav_abbr"] == home_abbr else away_row

    st.markdown(
        f'<div class="row-label-bar" style="border-left-color: #10B981;"><span class="row-label-title">🔑 FILA 2 // "CÓMO GANA EL FAVORITO" ({res["fav_name"].upper()} - WIN BASE {res["fav_base_win"]*100:.1f}%)</span>'
        f'<span class="row-label-sub">GATILLOS DE PROBABILIDAD CONDICIONAL EN LAS {res["n_sims"]:,} SIMULACIONES</span></div>',
        unsafe_allow_html=True,
    )

    f2_c1, f2_c2, f2_c3 = st.columns(3)
    with f2_c1:
        st.markdown(
            f'<div class="win-cond-card"><div class="win-cond-title">🎯 GATILLO DE VOLUMEN PERIMETRAL (3PM)</div>'
            f'<div class="win-cond-statement">{res["fav_abbr"]} gana el <span style="color:#00F5D4;">{res["win_given_3pm"]*100:.1f}%</span> si anota &gt;{res["threepm_threshold"]} triples</div>'
            f'<div class="win-cond-meta">Impulso Condicional: <strong>{delta_3pm:+.1f}% vs Win % Base</strong> | 3PA Rate: {float(fav_row["3PA_Rate"])*100:.1f}%</div></div>',
            unsafe_allow_html=True,
        )
    with f2_c2:
        st.markdown(
            f'<div class="win-cond-card"><div class="win-cond-title">🛡️ GATILLO DE PROTECCIÓN DE BALÓN (TOV)</div>'
            f'<div class="win-cond-statement">{res["fav_abbr"]} gana el <span style="color:#00F5D4;">{res["win_given_tov"]*100:.1f}%</span> si comete &lt;{res["tov_threshold"]} pérdidas</div>'
            f'<div class="win-cond-meta">Impulso Condicional: <strong>{delta_tov:+.1f}% vs Win % Base</strong> | TOV% Base: {float(fav_row["TOV_Pct"]):.1f}%</div></div>',
            unsafe_allow_html=True,
        )
    with f2_c3:
        st.markdown(
            f'<div class="win-cond-card"><div class="win-cond-title">⚡ GATILLO DE EFICIENCIA POR 100 POS (ORTG)</div>'
            f'<div class="win-cond-statement">{res["fav_abbr"]} gana el <span style="color:#00F5D4;">{res["win_given_ortg"]*100:.1f}%</span> si supera {res["ortg_threshold"]:.1f} OffRtg</div>'
            f'<div class="win-cond-meta">Impulso Condicional: <strong>{delta_ortg:+.1f}% vs Win % Base</strong> | Pace Proy: {res["exp_possessions"]:.1f} pos</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div class="row-label-bar" style="border-left-color: #38BDF8;"><span class="row-label-title">♟️ FILA 3 // ANÁLISIS TÁCTICO SYNERGY (ISO PPP &amp; PNR PPP VS DEFENSAS RIVALES)</span>'
        '<span class="row-label-sub">PUNTOS POR POSESIÓN (SYNERGY PLAYTYPE MATRIX)</span></div>',
        unsafe_allow_html=True,
    )

    f3_c1, f3_c2 = st.columns(2)
    with f3_c1:
        st.markdown(
            f'<div class="tactical-ppp-box"><div class="quant-subcard-header"><span>⚔️ ATAQUE {away_abbr} vs DEFENSA {home_abbr}</span><span>IMPACTO POR ESTILO</span></div>'
            f'<div class="sim-stat-line"><span class="sim-team-label" style="font-size:0.80rem;">ISOLATION: {away_abbr} Off ({away_row["Iso_PPP_Off"]:.2f}) vs {home_abbr} Def ({home_row["Iso_PPP_Def"]:.2f})</span>{format_edge_badge(res["away_iso_delta"])}</div>'
            f'<div class="sim-stat-line" style="margin-top:8px;"><span class="sim-team-label" style="font-size:0.80rem;">PICK &amp; ROLL: {away_abbr} Off ({away_row["PnR_PPP_Off"]:.2f}) vs {home_abbr} Def ({home_row["PnR_PPP_Def"]:.2f})</span>{format_edge_badge(res["away_pnr_delta"])}</div>'
            f'<div style="font-family:\'JetBrains Mono\',monospace; font-size:0.72rem; color:#94A3B8; margin-top:8px;">Ajuste Neto Táctico {away_abbr}: <strong style="color:#F8FAFC;">{res["away_tactical_ortg_adj"]:+.2f} pts / 100 pos</strong></div></div>',
            unsafe_allow_html=True,
        )
    with f3_c2:
        st.markdown(
            f'<div class="tactical-ppp-box"><div class="quant-subcard-header"><span>⚔️ ATAQUE {home_abbr} vs DEFENSA {away_abbr}</span><span>IMPACTO POR ESTILO</span></div>'
            f'<div class="sim-stat-line"><span class="sim-team-label" style="font-size:0.80rem;">ISOLATION: {home_abbr} Off ({home_row["Iso_PPP_Off"]:.2f}) vs {away_abbr} Def ({away_row["Iso_PPP_Def"]:.2f})</span>{format_edge_badge(res["home_iso_delta"])}</div>'
            f'<div class="sim-stat-line" style="margin-top:8px;"><span class="sim-team-label" style="font-size:0.80rem;">PICK &amp; ROLL: {home_abbr} Off ({home_row["PnR_PPP_Off"]:.2f}) vs {away_abbr} Def ({away_row["PnR_PPP_Def"]:.2f})</span>{format_edge_badge(res["home_pnr_delta"])}</div>'
            f'<div style="font-family:\'JetBrains Mono\',monospace; font-size:0.72rem; color:#94A3B8; margin-top:8px;">Ajuste Neto Táctico {home_abbr}: <strong style="color:#F8FAFC;">{res["home_tactical_ortg_adj"]:+.2f} pts / 100 pos</strong></div></div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div class="row-label-bar" style="border-left-color: #8B5CF6;"><span class="row-label-title">🏀 FILA 4 // PLAYER PROPS LEANS (SINCRONIZADO CON QUINTETOS Y MINUTOS ESPERADOS)</span>'
        '<span class="row-label-sub">SIMULACIÓN INDIVIDUAL AJUSTADA POR ESTILO DE DEFENSA RIVAL (ISO / PNR)</span></div>',
        unsafe_allow_html=True,
    )

    prop_cols = st.columns(4)
    for idx, prop in enumerate(res["props"]):
        lean_cls = "prop-lean-over" if prop["lean_side"] == "OVER" else "prop-lean-under"
        with prop_cols[idx]:
            st.markdown(
                f'<div class="prop-player-card"><div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">'
                f'<span class="prop-player-name">{escudo_nba_html(prop["team_abbr"], 22)}{prop["player_name"]}</span><span class="sb-chip" style="font-size:0.66rem;">{prop["team_abbr"]} &bull; {prop["style"]}</span></div>'
                f'<div style="font-family:\'JetBrains Mono\',monospace; font-size:0.73rem; color:#94A3B8; margin-bottom:6px;">PPG Vigente: <strong>{prop["base_ppg"]:.1f}</strong> &rarr; Proy: <strong style="color:#F8FAFC;">{prop["proj_ppg"]:.1f} Pts</strong></div>'
                f'<div style="background:rgba(5,8,17,0.72); border:1px solid rgba(148,163,184,0.16); border-radius:8px; padding:7px 10px; margin-bottom:6px;">'
                f'<div class="{lean_cls}">{prop["lean_side"]} {prop["prop_line"]:.1f} PTS ({prop["lean_prob"]*100:.1f}%)</div>'
                f'<div style="font-family:\'JetBrains Mono\',monospace; font-size:0.70rem; color:#CBD5E1; margin-top:2px;">Fair Odds: <strong>{prop["fair_dec"]} ({prop["fair_amer"]})</strong> | IQR: {prop["p25"]:.0f}-{prop["p75"]:.0f}</div></div>'
                f'<div style="font-family:\'JetBrains Mono\',monospace; font-size:0.68rem; color:#94A3B8;">{prop["matchup_note"]}</div></div>',
                unsafe_allow_html=True,
            )

    st.markdown("</div>", unsafe_allow_html=True)


def init_session_state() -> None:
    if "lineups_nba" not in st.session_state:
        st.session_state.lineups_nba = build_default_lineups_dict()
    if "df_nba" not in st.session_state:
        sincronizar_datos_nba_api(season=NBA_SEASON_TARGET)
        st.session_state.df_nba = sincronizar_df_nba_con_lineups(
            st.session_state.df_nba, st.session_state.lineups_nba
        )
    if "calendario_nba" not in st.session_state:
        st.session_state.calendario_nba = obtener_calendario_nba_hoy()
    if "modo_manual_respaldo" not in st.session_state:
        st.session_state.modo_manual_respaldo = False
    if "lineup_editor_version" not in st.session_state:
        st.session_state.lineup_editor_version = 0
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
    if "excel_procesado_sig" not in st.session_state:
        st.session_state.excel_procesado_sig = None
    if "excel_cargado_ok" not in st.session_state:
        st.session_state.excel_cargado_ok = False
    if "df_excel_preview" not in st.session_state:
        st.session_state.df_excel_preview = None


def reset_all_lineups() -> None:
    st.session_state.lineups_nba = build_default_lineups_dict()
    st.session_state.df_nba = sincronizar_df_nba_con_lineups(
        st.session_state.df_nba, st.session_state.lineups_nba
    )
    st.session_state.excel_procesado_sig = None
    st.session_state.excel_cargado_ok = False
    st.session_state.df_excel_preview = None
    st.session_state.lineup_editor_version += 1
    st.session_state.roster_editor_version += 1


def sync_edited_roster_to_session(edited_subset: pd.DataFrame) -> None:
    """Sincroniza ediciones realizadas en el Gestor Global de Rosters con st.session_state.df_nba."""
    master_df = st.session_state.df_nba.copy()
    for idx in edited_subset.index:
        if idx not in master_df.index:
            continue
        old_s1_name, old_s1_ppg = str(master_df.loc[idx, "Star1_Name"]), float(master_df.loc[idx, "Star1_PPG"])
        old_s2_name, old_s2_ppg = str(master_df.loc[idx, "Star2_Name"]), float(master_df.loc[idx, "Star2_PPG"])
        new_s1_name, new_s1_ppg = str(edited_subset.loc[idx, "Star1_Name"]), float(edited_subset.loc[idx, "Star1_PPG"])
        new_s2_name, new_s2_ppg = str(edited_subset.loc[idx, "Star2_Name"]), float(edited_subset.loc[idx, "Star2_PPG"])

        for col in ROSTER_EDITOR_COLS:
            master_df.loc[idx, col] = edited_subset.loc[idx, col]

        if new_s1_name != old_s1_name or abs(new_s1_ppg - old_s1_ppg) > 1e-4:
            master_df.loc[idx, "Star1_Line"] = round_to_half_point(max(0.5, new_s1_ppg - 0.5))
        if new_s2_name != old_s2_name or abs(new_s2_ppg - old_s2_ppg) > 1e-4:
            master_df.loc[idx, "Star2_Line"] = round_to_half_point(max(0.5, new_s2_ppg - 0.5))

    st.session_state.df_nba = master_df


def render_live_roster_manager() -> None:
    """Renderiza el Gestor de Roster & Traspasos (st.data_editor) sincronizado con los quintetos en sesión."""
    with st.expander("⚙️ Gestor de Roster & Traspasos (Live Trades / Injuries - 30 Equipos)", expanded=False):
        top_c1, top_c2 = st.columns([3.4, 1.2])
        with top_c1:
            st.markdown(
                '<div style="font-family:\'JetBrains Mono\',monospace; font-size:0.77rem; color:#CBD5E1; margin-bottom:6px;">Métricas activas en <code>st.session_state.df_nba</code> (sincronizadas automáticamente con tu Excel o ediciones tácticas).</div>',
                unsafe_allow_html=True,
            )
        with top_c2:
            if st.button("🔄 Restablecer Roster Oficial", use_container_width=True):
                clean_df, src_label = load_clean_nba_dataframe()
                st.session_state.lineups_nba = build_default_lineups_dict()
                st.session_state.df_nba = sincronizar_df_nba_con_lineups(clean_df, st.session_state.lineups_nba)
                st.session_state.data_source_label = src_label
                st.session_state.excel_procesado_sig = None
                st.session_state.excel_cargado_ok = False
                st.session_state.df_excel_preview = None
                st.session_state.roster_editor_version += 1
                st.session_state.lineup_editor_version += 1
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
                "Star1_PPG": st.column_config.NumberColumn("Star1 PPG", min_value=0.0, max_value=60.0, step=0.5, format="%.1f"),
                "Star2_Name": st.column_config.TextColumn("Estrella 2 (Co-Líder)", width="medium"),
                "Star2_PPG": st.column_config.NumberColumn("Star2 PPG", min_value=0.0, max_value=60.0, step=0.5, format="%.1f"),
                "Pace": st.column_config.NumberColumn("Pace Activo", min_value=85.0, max_value=115.0, step=0.2, format="%.1f"),
                "Off_Rtg": st.column_config.NumberColumn("Off_Rtg Activo", min_value=95.0, max_value=135.0, step=0.2, format="%.1f"),
                "Def_Rtg": st.column_config.NumberColumn("Def_Rtg Activo", min_value=95.0, max_value=135.0, step=0.2, format="%.1f"),
            },
        )

        if not edited_df.equals(current_subset):
            sync_edited_roster_to_session(edited_df)
            st.rerun()


def render_manual_slate_selector(df_teams: pd.DataFrame, n_sims: int, expanded_default: bool = True) -> None:
    """Renderiza el selector manual de cruces como respaldo cuando no hay juegos en ESPN o a petición del usuario."""
    team_list = df_teams["Team"].tolist()
    num_games = int(st.session_state.get("num_games", 6))

    with st.expander(f"🎛️ SELECTOR MANUAL DE CRUCES DE RESPALDO ({num_games} JUEGO{'S' if num_games > 1 else ''})", expanded=expanded_default):
        num_games = st.slider(
            "¿Cuántos juegos deseas simular manualmente?",
            min_value=1,
            max_value=15,
            key="num_games",
            help="Elige de 1 a 15 partidos para simular en la cuadrícula 3x3.",
        )

        selected_matchups: List[Tuple[str, str]] = list(st.session_state.active_matchups[:num_games])
        if len(selected_matchups) < num_games:
            for extra_idx in range(len(selected_matchups), num_games):
                fallback_pair = FULL_30_TEAM_SLATE[extra_idx % len(FULL_30_TEAM_SLATE)]
                if fallback_pair[0] in team_list and fallback_pair[1] in team_list:
                    selected_matchups.append(fallback_pair)

        with st.form("manual_backup_slate_form", clear_on_submit=False):
            form_selections: List[Tuple[str, str]] = []
            form_custom_lines: Dict[int, Tuple[Optional[float], Optional[float]]] = {}

            for i in range(num_games):
                default_away, default_home = FULL_30_TEAM_SLATE[i % len(FULL_30_TEAM_SLATE)]
                if i < len(selected_matchups):
                    prev_away, prev_home = selected_matchups[i]
                    if prev_away in team_list and prev_home in team_list:
                        default_away, default_home = prev_away, prev_home

                away_idx = team_list.index(default_away) if default_away in team_list else (i * 2) % len(team_list)
                home_idx = team_list.index(default_home) if default_home in team_list else (i * 2 + 1) % len(team_list)

                st.markdown(f'<div class="slate-slot-badge">🏀 JUEGO MANUAL #{i + 1} DE {num_games}</div>', unsafe_allow_html=True)
                col_a, col_h, col_sp, col_tot = st.columns([2.2, 2.2, 1.1, 1.1])

                with col_a:
                    sel_away = st.selectbox(f"Visitante (Juego #{i + 1})", options=team_list, index=away_idx, key=f"form_away_{i}")
                with col_h:
                    sel_home = st.selectbox(f"Local (Juego #{i + 1})", options=team_list, index=home_idx, key=f"form_home_{i}")
                with col_sp:
                    sel_sp = st.number_input(f"Spread Local #{i + 1} (0=Auto)", value=0.0, step=0.5, key=f"form_sp_{i}")
                with col_tot:
                    sel_tot = st.number_input(f"Total O/U #{i + 1} (0=Auto)", value=0.0, step=0.5, key=f"form_tot_{i}")

                form_selections.append((sel_away, sel_home))
                form_custom_lines[i] = (sel_sp if sel_sp != 0.0 else None, sel_tot if sel_tot != 0.0 else None)

            submitted = st.form_submit_button(
                f"⚡ ESCANEAR {num_games} PARTIDO(S) SELECCIONADOS ({num_games * n_sims:,} SIMULACIONES MONTE CARLO)",
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
                    st.warning(f"Atención: El Juego #{', #'.join(map(str, duplicate_team_games))} tenía el mismo equipo como Visitante y Local y fue omitido.")

                if valid_matchups:
                    st.session_state.active_matchups = valid_matchups
                    st.session_state.active_custom_lines = valid_lines
                    st.session_state.modo_manual_respaldo = True
                    st.session_state.config_expanded = False
                    st.rerun()


def main() -> None:
    inject_cyber_quant_css()
    init_session_state()

    st.sidebar.markdown(
        '<div style="font-family:\'Orbitron\',sans-serif; font-size:1.05rem; font-weight:900; color:#00F5D4; letter-spacing:0.08em; margin-bottom:4px;">⚡ SHARP SYNDICATE</div>'
        '<div style="font-family:\'JetBrains Mono\',monospace; font-size:0.72rem; color:#94A3B8; margin-bottom:14px;">MODULAR QUANT ARCHITECTURE v10.1</div>',
        unsafe_allow_html=True,
    )

    # ==========================================================================
    # MÓDULO DE DESCARGA Y CARGA REACTIVA DE ROSTERS EN EXCEL (.XLSX)
    # ==========================================================================
    with st.sidebar.expander("📁 Importar / Exportar Rosters en Excel", expanded=True):
        excel_bytes = construir_excel_plantilla_bytes(
            lineups_dict=st.session_state.lineups_nba,
            df_teams=st.session_state.df_nba,
        )

        st.download_button(
            label="📥 Descargar Plantilla Roster (Excel)",
            data=excel_bytes,
            file_name="nba_rosters_plantilla.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

        archivo_subido = st.file_uploader(
            "Sube tu Excel editado (.xlsx)",
            type=["xlsx"],
            key="uploader_excel_rosters",
        )

        if archivo_subido is not None:
            raw_bytes = archivo_subido.getvalue()
            content_hash = hashlib.md5(raw_bytes).hexdigest()
            excel_signature = f"{archivo_subido.name}_{len(raw_bytes)}_{content_hash}"

            # 1. RECARGA INMEDIATA TRAS LA SUBIDA (con bandera anti-bucle infinito)
            if st.session_state.get("excel_procesado_sig") != excel_signature:
                try:
                    df_subido = pd.read_excel(io.BytesIO(raw_bytes))
                    lineups_actualizados = parsear_excel_a_lineups(df_subido, strict_240=False)

                    # Guardar en st.session_state.lineups_nba y sincronizar st.session_state.df_nba
                    st.session_state.lineups_nba = lineups_actualizados
                    st.session_state.df_nba = sincronizar_df_nba_con_lineups(
                        st.session_state.df_nba, lineups_actualizados
                    )
                    st.session_state.df_excel_preview = df_subido.head(12).copy()
                    st.session_state.data_source_label = f"Excel Activo ({archivo_subido.name})"
                    st.session_state.excel_procesado_sig = excel_signature
                    st.session_state.excel_cargado_ok = True
                    st.session_state.lineup_editor_version += 1
                    st.session_state.roster_editor_version += 1
                    st.rerun()
                except Exception as exc:
                    st.session_state.excel_cargado_ok = False
                    st.error(f"Error al procesar el archivo Excel: {exc}")
        else:
            if st.session_state.get("excel_procesado_sig") is not None:
                st.session_state.excel_procesado_sig = None
                st.session_state.excel_cargado_ok = False
                st.session_state.df_excel_preview = None

    # 3. FEEDBACK VISUAL EN LA BARRA LATERAL Y VISTA PREVIA DE CONFIRMACIÓN
    if st.session_state.get("excel_cargado_ok") and st.session_state.get("df_excel_preview") is not None:
        st.sidebar.success("✅ Roster cargado desde Excel exitosamente")
        st.sidebar.caption("🔍 Vista previa en memoria (`st.session_state.lineups_nba`):")
        st.sidebar.dataframe(
            st.session_state.df_excel_preview[["Team_Abbr", "Pos", "Jugador", "Minutos", "O_EPM", "D_EPM"]],
            use_container_width=True,
            hide_index=True,
            height=180,
        )

    with st.sidebar:
        st.markdown("### 🗓️ CARTELERA EN VIVO (ESPN API)")
        if st.button("🔄 Actualizar Calendario de Hoy", use_container_width=True):
            with st.spinner("Consultando calendario oficial del día desde ESPN Scoreboard API..."):
                st.session_state.calendario_nba = obtener_calendario_nba_hoy()
                st.session_state.nba_partido_activo = None
                if st.session_state.calendario_nba:
                    st.session_state.modo_manual_respaldo = False
                    st.success(f"Calendario actualizado: {len(st.session_state.calendario_nba)} partido(s) hoy.")
                else:
                    st.info("No se encontraron partidos programados hoy en ESPN. Respaldo manual activo.")

        if st.session_state.calendario_nba:
            st.checkbox(
                "🎛️ Usar Selector Manual de Respaldo",
                key="modo_manual_respaldo",
                help="Activa esta casilla si deseas simular cruces personalizados en lugar del calendario oficial de hoy.",
            )

        st.markdown("---")
        st.markdown("### 🌐 TELEMETRÍA NBA.COM API")
        if st.button("🔄 Forzar Sincronización con NBA.com", use_container_width=True):
            st.cache_data.clear()
            with st.spinner(f"Descargando telemetría oficial desde stats.nba.com (Temporada {NBA_SEASON_TARGET})..."):
                _, _, _, sync_ok = sincronizar_datos_nba_api(season=NBA_SEASON_TARGET)
                st.session_state.df_nba = sincronizar_df_nba_con_lineups(
                    st.session_state.df_nba, st.session_state.lineups_nba
                )
                st.session_state.roster_editor_version += 1
                st.session_state.lineup_editor_version += 1
                if sync_ok:
                    st.success(f"Sincronización exitosa con NBA.com ({NBA_SEASON_TARGET}).")

        uploaded_csv = st.file_uploader("Cargar nba_stats_completo.csv (Opcional)", type=["csv"])
        if uploaded_csv is not None:
            custom_df, custom_label = load_clean_nba_dataframe(uploaded_csv)
            st.session_state.df_nba = sincronizar_df_nba_con_lineups(custom_df, st.session_state.lineups_nba)
            st.session_state.data_source_label = custom_label

        st.button("🔄 Restablecer Todos los Quintetos", on_click=reset_all_lineups, use_container_width=True)

        if st.session_state.nba_partido_activo is not None:
            if st.button("← Volver a la Cartelera NBA", key="sidebar_back_btn", use_container_width=True):
                st.session_state.nba_partido_activo = None
                st.rerun()

        st.markdown("---")
        st.markdown("### ⚙️ PARÁMETROS DEL MOTOR")
        n_sims = st.select_slider("Iteraciones Monte Carlo / Partido", options=[1000, 2500, 5000, 10000, 20000], value=5000)
        hfa_pts = st.slider("Factor de Localía (HFA Puntos)", min_value=0.0, max_value=5.0, value=2.5, step=0.1)
        base_seed = st.number_input("Semilla Cuantitativa (RNG Seed)", min_value=1, max_value=999999, value=2026, step=1)

        st.markdown("---")
        st.caption(f"🗓️ Partidos ESPN Hoy: {len(st.session_state.calendario_nba)}")
        st.caption(f"📂 Fuente Ratings: {st.session_state.get('data_source_label', 'Respaldo Local')}")

    df_teams = st.session_state.df_nba
    team_list = df_teams["Team"].tolist()
    calendario_hoy = st.session_state.calendario_nba

    espn_matchups_validos: List[Tuple[str, str]] = []
    espn_meta_validos: List[Dict] = []

    for item in calendario_hoy:
        a_abbr = str(item.get("away_abbr", "")).upper()
        h_abbr = str(item.get("home_abbr", "")).upper()
        a_match = df_teams[df_teams["Team_Abbr"].astype(str).str.upper() == a_abbr]
        h_match = df_teams[df_teams["Team_Abbr"].astype(str).str.upper() == h_abbr]
        if not a_match.empty and not h_match.empty:
            espn_matchups_validos.append((str(a_match.iloc[0]["Team"]), str(h_match.iloc[0]["Team"])))
            espn_meta_validos.append(item)

    usar_espn_en_vivo = bool(espn_matchups_validos) and not st.session_state.get("modo_manual_respaldo", False)
    active_games_count = len(espn_matchups_validos) if usar_espn_en_vivo else int(st.session_state.get("num_games", 6))
    slate_mode_badge = f"ESPN SCOREBOARD LIVE ({len(espn_matchups_validos)} JUEGOS HOY)" if usar_espn_en_vivo else "SELECTOR MANUAL DE RESPALDO"

    st.markdown(
        f"""
        <div class="tv-master-header">
            <div class="tv-top-bar">
                <div class="syndicate-badge"><span class="pulse-dot"></span> SHARP SYNDICATE // {slate_mode_badge}</div>
                <div class="font-mono" style="font-size:0.76rem; color:#94A3B8;">
                    CALENDARIO: <strong style="color:#00F5D4;">ESPN SITE API v2</strong> &nbsp;|&nbsp;
                    SIMULATIONS: <strong style="color:#F8FAFC;">{n_sims:,} / GAME</strong> &nbsp;|&nbsp;
                    HFA: <strong style="color:#38BDF8;">+{hfa_pts:.1f} PTS</strong>
                </div>
            </div>
            <div class="tv-title">TERMINAL SHARP: NBA QUANT SCANNER</div>
            <div class="tv-subtitle">Arquitectura modular limpia (<code>styles.py</code>, <code>sync_espn.py</code>, <code>engine_nba.py</code>, <code>app.py</code>) con sincronización reactiva de Excel en <code>st.session_state.lineups_nba</code> y motor Monte Carlo de 5,000 posesiones.</div>
            <div class="tv-telemetry-strip">
                <div class="telemetry-pill">CARTELERA HOY: <strong>{active_games_count} PARTIDO(S)</strong></div>
                <div class="telemetry-pill">ITERACIONES TOTALES: <strong>{active_games_count * n_sims:,}</strong></div>
                <div class="telemetry-pill">FUENTE EN MEMORIA: <strong>{st.session_state.get('data_source_label', 'nba_stats_completo.csv')}</strong></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    render_live_roster_manager()

    if st.session_state.nba_partido_activo is None:
        with st.expander("♟️ Laboratorio Táctico de Quintetos Titulares (30 Franquicias - O_EPM / D_EPM)", expanded=False):
            q_col1, q_col2 = st.columns([2.5, 1.5])
            with q_col1:
                chosen_team_for_lineup = st.selectbox("Selecciona una franquicia para editar su Quinteto Titular y Rotación (240 min):", options=team_list, index=0)
            with q_col2:
                st.write("")
                if st.button("🔄 Restablecer Quintetos Base (30 Equipos)", key="btn_reset_global_lineups", use_container_width=True):
                    reset_all_lineups()
                    st.rerun()

            chosen_row = df_teams[df_teams["Team"] == chosen_team_for_lineup].iloc[0]
            render_team_lineup_editor_panel(chosen_team_for_lineup, str(chosen_row["Team_Abbr"]), float(chosen_row.get("Base_Pace", chosen_row["Pace"])), "global_lab")

        if usar_espn_en_vivo:
            selected_matchups = espn_matchups_validos
            slate_meta = espn_meta_validos
            render_manual_slate_selector(df_teams, n_sims=n_sims, expanded_default=False)
        else:
            if not espn_matchups_validos:
                st.info(
                    "📅 Hoy no hay partidos programados en el calendario oficial de ESPN (o el servicio está fuera de horario). "
                    "Puedes seleccionar y simular manualmente cualquier cruce de las 30 franquicias a continuación."
                )
            render_manual_slate_selector(df_teams, n_sims=n_sims, expanded_default=st.session_state.config_expanded)
            num_games_manual = int(st.session_state.get("num_games", 6))
            selected_matchups = list(st.session_state.active_matchups[:num_games_manual])
            if len(selected_matchups) < num_games_manual:
                for extra_idx in range(len(selected_matchups), num_games_manual):
                    fallback_pair = FULL_30_TEAM_SLATE[extra_idx % len(FULL_30_TEAM_SLATE)]
                    if fallback_pair[0] in team_list and fallback_pair[1] in team_list:
                        selected_matchups.append(fallback_pair)
            slate_meta = None

        if not selected_matchups:
            st.info("Selecciona al menos un partido válido para visualizar la Cartelera NBA.")
            return

        # 2. CONSUMO ESTRICTO DE st.session_state.lineups_nba EN LA CUADRÍCULA Y RADAR
        sim_results: List[Dict] = []
        for idx, (away_name, home_name) in enumerate(selected_matchups):
            away_row_raw = df_teams[df_teams["Team"] == away_name].iloc[0]
            home_row_raw = df_teams[df_teams["Team"] == home_name].iloc[0]
            away_abbr, home_abbr = str(away_row_raw["Team_Abbr"]), str(home_row_raw["Team_Abbr"])
            c_sp, c_tot = (None, None) if usar_espn_en_vivo else st.session_state.active_custom_lines.get(idx, (None, None))

            away_lu_session = obtener_lineup_en_sesion(away_abbr)
            home_lu_session = obtener_lineup_en_sesion(home_abbr)

            res = run_monte_carlo_matchup(
                away_row_raw=away_row_raw,
                home_row_raw=home_row_raw,
                away_lineup=away_lu_session,
                home_lineup=home_lu_session,
                n_sims=n_sims,
                hfa_pts=hfa_pts,
                custom_spread_home=c_sp,
                custom_total_line=c_tot,
                seed=int(base_seed) + idx * 101,
            )
            sim_results.append(res)

        radar_picks = extract_executive_radar(sim_results)
        render_executive_radar(radar_picks, games_count=len(sim_results), n_sims=n_sims)
        render_slate_grid_3x3(sim_results, slate_meta=slate_meta)

    else:
        # 2. CONSUMO ESTRICTO DE st.session_state.lineups_nba EN LA VISTA B (DETALLE)
        active_info = st.session_state.nba_partido_activo
        game_idx = int(active_info.get("idx", 0))
        away_name, home_name = str(active_info["away_team"]), str(active_info["home_team"])
        hora_info, estado_info = str(active_info.get("hora", "")), str(active_info.get("estado", ""))

        nav_c1, nav_c2, nav_c3 = st.columns([1.4, 2.5, 1.1])
        with nav_c1:
            if st.button("← Volver a la Cartelera NBA", key="top_back_to_grid_btn", use_container_width=True):
                st.session_state.nba_partido_activo = None
                st.rerun()
        with nav_c2:
            meta_suffix = f" ({estado_info} • {hora_info})" if hora_info or estado_info else ""
            st.markdown(
                f'<div style="display:flex; align-items:center; height:38px; font-family:\'JetBrains Mono\',monospace; font-size:0.80rem; color:#00F5D4;">📂 EXPEDIENTE ACTIVO: <strong style="color:#F8FAFC; margin-left:8px;">{away_name.upper()} @ {home_name.upper()}{meta_suffix}</strong></div>',
                unsafe_allow_html=True,
            )
        with nav_c3:
            if st.button("🔄 Reset Quintetos a Base", key="reset_matchup_lineups_btn", use_container_width=True):
                a_abbr = str(df_teams[df_teams["Team"] == away_name].iloc[0]["Team_Abbr"])
                h_abbr = str(df_teams[df_teams["Team"] == home_name].iloc[0]["Team_Abbr"])
                default_dict = build_default_lineups_dict()
                st.session_state.lineups_nba[a_abbr] = default_dict[a_abbr]
                st.session_state.lineups_nba[h_abbr] = default_dict[h_abbr]
                st.session_state.df_nba = sincronizar_df_nba_con_lineups(
                    st.session_state.df_nba, st.session_state.lineups_nba
                )
                st.session_state.lineup_editor_version += 1
                st.rerun()

        away_row_raw = df_teams[df_teams["Team"] == away_name].iloc[0]
        home_row_raw = df_teams[df_teams["Team"] == home_name].iloc[0]
        away_abbr, home_abbr = str(away_row_raw["Team_Abbr"]), str(home_row_raw["Team_Abbr"])
        c_sp, c_tot = (None, None) if usar_espn_en_vivo else st.session_state.active_custom_lines.get(game_idx, (None, None))

        away_lu_session = obtener_lineup_en_sesion(away_abbr)
        home_lu_session = obtener_lineup_en_sesion(home_abbr)

        detailed_res = run_monte_carlo_matchup(
            away_row_raw=away_row_raw,
            home_row_raw=home_row_raw,
            away_lineup=away_lu_session,
            home_lineup=home_lu_session,
            n_sims=n_sims,
            hfa_pts=hfa_pts,
            custom_spread_home=c_sp,
            custom_total_line=c_tot,
            seed=int(base_seed) + game_idx * 101,
        )

        render_detailed_matchup_dossier(detailed_res)


if __name__ == "__main__":
    main()