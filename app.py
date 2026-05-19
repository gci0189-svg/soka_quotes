import streamlit as st
import pandas as pd
import zipfile
import io
import os
import re
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

st.set_page_config(page_title="創價鼓勵小卡產生器", layout="wide", page_icon="🍀")
st.title("🍀 創價鼓勵小卡 A4 2x3 產生器")

# ══════════════════════════════════════════════════════════════
# 字型系統：整句切換 Fallback
# ══════════════════════════════════════════════════════════════
FONT_CHAIN = [
    "fonts/芫荽.ttf",          # 主字型：文青手寫
    "fonts/NotoSansTC-Regular.ttf",  # 備用 1：Noto TC
    "fonts/MSJH.ttf",          # 備用 2：微軟正黑（兜底）
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # 系統 Noto（最終保底）
]

@st.cache_resource
def load_font(path: str, size: int, index: int = 0):
    """載入字型，失敗回傳 None。"""
    try:
        if path and os.path.exists(path):
            return ImageFont.truetype(path, size, index=index)
    except Exception:
        pass
    return None

def _font_index(path: str) -> int:
    """NotoSansCJK .ttc 需要 index=2 才是 TC。"""
    if "NotoSansCJK" in path and path.endswith(".ttc"):
        return 2
    return 0

@st.cache_data
def text_has_all_glyphs(text: str, font_path: str, size: int) -> bool:
    """
    整句檢查：只要有任何一個字元在此字型缺字，就回傳 False。
    使用 getmask().getbbox() — None 或空代表缺字。
    """
    font = load_font(font_path, size, _font_index(font_path))
    if font is None:
        return False
    for ch in text:
        if ch in (' ', '\n', '\u200b'):
            continue
        try:
            bbox = font.getmask(ch).getbbox()
            if bbox is None or (bbox[2] - bbox[0]) <= 1 or (bbox[3] - bbox[1]) <= 1:
                return False
        except Exception:
            return False
    return True

def pick_font_for_text(text: str, size: int):
    """
    整句切換 Fallback：
    依 FONT_CHAIN 順序找第一個能完整渲染整句的字型。
    回傳 (font_object, font_path_used)
    """
    for path in FONT_CHAIN:
        if not path:
            continue
        if text_has_all_glyphs(text, path, size):
            font = load_font(path, size, _font_index(path))
            if font:
                return font, path
    # 終極保底：用系統 Noto，不管缺不缺
    path = FONT_CHAIN[-1]
    font = load_font(path, size, _font_index(path))
    return font, path

# ══════════════════════════════════════════════════════════════
# 側邊欄
# ══════════════════════════════════════════════════════════════
st.sidebar.header("🎨 小卡視覺調整面板")

st.sidebar.markdown("**📝 全局文字設定**")
g_font_size_content = st.sidebar.slider("正文字型大小（全局）", 20, 70, 46, step=2)
g_font_size_source  = st.sidebar.slider("出處字型大小", 14, 40, 26, step=2)
line_spacing        = st.sidebar.slider("行距倍數", 1.2, 2.5, 1.6, step=0.1)
text_color          = st.sidebar.color_picker("文字顏色", "#FFFFFF")

st.sidebar.markdown("---")
st.sidebar.markdown("**🌄 背景設定**")
auto_darkness = st.sidebar.checkbox("✨ 智能自動遮罩（依底圖亮度調整）", value=False)
if auto_darkness:
    st.sidebar.caption("智能模式：依底圖亮度自動計算基準，再加下方偏移量。")
    bg_darkness = st.sidebar.slider("手動微調偏移量（+ 加深 / - 減淺）",
                                    -0.30, 0.30, 0.0, step=0.05)
else:
    bg_darkness = st.sidebar.slider("手動遮罩黯淡度（完全自訂）",
                                    0.0, 1.0, 0.0, step=0.05)
import streamlit as st
import pandas as pd
import zipfile
import io
import os
import re
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

st.set_page_config(page_title="創價鼓勵小卡產生器", layout="wide", page_icon="🍀")
st.title("🍀 創價鼓勵小卡 A4 2x3 產生器")

# ══════════════════════════════════════════════════════════════
# 字型系統：整句切換 Fallback
# ══════════════════════════════════════════════════════════════
FONT_CHAIN = [
    "fonts/芫荽.ttf",          # 主字型：文青手寫
    "fonts/NotoSansTC-Regular.ttf",  # 備用 1：Noto TC
    "fonts/MSJH.ttf",          # 備用 2：微軟正黑（兜底）
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # 系統 Noto（最終保底）
]

@st.cache_resource
def load_font(path: str, size: int, index: int = 0):
    """載入字型，失敗回傳 None。"""
    try:
        if path and os.path.exists(path):
            return ImageFont.truetype(path, size, index=index)
    except Exception:
        pass
    return None

def _font_index(path: str) -> int:
    """NotoSansCJK .ttc 需要 index=2 才是 TC。"""
    if "NotoSansCJK" in path and path.endswith(".ttc"):
        return 2
    return 0

@st.cache_data
def text_has_all_glyphs(text: str, font_path: str, size: int) -> bool:
    """
    整句檢查：只要有任何一個字元在此字型缺字，就回傳 False。
    使用 getmask().getbbox() — None 或空代表缺字。
    """
    font = load_font(font_path, size, _font_index(font_path))
    if font is None:
        return False
    for ch in text:
        if ch in (' ', '\n', '\u200b'):
            continue
        try:
            bbox = font.getmask(ch).getbbox()
            if bbox is None or (bbox[2] - bbox[0]) <= 1 or (bbox[3] - bbox[1]) <= 1:
                return False
        except Exception:
            return False
    return True

def pick_font_for_text(text: str, size: int):
    """
    整句切換 Fallback：
    依 FONT_CHAIN 順序找第一個能完整渲染整句的字型。
    回傳 (font_object, font_path_used)
    """
    for path in FONT_CHAIN:
        if not path:
            continue
        if text_has_all_glyphs(text, path, size):
            font = load_font(path, size, _font_index(path))
            if font:
                return font, path
    # 終極保底：用系統 Noto，不管缺不缺
    path = FONT_CHAIN[-1]
    font = load_font(path, size, _font_index(path))
    return font, path

# ══════════════════════════════════════════════════════════════
# 側邊欄
# ══════════════════════════════════════════════════════════════
st.sidebar.header("🎨 小卡視覺調整面板")

st.sidebar.markdown("**📝 全局文字設定**")
g_font_size_content = st.sidebar.slider("正文字型大小（全局）", 20, 70, 46, step=2)
g_font_size_source  = st.sidebar.slider("出處字型大小", 14, 40, 26, step=2)
line_spacing        = st.sidebar.slider("行距倍數", 1.2, 2.5, 1.6, step=0.1)
text_color          = st.sidebar.color_picker("文字顏色", "#FFFFFF")

st.sidebar.markdown("---")
st.sidebar.markdown("**🌄 背景設定**")
auto_darkness = st.sidebar.checkbox("✨ 智能自動遮罩（依底圖亮度調整）", value=False)
if auto_darkness:
    st.sidebar.caption("智能模式：依底圖亮度自動計算基準，再加下方偏移量。")
    bg_darkness = st.sidebar.slider("手動微調偏移量（+ 加深 / - 減淺）",
                                    -0.30, 0.30, 0.0, step=0.05)
else:
    bg_darkness = st.sidebar.slider("手動遮罩黯淡度（完全自訂）",
                                    0.0, 1.0, 0.0, step=0.05)
