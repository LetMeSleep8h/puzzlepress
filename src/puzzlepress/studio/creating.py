"""Studio adapter for creating a book in the library (`puzzlepress.creation`)."""

from dataclasses import replace

from puzzlepress.creation import NewProject, create_project, project_types, suggest_key

from .editing import _SAVE_LOCK
from .service import StudioError, StudioService, project_detail


class CreationService:
    def __init__(self, service: StudioService) -> None:
        self.service = service

    def types(self) -> dict[str, object]:
        from puzzlepress.interior import PROFILES

        return {
            "types": project_types(),
            "profiles": [
                {
                    "id": spec.profile_id,
                    "description": spec.description,
                    "paper": spec.paper.value,
                    "trim": {"width": spec.trim.width, "height": spec.trim.height},
                    "bleed": spec.bleed,
                }
                for spec in PROFILES.values()
            ],
        }

    def create(self, request: NewProject) -> dict[str, object]:
        root = self.service.store.root
        if not root.is_dir():
            raise StudioError(503, "library_unavailable", "The books directory is missing.")
        if not request.key:
            request = replace(request, key=suggest_key(request.title))
        # One writer at a time in this process, like every other source write.
        with _SAVE_LOCK:
            created = create_project(root, request)
        key = created.path.parent.name
        # Read back through the library, exactly as the Library and Overview will.
        return {
            **project_detail(key, *self.service.store.snapshot(key)),
            "recovered": created.recovered,
        }
