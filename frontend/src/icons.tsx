import type { SVGProps } from 'react'

const P = {
  copy: 'M9 9h10v10H9zM5 15V5h10',
  check: 'M5 12l5 5L20 7',
  download: 'M12 4v11m0 0l-4-4m4 4l4-4M5 19h14',
  clip: 'M21 11.5l-8.5 8.5a5 5 0 01-7-7L14 4.5a3.3 3.3 0 014.7 4.7L10 17.9a1.7 1.7 0 01-2.4-2.4l8-8',
  folder: 'M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z',
  send: 'M5 12h14M13 6l6 6-6 6',
  stop: 'M7 7h10v10H7z',
  plus: 'M12 5v14M5 12h14',
  trash: 'M4 7h16M9 7V4h6v3m-8 0l1 13h8l1-13',
  pin: 'M9 4h6l-1 6 4 3H6l4-3zM12 13v7',
  edit: 'M4 20h4L19 9l-4-4L4 16zM14 6l4 4',
  sun: 'M12 4V2m0 20v-2m8-8h2M2 12h2m13.7-5.7l1.4-1.4M4.9 19.1l1.4-1.4m11.4 0l1.4 1.4M4.9 4.9l1.4 1.4M12 8a4 4 0 100 8 4 4 0 000-8z',
  moon: 'M20 14.5A8 8 0 019.5 4 8 8 0 1020 14.5z',
  logout: 'M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10',
  settings: 'M12 9a3 3 0 100 6 3 3 0 000-6zM19 12l2-1-1-3-2 .3-1.3-1.3L17 5l-3-1-1 2h-2L10 4 7 5l.3 2L6 8.3 4 8l-1 3 2 1v0l-2 1 1 3 2-.3 1.3 1.3L7 19l3 1 1-2h2l1 2 3-1-.3-2 1.3-1.3 2 .3 1-3z',
  file: 'M7 3h7l5 5v13H7zM14 3v5h5',
  chevron: 'M9 6l6 6-6 6',
  code: 'M9 7l-5 5 5 5M15 7l5 5-5 5',
  play: 'M8 5l11 7-11 7z',
  x: 'M6 6l12 12M18 6L6 18',
  menu: 'M4 6h16M4 12h16M4 18h16',
  panel: 'M4 5h16v14H4zM15 5v14',
} as const

export type IconName = keyof typeof P

export function Icon({ name, size = 16, ...rest }: { name: IconName; size?: number } & SVGProps<SVGSVGElement>) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...rest}>
      <path d={P[name]} />
    </svg>
  )
}
