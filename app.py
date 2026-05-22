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
    # 字型優先順序：粗體黑體優先，提升小卡文字可讀性。
    "soka_all_materials/思源黑體 Heavy.otf",
    "fonts/思源黑體 Heavy.otf",
    "思源黑體 Heavy.otf",
    "soka_all_materials/源樣黑體 Heavy.otf",
    "fonts/源樣黑體 Heavy.otf",
    "源樣黑體 Heavy.otf",
    "soka_all_materials/源泉圓體.otf",
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

def pick_font_for_text(text: str, size: int):
    """整句切換字型：任一字不適合思源黑體 Heavy時，整句改用備用中文字型。"""
    text = str(text or '')

    for path in FONT_CHAIN:
        if not path:
            continue
        if text_has_all_glyphs(text, path, size):
            font = load_font(path, size, _font_index(path))
            if font:
                return font, path

    # 最後保底：找得到哪個字型就先用哪個，至少避免 None。
    for path in FONT_CHAIN:
        font = load_font(path, size, _font_index(path))
        if font:
            return font, path
    return ImageFont.load_default(), "Pillow-default"

@st.cache_resource
def pick_font_for_char(ch: str, size: int, preferred_path: str = ""):
    """逐字 fallback：先試目前字型，不支援就找下一個中文字型。"""
    candidates = []
    if preferred_path:
        candidates.append(preferred_path)
    candidates.extend([p for p in FONT_CHAIN if p and p not in candidates])

    for path in candidates:
        if text_has_all_glyphs(ch, path, size):
            font = load_font(path, size, _font_index(path))
            if font:
                return font, path
    return ImageFont.load_default(), "Pillow-default"

def text_width_fallback(draw, text: str, size: int, preferred_path: str = "") -> int:
    """計算逐字 fallback 後的實際寬度。"""
    width = 0
    for ch in text:
        font, _ = pick_font_for_char(ch, size, preferred_path)
        try:
            width += int(draw.textlength(ch, font=font))
        except Exception:
            bbox = draw.textbbox((0, 0), ch, font=font)
            width += bbox[2] - bbox[0]
    return width

def safe_wrap_line(text: str, size: int, max_w: int, draw, preferred_path: str = "") -> list:
    """均衡折行：標點不孤立、行寬不超界、最後一行不過短。"""
    line = text.strip()
    if not line:
        return []

    total_w = text_width_fallback(draw, line, size, preferred_path)
    if total_w <= max_w:
        return [line]

    n_chars = len(line)
    close_punct = set("，。！？；：、,.!?;:)）】》」』〕〉")
    open_punct = set("（【《「『〔〈“‘(")
    protected_words = [
        "什麼", "怎麼", "為什麼", "勇氣", "對話", "身邊", "和平", "友好", "道路",
        "心思", "接觸", "互相", "轉變", "一念", "鼓起", "進行", "打破",
        "盤踞", "自己", "心中", "不信", "憎惡", "恐怖", "智慧", "表現",
        "自然", "周密", "計劃", "具體性", "成功", "慈悲", "同苦", "想救",
    ]
    weak_tail_chars = set("用做有於與和及在的不、，")

    width_cache = {}
    def width(a, b):
        key = (a, b)
        if key not in width_cache:
            width_cache[key] = text_width_fallback(draw, line[a:b], size, preferred_path)
        return width_cache[key]

    def breaks_protected_word(pos):
        for word in protected_words:
            start = line.find(word)
            while start != -1:
                end = start + len(word)
                if start < pos < end:
                    return True
                start = line.find(word, start + 1)
        return False

    def valid_piece(a, b):
        if a >= b:
            return False
        piece = line[a:b].strip()
        if not piece:
            return False
        if line[a] in close_punct:
            return False
        if line[b - 1] in open_punct:
            return False
        if b < n_chars and breaks_protected_word(b):
            return False
        if len(piece) <= 1 and n_chars > 1:
            return False
        return width(a, b) <= max_w

    min_lines = max(2, int(total_w // max_w) + (1 if total_w % max_w else 0))
    best_lines, best_score = None, None

    for target_lines in range(min_lines, min(min_lines + 4, 7) + 1):
        target_w = total_w / target_lines
        dp = {0: (0.0, [])}
        for _ in range(target_lines):
            ndp = {}
            for start, (score, parts) in dp.items():
                remaining_slots = target_lines - len(parts)
                min_end = start + 1
                max_end = n_chars - (remaining_slots - 1)
                for end in range(min_end, max_end + 1):
                    if not valid_piece(start, end):
                        continue
                    piece_w = width(start, end)
                    piece = line[start:end]
                    new_score = score + ((piece_w - target_w) ** 2) / 1000
                    if piece[-1] in "，。！？；：":
                        new_score -= 5000
                    elif piece[-1] in "」』）】》":
                        new_score -= 1800
                    if end < n_chars and line[end] in close_punct:
                        new_score += 8000
                    if end < n_chars and line[end] in "「『（【《":
                        new_score -= 1000
                    if piece.count("「") != piece.count("」") or piece.count("『") != piece.count("』"):
                        new_score += 1600
                    if len(piece) <= 3 and end == n_chars:
                        new_score += 12000
                    elif len(piece) <= 5 and end == n_chars:
                        new_score += 4500
                    if end < n_chars and piece[-1] in weak_tail_chars:
                        new_score += 3500
                    if len(piece) <= 4 and end < n_chars and piece[-1] not in close_punct:
                        new_score += 2200
                    old = ndp.get(end)
                    if old is None or new_score < old[0]:
                        ndp[end] = (new_score, parts + [piece])
            dp = ndp
        if n_chars in dp:
            score, parts = dp[n_chars]
            if best_score is None or score < best_score:
                best_score, best_lines = score, parts

    if best_lines:
        if len(best_lines) >= 2 and len(best_lines[-1]) <= 4:
            merged = best_lines[-2] + best_lines[-1]
            best_split = None
            best_split_score = None
            for pos in range(2, len(merged) - 1):
                if breaks_protected_word(n_chars - len(merged) + pos):
                    continue
                left, right = merged[:pos], merged[pos:]
                if right[0] in close_punct or left[-1] in open_punct:
                    continue
                lw = text_width_fallback(draw, left, size, preferred_path)
                rw = text_width_fallback(draw, right, size, preferred_path)
                if lw > max_w or rw > max_w:
                    continue
                score = abs(lw - rw)
                if left[-1] in "，。！？；：」』）】》":
                    score -= 500
                if len(right) <= 3:
                    score += 5000
                if best_split_score is None or score < best_split_score:
                    best_split_score = score
                    best_split = [left, right]
            if best_split:
                best_lines = best_lines[:-2] + best_split
        return best_lines

    out, cur = [], ""
    for ch in line:
        if cur and text_width_fallback(draw, cur + ch, size, preferred_path) > max_w:
            out.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out

def manual_wrap_safe(text: str, size: int, max_w: int, draw, preferred_path: str = "") -> list:
    """Enter 是硬斷行；每個段落內再做均衡折行。"""
    lines = []
    for part in text.split('\n'):
        lines.extend(safe_wrap_line(part, size, max_w, draw, preferred_path))
    return lines if lines else [text.strip() or text]

def draw_text_fallback(draw, pos, text: str, size: int, preferred_path: str,
                       fill_rgb, stroke_w=3, img=None, glow_str=0):
    """逐字 fallback 繪製，單一缺字會自動改用備用中文字型。"""
    x, y = pos
    r, g, b = fill_rgb
    bright = r * 0.299 + g * 0.587 + b * 0.114
    stroke_fill = (15, 15, 15, 230) if bright > 128 else (240, 240, 240, 220)

    def draw_runs(target_draw, xy, fill, stroke=0, stroke_fill_arg=None):
        cx, cy = xy
        for ch in text:
            font, _ = pick_font_for_char(ch, size, preferred_path)
            target_draw.text(
                (cx, cy), ch, font=font, fill=fill,
                stroke_width=stroke,
                stroke_fill=stroke_fill_arg if stroke_fill_arg is not None else stroke_fill,
            )
            try:
                cx += target_draw.textlength(ch, font=font)
            except Exception:
                bbox = target_draw.textbbox((0, 0), ch, font=font)
                cx += bbox[2] - bbox[0]

    if glow_str > 0 and img is not None:
        gl = Image.new('RGBA', img.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(gl)
        draw_runs(gd, (x, y), (r, g, b, 160), stroke=0)
        img.alpha_composite(gl.filter(ImageFilter.GaussianBlur(radius=glow_str)))
        draw = ImageDraw.Draw(img, 'RGBA')

    draw_runs(draw, (x, y), (r, g, b, 255), stroke=stroke_w, stroke_fill_arg=stroke_fill)

DEFAULT_VISUAL_SETTINGS = {
    "g_font_size_content": 46,
    "g_font_size_source": 26,
    "line_spacing": 1.6,
    "text_color": "#FFFFFF",
    "auto_darkness": False,
    "bg_darkness": 0.0,
    "stroke_width": 3,
    "glow_strength": 0,
    "show_cut_lines": True,
}

def visual_key(name: str) -> str:
    return f"visual_{name}"

def clamp_value(value, min_value, max_value):
    return min(max(value, min_value), max_value)

def normalize_visual_settings(value) -> dict:
    if not isinstance(value, dict):
        return {}
    clean = {}
    try:
        clean["g_font_size_content"] = int(clamp_value(int(value.get("g_font_size_content", 46)), 20, 70))
    except Exception:
        pass
    try:
        clean["g_font_size_source"] = int(clamp_value(int(value.get("g_font_size_source", 26)), 14, 40))
    except Exception:
        pass
    try:
        clean["line_spacing"] = round(float(clamp_value(float(value.get("line_spacing", 1.6)), 1.2, 2.5)), 1)
    except Exception:
        pass
    color = value.get("text_color")
    if isinstance(color, str) and re.match(r"^#[0-9a-fA-F]{6}$", color):
        clean["text_color"] = color
    if "auto_darkness" in value:
        clean["auto_darkness"] = bool(value.get("auto_darkness"))
    auto_darkness_value = clean.get("auto_darkness", bool(value.get("auto_darkness", False)))
    try:
        bg_value = float(value.get("bg_darkness", 0.0))
        clean["bg_darkness"] = round(float(clamp_value(bg_value, -0.30 if auto_darkness_value else 0.0, 0.30 if auto_darkness_value else 1.0)), 2)
    except Exception:
        pass
    try:
        clean["stroke_width"] = int(clamp_value(int(value.get("stroke_width", 3)), 0, 5))
    except Exception:
        pass
    try:
        clean["glow_strength"] = int(clamp_value(int(value.get("glow_strength", 0)), 0, 8))
    except Exception:
        pass
    if "show_cut_lines" in value:
        clean["show_cut_lines"] = bool(value.get("show_cut_lines"))
    return clean

def apply_visual_settings(visual_settings: dict):
    for k, v in normalize_visual_settings(visual_settings).items():
        st.session_state[visual_key(k)] = v

# ══════════════════════════════════════════════════════════════
# 側邊欄
# ══════════════════════════════════════════════════════════════
st.sidebar.header("🎨 小卡視覺調整面板")

if "_pending_visual_settings" in st.session_state:
    apply_visual_settings(st.session_state.pop("_pending_visual_settings"))

for _visual_name, _visual_default in DEFAULT_VISUAL_SETTINGS.items():
    st.session_state.setdefault(visual_key(_visual_name), _visual_default)

st.sidebar.markdown("**📝 全局文字設定**")
g_font_size_content = st.sidebar.slider("正文字型大小（全局）", 20, 70, step=2, key=visual_key("g_font_size_content"))
g_font_size_source  = st.sidebar.slider("出處字型大小", 14, 40, step=2, key=visual_key("g_font_size_source"))
line_spacing        = st.sidebar.slider("行距倍數", 1.2, 2.5, step=0.1, key=visual_key("line_spacing"))
text_color          = st.sidebar.color_picker("文字顏色", key=visual_key("text_color"))

st.sidebar.markdown("---")
st.sidebar.markdown("**🌄 背景設定**")
auto_darkness = st.sidebar.checkbox("✨ 智能自動遮罩（依底圖亮度調整）", key=visual_key("auto_darkness"))
if auto_darkness:
    st.session_state[visual_key("bg_darkness")] = clamp_value(st.session_state[visual_key("bg_darkness")], -0.30, 0.30)
    st.sidebar.caption("智能模式：依底圖亮度自動計算基準，再加下方偏移量。")
    bg_darkness = st.sidebar.slider(
        "手動微調偏移量（+ 加深 / - 減淺）",
        -0.30, 0.30, step=0.05, key=visual_key("bg_darkness")
    )
else:
    st.session_state[visual_key("bg_darkness")] = clamp_value(st.session_state[visual_key("bg_darkness")], 0.0, 1.0)
    bg_darkness = st.sidebar.slider(
        "手動遮罩黯淡度（完全自訂）",
        0.0, 1.0, step=0.05, key=visual_key("bg_darkness")
    )

st.sidebar.markdown("---")
st.sidebar.markdown("**✨ 文字清晰強化**")
stroke_width  = st.sidebar.slider("文字描邊寬度", 0, 5, step=1, key=visual_key("stroke_width"))
glow_strength = st.sidebar.slider("文字發光強度（0=關閉）", 0, 8, step=1, key=visual_key("glow_strength"))

st.sidebar.markdown("---")
show_cut_lines = st.sidebar.checkbox("顯示 A4 裁切虛線", key=visual_key("show_cut_lines"))

sidebar_params = dict(
    g_font_size_content=g_font_size_content,
    g_font_size_source=g_font_size_source,
    line_spacing=line_spacing, text_color=text_color,
    bg_darkness=bg_darkness, auto_darkness=auto_darkness,
    stroke_width=stroke_width, glow_strength=glow_strength,
    show_cut_lines=show_cut_lines,
)

# ══════════════════════════════════════════════════════════════
# 主畫面上傳
# ══════════════════════════════════════════════════════════════
col1, col2 = st.columns(2)
with col1:
    uploaded_csv = st.file_uploader("1. 上傳語錄表格 (soka_quotes.csv)", type=["csv"])
with col2:
    uploaded_zip = st.file_uploader("2. 上傳素材壓縮包 (zip)", type=["zip"])

for k, v in [
    ("pdf_data", None), ("preview_bytes_list", []),
    ("last_params", None), ("zip_bytes_cache", None),
    ("csv_cache", None), ("zip_index_cache", None),
    ("card_overrides", {}),
    ("_dataset_key", ""),
]:
    if k not in st.session_state:
        st.session_state[k] = v

# ══════════════════════════════════════════════════════════════
# 設定 JSON：本機自動保存 + 匯入/匯出
# ══════════════════════════════════════════════════════════════
def get_dataset_key(csv_bytes: bytes, zip_name: str = "") -> str:
    h = hashlib.sha256()
    h.update(csv_bytes or b"")
    h.update(str(zip_name or "").encode("utf-8"))
    return h.hexdigest()[:16]

def settings_path(dataset_key: str) -> str:
    return os.path.join(SAVE_DIR, f"{dataset_key}.json")

def normalize_overrides(value) -> dict:
    if not isinstance(value, dict):
        return {}
    clean = {}
    for k, v in value.items():
        if not isinstance(v, dict):
            continue
        entry = {}
        if isinstance(v.get("content"), str) and v.get("content").strip():
            entry["content"] = v["content"]
        if "font_size" in v:
            try:
                entry["font_size"] = int(v["font_size"])
            except Exception:
                pass
        if entry:
            clean[str(k)] = entry
    return clean

def make_settings_payload(overrides: dict, dataset_key: str = "", csv_name: str = "", zip_name: str = "", visual_settings=None) -> dict:
    return {
        "version": 1,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "dataset_key": dataset_key,
        "csv_name": csv_name,
        "zip_name": zip_name,
        "visual_settings": dict(visual_settings or {}),
        "card_overrides": normalize_overrides(overrides),
    }

def load_card_overrides(dataset_key: str) -> dict:
    path = settings_path(dataset_key)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "card_overrides" in data:
            return normalize_overrides(data.get("card_overrides"))
        return normalize_overrides(data)
    except Exception:
        return {}

def save_card_overrides(dataset_key: str, overrides: dict, csv_name: str = "", zip_name: str = "", visual_settings=None):
    if not dataset_key:
        return
    payload = make_settings_payload(overrides, dataset_key, csv_name, zip_name, visual_settings)
    with open(settings_path(dataset_key), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

def parse_uploaded_settings(uploaded_file):
    try:
        uploaded_file.seek(0)
        raw = uploaded_file.read()
        data = json.loads(raw.decode("utf-8-sig"))
        if isinstance(data, dict) and "card_overrides" in data:
            return normalize_overrides(data.get("card_overrides")), data
        return normalize_overrides(data), {}
    except Exception as exc:
        raise ValueError(f"設定 JSON 讀取失敗：{exc}") from exc

# ══════════════════════════════════════════════════════════════
# 工具函式
# ══════════════════════════════════════════════════════════════
def hex_to_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

def smart_dark(img_rgb: Image.Image) -> float:
    w, h = img_rgb.size
    crop = img_rgb.crop((int(w*.3), int(h*.25), int(w*.7), int(h*.75))).convert('L')
    data = list(crop.getdata())
    avg  = sum(data) / len(data)
    return round(min(max(0.20 + (avg / 255) * 0.35, 0.15), 0.55), 2)

def smart_wrap(text: str, font, max_w: int, draw) -> list:
    """智能斷行：標點優先 → 均衡分行 → 短尾合併。"""
    BREAK_AFTER = set('。！？…；')
    chunks, buf = [], ''
    for ch in text:
        buf += ch
        if ch in BREAK_AFTER:
            chunks.append(buf); buf = ''
    if buf:
        chunks.append(buf)

    def width(t):
        return draw.textbbox((0, 0), t, font=font)[2]

    lines, cur = [], ''
    for chunk in chunks:
        if width(cur + chunk) <= max_w:
            cur += chunk
        else:
            if cur:
                lines.append(cur); cur = ''
            for ch in chunk:
                if width(cur + ch) <= max_w:
                    cur += ch
                else:
                    if cur: lines.append(cur)
                    cur = ch
    if cur:
        lines.append(cur)

    # 只有1行且偏長 → 嘗試平均拆2行
    if len(lines) == 1 and len(lines[0]) >= 12:
        s = lines[0]; mid = len(s) // 2; best = mid
        for off in range(0, mid + 1):
            for pos in [mid - off, mid + off + 1]:
                if 0 < pos <= len(s) and s[pos - 1] in BREAK_AFTER:
                    best = pos; break
            else:
                continue
            break
        lines = [s[:best], s[best:]] if s[best:] else [s]

    # 最後一行太短 → 合併再均分
    if len(lines) >= 2 and len(lines[-1]) <= 3:
        merged = lines[-2] + lines[-1]; mid = len(merged) // 2
        lines  = lines[:-2] + [merged[:mid], merged[mid:]]

    return lines if lines else [text]

def manual_wrap(text: str) -> list:
    """手動斷行：依 \\n 分行，不做任何智能處理。"""
    return [l for l in text.split('\n') if l.strip()] or [text]

def draw_text_pro(draw, pos, text, font, fill_rgb, stroke_w=3, img=None, glow_str=0):
    """描邊 + 發光文字渲染。整句使用同一個 font 物件，視覺完全統一。"""
    x, y = pos
    r, g, b = fill_rgb
    bright = r * 0.299 + g * 0.587 + b * 0.114
    sc = (15, 15, 15, 220) if bright > 128 else (240, 240, 240, 200)

    # 發光層
    if glow_str > 0 and img is not None:
        gl = Image.new('RGBA', img.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(gl)
        gd.text((x, y), text, font=font, fill=(r, g, b, 160))
        img.alpha_composite(gl.filter(ImageFilter.GaussianBlur(radius=glow_str)))
        draw = ImageDraw.Draw(img, 'RGBA')  # 重建 draw after composite

    # 描邊層
    if stroke_w > 0:
        for dx in range(-stroke_w, stroke_w + 1):
            for dy in range(-stroke_w, stroke_w + 1):
                if abs(dx) + abs(dy) <= stroke_w + 1 and not (dx == 0 and dy == 0):
                    draw.text((x + dx, y + dy), text, font=font, fill=sc)

    # 主色層
    draw.text((x, y), text, font=font, fill=(r, g, b, 255))

def build_zip_index(zip_bytes: bytes):
    IMG_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'}
    index, all_paths = {}, []
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    for name in zf.namelist():
        if '__MACOSX' in name or name.endswith('/'): continue
        bn = os.path.basename(name)
        if not bn or bn.startswith('.'): continue
        if os.path.splitext(bn)[1].lower() not in IMG_EXT: continue
        all_paths.append(name)
        stem = bn
        while os.path.splitext(stem)[1].lower() in IMG_EXT:
            stem = os.path.splitext(stem)[0]
        for key in [bn.lower(), stem.lower()] + \
                   [(stem + s).lower() for s in ['', '.jpg', '.webp', '.png', '.jpg.webp']]:
            index.setdefault(key, name)
        for num in re.findall(r'\d+', stem):
            n = int(num)
            for k in [num, str(n), str(n).zfill(2), str(n).zfill(3), str(n).zfill(4)]:
                index.setdefault(k, name)
            m = re.match(r'^([a-zA-Z_\-]+)(\d+)$', stem)
            if m:
                pfx = m.group(1)
                for pad in [0, 2, 3, 4]:
                    kk = pfx + (str(n) if pad == 0 else str(n).zfill(pad))
                    for sfx in ['', '.jpg', '.webp', '.png', '.jpg.webp']:
                        index.setdefault((kk + sfx).lower(), name)
    return index, all_paths, zf

def find_in_index(raw: str, index: dict):
    IMG_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'}
    raw = str(raw).strip()
    stem_raw = raw
    while os.path.splitext(stem_raw)[1].lower() in IMG_EXT:
        stem_raw = os.path.splitext(stem_raw)[0]
    candidates = [raw.lower(), stem_raw.lower()] + \
                 [(stem_raw + s).lower() for s in ['', '.jpg', '.webp', '.jpg.webp']]
    for num in re.findall(r'\d+', stem_raw):
        n = int(num)
        for k in [num, str(n), str(n).zfill(2), str(n).zfill(3), str(n).zfill(4)]:
            candidates.append(k)
        m = re.match(r'^([a-zA-Z_\-]+)', stem_raw)
        if m:
            pfx = m.group(1)
            for pad in [0, 2, 3, 4]:
                kk = pfx + (str(n) if pad == 0 else str(n).zfill(pad))
                for sfx in ['', '.jpg', '.webp', '.jpg.webp']:
                    candidates.append((kk + sfx).lower())
    return next((index[c] for c in candidates if c in index), None)

# ══════════════════════════════════════════════════════════════
# 核心：生成單張卡片
# ══════════════════════════════════════════════════════════════

def generate_card(row, row_idx, zf, zip_index,
                  g_size_content, size_source,
                  bg_darkness, auto_darkness_on,
                  text_color_hex, line_spacing_mult,
                  stroke_w, glow_str, overrides: dict):
    """
    overrides[str(row_idx)] 可包含：
      'content'  : 手動斷句文字（含 \\n）
      'font_size': 單張正文字體大小覆蓋
    字型使用整句切換 Fallback，同一句絕不混用兩種字型。
    """
    override    = overrides.get(str(row_idx), {})
    custom_text = override.get('content', None)
    font_size   = override.get('font_size', g_size_content)

    # ── 底圖 ──────────────────────────────────────────────────
    matched = find_in_index(row['Image_Name'], zip_index)
    if matched:
        try:
            card = Image.open(io.BytesIO(zf.read(matched))).convert('RGBA')
        except Exception:
            card = Image.new('RGBA', (1000, 1000), (220, 217, 210, 255))
    else:
        card = Image.new('RGBA', (1000, 1000), (220, 217, 210, 255))
    card = card.resize((1000, 1000), resample=Image.Resampling.BILINEAR)

    # ── 遮罩 ──────────────────────────────────────────────────
    if auto_darkness_on:
        base   = smart_dark(card.convert('RGB'))
        actual = round(min(max(base + bg_darkness, 0.0), 0.85), 2)
    else:
        actual = bg_darkness
    if actual > 0:
        overlay = Image.new('RGBA', (1000, 1000), (0, 0, 0, int(255 * actual)))
        card    = Image.alpha_composite(card, overlay)

    draw     = ImageDraw.Draw(card, 'RGBA')
    fill_rgb = hex_to_rgb(text_color_hex)

    # ── 正文：整句 fallback 字型 + 保守斷句 ─────────────────────
    raw_content = str(row.get('Content', '')).replace(' ', '')

    if custom_text is not None:
        full_text_for_check = custom_text.replace('\n', '')
        font_content, font_used = pick_font_for_text(full_text_for_check, font_size)
        lines = manual_wrap_safe(custom_text, font_size, 840, draw, font_used)
    else:
        font_content, font_used = pick_font_for_text(raw_content, font_size)
        lines = smart_wrap(raw_content, font_content, 840, draw)
        guarded_lines = []
        for line in lines:
            guarded_lines.extend(safe_wrap_line(line, font_size, 840, draw, font_used))
        lines = guarded_lines if guarded_lines else lines

    # ── 出處字型（也支援 fallback）─────────────────────────────
    src = str(row.get('Source', ''))
    if src and src != 'nan':
        font_source, source_font_used = pick_font_for_text(src, size_source)
    else:
        font_source, source_font_used = pick_font_for_text('', size_source)

    # ── 繪製正文 ──────────────────────────────────────────────
    bh      = draw.textbbox((0, 0), '高', font=font_content)
    lh      = max(1, (bh[3] - bh[1])) * line_spacing_mult
    total_h = len(lines) * lh
    start_y = (1000 - total_h) / 2 - 20

    for i, line in enumerate(lines):
        bx = draw.textbbox((0, 0), line, font=font_content)
        line_w = bx[2] - bx[0]
        x  = (1000 - line_w) / 2
        y  = start_y + i * lh
        draw_text_pro(draw, (x, y), line, font_content, fill_rgb,
                      stroke_w=stroke_w, img=card, glow_str=glow_str)
        draw = ImageDraw.Draw(card, 'RGBA')

    # ── 繪製出處 ──────────────────────────────────────────────
    if src and src != 'nan':
        bs = draw.textbbox((0, 0), src, font=font_source)
        src_w = bs[2] - bs[0]
        xs = (1000 - src_w) / 2
        draw_text_pro(draw, (xs, 900), src, font_source, fill_rgb,
                      stroke_w=stroke_w, img=card, glow_str=glow_str)

    return card.convert('RGB'), matched, actual, font_used

# ══════════════════════════════════════════════════════════════
# 快取 zip & csv + 自動載入本機設定
# ══════════════════════════════════════════════════════════════
if uploaded_csv and uploaded_zip:
    if st.session_state.get("_csv_name") != uploaded_csv.name:
        st.session_state["_csv_name"] = uploaded_csv.name
        st.session_state.csv_cache    = uploaded_csv.read()
    if st.session_state.get("_zip_name") != uploaded_zip.name:
        st.session_state["_zip_name"]    = uploaded_zip.name
        st.session_state.zip_bytes_cache = uploaded_zip.read()
        idx_b, paths_b, zf_b = build_zip_index(st.session_state.zip_bytes_cache)
        st.session_state.zip_index_cache = (idx_b, paths_b, zf_b)

    dataset_key = get_dataset_key(st.session_state.csv_cache, uploaded_zip.name)
    if st.session_state.get("_dataset_key") != dataset_key:
        st.session_state["_dataset_key"] = dataset_key
        st.session_state.card_overrides = load_card_overrides(dataset_key)

# ══════════════════════════════════════════════════════════════
# 設定檔匯入 / 匯出
# ══════════════════════════════════════════════════════════════
if uploaded_csv and uploaded_zip:
    if st.session_state.get("csv_cache") is not None and "preview_row_num" in st.session_state:
        try:
            df_sync = pd.read_csv(io.BytesIO(st.session_state.csv_cache))
            preview_row_sync = int(st.session_state.get("preview_row_num", 0))
            if 0 <= preview_row_sync < len(df_sync):
                row_key_sync = str(preview_row_sync)
                original_text_sync = str(df_sync.iloc[preview_row_sync].get("Content", "")).replace(" ", "")
                custom_text_sync = st.session_state.get(f"text_area_{preview_row_sync}", original_text_sync)
                use_custom_size_sync = st.session_state.get(f"use_custom_size_{preview_row_sync}", False)
                custom_size_sync = st.session_state.get(f"size_slider_{preview_row_sync}", g_font_size_content)
                entry_sync = {}
                if isinstance(custom_text_sync, str) and custom_text_sync.strip() and custom_text_sync != original_text_sync:
                    entry_sync["content"] = custom_text_sync
                if use_custom_size_sync:
                    entry_sync["font_size"] = int(custom_size_sync)
                if entry_sync:
                    st.session_state.card_overrides[row_key_sync] = entry_sync
                else:
                    st.session_state.card_overrides.pop(row_key_sync, None)
        except Exception:
            pass

    if "_settings_import_message" in st.session_state:
        st.success(st.session_state.pop("_settings_import_message"))

    st.subheader("💾 個別卡片設定")
    setting_col1, setting_col2, setting_col3 = st.columns([1, 1, 1])

    with setting_col1:
        payload = make_settings_payload(
            st.session_state.card_overrides,
            st.session_state.get("_dataset_key", ""),
            st.session_state.get("_csv_name", ""),
            st.session_state.get("_zip_name", ""),
            sidebar_params,
        )
        st.download_button(
            "⬇️ 下載設定 JSON",
            data=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name=f"soka_card_settings_{st.session_state.get('_dataset_key', 'manual')}.json",
            mime="application/json",
            help="下載目前所有手動斷句與單張字體設定，可留到下次匯入。",
        )

    with setting_col2:
        uploaded_settings = st.file_uploader(
            "⬆️ 上傳設定 JSON",
            type=["json"],
            key="settings_json_uploader",
            help="匯入之前下載的設定 JSON。",
        )
        if uploaded_settings is not None:
            try:
                imported_overrides, meta = parse_uploaded_settings(uploaded_settings)
                imported_visual_settings = normalize_visual_settings(meta.get("visual_settings") if isinstance(meta, dict) else {})
                if imported_overrides:
                    st.session_state.card_overrides = imported_overrides
                if imported_visual_settings:
                    st.session_state["_pending_visual_settings"] = imported_visual_settings
                if imported_overrides or imported_visual_settings:
                    save_card_overrides(
                        st.session_state.get("_dataset_key", ""),
                        st.session_state.card_overrides,
                        st.session_state.get("_csv_name", ""),
                        st.session_state.get("_zip_name", ""),
                        imported_visual_settings or sidebar_params,
                    )
                    st.session_state["_settings_import_message"] = f"已匯入 {len(imported_overrides)} 張個別設定與 {len(imported_visual_settings)} 個全局視覺設定。"
                    st.rerun()
                else:
                    st.warning("這份設定 JSON 沒有個別卡片設定，也沒有全局視覺設定，所以沒有可匯入的內容。")
            except ValueError as exc:
                st.error(str(exc))

    with setting_col3:
        st.caption(f"目前已客製化：{len(st.session_state.card_overrides)} 張")
        if st.button("🧹 清空目前設定"):
            st.session_state.card_overrides = {}
            save_card_overrides(
                st.session_state.get("_dataset_key", ""),
                st.session_state.card_overrides,
                st.session_state.get("_csv_name", ""),
                st.session_state.get("_zip_name", ""),
                sidebar_params,
            )
            st.rerun()

# ══════════════════════════════════════════════════════════════
# 診斷
# ══════════════════════════════════════════════════════════════
if uploaded_csv and uploaded_zip:
    with st.expander("🔍 診斷：ZIP 內容 & 配對", expanded=False):
        if st.button("執行診斷"):
            idx_d, paths_d, zf_d = st.session_state.zip_index_cache
            df_d = pd.read_csv(io.BytesIO(st.session_state.csv_cache))
            st.write(f"ZIP 圖片數：{len(paths_d)}")
            st.code("\n".join(paths_d[:20]))
            rows_out = []
            for _, r in df_d.head(10).iterrows():
                hit = find_in_index(r['Image_Name'], idx_d)
                rows_out.append({"Image_Name": str(r['Image_Name']),
                                 "配對結果": hit or "❌ 找不到"})
            st.table(pd.DataFrame(rows_out))

# ══════════════════════════════════════════════════════════════
# 即時預覽 + 個別卡片客製化
# ══════════════════════════════════════════════════════════════
if uploaded_csv and uploaded_zip and st.session_state.zip_index_cache:
    idx_p, _, zf_p = st.session_state.zip_index_cache
    df_p           = pd.read_csv(io.BytesIO(st.session_state.csv_cache))
    max_row        = len(df_p) - 1

    tab_single, tab_a4 = st.tabs(["🖼️ 單張預覽 & 個別客製化", "📄 A4 整頁預覽（前6筆）"])

    # ── 單張預覽 ──────────────────────────────────────────────
    with tab_single:
        c_left, c_right = st.columns([1, 1])

        with c_left:
            if st.session_state.get("preview_row_num", 0) > max_row:
                st.session_state.preview_row_num = 0
            preview_row = int(st.slider(
                "預覽第幾筆語錄（0 起算）",
                min_value=0,
                max_value=max_row,
                step=1,
                key="preview_row_num",
            ))
            row_p    = df_p.iloc[preview_row]
            row_key  = str(preview_row)
            override = st.session_state.card_overrides.get(row_key, {})

            st.markdown("---")
            st.markdown("**✏️ 個別卡片客製化**")

            # 文字編輯框
            original_text = str(row_p.get('Content', '')).replace(' ', '')
            default_text = override.get('content', original_text)
            custom_text = st.text_area(
                "手動斷句（Enter 換行；清空則恢復智能斷行）",
                value=default_text,
                height=140,
                key=f"text_area_{preview_row}",
                help="直接按 Enter 換行。若單行太長，預覽與 PDF 會自動做安全折行。"
            )

            # 個別字體大小：未勾選時，永遠跟隨側邊欄全局字體大小。
            use_custom_size = st.checkbox(
                "使用此卡專屬字體大小",
                value=('font_size' in override),
                key=f"use_custom_size_{preview_row}"
            )
            if use_custom_size:
                current_size = override.get('font_size', g_font_size_content)
                custom_size = st.slider(
                    "此卡片正文字體大小",
                    min_value=20, max_value=70,
                    value=int(current_size), step=2,
                    key=f"size_slider_{preview_row}"
                )
            else:
                custom_size = g_font_size_content
                st.slider(
                    "此卡片正文字體大小（跟隨全局）",
                    min_value=20, max_value=70,
                    value=int(g_font_size_content), step=2,
                    disabled=True,
                    key=f"size_slider_global_{preview_row}"
                )

            # 自動暫存目前這張卡片，批次輸出 PDF 會直接套用。
            entry = {}
            if custom_text.strip() and custom_text != original_text:
                entry['content'] = custom_text
            if use_custom_size:
                entry['font_size'] = custom_size
            if entry:
                st.session_state.card_overrides[row_key] = entry
            else:
                st.session_state.card_overrides.pop(row_key, None)

            save_card_overrides(
                st.session_state.get("_dataset_key", ""),
                st.session_state.card_overrides,
                st.session_state.get("_csv_name", ""),
                st.session_state.get("_zip_name", ""),
                sidebar_params,
            )

            col_save, col_reset = st.columns(2)
            with col_save:
                if st.button("💾 已自動暫存", key=f"save_{preview_row}"):
                    st.success(f"✅ 第 {preview_row} 筆目前設定已在暫存中，也已寫入本機 JSON！")

            with col_reset:
                if st.button("🔄 還原預設", key=f"reset_{preview_row}"):
                    st.session_state.card_overrides.pop(row_key, None)
                    save_card_overrides(
                        st.session_state.get("_dataset_key", ""),
                        st.session_state.card_overrides,
                        st.session_state.get("_csv_name", ""),
                        st.session_state.get("_zip_name", ""),
                        sidebar_params,
                    )
                    st.rerun()

            # 已客製化清單
            if st.session_state.card_overrides:
                st.markdown("---")
                st.markdown(f"**📋 已客製化：{len(st.session_state.card_overrides)} 張**")
                for k, v in sorted(st.session_state.card_overrides.items(),
                                   key=lambda x: int(x[0])):
                    tags = []
                    if 'content'   in v: tags.append("手動斷句")
                    if 'font_size' in v: tags.append(f"字體 {v['font_size']}")
                    st.caption(f"第 {k} 筆：{'、'.join(tags)}")

        with c_right:
            # 即時預覽：使用目前已自動暫存的設定
            live_override = entry.copy()
            live_override['font_size'] = custom_size

            card_p, matched_preview, used_dark, font_used = generate_card(
                row_p, preview_row, zf_p, idx_p,
                custom_size, g_font_size_source,
                bg_darkness, auto_darkness,
                text_color, line_spacing, stroke_width, glow_strength,
                {row_key: live_override}
            )
            buf_p = io.BytesIO()
            card_p.save(buf_p, format='JPEG', quality=88)

            # 顯示使用哪個字型
            font_label = os.path.basename(font_used) if font_used else "預設"
            image_name_label = str(row_p.get("Image_Name", ""))
            matched_label = os.path.basename(matched_preview) if matched_preview else "找不到底圖"
            st.image(
                buf_p.getvalue(),
                caption=(
                    f"第 {preview_row} 筆 ｜ CSV 圖名：{image_name_label} ｜ "
                    f"ZIP 配對：{matched_label} ｜ 遮罩 {used_dark:.2f} ｜ "
                    f"字體 {custom_size} ｜ 字型：{font_label}"
                ),
                width=420,
            )

    # ── A4 整頁預覽（前6筆）────────────────────────────────
    with tab_a4:
        st.caption("⚡ 即時渲染前 6 筆，確認整頁視覺效果。")
        preview_cards = []
        for i in range(min(6, len(df_p))):
            r = df_p.iloc[i]
            cp, _, _, _ = generate_card(
                r, i, zf_p, idx_p,
                g_font_size_content, g_font_size_source,
                bg_darkness, auto_darkness,
                text_color, line_spacing, stroke_width, glow_strength,
                st.session_state.card_overrides
            )
            preview_cards.append(cp)

        page    = Image.new('RGB', (840, 1188), (255, 255, 255))
        pd_draw = ImageDraw.Draw(page)
        mx, my, cw, ch = 10, 15, 95, 89
        for gi, cp in enumerate(preview_cards):
            xi = int((mx + (gi % 2) * cw) * 4)
            yi = int((my + (gi // 2) * ch) * 4)
            page.paste(cp.resize((cw*4, ch*4), resample=Image.Resampling.BILINEAR), (xi, yi))
            if show_cut_lines:
                pd_draw.rectangle([xi, yi, xi+cw*4, yi+ch*4], outline=(180, 180, 180), width=1)
        buf_a4 = io.BytesIO()
        page.resize((420, 594), resample=Image.Resampling.BILINEAR).save(buf_a4, 'JPEG', quality=82)
        st.image(buf_a4.getvalue(), caption="前 6 筆 A4 整頁預覽", width=500)

    st.divider()

    # ══════════════════════════════════════════════════════════
    # 批次生成 PDF
    # ══════════════════════════════════════════════════════════
    if st.button("🚀 開始批次排版並生成 PDF", type="primary"):
        with st.spinner("正在建構 A4 2x3 排版..."):
            df        = pd.read_csv(io.BytesIO(st.session_state.csv_cache))
            zip_index_b, all_paths_b, zf_b = build_zip_index(st.session_state.zip_bytes_cache)
            st.sidebar.caption(f"📦 ZIP {len(all_paths_b)} 張")

            pdf_buf  = io.BytesIO()
            c        = canvas.Canvas(pdf_buf, pagesize=A4)
            cur_page = Image.new('RGB', (840, 1188), (255, 255, 255))
            pg_draw  = ImageDraw.Draw(cur_page)
            mx, my, cw, ch = 10, 15, 95, 89
            total    = len(df)
            pbar     = st.progress(0)
            previews = []
            miss_list = []
            font_log  = {}   # 記錄哪些卡片用了備用字型

            for idx, row in df.iterrows():
                card_pil, matched, _, font_used = generate_card(
                    row, idx, zf_b, zip_index_b,
                    g_font_size_content, g_font_size_source,
                    bg_darkness, auto_darkness,
                    text_color, line_spacing, stroke_width, glow_strength,
                    st.session_state.card_overrides
                )
                if not matched:
                    miss_list.append(str(row.get('Image_Name', idx)))
                if font_used and '思源黑體 Heavy' not in font_used:
                    font_log[int(idx) + 1] = os.path.basename(font_used)

                gi    = idx % 6
                col_i = gi % 2
                row_i = gi // 2
                xp    = (mx + col_i * cw) * mm
                yp    = (297 - my - (row_i + 1) * ch) * mm

                buf = io.BytesIO()
                card_pil.save(buf, format='JPEG', quality=88)
                buf.seek(0)
                c.drawImage(ImageReader(buf), xp, yp, width=cw*mm, height=ch*mm)
                if show_cut_lines:
                    c.setStrokeColorRGB(0.7, 0.7, 0.7)
                    c.setLineWidth(0.3)
                    c.rect(xp, yp, cw*mm, ch*mm)

                xi = int((mx + col_i * cw) * 4)
                yi = int((my + row_i  * ch) * 4)
                cur_page.paste(
                    card_pil.resize((cw*4, ch*4), resample=Image.Resampling.BILINEAR),
                    (xi, yi)
                )
                if show_cut_lines:
                    pg_draw.rectangle([xi, yi, xi+cw*4, yi+ch*4],
                                      outline=(180, 180, 180), width=1)

                pbar.progress((idx + 1) / total)

                if gi == 5 or idx == total - 1:
                    c.showPage()
                    prev = cur_page.resize((420, 594), resample=Image.Resampling.BILINEAR)
                    b2   = io.BytesIO()
                    prev.save(b2, 'JPEG', quality=72)
                    previews.append(b2.getvalue())
                    cur_page = Image.new('RGB', (840, 1188), (255, 255, 255))
                    pg_draw  = ImageDraw.Draw(cur_page)

            c.save(); pdf_buf.seek(0)
            st.session_state.pdf_data           = pdf_buf.getvalue()
            st.session_state.preview_bytes_list = previews
            st.session_state.last_params        = sidebar_params.copy()

            custom_count = len(st.session_state.card_overrides)
            st.success(
                f"🎉 完成！{len(previews)} 頁 A4，"
                f"其中 {custom_count} 張使用個別客製化設定。"
            )
            if miss_list:
                st.warning(f"⚠️ {len(miss_list)} 筆找不到底圖：{'、'.join(miss_list[:20])}")
            if font_log:
                st.info(
                    f"ℹ️ {len(font_log)} 張卡片切換了備用字型：\n" +
                    "\n".join(f"  第 {n} 筆 → {f}" for n, f in list(font_log.items())[:10])
                )

elif not (uploaded_csv and uploaded_zip):
    st.info("💡 請在上方分別拖入 csv 與 zip 素材包。")

# ══════════════════════════════════════════════════════════════
# 結果顯示
# ══════════════════════════════════════════════════════════════
if st.session_state.pdf_data and st.session_state.preview_bytes_list:
    st.write("---")
    col_dl, col_view = st.columns([1, 2])
    with col_dl:
        st.subheader("📥 檔案下載")
        st.download_button(
            label="🍀 下載 2x3 A4 完美列印 PDF",
            data=st.session_state.pdf_data,
            file_name="soka_encouragement_cards_A4.pdf",
            mime="application/pdf",
            type="primary",
        )
        st.info("💡 列印時請設為「實際大小(100%)」或「不縮放」。")
    with col_view:
        st.subheader("👀 A4 2x3 完整排版預覽")
        total_p     = len(st.session_state.preview_bytes_list)
        page_select = st.slider("切換預覽頁數", 1, total_p, 1) if total_p > 1 else 1
        st.write(f"📄 第 **{page_select}** / {total_p} 頁")
        st.image(st.session_state.preview_bytes_list[page_select - 1],
                 caption=f"第 {page_select} 頁 A4 實印排版")
