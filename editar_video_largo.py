#!/usr/bin/env python3
"""
Script independiente (separado del pipeline de Shorts) para editar videos largos
horizontales (16:9, 1920x1080) a partir de streams de 2 a 3 horas:

1. Formato limpio 16:9 (1920x1080) directo con Python + FFmpeg:
   - Sin Remotion, sin subtítulos, sin tarjetas superiores ni recortes verticales.
   - Codificación rápida de alta calidad: -c:v libx264 -crf 19 -preset fast -pix_fmt yuv420p.

2. Corte automático de tiempos muertos y farmeo repetitivo:
   - Soporta --inicio HH:MM:SS y --fin HH:MM:SS.
   - Combina `ffmpeg -af silencedetect` + análisis de transcripción (Whisper / VTT)
     para cortar silencios > 2.2s conservando 0.25s de margen antes y después de cada frase.
   - Detecta tramos repetitivos de farmeo con baja densidad de habla y ajusta el umbral
     dinámicamente para encajar en [--duracion-objetivo-min, --duracion-objetivo-max].
   - Aplica micro-fades de audio (`afade` de 0.03s) en cada corte para evitar chasquidos.

3. Música de fondo inteligente con Auto-Ducking (`musica/catalogo_musica.json`):
   - Alterna pistas de `chill_storytime`, `comedia_absurda` y `tension_accion`.
   - Aplica auto-ducking real en FFmpeg (`sidechaincompress`) con base suave (~ -24 dB)
     que baja automáticamente cuando Berlín o Milton hablan.
   - Aplica cortes en seco (`volume=0` por 1.5s) antes de remates/momentos graciosos.

4. Capítulos de YouTube (`capitulos.txt`):
   - Genera `capitulos.txt` junto al video con timestamps re-mapeados al tiempo editado.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional


PUNCHLINE_KEYWORDS = {
    "boludo",
    "pelotudo",
    "gordo",
    "mierda",
    "crasheo",
    "crasheó",
    "heladera",
    "cereal",
    "estafa",
    "gualicho",
    "gualichos",
    "hamburguesa",
    "alcantarilla",
    "maquina",
    "máquina",
    "gta",
    "deluxe",
    "cajeta",
    "pinche",
    "grito",
    "risas",
}

# Regla estricta: compras, mejoras de equipo/celda y negociaciones/ventas con el guardia
UPGRADE_PURCHASE_KEYWORDS = {
    "comprar",
    "compro",
    "compré",
    "compre",
    "comprate",
    "comprando",
    "mejora",
    "mejorar",
    "mejoré",
    "mejore",
    "vender",
    "vendo",
    "vendí",
    "vendi",
    "venta",
    "negocio",
    "pala",
    "cuchara",
    "sartén",
    "sarten",
    "mochila",
    "bolsa",
    "agrandar",
    "planta",
    "inodoro",
    "cafetera",
    "té",
    "brújula",
    "brujula",
    "linterna",
    "dinamita",
    "energía",
    "energia",
    "tienda",
    "catálogo",
    "catalogo",
    "papel",
    "plata",
    "precio",
    "caro",
    "barato",
    "monedas",
    "dólares",
    "dolares",
}

# Descubrimientos y sustos (cofres, llaves, casi descubierto)
DISCOVERY_SCARE_KEYWORDS = {
    "cofre",
    "ataúd",
    "ataud",
    "llave",
    "llaves",
    "puerta",
    "almacén",
    "almacen",
    "subterráneo",
    "subterraneo",
    "piso",
    "descubre",
    "descubrió",
    "descubrio",
    "esconder",
    "escondite",
    "segundos",
    "alarma",
    "tipeja",
    "guardia",
    "llegó",
    "llego",
    "viene",
    "grito",
}

# Humor, apuestas, debates absurdos y clímax de escape
HUMOR_CLIMAX_KEYWORDS = {
    "apostar",
    "apuesta",
    "apuesto",
    "casino",
    "timba",
    "cartas",
    "milton",
    "john",
    "cereal",
    "heladera",
    "gualicho",
    "gualichos",
    "hamburguesa",
    "alcantarilla",
    "alcantarillas",
    "escapar",
    "escapo",
    "escapé",
    "escape",
    "gta",
    "máquina",
    "maquina",
    "perdí",
    "perdi",
    "escalera",
    "cajeta",
}

# Relleno rutinario o chat sin progreso (se penaliza salvo que haya compra/hito en el bloque)
BORING_CHAT_KEYWORDS = {
    "suscrib",
    "suscriptor",
    "follow",
    "seguidor",
    "donación",
    "donacion",
    "saludo",
    "saludos",
    "alfombra",
    "discord",
    "directo",
    "stream",
}

CHAPTER_MILESTONES = [
    (
        0,
        360,
        ["inicio", "continúa", "apostar", "papel"],
        "Inicio en la prisión y apuestas en el patio",
    ),
    (
        360,
        960,
        ["cuchara", "luces", "guardia", "bebé", "pozo"],
        "Excavando el túnel a escondidas del guardia",
    ),
    (
        960,
        1400,
        ["planta", "gualicho", "gualichos", "hamburguesa", "milton"],
        "La planta anti-gualichos vs. La hamburguesa de Milton",
    ),
    (
        1400,
        2000,
        ["piso", "derecha", "forest", "túnel"],
        "Explorando el subsuelo y buscando la ruta correcta",
    ),
    (
        2000,
        2650,
        ["lindo", "compro", "objetos", "caro"],
        "Saqueando objetos y mejorando el equipo",
    ),
    (
        2650,
        3250,
        ["pala", "norte", "40 segundos", "grito"],
        "Conseguimos la pala y pánico a 40 segundos del guardia",
    ),
    (
        3250,
        3800,
        ["descubre", "cacoide", "cafetera"],
        "Inspección límite en la celda y trueques con los presos",
    ),
    (
        3800,
        4350,
        ["cereal", "heladera", "capo", "escalera"],
        "El debate del cereal en la heladera y recta final",
    ),
    (
        4350,
        5200,
        ["perdí", "john", "máquina", "gta 7", "chocar"],
        "Perdido en las alcantarillas y el gran escape final (GTA 7)",
    ),
]


def obtener_ruta_ffmpeg() -> str:
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        return ffmpeg_bin
    winget_path = (
        Path.home()
        / "AppData/Local/Microsoft/WinGet/Packages"
        / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
        / "ffmpeg-8.0.1-full_build/bin/ffmpeg.exe"
    )
    if winget_path.exists():
        return str(winget_path)
    raise FileNotFoundError("No se encontró 'ffmpeg' en el PATH.")


def obtener_ruta_ffprobe() -> str:
    ffprobe_bin = shutil.which("ffprobe")
    if ffprobe_bin:
        return ffprobe_bin
    ffmpeg_p = Path(obtener_ruta_ffmpeg())
    cand = ffmpeg_p.with_name("ffprobe.exe")
    if cand.exists():
        return str(cand)
    return "ffprobe"


def parse_hms(hms: Optional[str]) -> Optional[float]:
    if not hms:
        return None
    parts = [float(x) for x in hms.strip().split(":")]
    if len(parts) == 3:
        return parts[0] * 3600.0 + parts[1] * 60.0 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60.0 + parts[1]
    return parts[0]


def format_timestamp_youtube(seconds: float, force_hours: bool = False) -> str:
    sec = max(0, int(round(seconds)))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0 or force_hours:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def obtener_duracion_video(video_path: Path) -> float:
    ffprobe_bin = obtener_ruta_ffprobe()
    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return round(float(res.stdout.strip()), 3)


def detectar_silencios_ffmpeg(
    video_path: Path,
    noise_db: float = -34.0,
    min_silence_sec: float = 1.2,
    start_sec: Optional[float] = None,
    end_sec: Optional[float] = None,
) -> list[tuple[float, float]]:
    """
    Ejecuta `ffmpeg -af silencedetect` para obtener los intervalos de silencio (start, end)
    relativos al inicio del tramo analizado (0 .. duracion).
    """
    ffmpeg_bin = obtener_ruta_ffmpeg()
    cmd = [ffmpeg_bin, "-hide_banner", "-nostats"]
    if start_sec is not None and start_sec > 0:
        cmd += ["-ss", f"{start_sec:.3f}"]
    if end_sec is not None and end_sec > 0:
        cmd += ["-to", f"{end_sec:.3f}"]
    cmd += [
        "-i",
        str(video_path),
        "-vn",
        "-af",
        f"silencedetect=noise={noise_db:.1f}dB:d={min_silence_sec:.2f}",
        "-f",
        "null",
        "-",
    ]
    print(
        f"[1/5] Analizando silencios con FFmpeg (silencedetect={noise_db}dB, min={min_silence_sec}s)..."
    )
    res = subprocess.run(cmd, capture_output=True, text=True)
    log = res.stderr

    starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)", log)]

    silencios: list[tuple[float, float]] = []
    for i, st in enumerate(starts):
        en = ends[i] if i < len(ends) else st + min_silence_sec
        if en > st:
            silencios.append((st, en))
    print(f"      Detectados {len(silencios)} intervalos de silencio base.")
    return silencios


def cargar_transcripcion_cues(
    base_dir: Path,
    video_path: Path,
    vtt_path: Optional[Path],
    vtt_offset_sec: float = 0.0,
    clip_duration: float = 0.0,
    usar_whisper_fallback: bool = False,
) -> list[dict[str, Any]]:
    """
    Carga segmentos de voz [{start, end, text}] desde un archivo .vtt/.json o con Whisper
    para medir densidad de habla, detectar tramos de farmeo repetitivo, remates y capítulos.
    """
    cues: list[dict[str, Any]] = []
    cand_vtt = vtt_path
    if cand_vtt is None:
        default_vtt = base_dir / "clips-procesados" / "vod_1u0iEWIddiM.es.vtt"
        if default_vtt.is_file():
            cand_vtt = default_vtt

    if cand_vtt and cand_vtt.is_file():
        if cand_vtt.suffix.lower() == ".json":
            raw = json.loads(cand_vtt.read_text(encoding="utf-8"))
            items = raw if isinstance(raw, list) else raw.get("segments", raw.get("subtitles", []))
            for it in items:
                st = float(it.get("start", 0.0)) - vtt_offset_sec
                en = float(it.get("end", st)) - vtt_offset_sec
                txt = str(it.get("text") or it.get("word") or "").strip()
                if 0.0 <= st <= clip_duration and txt:
                    cues.append({"start": max(0.0, st), "end": min(clip_duration, en), "text": txt})
        else:
            txt_vtt = cand_vtt.read_text(encoding="utf-8", errors="ignore")
            blocks = txt_vtt.split("\n\n")
            last_text = ""
            for b in blocks:
                m = re.search(
                    r"(\d\d:\d\d:\d\d\.\d+)\s*-->\s*(\d\d:\d\d:\d\d\.\d+)", b
                )
                if not m:
                    continue
                s_abs = parse_hms(m.group(1)) or 0.0
                e_abs = parse_hms(m.group(2)) or s_abs
                st = s_abs - vtt_offset_sec
                en = e_abs - vtt_offset_sec
                if en <= 0.0 or st >= clip_duration or en - st < 0.08:
                    continue
                lines = [
                    re.sub(r"<[^>]+>", "", l).strip()
                    for l in b.splitlines()[1:]
                    if "-->" not in l and l.strip()
                ]
                clean = " ".join(lines).replace("&nbsp;", " ").strip()
                if not clean or clean == last_text:
                    continue
                last_text = clean
                cues.append(
                    {
                        "start": round(max(0.0, st), 3),
                        "end": round(min(clip_duration, en), 3),
                        "text": clean,
                    }
                )
        print(f"      Cargados {len(cues)} bloques de transcripción desde '{cand_vtt.name}'.")
        return cues

    if usar_whisper_fallback:
        print("      [Whisper] Transcribiendo audio con modelo 'base'...")
        import whisper

        model = whisper.load_model("base")
        res = model.transcribe(str(video_path), language="es", fp16=False)
        for seg in res.get("segments", []):
            cues.append(
                {
                    "start": round(float(seg["start"]), 3),
                    "end": round(float(seg["end"]), 3),
                    "text": str(seg.get("text", "")).strip(),
                }
            )
    return cues


def detectar_pausas_habla_vtt(
    cues: list[dict[str, Any]],
    duracion_total: float,
    min_gap_sec: float = 1.6,
) -> list[tuple[float, float]]:
    """Complementa silencedetect usando huecos sin diálogo en la transcripción."""
    if not cues:
        return []
    ordenadas = sorted(cues, key=lambda c: float(c["start"]))
    gaps: list[tuple[float, float]] = []
    cur_end = 0.0
    for c in ordenadas:
        st = float(c["start"])
        en = float(c["end"])
        if st - cur_end >= min_gap_sec:
            gaps.append((cur_end, st))
        cur_end = max(cur_end, en)
    if duracion_total - cur_end >= min_gap_sec:
        gaps.append((cur_end, duracion_total))
    return gaps


def construir_segmentos_activos(
    duracion_total: float,
    silencios_base: list[tuple[float, float]],
    cues: list[dict[str, Any]],
    min_silence_cut: float = 2.2,
    margen: float = 0.25,
    min_seg_dur: float = 0.8,
) -> list[dict[str, Any]]:
    """
    Combina silencios de FFmpeg + pausas de transcripción para recortar baches > min_silence_cut
    conservando `margen` (0.25s) y puntuando cada bloque narrativo.
    Marca `protegido=True` en todo bloque con compras, mejoras, ventas al guardia,
    descubrimientos, sustos, apuestas, humor o el escape final.
    """
    gaps_vtt = detectar_pausas_habla_vtt(cues, duracion_total, min_gap_sec=min_silence_cut + margen * 2.0)
    todos_silencios = sorted(silencios_base + gaps_vtt, key=lambda x: x[0])

    # Unir intervalos solapados
    silencios_unidos: list[tuple[float, float]] = []
    for st, en in todos_silencios:
        if silencios_unidos and st <= silencios_unidos[-1][1] + 0.15:
            silencios_unidos[-1] = (silencios_unidos[-1][0], max(silencios_unidos[-1][1], en))
        else:
            silencios_unidos.append((st, en))

    cortes_silencio: list[tuple[float, float]] = []
    for s_st, s_en in silencios_unidos:
        eff_st = s_st + margen
        eff_en = s_en - margen
        if eff_en - eff_st >= min_silence_cut:
            cortes_silencio.append((max(0.0, eff_st), min(duracion_total, eff_en)))

    # Invertir cortes_silencio para obtener los segmentos activos conservados
    activos: list[tuple[float, float]] = []
    cursor = 0.0
    for c_st, c_en in cortes_silencio:
        if c_st > cursor:
            activos.append((cursor, c_st))
        cursor = max(cursor, c_en)
    if cursor < duracion_total:
        activos.append((cursor, duracion_total))

    # Fusionar segmentos muy cercanos (< 0.35s) y descartar micro-fragmentos sueltos
    fusionados: list[tuple[float, float]] = []
    for st, en in activos:
        if en - st < min_seg_dur:
            continue
        if fusionados and st - fusionados[-1][1] < 0.35:
            fusionados[-1] = (fusionados[-1][0], en)
        else:
            fusionados.append((st, en))

    # Subdividir bloques largos (> 26s) en pausas naturales (>= 0.70s) para aislar
    # limpiamente cada compra/hito de los tramos aburridos de excavación
    pausas_vtt_cortas = detectar_pausas_habla_vtt(cues, duracion_total, min_gap_sec=0.85)
    silencios_cortos = sorted(
        [
            (s_st + 0.15, s_en - 0.15)
            for s_st, s_en in (silencios_base + pausas_vtt_cortas)
            if (s_en - s_st) >= 0.75
        ],
        key=lambda x: x[0],
    )
    bloques: list[tuple[float, float]] = []
    for st, en in fusionados:
        if en - st <= 26.0:
            bloques.append((st, en))
            continue
        cur = st
        for sc_st, sc_en in silencios_cortos:
            if sc_st <= cur + 12.0:
                continue
            if sc_en >= en - 8.0:
                break
            bloques.append((cur, sc_st))
            cur = sc_en
        # Si todavía queda un bloque > 38s sin pausas, dividir en sub-bloques de ~22s
        while en - cur > 38.0:
            bloques.append((cur, cur + 22.0))
            cur += 22.0
        if en - cur >= min_seg_dur:
            bloques.append((cur, en))

    # Puntuar cada bloque cruzando con la transcripción
    resultado: list[dict[str, Any]] = []
    for st, en in bloques:
        dur = round(en - st, 3)
        if dur < min_seg_dur:
            continue
        textos_bloque: list[str] = []
        for c in cues:
            if c["end"] > st and c["start"] < en:
                textos_bloque.append(c["text"])
        texto_unido = " ".join(textos_bloque)
        low_txt = texto_unido.lower()
        palabras = re.findall(r"\w+", low_txt)
        wps = len(palabras) / max(1.0, dur)

        hits_compra = sum(1 for w in palabras if w in UPGRADE_PURCHASE_KEYWORDS)
        hits_desc = sum(1 for w in palabras if w in DISCOVERY_SCARE_KEYWORDS)
        hits_humor = sum(1 for w in palabras if w in HUMOR_CLIMAX_KEYWORDS)
        hits_relleno = sum(1 for w in palabras if any(w.startswith(b) for b in BORING_CHAT_KEYWORDS))
        exclam = texto_unido.count("!") + texto_unido.count("?") + texto_unido.count("[")

        es_inicio_o_climax = st < 95.0 or en > duracion_total - 260.0
        protegido = bool(
            es_inicio_o_climax
            or hits_compra >= 1
            or hits_desc >= 2
            or hits_humor >= 2
            or ("[risas]" in low_txt or "[grito]" in low_txt)
        )

        # Penalizar tramos rutinarios de chat/alfombra/inodoro sin compras ni descubrimientos
        penalizacion = hits_relleno * 2.5 if (hits_compra == 0 and hits_desc == 0) else 0.0
        score = (
            wps * 2.0
            + hits_compra * 6.0
            + hits_desc * 4.0
            + hits_humor * 3.5
            + exclam * 1.1
            + (15.0 if es_inicio_o_climax else 0.0)
            - penalizacion
        )
        resultado.append(
            {
                "start": round(st, 3),
                "end": round(en, 3),
                "duration": dur,
                "score": round(score, 3),
                "wps": round(wps, 2),
                "protegido": protegido,
                "text": texto_unido[:240],
            }
        )
    return resultado


def ajustar_segmentos_a_duracion_objetivo(
    duracion_total: float,
    silencios_base: list[tuple[float, float]],
    cues: list[dict[str, Any]],
    umbral_silencio_inicial: float,
    margen_inicial: float,
    min_minutos: float,
    max_minutos: float,
) -> list[dict[str, Any]]:
    """
    Ajusta dinámicamente el umbral de silencio y poda los tramos de excavación/relleno
    de menor score, protegiendo estrictamente compras, mejoras, descubrimientos, sustos,
    apuestas, humor y el escape final.
    """
    min_sec = min_minutos * 60.0
    max_sec = max_minutos * 60.0
    target_mid = (min_sec + max_sec) / 2.0

    segmentos = construir_segmentos_activos(
        duracion_total,
        silencios_base,
        cues,
        min_silence_cut=umbral_silencio_inicial,
        margen=margen_inicial,
    )
    suma_actual = sum(s["duration"] for s in segmentos)
    print(
        f"[2/5] Duración inicial tras cortar silencios >={umbral_silencio_inicial}s (margen {margen_inicial}s): {suma_actual/60.0:.2f} min ({len(segmentos)} bloques)"
    )

    if suma_actual > max_sec:
        for cand_umbral in [1.8, 1.5, 1.25]:
            if cand_umbral >= umbral_silencio_inicial:
                continue
            cand_segs = construir_segmentos_activos(
                duracion_total,
                silencios_base,
                cues,
                min_silence_cut=cand_umbral,
                margen=max(0.20, margen_inicial - 0.03),
            )
            cand_sum = sum(s["duration"] for s in cand_segs)
            segmentos = cand_segs
            suma_actual = cand_sum
            print(
                f"      -> Ajuste dinámico de umbral a {cand_umbral}s: {suma_actual/60.0:.2f} min ({len(segmentos)} bloques)"
            )
            if suma_actual <= max_sec:
                break

    # Primero podar únicamente bloques NO protegidos (excavación aburrida / chat relleno)
    if suma_actual > max_sec:
        orden_no_protegidos = sorted(
            [i for i, s in enumerate(segmentos) if not s.get("protegido")],
            key=lambda idx: (segmentos[idx]["score"], segmentos[idx]["wps"]),
        )
        descartar: set[int] = set()
        for idx in orden_no_protegidos:
            if suma_actual <= target_mid:
                break
            descartar.add(idx)
            suma_actual -= segmentos[idx]["duration"]

        # Si aún supera max_sec (ej. demasiados bloques protegidos), podar los de menor score
        if suma_actual > max_sec:
            orden_restantes = sorted(
                [
                    i
                    for i in range(len(segmentos))
                    if i not in descartar and i != 0 and i < len(segmentos) - 3
                ],
                key=lambda idx: (segmentos[idx]["score"], segmentos[idx]["wps"]),
            )
            for idx in orden_restantes:
                if suma_actual <= max_sec - 30.0:
                    break
                descartar.add(idx)
                suma_actual -= segmentos[idx]["duration"]

        segmentos = [s for idx, s in enumerate(segmentos) if idx not in descartar]
        protegidos_kept = sum(1 for s in segmentos if s.get("protegido"))
        print(
            f"      -> Poda de {len(descartar)} tramos de relleno/excavación: {suma_actual/60.0:.2f} min ({len(segmentos)} bloques, {protegidos_kept} hitos protegidos)"
        )

    elif suma_actual < min_sec and duracion_total >= min_sec:
        for cand_umbral in [2.8, 3.5, 4.5, 6.0]:
            cand_segs = construir_segmentos_activos(
                duracion_total,
                silencios_base,
                cues,
                min_silence_cut=cand_umbral,
                margen=min(0.40, margen_inicial + 0.08),
            )
            cand_sum = sum(s["duration"] for s in cand_segs)
            segmentos = cand_segs
            suma_actual = cand_sum
            if suma_actual >= min_sec:
                break

    # Compactar segmentos contiguos que hayan quedado a < 0.25s para evitar micro-cortes
    compactados: list[dict[str, Any]] = []
    for seg in segmentos:
        if compactados and seg["start"] - compactados[-1]["end"] <= 0.25:
            prev = compactados[-1]
            prev["end"] = seg["end"]
            prev["duration"] = round(prev["end"] - prev["start"], 3)
            prev["text"] = (prev["text"] + " " + seg["text"]).strip()[:300]
            prev["score"] = round(max(prev["score"], seg["score"]), 3)
            prev["protegido"] = bool(prev.get("protegido") or seg.get("protegido"))
        else:
            compactados.append(dict(seg))

    total_final = sum(s["duration"] for s in compactados)
    print(
        f"      Resultado selección: {len(compactados)} bloques activos | Duración editada: {total_final/60.0:.2f} min ({total_final:.1f}s)"
    )
    return compactados


def _renderizar_segmento_ffmpeg(
    ffmpeg_bin: str,
    input_video: Path,
    seg_idx: int,
    seg: dict[str, Any],
    temp_dir: Path,
) -> Path:
    """
    Renderiza un segmento individual en 1920x1080 (16:9) con -c:v libx264 -crf 19 -preset fast
    y micro-fades de audio de 0.03s (afade) al inicio y al final para evitar chasquidos.
    Usa búsqueda rápida (-ss antes de -i) con un único decodificador por proceso.
    """
    out_seg = temp_dir / f"seg_{seg_idx:04d}.mp4"
    st = seg["start"]
    en = seg["end"]
    dur = max(0.1, round(en - st, 3))
    fade_out_st = max(0.03, round(dur - 0.03, 3))

    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-nostats",
        "-y",
        "-ss",
        f"{st:.3f}",
        "-to",
        f"{en:.3f}",
        "-i",
        str(input_video),
        "-vf",
        "scale=1920:1080,setsar=1,fps=30,format=yuv420p",
        "-af",
        f"aformat=sample_rates=48000:channel_layouts=stereo,afade=t=in:st=0:d=0.03,afade=t=out:st={fade_out_st:.3f}:d=0.03",
        "-c:v",
        "libx264",
        "-crf",
        "19",
        "-preset",
        "fast",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "30",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-threads",
        "3",
        str(out_seg),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(
            f"Error en segmento FFmpeg {seg_idx} ({st}-{en}s):\n{res.stderr[-800:]}"
        )
    return out_seg


def ensamblar_video_cortado(
    input_video: Path,
    segmentos: list[dict[str, Any]],
    temp_dir: Path,
    max_workers: int = 4,
) -> Path:
    """
    Ensambla todos los segmentos activos en un archivo MP4 1920x1080 limpio
    procesando en paralelo y concatenándolos con `-c copy`.
    """
    ffmpeg_bin = obtener_ruta_ffmpeg()
    total_segs = len(segmentos)
    print(
        f"[3/5] Codificando {total_segs} segmentos en paralelo (1920x1080, libx264 crf=19 preset=fast, afade=0.03s)..."
    )

    t0 = time.perf_counter()
    resultados: dict[int, Path] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futuros = {
            pool.submit(
                _renderizar_segmento_ffmpeg, ffmpeg_bin, input_video, idx, seg, temp_dir
            ): idx
            for idx, seg in enumerate(segmentos)
        }
        completados = 0
        paso_log = max(1, total_segs // 10)
        for fut in as_completed(futuros):
            idx = futuros[fut]
            resultados[idx] = fut.result()
            completados += 1
            if completados % paso_log == 0 or completados == total_segs:
                elapsed = time.perf_counter() - t0
                print(
                    f"      Progreso segmentos: {completados}/{total_segs} completados ({elapsed:.1f}s)"
                )

    segs_ordenados = [resultados[i] for i in range(total_segs)]
    concat_list = temp_dir / "segs_concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in segs_ordenados),
        encoding="utf-8",
    )

    video_sin_musica = temp_dir / "video_cortado_sin_musica.mp4"
    subprocess.run(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-nostats",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(video_sin_musica),
        ],
        check=True,
        capture_output=True,
    )
    for p in segs_ordenados:
        p.unlink(missing_ok=True)
    return video_sin_musica


def remapear_tiempo_a_editado(
    t_orig: float, segmentos: list[dict[str, Any]]
) -> Optional[float]:
    """Convierte un timestamp del video original al nuevo timestamp en el video editado."""
    acum = 0.0
    for seg in segmentos:
        if seg["start"] <= t_orig <= seg["end"]:
            return round(acum + (t_orig - seg["start"]), 3)
        if t_orig < seg["start"]:
            return round(acum, 3)
        acum += seg["duration"]
    return round(acum, 3)


def detectar_cortes_secos_musica(
    cues: list[dict[str, Any]],
    segmentos: list[dict[str, Any]],
    duracion_editada: float,
    separacion_min_sec: float = 95.0,
) -> list[tuple[float, float]]:
    """
    Detecta momentos graciosos o remates en la transcripción re-mapeada al tiempo editado
    para hacer cortes en seco de la música (`volume=0` por 1.5s, 0.15s antes del remate).
    """
    candidatos: list[tuple[float, float, str]] = []
    for c in cues:
        txt = str(c.get("text", "")).strip()
        low = txt.lower()
        palabras = re.findall(r"\w+", low)
        hits = [w for w in palabras if w in PUNCHLINE_KEYWORDS]
        if not hits and "!" not in txt and "[grito]" not in low and "[risas]" not in low:
            continue
        # Verificar que caiga dentro de algún segmento conservado
        en_segmento = any(s["start"] <= c["start"] <= s["end"] for s in segmentos)
        if not en_segmento:
            continue
        t_edit = remapear_tiempo_a_editado(c["start"], segmentos)
        if t_edit is None or t_edit < 15.0 or t_edit > duracion_editada - 10.0:
            continue
        score = len(hits) * 2.0 + (1.5 if "!" in txt or "[grito]" in low else 0.0)
        candidatos.append((t_edit, score, txt[:50]))

    seleccionados: list[tuple[float, float]] = []
    ultimo_t = -999.0
    for t_edit, score, _ in sorted(candidatos, key=lambda x: x[0]):
        if score < 2.0:
            continue
        if t_edit - ultimo_t >= separacion_min_sec:
            st_cut = max(0.0, round(t_edit - 0.15, 2))
            en_cut = min(duracion_editada, round(st_cut + 1.5, 2))
            seleccionados.append((st_cut, en_cut))
            ultimo_t = t_edit
    return seleccionados


def mezclar_musica_con_autoducking(
    base_dir: Path,
    video_cortado: Path,
    output_video: Path,
    cues: list[dict[str, Any]],
    segmentos: list[dict[str, Any]],
    temp_dir: Path,
) -> None:
    """
    Construye una pista musical continua alternando canciones de `musica/catalogo_musica.json`
    (`chill_storytime`, `comedia_absurda`, `tension_accion`), aplica los cortes en seco (`volume=0`
    por 1.5s) antes de los remates y mezcla con la voz usando `sidechaincompress` (~ -24 dB base
    + auto-ducking cuando hablan Berlín o Milton).
    """
    ffmpeg_bin = obtener_ruta_ffmpeg()
    duracion_editada = obtener_duracion_video(video_cortado)
    catalogo_path = base_dir / "musica" / "catalogo_musica.json"
    catalogo = json.loads(catalogo_path.read_text(encoding="utf-8"))

    categorias_validas = {"chill_storytime", "comedia_absurda", "tension_accion"}
    por_cat: dict[str, list[dict[str, Any]]] = {c: [] for c in categorias_validas}
    for tr in catalogo.get("tracks", []):
        if tr.get("excludeFromAutoBgm"):
            continue
        cat = tr.get("category")
        f_path = base_dir / "musica" / str(tr.get("file", ""))
        if cat in categorias_validas and f_path.is_file() and float(tr.get("durationSeconds", 0)) >= 60.0:
            por_cat[cat].append(tr)

    # Orden de rotación para mantener variedad durante los 45-60 minutos
    ciclo_cats = ["chill_storytime", "comedia_absurda", "tension_accion", "comedia_absurda"]
    indices_cat = {c: 0 for c in categorias_validas}
    playlist: list[Path] = []
    acum_musica = 0.0
    paso = 0
    while acum_musica < duracion_editada + 60.0:
        cat = ciclo_cats[paso % len(ciclo_cats)]
        lista = por_cat.get(cat) or []
        if not lista:
            paso += 1
            continue
        tr = lista[indices_cat[cat] % len(lista)]
        indices_cat[cat] += 1
        paso += 1
        p_file = base_dir / "musica" / str(tr["file"])
        playlist.append(p_file)
        acum_musica += float(tr.get("durationSeconds", 180.0))

    print(
        f"[4/5] Preparando banda sonora ({len(playlist)} pistas alternadas de chill_storytime / comedia_absurda / tension_accion)..."
    )

    cortes_secos = detectar_cortes_secos_musica(cues, segmentos, duracion_editada)
    print(
        f"      Aplicando Auto-Ducking (`sidechaincompress` @ -24 dB) + {len(cortes_secos)} cortes en seco (1.5s) en remates..."
    )

    # Construir filtros de cortes en seco (volume=0 durante 1.5s) sobre la música
    vol_cuts_filters: list[str] = []
    for st_c, en_c in cortes_secos:
        vol_cuts_filters.append(f"volume=enable='between(t,{st_c:.2f},{en_c:.2f})':volume=0")
    cadena_cortes = ("," + ",".join(vol_cuts_filters)) if vol_cuts_filters else ""

    # Normalizar y concatenar todas las pistas MP3 por filtro de audio (inmune a distintos sample rates o carátulas ID3)
    bgm_norm_lines: list[str] = []
    bgm_labels: list[str] = []
    for idx_m in range(len(playlist)):
        in_idx = idx_m + 1
        bgm_norm_lines.append(
            f"[{in_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[m{idx_m}];"
        )
        bgm_labels.append(f"[m{idx_m}]")
    bgm_concat_filter = (
        "".join(bgm_norm_lines)
        + f"{''.join(bgm_labels)}concat=n={len(playlist)}:v=0:a=1[bgm_joined];"
    )

    # Filtro de mezcla con sidechaincompress real:
    # - [0:a] es la voz del stream (se divide con asplit en [voice_main] y [voice_sc] para disparar el compresor)
    # - [bgm_joined] es la playlist de música a -21dB (~ -24dB integrados), recortada a duracion_editada y con cortes secos
    # - sidechaincompress reduce la música automáticamente cada vez que Berlín o Milton hablan
    fade_out_bgm = max(1.0, round(duracion_editada - 2.5, 2))
    filter_ducking = (
        bgm_concat_filter
        + f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[voice_main][voice_sc];"
        + f"[bgm_joined]atrim=0:{duracion_editada:.3f},asetpts=PTS-STARTPTS,"
        + f"volume=-21dB,afade=t=in:st=0:d=1.5,afade=t=out:st={fade_out_bgm:.2f}:d=2.5{cadena_cortes}[bgm_pre];"
        + f"[bgm_pre][voice_sc]sidechaincompress=threshold=0.018:ratio=5:attack=25:release=350:makeup=1[bgm_ducked];"
        + f"[voice_main][bgm_ducked]amix=inputs=2:duration=first:dropout_transition=0:weights='1 1'[outa]"
    )
    filter_duck_file = temp_dir / "filter_ducking.txt"
    filter_duck_file.write_text(filter_ducking, encoding="utf-8")

    output_video.parent.mkdir(parents=True, exist_ok=True)
    cmd_mix = [
        ffmpeg_bin,
        "-hide_banner",
        "-nostats",
        "-y",
        "-i",
        str(video_cortado),
    ]
    for p_file in playlist:
        cmd_mix += ["-i", str(p_file)]
    cmd_mix += [
        "-filter_complex",
        filter_ducking,
        "-map",
        "0:v:0",
        "-map",
        "[outa]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-shortest",
        str(output_video),
    ]
    res = subprocess.run(cmd_mix, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(
            f"Error aplicando auto-ducking y mezcla musical:\n{res.stderr[-800:]}"
        )


def generar_capitulos_youtube(
    cues: list[dict[str, Any]],
    segmentos: list[dict[str, Any]],
    output_video: Path,
    capitulos_salida: Optional[Path] = None,
    parte2_info: Optional[tuple[list[dict[str, Any]], list[dict[str, Any]], float]] = None,
) -> Path:
    """
    Genera `capitulos.txt` (y/o la ruta indicada en `--capitulos-salida`) junto al video final
    con los timestamps ajustados al nuevo tiempo editado (empezando en `00:00` para YouTube).
    Soporta una o dos partes unidas.
    """
    dur_p1 = sum(s["duration"] for s in segmentos)
    dur_p2 = sum(s["duration"] for s in parte2_info[1]) if parte2_info else 0.0
    duracion_editada = dur_p1 + dur_p2
    usar_horas = duracion_editada >= 3600.0

    lineas: list[tuple[float, str]] = []
    if parte2_info is not None:
        p1_milestones = [
            (0, 420, ["arranco", "empezar", "excavar", "guardia"], "Parte 1: Primer día en prisión y primeras excavaciones"),
            (480, 1200, ["misión", "cartas", "vender", "guardia"], "Misiones con los presos, apuestas y primeras ventas"),
            (1300, 2600, ["plata", "compro", "mejor", "poco"], "Negociando mejoras y juntando dinero bajo tierra"),
            (2800, 3800, ["pala", "sartén", "mochila", "agrandar", "almuerzo"], "Comprando la pala, sartén y ampliando la mochila"),
            (3800, 4600, ["inodoro", "dormir", "discord"], "El inodoro nuevo de lujo y fin de la Parte 1"),
        ]
        lineas.append((0.0, p1_milestones[0][3]))
        for r_st, r_en, kws, tit in p1_milestones[1:]:
            mejor_t = next(
                (c["start"] for c in cues if r_st <= c["start"] <= r_en and any(k in c["text"].lower() for k in kws)),
                (r_st + r_en) / 2.0,
            )
            t_ed = remapear_tiempo_a_editado(mejor_t, segmentos) or 0.0
            if t_ed > lineas[-1][0] + 90.0 and t_ed < dur_p1 - 30.0:
                lineas.append((t_ed, tit))

        cues2, segs2, _ = parte2_info
        lineas.append((dur_p1, "Parte 2: Regreso a la celda y apuestas en el patio"))
        for idx, (r_st, r_en, keywords, titulo) in enumerate(CHAPTER_MILESTONES):
            if idx == 0:
                continue
            mejor_t2 = next(
                (c["start"] for c in cues2 if r_st <= c["start"] <= r_en and any(k in c["text"].lower() for k in keywords)),
                (r_st + r_en) / 2.0,
            )
            t_ed2 = dur_p1 + (remapear_tiempo_a_editado(mejor_t2, segs2) or 0.0)
            if t_ed2 > lineas[-1][0] + 90.0 and t_ed2 < duracion_editada - 45.0:
                lineas.append((t_ed2, titulo))
    else:
        lineas.append((0.0, "Inicio: Llegada a la prisión y apuestas"))
        for idx, (r_st, r_en, keywords, titulo) in enumerate(CHAPTER_MILESTONES):
            if idx == 0:
                continue
            mejor_t_orig: Optional[float] = None
            for c in cues:
                if r_st <= c["start"] <= r_en:
                    low = c["text"].lower()
                    if any(k in low for k in keywords):
                        mejor_t_orig = c["start"]
                        break
            if mejor_t_orig is None:
                mejor_t_orig = (r_st + r_en) / 2.0
            t_edit = remapear_tiempo_a_editado(mejor_t_orig, segmentos) or 0.0
            if t_edit > lineas[-1][0] + 90.0 and t_edit < duracion_editada - 45.0:
                lineas.append((t_edit, titulo))

    texto_cap = "\n".join(
        f"{format_timestamp_youtube(t, force_hours=usar_horas)} {titulo}"
        for t, titulo in lineas
    ) + "\n"

    cap_path = capitulos_salida if capitulos_salida else (output_video.parent / "capitulos.txt")
    cap_named_path = output_video.with_name(f"{output_video.stem}_capitulos.txt")
    cap_path.write_text(texto_cap, encoding="utf-8")
    if cap_named_path != cap_path:
        cap_named_path.write_text(texto_cap, encoding="utf-8")
    print(f"[5/5] Capítulos de YouTube guardados en '{cap_path}':")
    for l in texto_cap.strip().splitlines():
        print(f"      {l}")
    return cap_path


def _resolver_tramo_entrada(
    entrada: str,
    inicio: Optional[str],
    fin: Optional[str],
    entrada_dir: Path,
    temp_dir: Path,
    tag: str,
) -> tuple[Path, float, float]:
    """Resuelve la fuente local/URL, aplica recorte si hace falta y devuelve (working_video, dur_tramo, offset_vtt)."""
    if entrada.startswith(("http://", "https://")):
        out_raw = entrada_dir / f"stream_largo_{tag}_raw.mp4"
        cmd_dl = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-check-certificates",
            "-N",
            "8",
            "-f",
            "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]",
            "--merge-output-format",
            "mp4",
        ]
        if inicio and fin:
            cmd_dl += ["--download-sections", f"*{inicio}-{fin}"]
        cmd_dl += ["-o", str(out_raw), entrada]
        subprocess.run(cmd_dl, check=True)
        input_path = out_raw
        ya_recortado = True
    else:
        input_path = Path(entrada)
        if not input_path.is_file():
            input_path = entrada_dir / entrada
        if not input_path.is_file():
            raise FileNotFoundError(f"No se encontró el archivo de entrada: {input_path}")
        ya_recortado = False

    dur_archivo = obtener_duracion_video(input_path)
    ini_sec = parse_hms(inicio)
    fin_sec = parse_hms(fin)

    if (
        not ya_recortado
        and ini_sec is not None
        and fin_sec is not None
        and abs(dur_archivo - (fin_sec - ini_sec)) <= 35.0
    ):
        ya_recortado = True

    if not ya_recortado and (ini_sec is not None or fin_sec is not None):
        recorte_path = temp_dir / f"tramo_{tag}_recortado.mp4"
        cmd_cut = [obtener_ruta_ffmpeg(), "-hide_banner", "-nostats", "-y"]
        if ini_sec is not None:
            cmd_cut += ["-ss", f"{ini_sec:.3f}"]
        if fin_sec is not None:
            cmd_cut += ["-to", f"{fin_sec:.3f}"]
        cmd_cut += ["-i", str(input_path), "-c", "copy", str(recorte_path)]
        subprocess.run(cmd_cut, check=True)
        working_video = recorte_path
        dur_tramo = obtener_duracion_video(working_video)
    else:
        working_video = input_path
        dur_tramo = dur_archivo

    offset_vtt = ini_sec if ini_sec is not None else 0.0
    return working_video, dur_tramo, offset_vtt


def unir_con_fundido_negro(
    video1: Path,
    video2: Path,
    salida_unida: Path,
    duracion_fundido: float = 0.6,
) -> Path:
    """Une dos partes aplicando un fundido a negro limpio (0.3s out + 0.3s in = 0.6s)."""
    ffmpeg_bin = obtener_ruta_ffmpeg()
    half = round(duracion_fundido / 2.0, 3)
    dur1 = obtener_duracion_video(video1)
    st_out = max(0.1, round(dur1 - half, 3))

    v1_faded = salida_unida.parent / "parte1_fade.mp4"
    v2_faded = salida_unida.parent / "parte2_fade.mp4"

    subprocess.run(
        [
            ffmpeg_bin, "-hide_banner", "-nostats", "-y", "-i", str(video1),
            "-vf", f"fade=t=out:st={st_out:.3f}:d={half:.3f}",
            "-af", f"afade=t=out:st={st_out:.3f}:d={half:.3f}",
            "-c:v", "libx264", "-crf", "19", "-preset", "fast", "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            str(v1_faded),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            ffmpeg_bin, "-hide_banner", "-nostats", "-y", "-i", str(video2),
            "-vf", f"fade=t=in:st=0:d={half:.3f}",
            "-af", f"afade=t=in:st=0:d={half:.3f}",
            "-c:v", "libx264", "-crf", "19", "-preset", "fast", "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            str(v2_faded),
        ],
        check=True,
        capture_output=True,
    )
    concat_f = salida_unida.parent / "partes_concat.txt"
    concat_f.write_text(
        f"file '{v1_faded.as_posix()}'\nfile '{v2_faded.as_posix()}'\n",
        encoding="utf-8",
    )
    subprocess.run(
        [ffmpeg_bin, "-hide_banner", "-nostats", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_f), "-c", "copy", str(salida_unida)],
        check=True,
        capture_output=True,
    )
    v1_faded.unlink(missing_ok=True)
    v2_faded.unlink(missing_ok=True)
    return salida_unida


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Edita videos largos horizontales (16:9, 1920x1080) cortando silencios/farmeo, agregando música con auto-ducking y generando capítulos de YouTube."
    )
    parser.add_argument(
        "entrada",
        help="Ruta al video de entrada (ej. clips-entrada/directito_s3_prision_raw.mp4) o URL de YouTube/Twitch/Kick.",
    )
    parser.add_argument(
        "--inicio",
        default=None,
        help="Tiempo inicial HH:MM:SS en el stream/video original (ej. 00:31:30).",
    )
    parser.add_argument(
        "--fin",
        default=None,
        help="Tiempo final HH:MM:SS en el stream/video original (ej. 01:53:20).",
    )
    parser.add_argument(
        "-o",
        "--salida",
        default=None,
        help="Ruta del archivo MP4 final (default: videos-largos/<nombre>_editado.mp4).",
    )
    parser.add_argument(
        "--duracion-objetivo-min",
        type=float,
        default=45.0,
        help="Duración mínima objetivo en minutos (default: 45).",
    )
    parser.add_argument(
        "--duracion-objetivo-max",
        type=float,
        default=90.0,
        help="Duración máxima objetivo en minutos (default: 90).",
    )
    parser.add_argument(
        "--umbral-silencio",
        type=float,
        default=2.2,
        help="Umbral base de silencio a recortar en segundos (default: 2.2).",
    )
    parser.add_argument(
        "--margen",
        type=float,
        default=0.25,
        help="Margen en segundos antes y después de cada frase hablada (default: 0.25).",
    )
    parser.add_argument(
        "--db-silencio",
        type=float,
        default=-34.0,
        help="Umbral en dB para silencedetect en FFmpeg (default: -34.0).",
    )
    parser.add_argument(
        "--vtt",
        default=None,
        help="Ruta opcional a subtítulos .vtt o transcripción .json del directo.",
    )
    parser.add_argument(
        "--offset-vtt",
        type=float,
        default=None,
        help="Offset en segundos del archivo de video respecto al VTT del directo completo.",
    )
    parser.add_argument(
        "--parte2",
        default=None,
        help="Segunda parte opcional (archivo o URL) para unir en orden con fundido a negro.",
    )
    parser.add_argument("--inicio2", default=None, help="Inicio HH:MM:SS de la Parte 2.")
    parser.add_argument("--fin2", default=None, help="Fin HH:MM:SS de la Parte 2.")
    parser.add_argument("--vtt2", default=None, help="Subtítulos .vtt/.json de la Parte 2.")
    parser.add_argument(
        "--transicion-negro",
        type=float,
        default=0.6,
        help="Duración del fundido a negro entre Parte 1 y Parte 2 en segundos (default: 0.6).",
    )
    parser.add_argument(
        "--capitulos-salida",
        default=None,
        help="Ruta personalizada para guardar el archivo de capítulos (ej. videos-largos/capitulos_escape_prision.txt).",
    )

    args = parser.parse_args()
    base_dir = Path(__file__).resolve().parent
    entrada_dir = base_dir / "clips-entrada"
    salida_dir = base_dir / "videos-largos"
    temp_dir = base_dir / "clips-procesados" / "temp_video_largo"
    salida_dir.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    t_global = time.perf_counter()

    working_video1, dur_tramo1, off1 = _resolver_tramo_entrada(
        args.entrada, args.inicio, args.fin, entrada_dir, temp_dir, "p1"
    )
    offset_vtt1 = args.offset_vtt if args.offset_vtt is not None else off1
    output_path = (
        Path(args.salida)
        if args.salida
        else (salida_dir / f"{working_video1.stem.replace('_raw', '')}_editado.mp4")
    )
    cap_out_path = Path(args.capitulos_salida) if args.capitulos_salida else None

    if args.parte2:
        working_video2, dur_tramo2, off2 = _resolver_tramo_entrada(
            args.parte2, args.inicio2, args.fin2, entrada_dir, temp_dir, "p2"
        )
        prop1 = dur_tramo1 / max(1.0, dur_tramo1 + dur_tramo2)
        prop2 = 1.0 - prop1
        min1, max1 = args.duracion_objetivo_min * prop1, args.duracion_objetivo_max * prop1
        min2, max2 = args.duracion_objetivo_min * prop2, args.duracion_objetivo_max * prop2

        print(
            f"=== Editando Video Largo Unido 16:9 (1920x1080) ===\n"
            f"    Parte 1: {working_video1.name} ({dur_tramo1/60.0:.2f} min -> objetivo {min1:.1f}-{max1:.1f} min)\n"
            f"    Parte 2: {working_video2.name} ({dur_tramo2/60.0:.2f} min -> objetivo {min2:.1f}-{max2:.1f} min)\n"
            f"    Salida: {output_path}"
        )

        sil1 = detectar_silencios_ffmpeg(working_video1, noise_db=args.db_silencio, min_silence_sec=1.0)
        cues1 = cargar_transcripcion_cues(
            base_dir=base_dir,
            video_path=working_video1,
            vtt_path=Path(args.vtt) if args.vtt else None,
            vtt_offset_sec=offset_vtt1,
            clip_duration=dur_tramo1,
        )
        segs1 = ajustar_segmentos_a_duracion_objetivo(
            duracion_total=dur_tramo1,
            silencios_base=sil1,
            cues=cues1,
            umbral_silencio_inicial=args.umbral_silencio,
            margen_inicial=args.margen,
            min_minutos=min1,
            max_minutos=max1,
        )

        sil2 = detectar_silencios_ffmpeg(working_video2, noise_db=args.db_silencio, min_silence_sec=1.0)
        cues2 = cargar_transcripcion_cues(
            base_dir=base_dir,
            video_path=working_video2,
            vtt_path=Path(args.vtt2) if args.vtt2 else None,
            vtt_offset_sec=off2,
            clip_duration=dur_tramo2,
        )
        segs2 = ajustar_segmentos_a_duracion_objetivo(
            duracion_total=dur_tramo2,
            silencios_base=sil2,
            cues=cues2,
            umbral_silencio_inicial=args.umbral_silencio,
            margen_inicial=args.margen,
            min_minutos=min2,
            max_minutos=max2,
        )

        temp_p1 = temp_dir / "p1"
        temp_p2 = temp_dir / "p2"
        temp_p1.mkdir(parents=True, exist_ok=True)
        temp_p2.mkdir(parents=True, exist_ok=True)
        vid1_cut = ensamblar_video_cortado(working_video1, segs1, temp_p1)
        vid2_cut = ensamblar_video_cortado(working_video2, segs2, temp_p2)

        video_cortado = unir_con_fundido_negro(
            vid1_cut, vid2_cut, temp_dir / "unido_sin_musica.mp4", duracion_fundido=args.transicion_negro
        )
        vid1_cut.unlink(missing_ok=True)
        vid2_cut.unlink(missing_ok=True)

        dur_p1_edit = sum(s["duration"] for s in segs1)
        cues_comb = list(cues1) + [
            {"start": c["start"] + dur_tramo1, "end": c["end"] + dur_tramo1, "text": c["text"]}
            for c in cues2
        ]
        segs_comb = list(segs1) + [
            {**s, "start": s["start"] + dur_tramo1, "end": s["end"] + dur_tramo1}
            for s in segs2
        ]

        mezclar_musica_con_autoducking(
            base_dir=base_dir,
            video_cortado=video_cortado,
            output_video=output_path,
            cues=cues_comb,
            segmentos=segs_comb,
            temp_dir=temp_dir,
        )
        cap_path = generar_capitulos_youtube(
            cues=cues1,
            segmentos=segs1,
            output_video=output_path,
            capitulos_salida=cap_out_path,
            parte2_info=(cues2, segs2, dur_p1_edit),
        )
    else:
        print(
            f"=== Editando Video Largo 16:9 (1920x1080) ===\n"
            f"    Fuente: {working_video1.name} ({dur_tramo1/60.0:.2f} min)\n"
            f"    Rango objetivo: {args.duracion_objetivo_min:.0f} a {args.duracion_objetivo_max:.0f} min\n"
            f"    Salida: {output_path}"
        )

        silencios = detectar_silencios_ffmpeg(
            working_video1,
            noise_db=args.db_silencio,
            min_silence_sec=1.0,
        )
        cues = cargar_transcripcion_cues(
            base_dir=base_dir,
            video_path=working_video1,
            vtt_path=Path(args.vtt) if args.vtt else None,
            vtt_offset_sec=offset_vtt1,
            clip_duration=dur_tramo1,
        )
        segmentos = ajustar_segmentos_a_duracion_objetivo(
            duracion_total=dur_tramo1,
            silencios_base=silencios,
            cues=cues,
            umbral_silencio_inicial=args.umbral_silencio,
            margen_inicial=args.margen,
            min_minutos=args.duracion_objetivo_min,
            max_minutos=args.duracion_objetivo_max,
        )
        video_cortado = ensamblar_video_cortado(
            input_video=working_video1,
            segmentos=segmentos,
            temp_dir=temp_dir,
        )
        mezclar_musica_con_autoducking(
            base_dir=base_dir,
            video_cortado=video_cortado,
            output_video=output_path,
            cues=cues,
            segmentos=segmentos,
            temp_dir=temp_dir,
        )
        cap_path = generar_capitulos_youtube(
            cues=cues,
            segmentos=segmentos,
            output_video=output_path,
            capitulos_salida=cap_out_path,
        )

    shutil.rmtree(temp_dir, ignore_errors=True)
    dur_final = obtener_duracion_video(output_path)
    t_total = (time.perf_counter() - t_global) / 60.0
    print(
        f"\n[COMPLETADO] Video largo exportado en: {output_path}\n"
        f"             Duración final: {dur_final/60.0:.2f} min ({format_timestamp_youtube(dur_final, force_hours=True)})\n"
        f"             Capítulos YouTube: {cap_path}\n"
        f"             Tiempo total de proceso: {t_total:.2f} min"
    )


if __name__ == "__main__":
    main()
