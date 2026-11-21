import { staticFile } from 'remotion';

export const DEFAULT_POP_SFX = 'SONIDOS/efecto de sonido POP.mp3';
export const DEFAULT_WHOOSH_SFX = 'Whosh/Swipe Swoosh Transition Sound Effect.mp3';
export const DEFAULT_DING_SFX =
  'SONIDOS/ES_Notification, Tutorial Message Appear, Attention, Video Game 02 - Epidemic Sound.mp3';

/** Resuelve rutas relativas de efectos de sonido dentro de `public/sfx/`. */
export const resolveSfxSrc = (
  sfx: string | undefined,
  defaultFile: string
): string => {
  const chosen = sfx?.trim() || defaultFile;
  const normalized = chosen.replace(/^\/+/, '');
  const withPrefix = normalized.startsWith('sfx/')
    ? normalized
    : `sfx/${normalized}`;
  return staticFile(withPrefix);
};
