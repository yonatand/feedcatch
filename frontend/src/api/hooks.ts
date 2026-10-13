import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';
import type {
  ActivityEvent,
  AppSettings,
  AppSettingsIn,
  AuthStatus,
  Dashboard,
  Download,
  DownloadStatus,
  EntryOutcome,
  FeedEntry,
  FeedEntryDetail,
  FeedEntryPreview,
  FeedIn,
  FeedSource,
  FeedTestResult,
  GrabIn,
  GrabPreview,
  ItemsResponse,
  ListResponse,
  PollResult,
  PreviewPathIn,
  QbitConfig,
  QbitConfigIn,
  QbitTestResult,
  RegexValidation,
  Rule,
  RuleIn,
  Season,
  SeasonIn,
  SeasonPath,
  Series,
  SeriesIn,
  SimulateIn,
  SimulationResult,
  TestRecentResult,
} from './types';

export const qk = {
  auth: ['auth'] as const,
  dashboard: ['dashboard'] as const,
  feeds: ['feeds'] as const,
  feed: (id: number) => ['feeds', id] as const,
  series: ['series'] as const,
  seriesOne: (id: number) => ['series', id] as const,
  seriesPaths: (id: number) => ['series', id, 'paths'] as const,
  rules: (seriesId?: number) => ['rules', seriesId ?? 'all'] as const,
  entries: (f: EntryFilters) => ['entries', f] as const,
  entry: (id: number) => ['entry', id] as const,
  downloads: (f: DownloadFilters) => ['downloads', f] as const,
  qbit: ['qbit'] as const,
  settings: ['settings'] as const,
  activity: (f: ActivityFilters) => ['activity', f] as const,
};

// ---------------- Auth ----------------

export function useAuthStatus() {
  return useQuery({
    queryKey: qk.auth,
    queryFn: () => api<AuthStatus>('/api/auth/status'),
    staleTime: 60_000,
    retry: 1,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (password: string) => api<void>('/api/auth/login', { method: 'POST', body: { password } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.auth }),
  });
}

export function useSetup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (password: string) => api<void>('/api/auth/setup', { method: 'POST', body: { password } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.auth }),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>('/api/auth/logout', { method: 'POST' }),
    onSuccess: () => {
      qc.clear();
      void qc.invalidateQueries({ queryKey: qk.auth });
    },
  });
}

// ---------------- Dashboard ----------------

export function useDashboard() {
  return useQuery({
    queryKey: qk.dashboard,
    queryFn: () => api<Dashboard>('/api/dashboard'),
    refetchInterval: 30_000,
  });
}

// ---------------- Feeds ----------------

export function useFeeds() {
  return useQuery({ queryKey: qk.feeds, queryFn: () => api<ListResponse<FeedSource>>('/api/feeds') });
}

export function useSaveFeed() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id?: number; body: FeedIn }) =>
      id === undefined
        ? api<FeedSource>('/api/feeds', { method: 'POST', body })
        : api<FeedSource>(`/api/feeds/${id}`, { method: 'PUT', body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.feeds });
      void qc.invalidateQueries({ queryKey: qk.dashboard });
    },
  });
}

export function useDeleteFeed() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>(`/api/feeds/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.feeds });
      void qc.invalidateQueries({ queryKey: qk.dashboard });
    },
  });
}

export function useTestFeedUrl() {
  return useMutation({
    mutationFn: (url: string) => api<FeedTestResult>('/api/feeds/test', { method: 'POST', body: { url } }),
  });
}

export function useFeedPreview(feedId: number | null, limit = 50) {
  return useQuery({
    queryKey: ['feeds', feedId, 'preview', limit],
    queryFn: () => api<ListResponse<FeedEntryPreview>>(`/api/feeds/${feedId ?? 0}/preview`, { query: { limit } }),
    enabled: feedId !== null,
    staleTime: 60_000,
    retry: false,
  });
}

export function fetchFeedPreview(feedId: number, limit = 50) {
  return api<ListResponse<FeedEntryPreview>>(`/api/feeds/${feedId}/preview`, { query: { limit } });
}

export function usePollFeed() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<PollResult>(`/api/feeds/${id}/poll`, { method: 'POST' }),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: qk.feeds });
      void qc.invalidateQueries({ queryKey: qk.dashboard });
      void qc.invalidateQueries({ queryKey: ['entries'] });
      void qc.invalidateQueries({ queryKey: ['downloads'] });
    },
  });
}

// ---------------- Series / seasons ----------------

export function useSeriesList() {
  return useQuery({ queryKey: qk.series, queryFn: () => api<ListResponse<Series>>('/api/series') });
}

export function useSeries(id: number) {
  return useQuery({
    queryKey: qk.seriesOne(id),
    queryFn: () => api<Series>(`/api/series/${id}`),
    enabled: Number.isFinite(id),
  });
}

export function useSeriesPaths(id: number) {
  return useQuery({
    queryKey: qk.seriesPaths(id),
    queryFn: () => api<ItemsResponse<SeasonPath>>(`/api/series/${id}/paths`),
    enabled: Number.isFinite(id),
  });
}

function invalidateSeries(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: qk.series });
  void qc.invalidateQueries({ queryKey: ['rules'] });
  void qc.invalidateQueries({ queryKey: qk.dashboard });
}

export function useCreateSeries() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SeriesIn) => api<Series>('/api/series', { method: 'POST', body }),
    onSuccess: () => invalidateSeries(qc),
  });
}

export function useUpdateSeries() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: SeriesIn }) =>
      api<Series>(`/api/series/${id}`, { method: 'PUT', body }),
    onSuccess: () => invalidateSeries(qc),
  });
}

export function useDeleteSeries() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>(`/api/series/${id}`, { method: 'DELETE' }),
    onSuccess: () => invalidateSeries(qc),
  });
}

export function useCreateSeason() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ seriesId, body }: { seriesId: number; body: SeasonIn }) =>
      api<Season>(`/api/series/${seriesId}/seasons`, { method: 'POST', body }),
    onSuccess: () => invalidateSeries(qc),
  });
}

export function useUpdateSeason() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: SeasonIn }) =>
      api<Season>(`/api/seasons/${id}`, { method: 'PUT', body }),
    onSuccess: () => invalidateSeries(qc),
  });
}

export function useDeleteSeason() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>(`/api/seasons/${id}`, { method: 'DELETE' }),
    onSuccess: () => invalidateSeries(qc),
  });
}

export function previewPath(body: PreviewPathIn) {
  return api<{ save_path: string }>('/api/series/preview-path', { method: 'POST', body });
}

// ---------------- Rules ----------------

export function useRules(seriesId?: number) {
  return useQuery({
    queryKey: qk.rules(seriesId),
    queryFn: () => api<ListResponse<Rule>>('/api/rules', { query: { series_id: seriesId } }),
  });
}

export function useSaveRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id?: number; body: RuleIn }) =>
      id === undefined
        ? api<Rule>('/api/rules', { method: 'POST', body })
        : api<Rule>(`/api/rules/${id}`, { method: 'PUT', body }),
    onSuccess: () => invalidateSeries(qc),
  });
}

export function useDeleteRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>(`/api/rules/${id}`, { method: 'DELETE' }),
    onSuccess: () => invalidateSeries(qc),
  });
}

export function useSimulateRule() {
  return useMutation({
    mutationFn: (body: SimulateIn) =>
      api<ItemsResponse<SimulationResult>>('/api/rules/simulate', { method: 'POST', body }),
  });
}

export function useTestRecent() {
  return useMutation({
    mutationFn: ({ id, limit = 100 }: { id: number; limit?: number }) =>
      api<ItemsResponse<TestRecentResult>>(`/api/rules/${id}/test-recent`, { method: 'POST', query: { limit } }),
  });
}

export function validateRegex(pattern: string) {
  return api<RegexValidation>('/api/rules/validate-regex', { method: 'POST', body: { pattern } });
}

// ---------------- Entries ----------------

export type EntryFilters = {
  feed_id?: number;
  outcome?: EntryOutcome;
  q?: string;
  limit: number;
  offset: number;
};

export function useEntries(f: EntryFilters) {
  return useQuery({
    queryKey: qk.entries(f),
    queryFn: () => api<ListResponse<FeedEntry>>('/api/entries', { query: f }),
    placeholderData: keepPreviousData,
  });
}

export function fetchEntries(f: EntryFilters) {
  return api<ListResponse<FeedEntry>>('/api/entries', { query: f });
}

export function useEntry(id: number) {
  return useQuery({
    queryKey: qk.entry(id),
    queryFn: () => api<FeedEntryDetail>(`/api/entries/${id}`),
    enabled: Number.isFinite(id),
  });
}

export function useEvaluateEntry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<FeedEntryDetail>(`/api/entries/${id}/evaluate`, { method: 'POST' }),
    onSuccess: (data) => qc.setQueryData(qk.entry(data.id), data),
  });
}

export function useGrabPreview() {
  return useMutation({
    mutationFn: ({ entryId, body }: { entryId: number; body: Omit<GrabIn, 'confirm'> }) =>
      api<GrabPreview>(`/api/entries/${entryId}/grab`, { method: 'POST', body: { ...body, confirm: false } }),
  });
}

export function useGrabConfirm() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ entryId, body }: { entryId: number; body: Omit<GrabIn, 'confirm'> }) =>
      api<Download>(`/api/entries/${entryId}/grab`, { method: 'POST', body: { ...body, confirm: true } }),
    onSuccess: (_d, vars) => {
      void qc.invalidateQueries({ queryKey: qk.entry(vars.entryId) });
      void qc.invalidateQueries({ queryKey: ['downloads'] });
      void qc.invalidateQueries({ queryKey: qk.dashboard });
    },
  });
}

// ---------------- Downloads ----------------

export type DownloadFilters = {
  status?: DownloadStatus;
  series_id?: number;
  limit: number;
  offset: number;
};

export function useDownloads(f: DownloadFilters) {
  return useQuery({
    queryKey: qk.downloads(f),
    queryFn: () => api<ListResponse<Download>>('/api/downloads', { query: f }),
    refetchInterval: 15_000,
    placeholderData: keepPreviousData,
  });
}

function invalidateDownloads(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: ['downloads'] });
  void qc.invalidateQueries({ queryKey: qk.dashboard });
}

export function useRetryDownload() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<Download>(`/api/downloads/${id}/retry`, { method: 'POST' }),
    onSettled: () => invalidateDownloads(qc),
  });
}

export function useRetryFailed() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ retried: number }>('/api/downloads/retry-failed', { method: 'POST' }),
    onSettled: () => invalidateDownloads(qc),
  });
}

export function useRefreshStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ updated: number }>('/api/downloads/refresh-status', { method: 'POST' }),
    onSettled: () => invalidateDownloads(qc),
  });
}

// ---------------- qBittorrent ----------------

export function useQbit() {
  return useQuery({ queryKey: qk.qbit, queryFn: () => api<QbitConfig>('/api/qbit') });
}

export function useSaveQbit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: QbitConfigIn) => api<QbitConfig>('/api/qbit', { method: 'PUT', body }),
    onSuccess: (data) => {
      qc.setQueryData(qk.qbit, data);
      void qc.invalidateQueries({ queryKey: qk.dashboard });
    },
  });
}

export function useTestQbit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: QbitConfigIn | Record<string, never>) =>
      api<QbitTestResult>('/api/qbit/test', { method: 'POST', body }),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: qk.qbit });
      void qc.invalidateQueries({ queryKey: qk.dashboard });
    },
  });
}

// ---------------- Settings ----------------

export function useSettings() {
  return useQuery({ queryKey: qk.settings, queryFn: () => api<AppSettings>('/api/settings') });
}

export function useSaveSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: AppSettingsIn) => api<AppSettings>('/api/settings', { method: 'PUT', body }),
    onSuccess: (data) => {
      qc.setQueryData(qk.settings, data);
      void qc.invalidateQueries({ queryKey: qk.series });
    },
  });
}

// ---------------- Activity ----------------

export type ActivityFilters = {
  level?: string;
  event_type?: string;
  limit: number;
  offset: number;
};

export function useActivity(f: ActivityFilters) {
  return useQuery({
    queryKey: qk.activity(f),
    queryFn: () => api<ListResponse<ActivityEvent>>('/api/activity', { query: f }),
    placeholderData: keepPreviousData,
  });
}
