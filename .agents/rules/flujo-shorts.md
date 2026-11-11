---
trigger: always_on
description: Flujo automático para procesar clips a 30fps con detección de cambios de escena, 3 niveles de edición, hook visual, catálogo SFX y barra de progreso
---

Cada vez que el usuario pida procesar un clip de `clips-entrada/` (o del directorio del proyecto), seguí este flujo automático de principio a fin sin preguntar:

1. **Eliminar silencios y detectar escenas dinámicas**:
   Ejecutá `python procesar_clip.py <archivo> --detectar-escenas`.
   *(Esto genera `clips-procesados/sin_silencio_temp.mp4` a 30fps, detecta si hay cortes/cambios de cámara mayores a 1.5s, imprime los rangos `[start, end]` y guarda una imagen por tramo en `clips-procesados/escena_0.jpg`, `escena_1.jpg`, etc.).*

2. **Inspeccionar visualmente las escenas y procesar por segmentos**:
   - Usá `read_file` para ver todas las imágenes `clips-procesados/escena_*.jpg` generadas.
   - Por cada escena detectada, determiná si es:
     - **Solo cámara (*Just Chatting*)**: `"modo": "fullcam"`
     - **Gameplay + Webcam**: `"modo": "gameplay"` y calculá las coordenadas aproximadas `"coords": [X, Y, W, H]` de la webcam (sobre `1920x1080`).
   - Ejecutá `procesar_clip.py` pasando la lista de segmentos en `--segmentos` junto con `--sync-remotion` (reutilizará automáticamente `sin_silencio_temp.mp4` sin volver a correr `auto-editor`, guardando el video en `public/clips/<nombre>.mp4`, su JSON en `public/proyectos/<nombre>.json` y registrándolo en `public/proyectos/index.json`):
     ```powershell
     python procesar_clip.py <archivo> --segmentos '[{"start":0.0,"end":14.2,"modo":"gameplay","coords":[X,Y,W,H]},{"start":14.2,"end":24.6,"modo":"fullcam"}]' --sync-remotion
     ```

3. **Configurar `public/proyectos/<nombre>.json` (y `public/data.json` de respaldo)**:
   - **Hook inicial (`hookTitle`)**: En cualquiera de los 3 estilos, inventá y agregá siempre un `hookTitle` corto y llamativo (máximo 4 a 6 palabras, ej. `"¡EL TEMA MÁS POLÉMICO!"`) que resuma el gancho del clip en los primeros 3 segundos.
   - **Por defecto (`"editStyle": "simple"`)**: Si el usuario solo pide *"Procesá `archivo.mp4`"* (sin pedir edición detallada ni ilustraciones), dejá `"editStyle": "simple"`, marcá las palabras clave de mayor impacto con `"highlight": true` en `subtitles`, y **no gastes tokens generando `cards` ni `illustrations`**.
   - **Si pide *"con edición detallada"* (`"editStyle": "detallada"`)**: Configurá `"editStyle": "detallada"`, marcá palabras clave con `"highlight": true` y generá entre 2 y 3 `cards` animadas (tarjetas o sellos con `variant: "stamp"`) acordes a lo que dice el streamer, eligiendo un `"sfx"` acorde del catálogo.
   - **Si pide *"con edición ilustraciones"* (`"editStyle": "ilustraciones"`)**:
     - Configurá `"editStyle": "ilustraciones"`, marcá palabras clave con `"highlight": true` y agregá las `cards` o gráficos (`ComparisonBar`, `CounterBox`, `StampAlert`) cuando apliquen.
     - **Analizá la transcripción frase por frase y generá al menos de 4 a 6 ilustraciones SVG personalizadas (`type: "custom_svg"`)** dentro de `illustrations` que representen **literalmente** los objetos, sustantivos o conceptos clave que menciona el streamer.
     - **Prohibido tapar la cara**: las ilustraciones se renderizan siempre dentro de una tarjeta oscura (`bg-black/70 backdrop-blur-md`) en la **mitad inferior** (`top: 62%`), con el SVG limitado a 220×220px. Nunca planifiques un SVG gigante suelto en el centro de la pantalla.
     - **Prohibidos los íconos genéricos sueltos** (un `?`, un tilde verde, una estrella pelada, una carita sin contexto). Cada ilustración debe ser una **escena compuesta con contexto** (ej. la pastilla junto a un vaso de agua, el monitor mostrando la escena de OBS) y llevar siempre un `label` corto (2-3 palabras, ej. `"HORA DE LA PASTILLA"`).
     - **Puntajes, notas, votaciones o comparaciones** (ej. "10 de 10", "9", "X vs Y", precios o listas) **no van como `custom_svg`**: usá `explainerPanels` con `versusCards` (dos valores enfrentados) o `gridItems` (conteos/listas).
     - Cada objeto `"custom_svg"` debe incluir:
       - `svg`: código `<svg viewBox="0 0 200 200">...</svg>` limpio, estilo vector plano/cartoon colorido con trazo grueso negro (`stroke="#000000" stroke-width="6"`) para que resalte sobre el video.
       - `label`: texto corto que aparece debajo del dibujo dentro de la tarjeta.
       - `start` y `end`: sincronizados en el segundo exacto en que el streamer pronuncia el sustantivo/concepto.
       - `position`: solo define la columna horizontal (`"bottom-left"` | `"bottom"` | `"bottom-right"`); la altura es fija en la mitad inferior.
       - `scale`: `1.0` o menor (el código lo limita a un máximo de `1.0`).
       - `animation`: `"pop"` | `"float"` | `"shake"` según la intención de la escena.
       - `sfx`: ruta relativa dentro de `public/sfx/` que mejor acompañe la emoción o acción del objeto.
   - **Ubicación fija de capas (no modificar)**: subtítulos en `top: 78%`, badge del canal `berlinuno` en `top: 71%`, ilustraciones en `top: 58%` como badge horizontal compacto (ícono 130px + etiqueta). En escenas `fullcam` usá `position: "bottom-right"` o `"bottom-left"` para que el badge quede a un costado de la cara. Todas las palabras de los subtítulos tienen el mismo tamaño (76px, peso 900); `highlight: true` solo cambia el color a amarillo `#FFE600` y suma un `scale(1.1)`.
   - **Sin duplicados entre `cards` e `illustrations`**: nunca superpongas una `card` y una `illustration` en el mismo tramo de tiempo diciendo lo mismo (ej. card `"MOMENTO PASTILLA"` + ilustración `"HORA DE LA PASTILLA"`). Si ya hay una ilustración en ese tramo, no agregues una `card` arriba; usá las `cards` solo en tramos sin ilustración.
   - **Gráficos "Explainer" sobre el gameplay (`explainerPanels`)**:
     - Cuando el clip tenga una explicación con números, listas, inventarios, precios o comparaciones ("X vs Y"), generá un objeto en `explainerPanels` (compatible con modos `detallada` e `ilustraciones`) para que se dibuje directamente sobre el 62% inferior del gameplay con fondo transparente:
       - `start` y `end`: tramo en segundos que dura la explicación.
       - `headerLeft` (ej. `"CASA DE SUBASTAS"`) y `headerRight` (ej. `"BOLSA LINO ROJO • 8 HUECOS"`, en amarillo).
       - `gridItems`: lista opcional de `{ "icon": "bag" | "money" | "fire" | "<svg...>", "label": "...", "count": 12 }` para mostrar filas de íconos en grilla con animación escalonada.
       - `versusCards`: objeto opcional `{ "leftTitle": "...", "leftSub": "...", "leftValue": "+20", "rightTitle": "...", "rightSub": "...", "rightValue": "-5" }` para mostrar dos tarjetas comparativas lado a lado con contadores grandes.
       - `sfx`: sonido de entrada (por defecto `"Whosh/Fast_Whoosh.wav"`).

4. **Selección inteligente de SFX (`"sfx"` en `cards`, `illustrations` y `subtitles` con `highlight: true`)**:
   - El catálogo completo con los **200 efectos de sonido** está indexado en `public/sfx/catalogo.json`.
   - Si no especificás `"sfx"`, Remotion usa por defecto:
     - Pop: `"SONIDOS/efecto de sonido POP.mp3"` (tarjetas/ilustraciones)
     - Whoosh: `"Whosh/Swipe Swoosh Transition Sound Effect.mp3"` (hook/sellos)
     - Ding: `"SONIDOS/ES_Notification, Tutorial Message Appear, Attention, Video Game 02 - Epidemic Sound.mp3"` (palabras `highlight: true`)
   - En los modos `detallada` e `ilustraciones`, elegí el `"sfx"` contextual que mejor encaje con el chiste, emoción o tema (pasando la ruta relativa a `public/sfx/`):
     - **Pop / Aparición de íconos y tarjetas**:
       - `"SONIDOS/efecto de sonido POP.mp3"` (1.07s) — Pop clásico de edición por defecto
       - `"SONIDOS/ES_Cartoon, Pop, Small Lid - Epidemic Sound.mp3"` (0.44s) — Destape corto
       - `"SONIDOS/ES_Food & Drink, Glassware, Bottle, Glass, Cork, Open, Pop - Epidemic Sound.mp3"` (0.30s) — Pop rápido de corcho
       - `"SONIDOS/ES_Food & Drink, Glassware, Bottle, Champagne, Cork Pop, Outside - Epidemic Sound.mp3"` (0.84s) — Corcho de champagne / festejo
       - `"SONIDOS/ES_Explosions, Real, Very Small Pop - Epidemic Sound.mp3"` (1.24s) — Pequeño pop con eco
     - **Transiciones / Whoosh / Entradas rápidas**:
       - `"Whosh/Swipe Swoosh Transition Sound Effect.mp3"` (0.67s) — Swipe swoosh rápido por defecto
       - `"Whosh/Cartoon_Whoosh.wav"` (0.49s) — Whoosh ágil estilo dinámico
       - `"Whosh/Fast_Whoosh.wav"` (1.24s) / `"Whosh/Deep_Whoosh.wav"` (1.5s) — Barrido profundo para cambios de cámara o tarjetas grandes
       - `"Whosh/Woosh Effect 1.wav"` (0.77s) / `"Whosh/Woosh Effect 8.wav"` (0.31s) — Whoosh seco y corto
     - **Impactos / Sellos (`StampAlert` / "FACTOS" / "ALERTA")**:
       - `"SONIDOS/Sonido de impacto.mp3"` (1.46s) — Golpe de impacto directo
       - `"Impact y hit/Efecto de Sonido Impacto - Sonido para TUS VÍDEOS.mp3"` (2.9s) — Impacto clásico de YouTube
       - `"Impact y hit/ES_Designed, Bass Dive, Trailer Sub, Fall Down, Short, Clean 01 - Epidemic Sound.mp3"` (1.34s) — Sub-bass drop corto
       - `"Impact y hit/ES_Trailer Sub, Fall Down, Medium, Clean 04 - Epidemic Sound.mp3"` (2.52s) — Bajada de grave cinemática
       - `"SONIDOS/The Undertaker Bell  Sound Effect.mp3"` (4.23s) — Campana fúnebre (para condena o momento oscuro)
     - **Brillo / Puntos / Éxito / Palabras Clave (`highlight: true` o `CounterBox`)**:
       - `"SONIDOS/ES_Notification, Tutorial Message Appear, Attention, Video Game 02 - Epidemic Sound.mp3"` (1.37s) — Notificación limpia de juego por defecto
       - `"SONIDOS/ES_Event, Collect Point - Epidemic Sound - 0000-1708.wav"` (1.71s) — Sumar punto / moneda / logro
       - `"SONIDOS/IPHONE NOTIFICATION SOUND EFFECT (PINGDING).mp3"` (4.37s) — Ping de mensaje/notificación
       - `"SONIDOS/GTA IV Notification Sound.mp3"` (4.02s) — Notificación GTA IV
     - **Comedia / Memes / Golpes Cómicos / Fails**:
       - `"SONIDOS/Bonk Sound Effect.mp3"` (0.98s) — Golpe en la cabeza ("bonk") para tonterías o errores
       - `"SONIDOS/ES_User Interface, Alert, Denied, Error, Negative, Variations, Video Game 01 - Epidemic Sound - 0744-1520.wav"` (0.78s) — Error / Rechazado / Incorrecto
       - `"SONIDOS/Roblox Death Sound (Oof) - Sound Effect (HD).mp3"` (3.02s) — "Oof" clásico para fails
       - `"SONIDOS/Discord Disconnect  Sound Effect.mp3"` (5.09s) — Desconexión mental / "se fue"
       - `"SONIDOS/low honor sound effect.mp3"` (4.88s) — Bajo honor (Red Dead) para actitudes dudosas o traiciones
       - `"SONIDOS/aww sound effect ( 4K ).mp3"` (2.04s) — Ternura irónica ("aww")
       - `"SONIDOS/Pedo.mp3"` (0.55s) / `"SONIDOS/ES_Farts, Designed, Very Reverberant, Short, Meme Redesign - Epidemic Sound - 10415-14125.wav"` (3.71s) — Pedo meme con reverb
     - **Rebotes / Movimiento (`custom_svg` con `pop`, `float` o `shake`)**:
       - `"SONIDOS/ES_Cartoon, Boing, Jump, Short, Retro, Video Game - Epidemic Sound.mp3"` (0.36s) — Boing corto retro
       - `"SONIDOS/ES_Cartoon, Boing, Jump, Spring - Epidemic Sound - 0000-1389.wav"` (1.39s) — Resorte elástico
       - `"SONIDOS/ES_Brake Squeak, Loud 07 - Epidemic Sound.mp3"` (1.07s) — Frenada en seco ("pará todo")
       - `"SONIDOS/ES_Communications, Camera, Nikon D7200, Digital Camera, Shutter, With Flash - Epidemic Sound - 0078-1261.wav"` (1.18s) — Foto / captura en flagrancia
     - **Gaming (Minecraft / GTA / Shooter)**:
       - `"SONIDOS/Hit Marker sound effect.mp3"` (0.49s) — Hitmarker clásico para remates precisos
       - `"SONIDOS/ButtonPlate Click (Minecraft Sound) - Sound Effect for editing.mp3"` (0.88s) — Click de botón Minecraft
       - `"SONIDOS/Minecraft Ooh - Free Sound Effect.mp3"` (0.91s) — Daño de Minecraft
       - `"SONIDOS/Comer De Minecraft - Sonido.mp3"` (4.34s) — Comer / tragar (ideal cuando toma pastilla o come algo)
   - **Regla de duración**: Priorizá sonidos cortos (`0.3s` a `3.5s`) para tarjetas, palabras clave e ilustraciones, evitando pistas musicales largas (`>10s`) salvo que el usuario las pida explícitamente.

5. **Renderizar MP4 final (a 30 FPS)**:
   Ejecutá `npx remotion render <nombre> shorts-salida/<nombre>.mp4` para exportar la composición específica de ese clip en `shorts-salida/` (reemplazando `_` o espacios por `-` en el ID de composición si el nombre del archivo los tuviera).
