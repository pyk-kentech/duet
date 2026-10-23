// 작은 선 아이콘 (24px 격자, stroke). 외부 아이콘 묶음 없이 쓰는 것만.
const P: Record<string, string> = {
  work: "M4 6h16M4 12h16M4 18h10",
  gauge: "M12 14l4-4M4 18a8 8 0 1 1 16 0",
  flask: "M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3",
  plug: "M9 7V3M15 7V3M7 7h10v4a5 5 0 0 1-10 0V7zM12 16v5",
  cog: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z",
  talk: "M4 5h16v11H8l-4 4V5z",
  diff: "M8 3v12M5 12l3 3 3-3M16 21V9M13 12l3-3 3 3",
  merge: "M6 3v12a6 6 0 0 0 6 6M6 3a2 2 0 1 0 0 .1M18 15a2 2 0 1 0 0 .1M18 13V9a4 4 0 0 0-4-4h-2",
  drafts: "M4 4h7v16H4zM13 4h7v16h-7z",
  issue: "M12 8v5M12 16v.1M12 3l9 16H3z",
  console: "M4 6l5 5-5 5M11 18h9",
  doc: "M7 3h7l5 5v13H7zM14 3v5h5",
  robot: "M7 9h10v9H7zM12 5v4M9 13v.1M15 13v.1M5 12v3M19 12v3",
  terminal: "M4 5h16v14H4zM7 9l3 3-3 3M12 15h5",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4",
  plus: "M12 5v14M5 12h14",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  folderPlus: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM12 11v5M9.5 13.5h5",
  files: "M8 3h7l4 4v11H8zM15 3v4h4M5 7v14h11",
  git: "M6 3v12M18 9a3 3 0 1 0 0-.1M6 21a3 3 0 1 0 0-.1M18 12a9 9 0 0 1-9 9",
  pin: "M12 17v5M9 3h6l-1 6 3 3H7l3-3z",
  split: "M4 5h16v14H4zM12 5v14",
  play: "M7 5l12 7-12 7z",
  panelLeft: "M4 5h16v14H4zM9 5v14",
  panelRight: "M4 5h16v14H4zM15 5v14",
  flow: "M5 6h6M5 12h10M5 18h14",
  stack: "M12 3l9 5-9 5-9-5zM3 13l9 5 9-5",
  check: "M5 12l4 4 10-10",
  dots: "M5 12v.1M12 12v.1M19 12v.1",
};

export function Icon({ name, size = 18, label }: { name: keyof typeof P | string; size?: number; label?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}
         strokeLinecap="round" strokeLinejoin="round" role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      <path d={P[name] || P.work} />
    </svg>
  );
}
