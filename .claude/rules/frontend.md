# Frontend conventions (fast load is a requirement)

- Vite 5 + React 18 + TypeScript strict. Dependencies allowed: `react`, `react-dom`, `react-router-dom`, `@tanstack/react-query`. Nothing else at runtime
  (no UI kit, no icon packs, no date libs, no axios, no state libs). Dev deps: `typescript`, `vite`, `@vitejs/plugin-react`, `@types/react*`, `eslint` optional.
- `vite.config.ts`: `build.outDir = '../backend/app/static'`, `emptyOutDir: true`, `build.target = 'es2020'`, `manualChunks` so vendor (react + router + query) is its own cached chunk.
  Dev server proxies `/api` and `/healthz` to `http://127.0.0.1:8000`.
- Every page is `React.lazy` + `<Suspense>` route. Shared layout: left sidebar nav (collapses to top bar < 900px), content area max-width 1200px.
- `src/api/client.ts`: a single `api<T>(path, init?)` fetch wrapper: `credentials: 'same-origin'`, JSON, throws `ApiError {status, detail}`; on 401 redirect to `/login`
  (or `/setup` when `setup_required`). `src/api/types.ts` mirrors `.claude/rules/api-contract.md` exactly (copy the TS types).
- `src/api/hooks.ts`: react-query hooks per endpoint; `staleTime` 10s; dashboard refetchInterval 30s; downloads 15s.
- CSS: one `src/styles.css` with CSS variables (light + `prefers-color-scheme: dark`), system font stack, no web fonts. Tables for lists, cards for summaries.
  Status badges: pending=grey, submitted=green, failed=red, exists=blue, path_mismatch=orange, accepted=green, rejected/no_match=grey, duplicate=blue, historical=purple.
- Forms: plain controlled inputs; list fields (aliases, keywords, resolutions) are comma-separated text inputs converted to arrays on submit. Show server `detail` errors inline.
- Every destructive action (delete, force grab, confirm grab) uses an inline confirm step (not `window.confirm`).
- Match inspector shows a table of conditions per rule: check | passed (✓/✗) | detail. Grab flow: click "Grab" -> fetch GrabPreview -> show save_path, category, magnet, warnings, duplicate -> "Confirm send".
- New-series wizard (`/series/new`): step 1 name/aliases, step 2 seasons (season number, episode/absolute ranges, path preview via `/api/series/preview-path`),
  step 3 rule (group, prefix check, resolution, keywords, regex optional) with "Test against recent releases" using `/api/rules/simulate` against titles from `/api/entries` or feed preview,
  step 4 review: monitored toggle (default off), create series + season(s) + rule.
- Accessibility basics: labels on inputs, buttons not divs, focus styles kept.
- Performance: no barrel re-exports of all pages; avoid rendering > 200 rows (paginate); `bun run build` must report the entry chunk under 120 KB gzip. `bun run typecheck` = `tsc --noEmit`. Package manager is **Bun** (`bun.lock`; never commit `package-lock.json`).

## Learned the hard way (2026-10-13)
- Never nest a `<form>` inside another form (SimulateBox inside RuleForm). Use a `div` and `type="button"`; handle Enter with `preventDefault()`.
- Component-specific button classes must be scoped (`.sidebar .menu-toggle`), because `.btn` defined later in the stylesheet wins at equal specificity.
- Tables at phone width: wrapper scrolls horizontally; keep action cells `white-space: nowrap`, give the wrapper a scroll affordance, and let empty-state rows wrap.
