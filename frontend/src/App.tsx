import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { Suspense, lazy, useEffect } from 'react';
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import { ApiError, setUnauthorizedHandler } from './api/client';
import { qk, useAuthStatus } from './api/hooks';
import { ErrorBanner } from './components/ErrorBanner';
import { Layout } from './components/Layout';
import { LoadingBlock } from './components/Spinner';

const Dashboard = lazy(() => import('./pages/Dashboard'));
const Feeds = lazy(() => import('./pages/Feeds'));
const SeriesList = lazy(() => import('./pages/SeriesList'));
const SeriesNew = lazy(() => import('./pages/SeriesNew'));
const SeriesDetail = lazy(() => import('./pages/SeriesDetail'));
const Rules = lazy(() => import('./pages/Rules'));
const Releases = lazy(() => import('./pages/Releases'));
const Calendar = lazy(() => import('./pages/Calendar'));
const Wanted = lazy(() => import('./pages/Wanted'));
const ReleaseInspector = lazy(() => import('./pages/ReleaseInspector'));
const Downloads = lazy(() => import('./pages/Downloads'));
const QBittorrent = lazy(() => import('./pages/QBittorrent'));
const Activity = lazy(() => import('./pages/Activity'));
const Settings = lazy(() => import('./pages/Settings'));
const Login = lazy(() => import('./pages/Login'));
const Setup = lazy(() => import('./pages/Setup'));
const NotFound = lazy(() => import('./pages/NotFound'));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: true,
      retry: (count, err) => {
        if (err instanceof ApiError && err.status >= 400 && err.status < 500) return false;
        return count < 2;
      },
    },
    mutations: { retry: false },
  },
});

/** Re-check auth status whenever any API call returns 401; the gate then routes to /login or /setup. */
function UnauthorizedBridge() {
  const qc = useQueryClient();
  useEffect(() => {
    setUnauthorizedHandler(() => {
      void qc.invalidateQueries({ queryKey: qk.auth });
    });
    return () => setUnauthorizedHandler(null);
  }, [qc]);
  return null;
}

function AuthGate() {
  const { data, error, isLoading, refetch } = useAuthStatus();
  const loc = useLocation();
  if (isLoading) return <LoadingBlock label="Checking session…" />;
  if (error || !data) {
    return (
      <div className="content narrow">
        <ErrorBanner error={error ?? 'Could not load auth status'} title="Cannot reach the server" onRetry={() => void refetch()} />
      </div>
    );
  }
  if (data.auth_mode === 'disabled') return <Outlet />;
  if (data.setup_required) return <Navigate to="/setup" replace />;
  if (!data.authenticated) return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />;
  return <Outlet />;
}

function Page({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<LoadingBlock />}>{children}</Suspense>;
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <UnauthorizedBridge />
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Page><Login /></Page>} />
          <Route path="/setup" element={<Page><Setup /></Page>} />
          <Route element={<AuthGate />}>
            <Route element={<Layout />}>
              <Route index element={<Page><Dashboard /></Page>} />
              <Route path="feeds" element={<Page><Feeds /></Page>} />
              <Route path="series" element={<Page><SeriesList /></Page>} />
              <Route path="series/new" element={<Page><SeriesNew /></Page>} />
              <Route path="series/:id" element={<Page><SeriesDetail /></Page>} />
              <Route path="rules" element={<Page><Rules /></Page>} />
              <Route path="releases" element={<Page><Releases /></Page>} />
              <Route path="releases/:id" element={<Page><ReleaseInspector /></Page>} />
              <Route path="calendar" element={<Page><Calendar /></Page>} />
              <Route path="wanted" element={<Page><Wanted /></Page>} />
              <Route path="downloads" element={<Page><Downloads /></Page>} />
              <Route path="qbittorrent" element={<Page><QBittorrent /></Page>} />
              <Route path="activity" element={<Page><Activity /></Page>} />
              <Route path="settings" element={<Page><Settings /></Page>} />
              <Route path="*" element={<Page><NotFound /></Page>} />
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
