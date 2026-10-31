from datetime import datetime, timezone
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import unicodedata
import urllib.request

from bs4 import BeautifulSoup

try:
    import requests
except ImportError:
    requests = None

# ==============================================================================
# ENDPOINTS OFICIALES DEL INJURY REPORT DE ESPN NBA
# ==============================================================================
ESPN_NBA_INJURIES_URL = "https://www.espn.com/nba/injuries"
ESPN_NBA_INJURIES_API_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
)

INJURIES_HTTP_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "application/json,text/plain,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

NBA_30_TEAMS_SET = {
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}

ESPN_TEAM_TO_NBA_ABBR: Dict[str, str] = {
    # Abreviaturas ESPN / variantes históricas
    "ATL": "ATL",
    "BOS": "BOS",
    "BKN": "BKN",
    "BRK": "BKN",
    "CHA": "CHA",
    "CHO": "CHA",
    "CHI": "CHI",
    "CLE": "CLE",
    "DAL": "DAL",
    "DEN": "DEN",
    "DET": "DET",
    "GS": "GSW",
    "GSW": "GSW",
    "HOU": "HOU",
    "IND": "IND",
    "LAC": "LAC",
    "LAL": "LAL",
    "MEM": "MEM",
    "MIA": "MIA",
    "MIL": "MIL",
    "MIN": "MIN",
    "NO": "NOP",
    "NOP": "NOP",
    "NOH": "NOP",
    "NY": "NYK",
    "NYK": "NYK",
    "OKC": "OKC",
    "ORL": "ORL",
    "PHI": "PHI",
    "PHX": "PHX",
    "PHO": "PHX",
    "POR": "POR",
    "SAC": "SAC",
    "SA": "SAS",
    "SAS": "SAS",
    "TOR": "TOR",
    "UTA": "UTA",
    "UTAH": "UTA",
    "WAS": "WAS",
    "WSH": "WAS",
    # Nombres oficiales de las 30 franquicias NBA en ESPN
    "ATLANTA HAWKS": "ATL",
    "BOSTON CELTICS": "BOS",
    "BROOKLYN NETS": "BKN",
    "CHARLOTTE HORNETS": "CHA",
    "CHICAGO BULLS": "CHI",
    "CLEVELAND CAVALIERS": "CLE",
    "DALLAS MAVERICKS": "DAL",
    "DENVER NUGGETS": "DEN",
    "DETROIT PISTONS": "DET",
    "GOLDEN STATE WARRIORS": "GSW",
    "HOUSTON ROCKETS": "HOU",
    "INDIANA PACERS": "IND",
    "LA CLIPPERS": "LAC",
    "LOS ANGELES CLIPPERS": "LAC",
    "L.A. CLIPPERS": "LAC",
    "LOS ANGELES LAKERS": "LAL",
    "LA LAKERS": "LAL",
    "L.A. LAKERS": "LAL",
    "MEMPHIS GRIZZLIES": "MEM",
    "MIAMI HEAT": "MIA",
    "MILWAUKEE BUCKS": "MIL",
    "MINNESOTA TIMBERWOLVES": "MIN",
    "NEW ORLEANS PELICANS": "NOP",
    "NEW YORK KNICKS": "NYK",
    "OKLAHOMA CITY THUNDER": "OKC",
    "ORLANDO MAGIC": "ORL",
    "PHILADELPHIA 76ERS": "PHI",
    "PHOENIX SUNS": "PHX",
    "PORTLAND TRAIL BLAZERS": "POR",
    "SACRAMENTO KINGS": "SAC",
    "SAN ANTONIO SPURS": "SAS",
    "TORONTO RAPTORS": "TOR",
    "UTAH JAZZ": "UTA",
    "WASHINGTON WIZARDS": "WAS",
}

PLAYER_NAME_ALIASES: Dict[str, str] = {
    "nicolas claxton": "nic claxton",
    "cameron thomas": "cam thomas",
    "herb jones": "herbert jones",
    "lu dort": "luguentz dort",
    "alexandre sarr": "alex sarr",
    "bub carrington": "carlton carrington",
    "santiago aldama": "santi aldama",
    "mohamed bamba": "mo bamba",
    "moritz wagner": "mo wagner",
    "sviatoslav mykhailiuk": "svi mykhailiuk",
    "guillermo hernangomez": "willy hernangomez",
}

# Caché ligero en memoria con TTL de 20 minutos para evitar peticiones redundantes en reruns
_INJURIES_CACHE: Dict[str, Any] = {
    "timestamp_epoch": 0.0,
    "data": None,
    "meta": {
        "fuente": "Sin sincronizar",
        "ultima_actualizacion": "",
        "total_bajas": 0,
        "equipos_con_bajas": 0,
    },
}
_INJURIES_CACHE_TTL_SEC = 1200.0


def normalizar_equipo_nba(team_identifier: str) -> str:
    """
    Convierte el nombre completo o abreviatura de ESPN ('Golden State Warriors', 'GS', 'UTAH', 'WSH')
    al código estándar de 3 letras del motor NBA ('GSW', 'UTA', 'WAS', etc.).
    """
    raw = str(team_identifier or "").strip().upper()
    if not raw:
        return ""
    if raw in ESPN_TEAM_TO_NBA_ABBR:
        return ESPN_TEAM_TO_NBA_ABBR[raw]
    for full_name, abbr in ESPN_TEAM_TO_NBA_ABBR.items():
        if len(full_name) > 3 and full_name in raw:
            return abbr
    return raw if raw in NBA_30_TEAMS_SET else ""


def normalizar_nombre_jugador_nba(nombre: str) -> str:
    """
    Normaliza el nombre de un jugador NBA para cruce exacto y tolerante entre ESPN y Excel:
      - Elimina acentos y caracteres diacríticos ('Nikola Jokić' -> 'nikola jokic', 'Dëmin' -> 'demin').
      - Unifica iniciales y apóstrofes ('P.J. Washington' -> 'pj washington', 'De\\'Aaron' -> 'deaaron').
      - Convierte guiones en espacios ('Karl-Anthony Towns' -> 'karl anthony towns').
      - Remueve sufijos generacionales ('Jr.', 'Sr.', 'II', 'III', 'IV', 'V').
      - Resuelve alias frecuentes ('Nicolas Claxton' -> 'nic claxton', 'Jimmy Butler III' -> 'jimmy butler').
    """
    if not nombre:
        return ""
    clean = (
        str(nombre)
        .replace("đ", "d")
        .replace("Đ", "D")
        .replace("ł", "l")
        .replace("Ł", "L")
    )
    clean = (
        unicodedata.normalize("NFKD", clean)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    clean = clean.replace(".", "").replace("'", "").replace("\u2019", "").replace("`", "")
    clean = clean.replace("-", " ")
    clean = re.sub(r"[^a-z0-9\s]+", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    clean = re.sub(r"\s+(?:jr|sr|ii|iii|iv|v)$", "", clean).strip()
    return PLAYER_NAME_ALIASES.get(clean, clean)


def clasificar_estatus_lesion_nba(
    status_raw: str,
    comment_raw: str = "",
    fantasy_abbr: str = "",
) -> Optional[str]:
    """
    Clasifica si un registro del Injury Report de ESPN corresponde estrictamente a un jugador
    confirmado como 'Out' o 'Doubtful'.
    Ignora jugadores 'Questionable', 'Probable', 'Active' o 'Day-To-Day' genéricos.
    Retorna 'Out', 'Doubtful' o None.
    """
    st_clean = str(status_raw or "").strip().lower()
    f_clean = str(fantasy_abbr or "").strip().upper()
    comment_clean = str(comment_raw or "").strip()

    if st_clean in {
        "out",
        "o",
        "injury_status_out",
        "out for season",
        "ofs",
        "suspended",
        "suspension",
    } or st_clean.startswith("out "):
        return "Out"

    if st_clean in {
        "doubtful",
        "d",
        "injury_status_doubtful",
    } or st_clean.startswith("doubtful"):
        return "Doubtful"

    if f_clean in {"OUT", "OFS"} and st_clean not in {
        "day-to-day",
        "dd",
        "gtd",
        "injury_status_daytoday",
        "questionable",
        "probable",
    }:
        return "Out"

    if f_clean in {"D", "DOUBTFUL"}:
        return "Doubtful"

    # En ESPN NBA, los jugadores 'Doubtful' suelen agruparse bajo la etiqueta 'Day-To-Day'
    # especificando explícitamente 'is doubtful' / 'listed as doubtful' en el comentario oficial.
    if st_clean in {"day-to-day", "dd", "gtd", "injury_status_daytoday"} and comment_clean:
        if re.search(
            r"\b(?:is|are|listed as|downgraded to|remains|tagged as|considered)\s+doubtful\b",
            comment_clean,
            flags=re.IGNORECASE,
        ) and not re.search(r"\bupgraded\s+from\s+doubtful\b", comment_clean, flags=re.IGNORECASE):
            return "Doubtful"

    return None


def _parsear_html_espn_injuries(html_text: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Parsea con BeautifulSoup el HTML oficial de 'https://www.espn.com/nba/injuries'.
    Extrae por equipo únicamente los jugadores confirmados como 'Out' o 'Doubtful'.
    """
    if not html_text or "awsWafCookieDomainList" in html_text:
        return {}

    soup = BeautifulSoup(html_text, "html.parser")
    reporte: Dict[str, List[Dict[str, Any]]] = {}
    seen_per_team: Dict[str, set] = {}

    containers = soup.select("div.ResponsiveTable")
    if not containers:
        containers = soup.find_all("section")

    for block in containers:
        table = block.find("table")
        if table is None:
            continue

        team_label = ""
        title_el = block.find(
            ["div", "span", "h2", "h3", "h4"],
            class_=lambda c: bool(
                c
                and (
                    "Table__Title" in str(c)
                    or "injuries__teamName" in str(c)
                    or "TeamName" in str(c)
                )
            ),
        )
        if title_el is not None:
            team_label = title_el.get_text(" ", strip=True)
        if not team_label:
            img_el = block.find("img", alt=True)
            if img_el is not None and img_el.get("alt"):
                team_label = str(img_el.get("alt")).strip()
        if not team_label:
            prev_heading = block.find_previous(["h2", "h3", "h4"])
            if prev_heading is not None:
                team_label = prev_heading.get_text(" ", strip=True)

        team_abbr = normalizar_equipo_nba(team_label)
        if not team_abbr:
            continue

        headers = [
            th.get_text(" ", strip=True).upper()
            for th in table.select("thead th")
        ]
        idx_name = 0
        idx_pos = 1
        idx_return = 2
        idx_status = 3
        idx_comment = 4

        for idx, h_txt in enumerate(headers):
            if any(k in h_txt for k in ("NAME", "PLAYER", "JUGADOR")):
                idx_name = idx
            elif h_txt in {"POS", "POSITION", "POSICIÓN"}:
                idx_pos = idx
            elif any(k in h_txt for k in ("RETURN", "RETORNO", "DATE", "FECHA")):
                idx_return = idx
            elif any(k in h_txt for k in ("STATUS", "ESTADO", "ESTATUS")):
                idx_status = idx
            elif any(k in h_txt for k in ("COMMENT", "COMENTARIO", "DETAIL")):
                idx_comment = idx

        rows = table.select("tbody tr")
        if not rows:
            rows = table.find_all("tr")[1:]

        for tr in rows:
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue

            name_cell = tds[idx_name] if idx_name < len(tds) else tds[0]
            anchor = name_cell.find("a")
            player_name = (
                anchor.get_text(" ", strip=True)
                if anchor is not None
                else name_cell.get_text(" ", strip=True)
            )
            if not player_name:
                continue

            pos_val = (
                tds[idx_pos].get_text(" ", strip=True)
                if idx_pos < len(tds)
                else ""
            )
            return_val = (
                tds[idx_return].get_text(" ", strip=True)
                if idx_return < len(tds)
                else ""
            )

            if idx_status < len(tds):
                status_cell = tds[idx_status]
                status_span = status_cell.find("span", class_=lambda c: bool(c and "TextStatus" in str(c)))
                status_raw = (
                    status_span.get_text(" ", strip=True)
                    if status_span is not None
                    else status_cell.get_text(" ", strip=True)
                )
            else:
                status_raw = tds[-1].get_text(" ", strip=True)

            comment_val = (
                tds[idx_comment].get_text(" ", strip=True)
                if idx_comment < len(tds)
                else ""
            )

            clasificacion = clasificar_estatus_lesion_nba(
                status_raw=status_raw,
                comment_raw=comment_val,
            )
            if clasificacion not in {"Out", "Doubtful"}:
                continue

            norm_key = normalizar_nombre_jugador_nba(player_name)
            if not norm_key:
                continue

            team_seen = seen_per_team.setdefault(team_abbr, set())
            if norm_key in team_seen:
                continue
            team_seen.add(norm_key)

            reporte.setdefault(team_abbr, []).append(
                {
                    "team_abbr": team_abbr,
                    "jugador": player_name,
                    "jugador_norm": norm_key,
                    "pos": pos_val,
                    "status": clasificacion,
                    "fecha_retorno": return_val,
                    "detalle": comment_val,
                    "fuente": "ESPN HTML Injury Report",
                }
            )

    return reporte


def _parsear_json_api_espn_injuries(payload: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Parsea el payload JSON del endpoint oficial de ESPN NBA Injuries
    ('https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries')
    que alimenta la página web oficial cuando CloudFront aplica reto WAF (HTTP 202) al HTML.
    Filtra estrictamente jugadores 'Out' o 'Doubtful' por equipo.
    """
    if not isinstance(payload, dict):
        return {}

    reporte: Dict[str, List[Dict[str, Any]]] = {}
    seen_per_team: Dict[str, set] = {}

    for team_entry in payload.get("injuries", []):
        if not isinstance(team_entry, dict):
            continue

        team_abbr = normalizar_equipo_nba(str(team_entry.get("displayName", "")))
        injuries_list = team_entry.get("injuries", [])
        if not isinstance(injuries_list, list):
            continue

        for inj in injuries_list:
            if not isinstance(inj, dict):
                continue

            athlete = inj.get("athlete") if isinstance(inj.get("athlete"), dict) else {}
            if not team_abbr:
                ath_team = athlete.get("team") if isinstance(athlete.get("team"), dict) else {}
                team_abbr = normalizar_equipo_nba(
                    str(ath_team.get("abbreviation") or ath_team.get("displayName") or "")
                )
            if not team_abbr:
                continue

            player_name = str(
                athlete.get("displayName")
                or athlete.get("fullName")
                or athlete.get("shortName")
                or ""
            ).strip()
            if not player_name:
                continue

            pos_obj = athlete.get("position") if isinstance(athlete.get("position"), dict) else {}
            pos_str = str(pos_obj.get("abbreviation", "")).strip()

            status_raw = str(inj.get("status", "")).strip()
            type_obj = inj.get("type") if isinstance(inj.get("type"), dict) else {}
            if not status_raw:
                status_raw = str(type_obj.get("description") or type_obj.get("name") or "").strip()

            details_obj = inj.get("details") if isinstance(inj.get("details"), dict) else {}
            fantasy_obj = (
                details_obj.get("fantasyStatus")
                if isinstance(details_obj.get("fantasyStatus"), dict)
                else {}
            )
            fantasy_abbr = str(fantasy_obj.get("abbreviation", "")).strip()

            short_comment = str(inj.get("shortComment") or inj.get("longComment") or "").strip()
            clasificacion = clasificar_estatus_lesion_nba(
                status_raw=status_raw,
                comment_raw=short_comment,
                fantasy_abbr=fantasy_abbr,
            )
            if clasificacion not in {"Out", "Doubtful"}:
                continue

            norm_key = normalizar_nombre_jugador_nba(player_name)
            if not norm_key:
                continue

            team_seen = seen_per_team.setdefault(team_abbr, set())
            if norm_key in team_seen:
                continue
            team_seen.add(norm_key)

            injury_part = str(details_obj.get("type") or "").strip()
            injury_detail = str(details_obj.get("detail") or "").strip()
            return_date = str(details_obj.get("returnDate") or "").strip()
            resumen_lesion = " - ".join(x for x in (injury_part, injury_detail) if x)
            if not resumen_lesion:
                resumen_lesion = short_comment

            reporte.setdefault(team_abbr, []).append(
                {
                    "team_abbr": team_abbr,
                    "jugador": player_name,
                    "jugador_norm": norm_key,
                    "pos": pos_str,
                    "status": clasificacion,
                    "fecha_retorno": return_date,
                    "tipo_lesion": injury_part,
                    "detalle": resumen_lesion,
                    "comentario": short_comment,
                    "fuente": "ESPN Official NBA Injuries Feed",
                }
            )

    return reporte


def _http_get_text(url: str, timeout: int = 10) -> Tuple[int, str]:
    """Ejecuta una petición HTTP GET resiliente usando `requests` o `urllib.request`."""
    if requests is not None:
        try:
            resp = requests.get(url, headers=INJURIES_HTTP_HEADERS, timeout=timeout)
            return int(resp.status_code), str(resp.text or "")
        except Exception:
            pass

    try:
        req = urllib.request.Request(url, headers=INJURIES_HTTP_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = int(getattr(response, "status", 200))
            body = response.read().decode("utf-8", errors="replace")
            return status_code, body
    except Exception:
        return 0, ""


def obtener_reporte_lesiones_nba(
    url: str = ESPN_NBA_INJURIES_URL,
    timeout: int = 10,
    force_refresh: bool = False,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Consulta el Injury Report oficial de ESPN NBA ('https://www.espn.com/nba/injuries')
    y filtra/extrae únicamente los jugadores confirmados como 'Out' o 'Doubtful' por equipo.

    Flujo de extracción:
      1. Consulta directamente 'https://www.espn.com/nba/injuries' y parsea las tablas HTML
         por franquicia mediante BeautifulSoup (`beautifulsoup4`).
      2. Si CloudFront/AWS WAF responde con challenge vacío (HTTP 202) o sin tablas renderizadas,
         consulta automáticamente el endpoint JSON oficial que respalda la misma página de ESPN
         ('https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries').

    Retorna:
      Dict[team_abbr, List[Dict[str, Any]]] donde cada entrada contiene:
      `{'team_abbr', 'jugador', 'jugador_norm', 'pos', 'status', 'fecha_retorno', 'detalle', 'fuente'}`.
    """
    now_epoch = time.time()
    use_default_url = str(url).strip() == ESPN_NBA_INJURIES_URL

    if (
        use_default_url
        and not force_refresh
        and _INJURIES_CACHE["data"] is not None
        and (now_epoch - float(_INJURIES_CACHE["timestamp_epoch"])) < _INJURIES_CACHE_TTL_SEC
    ):
        return _INJURIES_CACHE["data"]

    reporte: Dict[str, List[Dict[str, Any]]] = {}
    fuente_activa = "Sin conexión ESPN"

    # 1. Consulta HTML primaria a https://www.espn.com/nba/injuries con BeautifulSoup
    status_html, html_body = _http_get_text(url, timeout=timeout)
    if status_html == 200 and html_body:
        reporte = _parsear_html_espn_injuries(html_body)
        if reporte:
            fuente_activa = "ESPN NBA Injuries (HTML BeautifulSoup)"

    # 2. Respaldo oficial directo al feed JSON de ESPN NBA Injuries si WAF (202) bloquea HTML
    if not reporte and use_default_url:
        status_api, json_body = _http_get_text(ESPN_NBA_INJURIES_API_URL, timeout=timeout)
        if status_api == 200 and json_body:
            try:
                payload = json.loads(json_body)
                reporte = _parsear_json_api_espn_injuries(payload)
                if reporte:
                    fuente_activa = "ESPN NBA Injuries (Official API Feed)"
            except Exception:
                reporte = {}

    if use_default_url and (reporte or _INJURIES_CACHE["data"] is None):
        total_bajas = sum(len(v) for v in reporte.values())
        _INJURIES_CACHE["timestamp_epoch"] = now_epoch
        _INJURIES_CACHE["data"] = reporte
        _INJURIES_CACHE["meta"] = {
            "fuente": fuente_activa,
            "ultima_actualizacion": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "total_bajas": total_bajas,
            "total_jugadores_descartados": total_bajas,
            "equipos_con_bajas": len(reporte),
        }

    return reporte


def obtener_jugadores_descartados_por_equipo(
    reporte: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    force_refresh: bool = False,
) -> Dict[str, List[str]]:
    """
    Devuelve un diccionario simplificado `{team_abbr: ['Jugador 1', 'Jugador 2', ...]}`
    únicamente con los jugadores confirmados como 'Out' o 'Doubtful' por franquicia.
    """
    rep = reporte if reporte is not None else obtener_reporte_lesiones_nba(force_refresh=force_refresh)
    return {
        team_abbr: [str(item["jugador"]) for item in items if item.get("jugador")]
        for team_abbr, items in rep.items()
    }


def obtener_metadata_sincronizacion_lesiones() -> Dict[str, Any]:
    """Devuelve metadatos de telemetría de la última sincronización del reporte de lesiones ESPN."""
    return dict(_INJURIES_CACHE.get("meta", {}))


if __name__ == "__main__":
    rep_live = obtener_reporte_lesiones_nba(force_refresh=True)
    meta_live = obtener_metadata_sincronizacion_lesiones()
    print(
        f"[ESPN NBA INJURIES] Fuente: {meta_live.get('fuente')} | "
        f"Equipos con bajas: {meta_live.get('equipos_con_bajas')} | "
        f"Total Out/Doubtful: {meta_live.get('total_bajas')}"
    )
    for abbr_key in sorted(rep_live.keys()):
        jugadores_str = ", ".join(
            f"{it['jugador']} ({it['status']})" for it in rep_live[abbr_key]
        )
        print(f"  {abbr_key}: {jugadores_str}")
