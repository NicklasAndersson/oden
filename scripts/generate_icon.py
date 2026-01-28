#!/usr/bin/env python3
"""
Generate Oden app icon as PNG files and create .icns for macOS.

Creates a stylized "Ö" letter with Nordic colors (blue/yellow).
Requires: Pillow (pip install Pillow)
"""

import math
import os
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Installing Pillow...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
    from PIL import Image, ImageDraw, ImageFont


def create_oden_icon(size: int) -> Image.Image:
    """Create the Oden icon at the specified size."""
    # Colors - Nordic blue and gold
    bg_color = (26, 26, 46)  # Dark blue (#1a1a2e)
    primary_color = (79, 195, 247)  # Light blue (#4fc3f7)
    accent_color = (255, 193, 7)  # Gold (#ffc107)

    # Create image with rounded corners effect via circle mask
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw rounded rectangle background
    corner_radius = size // 5
    draw.rounded_rectangle(
        [(0, 0), (size - 1, size - 1)],
        radius=corner_radius,
        fill=bg_color,
    )

    # Draw the "Ö" letter
    font_size = int(size * 0.65)

    # Try to use a nice font, fall back to default
    font = None
    font_paths = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSDisplay.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                font = ImageFont.truetype(font_path, font_size)
                break
            except Exception:
                continue

    if font is None:
        # Fall back to default font (smaller)
        font = ImageFont.load_default()
        font_size = size // 2

    # Draw "Ö" centered
    text = "Ö"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    x = (size - text_width) // 2
    y = (size - text_height) // 2 - bbox[1]  # Adjust for font baseline

    # Draw text shadow/glow
    for offset in range(3, 0, -1):
        alpha = 80 - offset * 20
        shadow_color = (*accent_color[:3], alpha)
        draw.text((x + offset, y + offset), text, font=font, fill=shadow_color)

    # Draw main text
    draw.text((x, y), text, font=font, fill=primary_color)

    # Draw a subtle shield/rune decoration
    shield_margin = size // 10
    shield_top = size // 6
    shield_points = [
        (size // 2, shield_top),  # Top center
        (size - shield_margin, shield_top + size // 8),  # Top right
        (size - shield_margin, size - shield_margin - size // 6),  # Bottom right
        (size // 2, size - shield_margin),  # Bottom center (point)
        (shield_margin, size - shield_margin - size // 6),  # Bottom left
        (shield_margin, shield_top + size // 8),  # Top left
    ]

    # Draw shield outline
    outline_width = max(1, size // 64)
    draw.line(
        shield_points + [shield_points[0]],
        fill=(*accent_color[:3], 60),
        width=outline_width,
    )

    return img


def create_iconset(output_dir: Path) -> None:
    """Create all required icon sizes for macOS iconset."""
    sizes = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]

    iconset_dir = output_dir / "oden.iconset"
    iconset_dir.mkdir(parents=True, exist_ok=True)

    print(f"Creating iconset in {iconset_dir}")

    for size, filename in sizes:
        print(f"  Creating {filename} ({size}x{size})")
        icon = create_oden_icon(size)
        icon.save(iconset_dir / filename, "PNG")

    # Also save a large PNG for other uses
    print("  Creating oden_1024.png")
    large_icon = create_oden_icon(1024)
    large_icon.save(output_dir / "oden_1024.png", "PNG")

    return iconset_dir


def create_icns(iconset_dir: Path, output_path: Path) -> bool:
    """Convert iconset to .icns using iconutil (macOS only)."""
    if sys.platform != "darwin":
        print("Note: .icns creation requires macOS. Skipping.")
        return False

    try:
        print(f"Creating {output_path}")
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(output_path)],
            check=True,
        )
        print(f"Successfully created {output_path}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error creating .icns: {e}")
        return False
    except FileNotFoundError:
        print("iconutil not found. Make sure Xcode command line tools are installed.")
        return False


def main():
    """Main entry point."""
    # Determine output directory
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    images_dir = project_root / "images"
    images_dir.mkdir(exist_ok=True)

    print("=== Oden Icon Generator ===")
    print()

    # Create iconset
    iconset_dir = create_iconset(images_dir)

    # Create .icns file
    icns_path = images_dir / "oden.icns"
    create_icns(iconset_dir, icns_path)

    print()
    print("Done!")
    print(f"  Iconset: {iconset_dir}")
    print(f"  ICNS: {icns_path}")
    print(f"  PNG: {images_dir / 'oden_1024.png'}")


if __name__ == "__main__":
    main()
