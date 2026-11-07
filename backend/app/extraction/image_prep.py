"""Phone-photo preparation: find the sheet of paper, undo perspective, clean up, OCR.

Deterministic OpenCV/Tesseract. The corrected image is also what the vision model
sees, so OCR line boxes and the model's view share one coordinate system.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


@dataclass
class PreparedImage:
    image: np.ndarray            # corrected BGR image
    corrected: bool
    notes: list[str]


def _order(pts: np.ndarray) -> np.ndarray:
    pts = pts.reshape(4, 2).astype(np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def find_page_quad(img: np.ndarray) -> Optional[np.ndarray]:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    # Paper is brighter than background: threshold on brightness then take the largest blob.
    blur = cv2.GaussianBlur(gray, (7, 7), 0)
    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.2 * h * w:
        return None
    peri = cv2.arcLength(c, True)
    for eps in (0.02, 0.03, 0.05):
        approx = cv2.approxPolyDP(c, eps * peri, True)
        if len(approx) == 4:
            return _order(approx)
    rect = cv2.minAreaRect(c)
    return _order(cv2.boxPoints(rect))


def prepare(path: str | Path) -> tuple[PreparedImage, np.ndarray]:
    img = cv2.imread(str(path))
    if img is None:
        raise ValueError("Unreadable image file")
    notes: list[str] = []
    quad = find_page_quad(img)
    corrected = False
    if quad is not None:
        tl, tr, br, bl = quad
        wid = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
        hei = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
        img_area = img.shape[0] * img.shape[1]
        if wid * hei < 0.97 * img_area:  # only warp when the page is not already full-frame
            dst = np.array([[0, 0], [wid - 1, 0], [wid - 1, hei - 1], [0, hei - 1]], dtype=np.float32)
            M = cv2.getPerspectiveTransform(quad, dst)
            img = cv2.warpPerspective(img, M, (wid, hei))
            corrected = True
            notes.append("Perspective corrected from detected page outline")
    if not corrected:
        notes.append("Page outline not detected — OCR run on original framing")
    # Normalise lighting: divide by a large-kernel background estimate.
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bg = cv2.medianBlur(gray, 51)
    norm = cv2.divide(gray, bg, scale=255)
    # Upscale small captures for OCR
    if norm.shape[1] < 1600:
        f = 1600 / norm.shape[1]
        norm = cv2.resize(norm, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
        img = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    return PreparedImage(image=img, corrected=corrected, notes=notes + ["Lighting normalised"]), norm


def ocr_lines(gray: np.ndarray) -> list[dict]:
    """Return OCR lines with bbox (in corrected-image pixels) and mean word confidence."""
    import pytesseract

    data = pytesseract.image_to_data(gray, config="--psm 4", output_type=pytesseract.Output.DICT)
    lines: dict[tuple, dict] = {}
    for i, word in enumerate(data["text"]):
        if not word or not word.strip():
            continue
        conf = float(data["conf"][i])
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        ln = lines.setdefault(key, {"words": [], "confs": [], "bbox": [x, y, x + w, y + h]})
        ln["words"].append(word)
        if conf >= 0:
            ln["confs"].append(conf)
        b = ln["bbox"]
        ln["bbox"] = [min(b[0], x), min(b[1], y), max(b[2], x + w), max(b[3], y + h)]
    out = []
    for key in sorted(lines, key=lambda k: (lines[k]["bbox"][1], lines[k]["bbox"][0])):
        ln = lines[key]
        out.append({"text": " ".join(ln["words"]), "bbox": ln["bbox"],
                    "conf": (sum(ln["confs"]) / len(ln["confs"])) if ln["confs"] else 0.0})
    return out
