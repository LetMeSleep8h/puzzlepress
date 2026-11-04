"""Serve disposable project copies for browser acceptance, never authored books."""

import shutil
import sys
import tempfile
from pathlib import Path

import uvicorn

from puzzlepress.studio.server import create_app

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))

from planning_helpers import complete_plan, document  # noqa: E402
from production_book import write_production_book  # noqa: E402

from puzzlepress.planning import write_planning  # noqa: E402

with tempfile.TemporaryDirectory(prefix="puzzlepress-browser-") as directory:
    books = Path(directory) / "books"
    for key in ("garden-demo", "composition-demo"):
        target = books / key
        target.mkdir(parents=True)
        shutil.copyfile(ROOT / "books" / key / "book.yaml", target / "book.yaml")
    # Planning: the SYNTHETIC production book's plan, and a synthetic plan ready for
    # approval. Real books live in puzzlepress-books; the engine never reads them.
    write_production_book(books / "production")
    # The same SYNTHETIC 60-puzzle book for the production walkthrough; its builds
    # write only inside this temporary directory.
    write_production_book(books / "production-book")
    source = books / "production-book" / "book.yaml"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "../../build/synthetic-production-book", "../../build/production-book"
        ),
        encoding="utf-8",
    )
    target = books / "planning-ready"
    target.mkdir()
    (target / "book.yaml").write_text(
        (ROOT / "tests/fixtures/legacy-automotive/book.yaml")
        .read_text(encoding="utf-8")
        .replace("Automotive Word Search", "Planning Acceptance Book"),
        encoding="utf-8",
    )
    write_planning(target, document(complete_plan()), None)  # SYNTHETIC test plan.
    target = books / "editor-demo"
    target.mkdir()
    shutil.copyfile(ROOT / "books/garden-demo/book.yaml", target / "book.yaml")
    source = target / "book.yaml"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "Garden Word Searches", "Editor acceptance project"
        ),
        encoding="utf-8",
    )
    target = books / "composer-demo"
    target.mkdir()
    shutil.copyfile(ROOT / "books/composition-demo/book.yaml", target / "book.yaml")
    # Print builds write only inside this temporary directory, never to build/.
    target = books / "print-demo"
    target.mkdir()
    source = (ROOT / "books/composition-demo/book.yaml").read_text(encoding="utf-8")
    (target / "book.yaml").write_text(
        source.replace("../../build/composition-demo", "../../build/print-demo"), encoding="utf-8"
    )
    # Cover Studio: the cover demo with its photograph, and a book without a cover.
    shutil.copytree(ROOT / "books/cover-demo", books / "cover-demo")
    target = books / "cover-start"
    target.mkdir()
    (target / "book.yaml").write_text(
        source.replace("../../build/composition-demo", "../../build/cover-start"), encoding="utf-8"
    )
    # Publishing: the publishing demo, and a second copy for a stale-cover case.
    shutil.copytree(ROOT / "books/publishing-demo", books / "publishing-demo")
    shutil.copytree(ROOT / "books/publishing-demo", books / "publishing-stale")
    source = books / "publishing-stale" / "book.yaml"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "../../build/publishing-demo", "../../build/publishing-stale"
        ),
        encoding="utf-8",
    )
    # Production design and publishing polish: a cover-demo copy with its own builds.
    shutil.copytree(ROOT / "books/cover-demo", books / "design-demo")
    source = books / "design-demo" / "book.yaml"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "../../build/cover-demo", "../../build/design-demo"
        ),
        encoding="utf-8",
    )
    # Cover templates and rich text: another cover-demo copy with its own builds.
    shutil.copytree(ROOT / "books/cover-demo", books / "template-demo")
    source = books / "template-demo" / "book.yaml"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "../../build/cover-demo", "../../build/template-demo"
        ),
        encoding="utf-8",
    )
    # Interior design: a cover-demo copy (20 puzzles) with its own builds.
    shutil.copytree(ROOT / "books/cover-demo", books / "interior-demo")
    source = books / "interior-demo" / "book.yaml"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "../../build/cover-demo", "../../build/interior-demo"
        ),
        encoding="utf-8",
    )
    # An unused photograph for the asset library (SYNTHETIC test pixels).
    from cover_helpers import photo_bytes  # noqa: E402

    from puzzlepress.cover.assets import import_photo  # noqa: E402

    import_photo(books / "design-demo", photo_bytes(900, 600), "spare-photo.jpg")
    import_photo(books / "template-demo", photo_bytes(900, 600), "spare-photo.jpg")
    # Coloring artwork: an empty SYNTHETIC coloring book; the spec imports its drawings.
    from coloring_helpers import write_coloring_book  # noqa: E402

    write_coloring_book(books / "coloring-demo")
    uvicorn.run(create_app(books, ROOT / "studio/dist"), host="127.0.0.1", port=8015)
