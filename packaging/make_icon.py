"""Windows-Icon aus der unveraenderten PNG-Vorlage erzeugen (nur beim Bauen)."""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SIZES = (16, 24, 32, 48, 64, 128, 256)


def make_icon(source: Path, target: Path) -> Path:
    with Image.open(source) as image:
        image = image.convert("RGBA")
        side = max(image.size)
        square = Image.new("RGBA", (side, side))
        square.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
        square.save(target, format="ICO", sizes=[(size, size) for size in SIZES])
    return target


if __name__ == "__main__":
    make_icon(ROOT / "assets" / "IconChatExporter.png", ROOT / "assets" / "IconChatExporter.ico")
