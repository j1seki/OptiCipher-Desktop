"""Desktop source-format discovery and decoder regression tests."""

from pathlib import Path

from app.widgets import IMAGE_EXTENSIONS, IMAGE_FILTER


def test_picker_filter_contains_google_photos_photo_extensions():
    for extension in (".jpg", ".jpeg", ".heic", ".heif", ".png", ".webp", ".gif", ".avif", ".dng"):
        assert extension in IMAGE_EXTENSIONS
        assert f"*{extension}" in IMAGE_FILTER


def test_folder_import_extension_set_includes_raster_and_raw_formats():
    for extension in (".tif", ".tiff", ".bmp", ".webp", ".heic", ".avif", ".cr3", ".nef", ".arw"):
        assert extension in IMAGE_EXTENSIONS


def test_extension_matching_is_case_insensitive():
    supported = {extension.lower() for extension in IMAGE_EXTENSIONS}
    assert Path("PHOTO.HEIC").suffix.lower() in supported
    assert Path("CAMERA.DNG").suffix.lower() in supported
