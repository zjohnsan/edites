"""
lote_gta6_ep2.py — Pipeline en lote para 7 Shorts de GTA 6 Episodio 2
Usando Python + yt-dlp + faster-whisper + Pillow + FFmpeg puro (sin Remotion ni música de fondo).

Uso:
  python lote_gta6_ep2.py --test-encuadre
  python lote_gta6_ep2.py --ejecutar
"""

from __future__ import annotations

import argparse
import ctypes
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from faster_whisper import WhisperModel
from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE_DIR = Path(__file__).resolve().parent
EP2_URL = "https://www.youtube.com/watch?v=F-Jho0kXwnc"

TEMP_DIR = BASE_DIR / "temp_gta6_ep2"
TRAMOS_DIR = TEMP_DIR / "tramos_1080p"
UNIDOS_DIR = TEMP_DIR / "unidos"
CARDS_DIR = TEMP_DIR / "cards"
TEST_ENCUADRE_JPG = TEMP_DIR / "test_encuadre_ep2.jpg"

SALIDA_BASE = BASE_DIR / "clips_gta6_ep2"
LISTOS_DIR = SALIDA_BASE / "listos"
SUBS_DIR = SALIDA_BASE / "subs"
RESUMEN_TXT = SALIDA_BASE / "TITULOS_Y_RESUMEN.txt"
CTA_PNG = BASE_DIR / "assets" / "cta_berlinuno.png"

# Coordenadas ajustadas al Ep. 2 tras verificar test_encuadre_ep2.jpg (0px bordes)
DEFAULT_CAM_CROP = "456:300:0:235"
DEFAULT_GAME_CROP = "972:1080:508:0"

STOPWORDS_ES = {
    "A", "AL", "CON", "DE", "DEL", "EL", "ELLA", "ELLOS", "EN", "ES", "ESA",
    "ESE", "ESO", "ESTA", "ESTE", "ESTO", "HA", "HAY", "LA", "LAS", "LE",
    "LES", "LO", "LOS", "ME", "MI", "MIS", "MUY", "NO", "NOS", "O", "OS",
    "PARA", "PERO", "POR", "QUE", "QUÉ", "SE", "SI", "SÍ", "SIN", "SOY",
    "SU", "SUS", "TE", "TI", "TU", "TÚ", "UN", "UNA", "UNO", "UNOS", "Y",
    "YA", "YO",
}

PALABRAS_IMPACTO = {
    "BUG", "MILLONES", "DESARROLLADORES", "TRUCO", "RETROVISORES", "MAPA",
    "PRESIÓN", "PRESION", "ESPERANZA", "MUERE", "MANGLARES", "MACUMBA",
    "SUSTO", "SCOOTER", "CONTRATO", "SHOW", "MENTIROSA", "ARMERÍA", "ARMERIA",
    "RESISTENCIA", "TRIPLE", "IMPOSIBLE", "GTA", "PRIMERA", "PERSONA", "OLAS",
    "PIEDRA", "PROGRAMADOR", "FLOTANDO",
}

MULETILLAS_RUIDO = {"EH", "EHH", "EHHH", "MM", "MMM", "AH", "AHH", "UM", "UMM"}

CLIPS_EP2 = [
    {
        "id": "01_piedra_flotante",
        "tarjeta_inicial": {
            "badge": "★ BUG",
            "texto": "BUG DE $2.000 MILLONES EN GTA 6",
            "duracion": 2.5,
        },
        "partes": [
            {"inicio": "00:15:01", "fin": "00:15:11", "tarjeta": None},
            {"inicio": "00:15:40", "fin": "00:15:52", "tarjeta": None},
            {"inicio": "00:16:00", "fin": "00:16:28", "tarjeta": None},
        ],
        "titulo_youtube": "Encuentran un bug de $2.000 millones en GTA 6 y lo arreglan 🪨😂 @berlinuno #shorts",
    },
    {
        "id": "02_primera_persona",
        "tarjeta_inicial": {
            "badge": "★ TRUCO",
            "texto": "TRUCO: PRIMERA PERSONA EN GTA 6",
            "duracion": 2.5,
        },
        "partes": [
            {"inicio": "01:20:19", "fin": "01:20:25", "tarjeta": None},
            {
                "inicio": "01:19:35",
                "fin": "01:19:46",
                "tarjeta": {"badge": "★ TUTORIAL", "texto": "CÓMO SE ACTIVA", "duracion": 1.5},
            },
            {"inicio": "01:21:02", "fin": "01:21:14", "tarjeta": None},
            {"inicio": "01:21:33", "fin": "01:21:45", "tarjeta": None},
            {"inicio": "01:30:27", "fin": "01:30:38", "tarjeta": None},
        ],
        "titulo_youtube": "El truco secreto para jugar GTA 6 en primera persona 👀🔥 @berlinuno #shorts",
    },
    {
        "id": "03_limite_mapa",
        "tarjeta_inicial": {
            "badge": "★ PRUEBA",
            "texto": "¿QUÉ PASA AL FINAL DEL MAPA DE GTA 6?",
            "duracion": 2.5,
        },
        "partes": [
            {"inicio": "00:07:42", "fin": "00:07:57", "tarjeta": None},
            {
                "inicio": "00:20:13",
                "fin": "00:20:24",
                "tarjeta": {"badge": "★ TIEMPO", "texto": "15 MINUTOS DESPUÉS...", "duracion": 1.5},
            },
            {"inicio": "00:23:15", "fin": "00:23:59", "tarjeta": None},
        ],
        "titulo_youtube": "¿Qué pasa si llegás al límite del mapa en GTA 6? 🌊😱 @berlinuno #shorts",
    },
    {
        "id": "04_senor_manglares",
        "tarjeta_inicial": {
            "badge": "★ EASTER EGG",
            "texto": "EL EASTER EGG MÁS TURBIO DE GTA 6",
            "duracion": 2.5,
        },
        "partes": [
            {"inicio": "01:24:11", "fin": "01:24:17", "tarjeta": None},
            {"inicio": "01:24:30", "fin": "01:24:37", "tarjeta": None},
            {"inicio": "01:25:40", "fin": "01:25:55", "tarjeta": None},
            {"inicio": "01:26:22", "fin": "01:26:32", "tarjeta": None},
            {
                "inicio": "01:51:22",
                "fin": "01:51:39",
                "tarjeta": {"badge": "★ NOTICIA", "texto": "DESPUÉS EN REDES...", "duracion": 1.5},
            },
        ],
        "titulo_youtube": 'Se cruzan con el "Señor Manglares" en primera persona en GTA 6 💀🌲 @berlinuno #shorts',
    },
    {
        "id": "05_abuela_scooter",
        "tarjeta_inicial": {
            "badge": "★ IA GTA 6",
            "texto": "LA IA DE ESTA SEÑORA EN GTA 6",
            "duracion": 2.5,
        },
        "partes": [
            {"inicio": "01:45:39", "fin": "01:45:47", "tarjeta": None},
            {"inicio": "01:46:17", "fin": "01:46:25", "tarjeta": None},
            {"inicio": "01:46:35", "fin": "01:46:49", "tarjeta": None},
            {"inicio": "01:46:59", "fin": "01:47:14", "tarjeta": None},
        ],
        "titulo_youtube": "Le roban el scooter a una señora en GTA 6 y hace tremendo show 😂🛵 @berlinuno #shorts",
    },
    {
        "id": "06_armeria_loquito",
        "tarjeta_inicial": {
            "badge": "★ DETALLE",
            "texto": "LO QUE PODÉS HACER EN GTA 6",
            "duracion": 2.5,
        },
        "partes": [
            {"inicio": "01:13:48", "fin": "01:14:04", "tarjeta": None},
            {"inicio": "01:15:09", "fin": "01:15:34", "tarjeta": None},
        ],
        "titulo_youtube": "Prueban esto en GTA 6 y entran así a la armería 😱😂 @berlinuno #shorts",
    },
    {
        "id": "07_triplazo_imposible",
        "tarjeta_inicial": {
            "badge": "★ CLIP",
            "texto": "EL TIRO MÁS IMPOSIBLE EN GTA 6",
            "duracion": 2.5,
        },
        "partes": [
            {"inicio": "02:15:07", "fin": "02:15:48", "tarjeta": None},
        ],
        "titulo_youtube": "Mete el triple más imposible en GTA 6 🏀🔥 @berlinuno #shorts",
    },
]


# ---------------------------------------------------------------------------
# Utilidades del sistema y binarios
# ---------------------------------------------------------------------------

def obtener_binario(nombre: str) -> str:
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

    raise FileNotFoundError(f"No se encontró '{nombre}' en PATH ni en rutas habituales.")


def hhmmss_a_seg(ts: str) -> float:
    p = [float(x) for x in ts.strip().split(":")]
    if len(p) == 3:
        return p[0] * 3600 + p[1] * 60 + p[2]
    if len(p) == 2:
        return p[0] * 60 + p[1]
    return p[0]


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


def obtener_ram_libre_gb() -> float:
    """Devuelve RAM física disponible en GB en Windows."""
    if os.name != "nt":
        return 4.0

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    return stat.ullAvailPhys / (1024 ** 3)


# ---------------------------------------------------------------------------
# Descarga rápida de tramos 1080p y test de encuadre
# ---------------------------------------------------------------------------

_URLS_1080P_CACHE: dict[str, tuple[str, str]] = {}


def _resolver_urls_1080p(url: str) -> Optional[tuple[str, str]]:
    if url in _URLS_1080P_CACHE:
        return _URLS_1080P_CACHE[url]

    formatos = [
        "137+140/bestvideo[height=1080][ext=mp4]+bestaudio[ext=m4a]",
        "bestvideo[height<=1080]+bestaudio",
    ]
    for fmt in formatos:
        res = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--no-check-certificates", "-f", fmt, "-g", url],
            capture_output=True,
            text=True,
            check=False,
        )
        lines = [l.strip() for l in res.stdout.splitlines() if l.strip().startswith("http")]
        if res.returncode == 0 and len(lines) >= 2:
            _URLS_1080P_CACHE[url] = (lines[0], lines[1])
            return _URLS_1080P_CACHE[url]
    return None


def descargar_tramo_1080p(
    url: str, inicio: str, fin: str, destino: Path, forzar: bool = False
) -> Path:
    """Descarga el tramo exacto en 1080p usando URLs directas (-ss/-to) con fallback a --download-sections."""
    TRAMOS_DIR.mkdir(parents=True, exist_ok=True)
    if destino.is_file() and destino.stat().st_size > 100_000 and not forzar:
        return destino

    ffmpeg_exe = obtener_binario("ffmpeg")
    dur = max(1.0, hhmmss_a_seg(fin) - hhmmss_a_seg(inicio))

    urls = _resolver_urls_1080p(url)
    if urls is not None:
        v_url, a_url = urls
        print(f"  [1080p directo] {inicio} -> {fin} ({dur:.0f}s) -> {destino.name}")
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
                f"{dur:.2f}",
                "-i",
                v_url,
                "-ss",
                inicio,
                "-t",
                f"{dur:.2f}",
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

    print(f"  [yt-dlp sections fallback] {inicio} -> {fin} -> {destino.name}")
    subprocess.run(
        [
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
        ],
        check=True,
    )
    return destino


def generar_test_encuadre(
    url: str,
    timestamp: str = "00:15:05",
    cam_crop: str = DEFAULT_CAM_CROP,
    game_crop: str = DEFAULT_GAME_CROP,
    forzar: bool = True,
) -> Path:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    t0 = hhmmss_a_seg(timestamp)
    t1 = t0 + 4.0
    fin_ts = f"{int(t1 // 3600):02d}:{int((t1 % 3600) // 60):02d}:{int(t1 % 60):02d}"
    src_mp4 = TEMP_DIR / "test_encuadre_src_ep2.mp4"
    descargar_tramo_1080p(url, timestamp, fin_ts, src_mp4, forzar=forzar)

    ffmpeg_exe = obtener_binario("ffmpeg")
    fc = (
        f"[0:v]crop={cam_crop},scale=1080:720,setsar=1[cam];"
        f"[0:v]crop={game_crop},scale=1080:1200,setsar=1[game];"
        "[cam][game]vstack=inputs=2,format=yuv420p[v]"
    )
    subprocess.run(
        [
            ffmpeg_exe,
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-ss",
            "2.0",
            "-i",
            str(src_mp4),
            "-filter_complex",
            fc,
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
    print(f"[Test Encuadre Ep2] Guardado en {TEST_ENCUADRE_JPG}")
    return TEST_ENCUADRE_JPG


# ---------------------------------------------------------------------------
# Tarjetas editoriales blancas con Pillow (PNG transparente, 0deg)
# ---------------------------------------------------------------------------

def _cargar_fuente(preferidas: list[str], size: int) -> ImageFont.FreeTypeFont:
    fonts_dir = Path("C:/Windows/Fonts")
    for nombre in preferidas:
        ruta = fonts_dir / nombre
        if ruta.is_file():
            return ImageFont.truetype(str(ruta), size)
    return ImageFont.load_default()


def _dibujar_estrella(draw: ImageDraw.ImageDraw, cx: float, cy: float, r_ext: float, r_int: float, fill: tuple[int, int, int, int]) -> None:
    import math
    pts = []
    for k in range(10):
        ang = -math.pi / 2 + k * (math.pi / 5)
        r = r_ext if k % 2 == 0 else r_int
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    draw.polygon(pts, fill=fill)


def _envolver_texto(draw: ImageDraw.ImageDraw, texto: str, fuente: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    palabras = texto.split()
    lineas: list[str] = []
    actual: list[str] = []
    for p in palabras:
        cand = " ".join(actual + [p])
        box = draw.textbbox((0, 0), cand, font=fuente)
        if actual and (box[2] - box[0]) > max_w:
            lineas.append(" ".join(actual))
            actual = [p]
        else:
            actual.append(p)
    if actual:
        lineas.append(" ".join(actual))
    return lineas


def generar_tarjeta_editorial_png(badge: str, texto: str, salida_png: Path) -> Path:
    """
    Genera tarjeta editorial blanca recta (0deg) en PNG transparente:
      - Contenedor #FFFFFF (borderRadius=18) con sombra suave abajo
      - Badge azul marino #0B132B arriba a la izquierda (texto blanco bold)
      - Titular extra-grueso #0B132B en mayúsculas (1 o 2 líneas centradas/izquierda)
    """
    salida_png.parent.mkdir(parents=True, exist_ok=True)
    S = 2
    W = 880 * S
    pad_x = 16 * S
    pad_inner_x = 28 * S
    max_text_w = (W - pad_x * 2) - pad_inner_x * 2

    f_badge = _cargar_fuente(["segoeuib.ttf", "arialbd.ttf"], 18 * S)
    f_title = _cargar_fuente(["seguibl.ttf", "ariblk.ttf", "arialbd.ttf"], 36 * S)

    dummy = Image.new("RGBA", (W, 400 * S), (0, 0, 0, 0))
    ddraw = ImageDraw.Draw(dummy)
    lineas = _envolver_texto(ddraw, texto.upper(), f_title, max_text_w)
    if len(lineas) > 2:
        f_title = _cargar_fuente(["seguibl.ttf", "ariblk.ttf", "arialbd.ttf"], 31 * S)
        lineas = _envolver_texto(ddraw, texto.upper(), f_title, max_text_w)

    pill_h = 32 * S
    line_h = 44 * S
    gap_badge_title = 12 * S
    pad_top = 18 * S
    pad_bot = 20 * S
    card_h = pad_top + pill_h + gap_badge_title + (len(lineas) * line_h) + pad_bot
    H = card_h + 22 * S  # deja espacio abajo para la sombra suave sin recortar

    card_top = 4 * S
    card_box = (pad_x, card_top, W - pad_x, card_top + card_h)
    radius = 18 * S

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # Sombra suave difusa abajo
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.rounded_rectangle(
        (card_box[0], card_box[1] + 6 * S, card_box[2], card_box[3] + 6 * S),
        radius=radius,
        fill=(11, 19, 43, 92),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=7 * S))
    canvas.alpha_composite(shadow)

    # Caja blanca #FFFFFF (0deg)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(card_box, radius=radius, fill=(255, 255, 255, 255))

    inner_x = card_box[0] + pad_inner_x
    cur_y = card_top + pad_top

    # Badge azul marino #0B132B
    badge_clean = badge.strip().upper()
    tiene_estrella = badge_clean.startswith("★")
    badge_label = badge_clean.lstrip("★").strip() if tiene_estrella else badge_clean

    tb = draw.textbbox((0, 0), badge_label, font=f_badge, anchor="la")
    pill_pad_x = 14 * S
    star_space = (18 * S) if tiene_estrella else 0
    pill_w = pill_pad_x * 2 + star_space + (tb[2] - tb[0])
    draw.rounded_rectangle(
        (inner_x, cur_y, inner_x + pill_w, cur_y + pill_h),
        radius=pill_h // 2,
        fill=(11, 19, 43, 255),
    )

    tx_b = inner_x + pill_pad_x
    if tiene_estrella:
        _dibujar_estrella(
            draw,
            cx=tx_b + 6 * S,
            cy=cur_y + pill_h / 2,
            r_ext=6.5 * S,
            r_int=2.8 * S,
            fill=(255, 229, 0, 255),
        )
        tx_b += star_space

    # Centrado vertical aproximado del texto en cápsula
    b_box = draw.textbbox((0, 0), badge_label, font=f_badge)
    b_h = b_box[3] - b_box[1]
    draw.text(
        (tx_b - b_box[0], cur_y + (pill_h - b_h) / 2 - b_box[1]),
        badge_label,
        font=f_badge,
        fill=(255, 255, 255, 255),
    )

    # Titular extra-grueso #0B132B
    y_t = cur_y + pill_h + gap_badge_title
    for ln in lineas:
        draw.text((inner_x, y_t), ln, font=f_title, fill=(11, 19, 43, 255), anchor="la")
        y_t += line_h

    final_w, final_h = W // S, H // S
    canvas.resize((final_w, final_h), Image.Resampling.LANCZOS).save(salida_png, format="PNG")
    return salida_png


# ---------------------------------------------------------------------------
# Subtítulos .ass dinámicos (faster-whisper medium / fallback small)
# ---------------------------------------------------------------------------

def formato_tiempo_ass(segundos: float) -> str:
    segundos = max(0.0, float(segundos))
    cent_tot = int(round(segundos * 100))
    cc = cent_tot % 100
    seg_tot = cent_tot // 100
    ss = seg_tot % 60
    min_tot = seg_tot // 60
    mm = min_tot % 60
    hh = min_tot // 60
    return f"{hh}:{mm:02d}:{ss:02d}.{cc:02d}"


def _limpiar_palabra(raw: str) -> tuple[str, bool]:
    txt = raw.strip()
    if not txt:
        return "", False
    pausa_fuerte = bool(re.search(r"[.?!,;:\u2026]+$", txt))
    txt = re.sub(r"[^\w\sáéíóúüñÁÉÍÓÚÜÑ¿¡?!$]", "", txt, flags=re.UNICODE)
    txt = txt.replace("_", "").strip().upper()
    if not re.search(r"[A-ZÁÉÍÓÚÜÑ0-9]", txt):
        return "", pausa_fuerte
    if txt in MULETILLAS_RUIDO:
        return "", pausa_fuerte
    txt = txt.replace("¿", "")
    return txt, pausa_fuerte


def cargar_modelo_whisper(preferido: str = "auto") -> tuple[WhisperModel, str]:
    libre_gb = obtener_ram_libre_gb()
    if preferido == "auto":
        orden = ["medium", "small"] if libre_gb >= 1.75 else ["small", "base"]
        print(f"[Whisper] RAM libre detectada: {libre_gb:.2f} GB -> orden de modelos: {orden}")
    else:
        orden = [preferido, "small"] if preferido != "small" else ["small", "base"]

    ultimo_err = None
    for nombre in orden:
        try:
            print(f"[Whisper] Cargando model='{nombre}' (compute_type='int8')...")
            m = WhisperModel(nombre, device="cpu", compute_type="int8")
            return m, nombre
        except Exception as exc:
            print(f"[Whisper] Aviso cargando '{nombre}': {exc}")
            ultimo_err = exc
    raise RuntimeError(f"No se pudo cargar ningún modelo Whisper: {ultimo_err}")


def transcribir_palabras_limpias(video_path: Path, model: WhisperModel) -> list[dict]:
    segments, _ = model.transcribe(
        str(video_path),
        language="es",
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
    )

    tokens_raw: list[dict] = []
    for seg in segments:
        if not getattr(seg, "words", None):
            continue
        for w in seg.words:
            raw_txt = w.word or ""
            # Unir sub-tokens de una misma palabra que no empiezan con espacio
            if (
                tokens_raw
                and raw_txt
                and not raw_txt[0].isspace()
                and not re.match(r"^[.?!,;:\u2026]+$", raw_txt.strip())
                and not re.search(r"[.?!,;:\u2026]$", tokens_raw[-1]["raw"].strip())
            ):
                tokens_raw[-1]["raw"] += raw_txt
                tokens_raw[-1]["end"] = float(w.end)
            else:
                tokens_raw.append(
                    {"raw": raw_txt, "start": float(w.start), "end": float(w.end)}
                )

    palabras: list[dict] = []
    for tok in tokens_raw:
        limpia, pausa = _limpiar_palabra(tok["raw"])
        if not limpia:
            continue
        palabras.append(
            {
                "text": limpia,
                "start": tok["start"],
                "end": tok["end"],
                "break_after": pausa,
            }
        )
    return palabras


def agrupar_bloques_shorts(
    palabras: list[dict],
    max_palabras: int = 4,
    pausa_corte: float = 0.35,
    max_chars: int = 24,
) -> list[dict]:
    if not palabras:
        return []

    bloques: list[list[dict]] = []
    actual: list[dict] = []
    for w in palabras:
        if actual:
            gap = w["start"] - actual[-1]["end"]
            nuevo_len = sum(len(x["text"]) for x in actual) + len(actual) + len(w["text"])
            if (
                len(actual) >= max_palabras
                or gap > pausa_corte
                or actual[-1]["break_after"]
                or (len(actual) >= 2 and nuevo_len > max_chars)
            ):
                bloques.append(actual)
                actual = []
        actual.append(w)
    if actual:
        bloques.append(actual)

    fusionados: list[list[dict]] = []
    i = 0
    while i < len(bloques):
        b = bloques[i]
        if len(b) == 1 and i + 1 < len(bloques):
            nxt = bloques[i + 1]
            if len(nxt) < max_palabras and (nxt[0]["start"] - b[-1]["end"]) <= pausa_corte and not b[-1]["break_after"]:
                bloques[i + 1] = b + nxt
                i += 1
                continue
        if len(b) == 1 and fusionados:
            prev = fusionados[-1]
            if len(prev) < max_palabras and (b[0]["start"] - prev[-1]["end"]) <= 0.25 and not prev[-1]["break_after"]:
                fusionados[-1] = prev + b
                i += 1
                continue
        fusionados.append(b)
        i += 1

    eventos: list[dict] = []
    for idx, b in enumerate(fusionados):
        t_ini = b[0]["start"]
        t_fin = max(b[-1]["end"] + 0.12, t_ini + 0.45)
        if idx + 1 < len(fusionados):
            nxt_ini = fusionados[idx + 1][0]["start"]
            if t_fin > nxt_ini - 0.02:
                t_fin = max(t_ini + 0.18, nxt_ini - 0.02)
        eventos.append({"words": [x["text"] for x in b], "start": t_ini, "end": t_fin})
    return eventos


def _elegir_indice_clave(words: list[str]) -> int:
    if len(words) == 1:
        return 0

    def bare(w: str) -> str:
        return re.sub(r"[?!¡¿.,]", "", w)

    for i in range(len(words) - 1, -1, -1):
        bw = bare(words[i])
        if bw in PALABRAS_IMPACTO or re.search(r"\d", bw) or "?" in words[i] or "!" in words[i]:
            return i

    mejor_idx = -1
    mejor_len = -1
    for i, w in enumerate(words):
        bw = bare(w)
        if bw in STOPWORDS_ES:
            continue
        if len(bw) >= mejor_len:
            mejor_len = len(bw)
            mejor_idx = i
    return mejor_idx if mejor_idx >= 0 else len(words) - 1


def generar_ass_para_clip(clip_id: str, video_unido: Path, salida_ass: Path, model: WhisperModel) -> Path:
    palabras = transcribir_palabras_limpias(video_unido, model)
    eventos = agrupar_bloques_shorts(palabras)

    header = f"""[Script Info]
Title: Subtitulos Dinamicos Shorts - {clip_id}
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Shorts,Arial Black,54,&H00FFFFFF,&H0000E5FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,2,8,80,80,742,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lineas = []
    for ev in eventos:
        ini = formato_tiempo_ass(ev["start"])
        fin = formato_tiempo_ass(ev["end"])
        idx = _elegir_indice_clave(ev["words"])
        txt = " ".join(
            f"{{\\c&H0000E5FF&}}{w}{{\\c&H00FFFFFF&}}" if i == idx else w
            for i, w in enumerate(ev["words"])
        )
        lineas.append(f"Dialogue: 0,{ini},{fin},Shorts,,0,0,0,,{txt}")

    salida_ass.parent.mkdir(parents=True, exist_ok=True)
    salida_ass.write_text(header + "\n".join(lineas) + "\n", encoding="utf-8-sig")
    print(f"  [Subtitulos] {len(palabras)} palabras -> {len(lineas)} bloques en {salida_ass.name}")
    return salida_ass


def _escapar_ruta_ass(ruta: Path) -> str:
    try:
        s = ruta.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        s = ruta.resolve().as_posix()
    return s.replace("\\", "/").replace(":", "\\:")


# ---------------------------------------------------------------------------
# Ensamblado + tarjetas + subtítulos + CTA últimos 3.5s
# ---------------------------------------------------------------------------

def unir_partes_split_screen(
    clip_id: str,
    partes_mp4: list[Path],
    salida_unida: Path,
    cam_crop: str,
    game_crop: str,
) -> list[float]:
    """Une todas las partes en 1080x1920 9:16 con corte seco y devuelve las duraciones reales de cada parte."""
    UNIDOS_DIR.mkdir(parents=True, exist_ok=True)
    ffmpeg_exe = obtener_binario("ffmpeg")
    duraciones_reales = [obtener_duracion_video(p) for p in partes_mp4]

    split_tpl = (
        "[{i}:v]crop=" + cam_crop + ",scale=1080:720,setsar=1[cam{i}];"
        "[{i}:v]crop=" + game_crop + ",scale=1080:1200,setsar=1[game{i}];"
        "[cam{i}][game{i}]vstack=inputs=2,fps=30,format=yuv420p,setpts=PTS-STARTPTS[v{i}];"
        "[{i}:a]asetpts=PTS-STARTPTS[a{i}]"
    )

    inputs: list[str] = []
    filtros: list[str] = []
    streams_concat: list[str] = []
    for i, p in enumerate(partes_mp4):
        inputs.extend(["-i", str(p)])
        filtros.append(split_tpl.format(i=i))
        streams_concat.append(f"[v{i}][a{i}]")

    if len(partes_mp4) == 1:
        v_map = "[v0]"
        a_map = "[a0]"
    else:
        filtros.append(f"{''.join(streams_concat)}concat=n={len(partes_mp4)}:v=1:a=1[vc][ac]")
        v_map = "[vc]"
        a_map = "[ac]"

    subprocess.run(
        [
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
            a_map,
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
            str(salida_unida),
        ],
        check=True,
    )
    return duraciones_reales


def renderizar_final_clip(
    clip: dict,
    video_unido: Path,
    duraciones_partes: list[float],
    archivo_ass: Path,
    salida_final: Path,
) -> float:
    """Superpone tarjetas (inicial + transición), CTA en últimos 3.5s y quema .ass."""
    LISTOS_DIR.mkdir(parents=True, exist_ok=True)
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    if not CTA_PNG.is_file():
        raise FileNotFoundError(f"Falta el cartel CTA reutilizable: {CTA_PNG}")

    ffmpeg_exe = obtener_binario("ffmpeg")
    dur_total = obtener_duracion_video(video_unido)

    # Construir lista de overlays [(png_path, t_start, t_end, fade_in_dur)]
    overlays: list[tuple[Path, float, float, float]] = []

    # 1. Tarjeta inicial (00:00 -> 00:02.5)
    t_ini = clip["tarjeta_inicial"]
    ini_png = CARDS_DIR / f"{clip['id']}_card_0.png"
    generar_tarjeta_editorial_png(t_ini["badge"], t_ini["texto"], ini_png)
    overlays.append((ini_png, 0.0, float(t_ini["duracion"]), 0.16))

    # 2. Tarjetas de transición al inicio de sus partes correspondientes
    acum = 0.0
    for idx_p, (parte, dur_p) in enumerate(zip(clip["partes"], duraciones_partes)):
        if parte.get("tarjeta"):
            tc = parte["tarjeta"]
            tc_png = CARDS_DIR / f"{clip['id']}_card_p{idx_p + 1}.png"
            generar_tarjeta_editorial_png(tc["badge"], tc["texto"], tc_png)
            overlays.append((tc_png, acum, acum + float(tc["duracion"]), 0.15))
        acum += dur_p

    # 3. CTA final (últimos 3.5s sin pisar tarjetas anteriores)
    cta_start = max(0.0, dur_total - 3.5)
    overlays.append((CTA_PNG, cta_start, dur_total, 0.25))

    inputs = ["-i", str(video_unido)]
    filtros: list[str] = []
    cur_v = "0:v"

    for idx_ov, (png_path, st, en, fd) in enumerate(overlays, start=1):
        inputs.extend(["-loop", "1", "-t", f"{dur_total:.3f}", "-framerate", "30", "-i", str(png_path)])
        fade_out_part = ""
        # Pequeño fade out para tarjetas (no necesario para CTA que muere con el fin del clip)
        if png_path != CTA_PNG and en < dur_total - 0.5:
            fade_out_st = max(st + fd, en - 0.15)
            fade_out_part = f",fade=t=out:st={fade_out_st:.3f}:d=0.15:alpha=1"
        filtros.append(
            f"[{idx_ov}:v]format=rgba,fade=t=in:st={st:.3f}:d={fd:.2f}:alpha=1{fade_out_part}[ov{idx_ov}]"
        )
        nxt_v = f"vov{idx_ov}"
        filtros.append(
            f"[{cur_v}][ov{idx_ov}]overlay=(W-w)/2:115:enable='between(t,{st:.3f},{en:.3f})':eof_action=pass[{nxt_v}]"
        )
        cur_v = nxt_v

    ass_esc = _escapar_ruta_ass(archivo_ass)
    filtros.append(f"[{cur_v}]ass='{ass_esc}'[vfinal]")

    subprocess.run(
        [
            ffmpeg_exe,
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
            *inputs,
            "-filter_complex",
            ";".join(filtros),
            "-map",
            "[vfinal]",
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
            str(salida_final),
        ],
        check=True,
    )
    return obtener_duracion_video(salida_final)


def ejecutar_lote(
    url: str,
    cam_crop: str,
    game_crop: str,
    modelo: str,
    solo_ids: Optional[set[str]] = None,
    forzar: bool = False,
) -> None:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    SALIDA_BASE.mkdir(parents=True, exist_ok=True)
    LISTOS_DIR.mkdir(parents=True, exist_ok=True)
    SUBS_DIR.mkdir(parents=True, exist_ok=True)

    whisper_model, nombre_modelo = cargar_modelo_whisper(modelo)
    resumen_lines = [
        "RESUMEN DE SHORTS — GTA 6 EPISODIO 2",
        f"Fuente: {url}",
        f"Whisper usado: {nombre_modelo} (int8, language=es, word_timestamps=True)",
        "=" * 72,
        "",
    ]

    clips_a_procesar = [c for c in CLIPS_EP2 if not solo_ids or c["id"] in solo_ids]
    print(f"[Lote Ep2] Procesando {len(clips_a_procesar)} clips...")

    for idx, clip in enumerate(clips_a_procesar, 1):
        cid = clip["id"]
        print(f"\n[{idx}/{len(clips_a_procesar)}] === {cid} ===")

        partes_mp4: list[Path] = []
        for p_idx, parte in enumerate(clip["partes"], 1):
            tramo_mp4 = TRAMOS_DIR / f"{cid}_p{p_idx}.mp4"
            descargar_tramo_1080p(url, parte["inicio"], parte["fin"], tramo_mp4, forzar=forzar)
            partes_mp4.append(tramo_mp4)

        video_unido = UNIDOS_DIR / f"{cid}_unido.mp4"
        print(f"  [Concat 9:16] Uniendo {len(partes_mp4)} parte(s) con corte seco...")
        duraciones_partes = unir_partes_split_screen(cid, partes_mp4, video_unido, cam_crop, game_crop)

        ass_path = SUBS_DIR / f"{cid}.ass"
        generar_ass_para_clip(cid, video_unido, ass_path, whisper_model)

        salida_final = LISTOS_DIR / f"{cid}.mp4"
        print(f"  [Render Final] Tarjetas + CTA últimos 3.5s + Subtítulos -> {salida_final.name}...")
        dur_final = renderizar_final_clip(clip, video_unido, duraciones_partes, ass_path, salida_final)
        print(f"  OK -> {salida_final} ({dur_final:.1f}s)")

        resumen_lines.extend(
            [
                f"Archivo:   {salida_final.name}",
                f"Duración:  {dur_final:.1f}s",
                f"Título YT: {clip['titulo_youtube']}",
                "-" * 72,
            ]
        )

    RESUMEN_TXT.write_text("\n".join(resumen_lines) + "\n", encoding="utf-8")
    print(f"\n[Lote Ep2] Completado! Resumen en {RESUMEN_TXT}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline Shorts GTA 6 Episodio 2")
    parser.add_argument("--url", default=EP2_URL, help="URL del VOD de YouTube")
    parser.add_argument("--test-encuadre", action="store_true", help="Genera temp_gta6_ep2/test_encuadre_ep2.jpg")
    parser.add_argument("--timestamp-test", default="00:15:05", help="Timestamp para test_encuadre_ep2.jpg")
    parser.add_argument("--ejecutar", action="store_true", help="Ejecuta el lote completo de los 7 clips")
    parser.add_argument("--cam-crop", default=DEFAULT_CAM_CROP, help="Crop webcam W:H:X:Y")
    parser.add_argument("--game-crop", default=DEFAULT_GAME_CROP, help="Crop gameplay W:H:Y")
    parser.add_argument("--modelo", default="auto", help="Modelo Whisper: auto | medium | small | base")
    parser.add_argument("--solo", nargs="*", help="Procesar solo ciertos IDs")
    parser.add_argument("--forzar", action="store_true", help="Re-descarga tramos existentes")
    args = parser.parse_args()

    if args.test_encuadre:
        generar_test_encuadre(
            args.url,
            timestamp=args.timestamp_test,
            cam_crop=args.cam_crop,
            game_crop=args.game_crop,
            forzar=True,
        )

    if args.ejecutar:
        ejecutar_lote(
            url=args.url,
            cam_crop=args.cam_crop,
            game_crop=args.game_crop,
            modelo=args.modelo,
            solo_ids=set(args.solo) if args.solo else None,
            forzar=args.forzar,
        )

    if not args.test_encuadre and not args.ejecutar:
        parser.print_help()


if __name__ == "__main__":
    main()
