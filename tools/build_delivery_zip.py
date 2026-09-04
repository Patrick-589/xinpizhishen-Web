from __future__ import annotations

import argparse
import shutil
import time
import zipfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a Unicode-safe Windows delivery ZIP.")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--archive-root",
        default=None,
        help="ASCII root directory used inside the archive (defaults to source name).",
    )
    parser.add_argument(
        "--include-prefix",
        action="append",
        default=[],
        help="Only include this source-relative path prefix; may be repeated.",
    )
    parser.add_argument(
        "--exclude-prefix",
        action="append",
        default=[],
        help="Exclude this source-relative path prefix; may be repeated.",
    )
    args = parser.parse_args()

    source = args.source.resolve()
    output = args.output.resolve()
    if not source.is_dir():
        raise SystemExit(f"Source directory not found: {source}")
    if output.exists():
        raise SystemExit(f"Output already exists: {output}")

    archive_root = args.archive_root or source.name
    if not archive_root or Path(archive_root).name != archive_root:
        raise SystemExit("--archive-root must be a single directory name")

    def normalized_parts(value: str) -> tuple[str, ...]:
        return tuple(part.casefold() for part in Path(value.replace("\\", "/")).parts if part not in {"", "."})

    includes = [normalized_parts(value) for value in args.include_prefix]
    excludes = [normalized_parts(value) for value in args.exclude_prefix]

    def starts_with(parts: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
        return parts[: len(prefix)] == prefix

    def selected(path: Path) -> bool:
        parts = tuple(part.casefold() for part in path.relative_to(source).parts)
        if includes and not any(starts_with(parts, prefix) for prefix in includes):
            return False
        return not any(starts_with(parts, prefix) for prefix in excludes)

    files = sorted(
        (path for path in source.rglob("*") if path.is_file() and selected(path)),
        key=lambda path: path.relative_to(source).as_posix().casefold(),
    )
    if not files:
        raise SystemExit("No files matched the requested include/exclude filters")
    total = sum(path.stat().st_size for path in files)
    started = time.monotonic()
    completed = 0
    next_report = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output.with_name(f".{output.name}.tmp")
    if temp_output.exists():
        temp_output.unlink()
    with zipfile.ZipFile(
        temp_output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=1,
        allowZip64=True,
        strict_timestamps=False,
    ) as archive:
        directories = {f"{archive_root}/"}
        for path in files:
            relative_parent = path.relative_to(source).parent
            while relative_parent != Path("."):
                directories.add(f"{archive_root}/{relative_parent.as_posix()}/")
                relative_parent = relative_parent.parent
        for directory in sorted(directories, key=lambda value: (value.count("/"), value.casefold())):
            info = zipfile.ZipInfo(directory)
            info.external_attr = 0o40775 << 16
            archive.writestr(info, b"")

        for file_number, path in enumerate(files, start=1):
            relative = path.relative_to(source).as_posix()
            archive.write(path, f"{archive_root}/{relative}")
            completed += path.stat().st_size
            percent = int(completed * 100 / total) if total else 100
            if percent >= next_report:
                elapsed = time.monotonic() - started
                print(
                    f"progress={percent}% files={file_number}/{len(files)} "
                    f"source_gb={completed / 1024**3:.2f} elapsed_s={elapsed:.0f}",
                    flush=True,
                )
                next_report = percent + 5

    shutil.move(str(temp_output), str(output))
    print(f"output={output}", flush=True)
    print(f"bytes={output.stat().st_size}", flush=True)


if __name__ == "__main__":
    main()
