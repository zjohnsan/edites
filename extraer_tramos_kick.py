#!/usr/bin/env python3
"""
Extrae tramos específicos de un VOD de Kick sin descargar el directo completo.

1. Obtiene la URL directa del stream HLS (.m3u8) usando `yt-dlp` (con impersonate chrome).
2. Usa `ffmpeg -ss <inicio> -to <fin> -i <m3u8> -c copy` para saltar directamente a los
   segmentos de cada tramo y guardarlos en `clips-entrada/` en segundos.

Uso:
    python extraer_tramos_kick.py
    python extraer_tramos_kick.py --tramo tramo_1_1h19m.mp4
    python extraer_tramos_kick.py --forzar
"""

import argparse
import subprocess
import sys
from pathlib import Path

from procesar_clip import obtener_duracion_video, obtener_ruta_ffmpeg

DEFAULT_VOD_URL = "https://kick.com/berlinuno/videos/01a1cbfb-79d0-74ed-933d-67f709e89e63"

TRAMOS_DEFAULT = [
    {
        "archivo": "tramo_1_1h19m.mp4",
        "start": "01:14:30",
        "end": "01:24:30",
        "nota": "1:19:30 ± 5 min",
    },
    {
        "archivo": "tramo_2_2h48m.mp4",
        "start": "02:43:00",
        "end": "02:53:00",
        "nota": "2:48:00 ± 5 min",
    },
    {
        "archivo": "tramo_3_3h02m.mp4",
        "start": "02:57:20",
        "end": "03:07:20",
        "nota": "3:02:20 ± 5 min",
    },
    {
        "archivo": "tramo_4_3h17m_a_3h23m.mp4",
        "start": "03:12:00",
        "end": "03:28:00",
        "nota": "3:17:00 (-5m) a 3:23:00 (+5m)",
    },
    {
        "archivo": "tramo_5_3h29m.mp4",
        "start": "03:24:00",
        "end": "03:34:00",
        "nota": "3:29:00 ± 5 min",
    },
]


def resolver_m3u8_kick(vod_url: str, formato: str = "1080p60/best") -> str:
    """Usa yt-dlp para obtener la URL directa del manifiesto .m3u8 del VOD de Kick."""
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-check-certificates",
        "--impersonate",
        "chrome",
        "-f",
        formato,
        "-g",
        vod_url,
    ]
    print(f"[yt-dlp] Resolviendo stream .m3u8 para: {vod_url}")
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0 or not res.stdout.strip():
        raise RuntimeError(
            f"No se pudo resolver el .m3u8 con yt-dlp:\n{res.stderr.strip()}"
        )
    m3u8_url = res.stdout.strip().splitlines()[0].strip()
    print(f"[yt-dlp] Stream resuelto: {m3u8_url[:90]}...")
    return m3u8_url


def descargar_tramo_ffmpeg(
    ffmpeg_exe: str, m3u8_url: str, start: str, end: str, destino: Path
) -> None:
    """Descarga únicamente el rango [start, end] desde el HLS .m3u8 sin recodificar (-c copy)."""
    cmd = [
        ffmpeg_exe,
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-ss",
        start,
        "-to",
        end,
        "-i",
        m3u8_url,
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        str(destino),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not destino.exists() or destino.stat().st_size < 10_000:
        raise RuntimeError(
            f"FFmpeg falló al descargar {destino.name} ({start}-{end}):\n{res.stderr[-1000:]}"
        )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Extrae tramos específicos de un VOD de Kick a clips-entrada/ usando yt-dlp + ffmpeg."
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_VOD_URL,
        help="URL del VOD de Kick.",
    )
    parser.add_argument(
        "--formato",
        default="1080p60/best",
        help="Formato de yt-dlp a seleccionar (ej. 1080p60/best, 720p60, 480p). Default: 1080p60/best",
    )
    parser.add_argument(
        "--tramo",
        default=None,
        help="Descargar únicamente el tramo con este nombre de archivo.",
    )
    parser.add_argument(
        "--forzar",
        action="store_true",
        help="Volver a descargar aunque el archivo ya exista en clips-entrada/.",
    )
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    entrada_dir = base_dir / "clips-entrada"
    entrada_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg_exe = obtener_ruta_ffmpeg()
    m3u8_url = resolver_m3u8_kick(args.url, formato=args.formato)

    tramos = [
        t
        for t in TRAMOS_DEFAULT
        if args.tramo is None or t["archivo"] == args.tramo
    ]
    if not tramos:
        print(f"No se encontró ningún tramo con nombre '{args.tramo}'.", file=sys.stderr)
        sys.exit(1)

    for idx, t in enumerate(tramos, start=1):
        destino = entrada_dir / t["archivo"]
        if destino.exists() and destino.stat().st_size > 100_000 and not args.forzar:
            dur = obtener_duracion_video(destino)
            print(
                f"[{idx}/{len(tramos)}] [=] {t['archivo']} ya existe ({dur}s, {destino.stat().st_size / (1024*1024):.1f} MB). Usá --forzar para re-descargar."
            )
            continue

        print(
            f"\n[{idx}/{len(tramos)}] Descargando {t['archivo']} ({t['start']} -> {t['end']} | {t['nota']})..."
        )
        descargar_tramo_ffmpeg(ffmpeg_exe, m3u8_url, t["start"], t["end"], destino)
        dur = obtener_duracion_video(destino)
        size_mb = destino.stat().st_size / (1024 * 1024)
        print(f"   OK -> {destino} ({dur}s, {size_mb:.1f} MB)")

    print("\nTodos los tramos solicitados están listos en clips-entrada/.")


if __name__ == "__main__":
    main()
