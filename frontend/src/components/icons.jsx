// Minimal inline icon set — stroke-based, inherits currentColor.
// Keeps the bundle dependency-free and the visual language consistent.

const base = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.7,
  strokeLinecap: "round",
  strokeLinejoin: "round",
};

function Svg({ size = 18, children, ...rest }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base} {...rest}>
      {children}
    </svg>
  );
}

export const Icon = {
  chat: (p) => (
    <Svg {...p}>
      <path d="M21 11.5a7.5 7.5 0 0 1-10.9 6.7L3 20l1.8-6A7.5 7.5 0 1 1 21 11.5z" />
      <path d="M8.5 11.5h.01M12 11.5h.01M15.5 11.5h.01" />
    </Svg>
  ),
  dashboard: (p) => (
    <Svg {...p}>
      <rect x="3" y="3" width="7" height="9" rx="1.5" />
      <rect x="14" y="3" width="7" height="5" rx="1.5" />
      <rect x="14" y="12" width="7" height="9" rx="1.5" />
      <rect x="3" y="16" width="7" height="5" rx="1.5" />
    </Svg>
  ),
  review: (p) => (
    <Svg {...p}>
      <path d="M9 11l3 3L22 4" />
      <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
    </Svg>
  ),
  reconcile: (p) => (
    <Svg {...p}>
      <path d="M17 3l4 4-4 4" />
      <path d="M21 7H7a4 4 0 0 0-4 4" />
      <path d="M7 21l-4-4 4-4" />
      <path d="M3 17h14a4 4 0 0 0 4-4" />
    </Svg>
  ),
  close: (p) => (
    <Svg {...p}>
      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
      <path d="M9 13l2 2 4-4" />
    </Svg>
  ),
  ledger: (p) => (
    <Svg {...p}>
      <path d="M4 4h12l4 4v12a0 0 0 0 1 0 0H4a0 0 0 0 1 0 0V4z" />
      <path d="M8 9h7M8 13h7M8 17h4" />
    </Svg>
  ),
  refund: (p) => (
    <Svg {...p}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </Svg>
  ),
  advice: (p) => (
    <Svg {...p}>
      <path d="M9 18h6M10 21h4" />
      <path d="M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.2 1 2.5h6c0-1.3.3-1.8 1-2.5A6 6 0 0 0 12 3z" />
    </Svg>
  ),
  plus: (p) => (
    <Svg {...p}>
      <path d="M12 5v14M5 12h14" />
    </Svg>
  ),
  edit: (p) => (
    <Svg {...p}>
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
    </Svg>
  ),
  upload: (p) => (
    <Svg {...p}>
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <path d="M17 8l-5-5-5 5M12 3v12" />
    </Svg>
  ),
  mail: (p) => (
    <Svg {...p}>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M3 7l9 6 9-6" />
    </Svg>
  ),
  check: (p) => (
    <Svg {...p}>
      <path d="M20 6L9 17l-5-5" />
    </Svg>
  ),
  x: (p) => (
    <Svg {...p}>
      <path d="M18 6L6 18M6 6l12 12" />
    </Svg>
  ),
  warn: (p) => (
    <Svg {...p}>
      <path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
      <path d="M12 9v4M12 17h.01" />
    </Svg>
  ),
  camera: (p) => (
    <Svg {...p}>
      <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
      <circle cx="12" cy="13" r="4" />
    </Svg>
  ),
  lock: (p) => (
    <Svg {...p}>
      <rect x="3" y="11" width="18" height="11" rx="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </Svg>
  ),
  receipt: (p) => (
    <Svg {...p}>
      <path d="M5 3v18l2-1.5L9 21l2-1.5L13 21l2-1.5L17 21l2-1.5V3l-2 1.5L15 3l-2 1.5L11 3 9 4.5 7 3z" />
      <path d="M8 8h8M8 12h8M8 16h5" />
    </Svg>
  ),
  bank: (p) => (
    <Svg {...p}>
      <path d="M3 10l9-6 9 6" />
      <path d="M5 10v9M19 10v9M9 10v9M15 10v9M3 21h18" />
    </Svg>
  ),
  search: (p) => (
    <Svg {...p}>
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4-4" />
    </Svg>
  ),
  gauge: (p) => (
    <Svg {...p}>
      <path d="M3 21h18" />
      <rect x="4" y="12" width="4" height="7" rx="1" />
      <rect x="10" y="7" width="4" height="12" rx="1" />
      <rect x="16" y="3" width="4" height="16" rx="1" />
    </Svg>
  ),
};
