import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useAuthStatus, useDashboard, useLogout } from '../api/hooks';
import { relativeTime } from './TimeAgo';

const NAV: { to: string; label: string; end?: boolean }[] = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/feeds', label: 'Feeds' },
  { to: '/series', label: 'Series' },
  { to: '/rules', label: 'Rules' },
  { to: '/releases', label: 'Releases' },
  { to: '/downloads', label: 'Downloads' },
  { to: '/qbittorrent', label: 'qBittorrent' },
  { to: '/activity', label: 'Activity' },
  { to: '/settings', label: 'Settings' },
];

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
    </div>
  );
}

export function Layout() {
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  const auth = useAuthStatus();
  const logout = useLogout();

  useEffect(() => {
    setOpen(false);
  }, [loc.pathname]);

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className={`sidebar${open ? ' open' : ''}`}>
        <div className="sidebar-top">
          <NavLinkBrand />
          <button
            type="button"
            className="btn btn-sm btn-ghost menu-toggle"
            aria-expanded={open}
            aria-controls="main-nav"
            onClick={() => setOpen((o) => !o)}
          >
            {open ? 'Close' : 'Menu'}
          </button>
        </div>
        <nav id="main-nav" className="nav" aria-label="Main">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <SchedulerIndicator />
          {auth.data?.auth_mode === 'password' && auth.data.authenticated ? (
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => logout.mutate()} disabled={logout.isPending}>
              Log out
            </button>
          ) : null}
        </div>
      </aside>
      <main id="main" className="main" tabIndex={-1}>
        <div className="content">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

function NavLinkBrand() {
  return (
    <NavLink to="/" className="brand" end>
      <span className="brand-mark" aria-hidden="true">
        ≡
      </span>
      feedcatch
    </NavLink>
  );
}
