"""
generar_subtitulos_ass.py — Transcribe un Short MP4 con faster-whisper (word_timestamps=True)
y genera un archivo .ass estilo Shorts (1080x1920, bloques de 2-4 palabras en MAYÚSCULAS,
palabra clave en amarillo #FFE500 y posición fija en MarginV=742 justo debajo de la cámara).
Opcionalmente quema los subtítulos con FFmpeg sin tocar el original.

Uso:
  python generar_subtitulos_ass.py clips_gta6_ep1/listos/06_pescando.mp4 --quemar
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from faster_whisper import WhisperModel

BASE_DIR = Path(__file__).resolve().parent

# Palabras funcionales que evitamos resaltar como palabra clave principal si hay otra más fuerte
STOPWORDS_ES = {
    "A", "AL", "CON", "DE", "DEL", "EL", "ELLA", "ELLOS", "EN", "ES", "ESA",
    "ESE", "ESO", "ESTA", "ESTE", "ESTO", "HA", "HAY", "LA", "LAS", "LE",
    "LES", "LO", "LOS", "ME", "MI", "MIS", "MUY", "NO", "NOS", "O", "OS",
    "PARA", "PERO", "POR", "QUE", "QUÉ", "SE", "SI", "SÍ", "SIN", "SOY",
    "SU", "SUS", "TE", "TI", "TU", "TÚ", "UN", "UNA", "UNO", "UNOS", "Y",
    "YA", "YO",
}

PALABRAS_IMPACTO = {
    "PESQUÉ", "PESQUE", "PEZ", "CAÑA", "CARNADA", "AGUA", "MORONDANGA",
    "PORQUERÍA", "PORQUERIA", "PISO", "HIJO", "PERRA", "BOLUDO", "MIERDA",
    "CARAJO", "LINDO", "BIEN", "TOMÁ", "TOMA", "VENÍ", "VENI", "MIRÁ",
    "MIRA", "ATRAE", "ALEJA", "AGARRAR", "BARCO", "GTA", "VIVO", "BUG",
    "COCODRILO", "CAIMÁN", "CANGREJO", "POLICÍA", "POLICIA", "PLATA",
}

MULETILLAS_RUIDO = {"EH", "EHH", "EHHH", "MM", "MMM", "AH", "AHH", "UM", "UMM"}


def obtener_binario(nombre: str) -> str:
    """Resuelve ffmpeg/ffprobe desde PATH o rutas habituales en Windows."""
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

    raise FileNotFoundError(f"No se encontró '{nombre}' en PATH.")


def formato_tiempo_ass(segundos: float) -> str:
    """Convierte segundos a formato ASS H:MM:SS.cc (centésimas)."""
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
    """
    Limpia símbolos raros dejando caracteres latinos/españoles, números y puntuación útil.
    Devuelve (texto_mayus_limpio, termina_en_pausa_fuerte).
    """
    txt = raw.strip()
    if not txt:
        return "", False

    pausa_fuerte = bool(re.search(r"[.?!,;:\u2026]+$", txt))

    # Conservar letras españolas, números y signos básicos (? ! ¿ ¡ .)
    txt = re.sub(r"[^\w\sáéíóúüñÁÉÍÓÚÜÑ¿¡?!]", "", txt, flags=re.UNICODE)
    # Quitar guiones bajos que \w permite
    txt = txt.replace("_", "").strip().upper()
    # Si quedó solo puntuación sin letras/números, descartar
    if not re.search(r"[A-ZÁÉÍÓÚÜÑ0-9]", txt):
        return "", pausa_fuerte
    if txt in MULETILLAS_RUIDO:
        return "", pausa_fuerte

    # Limpiar signos de apertura/cierre sueltos si quedan desbalanceados simples
    txt = txt.replace("¿", "")
    return txt, pausa_fuerte


def transcribir_palabras(
    video_path: Path,
    modelo: str = "base",
    whisper_model: Optional[WhisperModel] = None,
) -> list[dict]:
    """Transcribe un video/audio palabra por palabra con faster-whisper."""
    print(f"[Subtitulos] Transcribiendo '{video_path.name}' con faster-whisper (model={modelo}, int8, vad_filter=True)...")
    model = whisper_model or WhisperModel(modelo, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        str(video_path),
        language="es",
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
    )

    palabras: list[dict] = []
    for seg in segments:
        if not getattr(seg, "words", None):
            continue
        for w in seg.words:
            limpia, pausa_fuerte = _limpiar_palabra(w.word)
            if not limpia:
                continue
            palabras.append(
                {
                    "text": limpia,
                    "start": float(w.start),
                    "end": float(w.end),
                    "break_after": pausa_fuerte,
                }
            )
    print(f"[Subtitulos] {len(palabras)} palabras detectadas.")
    return palabras


def agrupar_bloques_shorts(
    palabras: list[dict],
    max_palabras: int = 4,
    pausa_corte: float = 0.35,
    max_chars: int = 24,
) -> list[dict]:
    """
    Agrupa palabras en bloques explosivos de 2 a 4 palabras máximo,
    cortando ante pausas > 0.35s, signos de puntuación o exceso de largo visual.
    """
    if not palabras:
        return []

    bloques: list[list[dict]] = []
    actual: list[dict] = []

    for w in palabras:
        if actual:
            gap = w["start"] - actual[-1]["end"]
            nuevo_len = sum(len(x["text"]) for x in actual) + len(actual) + len(w["text"])
            cortar = (
                len(actual) >= max_palabras
                or gap > pausa_corte
                or actual[-1]["break_after"]
                or (len(actual) >= 2 and nuevo_len > max_chars)
            )
            if cortar:
                bloques.append(actual)
                actual = []
        actual.append(w)

    if actual:
        bloques.append(actual)

    # Fusionar bloques huérfanos de 1 palabra corta con el vecino cercano (<= 0.35s) si no excede 4 palabras
    fusionados: list[list[dict]] = []
    i = 0
    while i < len(bloques):
        b = bloques[i]
        if len(b) == 1 and i + 1 < len(bloques):
            nxt = bloques[i + 1]
            gap_nxt = nxt[0]["start"] - b[-1]["end"]
            if len(nxt) < max_palabras and gap_nxt <= pausa_corte and not b[-1]["break_after"]:
                bloques[i + 1] = b + nxt
                i += 1
                continue
        if len(b) == 1 and fusionados:
            prev = fusionados[-1]
            gap_prev = b[0]["start"] - prev[-1]["end"]
            if len(prev) < max_palabras and gap_prev <= 0.25 and not prev[-1]["break_after"]:
                fusionados[-1] = prev + b
                i += 1
                continue
        fusionados.append(b)
        i += 1

    # Convertir a eventos no solapados con duración mínima legible
    eventos: list[dict] = []
    for idx, b in enumerate(fusionados):
        t_ini = b[0]["start"]
        t_fin = b[-1]["end"] + 0.12
        if t_fin - t_ini < 0.45:
            t_fin = t_ini + 0.45
        if idx + 1 < len(fusionados):
            nxt_ini = fusionados[idx + 1][0]["start"]
            if t_fin > nxt_ini - 0.02:
                t_fin = max(t_ini + 0.18, nxt_ini - 0.02)
        eventos.append({"words": [x["text"] for x in b], "start": t_ini, "end": t_fin})

    return eventos


def _elegir_indice_clave(words: list[str]) -> int:
    """Elige el índice de la palabra clave a resaltar en amarillo (o la última si no hay clara)."""
    if len(words) == 1:
        return 0

    def bare(w: str) -> str:
        return re.sub(r"[?!¡¿.,]", "", w)

    # 1. Priorizar palabras de impacto o números / exclamaciones
    for i in range(len(words) - 1, -1, -1):
        bw = bare(words[i])
        if bw in PALABRAS_IMPACTO or re.search(r"\d", bw) or "?" in words[i] or "!" in words[i]:
            return i

    # 2. Si no, la palabra más larga (y si empatan, la última) que no sea stopword
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


def construir_linea_ass(words: list[str]) -> str:
    """Formatea la línea ASS resaltando la palabra clave/última en amarillo (&H0000E5FF) sobre blanco (&H00FFFFFF)."""
    idx_clave = _elegir_indice_clave(words)
    partes: list[str] = []
    for i, w in enumerate(words):
        if i == idx_clave:
            partes.append(f"{{\\c&H0000E5FF&}}{w}{{\\c&H00FFFFFF&}}")
        else:
            partes.append(w)
    return " ".join(partes)


def generar_archivo_ass(
    video_path: Path,
    salida_ass: Optional[Path] = None,
    modelo: str = "base",
    font_name: str = "Arial Black",
    font_size: int = 54,
    margin_v: int = 742,
    whisper_model: Optional[WhisperModel] = None,
) -> Path:
    if not video_path.is_file():
        raise FileNotFoundError(f"No existe el video: {video_path}")

    if salida_ass is None:
        salida_ass = video_path.with_suffix(".ass")

    palabras = transcribir_palabras(video_path, modelo=modelo, whisper_model=whisper_model)
    eventos = agrupar_bloques_shorts(palabras)

    header = f"""[Script Info]
Title: Subtitulos Dinamicos Shorts - {video_path.stem}
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Shorts,{font_name},{font_size},&H00FFFFFF,&H0000E5FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,2,8,80,80,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lineas_eventos: list[str] = []
    for ev in eventos:
        ini = formato_tiempo_ass(ev["start"])
        fin = formato_tiempo_ass(ev["end"])
        texto_ass = construir_linea_ass(ev["words"])
        lineas_eventos.append(f"Dialogue: 0,{ini},{fin},Shorts,,0,0,0,,{texto_ass}")

    salida_ass.parent.mkdir(parents=True, exist_ok=True)
    salida_ass.write_text(header + "\n".join(lineas_eventos) + "\n", encoding="utf-8-sig")
    print(f"[Subtitulos] Archivo .ass guardado en {salida_ass} ({len(lineas_eventos)} bloques)")
    return salida_ass


def _escapar_ruta_filtro_ass(ruta: Path) -> str:
    """Escapa ruta Windows para el filtro ass='...' de FFmpeg."""
    try:
        rel = ruta.resolve().relative_to(Path.cwd().resolve())
        s = rel.as_posix()
    except ValueError:
        s = ruta.resolve().as_posix()
    s = s.replace("\\", "/").replace(":", "\\:")
    return s


def quemar_subtitulos_ffmpeg(
    video_entrada: Path,
    archivo_ass: Path,
    video_salida: Optional[Path] = None,
    en_lugar: bool = False,
) -> Path:
    if en_lugar:
        destino_final = video_entrada
        video_render = video_entrada.with_name(f".{video_entrada.stem}_subs_tmp{video_entrada.suffix}")
    elif video_salida is None:
        destino_final = video_entrada.with_name(f"{video_entrada.stem}_subs{video_entrada.suffix}")
        video_render = destino_final
    else:
        destino_final = video_salida
        video_render = destino_final

    ffmpeg_exe = obtener_binario("ffmpeg")
    ass_escaped = _escapar_ruta_filtro_ass(archivo_ass)

    cmd = [
        ffmpeg_exe,
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-i",
        str(video_entrada),
        "-vf",
        f"ass='{ass_escaped}'",
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
    print(f"[Subtitulos] Quemando {archivo_ass.name} en {video_entrada.name} -> {destino_final.name}...")
    subprocess.run(cmd, check=True)
    if en_lugar:
        os.replace(video_render, destino_final)
    print(f"[Subtitulos] Video listo -> {destino_final}")
    return destino_final


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera subtítulos .ass dinámicos con faster-whisper y opcionalmente los quema con FFmpeg."
    )
    parser.add_argument("video", nargs="?", help="Ruta al archivo MP4.")
    parser.add_argument("--lote", help="Carpeta con MP4s para subtitular y quemar en lote (reemplaza en lugar salvo --sufijo-subs).")
    parser.add_argument("--ass-dir", help="Carpeta donde guardar los .ass en modo --lote.")
    parser.add_argument("--en-lugar", action="store_true", help="Al quemar un video individual, reemplaza el original atómicamente.")
    parser.add_argument("--sufijo-subs", action="store_true", help="En --lote, guarda como <nombre>_subs.mp4 sin pisar originales.")
    parser.add_argument("--omitir", nargs="*", default=[], help="Archivos a omitir en --lote.")
    parser.add_argument("--ass", help="Ruta de salida para el .ass (default: mismo nombre .ass).")
    parser.add_argument("--salida", help="Ruta del MP4 de salida al quemar (default: <nombre>_subs.mp4).")
    parser.add_argument("--modelo", default="base", help="Modelo faster-whisper (default: base).")
    parser.add_argument("--quemar", action="store_true", help="Quema el .ass sobre el video con FFmpeg.")
    args = parser.parse_args()

    if args.lote:
        carpeta = Path(args.lote)
        if not carpeta.is_dir():
            raise FileNotFoundError(f"No existe la carpeta: {carpeta}")
        ass_dir = Path(args.ass_dir) if args.ass_dir else carpeta.parent / "subs"
        ass_dir.mkdir(parents=True, exist_ok=True)
        omitir = set(args.omitir)
        videos = sorted(
            p for p in carpeta.glob("*.mp4")
            if not p.name.startswith(".") and not p.stem.endswith("_subs") and p.name not in omitir
        )
        print(f"[Subtitulos Lote] Cargando faster-whisper ({args.modelo}) para {len(videos)} videos...")
        shared_model = WhisperModel(args.modelo, device="cpu", compute_type="int8")
        for idx, v in enumerate(videos, 1):
            print(f"\n[{idx}/{len(videos)}] {v.name}")
            ass_path = ass_dir / f"{v.stem}.ass"
            generar_archivo_ass(
                v,
                salida_ass=ass_path,
                modelo=args.modelo,
                whisper_model=shared_model,
            )
            quemar_subtitulos_ffmpeg(
                v,
                ass_path,
                en_lugar=not args.sufijo_subs,
            )
        print(f"\n[Subtitulos Lote] Terminados {len(videos)} clips.")
        return

    if not args.video:
        parser.error("Debes pasar la ruta al MP4 o usar --lote <carpeta>.")

    video_path = Path(args.video)
    ass_path = Path(args.ass) if args.ass else video_path.with_suffix(".ass")
    generar_archivo_ass(video_path, salida_ass=ass_path, modelo=args.modelo)

    if args.quemar:
        salida_mp4 = Path(args.salida) if args.salida else None
        quemar_subtitulos_ffmpeg(
            video_path,
            ass_path,
            video_salida=salida_mp4,
            en_lugar=args.en_lugar,
        )


if __name__ == "__main__":
    main()
