import React from 'react';
import {
  Audio,
  Img,
  interpolate,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import { CardItem, CardPosition } from '../types';
import { DEFAULT_POP_SFX, resolveSfxSrc } from '../utils/mediaPaths';

const LEGACY_IMAGE_POSITION_CLASSES: Record<CardPosition, string> = {
  'top-left': 'top-14 left-10',
  'top-right': 'top-14 right-10',
  center: 'top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2',
  'bottom-left': 'bottom-32 left-10',
  'bottom-right': 'bottom-32 right-10',
};

const EDITORIAL_FONT_STACK =
  "'Inter', 'Montserrat', 'Arial Black', sans-serif";

const ENTER_FRAMES = 10;
const EXIT_FRAMES = 8;

const resolveImageAssetSrc = (imagePath: string): string =>
  imagePath.startsWith('http') || imagePath.startsWith('/')
    ? imagePath
    : staticFile(imagePath);

/**
 * LegacyImageCard: Mantiene soporte para stickers PNG con transparencia y capturas de chat.
 * No afecta las tarjetas/etiquetas superiores de texto.
 */
const LegacyImageCard: React.FC<{ card: CardItem }> = ({ card }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const startFrame = Math.round(card.start * fps);
  const endFrame = Math.round(card.end * fps);
  const relativeFrame = Math.max(0, frame - startFrame);

  const enterSpring = spring({
    frame: relativeFrame,
    fps,
    config: { damping: 12, stiffness: 180, mass: 0.8 },
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
    : LEGACY_IMAGE_POSITION_CLASSES[card.position || 'top-right'];
  const baseTranslate = isCentered
    ? `translate(calc(-50% + ${xOffset}px), calc(-50% + ${yOffset}px))`
    : `translate(${xOffset}px, ${yOffset}px)`;
  const imgSrc = resolveImageAssetSrc(card.image || '');

  if (card.variant === 'sticker') {
    const floatY = Math.sin(frame / 4) * 8;
    const wiggleRot = Math.sin(frame / 5) * 4;
    return (
      <div
        style={{
          transform: `${baseTranslate} translateY(${floatY}px) rotate(${wiggleRot}deg) scale(${scale})`,
          opacity: Math.min(1, enterSpring * exitProgress),
        }}
        className={`absolute z-30 ${posClass} pointer-events-none select-none`}
      >
        <Sequence from={startFrame} layout="none">
          <Audio src={resolveSfxSrc(card.sfx, DEFAULT_POP_SFX)} volume={0.35} />
        </Sequence>
        <Img
          src={imgSrc}
          alt={card.texto || card.title || 'Sticker'}
          className="w-[400px] h-auto object-contain"
          style={{
            filter: 'drop-shadow(0 14px 26px rgba(0,0,0,0.85))',
          }}
        />
      </div>
    );
  }

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
            {card.texto || card.title || 'PREGUNTA DEL CHAT'}
          </span>
        </div>
        {(card.subtitulo || card.subtitle) && (
          <span className="text-white/70 font-bold text-lg uppercase tracking-wide">
            {card.subtitulo || card.subtitle}
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
};

/**
 * TopCardBanner: Etiqueta/tarjeta superior fija y completamente recta (0deg de inclinación).
 * Posición única centrada horizontalmente en `top: 130px` (zona segura de YouTube Shorts).
 * Soporta estilo `"editorial"` (caja blanca con badge azul marino) y `"coral"` (píldora rosa coral de impacto).
 */
export const TopCardBanner: React.FC<{ card: CardItem }> = ({ card }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  if (card.image) {
    return <LegacyImageCard card={card} />;
  }

  const startFrame = Math.round(card.start * fps);
  const endFrame = Math.round(card.end * fps);
  const relativeFrame = Math.max(0, frame - startFrame);

  // Entrada rápida con spring: escala 0.88 -> 1.0 y opacidad 0 -> 1 en 10 frames
  const enterSpring = spring({
    frame: relativeFrame,
    fps,
    durationInFrames: ENTER_FRAMES,
    config: { damping: 16, stiffness: 260, mass: 0.6 },
  });
  const enterScale = interpolate(enterSpring, [0, 1], [0.88, 1.0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const enterOpacity = interpolate(relativeFrame, [0, ENTER_FRAMES], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // Salida limpia de fade/escala en 8 frames
  const exitStartFrame = Math.max(startFrame, endFrame - EXIT_FRAMES);
  const exitProgress =
    frame >= exitStartFrame
      ? interpolate(frame, [exitStartFrame, endFrame], [1, 0], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
        })
      : 1;
  const exitScale = interpolate(exitProgress, [0, 1], [0.92, 1.0]);

  const finalScale = enterScale * exitScale;
  const finalOpacity = Math.min(1, enterOpacity * exitProgress);

  const estilo = card.estilo || 'editorial';
  const rawTexto = (card.texto || card.title || card.text || '').trim();
  const displaySubtitulo = (
    card.subtitulo ||
    card.subtitle ||
    card.subtext ||
    ''
  ).trim();
  const displayBadge = (card.badge || '★ MOMENTO').trim();

  // Ajuste sutil dentro del rango 34px-38px según longitud del titular
  const editorialTitleSize =
    rawTexto.length > 40 ? 34 : rawTexto.length <= 26 ? 38 : 36;

  return (
    <div
      style={{
        top: 130,
        left: '50%',
        transform: `translateX(-50%) scale(${finalScale}) rotate(0deg)`,
        opacity: finalOpacity,
        maxWidth: 860,
        width: 'max-content',
      }}
      className="absolute z-30 pointer-events-none select-none flex justify-center"
    >
      <Sequence from={startFrame} layout="none">
        <Audio src={resolveSfxSrc(card.sfx, DEFAULT_POP_SFX)} volume={0.35} />
      </Sequence>

      {estilo === 'coral' ? (
        <div
          style={{
            backgroundColor: '#FF4D6D',
            borderRadius: 18,
            padding: '16px 34px',
            maxWidth: 860,
            boxShadow: '0 10px 25px rgba(0, 0, 0, 0.25)',
            fontFamily: EDITORIAL_FONT_STACK,
          }}
          className="flex flex-col items-center justify-center text-center"
        >
          <span
            style={{
              color: '#FFFFFF',
              fontSize: 42,
              fontWeight: 900,
              lineHeight: 1.08,
              textTransform: 'uppercase',
              letterSpacing: '-0.01em',
            }}
          >
            {rawTexto}
          </span>
        </div>
      ) : (
        <div
          style={{
            backgroundColor: '#FFFFFF',
            borderRadius: 16,
            padding: '20px 26px',
            maxWidth: 860,
            minWidth: 460,
            boxShadow: '0 12px 32px rgba(0, 0, 0, 0.28)',
            fontFamily: EDITORIAL_FONT_STACK,
          }}
          className="flex flex-col items-start text-left"
        >
          <span
            style={{
              backgroundColor: '#0B132B',
              color: '#FFFFFF',
              borderRadius: 999,
              padding: '5px 12px',
              fontSize: 14,
              fontWeight: 800,
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
              lineHeight: 1.1,
              marginBottom: 10,
            }}
          >
            {displayBadge}
          </span>

          <span
            style={{
              color: '#0B132B',
              fontSize: editorialTitleSize,
              fontWeight: 900,
              lineHeight: 1.08,
              textTransform: 'uppercase',
              letterSpacing: '-0.015em',
              textAlign: 'left',
            }}
          >
            {rawTexto}
          </span>

          {displaySubtitulo && (
            <span
              style={{
                color: '#475569',
                fontSize: 15,
                fontWeight: 700,
                letterSpacing: '0.08em',
                lineHeight: 1.25,
                textTransform: 'uppercase',
                textAlign: 'left',
                marginTop: 8,
              }}
            >
              {displaySubtitulo}
            </span>
          )}
        </div>
      )}
    </div>
  );
};
