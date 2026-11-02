# Local Image Batch Compressor

A local Flask app that creates compressed copies of image folders. Original files are never modified or deleted. Images are processed concurrently in separate worker processes.

## Run on Windows

1. Install Python 3.10 or newer and open PowerShell in this project folder.
2. Create and activate a virtual environment, then install dependencies:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

3. Start the app and open the local address:

   ```powershell
   python app.py
   ```

   Visit <http://127.0.0.1:5000>. Use **Browse** for the native folder picker, or paste a folder path and press **Add**. By default, each selected folder is scanned recursively and its output is placed beside it as `folder_compressed`. Existing output names receive a numeric suffix. A custom existing output directory can be selected in the UI.

   The parent-folder option processes each immediate child folder as its own batch. Without it, a selected folder and its full nested structure form one batch.

## Compression behavior

- JPEG: quality 82 by default, optimized and progressive; WEBP: quality 82 and method 6.
- PNG uses lossless optimization unless the optional 256-color quantization checkbox is enabled.
- EXIF/GPS data is stripped by default. Resizing is disabled by default; when enabled, the image is fitted within the chosen maximum width and height without upscaling.
- Unsupported formats and non-image files are skipped, unless copying non-images is enabled. Corrupt image files are reported without stopping the batch.
- If an encoded image would be larger than its source, the original is copied into the output tree instead.
- Optional HEIC/HEIF support: install `python -m pip install pillow-heif`. The app then reads and writes HEIC/HEIF in their original format.

## CLI

```powershell
python compressor.py "C:\photos\trip" "D:\archive\scans" --quality 82 --max-size 1920
```

Optional CLI flags: `--output-dir PATH`, `--keep-metadata`, `--quantize-png`, and `--copy-non-images`.

## Tests

```powershell
python -m unittest discover -s tests -v
```
