#!/usr/bin/env python3
"""
Generate DMG background image for Oden installer.

Creates a stylized background with installation instructions.
Requires: Pillow (pip install Pillow)
"""

import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Installing Pillow...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
    from PIL import Image, ImageDraw, ImageFont


def create_dmg_background(width: int = 600, height: int = 400) -> Image.Image:
    """Create the DMG background image."""
    # Colors
    bg_gradient_top = (26, 26, 46)  # Dark blue
    bg_gradient_bottom = (22, 33, 62)  # Slightly lighter
    text_color = (150, 150, 150)  # Subtle gray
    arrow_color = (79, 195, 247)  # Light blue

    # Create gradient background
    img = Image.new("RGB", (width, height), bg_gradient_top)
    draw = ImageDraw.Draw(img)

    # Draw gradient
    for y in range(height):
        ratio = y / height
        r = int(bg_gradient_top[0] + (bg_gradient_bottom[0] - bg_gradient_top[0]) * ratio)
        g = int(bg_gradient_top[1] + (bg_gradient_bottom[1] - bg_gradient_top[1]) * ratio)
        b = int(bg_gradient_top[2] + (bg_gradient_bottom[2] - bg_gradient_top[2]) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Recreate draw after gradient
    draw = ImageDraw.Draw(img)

    # Load font
    font_size_large = 18
    font_size_small = 14
    font_large = None
    font_small = None

    font_paths = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSDisplay.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]

    for font_path in font_paths:
        try:
            font_large = ImageFont.truetype(font_path, font_size_large)
            font_small = ImageFont.truetype(font_path, font_size_small)
            break
        except Exception:
            continue

    if font_large is None:
        font_large = ImageFont.load_default()
        font_small = font_large

    # Draw subtle decorative elements
    # Top border line
    draw.line([(50, 30), (width - 50, 30)], fill=(40, 40, 60), width=1)
    # Bottom border line
    draw.line([(50, height - 30), (width - 50, height - 30)], fill=(40, 40, 60), width=1)

    # Draw arrow pointing from left to right (app to Applications)
    arrow_y = height // 2 + 40  # Below where icons will be
    arrow_start_x = 200
    arrow_end_x = 400
    arrow_head_size = 15

    # Arrow shaft
    draw.line(
        [(arrow_start_x, arrow_y), (arrow_end_x - arrow_head_size, arrow_y)],
        fill=arrow_color,
        width=3,
    )

    # Arrow head
    draw.polygon(
        [
            (arrow_end_x, arrow_y),
            (arrow_end_x - arrow_head_size, arrow_y - arrow_head_size // 2),
            (arrow_end_x - arrow_head_size, arrow_y + arrow_head_size // 2),
        ],
        fill=arrow_color,
    )

    # Draw instruction text at top
    title_text = "Installera Oden"
    bbox = draw.textbbox((0, 0), title_text, font=font_large)
    text_width = bbox[2] - bbox[0]
    draw.text(
        ((width - text_width) // 2, 50),
        title_text,
        font=font_large,
        fill=text_color,
    )

    # Draw instruction text at bottom
    instruction_text = "Dra Oden till Applications-mappen"
    bbox = draw.textbbox((0, 0), instruction_text, font=font_small)
    text_width = bbox[2] - bbox[0]
    draw.text(
        ((width - text_width) // 2, height - 60),
        instruction_text,
        font=font_small,
        fill=text_color,
    )

    return img


def main():
    """Main entry point."""
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    images_dir = project_root / "images"
    images_dir.mkdir(exist_ok=True)

    print("=== Oden DMG Background Generator ===")
    print()

    output_path = images_dir / "dmg_background.png"
    print(f"Creating {output_path}")

    img = create_dmg_background()
    img.save(output_path, "PNG")

    print(f"Successfully created {output_path}")
    print(f"Size: {img.size[0]}x{img.size[1]}")


if __name__ == "__main__":
    main()
