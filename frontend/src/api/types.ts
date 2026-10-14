// Mirrors .claude/rules/api-contract.md exactly. Do not diverge without updating the contract.

export type Condition = { check: string; passed: boolean; detail: string };

export type ParsedRelease = {
  group: string | null;
  title: string;
  season: number | null;
  episode: number | null;
  episode_end: number | null;
  absolute: boolean; // true when the number was given without an explicit season (e.g. "- 171")
  version: number | null;
  resolution: string | null;
  source: string | null;
  codec: string | null;
  audio: string | null;
  subs: string[];
  is_batch: boolean;
  raw: string;
};

export type FeedSource = {
  id: number;
  name: string;
  url: string;
  enabled: boolean;
  poll_interval_minutes: number;
  backfill_mode: 'skip' | 'process';
  /** Search feed URL with `{query}` exactly once (episodes.md); null = feed not used for release search. */
  search_url_template: string | null;
  last_checked_at: string | null;
  last_success_at: string | null;
  last_status: 'never' | 'ok' | 'error';
  last_error: string | null;
  consecutive_failures: number;
  initial_poll_done: boolean;
  entry_count: number;
  created_at: string;
};

// live, unpersisted
export type FeedEntryPreview = {
  guid: string;
  title: string;
  link: string | null;
  published_at: string | null;
  magnet_url: string | null;
  torrent_url: string | null;
  has_nzb: boolean;
  size_bytes: number | null;
  infohash: string | null;
  parsed: ParsedRelease;
};

export type EntryOutcome = 'unprocessed' | 'accepted' | 'rejected' | 'no_match' | 'historical' | 'duplicate' | 'searched';

export type FeedEntry = FeedEntryPreview & {
  id: number;
  feed_id: number;
  feed_name: string;
  first_seen_at: string;
  is_historical: boolean;
  processed_at: string | null;
  outcome: EntryOutcome;
  outcome_summary: string | null;
};

export type Evaluation = {
  rule_id: number;
  rule_name: string;
  series_id: number;
  series_name: string;
  season_id: number | null;
  season_number: number | null;
  episode_number: number | null;
  matched: boolean;
  conditions: Condition[];
  evaluated_at: string;
};

export type FeedEntryDetail = FeedEntry & { evaluations: Evaluation[]; downloads: Download[] };

export type Season = {
  id: number;
  series_id: number;
  season_number: number;
  monitored: boolean;
  path_override: string | null;
  episode_min: number | null;
  episode_max: number | null;
  absolute_min: number | null;
  absolute_max: number | null;
  /** tmdb: the TV id (season number is the season's own); anilist: the AniList media id of this entry. */
  metadata_provider: MetadataProviderName | null;
  metadata_id: string | null;
  metadata_refreshed_at?: string | null;
  computed_save_path: string;
  created_at: string;
  // computed (episodes.md)
  episode_count: number;
  downloaded_count: number;
  missing_count: number;
  /** best-effort metadata refresh problems after a PUT */
  warnings?: string[];
};

export type SeasonIn = Omit<
  Season,
  | 'id'
  | 'series_id'
  | 'computed_save_path'
  | 'created_at'
  | 'metadata_refreshed_at'
  | 'episode_count'
  | 'downloaded_count'
  | 'missing_count'
  | 'warnings'
>;

export type Series = {
  id: number;
  name: string;
  aliases: string[];
  monitored: boolean;
  season_folder_format: string;
  path_override: string | null;
  category_override: string | null;
  seasons: Season[];
  rule_count: number;
  metadata_provider: MetadataProviderName | null;
  metadata_id: string | null;
  cover_url: string | null;
  metadata: MetadataInfo | null;
  created_at: string;
};

export type SeriesIn = {
  name: string;
  aliases: string[];
  monitored: boolean;
  season_folder_format?: string;
  path_override?: string | null;
  category_override?: string | null;
  seasons?: SeasonIn[]; // seasons only honored on POST
  metadata_provider?: MetadataProviderName | null;
  metadata_id?: string | null;
  cover_url?: string | null;
  metadata?: MetadataInfo | null;
};

export type Rule = {
  id: number;
  series_id: number;
  season_id: number | null;
  name: string;
  enabled: boolean;
  priority: number;
  release_group: string | null;
  require_group_prefix: boolean;
  include_keywords: string[];
  exclude_keywords: string[];
  resolutions: string[];
  sources: string[];
  codecs: string[];
  language_keywords: string[];
  min_size_mb: number | null;
  max_size_mb: number | null;
  regex: string | null;
  series_name: string;
  season_number: number | null;
  created_at: string;
};

export type RuleIn = Omit<Rule, 'id' | 'series_name' | 'season_number' | 'created_at'>;

export type SimulationResult = {
  title: string;
  parsed: ParsedRelease;
  matched: boolean;
  season_number: number | null;
  episode_number: number | null;
  save_path: string | null;
  conditions: Condition[];
};

export type DownloadStatus = 'pending' | 'submitted' | 'failed' | 'exists' | 'path_mismatch';

export type Download = {
  id: number;
  entry_id: number;
  entry_title: string;
  series_id: number;
  series_name: string;
  season_id: number;
  season_number: number;
  episode_number: number;
  rule_id: number | null;
  rule_name: string | null;
  infohash: string | null;
  source_url: string;
  source_url_kind: 'magnet' | 'torrent';
  save_path: string;
  category: string | null;
  status: DownloadStatus;
  attempts: number;
  next_retry_at: string | null;
  last_error: string | null;
  qbit_hash: string | null;
  qbit_state: string | null;
  qbit_progress: number | null;
  qbit_save_path: string | null;
  forced: boolean;
  created_at: string;
  updated_at: string;
};

export type GrabPreview = {
  entry_id: number;
  season_id: number;
  episode_number: number;
  save_path: string;
  category: string | null;
  source_url: string;
  source_url_kind: 'magnet' | 'torrent';
  infohash: string | null;
  duplicate_of: Download | null;
  warnings: string[];
};

export type ActivityLevel = 'info' | 'warning' | 'error';

export type ActivityEvent = {
  id: number;
  ts: string;
  level: ActivityLevel;
  event_type: string;
  message: string;
  details: Record<string, unknown> | null;
  entry_id: number | null;
  download_id: number | null;
};

export type QbitTestResult = {
  ok: boolean;
  at: string;
  version: string | null;
  api_version: string | null;
  auto_tmm_enabled: boolean | null;
  default_save_path: string | null;
  category_exists: boolean | null;
  warnings: string[];
  error: string | null;
};

export type ConfigSource = 'env' | 'db';

export type QbitConfig = {
  url: string;
  username: string;
  password_set: boolean;
  category: string | null;
  timeout_seconds: number;
  start_immediately: boolean;
  poll_status: boolean;
  sources: Record<string, ConfigSource>;
  last_test: QbitTestResult | null;
};

export type QbitConfigIn = {
  url: string;
  username: string;
  password?: string; // omitted/undefined = unchanged; "" = clear
  category: string | null;
  timeout_seconds: number;
  start_immediately: boolean;
  poll_status: boolean;
};

export type DuplicatePolicy = 'one_per_episode' | 'allow_upgrades';

export type AppSettings = {
  media_base_path: string;
  default_season_folder_format: string;
  duplicate_policy: DuplicatePolicy;
  allow_private_feed_hosts: boolean;
  feed_fetch_timeout_seconds: number;
  log_retention_days: number;
  auto_search_missing: boolean;
  search_interval_hours: number;
  metadata_refresh_hours: number;
  search_delay_seconds: number;
  tmdb_api_key_set: boolean;
  sources: Record<string, ConfigSource>;
  warnings?: string[];
};

/** PUT /api/settings. `tmdb_api_key` omitted = unchanged; "" = clear. */
export type AppSettingsIn = Omit<AppSettings, 'sources' | 'warnings' | 'tmdb_api_key_set'> & { tmdb_api_key?: string };

export type AuthStatus = { auth_mode: 'password' | 'disabled'; setup_required: boolean; authenticated: boolean };

export type Dashboard = {
  feeds: FeedSource[];
  counts: {
    series_total: number;
    series_monitored: number;
    rules_active: number;
    entries_24h: number;
    downloads_submitted_24h: number;
    downloads_pending: number;
    downloads_failed: number;
    wanted: number;
  };
  upcoming: CalendarItem[]; // next 7 days, max 10, monitored only
  recent_downloads: Download[]; // last 10 any status
  failed_downloads: Download[]; // last 10 failed/path_mismatch
  recent_entries: FeedEntry[]; // last 10
  qbit: { configured: boolean; last_test: QbitTestResult | null };
  scheduler: { running: boolean; next_feed_poll_at: string | null };
};

// ---- Endpoint request/response shapes defined inline in the contract, named here ----

export type ListResponse<T> = { items: T[]; total: number };
export type ItemsResponse<T> = { items: T[] };

export type FeedIn = {
  name: string;
  url: string;
  enabled: boolean;
  poll_interval_minutes: number;
  backfill_mode: 'skip' | 'process';
  search_url_template: string | null;
};

export type FeedTestResult = {
  ok: boolean;
  feed_title: string | null;
  entry_count: number;
  sample: FeedEntryPreview[];
  error: string | null;
};

export type PollResult = {
  fetched: number;
  new_entries: number;
  historical: number;
  accepted: number;
  duplicate: number;
  rejected: number;
  no_match: number;
  submitted: number;
  errors: string[];
};

export type SeasonPath = { season_id: number; season_number: number; save_path: string };

export type PreviewPathIn = {
  name: string;
  season_folder_format: string;
  path_override: string | null;
  season_number: number;
  season_path_override: string | null;
};

export type GrabIn = { season_id: number; episode_number: number; force: boolean; confirm: boolean };

/** POST /api/rules/simulate. With `series` (unsaved, incl. seasons) the backend works in-memory:
 *  rule.series_id is ignored (send 0) and rule.season_id is a 0-based index into series.seasons, or null. */
export type SimulateIn = { rule: RuleIn; titles: string[]; series?: SeriesIn };

export type TestRecentResult = SimulationResult & { entry_id: number };

export type RegexValidation = { valid: boolean; error: string | null };

export type Health = { status: 'ok'; db: 'ok'; scheduler: 'running' | 'stopped'; version: string };

// ---- Metadata providers (.claude/rules/metadata.md) ----

export type MetadataProviderName = 'anilist' | 'tmdb';
export type MediaKind = 'anime' | 'tv';

export type MetadataProvider = { name: MetadataProviderName; label: string; kind: MediaKind; configured: boolean };

/** Stored on the series as `metadata` (backend column `metadata_json`). */
export type MetadataInfo = {
  provider: MetadataProviderName | null;
  id: string | null;
  title: string | null;
  original_title: string | null;
  alt_titles: string[];
  kind: MediaKind | null;
  format: string | null;
  status: string | null;
  year: number | null;
  episodes: number | null;
  site_url: string | null;
};

export type MediaResult = {
  provider: MetadataProviderName;
  id: string;
  title: string | null;
  original_title: string | null;
  alt_titles: string[];
  kind: MediaKind;
  format: string | null;
  status: string | null;
  year: number | null;
  episodes: number | null;
  cover_url: string | null;
  site_url: string | null;
};

export type SeasonInfo = { season_number: number; name: string | null; episode_count: number | null; air_date: string | null };

export type RelatedInfo = {
  relation_type: string;
  provider: MetadataProviderName;
  id: string;
  title: string | null;
  format: string | null;
  episodes: number | null;
  year: number | null;
  status: string | null;
  suggested_season_number: number | null;
};

export type MediaDetail = MediaResult & { seasons: SeasonInfo[]; related: RelatedInfo[] };

/** Suggestion seasons are SeasonIn-like; monitored/path_override may be missing. */
export type SuggestionSeason = Partial<SeasonIn> & { season_number: number };

export type Suggestion = {
  provider: MetadataProviderName;
  id: string;
  name: string;
  aliases: string[];
  cover_url: string | null;
  metadata: MetadataInfo;
  seasons: SuggestionSeason[];
  related: RelatedInfo[];
};

export type LinkMetadataIn = { provider: MetadataProviderName | null; id: string | null };

// ---- Episodes, release search, calendar, wanted (.claude/rules/episodes.md) ----

export type EpisodeStatus = 'downloaded' | 'downloading' | 'pending' | 'missing' | 'unaired' | 'unknown';

export type Episode = {
  id: number;
  season_id: number;
  episode_number: number;
  title: string | null;
  air_date: string | null;
  source: 'anilist' | 'tmdb' | 'jikan' | 'manual';
  status: EpisodeStatus;
  download: Download | null;
};

export type EpisodeSummary = { episode_count: number; downloaded_count: number; missing_count: number; unaired_count: number };

export type EpisodesResponse = { items: Episode[]; summary: EpisodeSummary };

export type EpisodeIn = { title?: string | null; air_date?: string | null };

export type Candidate = {
  entry: FeedEntry;
  episode_number: number;
  rule_id: number;
  rule_name: string;
  conditions: Condition[];
  save_path: string | null;
  episode_status: EpisodeStatus;
  already_have: boolean;
};

export type SearchResult = {
  queries: string[];
  /** names of the feeds that were searched */
  feeds_searched: string[];
  fetched: number;
  candidates: Candidate[];
  errors: string[];
};

export type SearchIn = { query?: string };

export type GrabMissingResult = { grabbed: Download[]; skipped: { episode_number: number; reason: string }[]; errors?: string[] };

export type CalendarItem = {
  series_id: number;
  series_name: string;
  cover_url: string | null;
  season_id: number;
  season_number: number;
  episode_number: number;
  title: string | null;
  air_date: string;
  status: EpisodeStatus;
  monitored: boolean;
};

export type SearchAllSeason = {
  season_id: number;
  series_name: string;
  season_number: number;
  grabbed: number;
  skipped: number;
  errors: string[];
};

export type SearchAllResult = { seasons: SearchAllSeason[] };
