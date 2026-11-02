"""Reusable image compression logic and command-line interface."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pass


EXTENSION_FORMATS = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".heic": "HEIF",
    ".heif": "HEIF",
}


def _io_path(path: str | os.PathLike[str]) -> str:
    """Add the Windows extended-length prefix for filesystem operations."""
    value = os.path.abspath(os.fspath(path))
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        if value.startswith("\\\\"):
            return "\\\\?\\UNC\\" + value[2:]
        return "\\\\?\\" + value
    return value


def _copy_file(source: str, destination: str) -> None:
    os.makedirs(_io_path(os.path.dirname(destination)), exist_ok=True)
    shutil.copy2(_io_path(source), _io_path(destination))


def compress_file(
    source: str,
    destination: str,
    quality: int = 82,
    max_size: int | None = None,
    strip_metadata: bool = True,
    quantize_png: bool = False,
) -> dict[str, Any]:
    """Compress one supported image; retain the original if output is larger."""
    source_path = Path(source)
    destination_path = Path(destination)
    original_size = os.path.getsize(_io_path(source))
    image_format = EXTENSION_FORMATS.get(source_path.suffix.lower())
    if image_format is None:
        raise ValueError(f"Unsupported image extension: {source_path.suffix}")

    try:
        with Image.open(_io_path(source)) as opened:
            if opened.format != image_format:
                raise ValueError(
                    f"Image content is {opened.format or 'unknown'}, "
                    f"but extension indicates {image_format}"
                )
            if getattr(opened, "n_frames", 1) > 1:
                raise ValueError("Animated images are not supported")
            image = ImageOps.exif_transpose(opened)
            image.load()

            if max_size:
                image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

            save_image = image.copy()
            if image_format == "JPEG" and save_image.mode not in ("RGB", "L"):
                if save_image.mode in ("RGBA", "LA") or "transparency" in save_image.info:
                    rgba = save_image.convert("RGBA")
                    background = Image.new("RGB", save_image.size, "white")
                    background.paste(rgba, mask=rgba.getchannel("A"))
                    save_image = background
                else:
                    save_image = save_image.convert("RGB")

            if image_format == "PNG" and quantize_png and save_image.mode in (
                "RGB",
                "RGBA",
            ):
                save_image = save_image.quantize(
                    colors=256,
                    method=(
                        Image.Quantize.FASTOCTREE
                        if save_image.mode == "RGBA"
                        else Image.Quantize.MEDIANCUT
                    ),
                    dither=Image.Dither.FLOYDSTEINBERG,
                )

            options: dict[str, Any] = {}
            if image_format == "JPEG":
                options.update(quality=quality, optimize=True, progressive=True)
            elif image_format == "PNG":
                options["optimize"] = True
            elif image_format == "WEBP":
                options.update(quality=quality, method=6)
            elif image_format == "HEIF":
                options["quality"] = quality
                if image_format == "HEIF":
                    options.pop("method")

            if not strip_metadata:
                exif = image.getexif()
                if exif:
                    options["exif"] = exif.tobytes()

            os.makedirs(_io_path(os.fspath(destination_path.parent)), exist_ok=True)
            save_image.save(_io_path(destination), format=image_format, **options)

        compressed_size = os.path.getsize(_io_path(destination))
        if compressed_size > original_size:
            _copy_file(source, destination)
            compressed_size = original_size
            used_original = True
        else:
            used_original = False

        return {
            "source": source,
            "destination": destination,
            "original_size": original_size,
            "new_size": compressed_size,
            "used_original": used_original,
            "format": image_format,
        }
    except Exception:
        try:
            if os.path.exists(_io_path(destination)):
                os.remove(_io_path(destination))
        except OSError:
            pass
        raise


def _scan_folder(folder: str, output_folder: str) -> tuple[list[tuple[str, str]], list[dict[str, str]]]:
    files: list[tuple[str, str]] = []
    failures: list[dict[str, str]] = []
    output_abs = os.path.normcase(os.path.abspath(output_folder))

    def scan_error(error: OSError) -> None:
        failures.append(
            {"file": error.filename or folder, "error": str(error)}
        )

    for root, dirs, filenames in os.walk(
        _io_path(folder), topdown=True, onerror=scan_error
    ):
        dirs[:] = [
            name
            for name in dirs
            if os.path.normcase(os.path.abspath(os.path.join(root, name))) != output_abs
        ]
        relative_root = os.path.relpath(root, _io_path(folder))
        for name in filenames:
            source = os.path.join(root, name)
            relative = name if relative_root == "." else os.path.join(relative_root, name)
            files.append((source, os.path.join(output_folder, relative)))
    return files, failures


def _is_image(source: str) -> bool:
    expected = EXTENSION_FORMATS.get(Path(source).suffix.lower())
    if expected is None:
        return False
    try:
        with Image.open(_io_path(source)) as image:
            return image.format == expected
    except Exception:
        # A corrupt file with an image extension is still reported as a failed image.
        return True


def _worker(args: tuple[str, str, dict[str, Any]]) -> dict[str, Any]:
    source, destination, options = args
    if not _is_image(source):
        if options["copy_non_images"]:
            _copy_file(source, destination)
            size = os.path.getsize(_io_path(source))
            return {
                "source": source,
                "destination": destination,
                "original_size": size,
                "new_size": size,
                "copied_non_image": True,
            }
        return {
            "source": source,
            "destination": destination,
            "original_size": os.path.getsize(_io_path(source)),
            "new_size": 0,
            "skipped": True,
        }

    return compress_file(
        source,
        destination,
        quality=options["quality"],
        max_size=options["max_size"],
        strip_metadata=options["strip_metadata"],
        quantize_png=options["quantize_png"],
    )


def process_folder(
    folder: str,
    output_folder: str,
    *,
    quality: int = 82,
    max_size: int | None = None,
    strip_metadata: bool = True,
    quantize_png: bool = False,
    copy_non_images: bool = False,
    workers: int | None = None,
    progress_callback: Any = None,
) -> dict[str, Any]:
    """Process a folder tree into a separate destination, without touching sources."""
    folder = os.path.abspath(folder)
    output_folder = os.path.abspath(output_folder)
    if not os.path.isdir(_io_path(folder)):
        raise NotADirectoryError(folder)

    files, scan_failures = _scan_folder(folder, output_folder)
    os.makedirs(_io_path(output_folder), exist_ok=False)
    options = {
        "quality": quality,
        "max_size": max_size,
        "strip_metadata": strip_metadata,
        "quantize_png": quantize_png,
        "copy_non_images": copy_non_images,
    }

    results: list[dict[str, Any]] = []
    failures = list(scan_failures)
    original_total = new_total = image_count = 0
    with ProcessPoolExecutor(max_workers=workers) as executor:
        future_sources = {
            executor.submit(_worker, (source, destination, options)): source
            for source, destination in files
        }
        completed = 0
        for future in as_completed(future_sources):
            source = future_sources[future]
            completed += 1
            try:
                result = future.result()
                results.append(result)
                if not result.get("skipped"):
                    original_total += result["original_size"]
                    new_total += result["new_size"]
                if not result.get("skipped") and not result.get("copied_non_image"):
                    image_count += 1
            except Exception as error:
                failures.append({"file": source, "error": str(error)})
            if progress_callback:
                progress_callback(completed, len(files), source)

    return {
        "source": folder,
        "output": output_folder,
        "files": len(files),
        "images": image_count,
        "original_size": original_total,
        "new_size": new_total,
        "saved_percent": (
            round((original_total - new_total) * 100 / original_total, 1)
            if original_total
            else 0
        ),
        "failures": failures,
    }


def _unique_output(folder: str, output_root: str | None) -> str:
    source = Path(folder)
    base = source.name + "_compressed"
    parent = Path(output_root) if output_root else source.parent
    candidate = parent / base
    suffix = 2
    while os.path.exists(_io_path(candidate)):
        candidate = parent / f"{base}_{suffix}"
        suffix += 1
    return str(candidate)


def compress_folders(
    folders: list[str],
    *,
    quality: int = 82,
    max_size: int | None = None,
    output_dir: str | None = None,
    strip_metadata: bool = True,
    quantize_png: bool = False,
    copy_non_images: bool = False,
    workers: int | None = None,
) -> list[dict[str, Any]]:
    reports = []
    for folder in folders:
        output = _unique_output(folder, output_dir)
        reports.append(
            process_folder(
                folder,
                output,
                quality=quality,
                max_size=max_size,
                strip_metadata=strip_metadata,
                quantize_png=quantize_png,
                copy_non_images=copy_non_images,
                workers=workers,
            )
        )
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch-compress image folders.")
    parser.add_argument("folders", nargs="+", help="Folders to compress")
    parser.add_argument("--quality", type=int, default=82)
    parser.add_argument("--max-size", type=int, default=None, metavar="PIXELS")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--keep-metadata", action="store_true")
    parser.add_argument("--quantize-png", action="store_true")
    parser.add_argument("--copy-non-images", action="store_true")
    args = parser.parse_args()

    if not 60 <= args.quality <= 95:
        parser.error("--quality must be between 60 and 95")
    if args.max_size is not None and args.max_size <= 0:
        parser.error("--max-size must be greater than zero")

    try:
        reports = compress_folders(
            args.folders,
            quality=args.quality,
            max_size=args.max_size,
            output_dir=args.output_dir,
            strip_metadata=not args.keep_metadata,
            quantize_png=args.quantize_png,
            copy_non_images=args.copy_non_images,
        )
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    for report in reports:
        print(
            f"{report['source']} -> {report['output']}: "
            f"{report['images']} images, {report['original_size']} -> "
            f"{report['new_size']} bytes ({report['saved_percent']}% saved)"
        )
        for failure in report["failures"]:
            print(f"  FAILED {failure['file']}: {failure['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
