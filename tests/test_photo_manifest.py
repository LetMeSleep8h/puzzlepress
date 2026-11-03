"""Explicit photo selection: manifests, Windows-style paths, print checks, import."""

import hashlib
import os
import sys
from pathlib import Path

import pytest

from puzzlepress.cli import main
from puzzlepress.photo_manifest import (
    ManifestError,
    PhotoEntry,
    PhotoManifest,
    check_photo,
    check_photos,
    parse_manifest,
    resolve_entry,
)
from puzzlepress.yaml_io import dump_project
from tests.cover_helpers import photo_bytes
from tests.helpers import demo_variant


def test_manifest_keeps_authored_windows_paths_verbatim() -> None:
    text = (
        "photo_manifest_version: 1\n"
        "base_directory: 'E:\\cameras'\n"
        "photos:\n"
        "  - path: '2025\\Track Day\\Événement 01.JPG'\n"
        "    role: cover\n"
        "  - 'C:\\Users\\me\\Pictures\\garage shot.png'\n"
    )
    manifest = parse_manifest(text, "photos.yaml")
    assert manifest.base_directory == "E:\\cameras"
    assert manifest.entries == (
        PhotoEntry("2025\\Track Day\\Événement 01.JPG", "cover"),
        PhotoEntry("C:\\Users\\me\\Pictures\\garage shot.png", "cover"),
    )


@pytest.mark.skipif(os.name == "nt", reason="drive paths are real paths on Windows")
def test_windows_drive_paths_are_reported_on_other_systems() -> None:
    entry = PhotoEntry("E:\\cameras\\IMG_0001.JPG")
    check, data = check_photo(entry, resolve_entry(entry.path, None, Path.cwd()))
    assert data is None and check.status == "error"
    assert check.issues[0][0] == "windows_path"


@pytest.mark.skipif(os.name != "nt", reason="Windows path joining")
def test_windows_relative_entries_join_the_drive_base() -> None:
    joined = resolve_entry("2025\\Track Day\\ü.jpg", "E:\\cameras", None)
    assert str(joined) == "E:\\cameras\\2025\\Track Day\\ü.jpg"


@pytest.mark.parametrize(
    "text",
    [
        "photos: [a.jpg]\n",
        "photo_manifest_version: 1\nphotos: []\n",
        "photo_manifest_version: 1\nphotos: ['shots/*.jpg']\n",
        "photo_manifest_version: 1\nphotos: [{path: a.jpg, role: back}]\n",
        "photo_manifest_version: 1\nphotos: [{path: a.jpg, crop: 1}]\n",
        "photo_manifest_version: 1\nfolder: x\nphotos: [a.jpg]\n",
        "- a.jpg\n",
    ],
)
def test_malformed_manifests_are_rejected(text) -> None:
    with pytest.raises(ManifestError):
        parse_manifest(text, "photos.yaml")


@pytest.fixture
def archive(tmp_path):
    """A nested photo folder with spaces and Unicode names (never scanned)."""
    folder = tmp_path / "cameras" / "2025 Track Day" / "Été"
    folder.mkdir(parents=True)
    (folder / "wide shot ü.jpg").write_bytes(photo_bytes(6000, 4000))
    (folder / "portrait.png").write_bytes(photo_bytes(2700, 3450, fmt="PNG"))
    (folder / "small.jpg").write_bytes(photo_bytes(600, 400))
    (folder / "medium.jpg").write_bytes(photo_bytes(2000, 2600))
    (folder / "notes.txt").write_text("not a photo", encoding="utf-8")
    return tmp_path / "cameras"


def _manifest(archive, *paths, role="cover"):
    return PhotoManifest(tuple(PhotoEntry(p, role) for p in paths), str(archive))


def test_checks_report_size_aspect_and_print_resolution(archive) -> None:
    sub = "2025 Track Day/Été/"
    report = check_photos(
        _manifest(
            archive,
            sub + "wide shot ü.jpg",
            sub + "portrait.png",
            sub + "small.jpg",
            sub + "medium.jpg",
            sub + "missing.jpg",
            sub + "notes.txt",
            sub.rstrip("/"),
        ),
        None,
    )
    by = {Path(c.entry.path).name: c for c in report.checks}
    wide = by["wide shot ü.jpg"]
    assert wide.status == "ok" and wide.pixels == (6000, 4000)
    assert wide.aspect_ratio == pytest.approx(1.5)
    assert wide.max_dpi == pytest.approx(min(6000 / 8.625, 4000 / 11.25))
    assert by["portrait.png"].status == "ok"
    assert by["medium.jpg"].status == "warning"
    assert by["medium.jpg"].issues[0][0] == "image_low_dpi"
    assert by["small.jpg"].status == "error"
    assert by["small.jpg"].issues[0][0] == "image_too_small"
    assert by["missing.jpg"].issues[0][0] == "missing"
    assert by["notes.txt"].issues[0][0] == "image_unsupported"
    assert by["Été"].issues[0][0] == "directory"
    assert report.errors == 4 and report.warnings == 1


def test_import_copies_only_usable_photos_and_keeps_originals(archive, tmp_path) -> None:
    project = tmp_path / "book"
    project.mkdir()
    original = archive / "2025 Track Day" / "Été" / "wide shot ü.jpg"
    before = (original.read_bytes(), original.stat().st_mtime_ns)
    report = check_photos(
        _manifest(archive, "2025 Track Day/Été/wide shot ü.jpg", "2025 Track Day/Été/small.jpg"),
        None,
        project,
    )
    imported = [c for c in report.checks if c.imported]
    assert len(imported) == 1
    copy = project / imported[0].imported
    assert copy.read_bytes() == before[0]
    assert hashlib.sha256(copy.read_bytes()).hexdigest() == imported[0].sha256
    assert (original.read_bytes(), original.stat().st_mtime_ns) == before
    assert sorted(p.name for p in (project / "cover-assets").iterdir()) == [copy.name]
    again = check_photos(_manifest(archive, "2025 Track Day/Été/wide shot ü.jpg"), None, project)
    assert again.checks[0].reused is True


def test_cover_photos_cli(archive, tmp_path, capsys) -> None:
    project = tmp_path / "book"
    project.mkdir()
    (project / "book.yaml").write_text(dump_project(demo_variant()), encoding="utf-8")
    manifest = tmp_path / "approved photos.yaml"
    manifest.write_text(
        "photo_manifest_version: 1\nphotos:\n  - cameras/2025 Track Day/Été/wide shot ü.jpg\n",
        encoding="utf-8",
    )
    assert main(["cover", "photos", str(project), "--manifest", str(manifest)]) == 0
    assert not (project / "cover-assets").exists()
    assert main(["cover", "photos", str(project), "--manifest", str(manifest), "--import"]) == 0
    assert len(list((project / "cover-assets").iterdir())) == 1
    small = str(archive / "2025 Track Day" / "Été" / "small.jpg")
    assert main(["cover", "photos", str(project), "--photo", small]) == 1
    assert main(["cover", "photos", str(project)]) == 2
    assert "folders are never scanned" in capsys.readouterr().err
    assert sys.platform  # Runs on every CI platform.
