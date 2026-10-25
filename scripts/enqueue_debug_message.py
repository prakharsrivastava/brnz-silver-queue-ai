"""Queue an existing bronze blob for local QueueToSilver debugging."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath

from pipeline import blob_url, clients


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("blob_name", help="Blob path, e.g. data/debug.txt")
    parser.add_argument(
        "--allow-pdf",
        action="store_true",
        help="Allow PDF processing, which may incur Document Intelligence charges",
    )
    args = parser.parse_args()

    local_settings = Path(__file__).resolve().parents[1] / "local.settings.json"
    if not local_settings.is_file():
        raise SystemExit("local.settings.json is required; copy the example and configure it locally.")

    values = json.loads(local_settings.read_text(encoding="utf-8")).get("Values", {})
    for name, value in values.items():
        os.environ.setdefault(name, str(value))

    name = PurePosixPath(args.blob_name)
    if name.is_absolute() or not name.as_posix().startswith("data/") or ".." in name.parts:
        raise SystemExit("Use a blob path under bronze/data/, such as data/debug.txt.")

    extension = name.suffix.lower()
    if extension not in {".txt", ".md", ".pdf"}:
        raise SystemExit("Supported extensions are .txt, .md, and .pdf.")
    if extension == ".pdf" and not args.allow_pdf:
        raise SystemExit("PDF analysis may incur charges; use --allow-pdf only if intended.")

    blob_service, queue = clients()
    blob_name = name.as_posix()
    source = blob_service.get_blob_client("bronze", blob_name)
    properties = source.get_blob_properties()
    message = {
        "document_id": name.stem,
        "document_url": blob_url(blob_service, "bronze", blob_name),
        "container": "bronze",
        "blob_name": blob_name,
        "etag": str(properties.etag),
        "metadata": properties.metadata or {},
    }
    queue.send_message(json.dumps(message))
    print(f"Queued {blob_name} for local QueueToSilver debugging.")


if __name__ == "__main__":
    main()
