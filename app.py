import hashlib
import io
from typing import Any, Dict, List, Optional, Tuple
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
    obtener_lineas_mercado_nba,
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
    evaluar_valor_spread_nba,
    evaluar_valor_totales_nba,
    extract_executive_radar,
    generar_dataframe_plantilla_excel,
    obtener_lineup_en_sesion,
    parsear_excel_a_lineups,
    proyectar_props_jugador,
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
    """Renderiza el Radar Ejecutivo superior con todas las cuotas estrictamente en FORMATO DECIMAL."""
    st.markdown(
        f'<div class="section-banner"><div class="section-banner-title">📡 RADAR EJECUTIVO DE LA JORNADA // TOP SYNDICATE PICKS</div>'
        f'<div class="section-banner-tag">FORMATO DECIMAL &bull; {games_count} PARTIDO(S) &bull; {games_count * n_sims:,} SIMS</div></div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4 = st.columns(4)
    lock, sp, tot, pr = radar["lock"], radar["spread"], radar["total"], radar["prop"]

    with c1:
        st.markdown(
            f'<div class="radar-card lock-card"><div><div class="radar-tag">🔒 1. EL LOCK DE LA NOCHE</div>'
            f'<div class="radar-pick-main">{escudo_nba_html(lock["abbr"], 26)}{lock["team"]} ML</div>'
            f'<div class="radar-prob-big">{lock["prob"] * 100:.1f}% WIN</div></div>'
            f'<div class="radar-meta">Fair Odd Decimal: <strong>{lock["dec"]}</strong><br/>{lock["context"]} | Dif: {lock["proj_margin"]:+.1f} pts</div></div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f'<div class="radar-card spread-card"><div><div class="radar-tag">⚡ 2. EL REY DEL SPREAD</div>'
            f'<div class="radar-pick-main">{escudo_nba_html(sp["abbr"], 26)}{sp["pick"]}</div>'
            f'<div class="radar-prob-big" style="color: #38BDF8;">{sp["prob"] * 100:.1f}% COVER</div></div>'
            f'<div class="radar-meta">Fair Odd Decimal: <strong>{sp["dec"]}</strong><br/>{sp["context"]}</div></div>',
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f'<div class="radar-card total-card"><div><div class="radar-tag">🎯 3. LA FIJA DE PUNTOS</div>'
            f'<div class="radar-pick-main">{escudo_nba_html(tot["abbr"], 26)}{tot["pick"]}</div>'
            f'<div class="radar-prob-big" style="color: #F59E0B;">{tot["prob"] * 100:.1f}% HIT</div></div>'
            f'<div class="radar-meta">Fair Odd Decimal: <strong>{tot["dec"]}</strong><br/>{tot["context"]}</div></div>',
            unsafe_allow_html=True,
        )
    with c4:
        lean_word = "Over" if pr["lean_side"] == "OVER" else "Under"
        st.markdown(
            f'<div class="radar-card prop-card"><div><div class="radar-tag">🏀 4. PLAYER PROP LEAN</div>'
            f'<div class="radar-pick-main">{escudo_nba_html(pr["team_abbr"], 26)}{pr["player_name"]} {lean_word} {pr["prop_line"]:.1f}</div>'
            f'<div class="radar-prob-big" style="color: #A78BFA;">{pr["lean_prob"] * 100:.1f}% ({pr["lean_side"]})</div></div>'
            f'<div class="radar-meta">Proyección: <strong>{pr["proj_ppg"]:.1f} Pts</strong> | Fair Decimal: <strong>{pr["fair_dec"]}</strong><br/>{pr["matchup_note"]}</div></div>',
            unsafe_allow_html=True,
        )


def _construir_badge_totales_html(audit_tot: Dict[str, Any]) -> str:
    """
    Construye el badge visual de Totales en formato estrictamente DECIMAL:
      - Verde neón (#00ff88): [⚡ VALOR: OVER 226.5 @ 1.91 (+4.5 pts Edge | +7.8% EV)]
      - Magenta/Rojo (#ff3366): [⚡ VALOR: UNDER 232.0 @ 1.95 (+3.8 pts Edge | +5.9% EV)]
      - Gris (#555555): [TOTAL EFICIENTE]
    """
    if audit_tot.get("valor"):
        pick = audit_tot["pick"]
        linea = float(audit_tot["linea"])
        cuota = float(audit_tot["cuota"])
        edge_pts = float(audit_tot["edge_pts"])
        ev_pct = float(audit_tot["ev_pct"])
        color = str(audit_tot.get("badge_color", "#00ff88"))
        bg_rgba = "rgba(0, 255, 136, 0.14)" if pick == "OVER" else "rgba(255, 51, 102, 0.16)"
        text_label = f"[⚡ VALOR: {pick} {linea:.1f} @ {cuota:.2f} (+{edge_pts:.1f} pts Edge | {ev_pct:+.1f}% EV)]"
        return (
            f'<div class="ev-badge-pill" style="background:{bg_rgba}; border:1px solid {color}; color:{color};">'
            f"{text_label}</div>"
        )
    return (
        '<div class="ev-badge-pill" style="background:rgba(85,85,85,0.22); border:1px solid #555555; color:#94A3B8;">'
        "[TOTAL EFICIENTE]</div>"
    )


def _construir_badge_spread_html(audit_sp: Dict[str, Any]) -> str:
    """
    Construye el badge visual de Hándicap / Spread en formato estrictamente DECIMAL:
      - Cyan (#00e5ff): [⚡ VALOR SPREAD: NYK +6.5 @ 1.92 (+4.1 pts Edge | +8.3% EV)]
      - Gris (#555555): [SPREAD EFICIENTE]
    """
    if audit_sp.get("valor"):
        pick_label = str(audit_sp["pick"])
        cuota = float(audit_sp["cuota"])
        edge_pts = float(audit_sp["edge_pts"])
        ev_pct = float(audit_sp["ev_pct"])
        color = str(audit_sp.get("badge_color", "#00e5ff"))
        text_label = f"[⚡ VALOR SPREAD: {pick_label} @ {cuota:.2f} (+{edge_pts:.1f} pts Edge | {ev_pct:+.1f}% EV)]"
        return (
            f'<div class="ev-badge-pill" style="background:rgba(0, 229, 255, 0.14); border:1px solid {color}; color:{color};">'
            f"{text_label}</div>"
        )
    return (
        '<div class="ev-badge-pill" style="background:rgba(85,85,85,0.22); border:1px solid #555555; color:#94A3B8;">'
        "[SPREAD EFICIENTE]</div>"
    )


def _construir_badge_prop_html(eval_mkt: Dict[str, Any]) -> str:
    """
    Construye el badge visual de Player Prop (PTS, REB, AST) evaluado por Poisson (+EV >= 5%):
      - Verde neón (#00ff88): [⚡ VALOR: OVER X.X @ Cuota (+EV%)]
      - Magenta/Rojo (#ff3366): [⚡ VALOR: UNDER X.X @ Cuota (+EV%)]
      - Gris (#555555): [LÍNEA JUSTA]
    """
    badge_txt = str(eval_mkt.get("badge", "[LÍNEA JUSTA]"))
    if eval_mkt.get("valor"):
        pick = str(eval_mkt.get("pick", "OVER"))
        color = str(eval_mkt.get("badge_color", "#00ff88"))
        bg_rgba = "rgba(0, 255, 136, 0.14)" if pick == "OVER" else "rgba(255, 51, 102, 0.16)"
        return (
            f'<div class="ev-badge-pill" style="background:{bg_rgba}; border:1px solid {color}; color:{color};">'
            f"{badge_txt}</div>"
        )
    return (
        '<div class="ev-badge-pill" style="background:rgba(85,85,85,0.22); border:1px solid #555555; color:#94A3B8;">'
        "[LÍNEA JUSTA]</div>"
    )


def render_slate_grid_3x3(
    sim_results: List[Dict],
    slate_meta: Optional[List[Dict]] = None,
    umbral_ev_pts: float = 3.0,
) -> None:
    """
    VISTA A: CARTELERA EN CUADRÍCULA (Grid de 3 Columnas)
    Renderiza para cada partido un contenedor Cyber-Quant con:
      - Marcador proyectado por Monte Carlo y escudos oficiales de ESPN.
      - Comparativa de Totales: Sportsbook vs. Modelo con cuota decimal (ej. O/U 226.5 @ 1.91).
      - Badge visual de Totales (+EV Over en verde neón, +EV Under en magenta/rojo, o Gris [TOTAL EFICIENTE]).
      - Comparativa de Hándicap: Sportsbook vs. Modelo con cuota decimal (ej. BOS -6.5 @ 1.92).
      - Badge visual de Hándicap (+EV Spread en cyan o Gris [SPREAD EFICIENTE]).
      - Botón 'LEER ANÁLISIS →' con persistencia mediante st.session_state y st.rerun().
    """
    st.markdown(
        f'<div class="section-banner"><div class="section-banner-title">🗓️ CARTELERA NBA EN CUADRÍCULA // {len(sim_results)} JUEGO(S) AUDITADOS EN DECIMAL</div>'
        f'<div class="section-banner-tag">UMBRAL +EV: &ge;{umbral_ev_pts:.1f} PTS &bull; CUOTAS DECIMALES EN VIVO</div></div>',
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

            total_modelo = float(res["exp_total_pts"])
            total_mercado = float(res["total_line"])
            cuota_over_dec = float(res["cuota_over_decimal"])
            cuota_under_dec = float(res["cuota_under_decimal"])

            audit_totales = evaluar_valor_totales_nba(
                total_modelo=total_modelo,
                total_mercado=total_mercado,
                cuota_over=cuota_over_dec,
                cuota_under=cuota_under_dec,
                umbral_pts=umbral_ev_pts,
                prob_over_sim=float(res["over_prob"]),
                prob_under_sim=float(res["under_prob"]),
            )
            cuota_tot_display = cuota_over_dec if total_modelo >= total_mercado else cuota_under_dec
            badge_totales_html = _construir_badge_totales_html(audit_totales)

            spread_modelo_home = float(res["proj_spread_home"])
            spread_mercado_home = float(res["spread_line_home"])
            cuota_sp_home_dec = float(res["cuota_spread_home_decimal"])
            cuota_sp_away_dec = float(res["cuota_spread_away_decimal"])

            audit_spread = evaluar_valor_spread_nba(
                spread_modelo=spread_modelo_home,
                spread_mercado_home=spread_mercado_home,
                cuota_home=cuota_sp_home_dec,
                cuota_away=cuota_sp_away_dec,
                umbral_pts=umbral_ev_pts,
                home_abbr=home_abbr,
                away_abbr=away_abbr,
                prob_home_cover_sim=float(res["home_cover_prob"]),
                prob_away_cover_sim=float(res["away_cover_prob"]),
            )
            badge_spread_html = _construir_badge_spread_html(audit_spread)

            mkt_sp_str = f"{home_abbr} {spread_mercado_home:+.1f} @ {cuota_sp_home_dec:.2f}"
            mod_sp_str = (
                f"{home_abbr} {spread_modelo_home:+.1f}"
                if spread_modelo_home <= 0
                else f"{away_abbr} {-spread_modelo_home:+.1f}"
            )
            fav_win_pct = res["fav_base_win"] * 100.0
            fav_ml_dec = res["home_ml_dec"] if res["fav_abbr"] == home_abbr else res["away_ml_dec"]

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
                                <div>
                                    <span class="grid-team-abbr">{away_abbr}</span>
                                    <span class="grid-team-fullname">ORTG {away_row['Off_Rtg']:.1f} &middot; DRTG {away_row['Def_Rtg']:.1f}</span>
                                </div>
                            </div>
                            <div style="display:flex; align-items:center; gap:8px;">
                                {render_form_pills_html(away_abbr)}
                                <span class="grid-proj-pts">{res['exp_away_pts']:.1f}</span>
                            </div>
                        </div>
                        <div class="grid-team-row">
                            <div class="grid-team-info">
                                {escudo_nba_html(home_abbr, size=32)}
                                <div>
                                    <span class="grid-team-abbr">{home_abbr}</span>
                                    <span class="grid-team-fullname">ORTG {home_row['Off_Rtg']:.1f} &middot; DRTG {home_row['Def_Rtg']:.1f}</span>
                                </div>
                            </div>
                            <div style="display:flex; align-items:center; gap:8px;">
                                {render_form_pills_html(home_abbr)}
                                <span class="grid-proj-pts">{res['exp_home_pts']:.1f}</span>
                            </div>
                        </div>
                        <div class="audit-market-box">
                            <div class="audit-market-row">
                                <span class="audit-market-label">TOTALES (MKT vs MOD):</span>
                                <span class="audit-market-val">O/U {total_mercado:.1f} @ {cuota_tot_display:.2f} &nbsp;|&nbsp; Proy: {total_modelo:.1f}</span>
                            </div>
                            {badge_totales_html}
                            <div class="audit-market-row" style="margin-top:8px;">
                                <span class="audit-market-label">HÁNDICAP (MKT vs MOD):</span>
                                <span class="audit-market-val">{mkt_sp_str} &nbsp;|&nbsp; Proy: {mod_sp_str}</span>
                            </div>
                            {badge_spread_html}
                        </div>
                        <div class="grid-quick-forecast">
                            <span class="grid-forecast-lines">PROY MC: {away_abbr} {res['exp_away_pts']:.1f} - {res['exp_home_pts']:.1f} {home_abbr}</span>
                            <span class="grid-forecast-win">{res['fav_abbr']} {fav_win_pct:.1f}% (Fair {fav_ml_dec})</span>
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


def render_player_props_dossier_section(res: Dict) -> None:
    """
    SECCIÓN ACTUALIZADA DE PLAYER PROPS EN EL EXPEDIENTE DETALLADO (VISTA B):
    Para cada jugador estrella del cruce:
      - Muestra una tarjeta interactiva dividida en 3 columnas (PUNTOS, REBOTES, ASISTENCIAS):
        * PUNTOS: Proyección Modelo (λ_PTS) | Línea Sportsbook (con cuota decimal) | Badge +EV
        * REBOTES: Proyección Modelo (λ_REB) | Línea Sportsbook (con cuota decimal) | Badge +EV
        * ASISTENCIAS: Proyección Modelo (λ_AST) | Línea Sportsbook (con cuota decimal) | Badge +EV
      - Incluye campos editables para ingresar la línea del sportsbook (ej. Línea REB: 6.5, Cuota: 1.91)
        con recálculo instantáneo mediante `proyectar_props_jugador`.
    """
    st.markdown(
        '<div class="row-label-bar" style="border-left-color: #8B5CF6;">'
        '<span class="row-label-title">🏀 FILA 4 // AUDITORÍA MULTIMERCADO DE PLAYER PROPS (PTS &bull; REB &bull; AST — POISSON +EV DECIMAL)</span>'
        '<span class="row-label-sub">EDITA LÍNEAS Y CUOTAS DECIMALES DEL SPORTSBOOK EN VIVO (&ge;5.0% EV ACTIVA SEÑAL SHARP)</span>'
        "</div>",
        unsafe_allow_html=True,
    )

    pace_partido = float(res["exp_possessions"])

    for p_idx, prop in enumerate(res["props"]):
        p_name = str(prop["player_name"])
        t_abbr = str(prop["team_abbr"])
        opp_abbr = str(prop["opp_abbr"])
        style_tag = str(prop["style"])
        opp_def_rtg = float(prop.get("opp_def_rtg", 115.0))

        # Recuperar las métricas base y minutos actuales desde la sesión (por si el usuario editó minutos en la tabla de arriba)
        lu_team_df = obtener_lineup_en_sesion(t_abbr)
        player_match = lu_team_df[lu_team_df["Jugador"].astype(str).str.lower() == p_name.lower()]

        if not player_match.empty:
            p_row = player_match.iloc[0]
            minutos_proyectados = float(p_row.get("Minutos_Esperados", prop.get("minutos_proyectados", 34.0)))
            minutos_base = float(p_row.get("Minutos_Base", prop.get("minutos_base", 34.0)))
            ppg_base = float(p_row.get("PPG_Base", prop.get("ppg_base_raw", prop["base_ppg"])))
            rpg_base = float(p_row.get("RPG_Base", prop.get("rpg_base", 5.8)))
            apg_base = float(p_row.get("APG_Base", prop.get("apg_base", 4.9)))
        else:
            minutos_proyectados = float(prop.get("minutos_proyectados", 34.0))
            minutos_base = float(prop.get("minutos_base", 34.0))
            ppg_base = float(prop.get("ppg_base_raw", prop["base_ppg"]))
            rpg_base = float(prop.get("rpg_base", 5.8))
            apg_base = float(prop.get("apg_base", 4.9))

        default_pts_line = round_to_half_point(max(0.5, ppg_base - 0.5))
        default_reb_line = round_to_half_point(max(0.5, rpg_base - 0.5))
        default_ast_line = round_to_half_point(max(0.5, apg_base - 0.5))

        st.markdown(
            f"""
            <div class="prop-player-card">
                <div class="prop-player-header">
                    <div style="display:flex; align-items:center; gap:8px;">
                        {escudo_nba_html(t_abbr, 28)}
                        <div>
                            <div class="prop-player-name">{p_name.upper()} <span style="font-size:0.74rem; color:#00F5D4;">({t_abbr} vs {opp_abbr})</span></div>
                            <div style="font-family:'JetBrains Mono',monospace; font-size:0.71rem; color:#94A3B8;">
                                Base: <strong>{ppg_base:.1f} PPG</strong> &middot; <strong>{rpg_base:.1f} RPG</strong> &middot; <strong>{apg_base:.1f} APG</strong> &nbsp;|&nbsp;
                                Minutos: <strong style="color:#F8FAFC;">{minutos_proyectados:.1f} Proy</strong> / {minutos_base:.1f} Base
                            </div>
                        </div>
                    </div>
                    <div style="display:flex; gap:6px; flex-wrap:wrap;">
                        <span class="sb-chip">ESTILO: {style_tag}</span>
                        <span class="sb-chip">PACE PARTIDO: {pace_partido:.1f}</span>
                        <span class="sb-chip">DEF RIVAL ({opp_abbr}): {opp_def_rtg:.1f}</span>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_pts, col_reb, col_ast = st.columns(3)
        key_base = f"prop_{res['matchup_id']}_{p_idx}_{t_abbr}"

        with col_pts:
            in_c1, in_c2 = st.columns(2)
            with in_c1:
                linea_pts = st.number_input(
                    f"Línea PTS ({p_name})",
                    min_value=0.5,
                    max_value=65.5,
                    value=float(default_pts_line),
                    step=0.5,
                    format="%.1f",
                    key=f"{key_base}_pts_line",
                )
            with in_c2:
                cuota_pts = st.number_input(
                    f"Cuota PTS (Dec)",
                    min_value=1.05,
                    max_value=10.00,
                    value=1.91,
                    step=0.01,
                    format="%.2f",
                    key=f"{key_base}_pts_odd",
                )

        with col_reb:
            in_r1, in_r2 = st.columns(2)
            with in_r1:
                linea_reb = st.number_input(
                    f"Línea REB ({p_name})",
                    min_value=0.5,
                    max_value=30.5,
                    value=float(default_reb_line),
                    step=0.5,
                    format="%.1f",
                    key=f"{key_base}_reb_line",
                )
            with in_r2:
                cuota_reb = st.number_input(
                    f"Cuota REB (Dec)",
                    min_value=1.05,
                    max_value=10.00,
                    value=1.91,
                    step=0.01,
                    format="%.2f",
                    key=f"{key_base}_reb_odd",
                )

        with col_ast:
            in_a1, in_a2 = st.columns(2)
            with in_a1:
                linea_ast = st.number_input(
                    f"Línea AST ({p_name})",
                    min_value=0.5,
                    max_value=25.5,
                    value=float(default_ast_line),
                    step=0.5,
                    format="%.1f",
                    key=f"{key_base}_ast_line",
                )
            with in_a2:
                cuota_ast = st.number_input(
                    f"Cuota AST (Dec)",
                    min_value=1.05,
                    max_value=10.00,
                    value=1.91,
                    step=0.01,
                    format="%.2f",
                    key=f"{key_base}_ast_odd",
                )

        # Ejecutar motor cuantitativo de proyección y Poisson +EV con los inputs actuales
        jugador_payload = {
            "Jugador": p_name,
            "Team_Abbr": t_abbr,
            "PPG_Base": ppg_base,
            "RPG_Base": rpg_base,
            "APG_Base": apg_base,
            "Minutos_Base": minutos_base,
        }
        proy_multi = proyectar_props_jugador(
            jugador_dict=jugador_payload,
            minutos_proyectados=minutos_proyectados,
            pace_partido=pace_partido,
            pace_promedio_liga=99.5,
            def_rating_rival=opp_def_rtg,
            lineas_mercado={"PTS": linea_pts, "REB": linea_reb, "AST": linea_ast},
            cuotas_mercado={"PTS": cuota_pts, "REB": cuota_reb, "AST": cuota_ast},
        )

        for col_widget, mkt_code, mkt_title in [
            (col_pts, "PTS", "🎯 PUNTOS (PTS)"),
            (col_reb, "REB", "🛡️ REBOTES (REB)"),
            (col_ast, "AST", "⚡ ASISTENCIAS (AST)"),
        ]:
            m_data = proy_multi[mkt_code]
            badge_html = _construir_badge_prop_html(m_data)
            with col_widget:
                st.markdown(
                    f"""
                    <div class="prop-market-col-box">
                        <div class="prop-market-title">
                            <span>{mkt_title}</span>
                            <span class="prop-lambda-val">&lambda; = {m_data['proyeccion']:.1f}</span>
                        </div>
                        <div class="audit-market-row">
                            <span class="audit-market-label">Proyección Modelo:</span>
                            <span class="audit-market-val" style="color:#00F5D4;">{m_data['proyeccion']:.1f} {mkt_code}</span>
                        </div>
                        <div class="audit-market-row">
                            <span class="audit-market-label">Línea Sportsbook:</span>
                            <span class="audit-market-val">O/U {m_data['linea']:.1f} @ {m_data['cuota']:.2f}</span>
                        </div>
                        <div class="audit-market-row">
                            <span class="audit-market-label">Poisson Over / Under:</span>
                            <span class="audit-market-val">{m_data['prob_over']:.1f}% / {m_data['prob_under']:.1f}%</span>
                        </div>
                        <div class="audit-market-row" style="margin-bottom:6px;">
                            <span class="audit-market-label">Fair Odd (Over / Under):</span>
                            <span class="audit-market-val">{m_data['fair_odd_over']:.2f} / {m_data['fair_odd_under']:.2f}</span>
                        </div>
                        {badge_html}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def render_detailed_matchup_dossier(res: Dict) -> None:
    """
    VISTA B: EXPEDIENTE CUANTITATIVO DETALLADO (FORMATO ESTRICTAMENTE DECIMAL)
    Consume obligatoriamente `st.session_state.lineups_nba` tanto en las tablas de quintetos como en las 4 filas Monte Carlo.
    """
    away_abbr, home_abbr = res["away_abbr"], res["home_abbr"]
    away_row, home_row = res["away_row"], res["home_row"]
    away_div = away_row.get("Division", away_row.get("Conference", "NBA"))
    home_div = home_row.get("Division", home_row.get("Conference", "NBA"))

    away_c1, away_c2 = TEAM_COLORS.get(away_abbr, ("#1E293B", "#38BDF8"))
    home_c1, home_c2 = TEAM_COLORS.get(home_abbr, ("#1E293B", "#00F5D4"))

    proj_spread_str = f"{home_abbr} {res['proj_spread_home']:+.1f}" if res["proj_spread_home"] <= 0 else f"{away_abbr} {-res['proj_spread_home']:+.1f}"
    mkt_spread_str = f"{home_abbr} {res['spread_line_home']:+.1f} @ {res['cuota_spread_home_decimal']:.2f}"

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
                        <span class="sb-chip">MKT: {mkt_spread_str}</span>
                        <span class="sb-chip">TOTAL PROY: {res['exp_total_pts']:.1f} (MKT {res['total_line']:.1f} @ {res['cuota_over_decimal']:.2f})</span>
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
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f'<div class="row-label-bar"><span class="row-label-title">📊 FILA 1 // AUDITORÍA DE SIMULACIÓN MONTE CARLO ({res["n_sims"]:,} ITERACIONES)</span>'
        f'<span class="row-label-sub">WIN % &bull; SPREAD COVER % &bull; TOTAL OVER/UNDER &bull; CUOTAS DECIMALES</span></div>',
        unsafe_allow_html=True,
    )

    f1_c1, f1_c2, f1_c3 = st.columns(3)
    with f1_c1:
        st.markdown(
            f'<div class="quant-subcard"><div class="quant-subcard-header"><span>🏆 MONEYLINE (PROB. VICTORIA)</span><span style="color:#00F5D4;">FAIR ODDS DECIMALES</span></div>'
            f'<div class="sim-stat-line"><span class="sim-team-label">{escudo_nba_html(away_abbr, 20)}{away_abbr} (Visita)</span><span><span class="sim-prob-val">{res["away_win_prob"]*100:.1f}%</span><span class="sim-odds-badge">Fair {res["away_ml_dec"]}</span></span></div>'
            f'<div class="sim-stat-line"><span class="sim-team-label">{escudo_nba_html(home_abbr, 20)}{home_abbr} (Local)</span><span><span class="sim-prob-val">{res["home_win_prob"]*100:.1f}%</span><span class="sim-odds-badge">Fair {res["home_ml_dec"]}</span></span></div>'
            f'<div class="quant-bar-track"><div class="quant-bar-fill-left" style="width: {res["away_win_prob"]*100:.1f}%;"></div><div class="quant-bar-fill-right" style="width: {res["home_win_prob"]*100:.1f}%;"></div></div>'
            f'<div style="font-family:\'JetBrains Mono\',monospace; font-size:0.72rem; color:#94A3B8; margin-top:4px;">Diferencial Esperado: <strong style="color:#F8FAFC;">{home_abbr} {-res["proj_spread_home"]:+.1f} pts</strong></div></div>',
            unsafe_allow_html=True,
        )
    with f1_c2:
        st.markdown(
            f'<div class="quant-subcard"><div class="quant-subcard-header"><span>⚡ SPREAD / HÁNDICAP</span><span style="color:#38BDF8;">MKT: {home_abbr} {res["spread_line_home"]:+.1f}</span></div>'
            f'<div class="sim-stat-line"><span class="sim-team-label">{escudo_nba_html(away_abbr, 20)}{away_abbr} ({res["spread_line_away"]:+.1f})</span><span><span class="sim-prob-val" style="color:#38BDF8;">{res["away_cover_prob"]*100:.1f}%</span><span class="sim-odds-badge">Mkt {res["cuota_spread_away_decimal"]:.2f} | Fair {res["away_sp_dec"]}</span></span></div>'
            f'<div class="sim-stat-line"><span class="sim-team-label">{escudo_nba_html(home_abbr, 20)}{home_abbr} ({res["spread_line_home"]:+.1f})</span><span><span class="sim-prob-val" style="color:#38BDF8;">{res["home_cover_prob"]*100:.1f}%</span><span class="sim-odds-badge">Mkt {res["cuota_spread_home_decimal"]:.2f} | Fair {res["home_sp_dec"]}</span></span></div>'
            f'<div class="quant-bar-track"><div class="quant-bar-fill-left" style="width: {res["away_cover_prob"]*100:.1f}%;"></div><div class="quant-bar-fill-right" style="width: {res["home_cover_prob"]*100:.1f}%;"></div></div>'
            f'{_construir_badge_spread_html(res["valor_spread"])}</div>',
            unsafe_allow_html=True,
        )
    with f1_c3:
        st.markdown(
            f'<div class="quant-subcard"><div class="quant-subcard-header"><span>🎯 PUNTOS TOTALES (O/U)</span><span style="color:#F59E0B;">MKT: {res["total_line"]:.1f} PTS</span></div>'
            f'<div class="sim-stat-line"><span class="sim-team-label">OVER {res["total_line"]:.1f}</span><span><span class="sim-prob-val" style="color:#F59E0B;">{res["over_prob"]*100:.1f}%</span><span class="sim-odds-badge">Mkt {res["cuota_over_decimal"]:.2f} | Fair {res["over_dec"]}</span></span></div>'
            f'<div class="sim-stat-line"><span class="sim-team-label">UNDER {res["total_line"]:.1f}</span><span><span class="sim-prob-val" style="color:#F59E0B;">{res["under_prob"]*100:.1f}%</span><span class="sim-odds-badge">Mkt {res["cuota_under_decimal"]:.2f} | Fair {res["under_dec"]}</span></span></div>'
            f'<div class="quant-bar-track"><div class="quant-bar-fill-left" style="width: {res["over_prob"]*100:.1f}%;"></div><div class="quant-bar-fill-right" style="width: {res["under_prob"]*100:.1f}%;"></div></div>'
            f'{_construir_badge_totales_html(res["valor_totales"])}</div>',
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

    # Renderizar Fila 4: Player Props Multimercado (PTS, REB, AST) con inputs en vivo
    render_player_props_dossier_section(res)


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
    if "lineas_mercado_nba" not in st.session_state:
        st.session_state.lineas_mercado_nba = obtener_lineas_mercado_nba(api_key=None)
    if "last_odds_api_key" not in st.session_state:
        st.session_state.last_odds_api_key = ""
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
        '<div style="font-family:\'JetBrains Mono\',monospace; font-size:0.72rem; color:#94A3B8; margin-bottom:14px;">MODULAR QUANT ARCHITECTURE v12.0 (PTS/REB/AST +EV)</div>',
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

            if st.session_state.get("excel_procesado_sig") != excel_signature:
                try:
                    df_subido = pd.read_excel(io.BytesIO(raw_bytes))
                    lineups_actualizados = parsear_excel_a_lineups(df_subido, strict_240=False)

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

    if st.session_state.get("excel_cargado_ok") and st.session_state.get("df_excel_preview") is not None:
        st.sidebar.success("✅ Roster cargado desde Excel exitosamente")
        st.sidebar.caption("🔍 Vista previa en memoria (`st.session_state.lineups_nba`):")
        preview_cols = [
            c for c in ["Team_Abbr", "Pos", "Jugador", "Minutos", "PPG_Base", "RPG_Base", "APG_Base"]
            if c in st.session_state.df_excel_preview.columns
        ]
        st.sidebar.dataframe(
            st.session_state.df_excel_preview[preview_cols],
            use_container_width=True,
            hide_index=True,
            height=180,
        )

    # ==========================================================================
    # SERVIDOR DE MOMIOS EN VIVO (THE ODDS API + ESPN CONSENSUS FALLBACK DECIMAL)
    # ==========================================================================
    st.sidebar.markdown("### 💹 SERVIDOR DE MOMIOS (DECIMAL)")
    api_key = st.sidebar.text_input("Odds API Key (Opcional)", type="password")
    if api_key != st.session_state.get("last_odds_api_key", ""):
        st.session_state.last_odds_api_key = api_key
        st.session_state.lineas_mercado_nba = obtener_lineas_mercado_nba(api_key=api_key)

    with st.sidebar:
        if st.button("🔄 Sincronizar Momios y Calendario", use_container_width=True):
            with st.spinner("Auditando líneas en formato decimal (The Odds API / ESPN Scoreboard)..."):
                st.session_state.calendario_nba = obtener_calendario_nba_hoy()
                st.session_state.lineas_mercado_nba = obtener_lineas_mercado_nba(api_key=api_key)
                st.session_state.nba_partido_activo = None
                if st.session_state.calendario_nba:
                    st.session_state.modo_manual_respaldo = False
                    st.success(
                        f"Cartelera sincronizada: {len(st.session_state.calendario_nba)} partido(s) | "
                        f"{len(st.session_state.lineas_mercado_nba)} línea(s) en decimal."
                    )
                else:
                    st.info("Sin juegos programados hoy en ESPN. Operando con selector manual y consenso decimal.")

        if st.session_state.calendario_nba:
            st.checkbox(
                "🎛️ Usar Selector Manual de Respaldo",
                key="modo_manual_respaldo",
                help="Activa esta casilla si deseas simular cruces personalizados en lugar del calendario oficial de hoy.",
            )

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

        st.markdown("### ⚙️ PARÁMETROS DEL MOTOR")
        n_sims = st.select_slider("Iteraciones Monte Carlo / Partido", options=[1000, 2500, 5000, 10000, 20000], value=5000)
        hfa_pts = st.slider("Factor de Localía (HFA Puntos)", min_value=0.0, max_value=5.0, value=2.5, step=0.1)
        umbral_ev_pts = st.slider("Umbral Mínimo de Valor (+EV Pts)", min_value=1.0, max_value=6.0, value=3.0, step=0.5)
        base_seed = st.number_input("Semilla Cuantitativa (RNG Seed)", min_value=1, max_value=999999, value=2026, step=1)

        st.caption(f"🗓️ Partidos ESPN Hoy: {len(st.session_state.calendario_nba)}")
        st.caption(f"💹 Líneas Mercado Activas: {len(st.session_state.get('lineas_mercado_nba', {}))}")
        st.caption(f"📂 Fuente Ratings: {st.session_state.get('data_source_label', 'Respaldo Local')}")

    df_teams = st.session_state.df_nba
    team_list = df_teams["Team"].tolist()
    calendario_hoy = st.session_state.calendario_nba
    lineas_mercado_dict: Dict[str, Dict[str, Any]] = st.session_state.get("lineas_mercado_nba", {})

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
    odds_provider_badge = "THE ODDS API (DECIMAL)" if api_key else "ESPN CONSENSUS FALLBACK (DECIMAL)"

    st.markdown(
        f"""
        <div class="tv-master-header">
            <div class="tv-top-bar">
                <div class="syndicate-badge"><span class="pulse-dot"></span> SHARP SYNDICATE // {odds_provider_badge}</div>
                <div class="font-mono" style="font-size:0.76rem; color:#94A3B8;">
                    FORMATO CUOTAS: <strong style="color:#00F5D4;">DECIMAL ESTRICTO</strong> &nbsp;|&nbsp;
                    SIMULATIONS: <strong style="color:#F8FAFC;">{n_sims:,} / GAME</strong> &nbsp;|&nbsp;
                    PROPS POISSON: <strong style="color:#38BDF8;">PTS &bull; REB &bull; AST (&ge;5% +EV)</strong>
                </div>
            </div>
            <div class="tv-title">TERMINAL SHARP: NBA QUANT SCANNER</div>
            <div class="tv-subtitle">Auditoría de líneas de mercado (Totales, Hándicap y Player Props de Puntos, Rebotes y Asistencias) frente a simulaciones Monte Carlo y Poisson en formato decimal.</div>
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

        sim_results: List[Dict] = []
        for idx, (away_name, home_name) in enumerate(selected_matchups):
            away_row_raw = df_teams[df_teams["Team"] == away_name].iloc[0]
            home_row_raw = df_teams[df_teams["Team"] == home_name].iloc[0]
            away_abbr, home_abbr = str(away_row_raw["Team_Abbr"]), str(home_row_raw["Team_Abbr"])
            matchup_key = f"{away_abbr}@{home_abbr}"

            c_sp, c_tot = (None, None) if usar_espn_en_vivo else st.session_state.active_custom_lines.get(idx, (None, None))
            mkt_odds_info = lineas_mercado_dict.get(matchup_key)
            if mkt_odds_info is None and slate_meta and idx < len(slate_meta):
                mkt_odds_info = slate_meta[idx]

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
                market_odds_info=mkt_odds_info,
                umbral_ev_pts=umbral_ev_pts,
                seed=int(base_seed) + idx * 101,
            )
            sim_results.append(res)

        radar_picks = extract_executive_radar(sim_results)
        render_executive_radar(radar_picks, games_count=len(sim_results), n_sims=n_sims)
        render_slate_grid_3x3(sim_results, slate_meta=slate_meta, umbral_ev_pts=umbral_ev_pts)

    else:
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
        matchup_key = f"{away_abbr}@{home_abbr}"
        c_sp, c_tot = (None, None) if usar_espn_en_vivo else st.session_state.active_custom_lines.get(game_idx, (None, None))
        mkt_odds_info = lineas_mercado_dict.get(matchup_key)

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
            market_odds_info=mkt_odds_info,
            umbral_ev_pts=umbral_ev_pts,
            seed=int(base_seed) + game_idx * 101,
        )

        render_detailed_matchup_dossier(detailed_res)


if __name__ == "__main__":
    main()