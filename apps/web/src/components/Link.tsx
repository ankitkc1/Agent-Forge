import type { AnchorHTMLAttributes, MouseEvent } from 'react';
import { navigate } from '@/router';

type LinkProps = AnchorHTMLAttributes<HTMLAnchorElement> & { to: string; replace?: boolean };

/** In-app link: plain anchor semantics (open in new tab, copy link) with client-side navigation. */
export function Link({ to, replace, onClick, ...props }: LinkProps) {
  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (props.target && props.target !== '_self') return;
    event.preventDefault();
    navigate(to, { replace });
    window.scrollTo({ top: 0 });
  };
  return <a href={to} onClick={handleClick} {...props} />;
}
