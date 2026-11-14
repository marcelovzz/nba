from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

import engine_nba
from engine_nba import (
    AUDIT_LOG_COLS,
    DEFAULT_CSV_DATA,
    ELO_BAYES_K,
    PREDICTION_HISTORY_COLS,
    PREDICTION_HISTORY_CSV_FILENAME,
    TEAM_RATINGS_STATE_FILENAME,
    append_audit_log_to_master_excel,
    cargar_rosters_plantilla_excel,
    obtener_lineup_en_sesion,
    run_monte_carlo_matchup,
    sincronizar_df_nba_con_lineups,
)
from sync_espn import (
    ESPN_NBA_SCOREBOARD_URL,
    load_clean_nba_dataframe,
    normalizar_abbr_nba,
)

ESPN_SCOREBOARD_URL: str = ESPN_NBA_SCOREBOARD_URL
K_FACTOR: float = ELO_BAYES_K  # K = 0.06


def _Construir_Mapas_Equipos() -> Tuple[Dict[str, str], Dict[str, str]]:
    """Retorna diccionarios `(abbr_to_name, name_lower_to_abbr)` para las 30 franquicias NBA."""
    abbr_to_name: Dict[str, str] = {}
    name_to_abbr: Dict[str, str] = {}
    for row in DEFAULT_CSV_DATA:
        abbr = str(row["Team_Abbr"]).strip().upper()
        name = str(row["Team"]).strip()
        abbr_to_name[abbr] = name
        name_to_abbr[name.lower()] = abbr
        name_to_abbr[abbr.lower()] = abbr
    return abbr_to_name, name_to_abbr


def inicializar_estado_ratings_equipos(
    state_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Inicializa o carga `data/team_ratings_state.json` con los ratings estabilizados
    de las 30 franquicias NBA si el archivo aún no existe en el repositorio.
    """
    target_path = Path(state_path) if state_path is not None else Path(TEAM_RATINGS_STATE_FILENAME)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if target_path.exists():
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data:
                return data
        except Exception:
            pass

    lineups_dict, _, _ = cargar_rosters_plantilla_excel(aplicar_lesiones=False)
    df_raw, _ = load_clean_nba_dataframe()
    df_sync = sincronizar_df_nba_con_lineups(df_raw, lineups_dict)

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    teams_state: Dict[str, Any] = {}

    for _, row in df_sync.iterrows():
        abbr = str(row["Team_Abbr"]).strip().upper()
        team_name = str(row["Team"]).strip()
        r_final = round(float(row.get("Rating_Final", row["Off_Rtg"] - row["Def_Rtg"])), 2)
        o_rtg = round(float(row["Off_Rtg"]), 1)
        d_rtg = round(float(row["Def_Rtg"]), 1)
        r_base = round(float(row.get("Rating_Base", r_final)), 2)

        entry = {
            "team": team_name,
            "abbr": abbr,
            "rating": r_final,
            "net_rating": r_final,
            "baseline_rating": r_final,
            "rating_base_preseason": r_base,
            "off_rtg": o_rtg,
            "def_rtg": d_rtg,
            "elo_delta": 0.0,
            "last_delta": 0.0,
            "games_calibrated": 0,
            "updated_at": now_iso,
        }
        teams_state[abbr] = entry
        teams_state[team_name] = dict(entry)

    full_payload: Dict[str, Any] = {
        "meta": {
            "k_factor": K_FACTOR,
            "updated_at": now_iso,
            "description": "Estado autocalibrado de Net Ratings NBA (Feedback Loop Elo/Bayesiano K=0.06)",
        },
        "teams": teams_state,
    }
    # Incluir claves en nivel raíz para compatibilidad directa
    for k, v in teams_state.items():
        full_payload[k] = v

    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(full_payload, f, indent=2, ensure_ascii=False)

    return full_payload


def consultar_marcadores_finales_espn(fecha_yyyymmdd: str) -> List[Dict[str, Any]]:
    """
    Consulta los marcadores finales de los partidos concluidos en la fecha `YYYYMMDD`
    desde la API oficial de ESPN:
    `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMMDD`
    """
    fecha_clean = str(fecha_yyyymmdd).strip().replace("-", "")
    url = f"{ESPN_SCOREBOARD_URL}?dates={fecha_clean}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }

    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    payload = resp.json()

    abbr_to_name, _ = _Construir_Mapas_Equipos()
    eventos = payload.get("events", []) or []
    finalizados: List[Dict[str, Any]] = []

    for ev in eventos:
        try:
            espn_id = str(ev.get("id", "")).strip()
            competitions = ev.get("competitions", []) or []
            if not competitions:
                continue
            comp = competitions[0]
            status_obj = comp.get("status", ev.get("status", {})) or {}
            status_type = status_obj.get("type", {}) or {}
            status_name = str(status_type.get("name", "")).strip().upper()
            state_code = str(status_type.get("state", "")).strip().lower()
            completed_flag = bool(status_type.get("completed", False))

            es_final = (
                completed_flag
                or status_name == "STATUS_FINAL"
                or state_code == "post"
            )
            if not es_final:
                continue

            competitors = comp.get("competitors", []) or []
            if len(competitors) < 2:
                continue

            away_abbr_raw, home_abbr_raw = "", ""
            away_score, home_score = None, None
            away_name_espn, home_name_espn = "", ""

            for c in competitors:
                side = str(c.get("homeAway", "")).strip().lower()
                t_obj = c.get("team", {}) or {}
                ab = normalizar_abbr_nba(str(t_obj.get("abbreviation", "")))
                d_name = str(t_obj.get("displayName") or t_obj.get("name") or "").strip()
                sc_raw = c.get("score")
                sc_val = float(sc_raw) if sc_raw not in (None, "") else None

                if side == "away":
                    away_abbr_raw = ab
                    away_name_espn = d_name
                    away_score = sc_val
                elif side == "home":
                    home_abbr_raw = ab
                    home_name_espn = d_name
                    home_score = sc_val

            if not away_abbr_raw or not home_abbr_raw or away_score is None or home_score is None:
                continue
            if (away_score + home_score) <= 0:
                continue

            away_team_std = abbr_to_name.get(away_abbr_raw, away_name_espn or away_abbr_raw)
            home_team_std = abbr_to_name.get(home_abbr_raw, home_name_espn or home_abbr_raw)

            finalizados.append(
                {
                    "espn_game_id": espn_id or f"{fecha_clean}_{away_abbr_raw}_{home_abbr_raw}",
                    "date_yyyymmdd": fecha_clean,
                    "date_iso": f"{fecha_clean[:4]}-{fecha_clean[4:6]}-{fecha_clean[6:8]}",
                    "home_team": home_team_std,
                    "away_team": away_team_std,
                    "home_abbr": home_abbr_raw,
                    "away_abbr": away_abbr_raw,
                    "actual_home_score": round(float(home_score), 1),
                    "actual_away_score": round(float(away_score), 1),
                    "actual_margin": round(float(home_score - away_score), 2),
                    "actual_total": round(float(home_score + away_score), 2),
                }
            )
        except Exception:
            continue

    return finalizados


def actualizar_rating_elo_bayesiano(
    rating_previo: float,
    margen_real: float,
    margen_proyectado: float,
    k: float = K_FACTOR,
) -> Tuple[float, float]:
    """
    Aplica la fórmula de actualización tipo Elo/Bayesiana al Net Rating del equipo:
      `Rating_nuevo = Rating_previo + K * (Margen Real - Margen Proyectado)` con `K = 0.06`.
    Retorna `(rating_nuevo, delta_aplicado)`.
    """
    error_margen = float(margen_real) - float(margen_proyectado)
    delta = float(k) * error_margen
    rating_nuevo = float(np.clip(float(rating_previo) + delta, -16.0, 18.0))
    return round(rating_nuevo, 2), round(delta, 3)


def _obtener_rating_actual_equipo(
    state_data: Dict[str, Any],
    team_abbr: str,
    team_name: str,
    fallback_rating: float = 0.0,
) -> float:
    """Extrae el Net Rating actual de un equipo desde la estructura de `team_ratings_state.json`."""
    teams_pool = state_data.get("teams", state_data) if isinstance(state_data.get("teams"), dict) else state_data
    for key in (team_abbr, team_name):
        if key in teams_pool:
            val = teams_pool[key]
            if isinstance(val, (int, float)):
                return float(val)
            if isinstance(val, dict):
                return float(val.get("rating", val.get("net_rating", fallback_rating)))
    return float(fallback_rating)


def _guardar_rating_actualizado_equipo(
    state_data: Dict[str, Any],
    team_abbr: str,
    team_name: str,
    rating_nuevo: float,
    delta_aplicado: float,
    now_iso: str,
    total_error: float = 0.0,
) -> Dict[str, float]:
    """
    Actualiza el Net Rating, Off_Rtg y Def_Rtg de la franquicia en `state_data` (por abbr y nombre)
    y retorna un diccionario con `Off_Rtg_Prev`, `Off_Rtg_New`, `Delta_Off`, `Def_Rtg_Prev`, `Def_Rtg_New`, `Delta_Def`.
    """
    teams_pool = state_data.setdefault("teams", {})
    existing = teams_pool.get(team_abbr) or teams_pool.get(team_name) or state_data.get(team_abbr) or {}
    if not isinstance(existing, dict):
        existing = {"rating": float(existing) if isinstance(existing, (int, float)) else 0.0}

    prev_elo_delta = float(existing.get("elo_delta", 0.0))
    prev_games = int(existing.get("games_calibrated", 0))
    base_rtg = float(existing.get("baseline_rating", rating_nuevo - delta_aplicado))
    prev_rating = round(float(rating_nuevo - delta_aplicado), 2)
    prev_off = round(float(existing.get("off_rtg", 115.5 + (prev_rating / 2.0))), 2)
    prev_def = round(float(existing.get("def_rtg", prev_off - prev_rating)), 2)

    tot_adj = 0.015 * float(total_error)
    new_off = round(float(np.clip(prev_off + (delta_aplicado / 2.0) + tot_adj, 98.0, 132.0)), 2)
    new_def = round(float(np.clip(prev_def - (delta_aplicado / 2.0) + tot_adj, 98.0, 132.0)), 2)
    delta_off = round(new_off - prev_off, 2)
    delta_def = round(new_def - prev_def, 2)

    updated_entry = {
        "team": team_name,
        "abbr": team_abbr,
        "rating": round(float(rating_nuevo), 2),
        "net_rating": round(float(rating_nuevo), 2),
        "baseline_rating": round(base_rtg, 2),
        "rating_base_preseason": round(float(existing.get("rating_base_preseason", base_rtg)), 2),
        "off_rtg": round(new_off, 1),
        "def_rtg": round(new_def, 1),
        "elo_delta": round(prev_elo_delta + delta_aplicado, 3),
        "last_delta": round(delta_aplicado, 3),
        "games_calibrated": prev_games + 1,
        "updated_at": now_iso,
    }
    teams_pool[team_abbr] = updated_entry
    teams_pool[team_name] = dict(updated_entry)
    state_data[team_abbr] = updated_entry
    state_data[team_name] = dict(updated_entry)

    return {
        "Off_Rtg_Prev": prev_off,
        "Off_Rtg_New": new_off,
        "Delta_Off": delta_off,
        "Def_Rtg_Prev": prev_def,
        "Def_Rtg_New": new_def,
        "Delta_Def": delta_def,
    }


def ejecutar_autocalibracion_jornada(
    fecha_yyyymmdd: Optional[str] = None,
    history_path: Optional[Path] = None,
    state_path: Optional[Path] = None,
    k_factor: float = K_FACTOR,
    marcadores_override: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Flujo principal de autocalibración post-jornada ('Feedback Loop'):
      1. Consulta los marcadores finales de ayer desde la API de ESPN (`?dates=YYYYMMDD`).
      2. Lee `data/prediction_history.csv` y `data/team_ratings_state.json`.
      3. Si algún partido concluido ayer no estaba registrado como 'pending' en `prediction_history.csv`,
         genera su proyección base para poder evaluarlo sin pérdida de aprendizaje.
      4. Calcula el error de margen (`Margen Real - Margen Proyectado`) y total.
      5. Actualiza los ratings de cada equipo con `Rating_nuevo = Rating_previo + K * (Margen Real - Margen Proyectado)` (`K = 0.06`).
      6. Guarda `data/team_ratings_state.json` y marca los partidos como `status = 'evaluated'` en `data/prediction_history.csv`.
    """
    if fecha_yyyymmdd is None:
        ayer = date.today() - timedelta(days=1)
        fecha_yyyymmdd = ayer.strftime("%Y%m%d")
    fecha_clean = str(fecha_yyyymmdd).strip().replace("-", "")
    fecha_iso = f"{fecha_clean[:4]}-{fecha_clean[4:6]}-{fecha_clean[6:8]}"

    target_history = Path(history_path) if history_path is not None else Path(PREDICTION_HISTORY_CSV_FILENAME)
    target_state = Path(state_path) if state_path is not None else Path(TEAM_RATINGS_STATE_FILENAME)
    target_history.parent.mkdir(parents=True, exist_ok=True)
    target_state.parent.mkdir(parents=True, exist_ok=True)

    state_data = inicializar_estado_ratings_equipos(state_path=target_state)
    abbr_to_name, name_to_abbr = _Construir_Mapas_Equipos()

    if target_history.exists():
        try:
            df_hist = pd.read_csv(target_history)
            for col in PREDICTION_HISTORY_COLS:
                if col not in df_hist.columns:
                    df_hist[col] = np.nan
            df_hist = df_hist[PREDICTION_HISTORY_COLS].copy()
        except Exception:
            df_hist = pd.DataFrame(columns=PREDICTION_HISTORY_COLS)
    else:
        df_hist = pd.DataFrame(columns=PREDICTION_HISTORY_COLS)

    for str_col in ("game_id", "date", "home_team", "away_team", "home_abbr", "away_abbr", "status", "calibrated_at"):
        if str_col in df_hist.columns:
            df_hist[str_col] = df_hist[str_col].fillna("").astype(object)

    marcadores = (
        marcadores_override
        if marcadores_override is not None
        else consultar_marcadores_finales_espn(fecha_clean)
    )

    # Preparar motor para reconstruir proyecciones si algún partido de ayer no estaba en prediction_history.csv
    lineups_dict = None
    df_teams_sync = None

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    partidos_calibrados: List[Dict[str, Any]] = []
    nuevas_filas_audit_log: List[Dict[str, Any]] = []

    for game in marcadores:
        h_abbr = str(game.get("home_abbr") or name_to_abbr.get(str(game.get("home_team", "")).lower(), "")).upper()
        a_abbr = str(game.get("away_abbr") or name_to_abbr.get(str(game.get("away_team", "")).lower(), "")).upper()
        h_team = abbr_to_name.get(h_abbr, str(game.get("home_team", h_abbr)))
        a_team = abbr_to_name.get(a_abbr, str(game.get("away_team", a_abbr)))
        espn_gid = str(game.get("espn_game_id") or f"{fecha_clean}_{a_abbr}_{h_abbr}")

        real_h_score = float(game["actual_home_score"])
        real_a_score = float(game["actual_away_score"])
        real_margin_home = round(real_h_score - real_a_score, 2)
        real_total = round(real_h_score + real_a_score, 2)

        # Buscar fila correspondiente en df_hist
        match_idx = None
        if not df_hist.empty:
            mask_gid = df_hist["game_id"].astype(str) == espn_gid
            mask_teams_date = (
                (
                    (df_hist["home_abbr"].astype(str).str.upper() == h_abbr)
                    | (df_hist["home_team"].astype(str).str.lower() == h_team.lower())
                )
                & (
                    (df_hist["away_abbr"].astype(str).str.upper() == a_abbr)
                    | (df_hist["away_team"].astype(str).str.lower() == a_team.lower())
                )
                & (
                    df_hist["date"].astype(str).str.replace("-", "") == fecha_clean
                )
            )
            mask_pending_teams = (
                (df_hist["status"].astype(str).str.lower() == "pending")
                & (
                    (df_hist["home_abbr"].astype(str).str.upper() == h_abbr)
                    | (df_hist["home_team"].astype(str).str.lower() == h_team.lower())
                )
                & (
                    (df_hist["away_abbr"].astype(str).str.upper() == a_abbr)
                    | (df_hist["away_team"].astype(str).str.lower() == a_team.lower())
                )
            )
            combined = mask_gid | mask_teams_date | mask_pending_teams
            if combined.any():
                match_idx = df_hist[combined].index[0]

        if match_idx is not None:
            row_status = str(df_hist.loc[match_idx, "status"]).strip().lower()
            if row_status == "evaluated":
                # Ya fue calibrado previamente; evitar doble conteo
                continue
            proj_margin_home = float(df_hist.loc[match_idx, "projected_margin"])
            proj_total = float(df_hist.loc[match_idx, "projected_total"])
        else:
            # Si el juego no estaba en prediction_history.csv, generar su proyección pre-partido
            if lineups_dict is None or df_teams_sync is None:
                lineups_dict, _, _ = cargar_rosters_plantilla_excel(aplicar_lesiones=True)
                df_raw, _ = load_clean_nba_dataframe()
                df_teams_sync = sincronizar_df_nba_con_lineups(df_raw, lineups_dict)

            aw_match = df_teams_sync[df_teams_sync["Team_Abbr"].astype(str).str.upper() == a_abbr]
            hm_match = df_teams_sync[df_teams_sync["Team_Abbr"].astype(str).str.upper() == h_abbr]
            if aw_match.empty or hm_match.empty:
                continue

            sim_res = run_monte_carlo_matchup(
                away_row_raw=aw_match.iloc[0],
                home_row_raw=hm_match.iloc[0],
                away_lineup=obtener_lineup_en_sesion(a_abbr, fallback_lineups=lineups_dict),
                home_lineup=obtener_lineup_en_sesion(h_abbr, fallback_lineups=lineups_dict),
                n_sims=5000,
            )
            proj_margin_home = round(float(sim_res["exp_margin_home"]), 2)
            proj_total = round(float(sim_res["exp_total_pts"]), 2)
            new_row = {
                "game_id": espn_gid,
                "date": fecha_iso,
                "home_team": h_team,
                "away_team": a_team,
                "home_abbr": h_abbr,
                "away_abbr": a_abbr,
                "projected_home_pts": round(float(sim_res["exp_home_pts"]), 2),
                "projected_away_pts": round(float(sim_res["exp_away_pts"]), 2),
                "projected_margin": proj_margin_home,
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
            df_hist = pd.concat([df_hist, pd.DataFrame([new_row])], ignore_index=True)
            match_idx = len(df_hist) - 1

        # Calcular errores (Margen Real - Margen Proyectado) y (Total Real - Total Proyectado)
        margin_error_home = round(real_margin_home - proj_margin_home, 2)
        total_error = round(real_total - proj_total, 2)

        # Actualizar Net Rating de equipo local y visitante con K = 0.06
        prev_home_rtg = _obtener_rating_actual_equipo(state_data, h_abbr, h_team, fallback_rating=0.0)
        prev_away_rtg = _obtener_rating_actual_equipo(state_data, a_abbr, a_team, fallback_rating=0.0)

        new_home_rtg, delta_home = actualizar_rating_elo_bayesiano(
            rating_previo=prev_home_rtg,
            margen_real=real_margin_home,
            margen_proyectado=proj_margin_home,
            k=k_factor,
        )
        new_away_rtg, delta_away = actualizar_rating_elo_bayesiano(
            rating_previo=prev_away_rtg,
            margen_real=-real_margin_home,
            margen_proyectado=-proj_margin_home,
            k=k_factor,
        )

        rtg_metrics_home = _guardar_rating_actualizado_equipo(
            state_data, h_abbr, h_team, new_home_rtg, delta_home, now_iso, total_error=total_error
        )
        rtg_metrics_away = _guardar_rating_actualizado_equipo(
            state_data, a_abbr, a_team, new_away_rtg, delta_away, now_iso, total_error=total_error
        )

        matchup_str = f"{a_abbr} @ {h_abbr}"
        marcador_real_str = f"{int(round(real_a_score))}-{int(round(real_h_score))}"
        proy_spread_home = round(-proj_margin_home, 2)

        # Agregar filas para Audit_Log (Visita y Local)
        nuevas_filas_audit_log.append(
            {
                "Fecha": fecha_iso,
                "Partido": matchup_str,
                "Marcador_Real": marcador_real_str,
                "Proy_Spread": proy_spread_home,
                "Error_Spread": margin_error_home,
                "Proy_Total": round(proj_total, 2),
                "Error_Total": total_error,
                "Equipo": a_abbr,
                "Off_Rtg_Prev": rtg_metrics_away["Off_Rtg_Prev"],
                "Off_Rtg_New": rtg_metrics_away["Off_Rtg_New"],
                "Delta_Off": rtg_metrics_away["Delta_Off"],
                "Def_Rtg_Prev": rtg_metrics_away["Def_Rtg_Prev"],
                "Def_Rtg_New": rtg_metrics_away["Def_Rtg_New"],
                "Delta_Def": rtg_metrics_away["Delta_Def"],
            }
        )
        nuevas_filas_audit_log.append(
            {
                "Fecha": fecha_iso,
                "Partido": matchup_str,
                "Marcador_Real": marcador_real_str,
                "Proy_Spread": proy_spread_home,
                "Error_Spread": margin_error_home,
                "Proy_Total": round(proj_total, 2),
                "Error_Total": total_error,
                "Equipo": h_abbr,
                "Off_Rtg_Prev": rtg_metrics_home["Off_Rtg_Prev"],
                "Off_Rtg_New": rtg_metrics_home["Off_Rtg_New"],
                "Delta_Off": rtg_metrics_home["Delta_Off"],
                "Def_Rtg_Prev": rtg_metrics_home["Def_Rtg_Prev"],
                "Def_Rtg_New": rtg_metrics_home["Def_Rtg_New"],
                "Delta_Def": rtg_metrics_home["Delta_Def"],
            }
        )

        # Marcar partido como evaluado en prediction_history.csv
        df_hist.loc[match_idx, "home_abbr"] = h_abbr
        df_hist.loc[match_idx, "away_abbr"] = a_abbr
        df_hist.loc[match_idx, "actual_home_score"] = real_h_score
        df_hist.loc[match_idx, "actual_away_score"] = real_a_score
        df_hist.loc[match_idx, "actual_margin"] = real_margin_home
        df_hist.loc[match_idx, "actual_total"] = real_total
        df_hist.loc[match_idx, "margin_error"] = margin_error_home
        df_hist.loc[match_idx, "total_error"] = total_error
        df_hist.loc[match_idx, "status"] = "evaluated"
        df_hist.loc[match_idx, "calibrated_at"] = now_iso

        partidos_calibrados.append(
            {
                "game_id": str(df_hist.loc[match_idx, "game_id"]),
                "matchup": matchup_str,
                "projected_margin_home": proj_margin_home,
                "actual_margin_home": real_margin_home,
                "margin_error": margin_error_home,
                "total_error": total_error,
                "home_rating_prev": prev_home_rtg,
                "home_rating_new": new_home_rtg,
                "home_delta": delta_home,
                "away_rating_prev": prev_away_rtg,
                "away_rating_new": new_away_rtg,
                "away_delta": delta_away,
            }
        )

    if "meta" in state_data and isinstance(state_data["meta"], dict):
        state_data["meta"]["updated_at"] = now_iso
        state_data["meta"]["last_calibrated_date"] = fecha_iso

    with open(target_state, "w", encoding="utf-8") as f:
        json.dump(state_data, f, indent=2, ensure_ascii=False)

    df_hist.to_csv(target_history, index=False, encoding="utf-8")

    # Persistir registro diario en modo append en la pestaña 'Audit_Log' del Excel maestro (nba_rosters_plantilla.xlsx)
    audit_log_df = append_audit_log_to_master_excel(nuevas_filas_audit_log)

    return {
        "fecha_evaluada": fecha_iso,
        "partidos_finalizados_espn": len(marcadores),
        "partidos_calibrados": len(partidos_calibrados),
        "audit_log_rows_total": len(audit_log_df),
        "detalles": partidos_calibrados,
        "state_path": str(target_state),
        "history_path": str(target_history),
    }


def main() -> int:
    fecha_arg = sys.argv[1].strip() if len(sys.argv) > 1 and sys.argv[1].strip() else None
    try:
        res = ejecutar_autocalibracion_jornada(fecha_yyyymmdd=fecha_arg)
        print(
            f"[OK] Autocalibración NBA completada ({res['fecha_evaluada']}) | "
            f"Finalizados ESPN: {res['partidos_finalizados_espn']} | "
            f"Calibrados (K={K_FACTOR}): {res['partidos_calibrados']}"
        )
        for d in res["detalles"]:
            print(
                f"  -> {d['matchup']}: Proy {d['projected_margin_home']:+.1f} vs Real {d['actual_margin_home']:+.1f} "
                f"(Err {d['margin_error']:+.1f}) | Home {d['home_rating_prev']:+.2f} -> {d['home_rating_new']:+.2f} "
                f"({d['home_delta']:+.2f}) | Away {d['away_rating_prev']:+.2f} -> {d['away_rating_new']:+.2f} ({d['away_delta']:+.2f})"
            )
        return 0
    except Exception as exc:
        print(f"[ERROR] Falló la autocalibración NBA: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
