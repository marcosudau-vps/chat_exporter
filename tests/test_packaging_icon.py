"""Die Icon-Konvertierung erhaelt die Vorlage und unterstuetzt Windows-Groessen."""

import importlib.util
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("make_icon", ROOT / "packaging" / "make_icon.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_release_icon_has_all_sizes_and_preserves_source(tmp_path):
    source = ROOT / "assets" / "IconChatExporter.png"
    before = source.read_bytes()
    target = module.make_icon(source, tmp_path / "app.ico")
    assert source.read_bytes() == before
    with Image.open(target) as icon:
        assert icon.format == "ICO"
        assert icon.ico.sizes() == {(size, size) for size in module.SIZES}
        for size in module.SIZES:
            frame = icon.ico.getimage((size, size)).convert("RGBA")
            assert frame.getextrema()[3][0] == 0
            assert frame.getextrema()[3][1] > 0


def test_non_square_icon_is_padded_without_distortion(tmp_path):
    source = tmp_path / "wide.png"
    Image.new("RGBA", (256, 128), (10, 20, 30, 255)).save(source)
    target = module.make_icon(source, tmp_path / "wide.ico")
    with Image.open(target) as icon:
        frame = icon.ico.getimage((256, 256)).convert("RGBA")
        assert frame.getbbox() == (0, 64, 256, 192)
        assert frame.getpixel((128, 128)) == (10, 20, 30, 255)
