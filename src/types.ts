import { z } from 'zod';

export const editStyleSchema = z.enum(['simple', 'detallada', 'ilustraciones']);
export type EditStyle = z.infer<typeof editStyleSchema>;

export const subtitleConfigSchema = z.object({
  yOffset: z.number().min(-500).max(500).default(0),
  scale: z.number().min(0.5).max(2.5).step(0.05).default(1),
});
export type SubtitleConfig = z.infer<typeof subtitleConfigSchema>;

export const subtitleItemSchema = z.object({
  word: z.string(),
  start: z.number(),
  end: z.number(),
  highlight: z.boolean().optional(),
  sfx: z.string().optional(),
});
export type SubtitleItem = z.infer<typeof subtitleItemSchema>;

export const cardPositionSchema = z.enum([
  'top-left',
  'top-right',
  'center',
  'bottom-left',
  'bottom-right',
]);
export type CardPosition = z.infer<typeof cardPositionSchema>;

export const svgPositionSchema = z.enum([
  'top',
  'center',
  'bottom',
  'top-left',
  'top-right',
  'bottom-left',
  'bottom-right',
]);
export type SvgPosition = z.infer<typeof svgPositionSchema>;

export const svgAnimationSchema = z.enum(['pop', 'float', 'shake']);
export type SvgAnimation = z.infer<typeof svgAnimationSchema>;

export const cardItemSchema = z.object({
  title: z.string(),
  subtitle: z.string().optional(),
  emoji: z.string().optional(),
  icon: z.string().optional(),
  start: z.number(),
  end: z.number(),
  position: cardPositionSchema.optional(),
  variant: z.enum(['card', 'stamp']).optional(),
  xOffset: z.number().min(-600).max(600).default(0).optional(),
  yOffset: z.number().min(-800).max(800).default(0).optional(),
  scale: z.number().min(0.3).max(3).step(0.05).default(1).optional(),
  sfx: z.string().optional(),
});
export type CardItem = z.infer<typeof cardItemSchema>;

export const illustrationTypeSchema = z.enum([
  'custom_svg',
  'CustomGraphic',
  'ComparisonBar',
  'CounterBox',
  'StampAlert',
]);
export type IllustrationType = z.infer<typeof illustrationTypeSchema>;

export const illustrationItemSchema = z.object({
  type: illustrationTypeSchema,
  start: z.number(),
  end: z.number(),
  position: svgPositionSchema.optional(),
  title: z.string().optional(),
  subtitle: z.string().optional(),
  emoji: z.string().optional(),
  icon: z.string().optional(),
  xOffset: z.number().min(-600).max(600).default(0).optional(),
  yOffset: z.number().min(-800).max(800).default(0).optional(),
  scale: z.number().min(0.3).max(3).step(0.05).default(1).optional(),
  sfx: z.string().optional(),
  // Propiedades para custom_svg / CustomGraphic (DynamicSvgIllustration)
  svg: z.string().optional(),
  animation: svgAnimationSchema.optional(),
  label: z.string().optional(),
  // Propiedades para ComparisonBar (A vs B)
  labelA: z.string().optional(),
  valueA: z.number().optional(),
  colorA: z.string().optional(),
  labelB: z.string().optional(),
  valueB: z.number().optional(),
  colorB: z.string().optional(),
  unit: z.string().optional(),
  // Propiedades para CounterBox (Contador / Calendario animado)
  fromValue: z.number().optional(),
  toValue: z.number().optional(),
  prefix: z.string().optional(),
  suffix: z.string().optional(),
  // Propiedades para StampAlert (Sello gigante cruzado en pantalla)
  stampText: z.string().optional(),
  stampColor: z.enum(['red', 'green', 'yellow']).optional(),
});
export type IllustrationItem = z.infer<typeof illustrationItemSchema>;

export const explainerGridItemSchema = z.object({
  icon: z.string(),
  label: z.string().optional(),
  count: z.number().min(1).max(500).default(1),
});
export type ExplainerGridItem = z.infer<typeof explainerGridItemSchema>;

export const explainerVersusCardsSchema = z.object({
  leftTitle: z.string(),
  leftSub: z.string().optional(),
  leftValue: z.string(),
  rightTitle: z.string(),
  rightSub: z.string().optional(),
  rightValue: z.string(),
});
export type ExplainerVersusCards = z.infer<typeof explainerVersusCardsSchema>;

export const explainerPanelSchema = z.object({
  start: z.number(),
  end: z.number(),
  headerLeft: z.string().optional(),
  headerRight: z.string().optional(),
  gridItems: z.array(explainerGridItemSchema).optional(),
  versusCards: explainerVersusCardsSchema.optional(),
  sfx: z.string().optional(),
  xOffset: z.number().min(-600).max(600).default(0).optional(),
  yOffset: z.number().min(-800).max(800).default(0).optional(),
  scale: z.number().min(0.4).max(2.5).step(0.05).default(1).optional(),
});
export type ExplainerPanel = z.infer<typeof explainerPanelSchema>;

export const shortSchema = z.object({
  editStyle: editStyleSchema.optional(),
  hookTitle: z.string().optional(),
  subtitleConfig: subtitleConfigSchema.optional(),
  videoSrc: z.string(),
  durationInSeconds: z.number().optional(),
  cards: z.array(cardItemSchema).optional(),
  explainerPanels: z.array(explainerPanelSchema).optional(),
  illustrations: z.array(illustrationItemSchema).optional(),
  subtitles: z.array(subtitleItemSchema),
});

export type ShortData = z.infer<typeof shortSchema>;
