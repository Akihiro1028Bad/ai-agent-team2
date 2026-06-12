import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement>;
const base = {
  width: 16,
  height: 16,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.7,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export const IconGrid = (p: P) => (
  <svg {...base} {...p}><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></svg>
);
export const IconInbox = (p: P) => (
  <svg {...base} {...p}><path d="M4 13l2.5-7.5A2 2 0 0 1 8.4 4h7.2a2 2 0 0 1 1.9 1.5L20 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" /><path d="M4 13h4l1.5 2.5h5L16 13h4" /></svg>
);
export const IconSliders = (p: P) => (
  <svg {...base} {...p}><path d="M4 6h10M18 6h2M4 12h2M10 12h10M4 18h7M15 18h5" /><circle cx="16" cy="6" r="2" /><circle cx="8" cy="12" r="2" /><circle cx="13" cy="18" r="2" /></svg>
);
export const IconPlay = (p: P) => (
  <svg {...base} {...p}><path d="M7 4.5v15l13-7.5z" /></svg>
);
export const IconPause = (p: P) => (
  <svg {...base} {...p}><rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" /></svg>
);
export const IconCommit = (p: P) => (
  <svg {...base} {...p}><circle cx="12" cy="12" r="3.2" /><path d="M3 12h5.8M15.2 12H21" /></svg>
);
export const IconCpu = (p: P) => (
  <svg {...base} {...p}><rect x="7" y="7" width="10" height="10" rx="2" /><path d="M10 2v3M14 2v3M10 19v3M14 19v3M2 10h3M2 14h3M19 10h3M19 14h3" /></svg>
);
export const IconMessage = (p: P) => (
  <svg {...base} {...p}><path d="M4 5h16v11H9l-4 3v-3H4z" /></svg>
);
export const IconAlert = (p: P) => (
  <svg {...base} {...p}><path d="M12 4l9 16H3z" /><path d="M12 10v4M12 17.5v.01" /></svg>
);
export const IconCheck = (p: P) => (
  <svg {...base} {...p}><path d="M20 6L9 17l-5-5" /></svg>
);
export const IconClock = (p: P) => (
  <svg {...base} {...p}><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></svg>
);
export const IconBolt = (p: P) => (
  <svg {...base} {...p}><path d="M13 2L4 14h7l-1 8 9-12h-7z" /></svg>
);
export const IconExternal = (p: P) => (
  <svg {...base} {...p}><path d="M14 4h6v6M20 4l-9 9M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" /></svg>
);
export const IconMenu = (p: P) => (
  <svg {...base} {...p}><path d="M4 6h16M4 12h16M4 18h16" /></svg>
);
export const IconX = (p: P) => (
  <svg {...base} {...p}><path d="M6 6l12 12M18 6L6 18" /></svg>
);
export const IconArrow = (p: P) => (
  <svg {...base} {...p}><path d="M5 12h14M13 6l6 6-6 6" /></svg>
);
export const IconGate = (p: P) => (
  <svg {...base} {...p}><path d="M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7z" /><path d="M9 12l2 2 4-4" /></svg>
);
export const IconSplit = (p: P) => (
  <svg {...base} {...p}><circle cx="6" cy="6" r="2.5" /><circle cx="6" cy="18" r="2.5" /><circle cx="18" cy="12" r="2.5" /><path d="M8 7l8 4M8 17l8-4" /></svg>
);
export const IconBell = (p: P) => (
  <svg {...base} {...p}><path d="M18 9a6 6 0 1 0-12 0c0 5-2 6-2 6h16s-2-1-2-6" /><path d="M10.3 19a2 2 0 0 0 3.4 0" /></svg>
);
export const IconSearch = (p: P) => (
  <svg {...base} {...p}><circle cx="11" cy="11" r="6.5" /><path d="M16 16l5 5" /></svg>
);
export const IconChart = (p: P) => (
  <svg {...base} {...p}><path d="M4 20V10M10 20V4M16 20v-8M21 20H3" /></svg>
);
export const IconDollar = (p: P) => (
  <svg {...base} {...p}><path d="M12 2v20M16.5 6.5c-1-1.2-2.7-1.8-4.5-1.8-2.5 0-4.5 1.3-4.5 3.4 0 4.6 9 2.6 9 7.2 0 2.1-2 3.5-4.5 3.5-2 0-3.8-.8-4.8-2" /></svg>
);
export const IconBrain = (p: P) => (
  <svg {...base} {...p}><path d="M9.5 3A2.5 2.5 0 0 0 7 5.5v.6A3 3 0 0 0 4.5 9 3 3 0 0 0 3 11.6c0 1 .5 1.9 1.3 2.4A3 3 0 0 0 6 19.5c.3 0 .5 0 .8-.1A2.7 2.7 0 0 0 9.5 21c1.4 0 2.5-1.1 2.5-2.5v-13A2.5 2.5 0 0 0 9.5 3z" /><path d="M14.5 3A2.5 2.5 0 0 1 17 5.5v.6A3 3 0 0 1 19.5 9a3 3 0 0 1 1.5 2.6c0 1-.5 1.9-1.3 2.4a3 3 0 0 1-1.7 5.5c-.3 0-.5 0-.8-.1A2.7 2.7 0 0 1 14.5 21a2.5 2.5 0 0 1-2.5-2.5v-13A2.5 2.5 0 0 1 14.5 3z" /></svg>
);
export const IconDiff = (p: P) => (
  <svg {...base} {...p}><path d="M12 3v18M7 7H3M7 11H3M21 15h-4M21 19h-4" /></svg>
);
export const IconTerminal = (p: P) => (
  <svg {...base} {...p}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 9l3 3-3 3M12 15h5" /></svg>
);
export const IconGantt = (p: P) => (
  <svg {...base} {...p}><path d="M3 5h8M7 12h10M11 19h8" strokeWidth="3" /></svg>
);
export const IconHeart = (p: P) => (
  <svg {...base} {...p}><path d="M3 12h4l2-5 3 10 2.5-7 1.5 2h5" /></svg>
);
export const IconRewind = (p: P) => (
  <svg {...base} {...p}><path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v5h5" /></svg>
);
export const IconStop = (p: P) => (
  <svg {...base} {...p}><rect x="6" y="6" width="12" height="12" rx="2" /></svg>
);
export const IconUp = (p: P) => (
  <svg {...base} {...p}><path d="M12 19V5M6 11l6-6 6 6" /></svg>
);
export const IconDown = (p: P) => (
  <svg {...base} {...p}><path d="M12 5v14M6 13l6 6 6-6" /></svg>
);
export const IconEdit = (p: P) => (
  <svg {...base} {...p}><path d="M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17z" /><path d="M13.5 6.5l3 3" /></svg>
);
export const IconLayers = (p: P) => (
  <svg {...base} {...p}><path d="M12 3l9 5-9 5-9-5z" /><path d="M3 13l9 5 9-5" /></svg>
);
