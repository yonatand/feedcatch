import { useState } from 'react';
import { safeUrl } from '../lib/anilist';

type Props = {
  url: string | null | undefined;
  /** Accessible name; normally the series name. Its first letter is the placeholder. */
  alt: string;
  size?: 'xs' | 'sm' | 'lg';
};

const DIMS = { xs: [40, 56], sm: [48, 68], lg: [120, 170] } as const;

/** Cover image from AniList's CDN (lazy, no referrer), or a lettered placeholder box. */
export function Cover({ url, alt, size = 'sm' }: Props) {
  const [failed, setFailed] = useState(false);
  const [w, h] = DIMS[size];
  const src = safeUrl(url);
  if (!src || failed) {
    const letter = alt.trim().charAt(0).toUpperCase() || '?';
    return (
      <span className={`cover cover-${size} cover-placeholder`} role="img" aria-label={alt}>
        <span aria-hidden="true">{letter}</span>
      </span>
    );
  }
  return (
    <img
      className={`cover cover-${size}`}
      src={src}
      alt={alt}
      width={w}
      height={h}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
}
