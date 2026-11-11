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
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional


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
        src_crop = f"crop={w}:{h}:{x}:{y}," if None not in (x, y, w, h) else ""
        return (
            f"[0:v]{src_crop}scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,boxblur=40:5,setsar=1[bg];"
            f"[0:v]{src_crop}scale=-2:1350:force_original_aspect_ratio=increase,"
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

        duracion_final = obtener_duracion_video(vertical_temp)
        remotion_data = {
            "editStyle": args.edit_style,
            "hookTitle": "",
            "subtitleConfig": {
                "yOffset": 0,
                "scale": 1,
            },
            "videoSrc": f"clips/{clip_name}.mp4",
            "durationInSeconds": duracion_final,
            "cards": [],
            "illustrations": [],
            "explainerPanels": [],
            "subtitles": palabras,
        }

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
