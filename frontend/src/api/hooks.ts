import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';
import type {
  ActivityEvent,
  AppSettings,
  AppSettingsIn,
  AuthStatus,
  BackfillSeasonLinksResult,
  CalendarItem,
  Dashboard,
  Download,
  DownloadStatus,
  EntryOutcome,
  Episode,
  EpisodeIn,
  EpisodesResponse,
  FeedEntry,
  FeedEntryDetail,
  FeedEntryPreview,
  FeedIn,
  FeedSource,
  FeedTestResult,
  GrabIn,
  GrabMissingResult,
  GrabPreview,
  ItemsResponse,
  LinkMetadataIn,
  ListResponse,
  MediaDetail,
  MediaResult,
  MetadataProvider,
  MetadataProviderName,
  PollResult,
  PreviewPathIn,
  QbitConfig,
  QbitConfigIn,
  QbitTestResult,
  RegexValidation,
  Rule,
  RuleIn,
  SearchAllResult,
  SearchIn,
  SearchResult,
  Season,
  SeasonIn,
  SeasonPath,
  Series,
  SeriesIn,
  SimulateIn,
  SimulationResult,
  Suggestion,
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
  metadataProviders: ['metadata', 'providers'] as const,
  metadataSearch: (provider: string, q: string) => ['metadata', 'search', provider, q] as const,
  metadataDetail: (provider: string, id: string) => ['metadata', 'detail', provider, id] as const,
  episodes: (seasonId: number) => ['episodes', seasonId] as const,
  calendar: (from: string, to: string) => ['calendar', from, to] as const,
  wanted: (limit: number, offset: number) => ['wanted', limit, offset] as const,
};

/** Everything derived from episodes/downloads: refresh after grabs, searches and metadata changes. */
function invalidateEpisodeViews(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: ['episodes'] });
  void qc.invalidateQueries({ queryKey: ['wanted'] });
  void qc.invalidateQueries({ queryKey: ['calendar'] });
  void qc.invalidateQueries({ queryKey: ['downloads'] });
  void qc.invalidateQueries({ queryKey: qk.series });
  void qc.invalidateQueries({ queryKey: qk.dashboard });
}

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
    onSuccess: (_d, vars) => {
      invalidateSeries(qc);
      void qc.invalidateQueries({ queryKey: qk.episodes(vars.id) });
    },
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
      invalidateEpisodeViews(qc);
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

/** DELETE /api/downloads/{id}: removes feedcatch's record only; the torrent stays in qBittorrent. */
export function useDeleteDownload() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<void>(`/api/downloads/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      invalidateEpisodeViews(qc);
      void qc.invalidateQueries({ queryKey: ['entry'] });
    },
  });
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
      void qc.invalidateQueries({ queryKey: qk.metadataProviders });
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

// ---------------- Metadata providers ----------------

export function useMetadataProviders() {
  return useQuery({
    queryKey: qk.metadataProviders,
    queryFn: () => api<ItemsResponse<MetadataProvider>>('/api/metadata/providers'),
    staleTime: 60_000,
  });
}

/** Server-cached too; a long staleTime keeps repeated keystrokes off the provider rate limits. */
export function useMetadataSearch(provider: MetadataProviderName | null, q: string, enabled: boolean) {
  const query = q.trim();
  return useQuery({
    queryKey: qk.metadataSearch(provider ?? '', query),
    queryFn: () =>
      api<ItemsResponse<MediaResult>>('/api/metadata/search', { query: { provider: provider ?? '', q: query, limit: 10 } }),
    enabled: enabled && provider !== null && query.length >= 2,
    staleTime: 10 * 60_000,
    retry: false,
    placeholderData: keepPreviousData,
  });
}

export function useMetadataDetail(provider: MetadataProviderName | null, id: string | null) {
  return useQuery({
    queryKey: qk.metadataDetail(provider ?? '', id ?? ''),
    queryFn: () => api<MediaDetail>(`/api/metadata/${provider ?? ''}/${encodeURIComponent(id ?? '')}`),
    enabled: provider !== null && id !== null && id !== '',
    staleTime: 30 * 60_000,
    retry: false,
  });
}

export function fetchMetadataSuggest(provider: MetadataProviderName, id: string) {
  return api<Suggestion>(`/api/metadata/${provider}/${encodeURIComponent(id)}/suggest`);
}

export function useLinkMetadata(seriesId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: LinkMetadataIn) => api<Series>(`/api/series/${seriesId}/metadata`, { method: 'PUT', body }),
    onSuccess: (data) => {
      qc.setQueryData(qk.seriesOne(data.id), data);
      invalidateSeries(qc);
      void qc.invalidateQueries({ queryKey: ['episodes'] });
    },
  });
}

/** POST /api/metadata/backfill-season-links: links unlinked seasons of linked series where it can. */
export function useBackfillSeasonLinks() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<BackfillSeasonLinksResult>('/api/metadata/backfill-season-links', { method: 'POST' }),
    onSuccess: () => {
      invalidateSeries(qc);
      invalidateEpisodeViews(qc);
    },
  });
}

// ---------------- Episodes ----------------

export function useEpisodes(seasonId: number) {
  return useQuery({
    queryKey: qk.episodes(seasonId),
    queryFn: () => api<EpisodesResponse>(`/api/seasons/${seasonId}/episodes`),
    refetchInterval: 60_000,
  });
}

export function useRefreshEpisodes() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (seasonId: number) => api<EpisodesResponse>(`/api/seasons/${seasonId}/episodes/refresh`, { method: 'POST' }),
    onSuccess: (data, seasonId) => {
      qc.setQueryData(qk.episodes(seasonId), data);
      invalidateEpisodeViews(qc);
    },
  });
}

export function useUpdateEpisode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ seasonId, number, body }: { seasonId: number; number: number; body: EpisodeIn }) =>
      api<Episode>(`/api/seasons/${seasonId}/episodes/${number}`, { method: 'PUT', body }),
    onSuccess: (_d, vars) => {
      void qc.invalidateQueries({ queryKey: qk.episodes(vars.seasonId) });
      void qc.invalidateQueries({ queryKey: ['calendar'] });
      void qc.invalidateQueries({ queryKey: ['wanted'] });
    },
  });
}

// ---------------- Release search ----------------

export function useSeasonSearch() {
  return useMutation({
    mutationFn: ({ seasonId, body }: { seasonId: number; body: SearchIn }) =>
      api<SearchResult>(`/api/seasons/${seasonId}/search`, { method: 'POST', body }),
  });
}

export function useGrabMissing() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ seasonId, body }: { seasonId: number; body: SearchIn }) =>
      api<GrabMissingResult>(`/api/seasons/${seasonId}/search/grab-missing`, { method: 'POST', body }),
    onSettled: () => invalidateEpisodeViews(qc),
  });
}

// ---------------- Calendar / wanted ----------------

export function useCalendar(from: string, to: string) {
  return useQuery({
    queryKey: qk.calendar(from, to),
    queryFn: () => api<ItemsResponse<CalendarItem>>('/api/calendar', { query: { from, to } }),
    placeholderData: keepPreviousData,
  });
}

export function useWanted(limit: number, offset: number) {
  return useQuery({
    queryKey: qk.wanted(limit, offset),
    queryFn: () => api<ListResponse<CalendarItem>>('/api/wanted', { query: { limit, offset } }),
    placeholderData: keepPreviousData,
  });
}

export function useSearchAllWanted() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<SearchAllResult>('/api/wanted/search-all', { method: 'POST' }),
    onSettled: () => invalidateEpisodeViews(qc),
  });
}
