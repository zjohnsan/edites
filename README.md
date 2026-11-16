# Pipeline de Edición (Shorts 9:16 con Remotion + Videos Largos 16:9)

Repositorio con los scripts de evaluación, recorte automático, transcripción y composición en Remotion para Shorts verticales (`9:16`), además del editor automático para videos largos horizontales (`16:9`).

---

## 1. Requisitos previos

- **Node.js** 18+ y **npm**
- **Python** 3.10+
- **FFmpeg** y **FFprobe** accesibles desde el `PATH` (en Windows podés instalarlo con `winget install Gyan.FFmpeg`)

---

## 2. Instalación en una máquina nueva

```powershell
git clone https://github.com/zjohnsan/edites.git
cd edites

# Dependencias de Remotion
npm install

# Dependencias de Python (Whisper, auto-editor, yt-dlp)
pip install -r requirements.txt
```

---

## 3. Archivos externos no incluidos en Git

Por tamaño, `.gitignore` excluye videos, binarios y pistas de música:

1. **Música de fondo (`musica/` y `public/musica/`):**
   - El repo incluye los catálogos `musica/catalogo_musica.json` y `public/musica/catalogo_musica.json`.
   - Copiá tus carpetas de pistas `.mp3`/`.wav` (o descomprimí `musica.rar`) dentro de `musica/` y `public/musica/`.
2. **Super-Resolution IA (opcional, solo si usás `--mejorar-ia` en `procesar_clip.py`):**
   - Colocá `realesrgan-ncnn-vulkan.exe` y sus modelos en `tools/ai-upscaler/`.
3. **Clips de entrada:**
   - Colocá los clips crudos en `clips-entrada/`.

---

## 4. Uso rápido

### Shorts (`9:16`, Remotion)

```powershell
# 1. Evaluar clips pendientes en clips-entrada/
python evaluar_clips.py

# 2. Detectar escenas sin silencios
python procesar_clip.py mi_clip.mp4 --detectar-escenas

# 3. Procesar y sincronizar con Remotion
python procesar_clip.py mi_clip.mp4 --segmentos '[{"start":0.0,"end":14.2,"modo":"gameplay","coords":[X,Y,W,H]}]' --sync-remotion

# 4. Previsualizar en Remotion Studio o renderizar MP4 final
npm run dev
npx remotion render mi-clip shorts-salida/mi-clip.mp4
```

### Videos largos (`16:9`, FFmpeg directo)

```powershell
python editar_video_largo.py clips-entrada/stream.mp4 --inicio 00:31:30 --fin 01:53:20 --duracion-objetivo-min 45 --duracion-objetivo-max 60 -o videos-largos/salida.mp4
```
