#!/usr/bin/env python3
"""
Descarga música de fondo instrumental (sin copyright) desde YouTube usando yt-dlp,
la convierte a MP3 192 kbps en `musica/<categoria>/` y la registra automáticamente
en `musica/catalogo_musica.json` (y sincroniza `public/musica/`).

Uso:
  python descargar_musica.py --query "Sneaky Snitch Kevin MacLeod no copyright" --categoria comedia_absurda --nombre sneaky_snitch.mp3
  python descargar_musica.py --url "https://www.youtube.com/watch?v=..." --categoria epica_climax --nombre epica_1.mp3
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Any

from procesar_clip import obtener_duracion_video, obtener_ruta_ffmpeg

CATEGORIAS_VALIDAS: tuple[str, ...] = (
    "chill_storytime",
    "comedia_absurda",
    "tension_accion",
    "epica_climax",
)

DEFAULTS_POR_CATEGORIA: dict[str, dict[str, Any]] = {
    "chill_storytime": {
        "description": "Para charlas tranquilas con el chat, debates o noticias (ej. planes de GTA 6)",
        "mood": "chill storytime",
        "genre": "lofi / background",
        "keywords": ["charla", "chat", "historia", "anécdota", "chill", "tranquilo", "storytime"],
        "usage": "Instrumental chill suave para anécdotas, charlas con el chat o storytime.",
    },
    "comedia_absurda": {
        "description": "Para anécdotas, fails, burlas o situaciones bizarras (ej. lentes rotos, 'es una maleducada')",
        "mood": "comedia absurda",
        "genre": "comedy / quirky",
        "keywords": ["comedia", "gracioso", "fail", "absurdo", "broma", "meme", "risa"],
        "usage": "Instrumental cómico / quirky ideal para fails, sarcasmo o situaciones absurdas.",
    },
    "tension_accion": {
        "description": "Para tiroteos, persecuciones, apuestas críticas o momentos de pánico/baneo",
        "mood": "tension accion",
        "genre": "action / suspense",
        "keywords": ["tensión", "acción", "persecución", "peligro", "pánico", "escape", "caos"],
        "usage": "Instrumental de tensión y acción para persecuciones, momentos límite o caos.",
    },
    "epica_climax": {
        "description": "Para jugadas buenas, anuncios importantes o remates triunfales",
        "mood": "epica climax",
        "genre": "epic / orchestral",
        "keywords": ["épico", "victoria", "triunfo", "clímax", "logro", "final", "cine"],
        "usage": "Instrumental épico triunfal para grandes logros, remontadas o anuncios clave.",
    },
}


def obtener_ruta_yt_dlp() -> str:
    """Busca el binario yt-dlp en PATH o en los directorios Scripts de Python."""
    yt_bin = shutil.which("yt-dlp")
    if yt_bin:
        return yt_bin

    candidates = [
        Path(sys.executable).resolve().parent / "Scripts" / "yt-dlp.exe",
        Path(sysconfig.get_path("scripts", "nt_user")) / "yt-dlp.exe",
        Path(sysconfig.get_path("scripts")) / "yt-dlp.exe",
    ]
    for cand in candidates:
        if cand.is_file():
            return str(cand)

    raise FileNotFoundError(
        "No se encontró 'yt-dlp'. Instalalo con: pip install yt-dlp"
    )


def limpiar_nombre_archivo(nombre: str) -> str:
    """Normaliza el nombre del archivo destino garantizando extensión .mp3."""
    stem = Path(nombre.strip()).stem
    stem = re.sub(r'[<>:"/\\|?*]+', "_", stem).strip(" .")
    if not stem:
        raise ValueError("El parámetro --nombre no puede estar vacío.")
    return f"{stem}.mp3"


def buscar_mejor_resultado_youtube(yt_dlp_exe: str, query: str) -> tuple[str, str]:
    """
    Busca en YouTube con ytsearch5 y prioriza un track de duración razonable
    (entre 45s y 12 min), evitando compilaciones de horas.
    Devuelve (url_video, titulo_video).
    """
    cmd = [
        yt_dlp_exe,
        "--dump-json",
        "--flat-playlist",
        "--no-warnings",
        f"ytsearch5:{query}",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    candidatos: list[dict[str, Any]] = []
    for line in res.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            candidatos.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not candidatos:
        raise RuntimeError(f"No se encontraron resultados en YouTube para: {query}")

    elegido = candidatos[0]
    for item in candidatos:
        dur = item.get("duration")
        title_lower = str(item.get("title", "")).lower()
        es_compilacion = any(
            bad in title_lower for bad in ("1 hour", "1 hora", "2 hours", "10 hours", "mix", "playlist")
        )
        if dur is not None and 45 <= float(dur) <= 720 and not es_compilacion:
            elegido = item
            break

    video_url = elegido.get("webpage_url") or elegido.get("url")
    if not video_url and elegido.get("id"):
        video_url = f"https://www.youtube.com/watch?v={elegido['id']}"
    if not video_url:
        raise RuntimeError("No se pudo obtener la URL del video seleccionado.")

    return str(video_url), str(elegido.get("title") or query)


def analizar_audio_mp3(mp3_path: Path) -> tuple[float, float]:
    """Devuelve (duracion_segundos, rms_mean_db) del MP3 usando ffprobe y ffmpeg."""
    duracion = round(obtener_duracion_video(mp3_path), 2)
    ffmpeg_exe = obtener_ruta_ffmpeg()
    cmd = [
        ffmpeg_exe,
        "-hide_banner",
        "-i",
        str(mp3_path),
        "-af",
        "volumedetect",
        "-f",
        "null",
        "-",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    rms_db = -17.0
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", res.stderr)
    if match:
        rms_db = round(float(match.group(1)), 1)
    return duracion, rms_db


def calcular_volumen_recomendado(rms_db: float) -> float:
    """Calibra el volumen base recomendado (0.08–0.12) según el RMS del track."""
    if rms_db >= -12.5:
        return 0.08
    if rms_db >= -16.0:
        return 0.09
    if rms_db >= -20.0:
        return 0.10
    if rms_db >= -24.5:
        return 0.11
    return 0.12


def descargar_pista_mp3(
    url_o_query: str,
    es_url: bool,
    categoria: str,
    nombre_archivo: str,
    base_dir: Path,
) -> tuple[Path, str]:
    """Descarga el audio en MP3 192K dentro de `musica/<categoria>/<nombre_archivo>`."""
    yt_dlp_exe = obtener_ruta_yt_dlp()
    ffmpeg_exe = obtener_ruta_ffmpeg()
    ffmpeg_dir = str(Path(ffmpeg_exe).resolve().parent)

    if es_url:
        target_url = url_o_query.strip()
        titulo_fuente = Path(nombre_archivo).stem.replace("_", " ")
    else:
        target_url, titulo_fuente = buscar_mejor_resultado_youtube(yt_dlp_exe, url_o_query)

    destino_dir = base_dir / "musica" / categoria
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino_mp3 = destino_dir / nombre_archivo
    output_template = str(destino_dir / f"{destino_mp3.stem}.%(ext)s")

    print(f"Descargando '{titulo_fuente}' -> {destino_mp3.relative_to(base_dir)} ...")
    cmd = [
        yt_dlp_exe,
        "--no-playlist",
        "--ffmpeg-location",
        ffmpeg_dir,
    ]
    if shutil.which("node"):
        cmd += ["--js-runtimes", "node"]
    cmd += [
        "-x",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "192K",
        "-o",
        output_template,
        target_url,
    ]
    subprocess.run(cmd, check=True)

    if not destino_mp3.is_file():
        raise FileNotFoundError(
            f"yt-dlp finalizó pero no se encontró el archivo esperado: {destino_mp3}"
        )

    return destino_mp3, titulo_fuente


def registrar_en_catalogo(
    base_dir: Path,
    mp3_path: Path,
    categoria: str,
    titulo_fuente: str,
    usage_custom: str | None = None,
    keywords_custom: list[str] | None = None,
    volume_custom: float | None = None,
) -> dict[str, Any]:
    """
    Analiza la pista descargada, actualiza `musica/catalogo_musica.json`,
    copia el MP3 a `public/musica/<categoria>/` y sincroniza `public/musica/catalogo_musica.json`.
    """
    duracion, rms_db = analizar_audio_mp3(mp3_path)
    energy = "high" if rms_db > -14.0 else ("medium" if rms_db > -21.0 else "low")
    rec_vol = volume_custom if volume_custom is not None else calcular_volumen_recomendado(rms_db)

    cat_defaults = DEFAULTS_POR_CATEGORIA[categoria]
    rel_file = f"{categoria}/{mp3_path.name}"
    rel_path = f"musica/{rel_file}"

    stem_words = [
        w.lower()
        for w in re.split(r"[\s_\-]+", mp3_path.stem)
        if len(w) >= 3 and w.lower() not in {"mp3", "music", "audio", "no", "copyright"}
    ]
    keywords = keywords_custom if keywords_custom else list(
        dict.fromkeys([*cat_defaults["keywords"], *stem_words])
    )
    usage = usage_custom.strip() if usage_custom else f"{cat_defaults['usage']} ({titulo_fuente})"

    nuevo_track: dict[str, Any] = {
        "file": rel_file,
        "path": rel_path,
        "category": categoria,
        "durationSeconds": duracion,
        "rmsDb": rms_db,
        "energy": energy,
        "genre": cat_defaults["genre"],
        "mood": cat_defaults["mood"],
        "recommendedVolume": rec_vol,
        "usage": usage,
        "keywords": keywords,
        "sourceTitle": titulo_fuente,
        "excludeFromAutoBgm": False,
    }

    catalogo_path = base_dir / "musica" / "catalogo_musica.json"
    if catalogo_path.is_file():
        catalogo = json.loads(catalogo_path.read_text(encoding="utf-8"))
    else:
        catalogo = {
            "totalTracks": 0,
            "categories": {},
            "defaultVolume": 0.1,
            "fadeInSeconds": 0.5,
            "fadeOutSeconds": 1.0,
            "defaultCutDurationSeconds": 1.8,
            "tracks": [],
        }

    tracks: list[dict[str, Any]] = catalogo.get("tracks", [])
    reemplazado = False
    for idx, tr in enumerate(tracks):
        if str(tr.get("file", "")).lower() == rel_file.lower():
            tracks[idx] = nuevo_track
            reemplazado = True
            break
    if not reemplazado:
        tracks.append(nuevo_track)

    categories_meta: dict[str, Any] = catalogo.get("categories", {})
    for cat_key in CATEGORIAS_VALIDAS:
        if cat_key not in categories_meta:
            categories_meta[cat_key] = {
                "count": 0,
                "description": DEFAULTS_POR_CATEGORIA[cat_key]["description"],
                "defaultTrack": "",
            }
        cat_tracks = [t for t in tracks if t.get("category") == cat_key]
        categories_meta[cat_key]["count"] = len(cat_tracks)
        if not categories_meta[cat_key].get("defaultTrack") and cat_tracks:
            categories_meta[cat_key]["defaultTrack"] = cat_tracks[0]["file"]

    catalogo["tracks"] = tracks
    catalogo["categories"] = categories_meta
    catalogo["totalTracks"] = len(tracks)

    serialized = json.dumps(catalogo, ensure_ascii=False, indent=2)
    catalogo_path.write_text(serialized, encoding="utf-8")

    # Sincronizar copia en public/musica/ para que Remotion pueda acceder directo
    public_mp3 = base_dir / "public" / "musica" / categoria / mp3_path.name
    public_mp3.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(mp3_path, public_mp3)

    public_catalogo = base_dir / "public" / "musica" / "catalogo_musica.json"
    public_catalogo.parent.mkdir(parents=True, exist_ok=True)
    public_catalogo.write_text(serialized, encoding="utf-8")

    return nuevo_track


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Descarga música sin copyright de YouTube en MP3 y la registra en musica/catalogo_musica.json."
    )
    fuente = parser.add_mutually_exclusive_group(required=True)
    fuente.add_argument(
        "--query",
        type=str,
        help="Búsqueda en YouTube (ej. 'Sneaky Snitch Kevin MacLeod no copyright').",
    )
    fuente.add_argument(
        "--url",
        type=str,
        help="URL directa de YouTube para descargar.",
    )
    parser.add_argument(
        "--categoria",
        required=True,
        choices=CATEGORIAS_VALIDAS,
        help="Categoría dentro del catálogo de música.",
    )
    parser.add_argument(
        "--nombre",
        required=True,
        type=str,
        help="Nombre del archivo destino (.mp3), ej. sneaky_snitch.mp3",
    )
    parser.add_argument(
        "--usage",
        type=str,
        default=None,
        help="Descripción opcional de uso para el catálogo.",
    )
    parser.add_argument(
        "--keywords",
        type=str,
        default=None,
        help="Palabras clave separadas por coma (opcional).",
    )
    parser.add_argument(
        "--volumen",
        type=float,
        default=None,
        help="Volumen recomendado manual (ej. 0.10).",
    )
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    nombre_limpio = limpiar_nombre_archivo(args.nombre)
    kw_list = (
        [k.strip().lower() for k in args.keywords.split(",") if k.strip()]
        if args.keywords
        else None
    )

    mp3_path, titulo_fuente = descargar_pista_mp3(
        url_o_query=args.url if args.url else args.query,
        es_url=bool(args.url),
        categoria=args.categoria,
        nombre_archivo=nombre_limpio,
        base_dir=base_dir,
    )
    entry = registrar_en_catalogo(
        base_dir=base_dir,
        mp3_path=mp3_path,
        categoria=args.categoria,
        titulo_fuente=titulo_fuente,
        usage_custom=args.usage,
        keywords_custom=kw_list,
        volume_custom=args.volumen,
    )
    print(
        f"[OK] Registrada '{entry['file']}' | cat={entry['category']} | "
        f"dur={entry['durationSeconds']}s | rms={entry['rmsDb']}dB | vol={entry['recommendedVolume']}"
    )


if __name__ == "__main__":
    main()
