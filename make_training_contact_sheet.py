"""Create evenly sampled contact sheets for the captured training frames."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def evenly_spaced(items: list[Path], count: int) -> list[Path]:
    if len(items) <= count:
        return items
    return [items[round(i * (len(items) - 1) / (count - 1))] for i in range(count)]


def make_sheet(source: Path, output: Path, count: int, columns: int) -> None:
    files = sorted(source.rglob("*.jpg"))
    selected = evenly_spaced(files, count)
    if not selected:
        raise SystemExit(f"No JPEG files found under {source}")

    thumb_size = (240, 240)
    label_height = 24
    rows = (len(selected) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * thumb_size[0], rows * (thumb_size[1] + label_height)), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    for index, path in enumerate(selected):
        image = Image.open(path).convert("RGB")
        image.thumbnail(thumb_size, Image.Resampling.LANCZOS)
        x = (index % columns) * thumb_size[0]
        y = (index // columns) * (thumb_size[1] + label_height)
        sheet.paste(image, (x + (thumb_size[0] - image.width) // 2, y))
        relative = path.relative_to(source)
        draw.text((x + 4, y + thumb_size[1] + 4), str(relative), fill="black", font=font)

    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=92)
    print(f"Created {output} from {len(selected)} of {len(files)} frames")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--count", type=int, default=36)
    parser.add_argument("--columns", type=int, default=6)
    args = parser.parse_args()
    make_sheet(args.source, args.output, args.count, args.columns)


if __name__ == "__main__":
    main()
