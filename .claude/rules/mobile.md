# Mobile UI (decided 2026-10-14)

Target: phones 360-430 px wide (iPhone 12-15, Pixel), portrait, touch. Desktop layout stays as is above 900 px. Breakpoints: `<= 900px` = mobile layout.
Must hold on every page: no horizontal page scroll, every action reachable without sideways scrolling, tap targets >= 44 px, inputs with `font-size: 16px`
(prevents iOS zoom), safe-area insets respected (`env(safe-area-inset-*)`), readable without zooming.

## Navigation
- Top app bar (sticky, 56 px): brand left, page title centered/left, menu button right (44 px). Menu opens a full-height slide-over with all routes and the
  scheduler indicator; tapping a route closes it; Escape/backdrop closes; body scroll locked while open.
- Primary page actions ("Add feed", "Add rule", "New series") move into a sticky bottom action bar on mobile (one or two buttons, full width, above the safe area).

## Tables -> cards on mobile
Every data table (`Table` component users: feeds, series list, rules, releases, downloads, activity, episodes, seasons, calendar rows, wanted, search candidates,
rejected list, dashboard lists) renders as a **card list** at `<= 900px`: one card per row, with the primary text (title/name) on top, secondary meta
(badges, dates, sizes) in a wrapping line, and actions as full-width or half-width buttons at the bottom of the card. Implement generically:
`Table` gets an optional `mobileCard: (row) => ReactNode` or the rows carry `data-label` per cell so CSS can render `display:block` cells with
`::before { content: attr(data-label) }`. Choose the `data-label` approach for the plain tables (less code) and explicit card renderers for the complex ones
(episodes, search candidates, downloads). Long monospace values (paths, magnets, infohashes) wrap with `overflow-wrap: anywhere`, never clip.

## Drawers and modals
- Drawers (feed preview, search, grab flow) are full-screen sheets on mobile: sticky header with title + close (44 px), scrollable body, sticky footer with the
  primary action ("Grab all missing", "Confirm send"). The grab flow inside the drawer stacks its fields vertically.
- Inline confirms (`ConfirmInline`) wrap to their own line under the action on mobile with full-width Confirm/Cancel buttons.

## Forms
- One column; labels above inputs; number inputs `inputmode="numeric"`; URL inputs `inputmode="url"`, `autocapitalize="off"`, `autocorrect="off"`;
  comma-list inputs keep working; select elements native. Form submit buttons full width at the bottom. Wizard steps show a compact step indicator (1/4) and
  prev/next in a sticky footer.

## Dashboard
- Count cards in a 2-column grid; feed health, upcoming, recent downloads and recent releases as card lists; onboarding card first when shown.

## Visual polish (both widths)
- Consistent spacing scale (4/8/12/16/24), card radius 10 px, badge size 12 px, body 15-16 px on mobile, headings 20/17 px, 1.45 line height.
- Dark mode parity for every new rule (use the existing CSS variables; no hard-coded colors).
- Focus-visible outlines kept; hover-only affordances must also be reachable by tap (no hover-revealed buttons).

## Verification (QA agent)
Playwright at 390x844 and 360x780 (+ 1366x900 regression) for every route and for: menu open/close, feed drawer, search drawer with candidates and rejected
list, grab flow in the drawer up to the confirm button (not clicked), episode title edit, wizard steps 1-4, settings form, downloads delete confirm.
Assert `document.documentElement.scrollWidth <= innerWidth`, no console errors, every primary action button fully inside the viewport (bounding box check),
and screenshot each state. Judge visually.
