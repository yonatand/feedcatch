import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { errorMessage } from '../api/client';
import {
  fetchAnilistSuggest,
  fetchEntries,
  fetchFeedPreview,
  useCreateSeries,
  useFeeds,
  useSaveRule,
  useSettings,
  useSimulateRule,
  useUpdateSeries,
} from '../api/hooks';
import type { AnilistMedia, AnilistRelated, AnilistSuggestion, RuleIn, SeasonIn, Series, SeriesIn, SimulationResult } from '../api/types';
import { AnilistSearch } from '../components/AnilistSearch';
import { Cover } from '../components/Cover';
import { ErrorBanner, Notice } from '../components/ErrorBanner';
import { CheckField, FormField } from '../components/FormField';
import { ListInput } from '../components/ListInput';
import { PathPreview } from '../components/PathPreview';
import { RuleFields, cleanRule, emptyRule } from '../components/RuleForm';
import { SeasonFields, usePathPreview } from '../components/SeasonFields';
import { SimulationTable } from '../components/SimulationTable';
import { Spinner } from '../components/Spinner';
import { Badge } from '../components/StatusBadge';
import { Card, PageHeader } from '../components/Table';
import { anilistStatus, anilistTitle, metaLine, relationLabel, safeUrl } from '../lib/anilist';
import { emptySeason, rangeText } from '../lib/series';

type LocalSeason = { key: number; data: SeasonIn };

const STEPS = ['Series', 'Seasons', 'Rule & test', 'Review'];

let keySeq = 1;
const nextKey = () => keySeq++;

function cleanSeason(s: SeasonIn): SeasonIn {
  const po = s.path_override?.trim() ?? '';
  return { ...s, path_override: po === '' ? null : po };
}

/** Suggestion seasons may come without monitored/path_override; fill the wizard defaults. */
function seasonFromSuggestion(s: SeasonIn): SeasonIn {
  const base = emptySeason(s.season_number ?? 1);
  return {
    ...base,
    monitored: s.monitored ?? base.monitored,
    path_override: s.path_override ?? null,
    episode_min: s.episode_min ?? null,
    episode_max: s.episode_max ?? null,
    absolute_min: s.absolute_min ?? null,
    absolute_max: s.absolute_max ?? null,
  };
}

function AnilistLink({ url }: { url: string | null | undefined }) {
  const href = safeUrl(url);
  if (!href) return null;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      View on AniList
    </a>
  );
}

function RelatedList({ related, added, onAdd }: { related: AnilistRelated[]; added: ReadonlySet<number>; onAdd: (r: AnilistRelated) => void }) {
  return (
    <div className="subcard">
      <div className="subcard-head">
        <strong>Related on AniList</strong>
      </div>
      <p className="small muted">
        Sequels, prequels and other entries AniList links to this one. Release groups often number a sequel as the next season; adding one appends a season
        with its episode count as the range. Check the numbering against real release titles in step 3.
      </p>
      <ul className="related-list">
        {related.map((r) => {
          const title = anilistTitle(r);
          const st = anilistStatus(r.status);
          const isAdded = added.has(r.id);
          return (
            <li key={`${r.relation_type}-${r.id}`} className="related-row">
              <div className="anilist-row-main">
                <Badge tone="purple">{relationLabel(r.relation_type)}</Badge> <strong>{title}</strong>
                <div className="small muted">
                  {metaLine(r)} <Badge tone={st.tone}>{st.label}</Badge>
                  {r.suggested_season_number !== null ? ` · suggested season ${r.suggested_season_number}` : ''}
                </div>
              </div>
              <button type="button" className="btn btn-sm" disabled={isAdded} aria-label={`Add ${title} as season`} onClick={() => onAdd(r)}>
                {isAdded ? 'Added' : 'Add as season'}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function SeasonPathRow({ series, season }: { series: SeriesIn; season: SeasonIn }) {
  const p = usePathPreview({
    name: series.name,
    season_folder_format: series.season_folder_format ?? 'Season {season:02d}',
    path_override: series.path_override ?? null,
    season_number: season.season_number,
    season_path_override: season.path_override,
  });
  return (
    <div>
      <div className="small">
        Season {season.season_number} · episodes {rangeText(season.episode_min, season.episode_max)} · absolute{' '}
        {rangeText(season.absolute_min, season.absolute_max)}
        {season.monitored ? '' : ' · season unmonitored'}
      </div>
      <PathPreview path={p.path} loading={p.loading} error={p.error} label={`Season ${season.season_number}`} />
    </div>
  );
}

export default function SeriesNew() {
  const nav = useNavigate();
  const settings = useSettings();
  const feeds = useFeeds();
  const createSeries = useCreateSeries();
  const updateSeries = useUpdateSeries();
  const saveRule = useSaveRule();
  const simulate = useSimulateRule();

  const [step, setStep] = useState(0);
  const [series, setSeries] = useState<SeriesIn>({
    name: '',
    aliases: [],
    monitored: false,
    season_folder_format: 'Season {season:02d}',
    path_override: null,
    category_override: null,
  });
  const [formatTouched, setFormatTouched] = useState(false);
  const [seasons, setSeasons] = useState<LocalSeason[]>([{ key: nextKey(), data: emptySeason(1) }]);
  // Rule fields; season binding is tracked by local season key (indices shift when seasons are removed).
  const [rule, setRule] = useState<RuleIn>(emptyRule(0));
  const [ruleSeasonKey, setRuleSeasonKey] = useState<number | null>(null);
  const [monitored, setMonitored] = useState(false);
  const [testFeedId, setTestFeedId] = useState<number | null>(null);
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<SimulationResult[] | null>(null);
  const [testSource, setTestSource] = useState('');
  const [created, setCreated] = useState<Series | null>(null);
  const [finishing, setFinishing] = useState(false);
  const [finishError, setFinishError] = useState<unknown>(null);
  // AniList: the applied suggestion, the id being fetched, and whether the user edited seasons by hand.
  const [suggestion, setSuggestion] = useState<AnilistSuggestion | null>(null);
  const [suggestPending, setSuggestPending] = useState<number | null>(null);
  const [suggestError, setSuggestError] = useState<string | null>(null);
  const [seasonsTouched, setSeasonsTouched] = useState(false);
  const [addedRelated, setAddedRelated] = useState<ReadonlySet<number>>(new Set<number>());

  // Default the season folder format from settings until the user edits it.
  useEffect(() => {
    if (settings.data && !formatTouched) {
      setSeries((s) => ({ ...s, season_folder_format: settings.data.default_season_folder_format }));
    }
  }, [settings.data, formatTouched]);

  // Drop a season binding whose season was removed.
  useEffect(() => {
    if (ruleSeasonKey !== null && !seasons.some((s) => s.key === ruleSeasonKey)) setRuleSeasonKey(null);
  }, [seasons, ruleSeasonKey]);

  const setS = <K extends keyof SeriesIn>(k: K, v: SeriesIn[K]) => setSeries((s) => ({ ...s, [k]: v }));

  const editSeasons = (fn: (p: LocalSeason[]) => LocalSeason[]) => {
    setSeasonsTouched(true);
    setSeasons(fn);
  };

  const pickAnilist = async (m: AnilistMedia) => {
    setSuggestPending(m.id);
    setSuggestError(null);
    try {
      const sug = await fetchAnilistSuggest(m.id);
      setSuggestion(sug);
      setAddedRelated(new Set<number>());
      setSeries((s) => ({
        ...s,
        name: sug.name,
        aliases: [...sug.aliases],
        anilist_id: m.id,
        cover_url: sug.cover_url,
        anilist: sug.anilist,
      }));
      if (!seasonsTouched && sug.seasons.length > 0) {
        setSeasons(sug.seasons.map((x) => ({ key: nextKey(), data: seasonFromSuggestion(x) })));
      }
    } catch (e: unknown) {
      setSuggestError(errorMessage(e));
    } finally {
      setSuggestPending(null);
    }
  };

  const clearAnilist = () => {
    setSuggestion(null);
    setSuggestError(null);
    setAddedRelated(new Set<number>());
    setSeries((s) => ({ ...s, anilist_id: null, cover_url: null, anilist: null }));
    if (!seasonsTouched) setSeasons([{ key: nextKey(), data: emptySeason(1) }]);
  };

  const addRelatedSeason = (r: AnilistRelated) => {
    editSeasons((p) => {
      const n = Math.max(0, ...p.map((x) => x.data.season_number)) + 1;
      return [...p, { key: nextKey(), data: { ...emptySeason(n), episode_max: r.episodes } }];
    });
    setAddedRelated((prev) => new Set(prev).add(r.id));
  };

  const linked = series.anilist ?? null;

  const seasonNumbers = seasons.map((s) => s.data.season_number);
  const dupSeason = seasonNumbers.some((n, i) => seasonNumbers.indexOf(n) !== i);
  const ruleSeasonIndex = ruleSeasonKey === null ? null : seasons.findIndex((s) => s.key === ruleSeasonKey);
  const ruleSeasonLocal = ruleSeasonIndex !== null && ruleSeasonIndex >= 0 ? seasons[ruleSeasonIndex] : null;

  const seriesBody = (): SeriesIn => ({
    name: series.name.trim(),
    aliases: series.aliases,
    monitored: false,
    season_folder_format: series.season_folder_format?.trim() || 'Season {season:02d}',
    path_override: series.path_override?.trim() ? series.path_override.trim() : null,
    category_override: series.category_override?.trim() ? series.category_override.trim() : null,
    seasons: seasons.map((s) => cleanSeason(s.data)),
    anilist_id: series.anilist_id ?? null,
    cover_url: series.cover_url ?? null,
    anilist: series.anilist ?? null,
  });

  /** Rule as sent to /api/rules/simulate with an inline series: series_id 0, season_id = index into series.seasons. */
  const simRule = (): RuleIn => cleanRule({ ...rule, series_id: 0, season_id: ruleSeasonIndex !== null && ruleSeasonIndex >= 0 ? ruleSeasonIndex : null });

  const runTest = async () => {
    setTesting(true);
    setTestError(null);
    setTestResults(null);
    try {
      const titles: string[] = [];
      const sources: string[] = [];
      const stored = await fetchEntries({ limit: 100, offset: 0 });
      titles.push(...stored.items.map((e) => e.title));
      sources.push(`${stored.items.length} stored releases`);
      if (testFeedId !== null) {
        try {
          const live = await fetchFeedPreview(testFeedId, 100);
          titles.push(...live.items.map((e) => e.title));
          sources.push(`${live.items.length} live feed items`);
        } catch (e: unknown) {
          sources.push(`live preview failed: ${errorMessage(e)}`);
        }
      }
      const unique = Array.from(new Set(titles));
      setTestSource(`${sources.join(' + ')} (${unique.length} unique titles)`);
      if (unique.length === 0) {
        setTestResults([]);
        return;
      }
      const res = await simulate.mutateAsync({ rule: simRule(), titles: unique, series: seriesBody() });
      setTestResults(res.items);
    } catch (e: unknown) {
      setTestError(errorMessage(e));
    } finally {
      setTesting(false);
    }
  };

  const finish = async () => {
    setFinishing(true);
    setFinishError(null);
    try {
      // 1. Series + seasons (unmonitored first, so nothing can be grabbed before the rule exists).
      const s = created ?? (await createSeries.mutateAsync(seriesBody()));
      setCreated(s);
      // 2. Rule, mapping the chosen local season to the real season id by season number.
      let seasonId: number | null = null;
      if (ruleSeasonLocal) {
        const match = s.seasons.find((x) => x.season_number === ruleSeasonLocal.data.season_number);
        if (!match) throw new Error(`Season ${ruleSeasonLocal.data.season_number} was not returned by the server`);
        seasonId = match.id;
      }
      await saveRule.mutateAsync({ body: cleanRule({ ...rule, series_id: s.id, season_id: seasonId }) });
      // 3. Monitoring per the toggle.
      if (monitored) {
        const { seasons: _omit, ...body } = seriesBody();
        void _omit;
        await updateSeries.mutateAsync({ id: s.id, body: { ...body, monitored: true } });
      }
      nav(`/series/${s.id}`);
    } catch (e: unknown) {
      setFinishError(e);
    } finally {
      setFinishing(false);
    }
  };

  const step1Valid = series.name.trim() !== '';
  const step2Valid = seasons.length > 0 && !dupSeason;
  const seasonChoices = seasons.map((s, i) => ({ id: i, season_number: s.data.season_number, monitored: s.data.monitored }));
  const editLocked = created !== null;

  return (
    <>
      <PageHeader
        title="New series"
        subtitle="Define the series, its seasons and a matching rule, test it against recent releases, then decide whether to monitor it. Nothing is saved until the last step."
        actions={<Link to="/series">Back to series</Link>}
      />
      <ol className="stepper" aria-label="Wizard steps">
        {STEPS.map((s, i) => (
          <li key={s} className={i === step ? 'current' : i < step ? 'done' : ''} aria-current={i === step ? 'step' : undefined}>
            <span className="step-num">{i + 1}</span> {s}
          </li>
        ))}
      </ol>

      {step === 0 ? (
        <Card title="1. Series">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (step1Valid) setStep(1);
            }}
          >
            <div className="anilist-pick">
              <AnilistSearch onPick={(m) => void pickAnilist(m)} pendingId={suggestPending} selectedId={series.anilist_id ?? null} autoFocus />
              <ErrorBanner error={suggestError} title="Could not load AniList details" onDismiss={() => setSuggestError(null)} />
              {linked ? (
                <div className="anilist-selected">
                  <Cover url={series.cover_url} alt={series.name.trim() || anilistTitle(linked)} size="sm" />
                  <div className="anilist-row-main">
                    <div>
                      Using AniList: <strong>{anilistTitle(linked)}</strong>
                    </div>
                    <div className="small muted">{metaLine(linked)}</div>
                    <div className="small">
                      <AnilistLink url={linked.site_url} />
                      {safeUrl(linked.site_url) ? ' · ' : null}
                      <button type="button" className="link-btn" onClick={clearAnilist}>
                        Clear AniList selection
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
                <p className="small muted">Optional. Picking a result prefills the fields below; they stay editable.</p>
              )}
            </div>
            <div className="form-grid">
              <FormField label="Name" help="Canonical name; used as the folder name under the media base path.">
                {(id) => (
                  <input id={id} type="text" required value={series.name} onChange={(e) => setS('name', e.target.value)} placeholder="Black Clover" />
                )}
              </FormField>
              <FormField label="Aliases" help="Comma-separated title variants to match, e.g. Black.Clover, Black_Clover.">
                {(id) => <ListInput id={id} value={series.aliases} onChange={(v) => setS('aliases', v)} />}
              </FormField>
              <FormField
                label="Season folder format"
                help={
                  <>
                    Tokens: <code>{'{season}'}</code>, <code>{'{season:02d}'}</code>, <code>{'{season:03d}'}</code>, <code>{'{series}'}</code>.
                  </>
                }
              >
                {(id) => (
                  <input
                    id={id}
                    type="text"
                    className="mono"
                    value={series.season_folder_format ?? ''}
                    onChange={(e) => {
                      setFormatTouched(true);
                      setS('season_folder_format', e.target.value);
                    }}
                  />
                )}
              </FormField>
              <FormField label="Category override" help="Optional qBittorrent category for this series.">
                {(id) => (
                  <input id={id} type="text" value={series.category_override ?? ''} onChange={(e) => setS('category_override', e.target.value === '' ? null : e.target.value)} />
                )}
              </FormField>
              <FormField
                label="Series path override"
                help="Optional absolute path (as seen by qBittorrent) replacing “media base / series name”. Season folders go inside it."
                className="span-2"
              >
                {(id) => (
                  <input
                    id={id}
                    type="text"
                    className="mono"
                    value={series.path_override ?? ''}
                    onChange={(e) => setS('path_override', e.target.value === '' ? null : e.target.value)}
                  />
                )}
              </FormField>
            </div>
            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={!step1Valid}>
                Next: seasons
              </button>
            </div>
          </form>
        </Card>
      ) : null}

      {step === 1 ? (
        <Card title="2. Seasons">
          {suggestion && linked && !seasonsTouched ? (
            <Notice kind="info">Seasons prefilled from AniList. Adjust the ranges to how release groups number this show.</Notice>
          ) : null}
          <p className="small muted">
            Define each season you want. Releases are only accepted when the season is explicit in the title (e.g. S02E05, “Season 2 - 05”) or an absolute
            episode range below maps a seasonless number (e.g. “- 171”) to the season. Nothing is guessed.
          </p>
          {seasons.map((ls, i) => (
            <div key={ls.key} className="subcard">
              <div className="subcard-head">
                <strong>Season {ls.data.season_number}</strong>
                {seasons.length > 1 ? (
                  <button type="button" className="btn btn-sm btn-ghost" onClick={() => editSeasons((p) => p.filter((x) => x.key !== ls.key))}>
                    Remove
                  </button>
                ) : null}
              </div>
              <SeasonFields
                value={ls.data}
                onChange={(d) => editSeasons((p) => p.map((x, j) => (j === i ? { ...x, data: d } : x)))}
                seriesName={series.name}
                seasonFolderFormat={series.season_folder_format ?? 'Season {season:02d}'}
                seriesPathOverride={series.path_override ?? null}
              />
            </div>
          ))}
          {dupSeason ? <ErrorBanner error="Two seasons have the same number." /> : null}
          <button
            type="button"
            className="btn"
            onClick={() => editSeasons((p) => [...p, { key: nextKey(), data: emptySeason(Math.max(0, ...p.map((x) => x.data.season_number)) + 1) }])}
          >
            Add season
          </button>
          {suggestion && linked && suggestion.related.length > 0 ? (
            <RelatedList related={suggestion.related} added={addedRelated} onAdd={addRelatedSeason} />
          ) : null}
          <div className="form-actions">
            <button type="button" className="btn btn-ghost" onClick={() => setStep(0)}>
              Back
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={!step2Valid}
              onClick={() => {
                if (rule.name.trim() === '') setRule((r) => ({ ...r, name: `${series.name.trim()} rule` }));
                if (ruleSeasonKey === null && seasons.length === 1) setRuleSeasonKey(seasons[0].key);
                setStep(2);
              }}
            >
              Next: rule
            </button>
          </div>
        </Card>
      ) : null}

      {step === 2 ? (
        <>
          <Card title="3. Matching rule">
            <RuleFields
              value={{ ...rule, season_id: ruleSeasonIndex !== null && ruleSeasonIndex >= 0 ? ruleSeasonIndex : null }}
              onChange={(r) => {
                setRuleSeasonKey(r.season_id === null ? null : (seasons[r.season_id]?.key ?? null));
                setRule({ ...r, season_id: null });
              }}
              seasons={seasonChoices}
              hideSeries
            />
          </Card>
          <Card title="Test against recent releases">
            <p className="small muted">
              Runs this unsaved rule and series against up to 100 stored releases, plus optionally a live fetch of a feed. Nothing is saved or sent.
            </p>
            <div className="inline-form">
              <label htmlFor="wiz-feed" className="small">
                Also include live feed:
              </label>
              <select id="wiz-feed" value={testFeedId ?? ''} onChange={(e) => setTestFeedId(e.target.value === '' ? null : Number(e.target.value))}>
                <option value="">None (stored releases only)</option>
                {(feeds.data?.items ?? []).map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </select>
              <button type="button" className="btn btn-primary" disabled={testing || rule.name.trim() === ''} onClick={() => void runTest()}>
                {testing ? 'Testing…' : 'Test against recent releases'}
              </button>
            </div>
            {testing ? <Spinner label="Fetching titles and simulating…" /> : null}
            <ErrorBanner error={testError} title="Test failed" />
            {testSource && !testing ? <div className="small muted">Source: {testSource}</div> : null}
            {testResults ? (
              testResults.length === 0 ? (
                <Notice kind="info">No titles available yet. Add a feed and poll it, or pick a live feed above.</Notice>
              ) : (
                <SimulationTable items={testResults} />
              )
            ) : null}
          </Card>
          <div className="form-actions">
            <button type="button" className="btn btn-ghost" onClick={() => setStep(1)}>
              Back
            </button>
            <button type="button" className="btn btn-primary" disabled={rule.name.trim() === ''} onClick={() => setStep(3)}>
              Next: review
            </button>
          </div>
        </>
      ) : null}

      {step === 3 ? (
        <Card title="4. Review">
          <div className="review-head">
            {linked ? <Cover url={series.cover_url} alt={series.name.trim()} size="lg" /> : null}
            <dl className="kv grow">
              <div className="kv-row">
                <dt>Series</dt>
                <dd>
                  <strong>{series.name.trim()}</strong>
                  {series.aliases.length ? <span className="muted"> (aliases: {series.aliases.join(', ')})</span> : null}
                </dd>
              </div>
              <div className="kv-row">
                <dt>Category</dt>
                <dd>{series.category_override?.trim() || <span className="muted">qBittorrent default from settings</span>}</dd>
              </div>
              <div className="kv-row">
                <dt>Rule</dt>
                <dd>
                  {rule.name}
                  {rule.release_group ? ` · group ${rule.release_group}${rule.require_group_prefix ? ` (requires [${rule.release_group}] prefix)` : ''}` : ''}
                  {rule.resolutions.length ? ` · ${rule.resolutions.join('/')}` : ''}
                  {rule.regex ? ' · regex' : ''}
                  {ruleSeasonLocal ? ` · season ${ruleSeasonLocal.data.season_number}` : ' · any season'}
                </dd>
              </div>
              {linked ? (
                <div className="kv-row">
                  <dt>AniList</dt>
                  <dd>
                    {anilistTitle(linked)} <span className="muted">({metaLine(linked)})</span>
                    {safeUrl(linked.site_url) ? ' · ' : null}
                    <AnilistLink url={linked.site_url} />
                  </dd>
                </div>
              ) : null}
            </dl>
          </div>
          <h3>Exact qBittorrent save paths</h3>
          <div className="stack">
            {[...seasons]
              .sort((a, b) => a.data.season_number - b.data.season_number)
              .map((s) => (
                <SeasonPathRow key={s.key} series={seriesBody()} season={cleanSeason(s.data)} />
              ))}
          </div>
          <p className="small muted">
            These strings are sent to qBittorrent as <code>savepath</code>. This app never creates, reads or modifies those folders.
          </p>
          <div className="monitor-toggle">
            <CheckField
              label={<strong>Monitor this series (enable automatic grabs)</strong>}
              checked={monitored}
              onChange={setMonitored}
              help="Off by default. Nothing is auto-grabbed until the series is monitored; you can still inspect matches and grab manually. Only releases arriving after this point are considered (historical entries are never auto-grabbed)."
            />
          </div>
          {created && finishError ? (
            <Notice kind="warning">
              Series “{created.name}” was created but a later step failed. Retrying will reuse it, or open it to finish manually:{' '}
              <Link to={`/series/${created.id}`}>{created.name}</Link>.
            </Notice>
          ) : null}
          <ErrorBanner error={finishError} title="Could not finish" />
          <div className="form-actions">
            <button type="button" className="btn btn-ghost" disabled={editLocked} onClick={() => setStep(2)}>
              Back
            </button>
            <button type="button" className="btn btn-primary" disabled={finishing} onClick={() => void finish()}>
              {finishing ? 'Creating…' : monitored ? 'Create series & start monitoring' : 'Create series (unmonitored)'}
            </button>
          </div>
        </Card>
      ) : null}
    </>
  );
}
