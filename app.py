import streamlit as st
import pandas as pd
import zipfile
import io
import os
import re
import json
import hashlib
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader

st.set_page_config(page_title="創價鼓勵小卡產生器", layout="wide", page_icon="🍀")
st.title("🍀 創價鼓勵小卡 A4 2x3 產生器")

# ══════════════════════════════════════════════════════════════
# 字型系統：整句切換 Fallback
# ══════════════════════════════════════════════════════════════
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_DIR = os.path.join(BASE_DIR, "saved_card_settings")
os.makedirs(SAVE_DIR, exist_ok=True)

FONT_CHAIN = [
    # 預設手寫字優先；若整句含缺字風險，整句切到完整中文字型。
    "fonts/芫荽.ttf",
    "芫荽.ttf",
    "fonts/思源黑體 Medium.ttf",
    "思源黑體 Medium.ttf",
    "fonts/源泉圓體.otf",
    "源泉圓體.otf",
    "fonts/NotoSansTC-Regular.ttf",
    "NotoSansTC-Regular.ttf",
    "fonts/MSJH.ttf",
    "MSJH.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]

HANDWRITING_UNSAFE_CHARS = set("麼麽么〇○●◎※→←↑↓★☆♡♥✓✔✕✖⟪⟫")

def resolve_font_path(path: str) -> str:
    """支援 repo 根目錄、fonts/ 子資料夾與 Linux 系統字型。"""
    if not path:
        return path
    if os.path.isabs(path):
        return path
    return os.path.join(BASE_DIR, path)

@st.cache_resource
def load_font(path: str, size: int, index: int = 0):
    """載入字型，失敗回傳 None。"""
    try:
        real_path = resolve_font_path(path)
        if real_path and os.path.exists(real_path):
            return ImageFont.truetype(real_path, size, index=index)
    except Exception:
        pass
    return None

def _font_index(path: str) -> int:
    """NotoSansCJK .ttc 用預設 index 較穩，避免挑到不適合的 collection。"""
    return 0

def _glyph_signature(font, ch: str):
    """把 glyph 畫成 mask 簽名；缺字通常會和 notdef 方框完全相同。"""
    try:
        mask = font.getmask(ch)
        bbox = mask.getbbox()
        if bbox is None:
            return None
        return (mask.size, bbox, bytes(mask))
    except Exception:
        return None

@st.cache_data
def text_has_all_glyphs(text: str, font_path: str, size: int) -> bool:
    """用 notdef mask 比對檢查缺字，避免把缺字方框誤判成正常文字。"""
    font = load_font(font_path, size, _font_index(font_path))
    if font is None:
        return False

    missing_signatures = set()
    for missing_ch in ("\uFFFF", "\uFFFE", "\U0010FFFF"):
        sig = _glyph_signature(font, missing_ch)
        if sig is not None:
            missing_signatures.add(sig)

    for ch in text:
        if ch in (' ', '\n', '\u200b'):
            continue
        sig = _glyph_signature(font, ch)
        if sig is None:
            return False
        if missing_signatures and sig in missing_signatures:
            return False
    return True
