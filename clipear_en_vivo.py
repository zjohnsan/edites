#!/usr/bin/env python3
"""
Script para extraer un tramo de un directo/VOD (YouTube/Kick/Twitch) en 1080p y
procesarlo automáticamente con procesar_clip.py (incluyendo los flags opcionales
--mejorar-ia / --sin-ia controlados por defecto desde config_edicion.json).
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def cargar_config_edicion(base_dir: Path) -> dict[str, Any]:
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extrae un clip en 1080p y ejecuta procesar_clip.py con soporte opcional de Super-Resolution IA (--mejorar-ia / --sin-ia)."
    )
    parser.add_argument("archivo_o_url", help="URL del stream/VOD o archivo en clips-entrada/")
    parser.add_argument("--start", default=None, help="Timestamp inicial (HH:MM:SS)")
    parser.add_argument("--end", default=None, help="Timestamp final (HH:MM:SS)")
    parser.add_argument("--out", default=None, help="Nombre del archivo de salida en clips-entrada/")
    parser.add_argument(
        "--coords",
        nargs=4,
        type=int,
        default=[0, 206, 468, 330],
        metavar=("X", "Y", "W", "H"),
        help="Coordenadas X Y W H de la webcam (default: 0 206 468 330)",
    )
    parser.add_argument(
        "--modo",
        choices=["gameplay", "fullcam"],
        default="gameplay",
        help="Modo de encuadre base (gameplay o fullcam)",
    )
    parser.add_argument(
        "--edit-style",
        choices=["simple", "detallada", "ilustraciones"],
        default="detallada",
        help="Estilo de edición en Remotion",
    )
    parser.add_argument(
        "--model",
        default="small",
        help="Modelo de Whisper (default: small)",
    )
    parser.add_argument(
        "--no-silencios",
        action="store_true",
        help="No recortar silencios con auto-editor",
    )
    ia_group = parser.add_mutually_exclusive_group()
    ia_group.add_argument(
        "--mejorar-ia",
        dest="mejorar_ia",
        action="store_true",
        default=None,
        help="Activa Super-Resolution IA (2x Real-ESRGAN Vulkan) sobre la webcam.",
    )
    ia_group.add_argument(
        "--sin-ia",
        dest="mejorar_ia",
        action="store_false",
        help="Desactiva la mejora de calidad por IA (usa el video limpio original).",
    )

    args = parser.parse_args()
    base_dir = Path(__file__).resolve().parent
    entrada_dir = base_dir / "clips-entrada"
    entrada_dir.mkdir(parents=True, exist_ok=True)

    cfg = cargar_config_edicion(base_dir)
    usar_ia = (
        bool(cfg.get("usarMejoraIA", False))
        if args.mejorar_ia is None
        else bool(args.mejorar_ia)
    )

    target_clip = args.archivo_o_url
    if target_clip.startswith(("http://", "https://")):
        if not args.start or not args.end or not args.out:
            parser.error("Cuando pasás una URL debés especificar --start, --end y --out.")
        out_name = args.out if args.out.endswith(".mp4") else f"{args.out}.mp4"
        out_path = entrada_dir / out_name
        cmd_dl = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-check-certificates",
            "-f",
            "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
            "--merge-output-format",
            "mp4",
            "--download-sections",
            f"*{args.start}-{args.end}",
            "--force-keyframes-at-cuts",
            "-o",
            str(out_path),
            target_clip,
        ]
        print(f"[Clipear] Descargando {args.start}-{args.end} en {out_path.name}...")
        subprocess.run(cmd_dl, check=True)
        target_clip = out_path.name

    x, y, w, h = args.coords
    cmd_proc = [
        sys.executable,
        str(base_dir / "procesar_clip.py"),
        target_clip,
        str(x),
        str(y),
        str(w),
        str(h),
        "--modo",
        args.modo,
        "--edit-style",
        args.edit_style,
        "--model",
        args.model,
        "--sync-remotion",
        "--mejorar-ia" if usar_ia else "--sin-ia",
    ]
    if args.no_silencios:
        cmd_proc.append("--no-silencios")

    subprocess.run(cmd_proc, check=True)


if __name__ == "__main__":
    main()
