import { useEffect, useRef, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useAuthStatus, useDashboard, useLogout } from '../api/hooks';
import { relativeTime } from './TimeAgo';

const NAV: { to: string; label: string; end?: boolean }[] = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/feeds', label: 'Feeds' },
  { to: '/series', label: 'Series' },
  { to: '/rules', label: 'Rules' },
  { to: '/releases', label: 'Releases' },
  { to: '/calendar', label: 'Calendar' },
  { to: '/wanted', label: 'Wanted' },
  { to: '/downloads', label: 'Downloads' },
  { to: '/qbittorrent', label: 'qBittorrent' },
  { to: '/activity', label: 'Activity' },
  { to: '/settings', label: 'Settings' },
];

/** Title shown in the mobile app bar for the current route. */
function pageTitle(path: string): string {
  if (path === '/series/new') return 'New series';
  if (/^\/series\/[^/]+$/.test(path)) return 'Series';
  if (/^\/releases\/[^/]+$/.test(path)) return 'Match inspector';
  const hit = NAV.find((n) => (n.end ? path === n.to : path === n.to || path.startsWith(`${n.to}/`)));
  return hit ? hit.label : 'feedcatch';
}

function SchedulerIndicator() {
  const { data, isError } = useDashboard();
  if (isError) {
    return (
      <div className="sched-indicator" title="Could not load scheduler state">
        <span className="dot dot-grey" aria-hidden="true" /> scheduler unknown
      </div>
    );
  }
  if (!data) return null;
  const running = data.scheduler.running;
  const next = data.scheduler.next_feed_poll_at;
  return (
    <div
      className="sched-indicator"
      title={next ? `Next feed poll ${relativeTime(next)} (${next})` : running ? 'Scheduler running' : 'Scheduler stopped'}
    >
      <span className={`dot ${running ? 'dot-green' : 'dot-red'}`} aria-hidden="true" />
      {running ? 'scheduler running' : 'scheduler stopped'}
      {next ? (
        <span className="sched-next">
          <span className="sched-sep"> · </span>next poll {relativeTime(next)}
        </span>
      ) : null}
    </div>
  );
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <>
      {NAV.map((n) => (
        <NavLink key={n.to} to={n.to} end={n.end} onClick={onNavigate} className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
          {n.label}
        </NavLink>
      ))}
    </>
  );
}

function SidebarFoot() {
  const auth = useAuthStatus();
  const logout = useLogout();
  return (
    <div className="sidebar-foot">
      <SchedulerIndicator />
      {auth.data?.auth_mode === 'password' && auth.data.authenticated ? (
        <button type="button" className="btn btn-sm btn-ghost" onClick={() => logout.mutate()} disabled={logout.isPending}>
          Log out
        </button>
      ) : null}
    </div>
  );
}

function MenuIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M4 6h16M4 12h16M4 18h16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" fill="none" />
    </svg>
  );
}

/** Mobile (<= 900px): sticky top app bar + full-height slide-over menu. Desktop: left sidebar. */
export function Layout() {
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  const menuBtn = useRef<HTMLButtonElement>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setOpen(false);
  }, [loc.pathname]);

  // While the menu is open: lock body scroll, close on Escape, keep focus inside; restore focus on close.
  useEffect(() => {
    if (!open) return undefined;
    closeBtn.current?.focus();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        setOpen(false);
        return;
      }
      if (e.key === 'Tab' && panel.current) {
        const items = panel.current.querySelectorAll<HTMLElement>('a[href], button:not([disabled])');
        if (items.length === 0) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = overflow;
      if (panel.current?.contains(document.activeElement)) menuBtn.current?.focus();
    };
  }, [open]);

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="appbar">
        <NavLink to="/" className="appbar-brand" end aria-label="feedcatch dashboard">
          <span className="brand-mark" aria-hidden="true">
            ≡
          </span>
          <span className="appbar-brand-name">feedcatch</span>
        </NavLink>
        <span className="appbar-title">{pageTitle(loc.pathname)}</span>
        <button
          ref={menuBtn}
          type="button"
          className="appbar-menu"
          aria-expanded={open}
          aria-controls="mobile-nav"
          aria-label="Open menu"
          onClick={() => setOpen(true)}
        >
          <MenuIcon />
        </button>
      </header>
      <div className={`mnav-root${open ? ' open' : ''}`} aria-hidden={!open}>
        <div className="mnav-backdrop" onClick={() => setOpen(false)} />
        <div ref={panel} id="mobile-nav" className="mnav" role="dialog" aria-modal="true" aria-label="Menu">
          <div className="mnav-head">
            <span className="brand">
              <span className="brand-mark" aria-hidden="true">
                ≡
              </span>
              feedcatch
            </span>
            <button ref={closeBtn} type="button" className="mnav-close" aria-label="Close menu" onClick={() => setOpen(false)}>
              ×
            </button>
          </div>
          <nav className="mnav-links" aria-label="Main">
            <NavLinks onNavigate={() => setOpen(false)} />
          </nav>
          <SidebarFoot />
        </div>
      </div>
      <aside className="sidebar">
        <div className="sidebar-top">
          <NavLink to="/" className="brand" end>
            <span className="brand-mark" aria-hidden="true">
              ≡
            </span>
            feedcatch
          </NavLink>
        </div>
        <nav id="main-nav" className="nav" aria-label="Main">
          <NavLinks />
        </nav>
        <SidebarFoot />
      </aside>
      <main id="main" className="main" tabIndex={-1}>
        <div className="content">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
