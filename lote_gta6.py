#!/usr/bin/env python3
"""
Pipeline rápido en lote para extraer Shorts del directo/VOD de GTA 6 usando
únicamente Python + faster-whisper + yt-dlp + FFmpeg puro (sin Remotion, sin subtítulos,
sin música de fondo y sin cambios de cámara).

Uso por pasos:
  1. Audio desde 04:27:00 + transcripción faster-whisper (+16020s offset):
     python lote_gta6.py --paso 1

  2. Detección automática de momentos obligatorios + bugs/extras -> plan_clips.json:
     python lote_gta6.py --paso 2

  3. Test de encuadre (genera clips_gta6_ep1/test_encuadre.jpg para verificar split 1080x1920):
     python lote_gta6.py --test-encuadre

  4. Descarga 1080p por tramos + render FFmpeg puro -> clips_gta6_ep1/listos/:
     python lote_gta6.py --paso 3

  Todo en lote:
     python lote_gta6.py --todo
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from procesar_clip import (
    _normalizar_token,
    obtener_duracion_video,
    obtener_ruta_ffmpeg,
    obtener_ruta_ffprobe,
)

DEFAULT_URL = "https://www.youtube.com/watch?v=xXTc9907J9Y"
OFFSET_SEG = 16020.0  # 04:27:00 = 4*3600 + 27*60
START_MARK = "04:27:00"
MAX_CLIP_DUR = 80.0  # 1 min 20s máximo por clip
SUFIJO_CANAL = "@berlinuno #shorts"
MAX_TITULO_CHARS = 55

# Encuadre fijo 1080x1920 (720 arriba + 1200 abajo = 1920)
DEFAULT_CAM_CROP = "460:306:0:226"   # w:h:x:y -> scale 1080:720 (sin borde blanco inferior)
DEFAULT_GAME_CROP = "972:1080:508:0"  # w:h:x:y -> scale 1080:1200 (evita webcam y chat a la izquierda)

BASE_DIR = Path(__file__).resolve().parent
TEMP_DIR = BASE_DIR / "temp_gta6"
TRAMOS_DIR = TEMP_DIR / "tramos_1080p"
OUT_DIR = BASE_DIR / "clips_gta6_ep1"
LISTOS_DIR = OUT_DIR / "listos"

AUDIO_COMPLETO = TEMP_DIR / "audio_completo.m4a"
AUDIO_DESDE_427 = TEMP_DIR / "audio_desde_427.m4a"
TRANSCRIPCION_JSON = TEMP_DIR / "transcripcion_gta6_ep1.json"
ASTATS_JSON = TEMP_DIR / "picos_audio_desde_427.json"
PLAN_JSON = OUT_DIR / "plan_clips.json"
TEST_ENCUADRE_JPG = OUT_DIR / "test_encuadre.jpg"
RESUMEN_TXT = OUT_DIR / "TITULOS_Y_RESUMEN.txt"


def seg_a_hhmmss(segundos: float) -> str:
    """Convierte segundos absolutos a formato HH:MM:SS."""
    total = max(0, int(round(segundos)))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def hhmmss_a_seg(valor: str | float | int) -> float:
    """Convierte HH:MM:SS (o número) a segundos."""
    if isinstance(valor, (int, float)):
        return float(valor)
    txt = str(valor).strip()
    if ":" not in txt:
        return float(txt)
    partes = [float(p) for p in txt.split(":")]
    if len(partes) == 3:
        return partes[0] * 3600.0 + partes[1] * 60.0 + partes[2]
    if len(partes) == 2:
        return partes[0] * 60.0 + partes[1]
    return float(partes[0])


def formatear_titulo_youtube(base: str) -> str:
    """Ajusta un título limpio <= 55 caracteres terminando con '@berlinuno #shorts'."""
    limpio = re.sub(r"\s{2,}", " ", base.strip(" .,-:;"))
    presupuesto = MAX_TITULO_CHARS - len(SUFIJO_CANAL) - 1
    if len(limpio) > presupuesto:
        recorte = limpio[:presupuesto].rsplit(" ", 1)[0].strip(" .,-:;")
        limpio = recorte if len(recorte) >= 8 else limpio[:presupuesto].strip(" .,-:;")
    titulo = f"{limpio} {SUFIJO_CANAL}".strip()
    return titulo[:MAX_TITULO_CHARS]


# ---------------------------------------------------------------------------
# Helpers DASH / yt-dlp para VODs post_live y directos con segmentos de 1s
# ---------------------------------------------------------------------------

_YTDLP_INFO_CACHE: dict[str, dict[str, Any]] = {}


def _obtener_info_ytdlp(url: str) -> dict[str, Any]:
    """Extrae metadatos y lista de fragmentos con Node JS runtime (cacheado en memoria)."""
    if url in _YTDLP_INFO_CACHE:
        return _YTDLP_INFO_CACHE[url]

    import shutil
    import yt_dlp

    node_bin = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "remote_components": ["ejs:github"],
    }
    if Path(node_bin).is_file():
        ydl_opts["js_runtimes"] = {"node": {"path": node_bin}}

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    _YTDLP_INFO_CACHE[url] = info
    return info


def _descargar_fragmentos_dash(
    frags: list[dict[str, Any]],
    start_idx: int,
    end_idx: int,
    out_raw: Path,
    workers: int = 20,
    etiqueta: str = "DASH",
) -> None:
    """Descarga en paralelo fragmentos fMP4 [start_idx:end_idx] con conexión HTTP persistente."""
    import urllib3
    from concurrent.futures import ThreadPoolExecutor

    s_i = max(0, int(start_idx))
    e_i = min(len(frags), int(end_idx))
    chosen = frags[s_i:e_i]
    if not chosen:
        raise RuntimeError(f"Rango vacío de fragmentos DASH [{s_i}:{e_i}]")

    http = urllib3.PoolManager(num_pools=8, maxsize=workers + 4, retries=False)
    total = len(chosen)
    print(f"  [{etiqueta}] Descargando {total} segmentos ({s_i}s -> {e_i}s) con {workers} hilos...")

    def fetch(frag: dict[str, Any]) -> bytes:
        u = frag["url"]
        for intento in range(5):
            try:
                resp = http.request("GET", u, timeout=15.0)
                if resp.status == 200 and resp.data:
                    return resp.data
                raise RuntimeError(f"HTTP {resp.status}")
            except Exception:
                if intento == 4:
                    raise
                time.sleep(0.25 * (intento + 1))
        return b""

    out_raw.parent.mkdir(parents=True, exist_ok=True)
    with out_raw.open("wb") as fp:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for idx_done, chunk in enumerate(ex.map(fetch, chosen), start=1):
                fp.write(chunk)
                if total >= 1000 and idx_done % 3000 == 0:
                    print(f"    [{etiqueta}] {idx_done}/{total} segmentos...")


# ---------------------------------------------------------------------------
# PASO 1: Audio liviano desde 04:27:00 + faster-whisper con offset +16020s
# ---------------------------------------------------------------------------

def descargar_o_recortar_audio_427(url: str, forzar: bool = False) -> Path:
    """Descarga audio_completo.m4a (sin --download-sections) y recorta local desde 04:27:00."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    if AUDIO_DESDE_427.is_file() and AUDIO_DESDE_427.stat().st_size > 1_000_000 and not forzar:
        dur = obtener_duracion_video(AUDIO_DESDE_427)
        print(f"[Paso 1] Reutilizando audio ya recortado: {AUDIO_DESDE_427.name} ({dur/60:.1f} min)")
        return AUDIO_DESDE_427

    ffmpeg_exe = obtener_ruta_ffmpeg()

    # 1. Descargar audio completo liviano (~48-64kbps) a velocidad máxima si no existe aún
    if not (AUDIO_COMPLETO.is_file() and AUDIO_COMPLETO.stat().st_size > 5_000_000) or forzar:
        print("[Paso 1] Descargando audio completo liviano (-f 139) en temp_gta6/audio_completo.m4a...")
        patron_completo = str(TEMP_DIR / "audio_completo.%(ext)s")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "yt_dlp",
                "--no-check-certificates",
                "-f",
                "139/bestaudio[abr<=64]/worstaudio",
                "-o",
                patron_completo,
                url,
            ],
            check=True,
        )
        if not AUDIO_COMPLETO.is_file():
            for ext in (".m4a", ".webm", ".opus", ".ogg", ".mp3", ".mp4"):
                cand = TEMP_DIR / f"audio_completo{ext}"
                if cand.is_file() and cand.stat().st_size > 5_000_000:
                    _normalizar_a_m4a(ffmpeg_exe, cand, AUDIO_COMPLETO)
                    break

    # 2. Recortar localmente desde 04:27:00 en 1 segundo sin recodificar
    print(f"[Paso 1] Recortando {AUDIO_COMPLETO.name} desde {START_MARK} -> {AUDIO_DESDE_427.name}...")
    subprocess.run(
        [
            ffmpeg_exe,
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-ss",
            START_MARK,
            "-i",
            str(AUDIO_COMPLETO),
            "-c",
            "copy",
            str(AUDIO_DESDE_427),
        ],
        check=True,
    )
    return AUDIO_DESDE_427


def _buscar_audio_descargado() -> Optional[Path]:
    for ext in (".m4a", ".webm", ".opus", ".ogg", ".mp3", ".mp4"):
        p = TEMP_DIR / f"audio_desde_427{ext}"
        if p.is_file() and p.stat().st_size > 1_000_000:
            return p
    return None


def _normalizar_a_m4a(ffmpeg_exe: str, origen: Path, destino: Path) -> None:
    if origen.suffix.lower() == ".m4a":
        origen.replace(destino)
        return
    subprocess.run(
        [
            ffmpeg_exe,
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-i",
            str(origen),
            "-vn",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            str(destino),
        ],
        check=True,
    )
    origen.unlink(missing_ok=True)


def paso_1_audio_y_transcripcion(
    url: str,
    modelo: str = "base",
    beam_size: int = 2,
    forzar_audio: bool = False,
    forzar_whisper: bool = False,
) -> Path:
    """Ejecuta el Paso 1 completo y guarda temp_gta6/transcripcion_gta6_ep1.json con offset +16020s."""
    audio_path = descargar_o_recortar_audio_427(url, forzar=forzar_audio)

    if TRANSCRIPCION_JSON.is_file() and not forzar_whisper:
        try:
            prev = json.loads(TRANSCRIPCION_JSON.read_text(encoding="utf-8"))
            segs = prev.get("segments", [])
            if segs and float(segs[0].get("start", 0)) >= OFFSET_SEG:
                print(
                    f"[Paso 1] Reutilizando transcripción existente: {TRANSCRIPCION_JSON} ({len(segs)} segmentos)"
                )
                return TRANSCRIPCION_JSON
        except Exception:
            pass

    from faster_whisper import WhisperModel

    print(
        f"[Paso 1] Transcribiendo {audio_path.name} con faster-whisper (model='{modelo}', compute_type='int8', vad_filter=True, offset=+{int(OFFSET_SEG)}s)..."
    )
    t0 = time.time()
    model = WhisperModel(modelo, device="cpu", compute_type="int8")
    segments_iter, info = model.transcribe(
        str(audio_path),
        language="es",
        vad_filter=True,
        beam_size=beam_size,
    )

    segments_out: list[dict[str, Any]] = []
    ultimo_reporte = -900.0
    for seg in segments_iter:
        start_abs = round(float(seg.start) + OFFSET_SEG, 2)
        end_abs = round(float(seg.end) + OFFSET_SEG, 2)
        texto = seg.text.strip()
        if not texto:
            continue
        segments_out.append(
            {
                "id": len(segments_out),
                "start": start_abs,
                "end": end_abs,
                "hhmmss_start": seg_a_hhmmss(start_abs),
                "hhmmss_end": seg_a_hhmmss(end_abs),
                "text": texto,
            }
        )
        if seg.start - ultimo_reporte >= 900.0:
            ultimo_reporte = float(seg.start)
            print(
                f"  [Whisper] Progreso: {seg_a_hhmmss(start_abs)} | {len(segments_out)} segs | {time.time() - t0:.1f}s transcurridos"
            )

    payload = {
        "source_url": url,
        "audio_file": str(audio_path),
        "offset_seconds": OFFSET_SEG,
        "offset_hhmmss": START_MARK,
        "model": modelo,
        "language": getattr(info, "language", "es"),
        "audio_duration_sec": round(float(getattr(info, "duration", 0.0)), 2),
        "segments_count": len(segments_out),
        "segments": segments_out,
    }
    TRANSCRIPCION_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"[Paso 1] Transcripción guardada en {TRANSCRIPCION_JSON} ({len(segments_out)} segmentos, {time.time() - t0:.1f}s)"
    )
    return TRANSCRIPCION_JSON


# ---------------------------------------------------------------------------
# PASO 2: Detección y clasificación automática de momentos obligatorios + extras
# ---------------------------------------------------------------------------

def calcular_picos_audio_427(audio_path: Path) -> list[dict[str, Any]]:
    """Mide energía RMS por ventanas de 2s en audio_desde_427.m4a (con offset +16020s)."""
    if ASTATS_JSON.is_file():
        try:
            data = json.loads(ASTATS_JSON.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass

    if not audio_path.is_file():
        return []

    ffmpeg_exe = obtener_ruta_ffmpeg()
    print(f"[Paso 2] Analizando energía/gritos de audio en {audio_path.name}...")
    cmd = [
        ffmpeg_exe,
        "-hide_banner",
        "-i",
        str(audio_path),
        "-af",
        "asetnsamples=96000,astats=metadata=1:reset=1",
        "-f",
        "null",
        "-",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    ventanas: list[dict[str, Any]] = []
    cur_t = 0.0
    for line in res.stderr.splitlines():
        if "pts_time:" in line:
            m = re.search(r"pts_time:([\d.]+)", line)
            if m:
                cur_t = float(m.group(1))
        elif "RMS level dB:" in line:
            m = re.search(r"RMS level dB:\s*(-?[\d.]+|inf|-inf)", line)
            if m and m.group(1) not in ("inf", "-inf"):
                t_abs = round(cur_t + OFFSET_SEG, 1)
                ventanas.append({"t": t_abs, "db": round(float(m.group(1)), 2)})

    if ventanas:
        ASTATS_JSON.write_text(json.dumps(ventanas, ensure_ascii=False), encoding="utf-8")
    return ventanas


def _texto_en_ventana(segments: list[dict[str, Any]], start: float, end: float) -> str:
    return " ".join(
        s["text"] for s in segments if s["end"] >= start and s["start"] <= end
    ).strip()


def _construir_tramo_desde_ancla(
    segments: list[dict[str, Any]],
    ancla_t: float,
    pre_seg: float = 12.0,
    post_seg: float = 34.0,
) -> tuple[float, float]:
    """Ajusta un tramo limpio [inicio, fin] <= 80s alineado a fronteras de oración Whisper."""
    target_start = max(OFFSET_SEG, ancla_t - pre_seg)
    target_end = target_start + min(MAX_CLIP_DUR, pre_seg + post_seg)

    cercanos = [
        s for s in segments if s["end"] >= target_start - 2.0 and s["start"] <= target_end + 2.0
    ]
    if cercanos:
        inicio = min(cercanos, key=lambda s: abs(s["start"] - target_start))["start"]
        fin = min(cercanos, key=lambda s: abs(s["end"] - target_end))["end"]
    else:
        inicio, fin = target_start, target_end

    inicio = max(OFFSET_SEG, round(inicio - 0.3, 2))
    fin = round(fin + 0.4, 2)
    if fin - inicio > MAX_CLIP_DUR:
        fin = round(inicio + MAX_CLIP_DUR, 2)
    if fin - inicio < 22.0:
        fin = round(inicio + 32.0, 2)
    return inicio, fin


MOMENTOS_OBLIGATORIOS = [
    {
        "id": "01_intro_gta6",
        "categoria": "reaccion",
        "keywords": ["intro", "empieza", "empezó", "comienza", "prólogo", "prologo", "rockstar", "gta 6", "gta seis", "bienvenidos"],
        "titulo": "Su reacción al inicio de GTA 6 😱🔥",
        "pre": 6.0,
        "post": 44.0,
    },
    {
        "id": "02_primeros_graficos",
        "categoria": "reaccion",
        "keywords": ["gráficos", "graficos", "detalles", "iluminación", "reflejos", "agua", "textura", "realista", "mirá cómo se ve", "mira como se ve"],
        "titulo": "No pueden creer los gráficos de GTA 6 🤯",
        "pre": 8.0,
        "post": 38.0,
    },
    {
        "id": "03_cargando_nafta",
        "categoria": "mecanica",
        "keywords": ["nafta", "gasolina", "combustible", "estación de servicio", "estacion de servicio", "tanque", "cargar", "surtidor"],
        "titulo": "Cargando nafta por primera vez en GTA 6 ⛽",
        "pre": 10.0,
        "post": 40.0,
    },
    {
        "id": "04_andando_bici",
        "categoria": "mecanica",
        "keywords": ["bicicleta", "bici", "pedalea", "pedaleando", "cleta"],
        "titulo": "Andando en bicicleta en GTA 6 🚲😂",
        "pre": 8.0,
        "post": 38.0,
    },
    {
        "id": "05_andando_auto",
        "categoria": "mecanica",
        "keywords": ["conducir", "manejando", "volante", "físicas", "fisicas", "primer auto", "manejar", "dobla", "frena"],
        "titulo": "Probando manejar el primer auto en GTA 6 🚗",
        "pre": 8.0,
        "post": 42.0,
    },
    {
        "id": "06_pescando",
        "categoria": "animal",
        "keywords": ["pescar", "pescando", "pesca", "caña", "anzuelo", "pez", "pescado", "piqué", "pique"],
        "titulo": "Se ponen a pescar en GTA 6 y pasa esto 🎣",
        "pre": 10.0,
        "post": 42.0,
    },
    {
        "id": "07_pateando_cangrejo",
        "categoria": "animal",
        "keywords": ["cangrejo", "patea", "pateando", "patada", "pinza", "playa"],
        "titulo": "Patean un cangrejo en GTA 6 y termina mal 🦀💀",
        "pre": 8.0,
        "post": 36.0,
    },
    {
        "id": "08_cae_avion",
        "categoria": "bug",
        "keywords": ["avión", "avion", "avioneta", "cayó", "cayo", "estrelló", "estrello", "helicóptero", "vuela"],
        "titulo": "Se les cae un avión encima de la nada ✈️💥",
        "pre": 10.0,
        "post": 38.0,
    },
    {
        "id": "09_cocodrilo",
        "categoria": "animal",
        "keywords": ["cocodrilo", "caimán", "caiman", "lagarto", "pantano", "everglades", "mordió"],
        "titulo": "Se encuentran un cocodrilo gigante en vivo 🐊😱",
        "pre": 8.0,
        "post": 40.0,
    },
]


def _puntuar_segmento(texto: str, keywords: list[str]) -> float:
    norm_text = _normalizar_token(texto)
    pts = 0.0
    for kw in keywords:
        norm_kw = _normalizar_token(kw)
        if not norm_kw:
            continue
        if norm_kw in norm_text:
            pts += 3.0 + len(norm_kw.split()) * 1.5
    return pts


def paso_2_detectar_y_clasificar(min_extras: int = 10) -> Path:
    """Analiza transcripcion_gta6_ep1.json + energía de audio y genera plan_clips.json."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not TRANSCRIPCION_JSON.is_file():
        raise FileNotFoundError(
            f"Falta {TRANSCRIPCION_JSON}. Ejecutá primero: python lote_gta6.py --paso 1"
        )

    tr_data = json.loads(TRANSCRIPCION_JSON.read_text(encoding="utf-8"))
    segments: list[dict[str, Any]] = tr_data.get("segments", [])
    if not segments:
        raise RuntimeError("transcripcion_gta6_ep1.json no contiene segmentos.")

    ventanas_db = calcular_picos_audio_427(AUDIO_DESDE_427)
    db_map = {int(v["t"] // 2): v["db"] for v in ventanas_db}
    avg_db = (
        sum(v["db"] for v in ventanas_db) / len(ventanas_db) if ventanas_db else -25.0
    )

    def energia_cercana(t_sec: float) -> float:
        bucket = int(t_sec // 2)
        vals = [db_map.get(b, avg_db) for b in range(bucket - 2, bucket + 3)]
        return max(vals) - avg_db

    clips_plan: list[dict[str, Any]] = []
    usados: list[tuple[float, float]] = []

    def solapa(s: float, e: float, margen: float = 20.0) -> bool:
        return any(not (e + margen < us or s - margen > ue) for us, ue in usados)

    # 1..9 Momentos obligatorios de 1 parte
    for spec in MOMENTOS_OBLIGATORIOS:
        mejor_t: Optional[float] = None
        mejor_score = 0.0
        for idx in range(len(segments)):
            win_s = segments[idx]["start"]
            win_txt = _texto_en_ventana(segments, win_s, win_s + 22.0)
            score = _puntuar_segmento(win_txt, spec["keywords"])
            if score <= 0:
                continue
            score += max(0.0, energia_cercana(win_s) * 0.4)
            if not solapa(win_s - 5, win_s + 30, margen=10.0) and score > mejor_score:
                mejor_score = score
                mejor_t = win_s

        if mejor_t is not None:
            ini, fin = _construir_tramo_desde_ancla(
                segments, mejor_t, pre_seg=spec["pre"], post_seg=spec["post"]
            )
            usados.append((ini, fin))
            clips_plan.append(
                {
                    "id": spec["id"],
                    "categoria": spec["categoria"],
                    "encontrado": True,
                    "score": round(mejor_score, 2),
                    "partes": [
                        {
                            "inicio": seg_a_hhmmss(ini),
                            "fin": seg_a_hhmmss(fin),
                            "inicio_seg": ini,
                            "fin_seg": fin,
                        }
                    ],
                    "duracion_est": round(fin - ini, 1),
                    "titulo_youtube": formatear_titulo_youtube(spec["titulo"]),
                    "etiqueta_opcional": None,
                    "muestra_texto": _texto_en_ventana(segments, ini, fin)[:240],
                }
            )
        else:
            clips_plan.append(
                {
                    "id": spec["id"],
                    "categoria": spec["categoria"],
                    "encontrado": False,
                    "partes": [],
                    "duracion_est": 0.0,
                    "titulo_youtube": formatear_titulo_youtube(spec["titulo"]),
                    "etiqueta_opcional": None,
                    "nota": "No detectado automáticamente con palabras clave en 04:27:00-fin; revisar timestamps.",
                }
            )

    # 10. NPC recuerda y pega (2 partes separadas por tiempo)
    npc_kw_a = ["corriendo", "salió corriendo", "salio corriendo", "qué hacés", "amigo", "señor", "flaco", "pará", "para"]
    npc_kw_b = ["siguiendo", "nos pegó", "nos pego", "se acuerda", "acordó", "piensa que", "me pegó", "me pego", "otra vez", "mismo chabón", "mismo npc", "mismo tipo"]
    candidatos_b = []
    for s in segments:
        txt_b = _texto_en_ventana(segments, s["start"], s["start"] + 18.0)
        sc_b = _puntuar_segmento(txt_b, npc_kw_b)
        if sc_b >= 4.5:
            candidatos_b.append((sc_b + max(0.0, energia_cercana(s["start"]) * 0.5), s["start"]))
    candidatos_b.sort(reverse=True)

    parte_a_t: Optional[float] = None
    parte_b_t: Optional[float] = None
    if candidatos_b:
        parte_b_t = candidatos_b[0][1]
        for s in segments:
            if parte_b_t - 900.0 <= s["start"] <= parte_b_t - 45.0:
                txt_a = _texto_en_ventana(segments, s["start"], s["start"] + 16.0)
                if _puntuar_segmento(txt_a, npc_kw_a) >= 4.5:
                    parte_a_t = s["start"]
                    break

    if parte_a_t is not None and parte_b_t is not None:
        a_ini, a_fin = _construir_tramo_desde_ancla(segments, parte_a_t, pre_seg=5.0, post_seg=24.0)
        b_ini, b_fin = _construir_tramo_desde_ancla(segments, parte_b_t, pre_seg=6.0, post_seg=32.0)
        # Mantener suma <= 80s
        if (a_fin - a_ini) + (b_fin - b_ini) > MAX_CLIP_DUR:
            b_fin = round(b_ini + (MAX_CLIP_DUR - (a_fin - a_ini)), 2)
        usados.extend([(a_ini, a_fin), (b_ini, b_fin)])
        clips_plan.append(
            {
                "id": "10_npc_recuerda_pega",
                "categoria": "npc",
                "encontrado": True,
                "partes": [
                    {
                        "inicio": seg_a_hhmmss(a_ini),
                        "fin": seg_a_hhmmss(a_fin),
                        "inicio_seg": a_ini,
                        "fin_seg": a_fin,
                    },
                    {
                        "inicio": seg_a_hhmmss(b_ini),
                        "fin": seg_a_hhmmss(b_fin),
                        "inicio_seg": b_ini,
                        "fin_seg": b_fin,
                    },
                ],
                "duracion_est": round((a_fin - a_ini) + (b_fin - b_ini), 1),
                "titulo_youtube": formatear_titulo_youtube("Este NPC los recuerda y los caga a trompadas 🥊"),
                "etiqueta_opcional": "AL RATO LO VOLVIERON A ENCONTRAR...",
                "muestra_texto": f"A: {_texto_en_ventana(segments, a_ini, a_fin)[:110]} | B: {_texto_en_ventana(segments, b_ini, b_fin)[:110]}",
            }
        )
    else:
        clips_plan.append(
            {
                "id": "10_npc_recuerda_pega",
                "categoria": "npc",
                "encontrado": False,
                "partes": [],
                "duracion_est": 0.0,
                "titulo_youtube": formatear_titulo_youtube("Este NPC los recuerda y los caga a trompadas 🥊"),
                "etiqueta_opcional": "AL RATO LO VOLVIERON A ENCONTRAR...",
                "nota": "No detectado automáticamente en 2 partes; ajustar inicio/fin tras revisar transcripcion_gta6_ep1.json.",
            }
        )

    # 11+ Extras: Bugs, glitches, choques, policía, tacón, gritos/risas
    extra_keywords = {
        "bug": ["bug", "bugeo", "bugueó", "glitch", "glitcheo", "glitcheó", "se trabó", "trabo", "traspasó", "desapareció", "volando"],
        "reaccion": ["qué carajo", "que carajo", "mirá esto", "mira esto", "tacón", "tacon", "no puede ser", "qué mierda", "boludo", "explotó", "exploto"],
        "npc": ["policía", "policia", "cana", "estrellas", "tiroteo", "arrestaron", "muerto", "chocó", "choco"],
    }
    candidatos_extra: list[tuple[float, str, float, str]] = []
    for s in segments:
        t_s = s["start"]
        if solapa(t_s - 5, t_s + 35, margen=25.0):
            continue
        win_txt = _texto_en_ventana(segments, t_s, t_s + 18.0)
        en = energia_cercana(t_s)
        best_cat = "reaccion"
        best_kw_pts = 0.0
        for cat, kws in extra_keywords.items():
            pts = _puntuar_segmento(win_txt, kws)
            if pts > best_kw_pts:
                best_kw_pts = pts
                best_cat = cat
        total_sc = best_kw_pts + max(0.0, en * 1.2)
        if total_sc >= 7.0 or en >= 6.5:
            candidatos_extra.append((total_sc, best_cat, t_s, win_txt))

    candidatos_extra.sort(reverse=True)
    extra_idx = 11
    for sc, cat, t_s, win_txt in candidatos_extra:
        if extra_idx >= 11 + min_extras:
            break
        ini, fin = _construir_tramo_desde_ancla(segments, t_s, pre_seg=10.0, post_seg=34.0)
        if solapa(ini, fin, margen=30.0):
            continue
        usados.append((ini, fin))
        slug = "bug" if cat == "bug" else "momento"
        snippet = re.sub(r"[^a-zA-ZáéíóúñÁÉÍÓÚÑ0-9 ¿?¡!]", "", win_txt)[:32].strip()
        titulo_base = f"¡{snippet}!" if len(snippet) >= 10 else "El momento más random en GTA 6 😂"
        clips_plan.append(
            {
                "id": f"{extra_idx:02d}_extra_{slug}",
                "categoria": cat,
                "encontrado": True,
                "score": round(sc, 2),
                "partes": [
                    {
                        "inicio": seg_a_hhmmss(ini),
                        "fin": seg_a_hhmmss(fin),
                        "inicio_seg": ini,
                        "fin_seg": fin,
                    }
                ],
                "duracion_est": round(fin - ini, 1),
                "titulo_youtube": formatear_titulo_youtube(titulo_base),
                "etiqueta_opcional": None,
                "muestra_texto": win_txt[:220],
            }
        )
        extra_idx += 1

    PLAN_JSON.write_text(
        json.dumps(clips_plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    encontrados = sum(1 for c in clips_plan if c.get("encontrado"))
    print(
        f"[Paso 2] Plan guardado en {PLAN_JSON} ({encontrados}/{len(clips_plan)} clips listos con timestamps)"
    )
    return PLAN_JSON


# ---------------------------------------------------------------------------
# PASO 3: Descarga por tramos 1080p, test_encuadre.jpg y render FFmpeg puro
# ---------------------------------------------------------------------------

_YTDLP_STREAM_URLS_CACHE: dict[str, tuple[str, str]] = {}


def _resolver_urls_1080p(url: str) -> Optional[tuple[str, str]]:
    """Resuelve las URLs directas de video (1080p) y audio con yt-dlp -g (cacheadas)."""
    if url in _YTDLP_STREAM_URLS_CACHE:
        return _YTDLP_STREAM_URLS_CACHE[url]
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-check-certificates",
            "-f",
            "bestvideo[height=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio",
            "-g",
            url,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    lines = [l.strip() for l in res.stdout.splitlines() if l.strip().startswith("http")]
    if res.returncode == 0 and len(lines) >= 2:
        _YTDLP_STREAM_URLS_CACHE[url] = (lines[0], lines[1])
        return _YTDLP_STREAM_URLS_CACHE[url]
    return None


def descargar_tramo_1080p(
    url: str, inicio: str, fin: str, destino: Path, forzar: bool = False
) -> Path:
    """Descarga únicamente el tramo [inicio, fin] en 1080p usando -ss antes de -i sobre URL directa o yt-dlp."""
    TRAMOS_DIR.mkdir(parents=True, exist_ok=True)
    if destino.is_file() and destino.stat().st_size > 100_000 and not forzar:
        return destino

    ffmpeg_exe = obtener_ruta_ffmpeg()
    dur_tramo = max(1.0, hhmmss_a_seg(fin) - hhmmss_a_seg(inicio))

    # Método rápido: -ss antes de -i directo con URLs de yt-dlp -g (-c copy sin recodificar)
    urls = _resolver_urls_1080p(url)
    if urls is not None:
        v_url, a_url = urls
        print(f"  [FFmpeg -ss directo 1080p] Descargando {inicio} -> {fin} en {destino.name}...")
        res_ff = subprocess.run(
            [
                ffmpeg_exe,
                "-y",
                "-hide_banner",
                "-loglevel",
                "warning",
                "-ss",
                inicio,
                "-t",
                f"{dur_tramo:.2f}",
                "-i",
                v_url,
                "-ss",
                inicio,
                "-t",
                f"{dur_tramo:.2f}",
                "-i",
                a_url,
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "libx264",
                "-crf",
                "17",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                str(destino),
            ],
            check=False,
        )
        if res_ff.returncode == 0 and destino.is_file() and destino.stat().st_size > 100_000:
            return destino

    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-check-certificates",
        "--download-sections",
        f"*{inicio}-{fin}",
        "-f",
        "bestvideo[height=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
        "--merge-output-format",
        "mp4",
        "--force-keyframes-at-cuts",
        "-o",
        str(destino),
        "--force-overwrite",
        url,
    ]
    print(f"  [yt-dlp 1080p] Descargando {inicio} -> {fin} en {destino.name}...")
    res = subprocess.run(cmd, check=False)
    if res.returncode == 0 and destino.is_file() and destino.stat().st_size > 100_000:
        return destino

    raise RuntimeError(f"No se pudo descargar el tramo 1080p {inicio}-{fin}")


def generar_test_encuadre(
    url: str,
    cam_crop: str = DEFAULT_CAM_CROP,
    game_crop: str = DEFAULT_GAME_CROP,
    timestamp_prueba: Optional[str] = None,
) -> Path:
    """Genera clips_gta6_ep1/test_encuadre.jpg aplicando exactamente el split 1080x1920."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ffmpeg_exe = obtener_ruta_ffmpeg()

    ts_inicio = timestamp_prueba
    if not ts_inicio and PLAN_JSON.is_file():
        plan = json.loads(PLAN_JSON.read_text(encoding="utf-8"))
        for c in plan:
            if c.get("partes"):
                ts_inicio = c["partes"][0]["inicio"]
                break
    if not ts_inicio:
        ts_inicio = "04:30:00"

    ini_seg = hhmmss_a_seg(ts_inicio)
    fin_str = seg_a_hhmmss(ini_seg + 4.0)
    muestra_mp4 = TEMP_DIR / "test_encuadre_src.mp4"
    descargar_tramo_1080p(url, ts_inicio, fin_str, muestra_mp4)

    filter_complex = (
        f"[0:v]crop={cam_crop},scale=1080:720,setsar=1[cam];"
        f"[0:v]crop={game_crop},scale=1080:1200,setsar=1[game];"
        f"[cam][game]vstack=inputs=2[v]"
    )
    subprocess.run(
        [
            ffmpeg_exe,
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-ss",
            "1.5",
            "-i",
            str(muestra_mp4),
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(TEST_ENCUADRE_JPG),
        ],
        check=True,
    )
    print(f"[Test Encuadre] Imagen generada en {TEST_ENCUADRE_JPG}")
    return TEST_ENCUADRE_JPG


def _escapar_drawtext(texto: str) -> str:
    return (
        texto.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\u2019")
        .replace("%", "\\%")
    )


def renderizar_clip_ffmpeg(
    partes_mp4: list[Path],
    salida_mp4: Path,
    etiqueta_opcional: Optional[str] = None,
    cam_crop: str = DEFAULT_CAM_CROP,
    game_crop: str = DEFAULT_GAME_CROP,
) -> float:
    """Renderiza el Short final 1080x1920 con FFmpeg puro (sin Remotion, música ni subtítulos)."""
    ffmpeg_exe = obtener_ruta_ffmpeg()
    LISTOS_DIR.mkdir(parents=True, exist_ok=True)

    split_tpl = (
        "[{i}:v]crop=" + cam_crop + ",scale=1080:720,setsar=1[cam{i}];"
        "[{i}:v]crop=" + game_crop + ",scale=1080:1200,setsar=1[game{i}];"
        "[cam{i}][game{i}]vstack=inputs=2,fps=30,format=yuv420p,setpts=PTS-STARTPTS[v{i}]"
    )

    if len(partes_mp4) == 1:
        filter_complex = split_tpl.format(i=0)
        cmd = [
            ffmpeg_exe,
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-i",
            str(partes_mp4[0]),
            "-filter_complex",
            filter_complex,
            "-map",
            "[v0]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-crf",
            "19",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(salida_mp4),
        ]
        subprocess.run(cmd, check=True)
    else:
        # Unión limpia de 2 partes + etiqueta editorial blanca recta arriba (0deg) durante 3s en el salto
        t_salto = obtener_duracion_video(partes_mp4[0])
        t_fin_label = round(t_salto + 3.0, 2)
        inputs: list[str] = []
        filtros: list[str] = []
        concat_streams: list[str] = []
        for i, p in enumerate(partes_mp4):
            inputs.extend(["-i", str(p)])
            filtros.append(split_tpl.format(i=i))
            filtros.append(f"[{i}:a]asetpts=PTS-STARTPTS[a{i}]")
            concat_streams.append(f"[v{i}][a{i}]")

        filtros.append(
            f"{''.join(concat_streams)}concat=n={len(partes_mp4)}:v=1:a=1[vc][ac]"
        )

        if etiqueta_opcional:
            label_clean = _escapar_drawtext(etiqueta_opcional.upper())
            enable_expr = f"between(t\\,{t_salto:.2f}\\,{t_fin_label:.2f})"
            font_path = "C\\:/Windows/Fonts/arialbd.ttf"
            filtros.append(
                f"[vc]drawbox=x=110:y=130:w=860:h=105:color=white@1.0:t=fill:enable='{enable_expr}',"
                f"drawtext=fontfile='{font_path}':text='{label_clean}':fontcolor=#0B132B:fontsize=30:"
                f"x=(w-text_w)/2:y=130+(105-text_h)/2:enable='{enable_expr}'[vout]"
            )
            v_map = "[vout]"
        else:
            v_map = "[vc]"

        cmd = [
            ffmpeg_exe,
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
            *inputs,
            "-filter_complex",
            ";".join(filtros),
            "-map",
            v_map,
            "-map",
            "[ac]",
            "-c:v",
            "libx264",
            "-crf",
            "19",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(salida_mp4),
        ]
        subprocess.run(cmd, check=True)

    return obtener_duracion_video(salida_mp4)


def paso_3_descargar_y_renderizar(
    url: str,
    cam_crop: str = DEFAULT_CAM_CROP,
    game_crop: str = DEFAULT_GAME_CROP,
    forzar: bool = False,
) -> Path:
    """Descarga cada tramo en 1080p y renderiza todos los clips del plan en clips_gta6_ep1/listos/."""
    if not PLAN_JSON.is_file():
        raise FileNotFoundError(
            f"Falta {PLAN_JSON}. Ejecutá primero: python lote_gta6.py --paso 2"
        )

    plan: list[dict[str, Any]] = json.loads(PLAN_JSON.read_text(encoding="utf-8"))
    LISTOS_DIR.mkdir(parents=True, exist_ok=True)

    resumen_lines = [
        "RESUMEN DE SHORTS — GTA 6 EPISODIO 1",
        f"Fuente: {url}",
        "=" * 72,
        "",
    ]

    renderizados = 0
    for item in plan:
        clip_id = item["id"]
        partes = item.get("partes") or []
        if not partes:
            print(f"[Paso 3] [=] Saltando '{clip_id}' (sin timestamps definidos).")
            continue

        salida_mp4 = LISTOS_DIR / f"{clip_id}.mp4"
        if salida_mp4.is_file() and salida_mp4.stat().st_size > 100_000 and not forzar:
            dur = obtener_duracion_video(salida_mp4)
            print(f"[Paso 3] [=] {salida_mp4.name} ya existe ({dur:.1f}s).")
        else:
            partes_mp4: list[Path] = []
            for p_idx, parte in enumerate(partes):
                tramo_path = TRAMOS_DIR / f"{clip_id}_p{p_idx + 1}.mp4"
                descargar_tramo_1080p(
                    url, parte["inicio"], parte["fin"], tramo_path, forzar=forzar
                )
                partes_mp4.append(tramo_path)

            print(f"[Paso 3] Renderizando {salida_mp4.name} ({len(partes_mp4)} parte(s))...")
            dur = renderizar_clip_ffmpeg(
                partes_mp4=partes_mp4,
                salida_mp4=salida_mp4,
                etiqueta_opcional=item.get("etiqueta_opcional"),
                cam_crop=cam_crop,
                game_crop=game_crop,
            )
            print(f"  OK -> {salida_mp4} ({dur:.1f}s)")
        renderizados += 1

        resumen_lines.extend(
            [
                f"Archivo:   {salida_mp4.name}",
                f"Duración:  {dur:.1f}s",
                f"Categoría: {item.get('categoria', 'extra')}",
                f"Título YT: {item.get('titulo_youtube', '')}",
                "-" * 72,
            ]
        )

    RESUMEN_TXT.write_text("\n".join(resumen_lines) + "\n", encoding="utf-8")
    print(f"\n[Paso 3] Listos {renderizados} Shorts en {LISTOS_DIR}")
    print(f"[Paso 3] Resumen guardado en {RESUMEN_TXT}")
    return RESUMEN_TXT


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Pipeline rápido en lote (yt-dlp + faster-whisper + FFmpeg puro) para Shorts de GTA 6."
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="URL del VOD/directo de YouTube.")
    parser.add_argument(
        "--paso",
        type=int,
        choices=[1, 2, 3],
        default=None,
        help="Ejecuta un paso específico: 1 (audio+whisper), 2 (plan_clips.json), 3 (descarga 1080p+render).",
    )
    parser.add_argument("--todo", action="store_true", help="Ejecuta los pasos 1, 2 y 3 en secuencia.")
    parser.add_argument("--test-encuadre", action="store_true", help="Genera clips_gta6_ep1/test_encuadre.jpg.")
    parser.add_argument("--timestamp-test", default=None, help="Timestamp HH:MM:SS para test_encuadre.jpg.")
    parser.add_argument("--modelo", default="base", help="Modelo faster-whisper (default: base).")
    parser.add_argument("--beam-size", type=int, default=2, help="Beam size de faster-whisper (default: 2).")
    parser.add_argument("--cam-crop", default=DEFAULT_CAM_CROP, help="Crop webcam W:H:X:Y.")
    parser.add_argument("--game-crop", default=DEFAULT_GAME_CROP, help="Crop gameplay W:H:X:Y.")
    parser.add_argument("--forzar", action="store_true", help="Re-descarga / re-renderiza aunque ya exista.")
    args = parser.parse_args()

    if args.test_encuadre:
        generar_test_encuadre(
            args.url,
            cam_crop=args.cam_crop,
            game_crop=args.game_crop,
            timestamp_prueba=args.timestamp_test,
        )
        return

    if args.todo:
        paso_1_audio_y_transcripcion(
            args.url, modelo=args.modelo, beam_size=args.beam_size, forzar_whisper=args.forzar
        )
        paso_2_detectar_y_clasificar()
        generar_test_encuadre(args.url, cam_crop=args.cam_crop, game_crop=args.game_crop)
        paso_3_descargar_y_renderizar(
            args.url, cam_crop=args.cam_crop, game_crop=args.game_crop, forzar=args.forzar
        )
        return

    if args.paso == 1:
        paso_1_audio_y_transcripcion(
            args.url, modelo=args.modelo, beam_size=args.beam_size, forzar_whisper=args.forzar
        )
    elif args.paso == 2:
        paso_2_detectar_y_clasificar()
    elif args.paso == 3:
        paso_3_descargar_y_renderizar(
            args.url, cam_crop=args.cam_crop, game_crop=args.game_crop, forzar=args.forzar
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
