#!/usr/bin/env python3
"""
Evaluación previa de clips: transcripción (Whisper) + picos de energía de audio (FFmpeg).

Escanea los videos de `clips-entrada/`, extrae la transcripción con marcas de tiempo y
detecta los momentos donde el volumen sube muy por encima del promedio del clip
(gritos, risas explosivas, sustos). Guarda todo en
`clips-entrada/transcripciones_pendientes.json` para calificar los clips ANTES de editarlos.

Este script NO corta video ni crea proyectos en public/proyectos/.

Uso:
    python evaluar_clips.py                    # evalúa todos los clips pendientes
    python evaluar_clips.py --archivo clip.mp4 # evalúa solo un clip
    python evaluar_clips.py --modelo small     # usa el modelo 'small' de Whisper
    python evaluar_clips.py --forzar           # re-evalúa aunque ya esté en el JSON
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from procesar_clip import (
    DURACION_SHORT_MAX_SEG,
    DURACION_SHORT_MIN_SEG,
    HABILITAR_HOOK_TEASER,
    VENTANA_AUDIO_SEG,
    analizar_estructura_gancho_tension_recompensa,
    detectar_picos_audio,
    generar_metadata_seo_short,
    medir_rms_por_ventana,
    obtener_duracion_video,
    seleccionar_musica_fondo,
)

EXTENSIONES_VIDEO = {".mp4", ".mkv", ".mov", ".webm"}
SALIDA_JSON = "transcripciones_pendientes.json"


def transcribir(
    model: Any, video_path: Path, usar_word_timestamps: bool = True
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Transcribe en español y devuelve (texto_completo, segmentos con start/end/text, palabras).
    En tramos largos (>90s) desactiva word_timestamps para acelerar Whisper en CPU.
    """
    result = model.transcribe(
        str(video_path),
        language="es",
        fp16=False,
        word_timestamps=usar_word_timestamps,
        verbose=False,
    )
    segmentos = []
    palabras = []
    for seg in result.get("segments", []):
        texto = str(seg.get("text", "")).strip()
        if not texto:
            continue
        segmentos.append(
            {
                "start": round(float(seg.get("start", 0.0)), 2),
                "end": round(float(seg.get("end", 0.0)), 2),
                "text": texto,
            }
        )
        for w in seg.get("words", []) or []:
            palabra = str(w.get("word", "")).strip()
            if palabra:
                palabras.append(
                    {
                        "start": float(w.get("start", 0.0)),
                        "end": float(w.get("end", 0.0)),
                        "word": palabra,
                        "highlight": len(palabra) >= 7 or palabra.isupper(),
                    }
                )
    return str(result.get("text", "")).strip(), segmentos, palabras


def cargar_resultados_previos(salida_path: Path) -> dict[str, dict[str, Any]]:
    if not salida_path.exists():
        return {}
    try:
        data = json.loads(salida_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {str(item.get("archivo")): item for item in data if isinstance(item, dict)}
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Transcribe los clips de clips-entrada/ y detecta picos de energía de audio para calificarlos."
    )
    parser.add_argument(
        "--archivo",
        default=None,
        help="Evaluar solo este archivo dentro de clips-entrada/ (por defecto: todos).",
    )
    parser.add_argument(
        "--modelo",
        default="base",
        help="Modelo de Whisper (tiny, base, small...). Default: base (rápido en CPU).",
    )
    parser.add_argument(
        "--picos",
        type=int,
        default=4,
        help="Cantidad máxima de picos de audio a reportar por clip. Default: 4",
    )
    parser.add_argument(
        "--forzar",
        action="store_true",
        help="Re-evalúa los clips aunque ya estén en el JSON con el mismo tamaño.",
    )
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    entrada_dir = base_dir / "clips-entrada"
    salida_path = entrada_dir / SALIDA_JSON

    if args.archivo:
        candidatos = [entrada_dir / args.archivo]
        if not candidatos[0].is_file():
            print(f"Error: no existe '{candidatos[0]}'", file=sys.stderr)
            sys.exit(1)
    else:
        candidatos = sorted(
            p
            for p in entrada_dir.iterdir()
            if p.is_file() and p.suffix.lower() in EXTENSIONES_VIDEO
        )

    if not candidatos:
        print(f"No hay clips de video en '{entrada_dir}'.")
        return

    previos = cargar_resultados_previos(salida_path)
    resultados: dict[str, dict[str, Any]] = dict(previos)

    pendientes = []
    for clip in candidatos:
        previo = previos.get(clip.name)
        if (
            not args.forzar
            and previo
            and previo.get("tamano_bytes") == clip.stat().st_size
            and previo.get("modelo_whisper") == args.modelo
        ):
            print(f"[=] {clip.name}: ya evaluado (usá --forzar para repetir).")
            continue
        pendientes.append(clip)

    if pendientes:
        import whisper

        print(f"[Whisper] Cargando modelo '{args.modelo}'...")
        model = whisper.load_model(args.modelo)

        for idx, clip in enumerate(pendientes, start=1):
            print(f"\n[{idx}/{len(pendientes)}] Evaluando '{clip.name}'...")
            duracion = obtener_duracion_video(clip)

            print("   - Transcribiendo...")
            usar_words = duracion <= 180.0
            texto_completo, segmentos, palabras = transcribir(
                model, clip, usar_word_timestamps=usar_words
            )

            print("   - Midiendo energía de audio por ventanas de 1s...")
            ventanas = medir_rms_por_ventana(clip, ventana_seg=VENTANA_AUDIO_SEG)
            picos_objetivo = (
                args.picos
                if duracion <= 120.0
                else max(args.picos, min(12, int(duracion // 60) + 2))
            )
            promedio_db, picos = detectar_picos_audio(
                ventanas,
                segmentos,
                palabras,
                max_picos=picos_objetivo,
                ventana_seg=VENTANA_AUDIO_SEG,
            )
            plan_narrativo = analizar_estructura_gancho_tension_recompensa(
                segmentos=segmentos,
                palabras=palabras,
                picos_audio=picos,
                duracion_total=duracion,
                min_seg=DURACION_SHORT_MIN_SEG,
                max_seg=DURACION_SHORT_MAX_SEG,
            )
            duracion_objetivo = float(
                plan_narrativo.get("duracion_objetivo_estimada", min(duracion, DURACION_SHORT_MAX_SEG))
            )
            seo_sugerido = generar_metadata_seo_short(
                texto=texto_completo,
                palabras=palabras,
                clip_name=clip.stem,
                picos_audio=picos,
            )
            musica_sugerida = seleccionar_musica_fondo(
                base_dir=base_dir,
                texto=texto_completo,
                palabras=palabras,
                duracion_final=duracion_objetivo,
                clip_name=clip.stem,
                picos_audio=picos,
            )

            resultados[clip.name] = {
                "archivo": clip.name,
                "duracion": duracion,
                "duracion_objetivo_22_45s": duracion_objetivo,
                "habilitarHookTeaser": HABILITAR_HOOK_TEASER,
                "estructura_narrativa": plan_narrativo.get("estructura", {}),
                "segmentos_conservar_tijera": plan_narrativo.get("segmentos_conservar", []),
                "frases_eliminadas_tijera": plan_narrativo.get("frases_eliminadas_tijera", []),
                "seo_sugerido": seo_sugerido,
                "texto_completo": texto_completo,
                "segmentos": segmentos,
                "promedio_db": promedio_db,
                "picos_audio": picos,
                "musica_sugerida": musica_sugerida,
                "tamano_bytes": clip.stat().st_size,
                "modelo_whisper": args.modelo,
            }
            resumen_picos = ", ".join(
                f"{p['segundo']}s ({p['db']} dB, {p['intensidad']})" for p in picos
            )
            resumen_musica = (
                f" | Música: [{musica_sugerida['category']}] {musica_sugerida['file']}"
                if musica_sugerida
                else ""
            )
            n_podadas = len(plan_narrativo.get("frases_eliminadas_tijera", []))
            print(
                f"   OK: {duracion}s -> {duracion_objetivo}s (objetivo 22-45s, {n_podadas} rellenos podados, hookTeaser=False) | "
                f"Título ({seo_sugerido['titleCharCount']}/55): {seo_sugerido['youtubeTitle']} | "
                f"Picos: {resumen_picos or 'ninguno'}{resumen_musica}"
            )

    # Solo se listan los clips que siguen existiendo en clips-entrada/
    existentes = {p.name for p in entrada_dir.iterdir() if p.is_file()}
    salida = [item for nombre, item in sorted(resultados.items()) if nombre in existentes]
    salida_path.write_text(
        json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nResultados guardados en: {salida_path} ({len(salida)} clip(s))")


if __name__ == "__main__":
    main()
