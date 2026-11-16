#!/usr/bin/env python3
"""
Script de automatización para transformar clips 16:9 en Shorts 9:16 (1080x1920 @ 30fps),
eliminar silencios automáticamente ("jump cuts") con auto-editor, detectar cambios dinámicos
de escena (ej. de gameplay+webcam a fullcam) y extraer subtítulos palabra por palabra con Whisper.

Modos de uso:
  1. Detectar escenas (y eliminar silencios):
     python procesar_clip.py <archivo> --detectar-escenas

  2. Procesar por segmentos dinámicos:
     python procesar_clip.py <archivo> --segmentos '[{"start":0,"end":14.2,"modo":"gameplay","coords":[0,0,480,270]},{"start":14.2,"end":24.6,"modo":"fullcam"}]' --sync-remotion

  3. Procesar clip de escena única (clásico):
     python procesar_clip.py <archivo> [x y w h] --modo {gameplay,fullcam} --sync-remotion
"""

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

VENTANA_AUDIO_SEG = 1.0
AUDIO_SAMPLE_RATE = 16000
SILENCIO_DB = -60.0


def obtener_ruta_ffmpeg() -> str:
    """Busca ffmpeg en el PATH o en la ruta de instalación de WinGet."""
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        return ffmpeg_bin

    winget_pkgs = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    if winget_pkgs.exists():
        matches = list(winget_pkgs.rglob("ffmpeg.exe"))
        if matches:
            return str(matches[0])

    raise FileNotFoundError(
        "No se encontró 'ffmpeg'. Asegurate de que esté instalado y en el PATH."
    )


def obtener_ruta_ffprobe() -> str:
    """Busca ffprobe en el PATH o junto al binario de ffmpeg."""
    ffprobe_bin = shutil.which("ffprobe")
    if ffprobe_bin:
        return ffprobe_bin

    ffmpeg_path = Path(obtener_ruta_ffmpeg())
    candidate = ffmpeg_path.with_name("ffprobe.exe")
    if candidate.exists():
        return str(candidate)

    raise FileNotFoundError("No se encontró 'ffprobe'.")


def obtener_ruta_auto_editor() -> str:
    """Busca auto-editor en el PATH o en el directorio Scripts de Python."""
    ae_bin = shutil.which("auto-editor")
    if ae_bin:
        return ae_bin

    scripts_dir = Path(sys.executable).resolve().parent / "Scripts"
    for candidate in ("auto-editor.exe", "auto-editor"):
        candidate_path = scripts_dir / candidate
        if candidate_path.exists():
            return str(candidate_path)

    raise FileNotFoundError(
        "No se encontró 'auto-editor'. Instalalo con: pip install auto-editor"
    )


def obtener_duracion_video(video_path: Path) -> float:
    """Obtiene la duración exacta del video en segundos usando ffprobe."""
    ffprobe_exe = obtener_ruta_ffprobe()
    cmd = [
        ffprobe_exe,
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


def extraer_frame_en_tiempo(
    input_path: Path, preview_path: Path, timestamp: float = 0.0
) -> None:
    """Extrae un frame del video en el segundo indicado y lo guarda como JPG."""
    ffmpeg_exe = obtener_ruta_ffmpeg()
    cmd = [
        ffmpeg_exe,
        "-y",
        "-ss",
        f"{max(0.0, timestamp):.3f}",
        "-i",
        str(input_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        "-update",
        "1",
        str(preview_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def eliminar_silencios_auto_editor(input_path: Path, output_path: Path) -> Path:
    """
    Ejecuta auto-editor sobre el clip de entrada para eliminar silencios mayores a 0.3s
    con un margen de 0.15s, exportando clips-procesados/sin_silencio_temp.mp4 a 30fps.
    """
    auto_editor_exe = obtener_ruta_auto_editor()
    cmd = [
        auto_editor_exe,
        str(input_path),
        "--margin",
        "0.15sec",
        "--edit",
        "audio:threshold=4%,mincut=0.3sec",
        "--frame-rate",
        "30",
        "--video-codec",
        "h264",
        "--audio-codec",
        "aac",
        "--no-open",
        "-o",
        str(output_path),
    ]

    print(
        f"[Auto-Editor] Eliminando silencios (>0.3s, margin 0.15s) -> '{output_path}' (30fps)..."
    )
    subprocess.run(cmd, check=True)
    print(f"              Video sin silencios guardado en: {output_path}")
    return output_path


def detectar_escenas_ffmpeg(
    video_path: Path,
    procesados_dir: Path,
    threshold: float = 0.35,
    min_segment_duration: float = 1.5,
) -> list[dict[str, Any]]:
    """
    Usa FFmpeg (select='gt(scene,threshold)',showinfo) sobre el video sin silencios
    para detectar cortes de escena, filtra segmentos menores a min_segment_duration (1.5s),
    extrae 1 imagen por escena (escena_0.jpg, escena_1.jpg, ...) y guarda escenas.json.
    """
    ffmpeg_exe = obtener_ruta_ffmpeg()
    duracion_total = obtener_duracion_video(video_path)

    print(
        f"[Escenas] Analizando cambios de escena en '{video_path.name}' (duración: {duracion_total}s, threshold={threshold})..."
    )
    cmd = [
        ffmpeg_exe,
        "-i",
        str(video_path),
        "-vf",
        f"select='gt(scene,{threshold})',showinfo",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    stderr_text = proc.stderr or ""

    # Extraer todos los pts_time reportados por showinfo
    raw_cuts: list[float] = []
    for match in re.finditer(r"pts_time:([0-9]+(?:\.[0-9]+)?)", stderr_text):
        t = round(float(match.group(1)), 2)
        raw_cuts.append(t)

    # Filtrar cortes para que cada segmento dure al menos min_segment_duration (1.5s)
    valid_cuts = [0.0]
    for t in raw_cuts:
        if t - valid_cuts[-1] >= min_segment_duration and (duracion_total - t) >= min_segment_duration:
            valid_cuts.append(t)
    valid_cuts.append(duracion_total)

    # Limpiar imágenes escena_*.jpg anteriores
    for old_img in procesados_dir.glob("escena_*.jpg"):
        try:
            old_img.unlink()
        except OSError:
            pass

    escenas: list[dict[str, Any]] = []
    for idx in range(len(valid_cuts) - 1):
        start_t = round(valid_cuts[idx], 2)
        end_t = round(valid_cuts[idx + 1], 2)
        mid_t = round(start_t + min(0.5, (end_t - start_t) / 2.0), 2)
        img_name = f"escena_{idx}.jpg"
        img_path = procesados_dir / img_name
        extraer_frame_en_tiempo(video_path, img_path, timestamp=mid_t)

        escena_info = {
            "index": idx,
            "start": start_t,
            "end": end_t,
            "duration": round(end_t - start_t, 2),
            "preview": f"clips-procesados/{img_name}",
        }
        escenas.append(escena_info)

    # También guardar preview.jpg con la primera escena por compatibilidad
    if escenas:
        shutil.copy2(procesados_dir / "escena_0.jpg", procesados_dir / "preview.jpg")

    escenas_json_path = procesados_dir / "escenas.json"
    escenas_json_path.write_text(
        json.dumps(
            {
                "video": str(video_path),
                "totalDuration": duracion_total,
                "scenes": escenas,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"[Escenas] Se detectaron {len(escenas)} segmento(s):")
    for esc in escenas:
        print(
            f"  - Escena {esc['index']}: {esc['start']}s -> {esc['end']}s ({esc['duration']}s) | Preview: {esc['preview']}"
        )
    return escenas


def construir_filter_complex(
    modo: str,
    x: Optional[int] = None,
    y: Optional[int] = None,
    w: Optional[int] = None,
    h: Optional[int] = None,
) -> str:
    """Devuelve la cadena filter_complex de FFmpeg para 'gameplay' o 'fullcam' a 1080x1920 @ 30fps."""
    if modo == "gameplay":
        if None in (x, y, w, h):
            raise ValueError(
                "Para el modo 'gameplay' debés especificar las coordenadas [x, y, w, h] de la cámara."
            )
        return (
            f"[0:v]crop={w}:{h}:{x}:{y},"
            f"scale=1080:640:force_original_aspect_ratio=increase,"
            f"crop=1080:640,setsar=1[cam];"
            f"[0:v]scale=1080:1280:force_original_aspect_ratio=increase,"
            f"crop=1080:1280,setsar=1[game];"
            f"[cam][game]vstack=inputs=2,fps=30,format=yuv420p[v]"
        )
    elif modo == "fullcam":
        if None not in (x, y, w, h):
            src_crop = f"crop={w}:{h}:{x}:{y},"
            return (
                f"[0:v]{src_crop}scale=1080:1920:force_original_aspect_ratio=increase,"
                f"crop=1080:1920,boxblur=40:5,setsar=1[bg];"
                f"[0:v]{src_crop}scale=1080:-2,setsar=1[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps=30,format=yuv420p[v]"
            )
        return (
            f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,boxblur=40:5,setsar=1[bg];"
            f"[0:v]scale=-2:1350:force_original_aspect_ratio=increase,"
            f"crop=1080:min(ih\\,1920),setsar=1[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps=30,format=yuv420p[v]"
        )
    else:
        raise ValueError(f"Modo desconocido: {modo}")


def procesar_video_ffmpeg(
    input_path: Path,
    output_path: Path,
    modo: str,
    x: Optional[int] = None,
    y: Optional[int] = None,
    w: Optional[int] = None,
    h: Optional[int] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
) -> None:
    """Procesa un video completo o un tramo [start_time, end_time] al formato 1080x1920 @ 30fps."""
    ffmpeg_exe = obtener_ruta_ffmpeg()
    filter_complex = construir_filter_complex(modo, x, y, w, h)

    cmd = [ffmpeg_exe, "-y"]
    if start_time is not None:
        cmd.extend(["-ss", f"{start_time:.3f}"])
    if end_time is not None:
        cmd.extend(["-to", f"{end_time:.3f}"])

    cmd.extend(
        [
            "-i",
            str(input_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(output_path),
        ]
    )

    subprocess.run(cmd, check=True)


def procesar_por_segmentos(
    input_path: Path,
    output_path: Path,
    segmentos: list[dict[str, Any]],
    procesados_dir: Path,
) -> None:
    """
    Recorta cada segmento de input_path, le aplica su modo ('gameplay' o 'fullcam')
    y concatena todos los tramos en output_path (clips-procesados/vertical_temp.mp4).
    """
    ffmpeg_exe = obtener_ruta_ffmpeg()

    if len(segmentos) == 1:
        seg = segmentos[0]
        modo = seg.get("modo", "fullcam")
        coords = seg.get("coords") or [None, None, None, None]
        print(
            f"[Segmento único] Procesando ({seg.get('start', 0)}s -> {seg.get('end')}s) en modo '{modo}'..."
        )
        procesar_video_ffmpeg(
            input_path,
            output_path,
            modo=modo,
            x=coords[0],
            y=coords[1],
            w=coords[2],
            h=coords[3],
            start_time=seg.get("start"),
            end_time=seg.get("end"),
        )
        return

    archivos_tramos: list[Path] = []
    for idx, seg in enumerate(segmentos):
        modo = seg.get("modo", "fullcam")
        coords = seg.get("coords") or [None, None, None, None]
        start_t = float(seg.get("start", 0.0))
        end_t = float(seg["end"]) if seg.get("end") is not None else None
        tramo_path = procesados_dir / f"seg_temp_{idx}.mp4"

        print(
            f"  [Segmento {idx + 1}/{len(segmentos)}] {start_t}s -> {end_t}s | modo={modo} | coords={coords if modo == 'gameplay' else 'N/A'}"
        )
        procesar_video_ffmpeg(
            input_path,
            tramo_path,
            modo=modo,
            x=coords[0],
            y=coords[1],
            w=coords[2],
            h=coords[3],
            start_time=start_t,
            end_time=end_t,
        )
        archivos_tramos.append(tramo_path)

    # Crear archivo de lista para concat demuxer
    concat_list_path = procesados_dir / "concat_list.txt"
    lines = [f"file '{p.resolve().as_posix()}'" for p in archivos_tramos]
    concat_list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[Concat] Uniendo {len(archivos_tramos)} segmentos en '{output_path}'...")
    cmd_concat = [
        ffmpeg_exe,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list_path),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-r",
        "30",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output_path),
    ]
    subprocess.run(cmd_concat, check=True)

    # Limpiar temporales de segmentos
    for p in archivos_tramos:
        try:
            p.unlink()
        except OSError:
            pass
    try:
        concat_list_path.unlink()
    except OSError:
        pass

    print(f"         Video multicámara concatenado en: {output_path}")


def transcribir_whisper(
    video_path: Path, json_output_path: Path, model_name: str = "base"
) -> list[dict]:
    """
    Ejecuta OpenAI Whisper en español con word_timestamps=True y guarda los tiempos
    palabra por palabra en clips-procesados/transcripcion.json.
    """
    import whisper

    print(f"[Whisper] Cargando modelo '{model_name}' y transcribiendo en español...")
    model = whisper.load_model(model_name)
    result = model.transcribe(
        str(video_path),
        language="es",
        word_timestamps=True,
        verbose=False,
    )

    palabras = []
    for segment in result.get("segments", []):
        for w_info in segment.get("words", []):
            word_text = w_info.get("word", "").strip()
            if not word_text:
                continue
            palabras.append(
                {
                    "word": word_text,
                    "start": round(float(w_info.get("start", 0.0)), 3),
                    "end": round(float(w_info.get("end", 0.0)), 3),
                    "highlight": len(word_text) >= 7 or word_text.isupper(),
                }
            )

    payload = {
        "text": result.get("text", "").strip(),
        "language": "es",
        "words": palabras,
        "segments": result.get("segments", []),
    }

    json_output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"          Transcripción palabra por palabra guardada en: {json_output_path}")
    return palabras


def parsear_argumento_segmentos(raw_segmentos: str) -> list[dict[str, Any]]:
    """Permite recibir un JSON directo o la ruta a un archivo .json con la lista de segmentos."""
    posible_archivo = Path(raw_segmentos)
    if posible_archivo.is_file():
        contenido = posible_archivo.read_text(encoding="utf-8")
        return json.loads(contenido)
    return json.loads(raw_segmentos)


CATEGORY_SIGNALS: dict[str, list[str]] = {
    "comedia_absurda": [
        "lentes",
        "roto",
        "rotos",
        "remera",
        "crotera",
        "croto",
        "pantalón",
        "maleducada",
        "ofrecerse",
        "ombligo",
        "cuánto es",
        "dos por seis",
        "2x6",
        "tabla",
        "multiplicar",
        "crasheo",
        "crasheó",
        "karma",
        "broma",
        "chiste",
        "risa",
        "ridículo",
        "payaso",
        "vergüenza",
        "troleo",
        "agujero",
        "laburo",
    ],
    "tension_accion": [
        "moto",
        "choque",
        "chocar",
        "chocó",
        "tiroteo",
        "disparo",
        "matar",
        "maté",
        "mataste",
        "morir",
        "muere",
        "mueren",
        "peligro",
        "baneo",
        "ban",
        "correr",
        "huir",
        "escapar",
        "policía",
        "bomba",
        "explosión",
        "susto",
        "miedo",
        "cuidado",
        "persecución",
    ],
    "chill_storytime": [
        "gta 6",
        "rumores",
        "vice city",
        "liberty city",
        "new york",
        "miami",
        "recorrer",
        "mapa",
        "prólogo",
        "directo",
        "episodios",
        "cooperativo",
        "charla",
        "chat",
        "historia",
        "planes",
        "primer día",
        "noticia",
        "habla",
    ],
    "epica_climax": [
        "ganamos",
        "victoria",
        "récord",
        "épico",
        "logramos",
        "campeón",
        "mejor jugada",
        "leyenda",
        "imposible",
        "salvada",
        "triunfo",
        "festejo",
    ],
}

IMPACT_CUT_WORDS: set[str] = {
    "pelotudo",
    "pelotuda",
    "boludo",
    "boluda",
    "gordo",
    "gorda",
    "mierda",
    "crasheo",
    "crasheó",
    "heladera",
    "estafa",
    "antena",
    "maquina",
    "máquina",
    "tarado",
    "idiota",
    "forro",
    "imbecil",
    "imbécil",
    "capo",
    "payaso",
    "ridiculo",
    "ridículo",
    "crotera",
    "croto",
    "maleducada",
    "maleducado",
    "choco",
    "chocó",
    "mataste",
    "mate",
    "maté",
    "moriste",
    "baneo",
    "baneado",
    "domado",
    "verguenza",
    "vergüenza",
    "desastre",
    "mentira",
    "nooo",
    "cago",
    "cagó",
    "carajo",
    "puta",
}

DEADPAN_CUT_PHRASES: list[str] = [
    "muestra su cara",
    "estoy en peligro",
    "me voy a la",
    "lo mataste",
    "muy bien te felicito",
    "te felicito",
    "deci algo directo",
    "decí algo directo",
    "ya esta tomada",
    "ya está tomada",
    "impactar tu audiencia",
    "lo que dijo la ia",
    "es lo que hay",
    "no hay problema",
    "que le digo",
    "qué le digo",
    "que carajo",
    "qué carajo",
]


def _normalizar_token(texto: str) -> str:
    return re.sub(r"[^\wáéíóúüñ]", "", texto.lower())


def clasificar_intensidad(sobre_promedio_db: float) -> str:
    """Clasifica cuánto sobresale un pico respecto del promedio del clip."""
    if sobre_promedio_db >= 10:
        return "muy_alta"
    if sobre_promedio_db >= 6:
        return "alta"
    if sobre_promedio_db >= 3:
        return "media"
    return "baja"


def medir_rms_por_ventana(
    video_path: Path,
    ventana_seg: float = VENTANA_AUDIO_SEG,
    sample_rate: int = AUDIO_SAMPLE_RATE,
) -> list[tuple[float, float]]:
    """
    Devuelve una lista de (segundo, rms_db) por ventanas de `ventana_seg` usando FFmpeg astats.
    """
    ffmpeg_exe = obtener_ruta_ffmpeg()
    muestras_por_ventana = int(sample_rate * ventana_seg)
    filtro = (
        f"aresample={sample_rate},"
        f"asetnsamples=n={muestras_por_ventana}:p=0,"
        "astats=metadata=1:reset=1,"
        "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-"
    )
    cmd = [
        ffmpeg_exe,
        "-hide_banner",
        "-nostats",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-af",
        filtro,
        "-f",
        "null",
        "-",
    ]
    res = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"FFmpeg falló al analizar el audio de '{video_path.name}':\n{res.stderr[-1500:]}"
        )

    ventanas: list[tuple[float, float]] = []
    segundo_actual: float | None = None
    for linea in res.stdout.splitlines():
        match_tiempo = re.search(r"pts_time:([\d.]+)", linea)
        if match_tiempo:
            segundo_actual = float(match_tiempo.group(1))
            continue
        if "RMS_level=" in linea and segundo_actual is not None:
            valor = linea.split("=", 1)[1].strip()
            try:
                db = float(valor)
            except ValueError:
                db = float("-inf")
            ventanas.append((segundo_actual, db))
            segundo_actual = None
    return ventanas


def detectar_picos_audio(
    ventanas: list[tuple[float, float]],
    segmentos: list[dict[str, Any]],
    palabras: list[dict[str, Any]],
    max_picos: int = 6,
    separacion_min: float = 2.0,
    ventana_seg: float = VENTANA_AUDIO_SEG,
) -> tuple[float | None, list[dict[str, Any]]]:
    """
    Calcula el volumen promedio del clip (ignorando silencios) y devuelve los `max_picos`
    momentos más fuertes separados al menos `separacion_min` segundos entre sí.
    """
    con_sonido = [
        (seg, db) for seg, db in ventanas if math.isfinite(db) and db > SILENCIO_DB
    ]
    if not con_sonido:
        return None, []

    promedio_db = sum(db for _, db in con_sonido) / len(con_sonido)

    elegidos: list[tuple[float, float]] = []
    for seg, db in sorted(con_sonido, key=lambda item: item[1], reverse=True):
        if all(abs(seg - otro) >= separacion_min for otro, _ in elegidos):
            elegidos.append((seg, db))
        if len(elegidos) >= max_picos:
            break

    picos: list[dict[str, Any]] = []
    for seg, db in sorted(elegidos, key=lambda item: item[0]):
        sobre = db - promedio_db
        if palabras:
            texto_cercano = " ".join(
                str(w.get("word", ""))
                for w in palabras
                if float(w.get("start", 0.0)) <= seg + ventana_seg + 0.5
                and float(w.get("end", 0.0)) >= seg - 0.5
            ).strip()
        else:
            centro = seg + ventana_seg / 2
            texto_cercano = " ".join(
                str(s.get("text", ""))
                for s in segmentos
                if float(s.get("start", 0.0)) <= centro + 1.5
                and float(s.get("end", 0.0)) >= centro - 1.5
            ).strip()
        picos.append(
            {
                "segundo": round(seg, 2),
                "db": round(db, 1),
                "sobre_promedio_db": round(sobre, 1),
                "intensidad": clasificar_intensidad(sobre),
                "texto_cercano": texto_cercano,
            }
        )
    return round(promedio_db, 1), picos


def _calcular_rango_corte_frase(
    palabras: list[dict[str, Any]],
    idx: int,
    duracion_total: float,
    lead_in: float = 0.15,
    min_dur: float = 1.2,
    max_dur: float = 2.2,
) -> tuple[float, float]:
    """
    Calcula [cut_start, cut_end] empezando `lead_in` (0.15s) antes de la palabra clave
    y manteniendo el silencio entre `min_dur` (1.2s) y `max_dur` (2.2s) según dure la frase.
    """
    t_trigger = float(palabras[idx].get("start", 0.0))
    cut_start = round(max(0.0, t_trigger - lead_in), 2)
    phrase_end = float(palabras[idx].get("end", t_trigger + 0.3))

    n = len(palabras)
    for j in range(idx, min(n, idx + 8)):
        w_end = float(palabras[j].get("end", phrase_end))
        if (w_end - cut_start) > max_dur:
            break
        phrase_end = w_end
        word_raw = str(palabras[j].get("word", "")).strip()
        if word_raw.endswith((".", "!")):
            break
        if word_raw.endswith("?"):
            # Si sigue una respuesta seca corta dentro del presupuesto max_dur, incluirla
            can_extend_reply = False
            if j + 1 < n:
                gap_reply = float(palabras[j + 1].get("start", w_end)) - w_end
                if gap_reply <= 0.45:
                    for k in range(j + 1, min(n, j + 5)):
                        k_end = float(palabras[k].get("end", w_end))
                        if (k_end - cut_start) > max_dur:
                            break
                        if str(palabras[k].get("word", "")).strip().endswith((".", "!")):
                            can_extend_reply = True
                            break
            if not can_extend_reply:
                break
        if j + 1 < n:
            next_start = float(palabras[j + 1].get("start", w_end))
            if (next_start - w_end) >= 0.35 and (phrase_end - cut_start) >= min_dur:
                break

    duracion_corte = max(min_dur, min(max_dur, (phrase_end - cut_start) + 0.08))
    cut_end = round(min(duracion_total, cut_start + duracion_corte), 2)
    return cut_start, cut_end


def _inicio_oracion_reciente(palabras: list[dict[str, Any]], idx: int, max_back: int = 3) -> int:
    """Si la palabra de impacto está al inicio de una cláusula/respuesta corta, retrocede hasta 3 palabras."""
    cur = idx
    for steps in range(1, max_back + 1):
        prev_idx = idx - steps
        if prev_idx < 0:
            break
        prev_word = str(palabras[prev_idx].get("word", "")).strip()
        if prev_word.endswith((".", "!", "?")):
            break
        cur_start = float(palabras[cur].get("start", 0.0))
        prev_end = float(palabras[prev_idx].get("end", 0.0))
        if (cur_start - prev_end) >= 0.30:
            break
        cur = prev_idx
    return cur


def detectar_cortes_remate(
    palabras: list[dict[str, Any]],
    duracion_total: float,
    picos_audio: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Analiza timestamps de Whisper y picos de voz para detectar entre 2 y 4 cortes
    estratégicos en seco (`volume = 0`), iniciando `0.15s` antes de la palabra/frase clave
    y sosteniendo el silencio entre `1.2s` y `2.2s`.
    """
    candidatos: list[dict[str, Any]] = []
    picos_altos = [
        p
        for p in (picos_audio or [])
        if p.get("intensidad") in {"alta", "muy_alta"}
        or float(p.get("sobre_promedio_db", 0.0)) >= 4.0
    ]

    def _cerca_de_pico(t: float) -> float:
        mejor = 0.0
        for p in picos_altos:
            seg = float(p.get("segundo", -99.0))
            if t - 0.8 <= seg <= t + 0.4:
                sobre = float(p.get("sobre_promedio_db", 0.0))
                if sobre > mejor:
                    mejor = sobre
        return mejor

    if palabras:
        n = len(palabras)
        for i, w in enumerate(palabras):
            raw = str(w.get("word", "")).strip()
            tok = _normalizar_token(raw)
            t_start = float(w.get("start", 0.0))
            if t_start < 4.5 or t_start > max(4.5, duracion_total - 0.9):
                continue

            ventana_txt = " ".join(
                re.sub(r"[¡!¿?,.;:\"'()]", "", str(palabras[j].get("word", "")).lower())
                for j in range(i, min(n, i + 5))
            )

            score = 0.0
            reason = ""
            target_idx = i

            if tok in IMPACT_CUT_WORDS:
                score = 12.0 + _cerca_de_pico(t_start) * 0.5
                reason = f"impacto:{raw}"
            elif any(ventana_txt.startswith(phr) for phr in DEADPAN_CUT_PHRASES):
                target_idx = _inicio_oracion_reciente(palabras, i, max_back=3)
                t_eff = float(palabras[target_idx].get("start", t_start))
                score = 10.5 + _cerca_de_pico(t_eff) * 0.4
                reason = f"remate:{ventana_txt[:28]}"
            else:
                sobre_pico = _cerca_de_pico(t_start)
                is_hl = bool(w.get("highlight"))
                is_exclam_or_turn = raw.endswith(("!", "?")) or raw.isupper()
                if is_hl and (is_exclam_or_turn or sobre_pico >= 4.0):
                    # Retroceder al inicio de la frase corta si es el remate de una pregunta/grito
                    target_idx = _inicio_oracion_reciente(palabras, i, max_back=3)
                    score = 7.0 + sobre_pico * 0.6 + (1.5 if raw.endswith("!") else 0.5)
                    reason = f"enfasis:{raw}"

            if score > 0.0:
                cut_start, cut_end = _calcular_rango_corte_frase(
                    palabras, target_idx, duracion_total
                )
                if cut_start >= 4.0 and (cut_end - cut_start) >= 1.1:
                    candidatos.append(
                        {
                            "start": cut_start,
                            "end": cut_end,
                            "score": round(score, 2),
                            "reason": reason,
                        }
                    )

    # Respaldo con picos de voz de alta intensidad acoplados a la palabra más cercana
    if picos_audio:
        for p in picos_audio:
            if p.get("intensidad") not in {"alta", "muy_alta"}:
                continue
            seg = float(p.get("segundo", 0.0))
            if seg < 4.5 or seg > max(4.5, duracion_total - 1.2):
                continue

            anchor_idx: int | None = None
            if palabras:
                cercanas = [
                    (abs(float(w.get("start", 0.0)) - seg), idx)
                    for idx, w in enumerate(palabras)
                    if seg - 0.6 <= float(w.get("start", 0.0)) <= seg + 1.2
                ]
                if cercanas:
                    _, anchor_idx = min(cercanas, key=lambda item: item[0])

            if anchor_idx is not None:
                cut_start, cut_end = _calcular_rango_corte_frase(
                    palabras, anchor_idx, duracion_total
                )
            else:
                cut_start = round(max(0.0, seg - 0.15), 2)
                cut_end = round(min(duracion_total, cut_start + 1.6), 2)

            if (cut_end - cut_start) >= 1.1:
                sobre = float(p.get("sobre_promedio_db", 6.0))
                candidatos.append(
                    {
                        "start": cut_start,
                        "end": cut_end,
                        "score": round(6.5 + sobre * 0.4, 2),
                        "reason": f"pico_voz:{sobre}dB",
                    }
                )

    if not candidatos:
        return []

    max_cortes = 2 if duracion_total < 24.0 else (3 if duracion_total < 42.0 else 4)
    separacion_min = 6.5 if duracion_total >= 35.0 else 5.0

    elegidos: list[dict[str, Any]] = []
    for cand in sorted(candidatos, key=lambda c: c["score"], reverse=True):
        if any(
            abs(cand["start"] - prev["start"]) < separacion_min
            or not (cand["end"] + 0.8 <= prev["start"] or cand["start"] >= prev["end"] + 0.8)
            for prev in elegidos
        ):
            continue
        elegidos.append(cand)
        if len(elegidos) >= max_cortes:
            break

    elegidos.sort(key=lambda c: c["start"])
    return [{"start": c["start"], "end": c["end"]} for c in elegidos]


def seleccionar_musica_fondo(
    base_dir: Path,
    texto: str,
    palabras: list[dict[str, Any]] | None = None,
    duracion_final: float = 60.0,
    clip_name: str = "",
    categoria_forzada: str | None = None,
    pista_forzada: str | None = None,
    picos_audio: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """
    Elige automáticamente la pista más acorde de `musica/catalogo_musica.json`
    según la transcripción, el tono del clip y sus palabras clave.
    """
    catalogo_path = base_dir / "musica" / "catalogo_musica.json"
    if not catalogo_path.is_file():
        return None

    try:
        catalogo = json.loads(catalogo_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    tracks: list[dict[str, Any]] = catalogo.get("tracks", [])
    if not tracks:
        return None

    texto_lower = f"{clip_name.replace('_', ' ')} {texto}".lower()
    cortes = detectar_cortes_remate(palabras or [], duracion_final, picos_audio)

    # 1. Si se indicó una pista específica por CLI
    if pista_forzada:
        for t in tracks:
            if t["file"].lower() == pista_forzada.lower() or pista_forzada.lower() in t["file"].lower():
                return {
                    "file": t["file"],
                    "category": t["category"],
                    "volume": t.get("recommendedVolume", 0.10),
                    "cutAtTimestamps": cortes,
                    "fadeInSeconds": 0.5,
                    "fadeOutSeconds": 1.0,
                    "cutFadeInSeconds": 0.4,
                }

    # 2. Determinar categoría según señales del texto (o usar categoria_forzada)
    if categoria_forzada in CATEGORY_SIGNALS:
        categoria = categoria_forzada
    else:
        scores_cat: dict[str, int] = {cat: 0 for cat in CATEGORY_SIGNALS}
        for cat, kws in CATEGORY_SIGNALS.items():
            for kw in kws:
                if kw in texto_lower:
                    scores_cat[cat] += 3 if len(kw) > 5 else 2

        if picos_audio:
            altos = sum(1 for p in picos_audio if p.get("intensidad") in {"alta", "muy_alta"})
            if altos >= 2:
                scores_cat["tension_accion"] += 2
                scores_cat["comedia_absurda"] += 1

        mejor_cat, mejor_score = max(scores_cat.items(), key=lambda kv: kv[1])
        categoria = mejor_cat if mejor_score > 0 else "comedia_absurda"

    # 3. Elegir la mejor pista dentro de la categoría
    candidatas = [
        t
        for t in tracks
        if t.get("category") == categoria and not t.get("excludeFromAutoBgm", False)
    ]
    if not candidatas:
        candidatas = [t for t in tracks if not t.get("excludeFromAutoBgm", False)] or tracks

    mejor_pista = candidatas[0]
    mejor_puntaje = -999.0
    seed = sum(ord(ch) for ch in (clip_name or texto[:30]))

    for idx, t in enumerate(candidatas):
        pts = 0.0
        fname = str(t.get("file", ""))
        # Priorizar pistas ES_ (Epidemic Sound) y bajar prioridad a Kevin MacLeod
        if fname.startswith("ES_"):
            pts += 8.0
        elif "kevin macleod" in fname.lower():
            pts -= 12.0

        for kw in t.get("keywords", []):
            if kw.lower() in texto_lower:
                pts += 4.0
        # Preferir pistas cuya duración cubra el clip o tenga buen cuerpo (>60s)
        if float(t.get("durationSeconds", 0)) >= duracion_final:
            pts += 1.0
        # Desempate determinista por nombre del clip para variar entre pistas top
        tie_breaker = ((seed + idx * 7) % 3) * 0.1
        total_pts = pts + tie_breaker
        if total_pts > mejor_puntaje:
            mejor_puntaje = total_pts
            mejor_pista = t

    return {
        "file": mejor_pista["file"],
        "category": categoria,
        "volume": mejor_pista.get("recommendedVolume", 0.10),
        "cutAtTimestamps": cortes,
        "fadeInSeconds": 0.5,
        "fadeOutSeconds": 1.0,
        "cutFadeInSeconds": 0.4,
    }


def cargar_config_edicion(base_dir: Path) -> dict[str, Any]:
    """Lee config_edicion.json para obtener la configuración global por defecto (ej. usarMejoraIA)."""
    cfg_path = base_dir / "config_edicion.json"
    defaults: dict[str, Any] = {
        "usarMejoraIA": False,
        "modeloIA": "realesr-animevideov3",
        "escalaIA": 2,
    }
    if cfg_path.is_file():
        try:
            loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                defaults.update(loaded)
        except Exception:
            pass
    return defaults


def _resolver_coords_webcam(
    args: argparse.Namespace, lista_segmentos: Optional[list[dict[str, Any]]]
) -> tuple[int, int, int, int]:
    """Obtiene (x, y, w, h) del recorte de webcam para la mejora IA."""
    if None not in (args.x, args.y, args.w, args.h):
        return int(args.x), int(args.y), int(args.w), int(args.h)
    if lista_segmentos:
        for seg in lista_segmentos:
            coords = seg.get("coords")
            if isinstance(coords, (list, tuple)) and len(coords) == 4:
                return int(coords[0]), int(coords[1]), int(coords[2]), int(coords[3])
    return 0, 206, 468, 330


def generar_video_webcam_ia(
    base_dir: Path,
    source_video: Path,
    vertical_base_video: Path,
    output_ia_video: Path,
    procesados_dir: Path,
    coords: tuple[int, int, int, int],
    lista_segmentos: Optional[list[dict[str, Any]]] = None,
    modo_unico: str = "gameplay",
    modelo_ia: str = "realesr-animevideov3",
    escala_ia: int = 2,
) -> Optional[dict[str, float]]:
    """
    Aplica Super-Resolution 2x con realesrgan-ncnn-vulkan (Vulkan GPU) ÚNICAMENTE en los
    tramos de cámara sola sin el juego ('fullcam'). Los tramos con gameplay se mantienen
    intactos sin pasar por IA para no alterar texturas del juego ni perder tiempo.
    Nunca sobrescribe el video original ni el vertical_base_video limpio.
    """
    realesrgan_bin = base_dir / "tools" / "ai-upscaler" / "realesrgan-ncnn-vulkan.exe"
    models_dir = base_dir / "tools" / "ai-upscaler" / "models"
    if not realesrgan_bin.is_file():
        raise FileNotFoundError(
            f"No se encontró el binario de Super-Resolution IA en: {realesrgan_bin}"
        )

    ffmpeg_bin = obtener_ruta_ffmpeg()
    t0_total = time.perf_counter()

    # Caso 1: Modo segmentado (--segmentos) -> solo aplicar IA en segmentos con modo == "fullcam"
    if lista_segmentos and len(lista_segmentos) > 0:
        fullcam_indices = [
            idx
            for idx, seg in enumerate(lista_segmentos)
            if str(seg.get("modo", "gameplay")).lower() == "fullcam"
        ]
        if not fullcam_indices:
            print(
                "      [IA] Omitido: el clip no tiene segmentos 'fullcam' (solo cámara sin juego)."
            )
            return None

        seg_files: list[Path] = []
        total_frames_ia = 0
        t_upscale_total = 0.0

        for idx, seg in enumerate(lista_segmentos):
            st = float(seg["start"])
            en = float(seg["end"])
            modo_seg = str(seg.get("modo", "gameplay")).lower()
            seg_out = procesados_dir / f"ia_seg_{idx}.mp4"

            if modo_seg != "fullcam":
                # Tramo con juego: copiar/renderizar limpio sin IA
                sc = seg.get("coords") or list(coords)
                sx, sy, sw, sh = int(sc[0]), int(sc[1]), int(sc[2]), int(sc[3])
                fc = construir_filter_complex("gameplay", sx, sy, sw, sh)
                cmd_gp = [
                    ffmpeg_bin,
                    "-y",
                    "-ss",
                    f"{st:.3f}",
                    "-to",
                    f"{en:.3f}",
                    "-i",
                    str(source_video),
                    "-filter_complex",
                    fc,
                    "-map",
                    "[outv]",
                    "-map",
                    "0:a?",
                    "-r",
                    "30",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    str(seg_out),
                ]
                subprocess.run(cmd_gp, check=True, capture_output=True)
                seg_files.append(seg_out)
                continue

            # Tramo fullcam (solo cámara sin juego): extraer crop nativo 9:16 -> 2x GPU -> 1080x1920
            in_dir = procesados_dir / f"ia_frames_in_{idx}"
            out_dir = procesados_dir / f"ia_frames_out_{idx}"
            shutil.rmtree(in_dir, ignore_errors=True)
            shutil.rmtree(out_dir, ignore_errors=True)
            in_dir.mkdir(parents=True, exist_ok=True)
            out_dir.mkdir(parents=True, exist_ok=True)

            subprocess.run(
                [
                    ffmpeg_bin,
                    "-y",
                    "-ss",
                    f"{st:.3f}",
                    "-to",
                    f"{en:.3f}",
                    "-i",
                    str(source_video),
                    "-vf",
                    "fps=30,crop=trunc(ih*9/16/2)*2:ih",
                    "-q:v",
                    "2",
                    str(in_dir / "frame_%05d.jpg"),
                ],
                check=True,
                capture_output=True,
            )
            n_f = len(list(in_dir.glob("frame_*.jpg")))
            total_frames_ia += n_f

            t0_u = time.perf_counter()
            res_ia = subprocess.run(
                [
                    str(realesrgan_bin),
                    "-i",
                    str(in_dir),
                    "-o",
                    str(out_dir),
                    "-n",
                    modelo_ia,
                    "-s",
                    str(escala_ia),
                    "-m",
                    str(models_dir),
                    "-f",
                    "jpg",
                ],
                capture_output=True,
                text=True,
            )
            if res_ia.returncode != 0:
                raise RuntimeError(
                    f"Error ejecutando realesrgan-ncnn-vulkan en segmento {idx}:\n{res_ia.stderr[-800:]}"
                )
            t_upscale_total += time.perf_counter() - t0_u

            subprocess.run(
                [
                    ffmpeg_bin,
                    "-y",
                    "-framerate",
                    "30",
                    "-i",
                    str(out_dir / "frame_%05d.jpg"),
                    "-ss",
                    f"{st:.3f}",
                    "-to",
                    f"{en:.3f}",
                    "-i",
                    str(source_video),
                    "-vf",
                    "scale=1080:1920:flags=lanczos,setsar=1",
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a?",
                    "-r",
                    "30",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    "-shortest",
                    str(seg_out),
                ],
                check=True,
                capture_output=True,
            )
            shutil.rmtree(in_dir, ignore_errors=True)
            shutil.rmtree(out_dir, ignore_errors=True)
            seg_files.append(seg_out)

        concat_txt = procesados_dir / "ia_concat_list.txt"
        concat_txt.write_text(
            "\n".join(f"file '{p.as_posix()}'" for p in seg_files), encoding="utf-8"
        )
        subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_txt),
                "-c",
                "copy",
                str(output_ia_video),
            ],
            check=True,
            capture_output=True,
        )
        for sf in seg_files:
            sf.unlink(missing_ok=True)
        concat_txt.unlink(missing_ok=True)

        t_total = time.perf_counter() - t0_total
        fps_ia = total_frames_ia / t_upscale_total if t_upscale_total > 0 else 0.0
        print(
            f"      [IA] Fullcam mejorado ({len(fullcam_indices)} tramo(s), {total_frames_ia} frames) en {t_total:.2f}s (GPU {fps_ia:.1f} fps) -> '{output_ia_video.name}'"
        )
        return {
            "frames": float(total_frames_ia),
            "upscaleSeconds": round(t_upscale_total, 2),
            "totalSeconds": round(t_total, 2),
            "fpsGpu": round(fps_ia, 2),
        }

    # Caso 2: Escena única -> solo aplicar si modo_unico == "fullcam"
    if str(modo_unico).lower() != "fullcam":
        print(
            "      [IA] Omitido: en escena única la mejora IA solo se aplica en '--modo fullcam' (cámara sola sin juego)."
        )
        return None

    in_frames_dir = procesados_dir / "ia_frames_in"
    out_frames_dir = procesados_dir / "ia_frames_out"
    shutil.rmtree(in_frames_dir, ignore_errors=True)
    shutil.rmtree(out_frames_dir, ignore_errors=True)
    in_frames_dir.mkdir(parents=True, exist_ok=True)
    out_frames_dir.mkdir(parents=True, exist_ok=True)

    t0_extract = time.perf_counter()
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(source_video),
            "-vf",
            "fps=30,crop=trunc(ih*9/16/2)*2:ih",
            "-q:v",
            "2",
            str(in_frames_dir / "frame_%05d.jpg"),
        ],
        check=True,
        capture_output=True,
    )
    t_extract = time.perf_counter() - t0_extract
    num_frames = len(list(in_frames_dir.glob("frame_*.jpg")))

    t0_upscale = time.perf_counter()
    res_ia = subprocess.run(
        [
            str(realesrgan_bin),
            "-i",
            str(in_frames_dir),
            "-o",
            str(out_frames_dir),
            "-n",
            modelo_ia,
            "-s",
            str(escala_ia),
            "-m",
            str(models_dir),
            "-f",
            "jpg",
        ],
        capture_output=True,
        text=True,
    )
    if res_ia.returncode != 0:
        raise RuntimeError(
            f"Error ejecutando realesrgan-ncnn-vulkan:\n{res_ia.stderr[-800:]}"
        )
    t_upscale = time.perf_counter() - t0_upscale
    fps_ia = num_frames / t_upscale if t_upscale > 0 else 0.0

    t0_merge = time.perf_counter()
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-framerate",
            "30",
            "-i",
            str(out_frames_dir / "frame_%05d.jpg"),
            "-i",
            str(vertical_base_video),
            "-vf",
            "scale=1080:1920:flags=lanczos,setsar=1",
            "-map",
            "0:v:0",
            "-map",
            "1:a?",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-shortest",
            str(output_ia_video),
        ],
        check=True,
        capture_output=True,
    )
    t_merge = time.perf_counter() - t0_merge
    t_total = time.perf_counter() - t0_total

    shutil.rmtree(in_frames_dir, ignore_errors=True)
    shutil.rmtree(out_frames_dir, ignore_errors=True)

    print(
        f"      [IA] Fullcam mejorado ({num_frames} frames) en {t_total:.2f}s (Extract: {t_extract:.2f}s, GPU 2x: {t_upscale:.2f}s [{fps_ia:.1f} fps], Merge: {t_merge:.2f}s) -> '{output_ia_video.name}'"
    )
    return {
        "frames": float(num_frames),
        "extractSeconds": round(t_extract, 2),
        "upscaleSeconds": round(t_upscale, 2),
        "mergeSeconds": round(t_merge, 2),
        "totalSeconds": round(t_total, 2),
        "fpsGpu": round(fps_ia, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Procesa un clip eliminando silencios, detectando cambios de cámara por escena, armando el vertical 9:16 (30fps) y transcribiendo con Whisper."
    )
    parser.add_argument(
        "archivo",
        help="Nombre del archivo dentro de 'clips-entrada/' (o ruta directa al clip)",
    )
    parser.add_argument(
        "x",
        type=int,
        nargs="?",
        default=None,
        help="Coordenada X de la webcam (para modo gameplay de escena única)",
    )
    parser.add_argument(
        "y",
        type=int,
        nargs="?",
        default=None,
        help="Coordenada Y de la webcam",
    )
    parser.add_argument(
        "w",
        type=int,
        nargs="?",
        default=None,
        help="Ancho (W) de la webcam",
    )
    parser.add_argument(
        "h",
        type=int,
        nargs="?",
        default=None,
        help="Alto (H) de la webcam",
    )
    parser.add_argument(
        "--modo",
        choices=["gameplay", "fullcam"],
        default="gameplay",
        help="Modo de composición cuando es escena única: 'gameplay' o 'fullcam'. Default: gameplay",
    )
    parser.add_argument(
        "--detectar-cam",
        action="store_true",
        help="Extrae el primer frame del video y lo guarda en clips-procesados/preview.jpg.",
    )
    parser.add_argument(
        "--detectar-escenas",
        action="store_true",
        help="Elimina silencios primero (sin_silencio_temp.mp4), detecta cambios de escena con FFmpeg y guarda clips-procesados/escena_0.jpg, escena_1.jpg, etc.",
    )
    parser.add_argument(
        "--scene-threshold",
        type=float,
        default=0.35,
        help="Sensibilidad de detección de cambio de escena en FFmpeg (0.0 a 1.0). Default: 0.35",
    )
    parser.add_argument(
        "--segmentos",
        type=str,
        default=None,
        help='JSON (o ruta a archivo JSON) con la lista de segmentos dinámicos. Ej: \'[{"start":0,"end":14.2,"modo":"gameplay","coords":[0,0,480,270]},{"start":14.2,"end":35.0,"modo":"fullcam"}]\'',
    )
    parser.add_argument(
        "--no-silencios",
        "--keep-silence",
        dest="keep_silence",
        action="store_true",
        help="Desactiva el recorte automático de silencios con auto-editor.",
    )
    parser.add_argument(
        "--model",
        default="base",
        help="Modelo de Whisper a utilizar (tiny, base, small, medium, large). Default: base",
    )
    parser.add_argument(
        "--sync-remotion",
        action="store_true",
        help="Copia el video a public/ y actualiza public/data.json automáticamente",
    )
    parser.add_argument(
        "--edit-style",
        choices=["simple", "detallada", "ilustraciones"],
        default="simple",
        help="Nivel de edición para public/data.json ('simple', 'detallada', 'ilustraciones'). Default: simple",
    )
    parser.add_argument(
        "--categoria-musica",
        choices=["comedia_absurda", "tension_accion", "chill_storytime", "epica_climax"],
        default=None,
        help="Fuerza la categoría de música de fondo para el clip.",
    )
    parser.add_argument(
        "--musica",
        default=None,
        help="Nombre exacto o parcial del archivo de música dentro de musica/.",
    )
    parser.add_argument(
        "--sin-musica",
        action="store_true",
        help="Desactiva la selección automática de música de fondo.",
    )
    ia_group = parser.add_mutually_exclusive_group()
    ia_group.add_argument(
        "--mejorar-ia",
        dest="mejorar_ia",
        action="store_true",
        default=None,
        help="Activa Super-Resolution IA (2x Real-ESRGAN Vulkan) únicamente sobre el recorte de la webcam y genera <nombre>_webcam_ia.mp4.",
    )
    ia_group.add_argument(
        "--sin-ia",
        dest="mejorar_ia",
        action="store_false",
        help="Desactiva explícitamente la mejora de calidad por IA (usa el video limpio original).",
    )

    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    entrada_dir = base_dir / "clips-entrada"
    procesados_dir = base_dir / "clips-procesados"
    procesados_dir.mkdir(parents=True, exist_ok=True)

    input_path = Path(args.archivo)
    if not input_path.is_file():
        input_path = entrada_dir / args.archivo

    if not input_path.is_file():
        print(
            f"Error: No se encontró el archivo de entrada en '{input_path}'",
            file=sys.stderr,
        )
        sys.exit(1)

    # Modo rápido --detectar-cam (1 solo frame del clip crudo)
    if args.detectar_cam and not args.detectar_escenas:
        preview_path = procesados_dir / "preview.jpg"
        extraer_frame_en_tiempo(input_path, preview_path, timestamp=0.0)
        print(f"[Preview] Frame inicial guardado en: {preview_path}")
        if args.segmentos is None and args.modo == "gameplay" and None in (args.x, args.y, args.w, args.h):
            return

    sin_silencio_temp = procesados_dir / "sin_silencio_temp.mp4"

    # Fase 1: --detectar-escenas
    if args.detectar_escenas:
        if args.keep_silence:
            source_video = input_path
        else:
            source_video = eliminar_silencios_auto_editor(input_path, sin_silencio_temp)

        detectar_escenas_ffmpeg(
            source_video,
            procesados_dir,
            threshold=args.scene_threshold,
            min_segment_duration=1.5,
        )
        return

    # Determinar el video fuente para el procesamiento (reutilizar sin_silencio_temp.mp4 si ya fue creado en --detectar-escenas)
    if args.keep_silence:
        print("[1/3] Recorte de silencios omitido (--no-silencios / --keep-silence).")
        source_for_ffmpeg = input_path
    elif sin_silencio_temp.exists() and sin_silencio_temp.stat().st_mtime >= input_path.stat().st_mtime:
        print(f"[1/3] Reutilizando '{sin_silencio_temp.name}' ya generado sin silencios.")
        source_for_ffmpeg = sin_silencio_temp
    else:
        source_for_ffmpeg = eliminar_silencios_auto_editor(input_path, sin_silencio_temp)

    vertical_temp = procesados_dir / "vertical_temp.mp4"
    transcripcion_json = procesados_dir / "transcripcion.json"

    # Fase 2: Procesamiento por segmentos múltiples o modo único
    lista_segmentos: Optional[list[dict[str, Any]]] = None
    if args.segmentos:
        lista_segmentos = parsear_argumento_segmentos(args.segmentos)
        print(f"[2/3] Procesando {len(lista_segmentos)} segmento(s) dinámico(s) a 30fps...")
        procesar_por_segmentos(
            source_for_ffmpeg, vertical_temp, lista_segmentos, procesados_dir
        )
    else:
        if args.modo == "gameplay" and None in (args.x, args.y, args.w, args.h):
            parser.error(
                "En '--modo gameplay' debés indicar las coordenadas 'x y w h' de la webcam (o usar --segmentos / --detectar-escenas)."
            )
        print(
            f"[2/3] Ejecutando FFmpeg (--modo {args.modo}) para generar '{vertical_temp}' (1080x1920 @ 30fps)..."
        )
        procesar_video_ffmpeg(
            source_for_ffmpeg,
            vertical_temp,
            modo=args.modo,
            x=args.x,
            y=args.y,
            w=args.w,
            h=args.h,
        )

    # Resolver si la mejora de calidad por IA está activa (--mejorar-ia / --sin-ia / config_edicion.json)
    cfg_edicion = cargar_config_edicion(base_dir)
    usar_ia = (
        bool(cfg_edicion.get("usarMejoraIA", False))
        if args.mejorar_ia is None
        else bool(args.mejorar_ia)
    )
    modelo_ia = str(cfg_edicion.get("modeloIA", "realesr-animevideov3"))
    escala_ia = int(cfg_edicion.get("escalaIA", 2))

    # Fase 3: Transcripción con Whisper sobre el video vertical final
    palabras = transcribir_whisper(
        vertical_temp, transcripcion_json, model_name=args.model
    )

    if args.sync_remotion:
        public_dir = base_dir / "public"
        clips_public_dir = public_dir / "clips"
        proyectos_dir = public_dir / "proyectos"
        clips_public_dir.mkdir(parents=True, exist_ok=True)
        proyectos_dir.mkdir(parents=True, exist_ok=True)

        clip_name = input_path.stem
        clip_video_dest = clips_public_dir / f"{clip_name}.mp4"
        shutil.copy2(vertical_temp, clip_video_dest)
        # También mantenemos vertical_temp.mp4 como respaldo para MainShort
        shutil.copy2(vertical_temp, public_dir / "vertical_temp.mp4")

        ia_video_name = f"{clip_name}_webcam_ia.mp4"
        ia_video_dest = clips_public_dir / ia_video_name
        webcam_enhanced_rel: Optional[str] = None
        if usar_ia:
            coords_ia = _resolver_coords_webcam(args, lista_segmentos)
            res_ia_stats = generar_video_webcam_ia(
                base_dir=base_dir,
                source_video=source_for_ffmpeg,
                vertical_base_video=vertical_temp,
                output_ia_video=ia_video_dest,
                procesados_dir=procesados_dir,
                coords=coords_ia,
                lista_segmentos=lista_segmentos,
                modo_unico=args.modo,
                modelo_ia=modelo_ia,
                escala_ia=escala_ia,
            )
            if res_ia_stats is not None:
                webcam_enhanced_rel = f"clips/{ia_video_name}"
        elif ia_video_dest.is_file():
            webcam_enhanced_rel = f"clips/{ia_video_name}"

        duracion_final = obtener_duracion_video(vertical_temp)
        texto_transcripcion = " ".join(str(w.get("word", "")) for w in palabras)
        picos_voz: list[dict[str, Any]] = []
        if not args.sin_musica:
            try:
                ventanas_audio = medir_rms_por_ventana(vertical_temp)
                _, picos_voz = detectar_picos_audio(
                    ventanas_audio, [], palabras, max_picos=6
                )
            except Exception as err:
                print(f"      [Música] Aviso: no se pudieron medir picos de voz ({err})")
        musica_fondo = (
            None
            if args.sin_musica
            else seleccionar_musica_fondo(
                base_dir=base_dir,
                texto=texto_transcripcion,
                palabras=palabras,
                duracion_final=duracion_final,
                clip_name=clip_name,
                categoria_forzada=args.categoria_musica,
                pista_forzada=args.musica,
                picos_audio=picos_voz,
            )
        )

        remotion_data: dict[str, Any] = {
            "editStyle": args.edit_style,
            "hookTitle": "",
            "subtitleConfig": {
                "yOffset": 0,
                "scale": 1,
            },
            "videoSrc": f"clips/{clip_name}.mp4",
            "webcamEnhancedFile": webcam_enhanced_rel,
            "usarMejoraIA": bool(usar_ia and webcam_enhanced_rel is not None),
            "durationInSeconds": duracion_final,
            "cards": [],
            "illustrations": [],
            "explainerPanels": [],
            "subtitles": palabras,
        }
        if musica_fondo:
            remotion_data["backgroundMusic"] = musica_fondo
            musica_public_dir = public_dir / "musica"
            musica_public_dir.mkdir(parents=True, exist_ok=True)
            src_music = base_dir / "musica" / musica_fondo["file"]
            dst_music = musica_public_dir / musica_fondo["file"]
            if src_music.is_file() and not dst_music.is_file():
                shutil.copy2(src_music, dst_music)
            print(
                f"      [Música] Categoría='{musica_fondo['category']}' | Pista='{musica_fondo['file']}' (vol={musica_fondo['volume']}) | Cortes={musica_fondo.get('cutAtTimestamps', [])}"
            )

        proyecto_json_path = proyectos_dir / f"{clip_name}.json"
        proyecto_json_path.write_text(
            json.dumps(remotion_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Actualizar public/data.json como respaldo de MainShort
        data_json_path = public_dir / "data.json"
        data_json_path.write_text(
            json.dumps(remotion_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Actualizar el índice public/proyectos/index.json sin borrar anteriores
        index_json_path = proyectos_dir / "index.json"
        lista_proyectos: list[str] = []
        if index_json_path.exists():
            try:
                cargado = json.loads(index_json_path.read_text(encoding="utf-8"))
                if isinstance(cargado, list):
                    lista_proyectos = [str(item) for item in cargado]
            except Exception:
                lista_proyectos = []

        if clip_name not in lista_proyectos:
            lista_proyectos.append(clip_name)

        index_json_path.write_text(
            json.dumps(lista_proyectos, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        print(
            f"      [Sync] Guardado video en public/clips/{clip_name}.mp4 ({duracion_final}s)"
        )
        print(
            f"      [Sync] Guardado proyecto en public/proyectos/{clip_name}.json (editStyle='{args.edit_style}')"
        )
        print(
            f"      [Sync] Índice actualizado en public/proyectos/index.json: {lista_proyectos}"
        )


if __name__ == "__main__":
    main()
