import json
import os
import zipfile

from .errors import ExportError, ParseError


def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, ValueError) as exc:
        raise ParseError(str(exc))


def write_json(path, data):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=4, separators=(",", ":"))


def zip_directory(source_dir, zip_path, files=None, compresslevel=1):
    if not os.path.isdir(source_dir):
        raise ExportError("Export directory does not exist: {0}".format(source_dir))
    files = tuple(files) if files is not None else export_files(source_dir)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=compresslevel) as archive:
        for path in files:
            name = os.path.relpath(path, source_dir).replace(os.sep, "/")
            if os.altsep:
                name = name.replace(os.altsep, "/")
            archive.write(path, name)
    return zip_path


def export_files(source_dir):
    return tuple(
        os.path.join(root, filename)
        for root, _, filenames in os.walk(source_dir)
        for filename in filenames
    )


def validate_export_file(path):
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        raise ExportError("Export file is missing or empty: {0}".format(path))
    return path


def zip_entries(path):
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        return ()
    try:
        with zipfile.ZipFile(path, "r") as archive:
            return tuple(archive.infolist())
    except (OSError, zipfile.BadZipFile):
        return ()


def is_safe_zip_name(name):
    if not name or os.path.isabs(name):
        return False
    normalized = name.replace("\\", "/")
    return not any(part == ".." for part in normalized.split("/"))
