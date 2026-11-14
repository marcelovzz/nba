import base64
from datetime import date, datetime
import html
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

import engine_nba
from engine_nba import (
    FULL_30_TEAM_SLATE,
    GAME_SLATE_TIMES,
    build_highest_probability_sheet,
    build_nba_predictions_export_df,
    cargar_rosters_plantilla_excel,
    export_high_probability_excel_bytes,
    export_nba_excel_bytes,
    extract_executive_radar,
    generate_executive_quant_report,
    get_nba_logo_url,
    obtener_lineup_en_sesion,
    run_monte_carlo_matchup,
    sincronizar_df_nba_con_lineups,
)
import sync_espn
from sync_espn import (
    formatear_fecha_larga_es,
    load_clean_nba_dataframe,
    normalizar_abbr_nba,
    obtener_calendario_nba,
    obtener_lineas_mercado_nba,
)
import sync_injuries_nba
from sync_injuries_nba import (
    obtener_metadata_sincronizacion_lesiones,
    obtener_reporte_lesiones_nba,
)

RESEND_API_URL = "https://api.resend.com/emails"
DEFAULT_SENDER = "Terminal Sharp <onboarding@resend.dev>"
EV_HIGHLIGHT_THRESHOLD = 4.0
NEON_GREEN_HEX = "#00ffcc"
PDF_BRIEFING_FILENAME = "Terminal_Sharp_NBA_Briefing.pdf"


def _convertir_hora_a_cst(hora_raw: Optional[str], idx: int = 0) -> str:
    """
    Convierte una hora en formato 'HH:MM ET' (o cadena de ESPN) a horario CST ('HH:MM CST')
    para ordenar y mostrar cronológicamente las tarjetas móviles.
    """
    raw = str(hora_raw or "").strip()
    if not raw or raw.upper() == "TBD":
        raw = GAME_SLATE_TIMES[idx % len(GAME_SLATE_TIMES)]
    if "CST" in raw.upper():
        return raw
    if "ET" in raw.upper():
        clean_t = raw.upper().replace("ET", "").strip()
        parts = clean_t.split(":")
        if len(parts) == 2:
            try:
                hh = (int(parts[0]) - 1) % 24
                mm = int(parts[1][:2])
                return f"{hh:02d}:{mm:02d} CST"
            except ValueError:
                pass
    return f"{raw} CST"


def _extraer_abbr_desde_fila_anchor(hp_row: pd.Series) -> Tuple[str, str]:
    """
    Extrae `(away_abbr, home_abbr)` a partir de la columna `Partido` de `high_prob_df`
    (ej. 'Detroit Pistons (DET) @ Boston Celtics (BOS)').
    """
    partido_str = str(hp_row.get("Partido", ""))
    if "@" in partido_str:
        left_p, right_p = partido_str.split("@", 1)
        a_ab = left_p.split("(")[-1].replace(")", "").strip() if "(" in left_p else left_p.strip()[:3]
        h_ab = right_p.split("(")[-1].replace(")", "").strip() if "(" in right_p else right_p.strip()[:3]
        return normalizar_abbr_nba(a_ab), normalizar_abbr_nba(h_ab)
    return "BOS", "LAL"


def generar_pdf_briefing_weasyprint(html_content: str) -> Optional[bytes]:
    """
    Renderiza el archivo PDF adjunto ('Terminal_Sharp_NBA_Briefing.pdf') directamente
    desde la plantilla HTML/CSS con `weasyprint` (`weasyprint.HTML(string=html_content).write_pdf(...)`)
    para que sea una réplica visual exacta del correo (fondo oscuro #0d1117, tarjetas #161b22,
    acentos #00ffcc y escudos oficiales de la NBA), sin texto plano.
    Envuelto en `try ... except Exception as e:` para que cualquier fallo de red o renderizado
    no detenga jamás el envío del correo HTML.
    """
    try:
        import weasyprint

        pdf_bytes = weasyprint.HTML(string=html_content).write_pdf()
        return pdf_bytes
    except Exception as e:
        print(
            f"[WARN] No se pudo renderizar '{PDF_BRIEFING_FILENAME}' con WeasyPrint ({e}). "
            "Se continuará enviando el correo HTML y el Excel sin detener el flujo.",
            file=sys.stderr,
        )
        return None


def _extraer_mejor_oportunidad_partido(res: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evalúa los mercados de un partido (Spread, Total y Moneyline) y retorna la mejor
    oportunidad cuantitativa junto con su cuota decimal, EV% y bandera de resaltado (+EV >= 4.0%).
    """
    desg = res.get("desglose_5000_sims") or {}
    val_sp = res.get("valor_spread") or {}
    val_tot = res.get("valor_totales") or {}

    candidatos: List[Dict[str, Any]] = []

    # 1. Spread
    sp_ev = float(val_sp.get("ev_pct", desg.get("spread_ev_pct", 0.0)))
    sp_cuota = float(val_sp.get("cuota", desg.get("spread_cuota_decimal", 1.91)))
    sp_pick = str(val_sp.get("pick") or f"{desg.get('spread_abbr', res.get('home_abbr'))} {desg.get('spread_linea_str', '')}").strip()
    sp_prob = float(val_sp.get("prob", desg.get("spread_prob_cubre", 50.0)))
    candidatos.append(
        {
            "mercado": "SPREAD",
            "pick": sp_pick,
            "cuota": round(sp_cuota, 2),
            "ev_pct": round(sp_ev, 1),
            "prob_pct": round(sp_prob, 1),
        }
    )

    # 2. Total (Over / Under)
    tot_ev = float(val_tot.get("ev_pct", max(float(desg.get("ev_over_pct", 0.0)), float(desg.get("ev_under_pct", 0.0)))))
    tot_cuota = float(val_tot.get("cuota", res.get("cuota_over_decimal", 1.91)))
    tot_linea = float(val_tot.get("linea", res.get("total_line", 224.5)))
    if val_tot.get("valor"):
        tot_side = str(val_tot.get("pick", "OVER"))
    else:
        tot_side = "OVER" if float(desg.get("ev_over_pct", 0.0)) >= float(desg.get("ev_under_pct", 0.0)) else "UNDER"
    tot_prob = float(res.get("over_prob", 0.5) if tot_side == "OVER" else res.get("under_prob", 0.5)) * 100.0
    candidatos.append(
        {
            "mercado": "TOTAL",
            "pick": f"{tot_side} {tot_linea:.1f}",
            "cuota": round(tot_cuota, 2),
            "ev_pct": round(tot_ev, 1),
            "prob_pct": round(tot_prob, 1),
        }
    )

    # 3. Moneyline
    ml_ev = float(desg.get("ml_ev_pct", 0.0))
    ml_cuota = float(desg.get("ml_cuota_decimal", 1.91))
    ml_abbr = str(desg.get("ml_abbr", res.get("fav_abbr", res.get("home_abbr", "HOME"))))
    ml_prob = float(desg.get("ml_prob_modelo", max(float(res.get("home_win_prob", 0.5)), float(res.get("away_win_prob", 0.5))) * 100.0))
    candidatos.append(
        {
            "mercado": "MONEYLINE",
            "pick": f"{ml_abbr} ML",
            "cuota": round(ml_cuota, 2),
            "ev_pct": round(ml_ev, 1),
            "prob_pct": round(ml_prob, 1),
        }
    )

    mejor = max(candidatos, key=lambda x: x["ev_pct"])
    mejor["es_sharp_ev"] = bool(mejor["ev_pct"] >= EV_HIGHLIGHT_THRESHOLD)
    return mejor


def construir_html_reporte_nba(
    sim_results: List[Dict[str, Any]],
    export_df: pd.DataFrame,
    fecha_obj: date,
    bajas_por_equipo: Dict[str, List[Dict[str, Any]]],
    fuente_rosters: str,
    high_prob_df: Optional[pd.DataFrame] = None,
    exec_report: Optional[Any] = None,
    slate_meta: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Construye el cuerpo HTML oscuro institucional ('TERMINAL SHARP: NBA QUANT') con diseño
    mobile-first de tarjetas verticales (max-width: 600px, fondo #0d1117, tarjetas #161b22 con borde #30363d):
      1. Bloque superior 'TOP 5 ANCHORS DE LA JORNADA' / '🎯 TOP PICKS: MAYOR CERTEZA CUANTITATIVA (HIGH-CONFIDENCE ANCHORS)'
         con borde #00ffcc, escudos oficiales pequeños (18x18 px), porcentaje de cubrimiento y memorando ejecutivo.
      2. Tarjetas cronológicas (CST) por partido con escudos de visitante y local (26x26 px),
         marcador proyectado, líneas de mercado y badges de '% Cubre Spread' y '% Cubre Total' junto al '+EV'.
      3. Reglas CSS `@page` compatibles con WeasyPrint (`background-color: #0d1117; margin: 0; width: 620px;`,
         `page-break-inside: avoid;`) para renderizar `Terminal_Sharp_NBA_Briefing.pdf`.
    """
    fecha_larga = html.escape(formatear_fecha_larga_es(fecha_obj))
    fecha_iso = fecha_obj.strftime("%Y-%m-%d")
    radar = extract_executive_radar(sim_results)
    total_bajas = sum(len(v) for v in (bajas_por_equipo or {}).values())

    if high_prob_df is None or high_prob_df.empty:
        high_prob_df = build_highest_probability_sheet(sim_results, fecha_str=fecha_iso)
    if exec_report is None:
        exec_report = generate_executive_quant_report(sim_results, high_prob_df=high_prob_df, top_n=3)

    exec_report_html = (
        exec_report.html
        if hasattr(exec_report, "html") and exec_report.html
        else f'<pre style="white-space:pre-wrap; color:#cbd5e1; font-size:12px;">{html.escape(str(exec_report))}</pre>'
    )

    # 1. Bloque superior: TOP 5 ANCHORS DE LA JORNADA con escudos 18x18 px
    tarjetas_anchors_html: List[str] = []
    for idx_hp, (_, hp_row) in enumerate(high_prob_df.head(5).iterrows()):
        rank_hp = int(hp_row.get("Ranking", idx_hp + 1))
        sel_hp = html.escape(str(hp_row.get("Mercado / Selección", "N/A")))
        mkt_hp = html.escape(str(hp_row.get("Tipo de Mercado", "N/A")))
        part_hp = html.escape(str(hp_row.get("Partido", "N/A")))
        prob_mod_hp = float(hp_row.get("Probabilidad del Modelo (%)", 50.0))
        prob_novig_hp = float(hp_row.get("Probabilidad Implícita del Mercado sin Vigorish (%)", 50.0))
        edge_hp = float(hp_row.get("Edge Matemático (%)", 0.0))
        ev_hp = float(hp_row.get("EV (%)", 0.0))
        conf_hp = html.escape(str(hp_row.get("Nivel de Confianza / Varianza del Modelo", "Alta")))

        aw_ab_hp, hm_ab_hp = _extraer_abbr_desde_fila_anchor(hp_row)
        sel_upper = str(hp_row.get("Mercado / Selección", "")).upper()
        primary_abbr = aw_ab_hp if aw_ab_hp in sel_upper else hm_ab_hp
        logo_18_primary = get_nba_logo_url(primary_abbr)
        logo_18_away = get_nba_logo_url(aw_ab_hp)
        logo_18_home = get_nba_logo_url(hm_ab_hp)

        ev_color_hp = NEON_GREEN_HEX if (ev_hp >= EV_HIGHLIGHT_THRESHOLD or edge_hp >= 2.0) else "#38bdf8"
        tarjetas_anchors_html.append(
            f"""
            <div class="anchor-card" style="background-color:#0d1117; border:1px solid #30363d; border-left:3px solid {NEON_GREEN_HEX}; border-radius:8px; padding:10px 12px; margin-bottom:8px; page-break-inside:avoid; break-inside:avoid;">
              <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;">
                <div style="display:flex; align-items:center; gap:6px;">
                  <span style="color:{NEON_GREEN_HEX}; font-weight:800; font-family:Consolas,monospace; font-size:12px;">#{rank_hp}</span>
                  <img src="{logo_18_primary}" width="18" height="18" alt="{primary_abbr}" style="width:18px; height:18px; object-fit:contain; vertical-align:middle;">
                  <span style="color:#ffffff; font-weight:800; font-size:13px;">{sel_hp}</span>
                  <span style="color:#38bdf8; font-size:11px; font-family:Consolas,monospace;">[{mkt_hp}]</span>
                </div>
                <div style="font-family:Consolas,monospace; font-size:12px; font-weight:800; color:{NEON_GREEN_HEX};">
                  {prob_mod_hp:.1f}% Cubre / Prob &bull; <span style="color:{ev_color_hp};">{ev_hp:+.1f}% EV</span>
                </div>
              </div>
              <div style="margin-top:4px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; font-size:11px; color:#94a3b8;">
                <div>
                  <img src="{logo_18_away}" width="18" height="18" alt="{aw_ab_hp}" style="width:18px; height:18px; object-fit:contain; vertical-align:middle; margin-right:3px;">
                  <span>{part_hp}</span>
                  <img src="{logo_18_home}" width="18" height="18" alt="{hm_ab_hp}" style="width:18px; height:18px; object-fit:contain; vertical-align:middle; margin-left:3px;">
                </div>
                <div style="font-family:Consolas,monospace;">
                  No-Vig: {prob_novig_hp:.1f}% | Edge: {edge_hp:+.1f}% | {conf_hp}
                </div>
              </div>
            </div>
            """
        )

    # 2. Tarjetas cronológicas (CST) por partido con escudos 26x26 px y % Cubre Spread / % Cubre Total
    oportunidades_sharp = 0
    tarjetas_partidos_html: List[str] = []

    for idx, res in enumerate(sim_results):
        away_abbr_raw = str(res.get("away_abbr", "AWAY")).strip().upper()
        home_abbr_raw = str(res.get("home_abbr", "HOME")).strip().upper()
        away_abbr = html.escape(away_abbr_raw)
        home_abbr = html.escape(home_abbr_raw)
        away_team = html.escape(str(res.get("away_team", away_abbr_raw)))
        home_team = html.escape(str(res.get("home_team", home_abbr_raw)))

        logo_26_away = get_nba_logo_url(away_abbr_raw)
        logo_26_home = get_nba_logo_url(home_abbr_raw)

        meta = slate_meta[idx] if slate_meta and idx < len(slate_meta) and isinstance(slate_meta[idx], dict) else {}
        hora_cst = html.escape(_convertir_hora_a_cst(meta.get("hora") or res.get("hora"), idx))
        pace_proy = float(res.get("exp_possessions", res.get("proj_pace", 99.2)))

        exp_away = float(res.get("exp_away_pts", 0.0))
        exp_home = float(res.get("exp_home_pts", 0.0))
        exp_total = float(res.get("exp_total_pts", exp_away + exp_home))
        proj_spread_home = float(res.get("proj_spread_home", -(exp_home - exp_away)))

        sp_mkt_home = float(res.get("spread_line_home", 0.0))
        sp_mkt_away = float(res.get("spread_line_away", -sp_mkt_home))
        tot_mkt = float(res.get("total_line", 224.5))

        away_row = res.get("away_row", {})
        home_row = res.get("home_row", {})
        net_away = float(away_row.get("Rating_Final", away_row.get("Net_Rtg", 0.0))) if hasattr(away_row, "get") else 0.0
        net_home = float(home_row.get("Rating_Final", home_row.get("Net_Rtg", 0.0))) if hasattr(home_row, "get") else 0.0

        bajas_juego = res.get("bajas_nombres") or []
        if bajas_juego:
            bajas_badge_html = (
                f'<div style="margin-top:8px; padding:6px 10px; background-color:rgba(244,63,94,0.12); '
                f'border:1px solid rgba(244,63,94,0.35); border-radius:6px; font-size:11px; color:#fda4af;">'
                f'🚨 <strong>Bajas Detectadas:</strong> {html.escape(", ".join(bajas_juego))}</div>'
            )
        else:
            bajas_badge_html = (
                '<div style="margin-top:8px; font-size:11px; color:#64748b;">'
                '✅ Rotación titular completa (240.0 min activos)</div>'
            )

        # Porcentajes exactos de cubrimiento en las 5,000 simulaciones: Spread y Total
        desg = res.get("desglose_5000_sims") or {}
        val_sp = res.get("valor_spread") or {}
        val_tot = res.get("valor_totales") or {}

        home_cover_pct = round(float(res.get("home_cover_prob", 0.5)) * 100.0, 1)
        away_cover_pct = round(float(res.get("away_cover_prob", 0.5)) * 100.0, 1)
        c_sp_home = float(res.get("cuota_spread_home_decimal", 1.91))
        c_sp_away = float(res.get("cuota_spread_away_decimal", 1.91))

        if home_cover_pct >= away_cover_pct:
            sp_side_label = f"{home_abbr_raw} {sp_mkt_home:+.1f}"
            pct_cubre_spread = home_cover_pct
            cuota_sp_sel = c_sp_home
        else:
            sp_side_label = f"{away_abbr_raw} {sp_mkt_away:+.1f}"
            pct_cubre_spread = away_cover_pct
            cuota_sp_sel = c_sp_away

        ev_spread_sel = round(((pct_cubre_spread / 100.0) * cuota_sp_sel - 1.0) * 100.0, 1)
        if val_sp.get("valor") and val_sp.get("pick"):
            sp_side_label = str(val_sp.get("pick"))
            pct_cubre_spread = round(float(val_sp.get("prob", pct_cubre_spread)), 1)
            cuota_sp_sel = float(val_sp.get("cuota", cuota_sp_sel))
            ev_spread_sel = round(float(val_sp.get("ev_pct", ev_spread_sel)), 1)

        over_pct = round(float(res.get("over_prob", 0.5)) * 100.0, 1)
        under_pct = round(float(res.get("under_prob", 0.5)) * 100.0, 1)
        c_over = float(res.get("cuota_over_decimal", 1.91))
        c_under = float(res.get("cuota_under_decimal", 1.91))

        if over_pct >= under_pct:
            tot_side_label = f"OVER {tot_mkt:.1f}"
            pct_cubre_total = over_pct
            cuota_tot_sel = c_over
        else:
            tot_side_label = f"UNDER {tot_mkt:.1f}"
            pct_cubre_total = under_pct
            cuota_tot_sel = c_under

        ev_total_sel = round(((pct_cubre_total / 100.0) * cuota_tot_sel - 1.0) * 100.0, 1)
        if val_tot.get("valor") and val_tot.get("pick"):
            tot_side_label = f"{val_tot.get('pick')} {float(val_tot.get('linea', tot_mkt)):.1f}"
            pct_cubre_total = round(
                over_pct if str(val_tot.get("pick")).upper() == "OVER" else under_pct, 1
            )
            cuota_tot_sel = float(val_tot.get("cuota", cuota_tot_sel))
            ev_total_sel = round(float(val_tot.get("ev_pct", ev_total_sel)), 1)

        mejor_op = _extraer_mejor_oportunidad_partido(res)
        es_ev_4 = bool(
            mejor_op["es_sharp_ev"]
            or ev_spread_sel >= EV_HIGHLIGHT_THRESHOLD
            or ev_total_sel >= EV_HIGHLIGHT_THRESHOLD
        )
        if es_ev_4:
            oportunidades_sharp += 1

        sp_badge_border = NEON_GREEN_HEX if ev_spread_sel >= EV_HIGHLIGHT_THRESHOLD else "#30363d"
        sp_badge_bg = "rgba(0, 255, 204, 0.13)" if ev_spread_sel >= EV_HIGHLIGHT_THRESHOLD else "#0d1117"
        sp_badge_color = NEON_GREEN_HEX if ev_spread_sel >= EV_HIGHLIGHT_THRESHOLD else "#e2e8f0"

        tot_badge_border = NEON_GREEN_HEX if ev_total_sel >= EV_HIGHLIGHT_THRESHOLD else "#30363d"
        tot_badge_bg = "rgba(0, 255, 204, 0.13)" if ev_total_sel >= EV_HIGHLIGHT_THRESHOLD else "#0d1117"
        tot_badge_color = NEON_GREEN_HEX if ev_total_sel >= EV_HIGHLIGHT_THRESHOLD else "#e2e8f0"

        card_border_color = NEON_GREEN_HEX if es_ev_4 else "#30363d"

        tarjetas_partidos_html.append(
            f"""
            <div class="game-card" style="background-color:#161b22; border:1px solid {card_border_color}; border-radius:10px; padding:14px 16px; margin-bottom:14px; page-break-inside:avoid; break-inside:avoid;">
              <!-- Cabecera Cronológica CST -->
              <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #30363d; padding-bottom:8px; margin-bottom:10px; font-size:11px; color:#94a3b8; font-family:Consolas,monospace;">
                <span>🕒 <strong>{hora_cst}</strong> &bull; PACE PROY: {pace_proy:.1f}</span>
                <span>5,000 SIMS &bull; NET RTG (N=25): {away_abbr} {net_away:+.1f} | {home_abbr} {net_home:+.1f}</span>
              </div>

              <!-- Equipos Visitante y Local con Escudos Oficiales (26x26 px) y Marcador Proyectado -->
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                <div style="display:flex; align-items:center; gap:8px;">
                  <img src="{logo_26_away}" width="26" height="26" alt="{away_abbr}" style="width:26px; height:26px; object-fit:contain; vertical-align:middle;">
                  <div>
                    <div style="font-size:14px; font-weight:800; color:#ffffff;">{away_team} <span style="color:#38bdf8; font-size:12px;">({away_abbr})</span></div>
                    <div style="font-size:11px; color:#94a3b8;">Visita &bull; Mkt Spread: {away_abbr} {sp_mkt_away:+.1f}</div>
                  </div>
                </div>
                <div style="font-family:Consolas,monospace; font-size:18px; font-weight:800; color:#f8fafc;">
                  {exp_away:.1f}
                </div>
              </div>

              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                <div style="display:flex; align-items:center; gap:8px;">
                  <img src="{logo_26_home}" width="26" height="26" alt="{home_abbr}" style="width:26px; height:26px; object-fit:contain; vertical-align:middle;">
                  <div>
                    <div style="font-size:14px; font-weight:800; color:#ffffff;">{home_team} <span style="color:{NEON_GREEN_HEX}; font-size:12px;">({home_abbr})</span></div>
                    <div style="font-size:11px; color:#94a3b8;">Local &bull; Mkt Spread: {home_abbr} {sp_mkt_home:+.1f}</div>
                  </div>
                </div>
                <div style="font-family:Consolas,monospace; font-size:18px; font-weight:800; color:{NEON_GREEN_HEX};">
                  {exp_home:.1f}
                </div>
              </div>

              <!-- Resumen Línea Modelo vs Mercado -->
              <div style="padding:7px 10px; background-color:#0d1117; border:1px solid #30363d; border-radius:6px; font-family:Consolas,monospace; font-size:11px; color:#cbd5e1; margin-bottom:10px;">
                <span>📊 <strong>Total Proy:</strong> {exp_total:.1f} pts (Mkt O/U {tot_mkt:.1f})</span>
                &nbsp;|&nbsp;
                <span><strong>Spread Mod:</strong> {home_abbr} {proj_spread_home:+.1f} (Mkt {home_abbr} {sp_mkt_home:+.1f})</span>
              </div>

              <!-- Badges de Señales: % Cubre Spread y % Cubre Total + EV -->
              <div style="display:flex; flex-direction:column; gap:6px;">
                <div style="padding:8px 10px; background-color:{sp_badge_bg}; border:1px solid {sp_badge_border}; border-radius:6px; font-family:Consolas,monospace; font-size:12px; color:{sp_badge_color}; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap;">
                  <span>⚡ <strong>SPREAD:</strong> {html.escape(sp_side_label)} @ {cuota_sp_sel:.2f}</span>
                  <span><strong>% Cubre Spread: {pct_cubre_spread:.1f}%</strong> ({ev_spread_sel:+.1f}% EV)</span>
                </div>
                <div style="padding:8px 10px; background-color:{tot_badge_bg}; border:1px solid {tot_badge_border}; border-radius:6px; font-family:Consolas,monospace; font-size:12px; color:{tot_badge_color}; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap;">
                  <span>🔥 <strong>TOTAL:</strong> {html.escape(tot_side_label)} @ {cuota_tot_sel:.2f}</span>
                  <span><strong>% Cubre Total: {pct_cubre_total:.1f}%</strong> ({ev_total_sel:+.1f}% EV)</span>
                </div>
              </div>

              {bajas_badge_html}
            </div>
            """
        )

    # Top Player Props con +EV >= 4.0%
    props_destacados_html: List[str] = []
    for res in sim_results:
        for prop in res.get("props", []):
            ev_prop = float(prop.get("mejor_ev_pct", 0.0))
            if ev_prop >= EV_HIGHLIGHT_THRESHOLD:
                p_name = html.escape(str(prop.get("player_name", "")))
                t_ab = html.escape(str(prop.get("team_abbr", "")))
                op_ab = html.escape(str(prop.get("opp_abbr", "")))
                mkt_p = html.escape(str(prop.get("mejor_mercado", "PTS")))
                pick_p = html.escape(str(prop.get("mejor_pick", "OVER")))
                cuota_p = float(prop.get("mejor_cuota_decimal", 1.91))
                proy_p = float(prop.get("proj_pts", 0.0))
                linea_p = float(prop.get("prop_line", 0.0))
                props_destacados_html.append(
                    f'<li style="margin-bottom:6px; color:#e2e8f0; font-size:12px;">'
                    f'<strong>{p_name}</strong> ({t_ab} vs {op_ab}) &mdash; '
                    f'Proy: <code style="color:#f8fafc;">{proy_p:.1f}</code> (Línea {linea_p:.1f}) &rarr; '
                    f'<span style="color:{NEON_GREEN_HEX}; font-weight:800; font-family:Consolas,monospace;">'
                    f'{mkt_p} {pick_p} @ {cuota_p:.2f} ({ev_prop:+.1f}% EV)</span></li>'
                )

    bloque_props_html = (
        f'<ul style="margin:8px 0 0 0; padding-left:18px;">{"".join(props_destacados_html[:8])}</ul>'
        if props_destacados_html
        else '<p style="margin:6px 0 0 0; font-size:12px; color:#94a3b8;">Sin Player Props por encima del umbral +4.0% EV en esta cartelera.</p>'
    )

    lock_info = radar.get("lock") or {}
    sp_info = radar.get("spread") or {}
    tot_info = radar.get("total") or {}

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TERMINAL SHARP: NBA QUANT - Reporte Diario ({fecha_iso})</title>
<style>
  @page {{
    size: 620px 1120px;
    margin: 0;
    background-color: #0d1117;
  }}
  html, body {{
    margin: 0;
    padding: 0;
    background-color: #0d1117;
    color: #f8fafc;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }}
  .main-container {{
    max-width: 600px;
    width: 100%;
    margin: 0 auto;
    background-color: #0d1117;
    padding: 14px 10px 24px 10px;
    box-sizing: border-box;
  }}
  .game-card, .anchor-card, .section-card {{
    page-break-inside: avoid;
    break-inside: avoid;
  }}
</style>
</head>
<body style="margin:0; padding:0; background-color:#0d1117; color:#f8fafc;">
  <div class="main-container" style="max-width:600px; margin:0 auto; background-color:#0d1117; border:1px solid #30363d; border-radius:12px; overflow:hidden;">

    <!-- CABECERA INSTITUCIONAL -->
    <div style="padding:20px 18px; background-color:#161b22; border-bottom:2px solid {NEON_GREEN_HEX};">
      <div style="font-size:11px; letter-spacing:1.6px; text-transform:uppercase; color:{NEON_GREEN_HEX}; font-weight:800;">
        TERMINAL SHARP // NBA QUANTITATIVE SYNDICATE BRIEFING
      </div>
      <h1 style="margin:6px 0 6px 0; font-size:20px; color:#ffffff;">
        🏀 Cartelera Cuantitativa NBA &mdash; {fecha_larga}
      </h1>
      <div style="font-size:11px; color:#94a3b8;">
        5,000 Simulaciones Monte Carlo &bull; Regresión Bayesiana (N=25) &bull; Bajas ESPN (240.0 min) &bull; Feedback Loop (K=0.06)
      </div>
    </div>

    <!-- KPI STRIP -->
    <div style="padding:12px 18px; background-color:#0d1117; border-bottom:1px solid #30363d; font-size:11px; color:#cbd5e1; display:flex; flex-wrap:wrap; gap:12px;">
      <span>📅 <strong>Fecha:</strong> {fecha_iso}</span>
      <span>🏟️ <strong>Juegos:</strong> {len(sim_results)}</span>
      <span>🚨 <strong>Bajas ESPN:</strong> {total_bajas}</span>
      <span>⚡ <strong>Señales Sharp (+EV &ge; 4.0%):</strong> <strong style="color:{NEON_GREEN_HEX};">{oportunidades_sharp}</strong></span>
    </div>

    <!-- BLOQUE SUPERIOR: TOP 5 ANCHORS DE LA JORNADA / MAYOR CERTEZA CUANTITATIVA -->
    <div class="section-card" style="margin:14px 12px; padding:16px; background-color:#161b22; border:1px solid {NEON_GREEN_HEX}; border-radius:10px;">
      <div style="font-size:10px; letter-spacing:1.3px; text-transform:uppercase; color:{NEON_GREEN_HEX}; font-weight:800; margin-bottom:4px;">
        TOP 5 ANCHORS DE LA JORNADA // RANKING ESTRICTO DE MAYOR PROBABILIDAD
      </div>
      <h2 style="margin:0 0 12px 0; font-size:15px; color:#ffffff;">
        🎯 TOP PICKS: MAYOR CERTEZA CUANTITATIVA (HIGH-CONFIDENCE ANCHORS)
      </h2>
      {''.join(tarjetas_anchors_html)}

      <div style="margin-top:12px; padding-top:10px; border-top:1px solid #30363d;">
        <div style="font-size:11px; font-weight:800; color:#38bdf8; text-transform:uppercase; margin-bottom:8px;">
          📋 Memorando Ejecutivo de Predictor Cuantitativo (Top 3 Anclas)
        </div>
        {exec_report_html}
      </div>
    </div>

    <!-- RADAR EJECUTIVO RÁPIDO -->
    <div class="section-card" style="margin:12px 12px; padding:12px 16px; background-color:#161b22; border:1px solid #30363d; border-radius:10px; font-size:12px; color:#cbd5e1; line-height:1.6;">
      <div style="font-size:11px; font-weight:800; text-transform:uppercase; color:#38bdf8; margin-bottom:4px;">
        🎯 Radar Ejecutivo (5,000 Simulaciones)
      </div>
      <div>&bull; <strong>Moneyline Principal:</strong> {html.escape(str(lock_info.get('team', 'N/A')))} ({float(lock_info.get('prob', 0.0))*100:.1f}% prob. | Fair: {html.escape(str(lock_info.get('dec', '2.00')))})</div>
      <div>&bull; <strong>Spread Destacado:</strong> {html.escape(str(sp_info.get('pick', 'N/A')))} ({float(sp_info.get('prob', 0.0))*100:.1f}% Cubre Spread)</div>
      <div>&bull; <strong>Total Destacado:</strong> {html.escape(str(tot_info.get('pick', 'N/A')))} ({float(tot_info.get('prob', 0.0))*100:.1f}% Cubre Total)</div>
    </div>

    <!-- TARJETAS CRONOLÓGICAS (CST) POR PARTIDO -->
    <div style="padding:6px 12px 12px 12px;">
      <h2 style="margin:0 0 12px 0; font-size:14px; text-transform:uppercase; letter-spacing:0.8px; color:#f8fafc;">
        📊 Tarjetas Cronológicas por Partido (CST) &bull; % Cubre Spread &amp; Total
      </h2>
      {''.join(tarjetas_partidos_html)}
    </div>

    <!-- PLAYER PROPS CON +EV >= 4.0% -->
    <div class="section-card" style="margin:6px 12px 14px 12px; padding:14px 16px; background-color:#161b22; border:1px solid #30363d; border-radius:10px;">
      <h3 style="margin:0; font-size:13px; text-transform:uppercase; letter-spacing:0.8px; color:{NEON_GREEN_HEX};">
        🔥 Player Props Destacados (+EV &ge; 4.0%)
      </h3>
      {bloque_props_html}
    </div>

    <!-- PIE DE PÁGINA -->
    <div style="padding:14px 18px; background-color:#0d1117; border-top:1px solid #30363d; font-size:11px; color:#94a3b8; text-align:center;">
      Adjuntos: <code>nba_quant_predictions_{fecha_iso}.xlsx</code> &amp; <code>{PDF_BRIEFING_FILENAME}</code> &bull; Fuente Rosters: {html.escape(fuente_rosters)}
    </div>
  </div>
</body>
</html>"""


def generar_reporte_diario_nba(
    fecha_obj: Optional[date] = None,
    n_sims: int = 5000,
    hfa_pts: float = 2.5,
    umbral_ev_pts: float = 3.0,
    base_seed: int = 2026,
) -> Dict[str, Any]:
    """
    Ejecuta el flujo cuantitativo completo del día:
      1. Consulta el Injury Report oficial de ESPN ('Out' / 'Doubtful') y ajusta la rotación a 240.0 min.
      2. Carga los ratings de las 30 franquicias y aplica la estabilización bayesiana (N = 25).
      3. Consulta los partidos del día en ESPN y los momios decimales de mercado.
      4. Ejecuta las 5,000 simulaciones de Monte Carlo por partido.
      5. Genera el Excel en memoria con `export_nba_excel_bytes`, lo codifica en Base64 y arma el HTML oscuro.
    """
    target_date = fecha_obj or date.today()
    fecha_yyyymmdd = target_date.strftime("%Y%m%d")
    fecha_iso = target_date.strftime("%Y-%m-%d")

    # 1. Reporte de lesiones ESPN y ajuste de rotaciones en nba_rosters_plantilla.xlsx
    reporte_lesiones = obtener_reporte_lesiones_nba(force_refresh=True)
    lineups_dict, bajas_por_equipo, fuente_rosters = cargar_rosters_plantilla_excel(
        aplicar_lesiones=True,
        reporte_lesiones=reporte_lesiones,
    )

    # 2. Carga de tabla de equipos y sincronización con quintetos + regresión bayesiana (N=25)
    df_teams_raw, fuente_csv = load_clean_nba_dataframe()
    df_teams = sincronizar_df_nba_con_lineups(df_teams_raw, lineups_dict)

    # 3. Consulta de partidos del día y líneas de mercado
    odds_api_key = os.environ.get("ODDS_API_KEY", "").strip() or None
    calendario_dia = obtener_calendario_nba(fecha_str=fecha_yyyymmdd)
    lineas_mercado = obtener_lineas_mercado_nba(api_key=odds_api_key, fecha_yyyymmdd=fecha_yyyymmdd)

    matchups_validos: List[Tuple[str, str]] = []
    slate_meta: List[Dict[str, Any]] = []

    for item in calendario_dia:
        a_abbr = str(item.get("away_abbr", "")).upper()
        h_abbr = str(item.get("home_abbr", "")).upper()
        a_match = df_teams[df_teams["Team_Abbr"].astype(str).str.upper() == a_abbr]
        h_match = df_teams[df_teams["Team_Abbr"].astype(str).str.upper() == h_abbr]
        if not a_match.empty and not h_match.empty:
            matchups_validos.append((str(a_match.iloc[0]["Team"]), str(h_match.iloc[0]["Team"])))
            slate_meta.append(item)

    # Si no hay juegos en ESPN para la fecha actual, usar los primeros 6 cruces de respaldo
    if not matchups_validos:
        team_list = set(df_teams["Team"].tolist())
        for aw_name, hm_name in FULL_30_TEAM_SLATE[:6]:
            if aw_name in team_list and hm_name in team_list:
                matchups_validos.append((aw_name, hm_name))
        slate_meta = []

    # 4. Ejecutar las 5,000 simulaciones de Monte Carlo por partido
    sim_results: List[Dict[str, Any]] = []
    for idx_p, (aw_name, hm_name) in enumerate(matchups_validos):
        aw_row = df_teams[df_teams["Team"] == aw_name].iloc[0]
        hm_row = df_teams[df_teams["Team"] == hm_name].iloc[0]
        aw_abbr = str(aw_row["Team_Abbr"]).strip().upper()
        hm_abbr = str(hm_row["Team_Abbr"]).strip().upper()
        m_key = f"{aw_abbr}@{hm_abbr}"

        mkt_info = lineas_mercado.get(m_key)
        if mkt_info is None and slate_meta and idx_p < len(slate_meta):
            mkt_info = slate_meta[idx_p]

        res_mc = run_monte_carlo_matchup(
            away_row_raw=aw_row,
            home_row_raw=hm_row,
            away_lineup=obtener_lineup_en_sesion(aw_abbr, fallback_lineups=lineups_dict),
            home_lineup=obtener_lineup_en_sesion(hm_abbr, fallback_lineups=lineups_dict),
            n_sims=n_sims,
            hfa_pts=hfa_pts,
            market_odds_info=mkt_info,
            umbral_ev_pts=umbral_ev_pts,
            seed=int(base_seed) + idx_p * 101,
        )
        sim_results.append(res_mc)

    # 5. Generar DataFrame de exportación, vista Ranking_Alta_Probabilidad, informe ejecutivo y Excel en memoria
    export_df = build_nba_predictions_export_df(
        sim_results,
        slate_meta=slate_meta if slate_meta else None,
        fecha_str=fecha_iso,
    )
    high_prob_df = build_highest_probability_sheet(
        sim_results,
        slate_meta=slate_meta if slate_meta else None,
        fecha_str=fecha_iso,
    )
    exec_report = generate_executive_quant_report(
        sim_results,
        high_prob_df=high_prob_df,
        top_n=3,
    )

    excel_buffer = export_nba_excel_bytes(
        export_df,
        high_prob_df=high_prob_df,
        results_list=sim_results,
    )
    excel_bytes = excel_buffer.getvalue() if hasattr(excel_buffer, "getvalue") else bytes(excel_buffer)
    excel_base64 = base64.b64encode(excel_bytes).decode("utf-8")
    filename_xlsx = f"nba_quant_predictions_{fecha_iso}.xlsx"

    high_prob_buffer = export_high_probability_excel_bytes(high_prob_df)
    high_prob_excel_bytes = (
        high_prob_buffer.getvalue() if hasattr(high_prob_buffer, "getvalue") else bytes(high_prob_buffer)
    )
    high_prob_excel_base64 = base64.b64encode(high_prob_excel_bytes).decode("utf-8")
    high_prob_filename_xlsx = "nba_high_probability_picks.xlsx"

    html_body = construir_html_reporte_nba(
        sim_results=sim_results,
        export_df=export_df,
        fecha_obj=target_date,
        bajas_por_equipo=bajas_por_equipo,
        fuente_rosters=fuente_rosters,
        high_prob_df=high_prob_df,
        exec_report=exec_report,
        slate_meta=slate_meta if slate_meta else None,
    )

    # 6. Renderizado de PDF visual idéntico al HTML con WeasyPrint (protegido con try/except)
    pdf_bytes = generar_pdf_briefing_weasyprint(html_body)
    pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8") if pdf_bytes else None

    return {
        "fecha_iso": fecha_iso,
        "partidos_simulados": len(sim_results),
        "bajas_totales": sum(len(v) for v in bajas_por_equipo.values()),
        "filename": filename_xlsx,
        "excel_bytes": excel_bytes,
        "excel_base64": excel_base64,
        "high_prob_filename": high_prob_filename_xlsx,
        "high_prob_excel_bytes": high_prob_excel_bytes,
        "high_prob_excel_base64": high_prob_excel_base64,
        "pdf_filename": PDF_BRIEFING_FILENAME,
        "pdf_bytes": pdf_bytes,
        "pdf_base64": pdf_base64,
        "html": html_body,
        "export_df": export_df,
        "high_prob_df": high_prob_df,
        "executive_report": exec_report,
        "sim_results": sim_results,
    }


def enviar_reporte_resend_nba(
    resend_api_key: Optional[str] = None,
    to_email: Optional[str] = None,
    fecha_obj: Optional[date] = None,
    n_sims: int = 5000,
) -> Dict[str, Any]:
    """
    Genera el reporte cuantitativo diario NBA y lo envía por correo mediante un POST
    a `https://api.resend.com/emails` usando `requests` y las variables de entorno
    `RESEND_API_KEY` y `TO_EMAIL`, adjuntando el Excel y `Terminal_Sharp_NBA_Briefing.pdf`.
    """
    api_key = (resend_api_key or os.environ.get("RESEND_API_KEY", "")).strip()
    destinatario_raw = (to_email or os.environ.get("TO_EMAIL", "")).strip()

    if not api_key:
        raise ValueError("La variable de entorno 'RESEND_API_KEY' no está definida o está vacía.")
    if not destinatario_raw:
        raise ValueError("La variable de entorno 'TO_EMAIL' no está definida o está vacía.")

    destinatarios = [e.strip() for e in destinatario_raw.split(",") if e.strip()]
    reporte = generar_reporte_diario_nba(fecha_obj=fecha_obj, n_sims=n_sims)

    subject = (
        f"🏀 TERMINAL SHARP: NBA QUANT — Reporte Diario ({reporte['fecha_iso']}) "
        f"[{reporte['partidos_simulados']} Partidos | 5,000 Sims]"
    )

    attachments: List[Dict[str, str]] = [
        {
            "filename": reporte["filename"],
            "content": reporte["excel_base64"],
        }
    ]
    if reporte.get("pdf_base64"):
        attachments.append(
            {
                "filename": reporte.get("pdf_filename", PDF_BRIEFING_FILENAME),
                "content": reporte["pdf_base64"],
            }
        )

    payload = {
        "from": DEFAULT_SENDER,
        "to": destinatarios,
        "subject": subject,
        "html": reporte["html"],
        "attachments": attachments,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    response = requests.post(RESEND_API_URL, headers=headers, json=payload, timeout=30)
    if response.status_code not in (200, 201, 202):
        raise RuntimeError(
            f"Error al enviar correo vía Resend API (HTTP {response.status_code}): {response.text}"
        )

    resp_json = response.json()
    return {
        "status_code": response.status_code,
        "resend_id": resp_json.get("id"),
        "to": destinatarios,
        "subject": subject,
        "filename": reporte["filename"],
        "partidos_simulados": reporte["partidos_simulados"],
        "bajas_totales": reporte["bajas_totales"],
    }


def main() -> int:
    try:
        resultado = enviar_reporte_resend_nba()
        print(
            f"[OK] Reporte NBA enviado exitosamente vía Resend API | "
            f"ID: {resultado.get('resend_id')} | "
            f"Partidos: {resultado.get('partidos_simulados')} | "
            f"Bajas ESPN: {resultado.get('bajas_totales')} | "
            f"Adjunto: {resultado.get('filename')}"
        )
        return 0
    except Exception as exc:
        print(f"[ERROR] Falló el envío del reporte NBA vía Resend: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
