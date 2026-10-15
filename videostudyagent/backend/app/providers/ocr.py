"""Local Tesseract TSV adapter. No downloads or cloud fallback."""

import csv
import io
import math
import re
import shutil
import subprocess

from app.core.errors import StudyError


class TesseractOCR:
    def __init__(self, binary="tesseract", language="chi_sim+eng", timeout=30):
        self.binary, self.language, self.timeout = binary, language, timeout
        self._version = None

    @property
    def version(self):
        if self._version:
            return self._version
        binary = shutil.which(self.binary)
        if not binary:
            raise StudyError("OCR_UNAVAILABLE", "本地 OCR 未安装或未配置。", 503, True)
        try:
            result = subprocess.run(
                [binary, "--version"],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=min(5, self.timeout),
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise StudyError("OCR_TIMEOUT", "OCR 版本检测超时。", 422, True) from None
        match = re.search(rb"tesseract\s+v?([0-9]+(?:\.[0-9]+)+)", result.stdout)
        if result.returncode or not match:
            raise StudyError("OCR_FAILED", "无法识别本地 OCR 版本。", 422, True)
        self._version = "tesseract-" + match.group(1).decode("ascii") + "/tsv-v1"
        return self._version

    def recognize(self, path):
        binary = shutil.which(self.binary)
        if not binary:
            raise StudyError("OCR_UNAVAILABLE", "本地 OCR 未安装或未配置。", 503, True)
        try:
            result = subprocess.run(
                [binary, str(path), "stdout", "-l", self.language, "tsv"],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise StudyError("OCR_TIMEOUT", "画面文字识别超时。", 422, True) from None
        if result.returncode:
            raise StudyError("OCR_FAILED", "画面文字识别失败，请检查语言包。", 422, True)
        words = []
        groups = {}
        try:
            for index, row in enumerate(
                csv.DictReader(io.StringIO(result.stdout.decode("utf-8")), delimiter="\t")
            ):
                if row["level"] != "5" or not row["text"].strip():
                    continue
                bbox = tuple(int(row[key]) for key in ("left", "top", "width", "height"))
                confidence = float(row["conf"])
                key = tuple(
                    row.get(field, str(index))
                    for field in ("page_num", "block_num", "par_num", "line_num")
                )
                groups.setdefault(key, []).append(
                    (
                        row["text"],
                        bbox,
                        confidence
                        if math.isfinite(confidence) and 0 <= confidence <= 100
                        else None,
                    )
                )
            for line in groups.values():
                left = min(w[1][0] for w in line)
                top = min(w[1][1] for w in line)
                right = max(w[1][0] + w[1][2] for w in line)
                bottom = max(w[1][1] + w[1][3] for w in line)
                confidence = [w[2] for w in line if w[2] is not None]
                words.append(
                    dict(
                        raw_text=" ".join(w[0] for w in line),
                        bbox=(left, top, right - left, bottom - top),
                        confidence=sum(confidence) / len(confidence) if confidence else None,
                    )
                )
        except (KeyError, ValueError, UnicodeError):
            raise StudyError("OCR_INVALID_OUTPUT", "OCR 返回格式无效。", 422, True) from None
        return words
