/**
 * Sticky bottom bar for a page's primary actions on mobile (<= 900px). Hidden on desktop, where the same
 * actions stay in the page header (render them there with `PageHeader actionsInBar`).
 * A spacer keeps the bar from covering the end of the page.
 */
export function MobileActionBar({ children, label = 'Page actions' }: { children: React.ReactNode; label?: string }) {
  return (
    <>
      <div className="m-actionbar-spacer" aria-hidden="true" />
      <div className="m-actionbar" role="region" aria-label={label}>
        {children}
      </div>
    </>
  );
}
