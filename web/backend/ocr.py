from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import Settings, WEB_ROOT


class LocalOCRError(Exception):
    pass


@dataclass(frozen=True)
class OCRPage:
    page: int
    text: str


def normalize_ocr_text(value: str) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\t\u00a0]+", " ", text)
    cjk = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    punctuation = r"，。；：！？、（）【】《》“”‘’"
    text = re.sub(rf"(?<=[{cjk}]) +(?=[{cjk}{punctuation}0-9A-Za-z])", "", text)
    text = re.sub(rf"(?<=[0-9A-Za-z]) +(?=[{cjk}{punctuation}0-9])", "", text)
    text = re.sub(rf"(?<=[{punctuation}]) +(?=[{cjk}0-9A-Za-z])", "", text)
    text = re.sub(r" +", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip()


class LocalOCRService:
    engine_name = "windows-media-ocr"

    def __init__(self, settings: Settings):
        self.enabled = settings.local_ocr_enabled
        self.language = settings.ocr_language
        self.dpi = settings.ocr_dpi
        self.max_pages = settings.ocr_max_pages
        self.script_path = WEB_ROOT / "scripts" / "windows-ocr.ps1"
        self.powershell_path = self._find_powershell()
        self.pdftoppm_path = self._find_pdftoppm(settings.pdftoppm_path)

    @staticmethod
    def _find_powershell() -> Path | None:
        system_root = os.getenv("SystemRoot", r"C:\Windows")
        candidates = [
            Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe",
        ]
        discovered = shutil.which("powershell.exe") or shutil.which("powershell")
        if discovered:
            candidates.append(Path(discovered))
        return next((path.resolve() for path in candidates if path.is_file()), None)

    @staticmethod
    def _find_pdftoppm(configured_path: str) -> Path | None:
        candidates: list[Path] = []
        if configured_path.strip():
            candidates.append(Path(configured_path).expanduser())
        executable = Path(sys.executable).resolve()
        for parent in executable.parents:
            candidates.append(parent / "native" / "poppler" / "Library" / "bin" / "pdftoppm.exe")
        discovered = shutil.which("pdftoppm.exe") or shutil.which("pdftoppm")
        if discovered:
            candidates.append(Path(discovered))
        return next((path.resolve() for path in candidates if path.is_file()), None)

    def status(self) -> dict[str, object]:
        if not self.enabled:
            return {
                "enabled": False,
                "available": False,
                "engine": self.engine_name,
                "language": self.language,
                "message": "本地 OCR 已通过配置关闭。",
            }
        missing = []
        if os.name != "nt":
            missing.append("Windows 11")
        if not self.script_path.is_file():
            missing.append("Windows OCR 脚本")
        if not self.powershell_path:
            missing.append("Windows PowerShell")
        if not self.pdftoppm_path:
            missing.append("PDF 本地渲染组件")
        return {
            "enabled": True,
            "available": not missing,
            "engine": self.engine_name,
            "language": self.language,
            "message": "本地 OCR 可用。" if not missing else "缺少：" + "、".join(missing),
        }

    def recognize_pdf_pages(self, content: bytes, pages: list[int]) -> list[OCRPage]:
        requested = sorted(set(page for page in pages if page > 0))
        if not requested:
            return []
        status = self.status()
        if not status["available"]:
            raise LocalOCRError(str(status["message"]))
        if len(requested) > self.max_pages:
            raise LocalOCRError(
                f"扫描页共 {len(requested)} 页，超过本地 OCR 上限 {self.max_pages} 页。"
            )
        with tempfile.TemporaryDirectory(prefix="xzs-ocr-") as temporary:
            temporary_path = Path(temporary)
            pdf_path = temporary_path / "source.pdf"
            pdf_path.write_bytes(content)
            results = []
            for page in requested:
                image_path = self._render_page(pdf_path, temporary_path, page)
                text = self._recognize_image(image_path)
                # A single rendered page may be intentionally blank; the parser
                # still rejects the document if no page yields usable text.
                results.append(OCRPage(page=page, text=text))
            return results

    def _render_page(self, pdf_path: Path, temporary_path: Path, page: int) -> Path:
        prefix = temporary_path / f"page-{page}"
        command = [
            str(self.pdftoppm_path),
            "-f", str(page),
            "-l", str(page),
            "-r", str(self.dpi),
            "-png",
            "-singlefile",
            str(pdf_path),
            str(prefix),
        ]
        completed = self._run(command, timeout=120)
        image_path = prefix.with_suffix(".png")
        if completed.returncode != 0 or not image_path.is_file():
            detail = completed.stderr.strip() or "PDF 页面渲染失败。"
            raise LocalOCRError(detail[:300])
        return image_path

    def _recognize_image(self, image_path: Path) -> str:
        command = [
            str(self.powershell_path),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy", "Bypass",
            "-File", str(self.script_path),
            "-ImagePath", str(image_path),
            "-Language", self.language,
        ]
        completed = self._run(command, timeout=120)
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "Windows OCR 识别失败。"
            raise LocalOCRError(detail[:300])
        return normalize_ocr_text(completed.stdout)

    @staticmethod
    def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            return subprocess.run(
                command,
                capture_output=True,
                check=False,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=creationflags,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise LocalOCRError(f"本地 OCR 执行失败：{error}") from error
