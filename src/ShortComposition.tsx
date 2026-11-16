import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Img,
  interpolate,
  OffthreadVideo,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {
  BackgroundMusic,
  CardItem,
  CardPosition,
  ExplainerGridItem,
  ExplainerPanel,
  getTeaserDurationFrames,
  HookTeaser,
  IllustrationItem,
  ShortData,
  SubtitleConfig,
  SubtitleItem,
  SvgPosition,
} from './types';

const positionClasses: Record<CardPosition, string> = {
  'top-left': 'top-14 left-10',
  'top-right': 'top-14 right-10',
  center: 'top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2',
  'bottom-left': 'bottom-32 left-10',
  'bottom-right': 'bottom-32 right-10',
};

const DEFAULT_POP_SFX = 'SONIDOS/efecto de sonido POP.mp3';
const DEFAULT_WHOOSH_SFX = 'Whosh/Swipe Swoosh Transition Sound Effect.mp3';
const DEFAULT_DING_SFX =
  'SONIDOS/ES_Notification, Tutorial Message Appear, Attention, Video Game 02 - Epidemic Sound.mp3';

const resolveSfxSrc = (sfx: string | undefined, defaultFile: string): string => {
  const chosen = sfx?.trim() || defaultFile;
  const normalized = chosen.replace(/^\/+/, '');
  const withPrefix = normalized.startsWith('sfx/')
    ? normalized
    : `sfx/${normalized}`;
  return staticFile(withPrefix);
};

const resolveMusicSrc = (musicFile: string): string => {
  const normalized = musicFile.trim().replace(/^\/+/, '');
  const withPrefix = normalized.startsWith('musica/')
    ? normalized
    : `musica/${normalized}`;
  return staticFile(withPrefix);
};

/**
 * BackgroundMusicLayer: Música de fondo con volumen bajo (0.08–0.12 por defecto),
 * fade-in suave (0.5s), fade-out final (1.0s), loop automático y corte dramático en seco
 * (volume = 0 por 1.5–2s) en remates/crasheos indicados en `cutAtTimestamps`.
 */
const BackgroundMusicLayer: React.FC<{
  music: BackgroundMusic;
  teaserFrames: number;
}> = ({ music, teaserFrames }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  if (!music.file?.trim()) {
    return null;
  }

  const baseVolume = music.volume ?? 0.1;
  const fadeInFrames = Math.max(1, Math.round((music.fadeInSeconds ?? 0.5) * fps));
  const fadeOutFrames = Math.max(1, Math.round((music.fadeOutSeconds ?? 1.0) * fps));

  const fadeInFactor = interpolate(frame, [0, fadeInFrames], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const fadeOutFactor = interpolate(
    frame,
    [Math.max(0, durationInFrames - fadeOutFrames), durationInFrames],
    [1, 0],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    }
  );

  // Corte limpio durante el flash de transición entre el hookTeaser y el inicio del video
  let cutFactor = 1;
  if (teaserFrames > 0) {
    if (frame >= teaserFrames - 1 && frame <= teaserFrames + 4) {
      cutFactor = 0;
    } else if (frame > teaserFrames + 4 && frame < teaserFrames + Math.round(0.3 * fps)) {
      cutFactor = interpolate(
        frame,
        [teaserFrames + 4, teaserFrames + Math.round(0.3 * fps)],
        [0, 1],
        { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
      );
    }
  }

  // Corte en seco (0ms fade-out) en los segundos del video principal definidos en cutAtTimestamps
  // y rampa suave de regreso (0.4s fade-in por defecto)
  if (frame >= teaserFrames && music.cutAtTimestamps?.length) {
    const mainTime = (frame - teaserFrames) / fps;
    const resumeFadeSeconds = Math.max(0.05, music.cutFadeInSeconds ?? 0.4);
    for (const rawCut of music.cutAtTimestamps) {
      const cutStart = typeof rawCut === 'number' ? rawCut : rawCut.start;
      const cutEnd =
        typeof rawCut === 'number'
          ? rawCut + 1.6
          : rawCut.end ?? rawCut.start + (rawCut.duration ?? 1.6);

      if (mainTime >= cutStart && mainTime <= cutEnd) {
        cutFactor = 0;
        break;
      }
      if (mainTime > cutEnd && mainTime < cutEnd + resumeFadeSeconds) {
        const resumeRamp = (mainTime - cutEnd) / resumeFadeSeconds;
        cutFactor = Math.min(cutFactor, resumeRamp);
      }
    }
  }

  const finalVolume = Math.max(
    0,
    baseVolume * fadeInFactor * fadeOutFactor * cutFactor
  );

  return <Audio src={resolveMusicSrc(music.file)} volume={finalVolume} loop />;
};

const AnimatedSubtitle: React.FC<{
  item: SubtitleItem;
  config?: SubtitleConfig;
}> = ({ item, config }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const startFrame = Math.round(item.start * fps);
  const relativeFrame = Math.max(0, frame - startFrame);

  const springScale = spring({
    frame: relativeFrame,
    fps,
    config: {
      damping: 11,
      stiffness: 240,
      mass: 0.6,
    },
  });

  const yOffset = config?.yOffset ?? 0;
  const customScale = config?.scale ?? 1;

  const isHighlighted = Boolean(item.highlight);

  // Solo reproducir SFX si está definido explícitamente en el JSON y no es sonido de notificación/ping
  const isNotificationSfx =
    item.sfx?.toLowerCase().includes('notification') ||
    item.sfx?.toLowerCase().includes('pingding');
  const shouldPlaySfx = Boolean(item.sfx) && !isNotificationSfx;

  // El pop de entrada arranca en 0.88 (no en 0) para que las palabras muy cortas
  // (3-4 frames) se vean siempre a tamaño completo. Highlight solo suma un leve scale(1.1).
  const popScale = interpolate(springScale, [0, 1], [0.88, 1]);
  const highlightScale = isHighlighted ? 1.1 : 1;
  const finalScale = popScale * highlightScale * customScale;

  return (
    <div
      style={{
        top: '78%',
        transform: `translate(-50%, calc(-50% + ${yOffset}px)) scale(${finalScale})`,
      }}
      className="absolute left-1/2 z-50 flex items-center justify-center px-6 pointer-events-none select-none w-full text-center"
    >
      {shouldPlaySfx && (
        <Sequence from={startFrame} layout="none">
          <Audio src={resolveSfxSrc(item.sfx, DEFAULT_DING_SFX)} volume={0.2} />
        </Sequence>
      )}
      <span
        style={{
          fontFamily: "'Montserrat', 'Arial Black', 'Impact', sans-serif",
          fontSize: 76,
          fontWeight: 900,
          lineHeight: 1,
          color: isHighlighted ? '#FFE600' : '#FFFFFF',
        }}
        className="uppercase tracking-wider text-stroke-black whitespace-nowrap"
      >
        {item.word}
      </span>
    </div>
  );
};

const AnimatedCard: React.FC<{ card: CardItem }> = ({ card }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const startFrame = Math.round(card.start * fps);
  const endFrame = Math.round(card.end * fps);
  const relativeFrame = Math.max(0, frame - startFrame);

  const enterSpring = spring({
    frame: relativeFrame,
    fps,
    config: {
      damping: 12,
      stiffness: 180,
      mass: 0.8,
    },
  });

  const exitFrames = Math.max(4, Math.round(0.2 * fps));
  const exitProgress =
    frame > endFrame - exitFrames
      ? Math.max(0, (endFrame - frame) / exitFrames)
      : 1;

  const xOffset = card.xOffset ?? 0;
  const yOffset = card.yOffset ?? 0;
  const customScale = card.scale ?? 1;
  const scale = enterSpring * exitProgress * customScale;
  const isCentered = (card.position || 'top-right') === 'center';
  const posClass = isCentered
    ? 'top-1/2 left-1/2'
    : positionClasses[card.position || 'top-right'];
  const baseTranslate = isCentered
    ? `translate(calc(-50% + ${xOffset}px), calc(-50% + ${yOffset}px))`
    : `translate(${xOffset}px, ${yOffset}px)`;
  const displayIcon = card.icon || card.emoji;

  if (card.image) {
    const imgSrc = card.image.startsWith('http') || card.image.startsWith('/')
      ? card.image
      : staticFile(card.image);

    return (
      <div
        style={{
          transform: `${baseTranslate} scale(${scale})`,
          opacity: Math.min(1, enterSpring * exitProgress),
        }}
        className={`absolute z-30 ${posClass} bg-black/90 backdrop-blur-md border-4 border-yellow-400 rounded-3xl p-5 shadow-[0_16px_40px_rgba(0,0,0,0.9),0_0_24px_rgba(255,230,0,0.3)] flex flex-col items-center gap-3 w-[840px] max-w-[92vw]`}
      >
        <Sequence from={startFrame} layout="none">
          <Audio src={resolveSfxSrc(card.sfx, DEFAULT_POP_SFX)} volume={0.35} />
        </Sequence>
        <div className="flex items-center gap-3 w-full justify-between border-b border-white/20 pb-2 px-1">
          <div className="flex items-center gap-2">
            <span className="w-3.5 h-3.5 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-yellow-400 font-black text-2xl uppercase tracking-wider">
              {card.title || 'PREGUNTA DEL CHAT'}
            </span>
          </div>
          {card.subtitle && (
            <span className="text-white/70 font-bold text-lg uppercase tracking-wide">
              {card.subtitle}
            </span>
          )}
        </div>
        <div className="rounded-xl overflow-hidden bg-black/85 border border-white/20 p-2 shadow-inner w-full flex items-center justify-center">
          <Img
            src={imgSrc}
            alt="Chat question"
            className="w-full h-auto object-contain rounded"
            style={{ imageRendering: 'crisp-edges' }}
          />
        </div>
      </div>
    );
  }

  if (card.variant === 'stamp') {
    return (
      <div
        style={{
          transform: `${baseTranslate} scale(${scale}) rotate(-8deg)`,
          opacity: Math.min(1, enterSpring * exitProgress),
        }}
        className={`absolute z-30 ${posClass} border-8 border-yellow-400 bg-black/90 px-8 py-4 rounded-2xl shadow-2xl max-w-[920px] text-center`}
      >
        <Sequence from={startFrame} layout="none">
          <Audio src={resolveSfxSrc(card.sfx, DEFAULT_POP_SFX)} volume={0.35} />
        </Sequence>
        <div className="flex items-center justify-center gap-4">
          {displayIcon && <span className="text-5xl shrink-0">{displayIcon}</span>}
          <span className="text-yellow-400 font-black text-5xl uppercase tracking-wider leading-tight">
            {card.title || card.text}
          </span>
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        transform: `${baseTranslate} scale(${scale})`,
        opacity: Math.min(1, enterSpring * exitProgress),
      }}
      className={`absolute z-20 ${posClass} bg-zinc-900/95 border-4 border-yellow-400 rounded-3xl px-7 py-5 shadow-2xl flex items-center gap-5 max-w-[650px]`}
    >
      <Sequence from={startFrame} layout="none">
        <Audio src={resolveSfxSrc(card.sfx, DEFAULT_POP_SFX)} volume={0.35} />
      </Sequence>
      {displayIcon && (
        <span className="text-6xl select-none">{displayIcon}</span>
      )}
      <div className="flex flex-col">
        <span className="text-yellow-400 font-black text-3xl uppercase tracking-wide leading-tight">
          {card.title || card.text}
        </span>
        {(card.subtitle || card.subtext) && (
          <span className="text-white font-bold text-2xl mt-1 leading-snug">
            {card.subtitle || card.subtext}
          </span>
        )}
      </div>
    </div>
  );
};

/**
 * DynamicSvgIllustration: Badge horizontal compacto (ícono SVG + etiqueta) ubicado en la mitad inferior.
 * Entrada con spring (scale 0→1, translateY 40→0, rotate -12°→0), salida con rebote inverso
 * y animación idle continua del ícono (flotación, oscilación ±6° y pulso de escala).
 */
export const DynamicSvgIllustration: React.FC<{ item: IllustrationItem }> = ({
  item,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const startFrame = Math.round(item.start * fps);
  const endFrame = Math.round(item.end * fps);
  const relativeFrame = Math.max(0, frame - startFrame);

  const animationType = item.animation || 'pop';

  // Entrada rápida con rebote
  const enterSpring = spring({
    frame: relativeFrame,
    fps,
    config: { damping: 10, stiffness: 260, mass: 0.6 },
  });

  // Salida: últimos 0.25s se encoge, baja y gira un poco
  const exitFrames = Math.max(5, Math.round(0.25 * fps));
  const exitProgress = interpolate(
    frame,
    [endFrame - exitFrames, endFrame],
    [1, 0],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  );

  const enterScale = interpolate(enterSpring, [0, 1], [0, 1]);
  const enterY = interpolate(enterSpring, [0, 1], [40, 0]);
  const enterRotate = interpolate(enterSpring, [0, 1], [-12, 0]);
  const exitY = interpolate(exitProgress, [0, 1], [30, 0]);
  const exitRotate = interpolate(exitProgress, [0, 1], [8, 0]);

  // Idle continuo del ícono (Math.sin(frame / 4)); 'shake' más nervioso, 'float' más amplio
  const speed = animationType === 'shake' ? 1.8 : 1;
  const wave = Math.sin((frame / 4) * speed);
  const iconFloatY = wave * (animationType === 'float' ? 10 : 6);
  const iconRotate = Math.sin((frame / 5) * speed) * 6; // -6° a 6°
  const iconPulse = 1 + Math.sin(frame / 3.5) * (animationType === 'pop' ? 0.07 : 0.04);
  const iconShakeX = animationType === 'shake' ? Math.sin(frame * 1.3) * 4 : 0;

  const manualX = item.xOffset ?? 0;
  const manualY = item.yOffset ?? 0;
  const baseScale = Math.min(item.scale ?? 1, 1);
  const containerScale = enterScale * baseScale * interpolate(exitProgress, [0, 1], [0.6, 1]);

  const posKey: SvgPosition = item.position || 'center';
  const isLeft = posKey.endsWith('left');
  const isRight = posKey.endsWith('right');
  const anchorStyle: React.CSSProperties = isLeft
    ? { left: '4%' }
    : isRight
      ? { right: '4%' }
      : { left: '50%' };
  const translateX = isLeft || isRight ? '0%' : '-50%';

  // Sanitización básica por seguridad (elimina tags <script> si existieran)
  const safeSvg = (item.svg || '').replace(
    /<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi,
    ''
  );

  const captionText = item.label || item.title;

  return (
    <div
      style={{
        top: '58%',
        ...anchorStyle,
        transform: `translate(calc(${translateX} + ${manualX}px), calc(-50% + ${enterY + exitY + manualY}px)) rotate(${enterRotate + exitRotate}deg) scale(${containerScale})`,
        transformOrigin: isLeft ? 'left center' : isRight ? 'right center' : 'center',
        opacity: Math.min(1, enterSpring * 1.4) * exitProgress,
      }}
      className="absolute z-30 pointer-events-none select-none"
    >
      <Sequence from={startFrame} layout="none">
        <Audio src={resolveSfxSrc(item.sfx, DEFAULT_POP_SFX)} volume={0.35} />
      </Sequence>
      <div
        style={{
          boxShadow:
            '0 14px 30px rgba(0,0,0,0.75), 0 0 26px rgba(250,204,21,0.28), inset 0 1px 0 rgba(255,255,255,0.12)',
        }}
        className="flex items-center gap-4 bg-gradient-to-br from-zinc-900/90 to-black/90 backdrop-blur-md border-2 border-yellow-300/40 rounded-[32px] pl-4 pr-7 py-3"
      >
        <div
          style={{
            transform: `translate(${iconShakeX}px, ${iconFloatY}px) rotate(${iconRotate}deg) scale(${iconPulse})`,
            filter: 'drop-shadow(0px 5px 0px rgba(0,0,0,0.9))',
          }}
          className="w-[130px] h-[130px] shrink-0 flex items-center justify-center [&>svg]:w-full [&>svg]:h-full"
          dangerouslySetInnerHTML={{ __html: safeSvg }}
        />
        {captionText && (
          <span
            style={{
              fontFamily: "'Montserrat', 'Arial Black', 'Impact', sans-serif",
              textShadow: '0 3px 0 #000, 0 0 10px rgba(0,0,0,0.9)',
            }}
            className="text-yellow-400 font-black text-3xl uppercase tracking-wide leading-tight max-w-[250px]"
          >
            {captionText}
          </span>
        )}
      </div>
    </div>
  );
};

/**
 * 1. ComparisonBar: Comparativa visual A vs B con barras de progreso animadas y SVG
 */
export const ComparisonBar: React.FC<{ item: IllustrationItem }> = ({ item }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const startFrame = Math.round(item.start * fps);
  const endFrame = Math.round(item.end * fps);
  const relativeFrame = Math.max(0, frame - startFrame);

  const enter = spring({
    frame: relativeFrame,
    fps,
    config: { damping: 13, stiffness: 160 },
  });

  const barProgress = spring({
    frame: Math.max(0, relativeFrame - Math.round(0.15 * fps)),
    fps,
    config: { damping: 15, stiffness: 100 },
  });

  const exitFrames = Math.max(4, Math.round(0.2 * fps));
  const exit =
    frame > endFrame - exitFrames
      ? Math.max(0, (endFrame - frame) / exitFrames)
      : 1;

  const valA = item.valueA ?? 80;
  const valB = item.valueB ?? 25;
  const maxVal = Math.max(valA, valB, 100);
  const widthA = Math.min(100, Math.round((valA / maxVal) * 100 * barProgress));
  const widthB = Math.min(100, Math.round((valB / maxVal) * 100 * barProgress));
  const unit = item.unit ?? '%';
  const posKey =
    item.position && item.position in positionClasses
      ? (item.position as CardPosition)
      : 'bottom-left';
  const posClass = positionClasses[posKey];
  const xOffset = item.xOffset ?? 0;
  const yOffset = item.yOffset ?? 0;
  const customScale = item.scale ?? 1;

  return (
    <div
      style={{
        transform: `translate(calc(-50% + ${xOffset}px), ${yOffset}px) scale(${enter * exit * customScale})`,
        opacity: Math.min(1, enter * exit),
      }}
      className={`absolute z-30 ${posClass} w-[880px] left-1/2 bg-zinc-950/95 border-4 border-white/90 rounded-3xl p-8 shadow-2xl`}
    >
      <Sequence from={startFrame} layout="none">
        <Audio src={resolveSfxSrc(item.sfx, DEFAULT_POP_SFX)} volume={0.35} />
      </Sequence>
      <div className="flex items-center gap-4 mb-6">
        <svg
          className="w-12 h-12 text-yellow-400 shrink-0"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
        >
          <path d="M18 20V10M12 20V4M6 20v-6" strokeLinecap="round" />
        </svg>
        <span className="text-white font-black text-4xl uppercase tracking-wider">
          {item.title || 'COMPARATIVA'}
        </span>
      </div>

      {/* Barra A */}
      <div className="mb-5">
        <div className="flex justify-between text-2xl font-black text-white mb-2 uppercase">
          <span>{item.labelA || 'OPCIÓN A'}</span>
          <span className="text-yellow-400">
            {Math.round(valA * barProgress)}
            {unit}
          </span>
        </div>
        <div className="w-full h-10 bg-zinc-800 rounded-full overflow-hidden border-2 border-white/20">
          <div
            style={{
              width: `${widthA}%`,
              backgroundColor: item.colorA || '#FACC15',
            }}
            className="h-full rounded-full"
          />
        </div>
      </div>

      {/* Barra B */}
      <div>
        <div className="flex justify-between text-2xl font-black text-white mb-2 uppercase">
          <span>{item.labelB || 'OPCIÓN B'}</span>
          <span className="text-cyan-400">
            {Math.round(valB * barProgress)}
            {unit}
          </span>
        </div>
        <div className="w-full h-10 bg-zinc-800 rounded-full overflow-hidden border-2 border-white/20">
          <div
            style={{
              width: `${widthB}%`,
              backgroundColor: item.colorB || '#22D3EE',
            }}
            className="h-full rounded-full"
          />
        </div>
      </div>
    </div>
  );
};

/**
 * 2. CounterBox: Contador gigante / Calendario animado con ícono SVG
 */
export const CounterBox: React.FC<{ item: IllustrationItem }> = ({ item }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const startFrame = Math.round(item.start * fps);
  const endFrame = Math.round(item.end * fps);
  const relativeFrame = Math.max(0, frame - startFrame);

  const enter = spring({
    frame: relativeFrame,
    fps,
    config: { damping: 12, stiffness: 180 },
  });

  const countDurationFrames = Math.max(
    10,
    Math.min(
      Math.round((item.end - item.start) * fps * 0.7),
      Math.round(1.5 * fps)
    )
  );
  const fromVal = item.fromValue ?? 0;
  const toVal = item.toValue ?? 100;
  const currentVal = Math.round(
    interpolate(relativeFrame, [0, countDurationFrames], [fromVal, toVal], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    })
  );

  const exitFrames = Math.max(4, Math.round(0.2 * fps));
  const exit =
    frame > endFrame - exitFrames
      ? Math.max(0, (endFrame - frame) / exitFrames)
      : 1;

  const posKey =
    item.position && item.position in positionClasses
      ? (item.position as CardPosition)
      : 'top-right';
  const posClass = positionClasses[posKey];
  const xOffset = item.xOffset ?? 0;
  const yOffset = item.yOffset ?? 0;
  const customScale = item.scale ?? 1;
  const displayIcon = item.icon || item.emoji;

  return (
    <div
      style={{
        transform: `translate(${xOffset}px, ${yOffset}px) scale(${enter * exit * customScale})`,
        opacity: Math.min(1, enter * exit),
      }}
      className={`absolute z-30 ${posClass} bg-zinc-950/95 border-4 border-emerald-400 rounded-3xl overflow-hidden shadow-2xl min-w-[420px]`}
    >
      <Sequence from={startFrame} layout="none">
        <Audio src={resolveSfxSrc(item.sfx, DEFAULT_POP_SFX)} volume={0.35} />
      </Sequence>
      <div className="bg-emerald-500 px-6 py-3 flex items-center justify-between">
        <span className="text-zinc-950 font-black text-2xl uppercase tracking-widest">
          {item.title || 'CONTADOR'}
        </span>
        <svg
          className="w-8 h-8 text-zinc-950"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
        >
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
          <line x1="16" y1="2" x2="16" y2="6" />
          <line x1="8" y1="2" x2="8" y2="6" />
          <line x1="3" y1="10" x2="21" y2="10" />
        </svg>
      </div>
      <div className="p-7 flex flex-col items-center justify-center text-center">
        <div className="text-7xl font-black text-white tracking-tight flex items-center gap-2">
          {displayIcon && <span>{displayIcon}</span>}
          <span className="text-emerald-400">
            {item.prefix || ''}
            {currentVal}
            {item.suffix || ''}
          </span>
        </div>
        {item.subtitle && (
          <span className="text-zinc-300 font-bold text-2xl mt-2 uppercase tracking-wide">
            {item.subtitle}
          </span>
        )}
      </div>
    </div>
  );
};

/**
 * 3. StampAlert: Sello gigante cruzado en pantalla con impacto tipo "FACTOS / RECHAZADO / ALERTA"
 */
export const StampAlert: React.FC<{ item: IllustrationItem }> = ({ item }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const startFrame = Math.round(item.start * fps);
  const endFrame = Math.round(item.end * fps);
  const relativeFrame = Math.max(0, frame - startFrame);

  const slam = spring({
    frame: relativeFrame,
    fps,
    config: { damping: 9, stiffness: 260, mass: 0.7 },
  });

  const scale = interpolate(slam, [0, 1], [2.4, 1]);
  const exitFrames = Math.max(4, Math.round(0.2 * fps));
  const exit =
    frame > endFrame - exitFrames
      ? Math.max(0, (endFrame - frame) / exitFrames)
      : 1;

  const colorMap = {
    red: 'border-red-500 text-red-500 bg-red-950/90',
    green: 'border-emerald-400 text-emerald-400 bg-emerald-950/90',
    yellow: 'border-yellow-400 text-yellow-400 bg-zinc-950/90',
  };
  const chosenColor = colorMap[item.stampColor || 'red'];
  const xOffset = item.xOffset ?? 0;
  const yOffset = item.yOffset ?? 0;
  const customScale = item.scale ?? 1;
  const displayIcon = item.icon || item.emoji;

  return (
    <div
      style={{
        top: 1150,
        transform: `translate(calc(-50% + ${xOffset}px), calc(-50% + ${yOffset}px)) scale(${scale * exit * customScale}) rotate(-12deg)`,
        opacity: Math.min(1, slam * exit),
      }}
      className={`absolute left-1/2 z-30 border-[10px] ${chosenColor} px-12 py-6 rounded-3xl shadow-2xl pointer-events-none select-none`}
    >
      <Sequence from={startFrame} layout="none">
        <Audio src={resolveSfxSrc(item.sfx, DEFAULT_WHOOSH_SFX)} volume={0.35} />
      </Sequence>
      <div className="flex flex-col items-center text-center">
        <div className="flex items-center gap-4">
          {displayIcon && <span className="text-7xl">{displayIcon}</span>}
          <span className="font-black text-7xl uppercase tracking-widest">
            {item.stampText || item.title || '¡FACTOS!'}
          </span>
        </div>
        {item.subtitle && (
          <span className="text-white font-extrabold text-3xl uppercase tracking-wider mt-2">
            {item.subtitle}
          </span>
        )}
      </div>
    </div>
  );
};

/**
 * HookTitleBanner: Hook visual superior en los primeros 2.5 a 3 segundos (frames 0 a 85 a 30fps)
 */
export const HookTitleBanner: React.FC<{ title: string }> = ({ title }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const maxFrames = Math.round(2.8 * fps); // ~84 frames a 30fps
  if (frame > maxFrames) {
    return null;
  }

  const enterSpring = spring({
    frame,
    fps,
    config: {
      damping: 11,
      stiffness: 220,
      mass: 0.7,
    },
  });

  const exitDuration = Math.round(0.35 * fps);
  const exitProgress =
    frame > maxFrames - exitDuration
      ? Math.max(0, (maxFrames - frame) / exitDuration)
      : 1;

  const scale = enterSpring * exitProgress;

  return (
    <div
      style={{
        top: 100,
        transform: `translate(-50%, 0) scale(${scale})`,
        opacity: Math.min(1, enterSpring * exitProgress),
      }}
      className="absolute left-1/2 z-40 flex items-center justify-center px-6 pointer-events-none select-none w-auto max-w-[950px] text-center"
    >
      <Sequence from={0} layout="none">
        <Audio src={resolveSfxSrc(undefined, DEFAULT_WHOOSH_SFX)} volume={0.35} />
      </Sequence>
      <div className="bg-black/85 border-4 border-yellow-400 px-8 py-3.5 rounded-full shadow-[0px_10px_30px_rgba(0,0,0,0.85)] flex items-center gap-3">
        <span className="text-2xl">⚡</span>
        <span
          style={{
            fontFamily: "'Montserrat', 'Arial Black', 'Impact', sans-serif",
          }}
          className="text-white font-black text-3xl uppercase tracking-wider leading-none"
        >
          {title}
        </span>
      </div>
    </div>
  );
};

/**
 * ProgressBar: Barra de progreso continua de 6px en el borde inferior con brillo amarillo (#FFE600)
 */
export const ProgressBar: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const progressPercent = Math.min(
    100,
    Math.max(0, ((frame + 1) / durationInFrames) * 100)
  );

  return (
    <div className="absolute bottom-0 left-0 w-full h-[6px] bg-black/40 z-50 pointer-events-none">
      <div
        style={{
          width: `${progressPercent}%`,
          backgroundColor: '#FFE600',
          boxShadow: '0 0 12px #FFE600, 0 0 4px #FFFFFF',
        }}
        className="h-full"
      />
    </div>
  );
};

/**
 * ExplainerPanelOverlay: Gráficos explicativos estilo Xokas/AuronPlay
 * Renderizados directamente sobre el 62% inferior (zona del gameplay) con fondo transparente,
 * grillas de íconos escalonadas (gridItems) y tarjetas comparativas lado a lado (versusCards).
 */
export const ExplainerPanelOverlay: React.FC<{ panel: ExplainerPanel }> = ({
  panel,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const startFrame = Math.round(panel.start * fps);
  const endFrame = Math.round(panel.end * fps);
  const relativeFrame = Math.max(0, frame - startFrame);

  const exitFrames = Math.max(4, Math.round(0.2 * fps));
  const exitProgress =
    frame > endFrame - exitFrames
      ? Math.max(0, (endFrame - frame) / exitFrames)
      : 1;

  const headerSpring = spring({
    frame: relativeFrame,
    fps,
    config: { damping: 12, stiffness: 200, mass: 0.7 },
  });

  // Entrada en colisión: izquierda desde -120px, derecha desde +120px, VS cae después
  const leftSlide = spring({
    frame: Math.max(0, relativeFrame - 3),
    fps,
    config: { damping: 13, stiffness: 210, mass: 0.7 },
  });
  const rightSlide = spring({
    frame: Math.max(0, relativeFrame - 5),
    fps,
    config: { damping: 13, stiffness: 210, mass: 0.7 },
  });
  const vsDrop = spring({
    frame: Math.max(0, relativeFrame - 11),
    fps,
    config: { damping: 9, stiffness: 260, mass: 0.6 },
  });
  // Pulso continuo del VS + brillo oscilante para que nunca quede congelado
  const vsPulse = 1 + Math.sin(frame / 5) * 0.08;
  const vsScale = interpolate(vsDrop, [0, 1], [2.2, 1]) * vsPulse;
  const vsGlow = (Math.sin(frame / 5) + 1) / 2;
  // Balanceo idle muy sutil de las tarjetas y respiración de los números
  const idleSway = Math.sin(frame / 9) * 0.8;
  const valuePulse = 1 + Math.sin(frame / 6) * 0.04;

  // Count-up: si el valor es numérico (ej. "10", "+20", "9/10") cuenta desde 0 en los primeros 20 frames
  const COUNT_FRAMES = 20;
  const countUp = (value: string): string => {
    const match = value.match(/^([^\d-]*)(-?\d+(?:[.,]\d+)?)(.*)$/);
    if (!match) {
      return value;
    }
    const [, prefix, numStr, suffix] = match;
    const target = parseFloat(numStr.replace(',', '.'));
    const decimals = numStr.includes('.') || numStr.includes(',') ? 1 : 0;
    const current = interpolate(
      relativeFrame,
      [3, 3 + COUNT_FRAMES],
      [0, target],
      { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
    );
    return `${prefix}${current.toFixed(decimals)}${suffix}`;
  };

  // Normalizar gridItems por si viene un objeto único o un array
  const rawGridItems: ExplainerGridItem[] = Array.isArray(panel.gridItems)
    ? panel.gridItems
    : panel.gridItems
      ? [panel.gridItems as unknown as ExplainerGridItem]
      : [];

  // Expandir celdas de la grilla (si count <= 16 repite el ícono 'count' veces; si es mayor muestra badge xCount)
  const expandedCells: {
    icon: string;
    label?: string;
    badge?: string;
  }[] = [];

  for (const item of rawGridItems) {
    const count = Math.max(1, Math.round(item.count || 1));
    if (count <= 16 && expandedCells.length + count <= 16) {
      for (let i = 0; i < count; i++) {
        expandedCells.push({
          icon: item.icon,
          label: item.label,
          badge: count > 1 ? `${i + 1}` : undefined,
        });
      }
    } else {
      expandedCells.push({
        icon: item.icon,
        label: item.label,
        badge: count > 1 ? `×${count}` : undefined,
      });
    }
  }

  const gridColsClass =
    expandedCells.length <= 2
      ? 'grid-cols-2'
      : expandedCells.length <= 3
        ? 'grid-cols-3'
        : 'grid-cols-4';

  const xOffset = panel.xOffset ?? 0;
  const yOffset = panel.yOffset ?? 0;
  const customScale = panel.scale ?? 1;

  const hasHeader = Boolean(panel.headerLeft || panel.headerRight);
  const versus = panel.versusCards;

  return (
    <div
      style={{
        height: '62%',
        backgroundColor: 'transparent',
        backgroundImage:
          'linear-gradient(to bottom, transparent 0%, rgba(0,0,0,0.32) 30%, rgba(0,0,0,0.45) 100%)',
        opacity: exitProgress,
      }}
      className="absolute bottom-0 left-0 w-full z-20 flex flex-col justify-start px-10 pt-24 pb-12 pointer-events-none select-none"
    >
      <Sequence from={startFrame} layout="none">
        <Audio
          src={resolveSfxSrc(panel.sfx, DEFAULT_WHOOSH_SFX)}
          volume={0.35}
        />
      </Sequence>

      <div
        style={{
          transform: `translate(${xOffset}px, ${yOffset}px) scale(${customScale})`,
          transformOrigin: 'top center',
        }}
        className="w-full flex flex-col gap-6"
      >
        {/* Header Left & Header Right con badges oscuros semitransparentes y textShadow fuerte */}
        {hasHeader && (
          <div
            style={{
              transform: `scale(${headerSpring})`,
              opacity: Math.min(1, headerSpring),
            }}
            className="w-full flex items-center justify-between gap-4 bg-black/65 backdrop-blur-md border border-white/15 rounded-2xl px-7 py-4 shadow-[0_12px_30px_rgba(0,0,0,0.85)]"
          >
            {panel.headerLeft && (
              <span
                style={{
                  fontFamily:
                    "'Montserrat', 'Arial Black', 'Impact', sans-serif",
                  textShadow:
                    '0 4px 10px rgba(0,0,0,0.95), 0 0 4px rgba(0,0,0,1)',
                }}
                className="text-white font-black text-3xl uppercase tracking-wider leading-tight"
              >
                {panel.headerLeft}
              </span>
            )}
            {panel.headerRight && (
              <span
                style={{
                  fontFamily:
                    "'Montserrat', 'Arial Black', 'Impact', sans-serif",
                  textShadow:
                    '0 4px 10px rgba(0,0,0,0.95), 0 0 4px rgba(0,0,0,1)',
                }}
                className="text-[#FFE600] font-black text-3xl uppercase tracking-wider leading-tight text-right"
              >
                {panel.headerRight}
              </span>
            )}
          </div>
        )}

        {/* Grilla de Íconos (gridItems) con entrada escalonada */}
        {expandedCells.length > 0 && (
          <div className={`grid ${gridColsClass} gap-4 w-full`}>
            {expandedCells.map((cell, idx) => {
              const cellSpring = spring({
                frame: Math.max(0, relativeFrame - 3 - idx * 2),
                fps,
                config: { damping: 11, stiffness: 220, mass: 0.65 },
              });
              const isRawSvg = cell.icon.trim().startsWith('<svg');
              const safeCellSvg = isRawSvg
                ? cell.icon.replace(
                    /<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi,
                    ''
                  )
                : '';

              return (
                <div
                  key={`grid-cell-${idx}`}
                  style={{
                    transform: `scale(${cellSpring})`,
                    opacity: Math.min(1, cellSpring),
                  }}
                  className="relative bg-black/65 backdrop-blur-md border border-white/15 rounded-2xl p-4 shadow-[0_12px_28px_rgba(0,0,0,0.85)] flex flex-col items-center justify-center min-h-[155px]"
                >
                  {cell.badge && (
                    <span className="absolute top-2.5 right-3 bg-yellow-400 text-black font-black text-xl px-2.5 py-0.5 rounded-lg shadow-md">
                      {cell.badge}
                    </span>
                  )}
                  {isRawSvg ? (
                    <div
                      className="w-20 h-20 flex items-center justify-center [&>svg]:w-full [&>svg]:h-full drop-shadow-[0_6px_10px_rgba(0,0,0,0.9)]"
                      dangerouslySetInnerHTML={{ __html: safeCellSvg }}
                    />
                  ) : (
                    <span className="text-6xl leading-none drop-shadow-[0_6px_10px_rgba(0,0,0,0.9)]">
                      {cell.icon}
                    </span>
                  )}
                  {cell.label && (
                    <span
                      style={{
                        textShadow: '0 3px 6px rgba(0,0,0,0.95)',
                      }}
                      className="text-white font-extrabold text-xl uppercase tracking-wide mt-2 text-center leading-tight"
                    >
                      {cell.label}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Tarjetas Comparativas Lado a Lado (versusCards) con entrada en colisión */}
        {versus && (
          <div className="relative grid grid-cols-2 gap-6 w-full mt-1">
            {/* Card Izquierda: entra deslizándose desde la izquierda */}
            <div
              style={{
                transform: `translateX(${interpolate(leftSlide, [0, 1], [-120, 0])}px) rotate(${interpolate(leftSlide, [0, 1], [-4, 0]) + idleSway}deg)`,
                opacity: Math.min(1, leftSlide),
              }}
              className="bg-black/65 backdrop-blur-md border border-cyan-300/30 rounded-3xl p-7 shadow-[0_16px_35px_rgba(0,0,0,0.9),0_0_28px_rgba(34,211,238,0.22)] flex flex-col items-center justify-center text-center"
            >
              <span
                style={{
                  textShadow: '0 3px 8px rgba(0,0,0,0.95)',
                }}
                className="text-white font-black text-3xl uppercase tracking-wider"
              >
                {versus.leftTitle}
              </span>
              {versus.leftSub && (
                <span
                  style={{
                    textShadow: '0 2px 6px rgba(0,0,0,0.95)',
                  }}
                  className="text-zinc-300 font-bold text-xl uppercase tracking-wide mt-1"
                >
                  {versus.leftSub}
                </span>
              )}
              <span
                style={{
                  fontFamily:
                    "'Montserrat', 'Arial Black', 'Impact', sans-serif",
                  textShadow:
                    '0 6px 14px rgba(0,0,0,0.95), 0 0 6px rgba(0,0,0,1)',
                  transform: `scale(${valuePulse})`,
                }}
                className="text-cyan-400 font-black text-7xl uppercase tracking-tight mt-4"
              >
                {countUp(versus.leftValue)}
              </span>
            </div>

            {/* Badge central VS: cae con golpe de escala y luego pulsa con brillo */}
            <div
              style={{
                transform: `translate(-50%, -50%) scale(${vsScale})`,
                opacity: Math.min(1, vsDrop * 1.5),
                boxShadow: `0 8px 20px rgba(0,0,0,0.9), 0 0 ${18 + vsGlow * 22}px rgba(255,170,0,${0.55 + vsGlow * 0.35})`,
              }}
              className="absolute left-1/2 top-1/2 z-10 bg-yellow-400 border-4 border-black text-black font-black text-3xl px-4 py-2.5 rounded-full"
            >
              VS
            </div>

            {/* Card Derecha: entra deslizándose desde la derecha */}
            <div
              style={{
                transform: `translateX(${interpolate(rightSlide, [0, 1], [120, 0])}px) rotate(${interpolate(rightSlide, [0, 1], [4, 0]) - idleSway}deg)`,
                opacity: Math.min(1, rightSlide),
              }}
              className="bg-black/65 backdrop-blur-md border border-yellow-300/30 rounded-3xl p-7 shadow-[0_16px_35px_rgba(0,0,0,0.9),0_0_28px_rgba(255,230,0,0.22)] flex flex-col items-center justify-center text-center"
            >
              <span
                style={{
                  textShadow: '0 3px 8px rgba(0,0,0,0.95)',
                }}
                className="text-white font-black text-3xl uppercase tracking-wider"
              >
                {versus.rightTitle}
              </span>
              {versus.rightSub && (
                <span
                  style={{
                    textShadow: '0 2px 6px rgba(0,0,0,0.95)',
                  }}
                  className="text-zinc-300 font-bold text-xl uppercase tracking-wide mt-1"
                >
                  {versus.rightSub}
                </span>
              )}
              <span
                style={{
                  fontFamily:
                    "'Montserrat', 'Arial Black', 'Impact', sans-serif",
                  textShadow:
                    '0 6px 14px rgba(0,0,0,0.95), 0 0 6px rgba(0,0,0,1)',
                  transform: `scale(${valuePulse})`,
                }}
                className="text-[#FFE600] font-black text-7xl uppercase tracking-tight mt-4"
              >
                {countUp(versus.rightValue)}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

/**
 * ChannelWatermark: Badge fijo con los logos de YouTube y Kick + marca "berlinuno"
 * En formato dividido (gameplay + cam) se ubica en la línea divisoria (y = 640px).
 * En cámara completa (cameraFullscreenRanges) baja al borde del difuminado inferior (85%)
 * para no tapar la cara ni el pecho del streamer.
 */
export const ChannelWatermark: React.FC<{ isFullscreen?: boolean }> = ({
  isFullscreen = false,
}) => {
  return (
    <div
      style={{
        top: isFullscreen ? '85%' : '640px',
        transform: 'translate(-50%, -50%)',
      }}
      className="absolute left-1/2 z-40 pointer-events-none select-none"
    >
      <div className="flex items-center gap-4 bg-black/75 backdrop-blur-md border border-white/25 rounded-full px-8 py-3.5 shadow-[0_8px_25px_rgba(0,0,0,0.75)]">
        {/* Logo SVG de YouTube (#FF0000 con triángulo blanco) */}
        <svg
          className="w-11 h-8 shrink-0"
          viewBox="0 0 36 26"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <rect width="36" height="26" rx="7" fill="#FF0000" />
          <polygon points="14,7 14,19 25,13" fill="#FFFFFF" />
        </svg>

        {/* Logo SVG de Kick (#53FC18 con la "K" geométrica/pixelada) */}
        <svg
          className="w-9 h-9 shrink-0"
          viewBox="0 0 28 28"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <rect width="28" height="28" rx="6" fill="#0B0E0F" stroke="#53FC18" strokeWidth="2" />
          <path
            d="M6 5H11V11.5H13.5V8.5H16.5V5H22V9.5H19V12.5H16.5V15.5H19V18.5H22V23H16.5V19.5H13.5V16.5H11V23H6V5Z"
            fill="#53FC18"
          />
        </svg>

        {/* Nombre del canal */}
        <span
          style={{
            fontFamily: "'Montserrat', 'Arial Black', 'Impact', sans-serif",
          }}
          className="text-white font-black text-3xl tracking-wider lowercase leading-none drop-shadow-[0_2px_4px_rgba(0,0,0,0.9)]"
        >
          berlinuno
        </span>
      </div>
    </div>
  );
};

const resolveVideoSrc = (videoSrc: string | undefined | null): string =>
  videoSrc
    ? videoSrc.startsWith('http') || videoSrc.startsWith('/')
      ? videoSrc
      : staticFile(videoSrc)
    : '';

const resolveActiveVideoSrc = (data: ShortData): string => {
  const enhanced = data.webcamEnhancedFile?.trim();
  const useEnhanced =
    Boolean(enhanced) && (data.usarMejoraIA ?? true);
  return resolveVideoSrc(useEnhanced ? enhanced : data.videoSrc);
};

/**
 * TeaserLabelBadge: Badge superior durante el hookTeaser (ej. "MÁS ADELANTE...").
 */
const TeaserLabelBadge: React.FC<{ label: string }> = ({ label }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({
    frame,
    fps,
    config: { damping: 11, stiffness: 220, mass: 0.7 },
  });
  // Punto rojo parpadeante estilo "REC"
  const blink = Math.floor(frame / 8) % 2 === 0 ? 1 : 0.25;

  return (
    <div
      style={{
        top: 100,
        transform: `translate(-50%, ${interpolate(enter, [0, 1], [-40, 0])}px) scale(${interpolate(enter, [0, 1], [0.7, 1])})`,
        opacity: Math.min(1, enter * 1.4),
      }}
      className="absolute left-1/2 z-40 pointer-events-none select-none"
    >
      <div className="flex items-center gap-3 bg-black/85 border-4 border-red-500 px-8 py-3.5 rounded-full shadow-[0px_10px_30px_rgba(0,0,0,0.85)]">
        <span
          style={{ opacity: blink }}
          className="w-4 h-4 rounded-full bg-red-500 shrink-0"
        />
        <span
          style={{
            fontFamily: "'Montserrat', 'Arial Black', 'Impact', sans-serif",
          }}
          className="text-white font-black text-3xl uppercase tracking-wider leading-none whitespace-nowrap"
        >
          {label}
        </span>
      </div>
    </div>
  );
};

/**
 * HookTeaserSegment: Reproduce el fragmento destacado (hookTeaser.start → end) del clip
 * con sus subtítulos re-sincronizados al inicio del teaser y el badge opcional.
 * Se monta dentro de un <Sequence> que empieza en el frame 0.
 */
const HookTeaserSegment: React.FC<{ data: ShortData; teaser: HookTeaser }> = ({
  data,
  teaser,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const sourceTime = teaser.start + frame / fps;
  const videoSrc = resolveActiveVideoSrc(data);

  const sourceSubtitle = data.subtitles?.find(
    (s) => sourceTime >= s.start && sourceTime <= s.end
  );
  // Tiempos relativos al inicio del teaser para que el pop y el SFX caigan en el frame correcto
  const teaserSubtitle = sourceSubtitle
    ? {
        ...sourceSubtitle,
        start: Math.max(0, sourceSubtitle.start - teaser.start),
        end: sourceSubtitle.end - teaser.start,
      }
    : undefined;

  return (
    <AbsoluteFill>
      {videoSrc && (
        <OffthreadVideo
          src={videoSrc}
          startFrom={Math.round(teaser.start * fps)}
          endAt={Math.round(teaser.end * fps)}
          className="w-full h-full object-cover"
          style={{ filter: 'contrast(1.06) saturate(1.12)' }}
        />
      )}
      {teaser.label && <TeaserLabelBadge label={teaser.label} />}
      {teaserSubtitle && (
        <AnimatedSubtitle
          key={`teaser-${sourceSubtitle?.start}`}
          item={teaserSubtitle}
          config={data.subtitleConfig}
        />
      )}
    </AbsoluteFill>
  );
};

/**
 * TeaserCutFlash: Flash blanco de 3 frames + whoosh en el corte entre el teaser y el video completo.
 */
const TeaserCutFlash: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill
      style={{
        backgroundColor: '#FFFFFF',
        opacity: interpolate(frame, [0, 3], [1, 0], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
        }),
      }}
      className="z-50 pointer-events-none"
    >
      <Audio src={resolveSfxSrc(undefined, DEFAULT_WHOOSH_SFX)} volume={0.4} />
    </AbsoluteFill>
  );
};

/**
 * MainShortContent: El video completo desde 0:00 con subtítulos, hook, tarjetas, ilustraciones
 * y paneles. Al estar dentro de un <Sequence from={teaserFrames}>, useCurrentFrame() es relativo
 * al inicio del video principal, así que todo queda desplazado y sincronizado automáticamente.
 */
const MainShortContent: React.FC<{ data: ShortData }> = ({ data }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentTime = frame / fps;

  const editStyle = data.editStyle || 'simple';

  const activeSubtitle = data.subtitles?.find(
    (s) => currentTime >= s.start && currentTime <= s.end
  );

  const showCards = editStyle === 'detallada' || editStyle === 'ilustraciones';
  const showIllustrations = editStyle === 'ilustraciones';

  const activeCards = showCards
    ? (data.cards || []).filter(
        (c) => currentTime >= c.start && currentTime <= c.end
      )
    : [];

  const activeIllustrations = showIllustrations
    ? (data.illustrations || []).filter(
        (ill) => currentTime >= ill.start && currentTime <= ill.end
      )
    : [];

  const activeExplainerPanels = showCards
    ? (data.explainerPanels || []).filter(
        (panel) => currentTime >= panel.start && currentTime <= panel.end
      )
    : [];

  const resolvedVideoSrc = resolveActiveVideoSrc(data);

  return (
    <AbsoluteFill>
      {resolvedVideoSrc ? (
        <OffthreadVideo
          src={resolvedVideoSrc}
          className="w-full h-full object-cover"
          style={{ filter: 'contrast(1.06) saturate(1.12)' }}
        />
      ) : (
        <AbsoluteFill className="flex flex-col">
          {/* Placeholder 1080x640 Webcam */}
          <div className="w-full h-[640px] bg-gradient-to-b from-indigo-950 to-slate-900 border-b-4 border-yellow-400/40 flex flex-col items-center justify-center">
            <span className="text-white/40 font-black text-4xl tracking-widest uppercase">
              CÁMARA STREAMER (1080x640)
            </span>
          </div>
          {/* Placeholder 1080x1280 Gameplay */}
          <div className="w-full h-[1280px] bg-gradient-to-b from-slate-900 to-zinc-950 flex flex-col items-center justify-center">
            <span className="text-white/30 font-black text-5xl tracking-widest uppercase">
              GAMEPLAY / FONDO (1080x1280)
            </span>
          </div>
        </AbsoluteFill>
      )}

      {/* Hook visual en los primeros 2.5 a 3 segundos del video principal */}
      {data.hookTitle && <HookTitleBanner title={data.hookTitle} />}

      {/* Modo 'detallada' e 'ilustraciones': Gráficos Explainer transparentes sobre el gameplay */}
      {activeExplainerPanels.map((panel, idx) => (
        <ExplainerPanelOverlay key={`explainer-${idx}`} panel={panel} />
      ))}

      {/* Modo 'detallada' e 'ilustraciones': Tarjetas y sellos animados */}
      {activeCards.map((card, idx) => (
        <AnimatedCard key={`${card.title || card.text || 'card'}-${idx}`} card={card} />
      ))}

      {/* Modo 'ilustraciones': Ilustraciones SVG literales + Gráficos React/SVG */}
      {activeIllustrations.map((ill, idx) => {
        if (
          ill.type === 'custom_svg' ||
          ill.type === 'CustomGraphic' ||
          Boolean(ill.svg)
        ) {
          return <DynamicSvgIllustration key={`ill-${idx}`} item={ill} />;
        }
        if (ill.type === 'ComparisonBar') {
          return <ComparisonBar key={`ill-${idx}`} item={ill} />;
        }
        if (ill.type === 'CounterBox') {
          return <CounterBox key={`ill-${idx}`} item={ill} />;
        }
        return <StampAlert key={`ill-${idx}`} item={ill} />;
      })}

      {/* Subtítulo dinámico palabra por palabra */}
      {activeSubtitle && (
        <AnimatedSubtitle item={activeSubtitle} config={data.subtitleConfig} />
      )}
    </AbsoluteFill>
  );
};

export const ShortComposition: React.FC<ShortData & { data?: ShortData }> = (
  props
) => {
  const data: ShortData = props.data ?? props;
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const teaser = data.hookTeaser;
  const teaserFrames = getTeaserDurationFrames(teaser, fps);

  const sourceTime =
    teaser && teaserFrames > 0 && frame < teaserFrames
      ? teaser.start + frame / fps
      : (frame - teaserFrames) / fps;

  const isFullscreenCam = Boolean(
    data.cameraFullscreenRanges?.some(
      (range) => sourceTime >= range.start && sourceTime <= range.end
    )
  );

  return (
    <AbsoluteFill className="bg-black overflow-hidden">
      {/* 0. Música de fondo con loop automático, fades y cortes dramáticos en remates */}
      {data.backgroundMusic?.file && (
        <BackgroundMusicLayer
          music={data.backgroundMusic}
          teaserFrames={teaserFrames}
        />
      )}

      {/* 1. Gancho inicial: fragmento destacado antes del video completo */}
      {teaser && teaserFrames > 0 && (
        <Sequence durationInFrames={teaserFrames} name="Hook Teaser">
          <HookTeaserSegment data={data} teaser={teaser} />
        </Sequence>
      )}

      {/* 2. Video completo desde 0:00, desplazado por la duración del teaser */}
      <Sequence
        from={teaserFrames}
        name="Video principal"
        premountFor={teaserFrames > 0 ? fps : undefined}
      >
        <MainShortContent data={data} />
      </Sequence>

      {/* Transición rápida en el corte teaser → video completo */}
      {teaserFrames > 0 && (
        <Sequence from={teaserFrames} durationInFrames={3} name="Flash de corte">
          <TeaserCutFlash />
        </Sequence>
      )}

      {/* Badge fijo del canal ("berlinuno" + YouTube + Kick) durante todo el Short */}
      <ChannelWatermark isFullscreen={isFullscreenCam} />

      {/* Barra de progreso inferior fina (6px) con brillo amarillo */}
      <ProgressBar />
    </AbsoluteFill>
  );
};
