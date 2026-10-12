import type { SVGProps } from 'react';

type IconName =
  | 'plus' | 'builds' | 'file' | 'tools' | 'chart' | 'shield' | 'arrow'
  | 'lock' | 'check' | 'play' | 'download' | 'copy' | 'refresh' | 'menu';

const paths: Record<IconName, React.ReactNode> = {
  plus: <><path d="M12 3v18M3 12h18" /></>,
  builds: <><path d="M4 7h16M4 7l2-3h5l2 3M6 7v13h12V7M9 11v5M15 11v5" /></>,
  file: <><path d="M7 3h8l4 4v14H7zM15 3v5h4M10 12h6M10 16h6" /></>,
  tools: <><path d="m14.5 6.5 3-3 3 3-3 3M3 12h9M12 12l4-4M12 12l4 4M16 16h5" /></>,
  chart: <><path d="M4 19V9M10 19V5M16 19v-7M22 19H2" /></>,
  shield: <><path d="M12 3 4.5 6v5c0 4.7 3.1 8.5 7.5 10 4.4-1.5 7.5-5.3 7.5-10V6L12 3Z" /><path d="m9 12 2 2 4-4" /></>,
  arrow: <><path d="M5 12h14M13 6l6 6-6 6" /></>,
  lock: <><path d="M7 10V8a5 5 0 0 1 10 0v2M5 10h14v11H5z" /></>,
  check: <><path d="m5 12 4 4L19 6" /></>,
  play: <><path d="M8 5v14l11-7L8 5Z" /></>,
  download: <><path d="M12 3v12M7 10l5 5 5-5M4 21h16" /></>,
  copy: <><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></>,
  refresh: <><path d="M20 7v5h-5M4 17v-5h5M6.1 8.5A7 7 0 0 1 18.5 7M17.9 15.5A7 7 0 0 1 5.5 17" /></>,
  menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
};

export function Icon({ name, ...props }: SVGProps<SVGSVGElement> & { name: IconName }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name]}</svg>;
}

