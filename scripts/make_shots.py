"""Render terminal transcripts as PNG screenshots for the report.

The report needs reproducible evidence of compiling and running the
program; instead of photographing a screen, the same text that the
commands printed is drawn with the CJK mono font, so the figures stay
sharp at print size.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_INDEX = 7  # Noto Sans Mono CJK SC inside the TTC collection
FONT_SIZE = 15
LINE_HEIGHT = 24
PADDING = 18
TITLE_HEIGHT = 34
BACKGROUND = (27, 27, 31)
TITLE_BACKGROUND = (48, 48, 56)
FOREGROUND = (230, 230, 230)
TITLE_FOREGROUND = (196, 196, 206)


def _compact(text: str) -> list[str]:
    """Collapse runs of blank lines so figures do not waste space."""
    lines: list[str] = []
    for line in text.splitlines():
        if not line.strip() and lines and not lines[-1].strip():
            continue
        lines.append(line)
    return lines


def _split(lines: list[str], parts: int) -> list[list[str]]:
    """Split a transcript into roughly equal parts."""
    size = (len(lines) + parts - 1) // parts
    return [lines[i:i + size] for i in range(0, len(lines), size)]


def render(text: str, title: str, output: Path) -> None:
    """Draw one block of text into a terminal-like image."""
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE, index=FONT_INDEX)
    title_font = ImageFont.truetype(FONT_PATH, 13, index=FONT_INDEX)
    lines = text.rstrip("\n").split("\n")
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    widths = [probe.textlength(line, font=font) for line in lines] or [0]
    width = int(max(widths)) + PADDING * 2
    height = TITLE_HEIGHT + LINE_HEIGHT * len(lines) + PADDING * 2
    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, width, TITLE_HEIGHT], fill=TITLE_BACKGROUND)
    draw.text((PADDING, 9), title, font=title_font, fill=TITLE_FOREGROUND)
    offset = TITLE_HEIGHT + PADDING
    for line in lines:
        draw.text((PADDING, offset), line, font=font, fill=FOREGROUND)
        offset += LINE_HEIGHT
    image.save(output)


def head(path: Path, count: int) -> str:
    """First ``count`` lines of a text file."""
    return "\n".join(path.read_text(encoding="utf-8").splitlines()[:count])


def tail(path: Path, count: int) -> str:
    """Last ``count`` lines of a text file."""
    return "\n".join(path.read_text(encoding="utf-8").splitlines()[-count:])


def main() -> None:
    """Generate the four report figures."""
    root = Path(__file__).resolve().parent.parent
    docs = root / "docs"
    shots = docs / "shots"
    shots.mkdir(exist_ok=True)
    demo_lines = _compact(
        (docs / "运行结果.txt").read_text(encoding="utf-8")
    )
    chunks = _split(demo_lines, 3)
    for index, chunk in enumerate(chunks, start=1):
        render(
            "\n".join(chunk),
            f"python3 scripts/demo.py（第 {index} 段）",
            shots / f"运行演示{index}.png",
        )
    render(
        tail(docs / "测试结果.txt", 22),
        "python3 -m pytest tests -v",
        shots / "单元测试.png",
    )
    render(
        (docs / "风格检查.txt").read_text(encoding="utf-8"),
        "python3 -m pylint hotel_booking --rcfile=pylintrc",
        shots / "风格检查.png",
    )
    render(
        head(docs / "git日志.txt", 18),
        "git log --oneline --stat",
        shots / "git日志.png",
    )
    for name in ("运行演示1", "运行演示2", "运行演示3",
                 "单元测试", "风格检查", "git日志"):
        print(shots / f"{name}.png")


if __name__ == "__main__":
    main()
