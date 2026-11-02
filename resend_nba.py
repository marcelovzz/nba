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
    build_nba_predictions_export_df,
    cargar_rosters_plantilla_excel,
    export_nba_excel_bytes,
    extract_executive_radar,
    obtener_lineup_en_sesion,
    run_monte_carlo_matchup,
    sincronizar_df_nba_con_lineups,
)
import sync_espn
from sync_espn import (
    formatear_fecha_larga_es,
    load_clean_nba_dataframe,
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
) -> str:
    """
    Construye el cuerpo HTML oscuro institucional ('TERMINAL SHARP: NBA QUANT') para el reporte diario.
    Resalta en verde neón (#00ffcc) todas las cuotas y selecciones con +EV >= 4.0%.
    """
    fecha_larga = html.escape(formatear_fecha_larga_es(fecha_obj))
    fecha_iso = fecha_obj.strftime("%Y-%m-%d")
    radar = extract_executive_radar(sim_results)
    total_bajas = sum(len(v) for v in (bajas_por_equipo or {}).values())

    # Contabilizar oportunidades con +EV >= 4.0%
    oportunidades_sharp = 0
    filas_partidos_html: List[str] = []

    for idx, res in enumerate(sim_results):
        away_abbr = html.escape(str(res.get("away_abbr", "AWAY")))
        home_abbr = html.escape(str(res.get("home_abbr", "HOME")))
        away_team = html.escape(str(res.get("away_team", away_abbr)))
        home_team = html.escape(str(res.get("home_team", home_abbr)))

        exp_away = float(res.get("exp_away_pts", 0.0))
        exp_home = float(res.get("exp_home_pts", 0.0))
        exp_total = float(res.get("exp_total_pts", exp_away + exp_home))
        proj_spread_home = float(res.get("proj_spread_home", -(exp_home - exp_away)))

        sp_mkt_home = float(res.get("spread_line_home", 0.0))
        tot_mkt = float(res.get("total_line", 224.5))

        away_row = res.get("away_row", {})
        home_row = res.get("home_row", {})
        net_away = float(away_row.get("Rating_Final", away_row.get("Net_Rtg", 0.0))) if hasattr(away_row, "get") else 0.0
        net_home = float(home_row.get("Rating_Final", home_row.get("Net_Rtg", 0.0))) if hasattr(home_row, "get") else 0.0

        bajas_juego = res.get("bajas_nombres") or []
        if bajas_juego:
            bajas_badge_html = (
                f'<div style="margin-top:4px; font-size:11px; color:#fda4af;">'
                f'🚨 Bajas Detectadas: {html.escape(", ".join(bajas_juego))}</div>'
            )
        else:
            bajas_badge_html = '<div style="margin-top:4px; font-size:11px; color:#64748b;">✅ Sin bajas titulares</div>'

        mejor_op = _extraer_mejor_oportunidad_partido(res)
        es_ev_4 = mejor_op["es_sharp_ev"]
        if es_ev_4:
            oportunidades_sharp += 1

        pick_label = html.escape(f"{mejor_op['mercado']}: {mejor_op['pick']}")
        cuota_str = f"{mejor_op['cuota']:.2f}"
        ev_str = f"{mejor_op['ev_pct']:+.1f}% EV"
        prob_str = f"{mejor_op['prob_pct']:.1f}%"

        if es_ev_4:
            cuota_cell_html = (
                f'<span style="display:inline-block; padding:4px 9px; border-radius:6px; '
                f'background-color:rgba(0, 255, 204, 0.14); border:1px solid {NEON_GREEN_HEX}; '
                f'color:{NEON_GREEN_HEX}; font-weight:800; font-family:Consolas,monospace;">'
                f'{pick_label} @ {cuota_str} ({ev_str})</span>'
            )
        else:
            cuota_cell_html = (
                f'<span style="color:#cbd5e1; font-family:Consolas,monospace; font-size:12px;">'
                f'{pick_label} @ {cuota_str} ({ev_str})</span>'
            )

        bg_row = "#111827" if idx % 2 == 0 else "#0d1322"
        filas_partidos_html.append(
            f"""
            <tr style="background-color:{bg_row}; border-bottom:1px solid #1e293b;">
                <td style="padding:12px 10px; color:#f8fafc; font-weight:700; font-size:13px;">
                    <div>{away_team} <span style="color:#38bdf8;">({away_abbr})</span> @ {home_team} <span style="color:#00ffcc;">({home_abbr})</span></div>
                    <div style="font-size:11px; color:#94a3b8; font-weight:400; margin-top:2px;">
                        Net Rtg Bayes (N=25): {away_abbr} {net_away:+.1f} | {home_abbr} {net_home:+.1f}
                    </div>
                    {bajas_badge_html}
                </td>
                <td style="padding:12px 10px; text-align:center; color:#e2e8f0; font-family:Consolas,monospace; font-size:13px;">
                    <strong>{exp_away:.1f}</strong> - <strong>{exp_home:.1f}</strong>
                    <div style="font-size:11px; color:#94a3b8;">Total: {exp_total:.1f}</div>
                </td>
                <td style="padding:12px 10px; text-align:center; color:#cbd5e1; font-family:Consolas,monospace; font-size:12px;">
                    <div>Mod: {home_abbr} {proj_spread_home:+.1f}</div>
                    <div style="color:#94a3b8;">Mkt: {home_abbr} {sp_mkt_home:+.1f} | O/U {tot_mkt:.1f}</div>
                </td>
                <td style="padding:12px 10px; text-align:center; color:#e2e8f0; font-family:Consolas,monospace; font-size:12px;">
                    {prob_str}
                </td>
                <td style="padding:12px 10px; text-align:right;">
                    {cuota_cell_html}
                </td>
            </tr>
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
<title>TERMINAL SHARP: NBA QUANT - Reporte Diario ({fecha_iso})</title>
</head>
<body style="margin:0; padding:24px; background-color:#070a12; color:#f8fafc; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <div style="max-width:920px; margin:0 auto; background-color:#0b0f19; border:1px solid #1e293b; border-radius:12px; overflow:hidden; box-shadow:0 12px 32px rgba(0,0,0,0.65);">
    
    <!-- CABECERA INSTITUCIONAL -->
    <div style="padding:24px 28px; background:linear-gradient(135deg, #0b132b 0%, #090d16 100%); border-bottom:2px solid {NEON_GREEN_HEX};">
      <div style="font-size:11px; letter-spacing:1.8px; text-transform:uppercase; color:{NEON_GREEN_HEX}; font-weight:800;">
        TERMINAL SHARP // NBA QUANTITATIVE SYNDICATE REPORT
      </div>
      <h1 style="margin:8px 0 6px 0; font-size:22px; color:#ffffff;">
        🏀 Cartelera Cuantitativa NBA &mdash; {fecha_larga}
      </h1>
      <div style="font-size:12px; color:#94a3b8;">
        Simulación Monte Carlo (5,000 iteraciones/partido) &bull; Estabilización Bayesiana (N=25) &bull; Reasignación Automática ESPN Injuries (240.0 min)
      </div>
    </div>

    <!-- KPI STRIP -->
    <div style="padding:16px 28px; background-color:#0f172a; border-bottom:1px solid #1e293b; font-size:12px; color:#cbd5e1;">
      <span style="margin-right:18px;">📅 <strong>Fecha:</strong> {fecha_iso}</span>
      <span style="margin-right:18px;">🏟️ <strong>Partidos Auditados:</strong> {len(sim_results)}</span>
      <span style="margin-right:18px;">🚨 <strong>Bajas Descontadas (ESPN):</strong> {total_bajas}</span>
      <span>⚡ <strong>Señales Sharp (+EV &ge; 4.0%):</strong> <strong style="color:{NEON_GREEN_HEX};">{oportunidades_sharp}</strong></span>
    </div>

    <!-- RADAR EJECUTIVO -->
    <div style="padding:20px 28px; border-bottom:1px solid #1e293b;">
      <h2 style="margin:0 0 10px 0; font-size:14px; text-transform:uppercase; letter-spacing:1px; color:#38bdf8;">
        🎯 Radar Ejecutivo (5,000 Simulaciones)
      </h2>
      <div style="font-size:12px; color:#cbd5e1; line-height:1.7;">
        <div>&bull; <strong>Moneyline Principal:</strong> {html.escape(str(lock_info.get('team', 'N/A')))} ({float(lock_info.get('prob', 0.0))*100:.1f}% prob. | Fair Decimal: {html.escape(str(lock_info.get('dec', '2.00')))})</div>
        <div>&bull; <strong>Spread Destacado:</strong> {html.escape(str(sp_info.get('pick', 'N/A')))} ({float(sp_info.get('prob', 0.0))*100:.1f}% cubre)</div>
        <div>&bull; <strong>Total Destacado:</strong> {html.escape(str(tot_info.get('pick', 'N/A')))} ({float(tot_info.get('prob', 0.0))*100:.1f}% prob.)</div>
      </div>
    </div>

    <!-- TABLA DE PROYECCIONES Y CUOTAS CON +EV >= 4.0% EN #00ffcc -->
    <div style="padding:20px 28px;">
      <h2 style="margin:0 0 12px 0; font-size:14px; text-transform:uppercase; letter-spacing:1px; color:#f8fafc;">
        📊 Proyecciones por Partido (Cuotas con +EV &ge; 4.0% resaltadas en <span style="color:{NEON_GREEN_HEX};">Verde Neón {NEON_GREEN_HEX}</span>)
      </h2>
      <table style="width:100%; border-collapse:collapse; background-color:#0b0f19; border:1px solid #1e293b;">
        <thead>
          <tr style="background-color:#050811; border-bottom:2px solid #1e293b; color:{NEON_GREEN_HEX}; font-size:11px; text-transform:uppercase;">
            <th style="padding:10px; text-align:left;">Partido / Rotación &amp; Bajas</th>
            <th style="padding:10px; text-align:center;">Marcador Proy.</th>
            <th style="padding:10px; text-align:center;">Spread / Total</th>
            <th style="padding:10px; text-align:center;">Prob. Modelo</th>
            <th style="padding:10px; text-align:right;">Mejor Cuota Decimal (+EV)</th>
          </tr>
        </thead>
        <tbody>
          {''.join(filas_partidos_html)}
        </tbody>
      </table>
    </div>

    <!-- PLAYER PROPS CON +EV >= 4.0% -->
    <div style="padding:16px 28px 22px 28px; border-top:1px solid #1e293b; background-color:#090d16;">
      <h3 style="margin:0; font-size:13px; text-transform:uppercase; letter-spacing:0.8px; color:{NEON_GREEN_HEX};">
        🔥 Player Props Destacados (+EV &ge; 4.0%)
      </h3>
      {bloque_props_html}
    </div>

    <!-- PIE DE PÁGINA -->
    <div style="padding:14px 28px; background-color:#050811; border-top:1px solid #1e293b; font-size:11px; color:#64748b; text-align:center;">
      Archivo Excel adjunto: <code>nba_quant_predictions_{fecha_iso}.xlsx</code> &bull; Fuente Rosters: {html.escape(fuente_rosters)} &bull; Generado automáticamente por TERMINAL SHARP: NBA QUANT
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

    # 5. Generar DataFrame de exportación, buffer Excel en memoria y codificación Base64
    export_df = build_nba_predictions_export_df(
        sim_results,
        slate_meta=slate_meta if slate_meta else None,
        fecha_str=fecha_iso,
    )
    excel_buffer = export_nba_excel_bytes(export_df)
    excel_bytes = excel_buffer.getvalue() if hasattr(excel_buffer, "getvalue") else bytes(excel_buffer)
    excel_base64 = base64.b64encode(excel_bytes).decode("utf-8")
    filename_xlsx = f"nba_quant_predictions_{fecha_iso}.xlsx"

    html_body = construir_html_reporte_nba(
        sim_results=sim_results,
        export_df=export_df,
        fecha_obj=target_date,
        bajas_por_equipo=bajas_por_equipo,
        fuente_rosters=fuente_rosters,
    )

    return {
        "fecha_iso": fecha_iso,
        "partidos_simulados": len(sim_results),
        "bajas_totales": sum(len(v) for v in bajas_por_equipo.values()),
        "filename": filename_xlsx,
        "excel_bytes": excel_bytes,
        "excel_base64": excel_base64,
        "html": html_body,
        "export_df": export_df,
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
    `RESEND_API_KEY` y `TO_EMAIL`.
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

    payload = {
        "from": DEFAULT_SENDER,
        "to": destinatarios,
        "subject": subject,
        "html": reporte["html"],
        "attachments": [
            {
                "filename": reporte["filename"],
                "content": reporte["excel_base64"],
            }
        ],
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
