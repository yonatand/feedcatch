"""First-start defaults. No demo series, rule or feed (see `.claude/rules/metadata.md` "Seed / onboarding").

- settings defaults are written for absent keys;
- when `FEED_URL` is set, that one feed is created once (name = host); its release-search template is prefilled only
  for `feed.animetosho.net`;
- one-time backfill: an existing feed whose url is exactly the AnimeTosho RSS2 url and has no template gets it.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import FeedSource
from app.services import activity, settings_store

log = structlog.get_logger("seed")

ANIMETOSHO_HOST = "feed.animetosho.net"
ANIMETOSHO_RSS2 = "https://feed.animetosho.net/rss2"
ANIMETOSHO_SEARCH_TEMPLATE = "https://feed.animetosho.net/rss2?q={query}"


def search_template_for(url: str) -> str | None:
    """`<url>?q={query}` (or `&q=`) for AnimeTosho feeds; None for any other host (no server-side knowledge)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if (parts.hostname or "").lower() != ANIMETOSHO_HOST or "{" in url or "}" in url:
        return None
    return f"{url}{'&' if parts.query else '?'}q={{query}}"


def seed_defaults(db: Session, settings: Settings) -> bool:
    """Idempotent first-start setup. Commits. Returns True if a feed was created."""
    settings_store.ensure_defaults(db)
    created = False
    url = (settings.FEED_URL or "").strip()
    if url and not settings_store.get(db, settings_store.FEED_SEEDED, False):
        if db.scalar(select(FeedSource).where(FeedSource.url == url)) is None:
            name = (urlsplit(url).hostname or "Feed")[:200]
            db.add(
                FeedSource(
                    name=name,
                    url=url,
                    enabled=True,
                    poll_interval_minutes=15,
                    backfill_mode="skip",
                    search_url_template=search_template_for(url),
                )
            )
            created = True
            log.info("feed_seeded", name=name)
        settings_store.set(db, settings_store.FEED_SEEDED, True)

    if not settings_store.get(db, settings_store.ANIMETOSHO_TEMPLATE_BACKFILLED, False):
        feed = db.scalar(
            select(FeedSource).where(FeedSource.url == ANIMETOSHO_RSS2, FeedSource.search_url_template.is_(None))
        )
        if feed is not None:
            feed.search_url_template = ANIMETOSHO_SEARCH_TEMPLATE
            activity.log_event(
                db,
                "info",
                "feed_search_template_backfilled",
                f"Feed '{feed.name}': release search template set to {ANIMETOSHO_SEARCH_TEMPLATE}",
                details={"feed_id": feed.id},
            )
        settings_store.set(db, settings_store.ANIMETOSHO_TEMPLATE_BACKFILLED, True)
    db.commit()
    return created
