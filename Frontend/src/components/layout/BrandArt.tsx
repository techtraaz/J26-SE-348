import { useState } from "react";
import { BRAND } from "./brand";

// Sri Lanka Air Force artwork for the app's chrome and page background:
// the crest (an image file), the national flag (an image file) and the jet and
// mountain silhouettes (drawn here as vectors, so they recolour with the theme).


/** An image that simply disappears if its file is not there yet. */
export function BrandImage({ src, alt, className, style }: {
  src: string; alt: string; className?: string; style?: React.CSSProperties;
}) {
  const [missing, setMissing] = useState(false);
  if (missing) return null;
  return <img src={src} alt={alt} className={className} style={style} onError={() => setMissing(true)} draggable={false} />;
}

/** A fighter jet in side view, nose to the right. */
export function Jet({ className, style }: { className?: string; style?: React.CSSProperties }) {
  return (
    <svg viewBox="0 0 220 90" className={className} style={style} aria-hidden focusable="false">
      <g fill="currentColor">
        {/* fuselage and nose */}
        <path d="M14 47 L58 44 L150 39 Q190 40 214 45 Q190 50 150 51 L58 52 L14 53 Z" />
        {/* canopy */}
        <path d="M138 40 Q150 30 170 36 L172 40 Z" opacity="0.85" />
        {/* far wing, swept back */}
        <path d="M78 43 L122 42 L92 22 L80 23 Z" opacity="0.7" />
        {/* near wing, swept back */}
        <path d="M70 50 L128 49 L88 80 L66 79 Z" />
        {/* tail fin */}
        <path d="M14 47 L44 45 L30 10 L16 12 Z" />
        {/* tailplane */}
        <path d="M12 51 L44 51 L28 64 L10 63 Z" />
        {/* exhaust */}
        <path d="M4 46 L14 46 L14 54 L4 54 Z" opacity="0.8" />
      </g>
    </svg>
  );
}

/** Layered mountain ridges along the bottom of the page. */
export function Mountains({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 1440 220" preserveAspectRatio="none" className={className} aria-hidden focusable="false">
      <path fill="currentColor" opacity="0.35"
            d="M0 150 L120 96 L210 132 L330 70 L430 118 L560 60 L690 124 L790 84 L900 128 L1030 66 L1150 120 L1260 88 L1360 118 L1440 96 L1440 220 L0 220 Z" />
      <path fill="currentColor" opacity="0.55"
            d="M0 180 L140 130 L260 168 L380 120 L500 160 L640 112 L760 164 L880 126 L1000 166 L1120 124 L1240 164 L1340 136 L1440 158 L1440 220 L0 220 Z" />
      <path fill="currentColor" opacity="0.8"
            d="M0 206 L180 178 L340 200 L520 172 L700 202 L880 176 L1060 204 L1240 180 L1440 200 L1440 220 L0 220 Z" />
    </svg>
  );
}

/** The page background: clear sky, mountains, two jets and the crest as a watermark. */
export function SkyBackdrop() {
  return (
    <div className="slaf-sky" aria-hidden>
      <BrandImage src={BRAND.crest} alt="" className="slaf-sky-crest" />
      <Jet className="slaf-sky-jet slaf-sky-jet-a" />
      <Jet className="slaf-sky-jet slaf-sky-jet-b" />
      <Mountains className="slaf-sky-mountains" />
    </div>
  );
}
