"""
aplicar_cta.py — Genera el cartel CTA transparente reutilizable (assets/cta_berlinuno.png)
y lo superpone con FFmpeg en los últimos 6 segundos de un video 1080x1920.

Uso:
  python aplicar_cta.py clips_gta6_ep1/listos/10_npc_recuerda_pega.mp4
  python aplicar_cta.py --solo-png
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CTA_PNG = BASE_DIR / "assets" / "cta_berlinuno.png"


def obtener_binario(nombre: str) -> str:
    """Resuelve ffmpeg/ffprobe desde PATH o instalaciones comunes en Windows."""
    encontrado = shutil.which(nombre)
    if encontrado:
        return encontrado

    exe = f"{nombre}.exe" if os.name == "nt" and not nombre.endswith(".exe") else nombre
    local_app = Path(os.environ.get("LOCALAPPDATA", ""))
    candidatos = [
        local_app / "Microsoft" / "WinGet" / "Links" / exe,
        Path("C:/ffmpeg/bin") / exe,
    ]
    winget_pkgs = local_app / "Microsoft" / "WinGet" / "Packages"
    if winget_pkgs.is_dir():
        for p in winget_pkgs.glob(f"**/{exe}"):
            candidatos.append(p)
            break

    for c in candidatos:
        if c.is_file():
            return str(c)

    raise FileNotFoundError(f"No se encontró '{nombre}' en PATH ni en rutas conocidas.")


def _cargar_fuente(preferidas: list[str], size: int) -> ImageFont.FreeTypeFont:
    fonts_dir = Path("C:/Windows/Fonts")
    for nombre in preferidas:
        ruta = fonts_dir / nombre
        if ruta.is_file():
            return ImageFont.truetype(str(ruta), size)
    return ImageFont.load_default()


def generar_cta_png(salida_png: Path = DEFAULT_CTA_PNG) -> Path:
    """
    Dibuja la tarjeta CTA editorial recta (0deg) de 880x195 px con fondo transparente:
      - Contenedor blanco #FFFFFF con esquinas redondeadas (radius=22) y sombra difusa abajo
      - Píldora roja #FF0033 superior izquierda: ● EN VIVO EN YOUTUBE (20px bold)
      - Título extra-grueso #0B132B (40px): MIRALO EN VIVO EN @BERLINUNO
      - Subtítulo #334155 (26px bold): LUNES, MIÉRCOLES Y VIERNES • 18:00 HS
    """
    salida_png.parent.mkdir(parents=True, exist_ok=True)

    # Supersampling 2x para bordes, cápsula y tipografía ultra nítidos
    S = 2
    W, H = 880 * S, 195 * S

    # Margen transparente para alojar la sombra suave abajo sin recortes
    pad_x = 16 * S
    card_top = 4 * S
    card_bottom = 177 * S  # deja 18px debajo para la sombra difusa
    card_box = (pad_x, card_top, W - pad_x, card_bottom)
    card_radius = 22 * S

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # 1. Sombra suave difusa desplazada hacia abajo
    shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    shadow_box = (
        card_box[0],
        card_box[1] + 6 * S,
        card_box[2],
        card_box[3] + 6 * S,
    )
    shadow_draw.rounded_rectangle(
        shadow_box, radius=card_radius, fill=(11, 19, 43, 95)
    )
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=7 * S))
    canvas.alpha_composite(shadow_layer)

    # 2. Contenedor blanco puro #FFFFFF (0deg)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(card_box, radius=card_radius, fill=(255, 255, 255, 255))

    # Fuentes
    f_badge = _cargar_fuente(["segoeuib.ttf", "arialbd.ttf"], 20 * S)
    f_title = _cargar_fuente(["seguibl.ttf", "ariblk.ttf", "arialbd.ttf"], 40 * S)
    f_sub = _cargar_fuente(["segoeuib.ttf", "arialbd.ttf"], 26 * S)

    inner_x = card_box[0] + 28 * S
    y_cursor = card_top + 18 * S

    # 3. Píldora superior izquierda: ● EN VIVO EN YOUTUBE (#FF0033)
    badge_text = "EN VIVO EN YOUTUBE"
    tb = draw.textbbox((0, 0), badge_text, font=f_badge)
    text_w = tb[2] - tb[0]
    text_h = tb[3] - tb[1]

    dot_r = 5 * S
    dot_gap = 9 * S
    pill_pad_x = 14 * S
    pill_h = 34 * S
    pill_w = pill_pad_x * 2 + (dot_r * 2) + dot_gap + text_w
    pill_box = (inner_x, y_cursor, inner_x + pill_w, y_cursor + pill_h)

    draw.rounded_rectangle(pill_box, radius=pill_h // 2, fill=(255, 0, 51, 255))

    dot_cx = inner_x + pill_pad_x + dot_r
    dot_cy = y_cursor + pill_h // 2
    draw.ellipse(
        (dot_cx - dot_r, dot_cy - dot_r, dot_cx + dot_r, dot_cy + dot_r),
        fill=(255, 255, 255, 255),
    )

    tx_badge = dot_cx + dot_r + dot_gap - tb[0]
    ty_badge = y_cursor + (pill_h - text_h) // 2 - tb[1]
    draw.text((tx_badge, ty_badge), badge_text, font=f_badge, fill=(255, 255, 255, 255))

    # 4. Título principal: MIRALO EN VIVO EN @BERLINUNO (#0B132B)
    title_text = "MIRALO EN VIVO EN @BERLINUNO"
    y_title = y_cursor + pill_h + 12 * S
    ttb = draw.textbbox((0, 0), title_text, font=f_title)
    draw.text(
        (inner_x - ttb[0], y_title - ttb[1]),
        title_text,
        font=f_title,
        fill=(11, 19, 43, 255),
    )

    # 5. Subtítulo inferior: LUNES, MIÉRCOLES Y VIERNES • 18:00 HS (#334155)
    sub_y = y_title + (ttb[3] - ttb[1]) + 15 * S
    sub_left = "LUNES, MIÉRCOLES Y VIERNES"
    sub_right = "18:00 HS"

    # Usar anchor="la" (left-ascender) para que ambas cadenas compartan la línea base exacta
    s1 = draw.textbbox((0, 0), sub_left, font=f_sub, anchor="la")
    s_cap = draw.textbbox((0, 0), sub_right, font=f_sub, anchor="la")
    sub_color = (51, 65, 85, 255)

    draw.text(
        (inner_x, sub_y),
        sub_left,
        font=f_sub,
        fill=sub_color,
        anchor="la",
    )

    # Punto separador vectorial centrado verticalmente respecto a las mayúsculas
    cap_top = sub_y + s_cap[1]
    cap_bot = sub_y + s_cap[3]
    sep_gap = 15 * S
    sep_r = 3.5 * S
    sep_cx = inner_x + s1[2] + sep_gap + sep_r
    sep_cy = (cap_top + cap_bot) / 2
    draw.ellipse(
        (sep_cx - sep_r, sep_cy - sep_r, sep_cx + sep_r, sep_cy + sep_r),
        fill=sub_color,
    )

    right_x = sep_cx + sep_r + sep_gap
    draw.text(
        (right_x, sub_y),
        sub_right,
        font=f_sub,
        fill=sub_color,
        anchor="la",
    )

    final_img = canvas.resize((880, 195), Image.Resampling.LANCZOS)
    final_img.save(salida_png, format="PNG")
    print(f"[CTA] PNG generado: {salida_png} ({final_img.size[0]}x{final_img.size[1]})")
    return salida_png


def obtener_duracion_video(video_path: Path) -> float:
    ffprobe_exe = obtener_binario("ffprobe")
    res = subprocess.run(
        [
            ffprobe_exe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(res.stdout.strip())


def aplicar_cta_a_video(
    video_entrada: Path,
    video_salida: Optional[Path] = None,
    cta_png: Path = DEFAULT_CTA_PNG,
    duracion_cta: float = 6.0,
    pos_y: int = 115,
    fade_in: float = 0.25,
    en_lugar: bool = False,
) -> Path:
    if not video_entrada.is_file():
        raise FileNotFoundError(f"No existe el video de entrada: {video_entrada}")
    if not cta_png.is_file():
        generar_cta_png(cta_png)

    if en_lugar:
        destino_final = video_entrada
        video_render = video_entrada.with_name(f".{video_entrada.stem}_cta_tmp{video_entrada.suffix}")
    elif video_salida is None:
        destino_final = video_entrada.with_name(f"{video_entrada.stem}_cta{video_entrada.suffix}")
        video_render = destino_final
    else:
        destino_final = video_salida
        video_render = destino_final

    duracion_total = obtener_duracion_video(video_entrada)
    t_inicio = max(0.0, duracion_total - duracion_cta)
    ffmpeg_exe = obtener_binario("ffmpeg")

    filter_complex = (
        f"[1:v]format=rgba,fade=t=in:st={t_inicio:.3f}:d={fade_in:.2f}:alpha=1[cta];"
        f"[0:v][cta]overlay=(W-w)/2:{pos_y}:enable='between(t,{t_inicio:.3f},{duracion_total:.3f})':eof_action=pass[v]"
    )

    cmd = [
        ffmpeg_exe,
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-i",
        str(video_entrada),
        "-loop",
        "1",
        "-t",
        f"{duracion_total:.3f}",
        "-framerate",
        "30",
        "-i",
        str(cta_png),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
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
        "copy",
        "-movflags",
        "+faststart",
        str(video_render),
    ]

    print(
        f"[CTA] Superponiendo {cta_png.name} en {video_entrada.name} "
        f"(duracion={duracion_total:.2f}s, CTA={t_inicio:.2f}s->{duracion_total:.2f}s, y={pos_y})..."
    )
    subprocess.run(cmd, check=True)
    if en_lugar:
        os.replace(video_render, destino_final)
    print(f"[CTA] Listo -> {destino_final}")
    return destino_final


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera assets/cta_berlinuno.png y lo superpone al final de un Short MP4 o una carpeta."
    )
    parser.add_argument("video", nargs="?", help="Ruta al archivo MP4 de entrada.")
    parser.add_argument("--lote", help="Carpeta con MP4s a procesar en lote (sobrescribe en lugar salvo --sufijo-cta).")
    parser.add_argument("--en-lugar", action="store_true", help="Reemplaza el MP4 original de forma atómica.")
    parser.add_argument("--sufijo-cta", action="store_true", help="En --lote, guarda como <nombre>_cta.mp4 sin pisar el original.")
    parser.add_argument("--omitir", nargs="*", default=[], help="Nombres de archivo a omitir en --lote.")
    parser.add_argument("--salida", help="Ruta del MP4 de salida (default: <nombre>_cta.mp4).")
    parser.add_argument("--cta", default=str(DEFAULT_CTA_PNG), help="Ruta al PNG CTA transparente.")
    parser.add_argument("--duracion-cta", type=float, default=6.0, help="Segundos finales (default: 6).")
    parser.add_argument("--y", type=int, default=115, help="Posición Y del CTA (default: 115).")
    parser.add_argument("--fade", type=float, default=0.25, help="Duración fade-in en segundos (default: 0.25).")
    parser.add_argument("--solo-png", action="store_true", help="Solo genera/regenera el PNG CTA.")
    args = parser.parse_args()

    cta_path = Path(args.cta)
    if args.solo_png:
        generar_cta_png(cta_path)
        return

    if args.lote:
        carpeta = Path(args.lote)
        if not carpeta.is_dir():
            raise FileNotFoundError(f"No existe la carpeta: {carpeta}")
        generar_cta_png(cta_path)
        omitir = set(args.omitir)
        videos = sorted(
            p for p in carpeta.glob("*.mp4")
            if not p.name.startswith(".") and not p.stem.endswith("_cta") and p.name not in omitir
        )
        print(f"[CTA Lote] Procesando {len(videos)} videos en {carpeta}...")
        for idx, v in enumerate(videos, 1):
            print(f"\n[{idx}/{len(videos)}] {v.name}")
            aplicar_cta_a_video(
                video_entrada=v,
                cta_png=cta_path,
                duracion_cta=args.duracion_cta,
                pos_y=args.y,
                fade_in=args.fade,
                en_lugar=not args.sufijo_cta,
            )
        print(f"\n[CTA Lote] Terminados {len(videos)} clips.")
        return

    if not args.video:
        parser.error("Debes pasar la ruta al MP4, --lote <carpeta> o --solo-png.")

    generar_cta_png(cta_path)
    aplicar_cta_a_video(
        video_entrada=Path(args.video),
        video_salida=Path(args.salida) if args.salida else None,
        cta_png=cta_path,
        duracion_cta=args.duracion_cta,
        pos_y=args.y,
        fade_in=args.fade,
        en_lugar=args.en_lugar,
    )


if __name__ == "__main__":
    main()
