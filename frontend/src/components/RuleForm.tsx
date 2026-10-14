import { useId, useState } from 'react';
import { errorMessage } from '../api/client';
import { useSaveRule, useSimulateRule, validateRegex } from '../api/hooks';
import type { Rule, RuleIn, Season, Series, SimulationResult } from '../api/types';
import { seasonEpisode } from '../lib/format';
import { ConditionsTable } from './ConditionsTable';
import { ErrorBanner } from './ErrorBanner';
import { CheckField, FormField } from './FormField';
import { ListInput } from './ListInput';
import { NumberInput } from './NumberInput';
import { ParsedBadges } from './ParsedBadges';
import { PathPreview } from './PathPreview';
import { StatusBadge } from './StatusBadge';

export function emptyRule(seriesId: number, seasonId: number | null = null): RuleIn {
  return {
    series_id: seriesId,
    season_id: seasonId,
    name: '',
    enabled: true,
    priority: 0,
    release_group: null,
    require_group_prefix: false,
    include_keywords: [],
    exclude_keywords: [],
    resolutions: [],
    sources: [],
    codecs: [],
    language_keywords: [],
    min_size_mb: null,
    max_size_mb: null,
    regex: null,
  };
}

export function ruleToIn(r: Rule): RuleIn {
  return {
    series_id: r.series_id,
    season_id: r.season_id,
    name: r.name,
    enabled: r.enabled,
    priority: r.priority,
    release_group: r.release_group,
    require_group_prefix: r.require_group_prefix,
    include_keywords: [...r.include_keywords],
    exclude_keywords: [...r.exclude_keywords],
    resolutions: [...r.resolutions],
    sources: [...r.sources],
    codecs: [...r.codecs],
    language_keywords: [...r.language_keywords],
    min_size_mb: r.min_size_mb,
    max_size_mb: r.max_size_mb,
    regex: r.regex,
  };
}

/** Trim strings / normalise empty to null before sending. */
export function cleanRule(r: RuleIn): RuleIn {
  const rg = r.release_group?.trim() ?? '';
  const rx = r.regex ?? '';
  return {
    ...r,
    name: r.name.trim(),
    release_group: rg === '' ? null : rg,
    regex: rx.trim() === '' ? null : rx,
  };
}

// ---------------- Regex field ----------------

type RegexState = { status: 'idle' | 'checking' | 'valid' | 'invalid' | 'error'; message: string | null };

export function RegexField({ value, onChange }: { value: string | null; onChange: (v: string | null) => void }) {
  const [state, setState] = useState<RegexState>({ status: 'idle', message: null });
  const check = async (pattern: string) => {
    if (pattern.trim() === '') {
      setState({ status: 'idle', message: null });
      return;
    }
    setState({ status: 'checking', message: null });
    try {
      const res = await validateRegex(pattern);
      setState(res.valid ? { status: 'valid', message: null } : { status: 'invalid', message: res.error ?? 'invalid regex' });
    } catch (e: unknown) {
      setState({ status: 'error', message: errorMessage(e) });
    }
  };
  return (
    <FormField
      label="Regex (optional, advanced)"
      error={state.status === 'invalid' ? `Invalid: ${state.message ?? ''}` : state.status === 'error' ? `Could not validate: ${state.message ?? ''}` : null}
      help={
        <>
          Python <code>re</code> syntax, applied with <code>re.search</code>, case-insensitive, against the raw title. Not PCRE.
          {state.status === 'checking' ? ' Checking…' : state.status === 'valid' ? ' ✓ valid' : ''}
        </>
      }
      badge={state.status === 'valid' ? <StatusBadge status="valid" tone="green" /> : null}
    >
      {(id) => (
        <input
          id={id}
          type="text"
          className="mono"
          value={value ?? ''}
          placeholder={String.raw`e.g. ^\[DKB\] Black[ ._]Clover`}
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          autoComplete="off"
          onChange={(e) => {
            onChange(e.target.value === '' ? null : e.target.value);
            if (state.status !== 'idle') setState({ status: 'idle', message: null });
          }}
          onBlur={(e) => void check(e.target.value)}
        />
      )}
    </FormField>
  );
}

// ---------------- Fields ----------------

type FieldsProps = {
  value: RuleIn;
  onChange: (r: RuleIn) => void;
  seriesOptions?: Series[]; // when present, a series select is shown
  /** Season choices; `id` is the value stored in rule.season_id (a real id, or an index for unsaved series). */
  seasons: Pick<Season, 'id' | 'season_number' | 'monitored'>[];
  hideSeries?: boolean;
};

export function RuleFields({ value, onChange, seriesOptions, seasons, hideSeries }: FieldsProps) {
  const set = <K extends keyof RuleIn>(k: K, v: RuleIn[K]) => onChange({ ...value, [k]: v });
  return (
    <div className="form-grid">
      <FormField label="Rule name">
        {(id) => (
          <input id={id} type="text" required value={value.name} onChange={(e) => set('name', e.target.value)} placeholder="e.g. DKB 1080p" />
        )}
      </FormField>
      {!hideSeries && seriesOptions ? (
        <FormField label="Series">
          {(id) => (
            <select
              id={id}
              value={value.series_id}
              onChange={(e) => onChange({ ...value, series_id: Number(e.target.value), season_id: null })}
            >
              {seriesOptions.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          )}
        </FormField>
      ) : null}
      <FormField label="Season" help="Bind to one season, or leave as any season defined for the series.">
        {(id) => (
          <select
            id={id}
            value={value.season_id ?? ''}
            onChange={(e) => set('season_id', e.target.value === '' ? null : Number(e.target.value))}
          >
            <option value="">Any defined season</option>
            {seasons.map((s) => (
              <option key={s.id} value={s.id}>
                Season {s.season_number}
                {s.monitored ? '' : ' (unmonitored)'}
              </option>
            ))}
          </select>
        )}
      </FormField>
      <FormField label="Priority" help="Higher wins when several rules match the same episode.">
        {(id) => <NumberInput id={id} value={value.priority} onChange={(v) => set('priority', v ?? 0)} />}
      </FormField>
      <FormField label="Release group" help="e.g. DKB (case-insensitive).">
        {(id) => (
          <input
            id={id}
            type="text"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            value={value.release_group ?? ''}
            onChange={(e) => set('release_group', e.target.value === '' ? null : e.target.value)}
            placeholder="DKB"
          />
        )}
      </FormField>
      <CheckField
        label={
          <>
            Require literal <code>[{value.release_group?.trim() || 'GROUP'}]</code> title prefix
          </>
        }
        checked={value.require_group_prefix}
        onChange={(v) => set('require_group_prefix', v)}
      />
      <FormField label="Resolutions" help="Comma-separated, e.g. 1080p, 720p. Empty = any.">
        {(id) => <ListInput id={id} value={value.resolutions} onChange={(v) => set('resolutions', v)} placeholder="1080p" />}
      </FormField>
      <FormField label="Include keywords" help="All must appear in the title.">
        {(id) => <ListInput id={id} value={value.include_keywords} onChange={(v) => set('include_keywords', v)} />}
      </FormField>
      <FormField label="Exclude keywords" help="Reject if any appears.">
        {(id) => <ListInput id={id} value={value.exclude_keywords} onChange={(v) => set('exclude_keywords', v)} placeholder="batch, dub" />}
      </FormField>
      <FormField label="Sources" help="e.g. WEB, BD. Empty = any.">
        {(id) => <ListInput id={id} value={value.sources} onChange={(v) => set('sources', v)} />}
      </FormField>
      <FormField label="Codecs" help="e.g. HEVC, x264. Empty = any.">
        {(id) => <ListInput id={id} value={value.codecs} onChange={(v) => set('codecs', v)} />}
      </FormField>
      <FormField label="Subtitle / language keywords">
        {(id) => <ListInput id={id} value={value.language_keywords} onChange={(v) => set('language_keywords', v)} placeholder="ENG, Multi-Subs" />}
      </FormField>
      <FormField label="Min size (MB)" help="Only applied when the feed provides a size.">
        {(id) => <NumberInput id={id} integer={false} min={0} value={value.min_size_mb} onChange={(v) => set('min_size_mb', v)} />}
      </FormField>
      <FormField label="Max size (MB)">
        {(id) => <NumberInput id={id} integer={false} min={0} value={value.max_size_mb} onChange={(v) => set('max_size_mb', v)} />}
      </FormField>
      <div className="span-2">
        <RegexField value={value.regex} onChange={(v) => set('regex', v)} />
      </div>
      <CheckField label="Enabled" checked={value.enabled} onChange={(v) => set('enabled', v)} />
    </div>
  );
}

// ---------------- Simulate on a sample title ----------------

export function SimulateBox({ rule, defaultTitle = '' }: { rule: RuleIn; defaultTitle?: string }) {
  const [title, setTitle] = useState(defaultTitle);
  const sim = useSimulateRule();
  const inputId = useId();
  const result: SimulationResult | undefined = sim.data?.items[0];
  const run = () => {
    if (title.trim() && !sim.isPending) sim.mutate({ rule: cleanRule(rule), titles: [title.trim()] });
  };
  return (
    <div className="simulate-box">
      {/* Not a <form>: SimulateBox is rendered inside RuleForm's <form>, and a nested form's submit
          bubbles (React tree) to the outer onSubmit, which would save the rule and close the editor. */}
      <div className="inline-form">
        <label className="sr-only" htmlFor={inputId}>
          Sample title
        </label>
        <input
          id={inputId}
          type="text"
          className="grow"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              // Keep Enter from submitting (saving) the surrounding rule form.
              e.preventDefault();
              run();
            }
          }}
          placeholder="[DKB] Black Clover Season 2 - 01 [1080p]"
        />
        <button type="button" className="btn" disabled={sim.isPending || !title.trim()} onClick={run}>
          {sim.isPending ? 'Simulating…' : 'Simulate on sample title'}
        </button>
      </div>
      <ErrorBanner error={sim.error} />
      {result ? (
        <div className="sim-result">
          <div className="sim-head">
            <StatusBadge status={result.matched ? 'accepted' : 'rejected'} />{' '}
            <span>{result.matched ? 'Would match' : 'Would not match'}</span>{' '}
            <span className="muted">{seasonEpisode(result.season_number, result.episode_number)}</span>
          </div>
          <ParsedBadges parsed={result.parsed} />
          {result.save_path ? <PathPreview path={result.save_path} /> : null}
          <ConditionsTable conditions={result.conditions} compact />
        </div>
      ) : null}
    </div>
  );
}

// ---------------- Full form with save ----------------

type FormProps = {
  initial: Rule | null;
  defaultSeriesId: number;
  seriesOptions?: Series[];
  seasonsFor: (seriesId: number) => Season[];
  onDone: (rule: Rule | null) => void;
};

export function RuleForm({ initial, defaultSeriesId, seriesOptions, seasonsFor, onDone }: FormProps) {
  const [value, setValue] = useState<RuleIn>(() => (initial ? ruleToIn(initial) : emptyRule(defaultSeriesId)));
  const save = useSaveRule();
  return (
    <form
      className="rule-form"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(
          { id: initial?.id, body: cleanRule(value) },
          { onSuccess: (r) => onDone(r) },
        );
      }}
    >
      <RuleFields value={value} onChange={setValue} seriesOptions={seriesOptions} seasons={seasonsFor(value.series_id)} />
      <details className="details">
        <summary>Simulate on sample title</summary>
        <SimulateBox rule={value} />
      </details>
      <ErrorBanner error={save.error} />
      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={save.isPending || value.name.trim() === ''}>
          {save.isPending ? 'Saving…' : initial ? 'Save rule' : 'Create rule'}
        </button>
        <button type="button" className="btn btn-ghost" onClick={() => onDone(null)}>
          Cancel
        </button>
      </div>
    </form>
  );
}
