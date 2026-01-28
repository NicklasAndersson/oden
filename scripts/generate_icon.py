#!/usr/bin/env python3
"""
Generate Oden app icon from logo image.

Converts the logo to all required sizes and creates .icns for macOS.
Requires: Pillow (pip install Pillow)
"""

import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Installing Pillow...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
    from PIL import Image


def load_source_image(images_dir: Path) -> Image.Image:
    """Load the source logo image."""
    # Try different logo file names
    logo_files = [
        "oden_logo.png",
        "logo.png",
        "logo_small.jpg",
        "oden_1024.png",
    ]

    for filename in logo_files:
        logo_path = images_dir / filename
        if logo_path.exists():
            print(f"Using logo: {logo_path}")
            img = Image.open(logo_path)
            # Convert to RGBA if needed
            if img.mode != "RGBA":
                img = img.convert("RGBA")

            # Crop to square from center if not already square
            width, height = img.size
            if width != height:
                size = min(width, height)
                left = (width - size) // 2
                top = (height - size) // 2
                right = left + size
                bottom = top + size
                img = img.crop((left, top, right, bottom))
                print(f"  Cropped to square: {size}x{size}")

            return img

    raise FileNotFoundError(f"No logo file found in {images_dir}. Please add one of: {', '.join(logo_files)}")


def create_icon_from_logo(source: Image.Image, size: int) -> Image.Image:
    """Resize logo to specified size with high quality."""
    # Use LANCZOS for high-quality downsampling
    resized = source.resize((size, size), Image.Resampling.LANCZOS)
    return resized


def create_iconset(source: Image.Image, output_dir: Path) -> Path:
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
        icon = create_icon_from_logo(source, size)
        icon.save(iconset_dir / filename, "PNG")

    # Also save a large PNG for other uses
    print("  Creating oden_1024.png")
    large_icon = create_icon_from_logo(source, 1024)
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

    # Load source logo
    try:
        source = load_source_image(images_dir)
        print(f"  Source size: {source.size[0]}x{source.size[1]}")
        print()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Create iconset
    iconset_dir = create_iconset(source, images_dir)

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
