"""Studio adapter for the read-only book audit.

The audit comes from `puzzlepress.audit`; this module reuses the production
overview Studio already caches for the same bytes, compares with the library's
other books in the same catalog collection (read only), and caches the result by
the bytes it depends on. It writes nothing.
"""

from collections import OrderedDict

from puzzlepress.audit import OtherBook, audit_book, audit_markdown
from puzzlepress.errors import ProjectError
from puzzlepress.inventory import inventory_from_project
from puzzlepress.models import Project

from .production import LOCK_WAIT, ProductionService
from .service import StudioService


def _collection(project: Project) -> str | None:
    return project.catalog.collection if project.catalog is not None else None


class AuditService:
    def __init__(self, service: StudioService, production: ProductionService) -> None:
        self.service = service
        self.store = service.store
        self.production = production
        self._cache: OrderedDict[tuple[object, ...], dict[str, object]] = OrderedDict()

    def _siblings(self, key: str, project: Project) -> list[tuple[str, Project, str]]:
        """Other library books in the same collection, by key order; unreadable ones skipped."""
        collection = _collection(project)
        if collection is None:
            return []
        found: list[tuple[str, Project, str]] = []
        for entry in self.store.discover():
            other = entry.get("key")
            if not isinstance(other, str) or other == key:
                continue
            try:
                sibling, revision = self.store.snapshot(other)
            except ProjectError:
                continue
            if _collection(sibling) == collection:
                found.append((other, sibling, revision))
        return found

    def audit(self, key: str) -> dict[str, object]:
        with self.service.exclusive(wait=LOCK_WAIT):
            project, revision = self.store.snapshot(key)
            source, directory = self.production._folders(key, project)
            siblings = self._siblings(key, project)
            cache_key = (
                self.production._key(key, revision, project, source, directory),
                tuple((other, rev) for other, _, rev in siblings),
            )
            cached = self._cache.get(cache_key)
            if cached is None:
                overview = self.production._status(key)
                others = [
                    OtherBook(
                        sibling.book.id,
                        sibling,
                        inventory_from_project(self.store.source(other), sibling.book.id)
                        if sibling.word_search is not None
                        else None,
                    )
                    for other, sibling, _ in siblings
                ]
                report = audit_book(project, source, directory, others, overview)
                cached = {
                    "audit": report.to_dict(),
                    "markdown": audit_markdown(report),
                    "collection": _collection(project),
                    "compared": [other for other, _, _ in siblings],
                }
                self._cache[cache_key] = cached
                while len(self._cache) > 4:
                    self._cache.popitem(last=False)
            return {"key": key, "revision": revision, **cached}
