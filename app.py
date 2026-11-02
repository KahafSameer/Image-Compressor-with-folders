"""Local Flask interface for batch image compression."""

from __future__ import annotations

import os
import sys
import threading
import uuid
from typing import Any

from flask import Flask, jsonify, render_template, request

from compressor import _unique_output, process_folder

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024

jobs: dict[str, dict[str, Any]] = {}
jobs_lock = threading.Lock()


def _expand_folders(folders: list[str], process_subfolders: bool) -> list[str]:
    expanded: list[str] = []
    for folder in folders:
        path = os.path.abspath(os.path.expanduser(folder.strip()))
        if not os.path.isdir(path):
            raise ValueError(f"Folder does not exist: {folder}")
        if process_subfolders:
            try:
                children = sorted(
                    os.path.join(path, entry.name)
                    for entry in os.scandir(path)
                    if entry.is_dir(follow_symlinks=False)
                )
            except OSError as error:
                raise ValueError(f"Cannot scan folder {path}: {error}") from error
            expanded.extend(children)
        else:
            expanded.append(path)
    return list(dict.fromkeys(expanded))


def _run_job(job_id: str, folders: list[str], options: dict[str, Any]) -> None:
    reports = []
    try:
        for index, folder in enumerate(folders):
            output = _unique_output(folder, options["output_dir"])
            with jobs_lock:
                jobs[job_id]["current_folder"] = folder
                jobs[job_id]["current_output"] = output
                jobs[job_id]["folder_index"] = index
                jobs[job_id]["file_done"] = 0
                jobs[job_id]["file_total"] = 0
                jobs[job_id]["current_file"] = ""

            def progress(done: int, total: int, current: str) -> None:
                with jobs_lock:
                    jobs[job_id]["file_done"] = done
                    jobs[job_id]["file_total"] = total
                    jobs[job_id]["current_file"] = current

            report = process_folder(
                folder,
                output,
                quality=options["quality"],
                max_size=options["max_size"],
                strip_metadata=options["strip_metadata"],
                quantize_png=options["quantize_png"],
                copy_non_images=options["copy_non_images"],
                progress_callback=progress,
            )
            reports.append(report)
            with jobs_lock:
                jobs[job_id]["reports"] = reports.copy()
                jobs[job_id]["folders_done"] = index + 1
        with jobs_lock:
            jobs[job_id]["status"] = "complete"
    except Exception as error:
        with jobs_lock:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = str(error)
            jobs[job_id]["reports"] = reports


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/browse")
def browse():
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(parent=root, title="Select a folder")
        root.destroy()
        return jsonify({"path": selected})
    except Exception as error:
        return jsonify({"error": f"Folder picker could not be opened: {error}"}), 500


@app.post("/start")
def start():
    data = request.get_json(silent=True) or {}
    folders = data.get("folders")
    if not isinstance(folders, list) or not folders or not all(
        isinstance(folder, str) and folder.strip() for folder in folders
    ):
        return jsonify({"error": "Add at least one valid folder path."}), 400
    try:
        folders = _expand_folders(folders, bool(data.get("process_subfolders")))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    if not folders:
        return jsonify({"error": "The selected parent folder has no subfolders."}), 400

    quality = data.get("quality", 82)
    max_size = data.get("max_size")
    if isinstance(quality, bool) or not isinstance(quality, int) or not 60 <= quality <= 95:
        return jsonify({"error": "Quality must be between 60 and 95."}), 400
    if max_size is not None and (
        isinstance(max_size, bool) or not isinstance(max_size, int) or max_size <= 0
    ):
        return jsonify({"error": "Maximum dimensions must be a positive number."}), 400
    output_dir = data.get("output_dir") or None
    if output_dir is not None and not isinstance(output_dir, str):
        return jsonify({"error": "Output directory must be a folder path."}), 400
    if output_dir:
        output_dir = os.path.abspath(os.path.expanduser(output_dir.strip()))
        if not os.path.isdir(output_dir):
            return jsonify({"error": "The custom output directory does not exist."}), 400

    job_id = uuid.uuid4().hex
    options = {
        "quality": quality,
        "max_size": max_size,
        "output_dir": output_dir,
        "strip_metadata": bool(data.get("strip_metadata", True)),
        "quantize_png": bool(data.get("quantize_png", False)),
        "copy_non_images": bool(data.get("copy_non_images", False)),
    }
    with jobs_lock:
        jobs[job_id] = {
            "status": "running",
            "folders": folders,
            "folder_total": len(folders),
            "folders_done": 0,
            "folder_index": 0,
            "file_done": 0,
            "file_total": 0,
            "reports": [],
        }
    threading.Thread(
        target=_run_job, args=(job_id, folders, options), daemon=True
    ).start()
    return jsonify({"job_id": job_id})


@app.get("/status/<job_id>")
def status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return jsonify({"error": "Job not found."}), 404
        result = dict(job)
    return jsonify(result)


@app.post("/open/<job_id>/<int:folder_index>")
def open_output(job_id: str, folder_index: int):
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None or folder_index < 0 or folder_index >= len(job["reports"]):
            return jsonify({"error": "Output folder is not available yet."}), 404
        output = job["reports"][folder_index]["output"]
    try:
        if os.name == "nt":
            os.startfile(output)  # type: ignore[attr-defined]
        else:
            import subprocess

            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", output])
        return jsonify({"ok": True})
    except OSError as error:
        return jsonify({"error": f"Could not open output folder: {error}"}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, threaded=True)
