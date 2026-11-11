import React, { useEffect, useState } from 'react';
import {
  Composition,
  continueRender,
  delayRender,
  staticFile,
} from 'remotion';
import { ShortComposition } from './ShortComposition';
import { ShortData, shortSchema } from './types';
import defaultData from '../public/data.json';
import proyectosIndexDefault from '../public/proyectos/index.json';
import './style.css';

const FPS = 30;

/**
 * Remotion solo permite a-z, A-Z, 0-9 y guiones '-' en el id de <Composition />.
 * Si un nombre de archivo tiene '_' o espacios (ej. 'clip_01'), lo normaliza a 'clip-01'
 * para el id de Remotion, manteniendo el nombre real para cargar 'proyectos/<nombre>.json'.
 */
const toValidCompositionId = (name: string): string => {
  const cleaned = name
    .replace(/[^a-zA-Z0-9-\u4E00-\u9FFF]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return cleaned || 'clip';
};

const buildCalculateMetadata = (jsonRelativePath: string) => {
  return async ({
    props,
    defaultProps,
  }: {
    props: ShortData;
    defaultProps: ShortData;
  }) => {
    let loadedData: ShortData = props;
    const isUnmodifiedDefault =
      JSON.stringify(props) === JSON.stringify(defaultProps);

    if (isUnmodifiedDefault) {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 1500);
        const response = await fetch(staticFile(jsonRelativePath), {
          signal: controller.signal,
        });
        clearTimeout(timeoutId);
        if (response.ok) {
          loadedData = (await response.json()) as ShortData;
        }
      } catch {
        // Si falla o da timeout, continúa inmediatamente con defaultProps
      }
    }

    const maxSubtitleEnd =
      loadedData.subtitles?.reduce((max, s) => Math.max(max, s.end), 0) ?? 0;
    const maxCardEnd =
      loadedData.cards?.reduce((max, c) => Math.max(max, c.end), 0) ?? 0;
    const maxIllustrationEnd =
      loadedData.illustrations?.reduce(
        (max, ill) => Math.max(max, ill.end),
        0
      ) ?? 0;
    const maxExplainerEnd =
      loadedData.explainerPanels?.reduce(
        (max, ep) => Math.max(max, ep.end),
        0
      ) ?? 0;

    const totalSeconds =
      loadedData.durationInSeconds ||
      Math.max(
        10,
        Math.ceil(
          Math.max(
            maxSubtitleEnd,
            maxCardEnd,
            maxIllustrationEnd,
            maxExplainerEnd
          ) + 1
        )
      );

    return {
      fps: FPS,
      durationInFrames: Math.round(totalSeconds * FPS),
      props: loadedData,
    };
  };
};

export const RemotionRoot: React.FC = () => {
  const [projectList, setProjectList] = useState<string[]>(() =>
    Array.isArray(proyectosIndexDefault) ? proyectosIndexDefault : []
  );

  useEffect(() => {
    let mounted = true;
    fetch(staticFile('proyectos/index.json'))
      .then(async (res) => {
        if (res.ok) {
          const list = await res.json();
          if (mounted && Array.isArray(list)) {
            setProjectList(list.map((item) => String(item)));
          }
        }
      })
      .catch(() => {
        // Usa proyectosIndexDefault si falla el fetch
      });

    return () => {
      mounted = false;
    };
  }, []);

  return (
    <>
      {projectList.map((projectName) => {
        const compId = toValidCompositionId(projectName);
        return (
          <Composition
            key={projectName}
            id={compId}
            component={ShortComposition}
            schema={shortSchema}
            fps={FPS}
            width={1080}
            height={1920}
            defaultProps={defaultData as ShortData}
            calculateMetadata={buildCalculateMetadata(
              `proyectos/${projectName}.json`
            )}
          />
        );
      })}

      {/* Composición de respaldo apuntando a public/data.json */}
      <Composition
        id="MainShort"
        component={ShortComposition}
        schema={shortSchema}
        fps={FPS}
        width={1080}
        height={1920}
        defaultProps={defaultData as ShortData}
        calculateMetadata={buildCalculateMetadata('data.json')}
      />
    </>
  );
};
