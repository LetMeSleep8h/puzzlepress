"""Single-process local HTTP adapter; domain rules remain in the Python core."""

import argparse
import logging
import re
from collections.abc import Callable
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from puzzlepress.cover.assets import MAX_ASSET_BYTES
from puzzlepress.cover.font_assets import MAX_FONT_BYTES
from puzzlepress.creation import NewProject
from puzzlepress.errors import ProjectError

from .assets import AssetService
from .coloring import ColoringService, PreparationService
from .covering import CoverService
from .creating import CreationService
from .designing import DesignService
from .editing import DraftStore
from .planning import PlanningInvalid, PlanningService
from .printing import PrintService
from .producing import ProducingService
from .production import ProductionService
from .publishing import PublishingService
from .reviewing import ReviewService
from .service import ProjectStore, StudioError, StudioService, issue_dicts, project_detail
from .templating import TemplateService

LOGGER = logging.getLogger(__name__)


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity: str


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: dict[str, object]


class SaveRequest(DraftRequest):
    revision: str


class BuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str


class InteriorBuildRequest(BuildRequest):
    profile: str | None = None


class ProjectCreateRequest(BaseModel):
    """A new book. Python validates every value; the browser only collects them."""

    model_config = ConfigDict(extra="forbid")
    kind: str
    key: str
    title: str
    language: str = "en"
    subtitle: str | None = None
    author: str | None = None
    subject: str | None = None
    collection: str | None = None
    profile: str | None = None
    template: str | None = None


class ExportRequest(BuildRequest):
    archive: bool = False


class DesignExportRequest(DraftRequest):
    name: str


class DesignImportRequest(DraftRequest):
    text: str


class PlanningSaveRequest(DraftRequest):
    revision: str | None  # None: planning.yaml does not exist yet.


class ApprovalRequest(BuildRequest):
    identity: str | None  # The planning identity reviewed; None withdraws the approval.


class TemplateSaveRequest(DraftRequest):
    name: str
    description: str = ""


class TemplateUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity: str
    name: str
    description: str = ""


class TemplateNameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


class TemplateDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity: str


class TemplateImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


class OptionalDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: dict[str, object] | None = None


class TrashRequest(OptionalDraftRequest):
    path: str
    sha256: str
    revision: str


class TrashedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trashed: str
    sha256: str | None = None


class ArtworkRemoval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artwork: str
    revision: str
    with_pages: bool = False


class PreparationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artwork: str
    adjustments: dict[str, object] | None = None  # None previews the saved settings.


class AdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artwork: str
    revision: str
    adjustments: dict[str, object] | None  # None restores the defaults.


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_revision: str
    revision: str | None
    puzzle: str
    status: str
    identity: str | None = None
    note: str | None = None
    reviewer: str | None = None
    reviewed_on: str | None = None


class PolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str | None
    require_all: bool


class ProofRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str | None
    record: dict[str, object]


class ProofRemoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str | None
    id: str


# The only non-JSON POSTs: photograph, font and artwork uploads. Their content types
# are not CORS-safelisted, so another site cannot send one without a refused
# preflight. Artwork also admits SVG and unlabeled files, so Python can explain why
# it refuses them instead of the browser seeing a bare rejection.
UPLOAD_PATH = re.compile(r"/api/projects/[^/]+/(cover/assets|cover/fonts|coloring/artwork)")
UPLOAD_TYPES = {
    "cover/assets": ("image/jpeg", "image/png"),
    "cover/fonts": ("font/ttf", "font/otf"),
    "coloring/artwork": ("image/png", "image/jpeg", "image/svg+xml", "application/octet-stream"),
}


def error_response(
    status: int,
    code: str,
    message: str,
    uses: list[object] | None = None,
    issues: list[object] | None = None,
) -> JSONResponse:
    error: dict[str, object] = {"code": code, "message": message, "issues": issues or []}
    if uses is not None:
        error["uses"] = uses  # Where an asset is used, so Studio can link to each use.
    return JSONResponse({"error": error}, status)


def create_app(
    books: Path,
    frontend: Path,
    production_jobs: Callable[[StudioService], ProducingService] = ProducingService,
) -> FastAPI:
    """`production_jobs` builds the production job service (benchmarks set its limits)."""
    service = StudioService(ProjectStore(books.resolve()))
    drafts = DraftStore(service.store)
    printing = PrintService(service, drafts=drafts)
    designs = DesignService(drafts)
    covers = CoverService(service, drafts)
    templates = TemplateService(covers)
    publishing = PublishingService(service, drafts)
    planning = PlanningService(service)
    assets = AssetService(service, drafts)
    coloring = ColoringService(service)
    preparation = PreparationService(service, coloring)
    reviews = ReviewService(service)
    production = ProductionService(service)
    creating = CreationService(service)
    producing = production_jobs(service)
    app = FastAPI(title="PuzzlePress Studio", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )

    @app.middleware("http")
    async def local_boundary(request: Request, call_next: RequestResponseEndpoint) -> Response:
        # A JSON POST and same-origin check prevent other sites driving local generation.
        origin = request.headers.get("origin")
        kind = request.headers.get("content-type", "").split(";")[0]
        upload = UPLOAD_PATH.fullmatch(request.url.path)
        if request.method == "POST" and (
            (origin is not None and origin != str(request.base_url).rstrip("/"))
            or (kind not in UPLOAD_TYPES[upload[1]] if upload else kind != "application/json")
        ):
            return error_response(403, "origin_rejected", "Use Studio on this local server.")
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Digest-addressed page previews may be cached; everything else is no-store.
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self'; style-src 'self'; font-src 'self'; "
            "script-src 'self'; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(StudioError)
    async def studio_error(request: Request, error: StudioError) -> JSONResponse:
        return error_response(
            error.status,
            error.code,
            str(error),
            getattr(error, "uses", None),
            getattr(error, "issues", None),
        )

    @app.exception_handler(ProjectError)
    async def project_error(request: Request, error: ProjectError) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_project",
                    "message": "Project validation failed.",
                    "issues": issue_dicts(error),
                }
            },
            422,
        )

    @app.exception_handler(PlanningInvalid)
    async def planning_error(request: Request, error: PlanningInvalid) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_planning",
                    "message": "The plan does not satisfy the planning schema.",
                    "issues": issue_dicts(error),
                }
            },
            422,
        )

    @app.exception_handler(RequestValidationError)
    async def request_error(request: Request, error: RequestValidationError) -> JSONResponse:
        return error_response(422, "invalid_request", "Supply the required request fields as JSON.")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        return error_response(
            error.status_code,
            "not_found" if error.status_code == 404 else "http_error",
            "Page or endpoint not found." if error.status_code == 404 else "Request not supported.",
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
        LOGGER.error("Unexpected Studio failure", exc_info=error)
        return error_response(
            500, "server_error", "Studio could not complete the request. See the server log."
        )

    @app.get("/api/projects")
    def projects() -> dict[str, object]:
        return {"projects": service.store.discover()}

    @app.get("/api/project-types")
    def project_types() -> dict[str, object]:
        return creating.types()

    @app.post("/api/projects", status_code=201)
    def create_project(body: ProjectCreateRequest) -> dict[str, object]:
        return creating.create(NewProject(**body.model_dump()))

    @app.get("/api/projects/{key}")
    def project(key: str) -> dict[str, object]:
        return service.store.detail(key)

    @app.post("/api/projects/{key}/generation")
    def generation(key: str, body: GenerationRequest) -> dict[str, object]:
        return service.generate(key, body.identity)

    @app.post("/api/projects/{key}/draft/validate")
    def validate_draft(key: str, body: DraftRequest) -> dict[str, object]:
        return project_detail(key, drafts.validate(key, body.source))

    @app.post("/api/projects/{key}/draft/preview")
    def preview_draft(key: str, body: DraftRequest) -> dict[str, object]:
        return service.generate_project(drafts.validate(key, body.source))

    @app.post("/api/projects/{key}/draft/plan")
    def plan_draft(key: str, body: DraftRequest) -> dict[str, object]:
        return service.plan_project(
            drafts.validate(key, body.source), service.store.source(key).parent
        )

    @app.post("/api/projects/{key}/draft/save")
    def save_draft(key: str, body: SaveRequest) -> dict[str, object]:
        return drafts.save(key, body.source, body.revision)

    @app.get("/api/projects/{key}/interior")
    def interior(key: str) -> dict[str, object]:
        return printing.status(key)

    @app.post("/api/projects/{key}/interior/build")
    def build_interior(key: str, body: InteriorBuildRequest) -> dict[str, object]:
        return printing.build(key, body.revision, body.profile)

    @app.post("/api/projects/{key}/draft/interior")
    def draft_interior(key: str, body: DraftRequest) -> dict[str, object]:
        return printing.draft(key, body.source)

    @app.get("/api/interior/designs")
    def interior_designs() -> dict[str, object]:
        return designs.catalogue()

    @app.post("/api/projects/{key}/draft/interior/export")
    def export_interior_design(key: str, body: DesignExportRequest) -> Response:
        filename, data = designs.export(key, body.source, body.name)
        return Response(
            data,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/api/projects/{key}/draft/interior/import")
    def import_interior_design(key: str, body: DesignImportRequest) -> dict[str, object]:
        return designs.import_file(key, body.source, body.text)

    @app.get("/api/projects/{key}/draft/interior/pages/{index}")
    def draft_interior_page(key: str, index: int, size: str, pdf: str) -> Response:
        return Response(
            printing.draft_image(key, index, size, pdf),
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
        )

    @app.get("/api/projects/{key}/interior/pdf")
    def interior_pdf(key: str, pdf: str) -> Response:
        return Response(
            printing.pdf(key, pdf),
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="interior.pdf"'},
        )

    @app.get("/api/projects/{key}/interior/pages/{page}")
    def interior_page(key: str, page: int, size: str, pdf: str) -> Response:
        image = printing.page_image(key, page, size, pdf)
        return Response(
            image,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
        )

    @app.get("/api/projects/{key}/cover")
    def cover(key: str) -> dict[str, object]:
        return covers.status(key)

    @app.post("/api/projects/{key}/draft/cover")
    def draft_cover(key: str, body: DraftRequest) -> dict[str, object]:
        return covers.draft(key, body.source)

    @app.post("/api/projects/{key}/draft/cover/convert")
    def convert_cover(key: str, body: DraftRequest) -> dict[str, object]:
        return covers.convert(key, body.source)

    @app.post("/api/projects/{key}/draft/cover/presets")
    def cover_presets(key: str, body: DraftRequest) -> dict[str, object]:
        return covers.presets(key, body.source)

    @app.post("/api/projects/{key}/assets/list")
    def asset_library(key: str, body: OptionalDraftRequest) -> dict[str, object]:
        return assets.listing(key, body.source)

    @app.post("/api/projects/{key}/assets/trash")
    def trash_asset(key: str, body: TrashRequest) -> dict[str, object]:
        return assets.trash(key, body.path, body.sha256, body.revision, body.source)

    @app.post("/api/projects/{key}/assets/restore")
    def restore_asset(key: str, body: TrashedRequest) -> dict[str, object]:
        return assets.restore(key, body.trashed)

    @app.post("/api/projects/{key}/assets/purge")
    def purge_asset(key: str, body: TrashedRequest) -> dict[str, object]:
        if body.sha256 is None:
            raise StudioError(422, "invalid_request", "Confirm the asset's SHA-256 to purge it.")
        return assets.purge(key, body.trashed, body.sha256)

    @app.get("/api/projects/{key}/reviews")
    def review_status(key: str) -> dict[str, object]:
        return reviews.reviews(key)

    @app.post("/api/projects/{key}/reviews/record")
    def record_review(key: str, body: ReviewRequest) -> dict[str, object]:
        return reviews.record(
            key,
            body.source_revision,
            body.revision,
            body.puzzle,
            body.status,
            body.identity,
            body.note,
            body.reviewer,
            body.reviewed_on,
        )

    @app.post("/api/projects/{key}/reviews/policy")
    def review_policy(key: str, body: PolicyRequest) -> dict[str, object]:
        return reviews.policy(key, body.revision, body.require_all)

    @app.get("/api/projects/{key}/proofs")
    def proof_status(key: str) -> dict[str, object]:
        return reviews.proofs(key)

    @app.post("/api/projects/{key}/proofs/record")
    def record_proof(key: str, body: ProofRequest) -> dict[str, object]:
        return reviews.record_proof(key, body.revision, body.record)

    @app.post("/api/projects/{key}/proofs/remove")
    def remove_proof(key: str, body: ProofRemoveRequest) -> dict[str, object]:
        return reviews.remove_proof(key, body.revision, body.id)

    @app.get("/api/projects/{key}/produce")
    def produce_status(key: str) -> dict[str, object]:
        return producing.status(key)

    @app.get("/api/projects/{key}/produce/job")
    def produce_job(key: str) -> dict[str, object]:
        return producing.job(key)

    @app.post("/api/projects/{key}/produce")
    def produce_start(key: str, body: BuildRequest) -> dict[str, object]:
        return producing.start(key, body.revision)

    @app.post("/api/projects/{key}/produce/cancel")
    def produce_cancel(key: str) -> dict[str, object]:
        return producing.cancel(key)

    @app.get("/api/projects/{key}/produce/file")
    def produce_file(key: str, name: str) -> Response:
        data, filename = producing.file(key, name)
        kind = (
            "application/pdf"
            if filename.endswith(".pdf")
            else "application/json"
            if filename.endswith(".json")
            else "text/markdown; charset=utf-8"
        )
        return Response(
            data,
            media_type=kind,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/projects/{key}/produce/package.zip")
    def produce_package(key: str) -> Response:
        return Response(
            producing.package_zip(key),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{key}-kdp-package.zip"'},
        )

    @app.get("/api/projects/{key}/production")
    def production_status(key: str) -> dict[str, object]:
        return production.status(key)

    @app.post("/api/projects/{key}/rebuild")
    def rebuild_outdated(key: str, body: BuildRequest) -> dict[str, object]:
        return production.rebuild(key, body.revision)

    @app.get("/api/projects/{key}/cover/templates")
    def cover_templates(key: str) -> dict[str, object]:
        return templates.gallery(key)

    @app.post("/api/projects/{key}/draft/cover/templates/{template_id}/preview")
    def preview_cover_template(key: str, template_id: str, body: DraftRequest) -> dict[str, object]:
        return templates.preview(key, template_id, body.source)

    @app.post("/api/projects/{key}/cover/templates")
    def save_cover_template(key: str, body: TemplateSaveRequest) -> dict[str, object]:
        return templates.save(key, body.source, body.name, body.description)

    @app.post("/api/projects/{key}/cover/templates/import")
    def import_cover_template(key: str, body: TemplateImportRequest) -> dict[str, object]:
        return templates.import_template(key, body.text)

    @app.post("/api/projects/{key}/cover/templates/{template_id}/update")
    def update_cover_template(
        key: str, template_id: str, body: TemplateUpdateRequest
    ) -> dict[str, object]:
        return templates.update(key, template_id, body.identity, body.name, body.description)

    @app.post("/api/projects/{key}/cover/templates/{template_id}/duplicate")
    def duplicate_cover_template(
        key: str, template_id: str, body: TemplateNameRequest
    ) -> dict[str, object]:
        return templates.duplicate(key, template_id, body.name)

    @app.post("/api/projects/{key}/cover/templates/{template_id}/delete")
    def delete_cover_template(
        key: str, template_id: str, body: TemplateDeleteRequest
    ) -> dict[str, object]:
        return templates.delete(key, template_id, body.identity)

    @app.get("/api/projects/{key}/cover/templates/{template_id}/export")
    def export_cover_template(key: str, template_id: str) -> Response:
        name, data = templates.export(key, template_id)
        return Response(
            data,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.post("/api/projects/{key}/cover/build")
    def build_cover(key: str, body: BuildRequest) -> dict[str, object]:
        return covers.build(key, body.revision)

    @app.get("/api/projects/{key}/cover/assets")
    def cover_assets(key: str) -> dict[str, object]:
        return covers.assets(key)

    async def read_upload(request: Request, limit: int, code: str, what: str) -> bytes:
        declared = request.headers.get("content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > limit):
            raise StudioError(413, code, f"The {what} file is too large.")
        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise StudioError(413, code, f"The {what} file is too large.")
            chunks.append(chunk)
        return b"".join(chunks)

    @app.post("/api/projects/{key}/cover/assets")
    async def import_cover_photo(key: str, request: Request, name: str = "photo") -> JSONResponse:
        data = await read_upload(request, MAX_ASSET_BYTES, "image_unsupported", "photograph")
        return JSONResponse(covers.import_photo(key, data, name[:200]))

    @app.get("/api/projects/{key}/cover/assets/thumbnail")
    def cover_thumbnail(key: str, path: str) -> Response:
        return Response(
            covers.thumbnail(key, path[:200]),
            media_type="image/jpeg",
            headers={"Cache-Control": "private, no-cache"},
        )

    @app.get("/api/projects/{key}/cover/fonts")
    def cover_fonts(key: str) -> dict[str, object]:
        return covers.fonts(key)

    @app.post("/api/projects/{key}/cover/fonts")
    async def import_cover_font(key: str, request: Request, name: str = "font.ttf") -> JSONResponse:
        data = await read_upload(request, MAX_FONT_BYTES, "font_unsupported", "font")
        return JSONResponse(covers.import_font(key, data, name[:200]))

    @app.get("/api/projects/{key}/cover/fonts/specimen")
    def cover_font_specimen(key: str, font: str) -> Response:
        return Response(
            covers.specimen(key, font[:200]),
            media_type="image/png",
            headers={"Cache-Control": "private, no-cache"},
        )

    @app.get("/api/projects/{key}/cover/preview")
    def cover_preview(key: str, size: str, pdf: str) -> Response:
        image = covers.image(key, pdf, size)
        return Response(
            image,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
        )

    @app.get("/api/projects/{key}/coloring")
    def coloring_library(key: str) -> dict[str, object]:
        return coloring.listing(key)

    @app.post("/api/projects/{key}/coloring/artwork")
    async def import_artwork(
        key: str, request: Request, revision: str, name: str = "artwork.png"
    ) -> JSONResponse:
        data = await read_upload(request, MAX_ASSET_BYTES, "file_too_large", "artwork")
        return JSONResponse(coloring.import_artwork(key, data, name[:200], revision))

    @app.post("/api/projects/{key}/coloring/remove")
    def remove_artwork(key: str, body: ArtworkRemoval) -> dict[str, object]:
        return coloring.remove(key, body.artwork, body.revision, body.with_pages)

    @app.post("/api/projects/{key}/coloring/prepare")
    def prepare_artwork(key: str, body: PreparationRequest) -> dict[str, object]:
        return preparation.prepare(key, body.artwork, body.adjustments)

    @app.get("/api/projects/{key}/coloring/prepared/{prepared}/{kind}")
    def prepared_image(key: str, prepared: str, kind: str) -> Response:
        return Response(
            preparation.image(key, prepared[:128], kind),
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=3600, immutable"},
        )

    @app.post("/api/projects/{key}/coloring/adjustments")
    def adjust_artwork(key: str, body: AdjustmentRequest) -> dict[str, object]:
        return preparation.adjust(key, body.artwork, body.adjustments, body.revision)

    @app.get("/api/projects/{key}/coloring/thumbnail")
    def artwork_thumbnail(key: str, artwork: str) -> Response:
        return Response(
            coloring.thumbnail(key, artwork[:64]),
            media_type="image/png",
            headers={"Cache-Control": "private, no-cache"},
        )

    @app.get("/api/projects/{key}/publishing")
    def publishing_status(key: str) -> dict[str, object]:
        return publishing.status(key)

    @app.post("/api/projects/{key}/draft/publishing")
    def draft_publishing(key: str, body: DraftRequest) -> dict[str, object]:
        return publishing.draft(key, body.source)

    @app.post("/api/projects/{key}/publishing/export")
    def export_publishing(key: str, body: ExportRequest) -> dict[str, object]:
        return publishing.export(key, body.revision, body.archive)

    @app.get("/api/projects/{key}/planning")
    def planning_status(key: str) -> dict[str, object]:
        return planning.status(key)

    @app.post("/api/projects/{key}/draft/planning")
    def draft_planning(key: str, body: DraftRequest) -> dict[str, object]:
        return planning.draft(key, body.source)

    @app.post("/api/projects/{key}/planning/save")
    def save_planning(key: str, body: PlanningSaveRequest) -> dict[str, object]:
        return planning.save(key, body.source, body.revision)

    @app.post("/api/projects/{key}/planning/approval")
    def planning_approval(key: str, body: ApprovalRequest) -> dict[str, object]:
        return planning.approval(key, body.revision, body.identity)

    if (frontend / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

    @app.get("/logo.png")
    def logo() -> FileResponse:
        path = frontend / "logo.png"
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path)

    @app.get("/")
    @app.get("/books")
    @app.get("/create")
    @app.get("/books/{key}")
    @app.get("/books/{key}/settings")
    @app.get("/books/{key}/produce")
    @app.get("/books/{key}/puzzles")
    @app.get("/books/{key}/quality")
    @app.get("/books/{key}/edit")
    @app.get("/books/{key}/book")
    @app.get("/books/{key}/interior")
    @app.get("/books/{key}/print")
    @app.get("/books/{key}/cover")
    @app.get("/books/{key}/publishing")
    @app.get("/books/{key}/planning")
    @app.get("/books/{key}/artwork")
    @app.get("/books/{key}/pages")
    @app.get("/books/{key}/puzzles/{puzzle_id}")
    def shell() -> FileResponse:
        index = frontend / "index.html"
        if not index.is_file():
            raise StudioError(
                503, "frontend_missing", "Build Studio first: cd studio, npm ci, npm run build."
            )
        return FileResponse(index)

    return app


def default_frontend() -> Path:
    """This engine checkout's built Studio, so Studio can serve a library kept elsewhere.

    An editable install resolves to the checkout's studio/dist from any working
    directory (for example a separate book repository); otherwise ./studio/dist.
    """
    checkout = Path(__file__).resolve().parents[3] / "studio" / "dist"
    return checkout if (checkout / "index.html").is_file() else Path("studio/dist")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the local PuzzlePress authoring Studio.")
    parser.add_argument(
        "--books",
        type=Path,
        default=Path("books"),
        help="Library folder whose subfolders each hold a book.yaml (any location)",
    )
    parser.add_argument("--frontend", type=Path, default=None, help="Built Studio (studio/dist)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--worker-priority",
        choices=("normal", "low"),
        default="normal",
        help="Scheduling priority of production workers (low yields to other work)",
    )
    args = parser.parse_args(argv)
    if not args.books.is_dir():
        parser.error(f"--books {args.books} is not a directory of book projects.")
    frontend = args.frontend if args.frontend is not None else default_frontend()
    print(f"PuzzlePress Studio library: {args.books.resolve()}")
    low = args.worker_priority == "low"

    def jobs(service: StudioService) -> ProducingService:
        return ProducingService(service, lower_priority=low)

    uvicorn.run(create_app(args.books, frontend, jobs), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
