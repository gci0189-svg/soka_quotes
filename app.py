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

st.set_page_config(page_title="?萄曌撠?Ｙ???, layout="wide", page_icon="??")
st.title("?? ?萄曌撠 A4 2x3 ?Ｙ???)

# ??????????????????????????????????????????????????????????????
# 摮?蝟餌絞嚗?亙???Fallback
# ??????????????????????????????????????????????????????????????
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_DIR = os.path.join(BASE_DIR, "saved_card_settings")
os.makedirs(SAVE_DIR, exist_ok=True)

FONT_CHAIN = [
    "fonts/??暺? Heavy.otf",
    "??暺? Heavy.otf",
    "fonts/皞見暺? Heavy.otf",
    "皞見暺? Heavy.otf",
    "fonts/皞???.otf",
    "皞???.otf",
    "fonts/NotoSansTC-Regular.ttf",
    "NotoSansTC-Regular.ttf",
    "fonts/MSJH.ttf",
    "MSJH.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]

HANDWRITING_UNSAFE_CHARS = set("暻潮瑤銋????領???????乒??????)


def resolve_font_path(path: str) -> str:
    if not path:
        return path
    if os.path.isabs(path):
        return path
    return os.path.join(BASE_DIR, path)


@st.cache_resource
def load_font(path: str, size: int, index: int = 0):
    try:
        real_path = resolve_font_path(path)
        if real_path and os.path.exists(real_path):
            return ImageFont.truetype(real_path, size, index=index)
    except Exception:
        pass
    return None


def _font_index(path: str) -> int:
    return 0


def _glyph_signature(font, ch: str):
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
    font = load_font(font_path, size, _font_index(font_path))
    if font is None:
        return False

    missing_signatures = set()
    for missing_ch in ("\uFFFF", "\uFFFE", "\U0010FFFF"):
        sig = _glyph_signature(font, missing_ch)
        if sig is not None:
            missing_signatures.add(sig)

    for ch in text:
        if ch in (" ", "\n", "\u200b"):
            continue
        sig = _glyph_signature(font, ch)
        if sig is None:
            return False
        if missing_signatures and sig in missing_signatures:
            return False
    return True


def pick_font_for_text(text: str, size: int):
    text = str(text or "")
    has_unsafe_char = any(ch in HANDWRITING_UNSAFE_CHARS for ch in text)

    for path in FONT_CHAIN:
        if not path:
            continue
        if has_unsafe_char and "??暺? Heavy" in path:
            continue
        if text_has_all_glyphs(text, path, size):
            font = load_font(path, size, _font_index(path))
            if font:
                return font, path

    for path in FONT_CHAIN:
        if has_unsafe_char and "??暺? Heavy" in path:
            continue
        font = load_font(path, size, _font_index(path))
        if font:
            return font, path
    return ImageFont.load_default(), "Pillow-default"


@st.cache_resource
def pick_font_for_char(ch: str, size: int, preferred_path: str = ""):
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
    line = text.strip()
    if not line:
        return []

    total_w = text_width_fallback(draw, line, size, preferred_path)
    if total_w <= max_w:
        return [line]

    n_chars = len(line)
    close_punct = set("嚗?嚗?嚗?.!?;:)嚗?)
    open_punct = set("嚗?")
    protected_words = [
        "隞暻?, "?獐", "?箔?暻?, "?除", "撠店", "頨恍?", "?像", "?末", "?楝",
        "敹?, "?亥孛", "鈭", "頧?", "銝敹?, "曌絲", "?脰?", "?",
        "?方?", "?芸楛", "敹葉", "銝縑", "?", "??, "?箸", "銵函",
        "?芰", "?典?", "閮?", "?琿???, "??", "?", "?", "?單?",
    ]
    weak_tail_chars = set("?典?????????")

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
                    if piece[-1] in "嚗?嚗?嚗?:
                        new_score -= 5000
                    elif piece[-1] in "????:
                        new_score -= 1800
                    if end < n_chars and line[end] in close_punct:
                        new_score += 8000
                    if end < n_chars and line[end] in "????:
                        new_score -= 1000
                    if piece.count("??) != piece.count("??) or piece.count("??) != piece.count("??):
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
                if left[-1] in "嚗?嚗?嚗???:
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
    lines = []
    for part in text.split("\n"):
        lines.extend(safe_wrap_line(part, size, max_w, draw, preferred_path))
    return lines if lines else [text.strip() or text]


# ??????????????????????????????????????????????????????????????
# 閮剖? JSON嚗璈??摮?+ ?臬/?臬
# ??????????????????????????????????????????????????????????????
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


def make_settings_payload(overrides: dict, dataset_key: str = "", csv_name: str = "", zip_name: str = "") -> dict:
    return {
        "version": 1,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "dataset_key": dataset_key,
        "csv_name": csv_name,
        "zip_name": zip_name,
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


def save_card_overrides(dataset_key: str, overrides: dict, csv_name: str = "", zip_name: str = ""):
    if not dataset_key:
        return
    payload = make_settings_payload(overrides, dataset_key, csv_name, zip_name)
    with open(settings_path(dataset_key), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def parse_uploaded_settings(uploaded_file):
    try:
        data = json.loads(uploaded_file.read().decode("utf-8"))
        if isinstance(data, dict) and "card_overrides" in data:
            return normalize_overrides(data.get("card_overrides")), data
        return normalize_overrides(data), {}
    except Exception as exc:
        raise ValueError(f"閮剖? JSON 霈?仃??{exc}") from exc


# ??????????????????????????????????????????????????????????????
# ?湧?甈?# ??????????????????????????????????????????????????????????????
st.sidebar.header("? 撠閬死隤踵?Ｘ")

st.sidebar.markdown("**?? ?典???閮剖?**")
g_font_size_content = st.sidebar.slider("甇??摮?憭批?嚗撅嚗?, 20, 100, 60, step=1)
g_font_size_source = st.sidebar.slider("?箄?摮?憭批?", 14, 70, 40, step=1)
line_spacing = st.sidebar.slider("銵??", 1.2, 4.5, 2.0, step=0.1)
text_color = st.sidebar.color_picker("??憿", "#FFFFFF")

st.sidebar.markdown("---")
st.sidebar.markdown("**?? ?閮剖?**")
auto_darkness = st.sidebar.checkbox("???箄?芸??桃蔗嚗?摨?鈭桀漲隤踵嚗?, value=False)
if auto_darkness:
    st.sidebar.caption("?箄璅∪?嚗?摨?鈭桀漲?芸?閮??箸?嚗????孵?蝘駁???)
    bg_darkness = st.sidebar.slider("??敺株矽?宏??+ ?楛 / - 皜滓嚗?, -0.30, 0.30, 0.0, step=0.05)
else:
    bg_darkness = st.sidebar.slider("???桃蔗暺舀楚摨佗?摰?芾?嚗?, 0.0, 1.0, 0.0, step=0.05)

st.sidebar.markdown("---")
st.sidebar.markdown("**????皜撘瑕?**")
stroke_width = st.sidebar.slider("????撖砍漲", 0, 10, 5, step=1)
glow_strength = st.sidebar.slider("???澆?撘瑕漲嚗?=??嚗?, 0, 8, 0, step=1)

st.sidebar.markdown("---")
show_cut_lines = st.sidebar.checkbox("憿舐內 A4 鋆???", value=True)

sidebar_params = dict(
    g_font_size_content=g_font_size_content,
    g_font_size_source=g_font_size_source,
    line_spacing=line_spacing,
    text_color=text_color,
    bg_darkness=bg_darkness,
    auto_darkness=auto_darkness,
    stroke_width=stroke_width,
    glow_strength=glow_strength,
    show_cut_lines=show_cut_lines,
)

# ??????????????????????????????????????????????????????????????
# 銝餌?Ｖ???# ??????????????????????????????????????????????????????????????
col1, col2 = st.columns(2)
with col1:
    uploaded_csv = st.file_uploader("1. 銝隤?銵冽 (soka_quotes.csv)", type=["csv"])
with col2:
    uploaded_zip = st.file_uploader("2. 銝蝝?憯葬??(zip)", type=["zip"])

for k, v in [
    ("pdf_data", None),
    ("preview_bytes_list", []),
    ("last_params", None),
    ("zip_bytes_cache", None),
    ("csv_cache", None),
    ("zip_index_cache", None),
    ("card_overrides", {}),
    ("_dataset_key", ""),
]:
    if k not in st.session_state:
        st.session_state[k] = v


# ??????????????????????????????????????????????????????????????
# 撌亙?賢?
# ??????????????????????????????????????????????????????????????
def hex_to_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def smart_dark(img_rgb: Image.Image) -> float:
    w, h = img_rgb.size
    crop = img_rgb.crop((int(w * .3), int(h * .25), int(w * .7), int(h * .75))).convert("L")
    data = list(crop.getdata())
    avg = sum(data) / len(data)
    return round(min(max(0.20 + (avg / 255) * 0.35, 0.15), 0.55), 2)


def smart_wrap(text: str, font, max_w: int, draw) -> list:
    break_after = set("??嚗佗?")
    chunks, buf = [], ""
    for ch in text:
        buf += ch
        if ch in break_after:
            chunks.append(buf)
            buf = ""
    if buf:
        chunks.append(buf)

    def width(t):
        return draw.textbbox((0, 0), t, font=font)[2]

    lines, cur = [], ""
    for chunk in chunks:
        if width(cur + chunk) <= max_w:
            cur += chunk
        else:
            if cur:
                lines.append(cur)
                cur = ""
            for ch in chunk:
                if width(cur + ch) <= max_w:
                    cur += ch
                else:
                    if cur:
                        lines.append(cur)
                    cur = ch
    if cur:
        lines.append(cur)

    if len(lines) == 1 and len(lines[0]) >= 12:
        s = lines[0]
        mid = len(s) // 2
        best = mid
        for off in range(0, mid + 1):
            found = False
            for pos in [mid - off, mid + off + 1]:
                if 0 < pos <= len(s) and s[pos - 1] in break_after:
                    best = pos
                    found = True
                    break
            if found:
                break
        lines = [s[:best], s[best:]] if s[best:] else [s]

    if len(lines) >= 2 and len(lines[-1]) <= 3:
        merged = lines[-2] + lines[-1]
        mid = len(merged) // 2
        lines = lines[:-2] + [merged[:mid], merged[mid:]]

    return lines if lines else [text]


def draw_text_pro(draw, pos, text, font, fill_rgb, stroke_w=3, img=None, glow_str=0):
    x, y = pos
    r, g, b = fill_rgb
    bright = r * 0.299 + g * 0.587 + b * 0.114
    sc = (15, 15, 15, 220) if bright > 128 else (240, 240, 240, 200)

    if glow_str > 0 and img is not None:
        gl = Image.new("RGBA", img.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(gl)
        gd.text((x, y), text, font=font, fill=(r, g, b, 160))
        img.alpha_composite(gl.filter(ImageFilter.GaussianBlur(radius=glow_str)))
        draw = ImageDraw.Draw(img, "RGBA")

    if stroke_w > 0:
        for dx in range(-stroke_w, stroke_w + 1):
            for dy in range(-stroke_w, stroke_w + 1):
                if abs(dx) + abs(dy) <= stroke_w + 1 and not (dx == 0 and dy == 0):
                    draw.text((x + dx, y + dy), text, font=font, fill=sc)

    draw.text((x, y), text, font=font, fill=(r, g, b, 255))


def build_zip_index(zip_bytes: bytes):
    img_ext = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
    index, all_paths = {}, []
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    for name in zf.namelist():
        if "__MACOSX" in name or name.endswith("/"):
            continue
        bn = os.path.basename(name)
        if not bn or bn.startswith("."):
            continue
        if os.path.splitext(bn)[1].lower() not in img_ext:
            continue
        all_paths.append(name)
        stem = bn
        while os.path.splitext(stem)[1].lower() in img_ext:
            stem = os.path.splitext(stem)[0]
        for key in [bn.lower(), stem.lower()] + [(stem + s).lower() for s in ["", ".jpg", ".webp", ".png", ".jpg.webp"]]:
            index.setdefault(key, name)
        for num in re.findall(r"\d+", stem):
            n = int(num)
            for k in [num, str(n), str(n).zfill(2), str(n).zfill(3), str(n).zfill(4)]:
                index.setdefault(k, name)
            m = re.match(r"^([a-zA-Z_\-]+)(\d+)$", stem)
            if m:
                pfx = m.group(1)
                for pad in [0, 2, 3, 4]:
                    kk = pfx + (str(n) if pad == 0 else str(n).zfill(pad))
                    for sfx in ["", ".jpg", ".webp", ".png", ".jpg.webp"]:
                        index.setdefault((kk + sfx).lower(), name)
    return index, all_paths, zf


def find_in_index(raw: str, index: dict):
    img_ext = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
    raw = str(raw).strip()
    stem_raw = raw
    while os.path.splitext(stem_raw)[1].lower() in img_ext:
        stem_raw = os.path.splitext(stem_raw)[0]
    candidates = [raw.lower(), stem_raw.lower()] + [(stem_raw + s).lower() for s in ["", ".jpg", ".webp", ".jpg.webp"]]
    for num in re.findall(r"\d+", stem_raw):
        n = int(num)
        for k in [num, str(n), str(n).zfill(2), str(n).zfill(3), str(n).zfill(4)]:
            candidates.append(k)
        m = re.match(r"^([a-zA-Z_\-]+)", stem_raw)
        if m:
            pfx = m.group(1)
            for pad in [0, 2, 3, 4]:
                kk = pfx + (str(n) if pad == 0 else str(n).zfill(pad))
                for sfx in ["", ".jpg", ".webp", ".jpg.webp"]:
                    candidates.append((kk + sfx).lower())
    return next((index[c] for c in candidates if c in index), None)


# ??????????????????????????????????????????????????????????????
# ?詨?嚗??撘萄??# ??????????????????????????????????????????????????????????????
def generate_card(row, row_idx, zf, zip_index,
                  g_size_content, size_source,
                  bg_darkness, auto_darkness_on,
                  text_color_hex, line_spacing_mult,
                  stroke_w, glow_str, overrides: dict):
    override = overrides.get(str(row_idx), {})
    custom_text = override.get("content", None)
    font_size = override.get("font_size", g_size_content)

    matched = find_in_index(row["Image_Name"], zip_index)
    if matched:
        try:
            card = Image.open(io.BytesIO(zf.read(matched))).convert("RGBA")
        except Exception:
            card = Image.new("RGBA", (1000, 1000), (220, 217, 210, 255))
    else:
        card = Image.new("RGBA", (1000, 1000), (220, 217, 210, 255))
    card = card.resize((1000, 1000), resample=Image.Resampling.BILINEAR)

    if auto_darkness_on:
        base = smart_dark(card.convert("RGB"))
        actual = round(min(max(base + bg_darkness, 0.0), 0.85), 2)
    else:
        actual = bg_darkness
    if actual > 0:
        overlay = Image.new("RGBA", (1000, 1000), (0, 0, 0, int(255 * actual)))
        card = Image.alpha_composite(card, overlay)

    draw = ImageDraw.Draw(card, "RGBA")
    fill_rgb = hex_to_rgb(text_color_hex)
    raw_content = str(row.get("Content", "")).replace(" ", "")

    if custom_text is not None:
        full_text_for_check = custom_text.replace("\n", "")
        font_content, font_used = pick_font_for_text(full_text_for_check, font_size)
        lines = manual_wrap_safe(custom_text, font_size, 840, draw, font_used)
    else:
        font_content, font_used = pick_font_for_text(raw_content, font_size)
        lines = smart_wrap(raw_content, font_content, 840, draw)
        guarded_lines = []
        for line in lines:
            guarded_lines.extend(safe_wrap_line(line, font_size, 840, draw, font_used))
        lines = guarded_lines if guarded_lines else lines

    src = str(row.get("Source", ""))
    if src and src != "nan":
        font_source, _ = pick_font_for_text(src, size_source)
    else:
        font_source, _ = pick_font_for_text("", size_source)

    bh = draw.textbbox((0, 0), "擃?, font=font_content)
    lh = max(1, (bh[3] - bh[1])) * line_spacing_mult
    total_h = len(lines) * lh
    start_y = (1000 - total_h) / 2 - 20

    for i, line in enumerate(lines):
        bx = draw.textbbox((0, 0), line, font=font_content)
        line_w = bx[2] - bx[0]
        x = (1000 - line_w) / 2
        y = start_y + i * lh
        draw_text_pro(draw, (x, y), line, font_content, fill_rgb, stroke_w=stroke_w, img=card, glow_str=glow_str)
        draw = ImageDraw.Draw(card, "RGBA")

    if src and src != "nan":
        bs = draw.textbbox((0, 0), src, font=font_source)
        src_w = bs[2] - bs[0]
        xs = (1000 - src_w) / 2
        draw_text_pro(draw, (xs, 900), src, font_source, fill_rgb, stroke_w=stroke_w, img=card, glow_str=glow_str)

    return card.convert("RGB"), matched, actual, font_used


# ??????????????????????????????????????????????????????????????
# 敹怠? zip & csv + ?芸?頛?祆?閮剖?
# ??????????????????????????????????????????????????????????????
if uploaded_csv and uploaded_zip:
    if st.session_state.get("_csv_name") != uploaded_csv.name:
        st.session_state["_csv_name"] = uploaded_csv.name
        st.session_state.csv_cache = uploaded_csv.read()
    if st.session_state.get("_zip_name") != uploaded_zip.name:
        st.session_state["_zip_name"] = uploaded_zip.name
        st.session_state.zip_bytes_cache = uploaded_zip.read()
        idx_b, paths_b, zf_b = build_zip_index(st.session_state.zip_bytes_cache)
        st.session_state.zip_index_cache = (idx_b, paths_b, zf_b)

    dataset_key = get_dataset_key(st.session_state.csv_cache, uploaded_zip.name)
    if st.session_state.get("_dataset_key") != dataset_key:
        st.session_state["_dataset_key"] = dataset_key
        st.session_state.card_overrides = load_card_overrides(dataset_key)


# ??????????????????????????????????????????????????????????????
# 閮剖?瑼??/ ?臬
# ??????????????????????????????????????????????????????????????
if uploaded_csv and uploaded_zip:
    st.subheader("? ??∠?閮剖?")
    setting_col1, setting_col2, setting_col3 = st.columns([1, 1, 1])

    with setting_col1:
        payload = make_settings_payload(
            st.session_state.card_overrides,
            st.session_state.get("_dataset_key", ""),
            st.session_state.get("_csv_name", ""),
            st.session_state.get("_zip_name", ""),
        )
        st.download_button(
            "漎? 銝?閮剖? JSON",
            data=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name=f"soka_card_settings_{st.session_state.get('_dataset_key', 'manual')}.json",
            mime="application/json",
            help="銝??桀??????亥??桀撐摮?閮剖?嚗?銝活?臬??,
        )

    with setting_col2:
        uploaded_settings = st.file_uploader(
            "漎? 銝閮剖? JSON",
            type=["json"],
            key="settings_json_uploader",
            help="?臬銋?銝??身摰?JSON??,
        )
        if uploaded_settings is not None:
            try:
                imported_overrides, meta = parse_uploaded_settings(uploaded_settings)
                st.session_state.card_overrides = imported_overrides
                save_card_overrides(
                    st.session_state.get("_dataset_key", ""),
                    st.session_state.card_overrides,
                    st.session_state.get("_csv_name", ""),
                    st.session_state.get("_zip_name", ""),
                )
                st.success(f"撌脣??{len(imported_overrides)} 撘萄閮剖???)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    with setting_col3:
        st.caption(f"?桀?撌脣恥鋆賢?嚗len(st.session_state.card_overrides)} 撘?)
        if st.button("?完 皜征?桀?閮剖?"):
            st.session_state.card_overrides = {}
            save_card_overrides(
                st.session_state.get("_dataset_key", ""),
                st.session_state.card_overrides,
                st.session_state.get("_csv_name", ""),
                st.session_state.get("_zip_name", ""),
            )
            st.rerun()


# ??????????????????????????????????????????????????????????????
# 閮箸
# ??????????????????????????????????????????????????????????????
if uploaded_csv and uploaded_zip:
    with st.expander("?? 閮箸嚗IP ?批捆 & ??", expanded=False):
        if st.button("?瑁?閮箸"):
            idx_d, paths_d, zf_d = st.session_state.zip_index_cache
            df_d = pd.read_csv(io.BytesIO(st.session_state.csv_cache))
            st.write(f"ZIP ???賂?{len(paths_d)}")
            st.code("\n".join(paths_d[:20]))
            rows_out = []
            for _, r in df_d.head(10).iterrows():
                hit = find_in_index(r["Image_Name"], idx_d)
                rows_out.append({"Image_Name": str(r["Image_Name"]), "??蝯?": hit or "???曆???})
            st.table(pd.DataFrame(rows_out))


# ??????????????????????????????????????????????????????????????
# ?單??汗 + ??∠?摰Ｚˊ??# ??????????????????????????????????????????????????????????????
if uploaded_csv and uploaded_zip and st.session_state.zip_index_cache:
    idx_p, _, zf_p = st.session_state.zip_index_cache
    df_p = pd.read_csv(io.BytesIO(st.session_state.csv_cache))
    max_row = len(df_p) - 1

    tab_single, tab_a4 = st.tabs(["?儭??桀撐?汗 & ?摰Ｚˊ??, "?? A4 ?湧??汗嚗?6蝑?"])

    with tab_single:
        c_left, c_right = st.columns([1, 1])

        with c_left:
            preview_row = st.number_input(
                "?汗蝚砍嗾蝑???0 韏瑞?嚗?,
                min_value=0,
                max_value=max_row,
                value=0,
                step=1,
                key="preview_row_num",
            )
            row_p = df_p.iloc[int(preview_row)]
            row_key = str(preview_row)
            override = st.session_state.card_overrides.get(row_key, {})

            st.markdown("---")
            st.markdown("**?? ??∠?摰Ｚˊ??*")

            original_text = str(row_p.get("Content", "")).replace(" ", "")
            default_text = override.get("content", original_text)
            custom_text = st.text_area(
                "???瑕嚗nter ??嚗?蝛箏??Ｗ儔?箄?瑁?嚗?,
                value=default_text,
                height=140,
                key=f"text_area_{preview_row}",
                help="?湔??Enter ????株?憭芷嚗?閬質? PDF ???摰????,
            )

            use_custom_size = st.checkbox(
                "雿輻甇文撠惇摮?憭批?",
                value=("font_size" in override),
                key=f"use_custom_size_{preview_row}",
            )
            if use_custom_size:
                current_size = override.get("font_size", g_font_size_content)
                custom_size = st.slider(
                    "甇文?迤??擃之撠?,
                    min_value=20,
                    max_value=70,
                    value=int(current_size),
                    step=2,
                    key=f"size_slider_{preview_row}",
                )
            else:
                custom_size = g_font_size_content
                st.slider(
                    "甇文?迤??擃之撠?頝?典?嚗?,
                    min_value=20,
                    max_value=70,
                    value=int(g_font_size_content),
                    step=2,
                    disabled=True,
                    key=f"size_slider_global_{preview_row}",
                )

            entry = {}
            if custom_text.strip() and custom_text != original_text:
                entry["content"] = custom_text
            if use_custom_size:
                entry["font_size"] = custom_size
            if entry:
                st.session_state.card_overrides[row_key] = entry
            else:
                st.session_state.card_overrides.pop(row_key, None)

            save_card_overrides(
                st.session_state.get("_dataset_key", ""),
                st.session_state.card_overrides,
                st.session_state.get("_csv_name", ""),
                st.session_state.get("_zip_name", ""),
            )

            col_save, col_reset = st.columns(2)
            with col_save:
                if st.button("? 撌脰?摮?, key=f"save_{preview_row}"):
                    st.success(f"??蝚?{preview_row} 蝑?身摰歇?冽摮葉嚗?撌脣神?交璈?JSON嚗?)

            with col_reset:
                if st.button("?? ???身", key=f"reset_{preview_row}"):
                    st.session_state.card_overrides.pop(row_key, None)
                    save_card_overrides(
                        st.session_state.get("_dataset_key", ""),
                        st.session_state.card_overrides,
                        st.session_state.get("_csv_name", ""),
                        st.session_state.get("_zip_name", ""),
                    )
                    st.rerun()

            if st.session_state.card_overrides:
                st.markdown("---")
                st.markdown(f"**?? 撌脣恥鋆賢?嚗len(st.session_state.card_overrides)} 撘?*")
                for k, v in sorted(st.session_state.card_overrides.items(), key=lambda x: int(x[0])):
                    tags = []
                    if "content" in v:
                        tags.append("???瑕")
                    if "font_size" in v:
                        tags.append(f"摮? {v['font_size']}")
                    st.caption(f"蝚?{k} 蝑?{'??.join(tags)}")

        with c_right:
            live_override = entry.copy()
            live_override["font_size"] = custom_size

            card_p, _, used_dark, font_used = generate_card(
                row_p,
                preview_row,
                zf_p,
                idx_p,
                custom_size,
                g_font_size_source,
                bg_darkness,
                auto_darkness,
                text_color,
                line_spacing,
                stroke_width,
                glow_strength,
                {row_key: live_override},
            )
            buf_p = io.BytesIO()
            card_p.save(buf_p, format="JPEG", quality=88)

            font_label = os.path.basename(font_used) if font_used else "?身"
            st.image(
                buf_p.getvalue(),
                caption=f"蝚?{preview_row} 蝑?嚚??桃蔗 {used_dark:.2f} 嚚?摮? {custom_size} 嚚?摮?嚗font_label}",
                width=420,
            )

    with tab_a4:
        st.caption("???單?皜脫???6 蝑?蝣箄??湧?閬死????)
        preview_cards = []
        for i in range(min(6, len(df_p))):
            r = df_p.iloc[i]
            cp, _, _, _ = generate_card(
                r,
                i,
                zf_p,
                idx_p,
                g_font_size_content,
                g_font_size_source,
                bg_darkness,
                auto_darkness,
                text_color,
                line_spacing,
                stroke_width,
                glow_strength,
                st.session_state.card_overrides,
            )
            preview_cards.append(cp)

        page = Image.new("RGB", (840, 1188), (255, 255, 255))
        pd_draw = ImageDraw.Draw(page)
        mx, my, cw, ch = 10, 15, 95, 89
        for gi, cp in enumerate(preview_cards):
            xi = int((mx + (gi % 2) * cw) * 4)
            yi = int((my + (gi // 2) * ch) * 4)
            page.paste(cp.resize((cw * 4, ch * 4), resample=Image.Resampling.BILINEAR), (xi, yi))
            if show_cut_lines:
                pd_draw.rectangle([xi, yi, xi + cw * 4, yi + ch * 4], outline=(180, 180, 180), width=1)
        buf_a4 = io.BytesIO()
        page.resize((420, 594), resample=Image.Resampling.BILINEAR).save(buf_a4, "JPEG", quality=82)
        st.image(buf_a4.getvalue(), caption="??6 蝑?A4 ?湧??汗", width=500)

    st.divider()

    if st.button("?? ???寞活??銝衣???PDF", type="primary"):
        with st.spinner("甇?撱箸? A4 2x3 ??..."):
            df = pd.read_csv(io.BytesIO(st.session_state.csv_cache))
            zip_index_b, all_paths_b, zf_b = build_zip_index(st.session_state.zip_bytes_cache)
            st.sidebar.caption(f"? ZIP {len(all_paths_b)} 撘?)

            pdf_buf = io.BytesIO()
            c = canvas.Canvas(pdf_buf, pagesize=A4)
            cur_page = Image.new("RGB", (840, 1188), (255, 255, 255))
            pg_draw = ImageDraw.Draw(cur_page)
            mx, my, cw, ch = 10, 15, 95, 89
            total = len(df)
            pbar = st.progress(0)
            previews = []
            miss_list = []
            font_log = {}

            for idx, row in df.iterrows():
                card_pil, matched, _, font_used = generate_card(
                    row,
                    idx,
                    zf_b,
                    zip_index_b,
                    g_font_size_content,
                    g_font_size_source,
                    bg_darkness,
                    auto_darkness,
                    text_color,
                    line_spacing,
                    stroke_width,
                    glow_strength,
                    st.session_state.card_overrides,
                )
                if not matched:
                    miss_list.append(str(row.get("Image_Name", idx)))
                if font_used and "?怨" not in font_used:
                    font_log[int(idx) + 1] = os.path.basename(font_used)

                gi = idx % 6
                col_i = gi % 2
                row_i = gi // 2
                xp = (mx + col_i * cw) * mm
                yp = (297 - my - (row_i + 1) * ch) * mm

                buf = io.BytesIO()
                card_pil.save(buf, format="JPEG", quality=88)
                buf.seek(0)
                c.drawImage(ImageReader(buf), xp, yp, width=cw * mm, height=ch * mm)
                if show_cut_lines:
                    c.setStrokeColorRGB(0.7, 0.7, 0.7)
                    c.setLineWidth(0.3)
                    c.rect(xp, yp, cw * mm, ch * mm)

                xi = int((mx + col_i * cw) * 4)
                yi = int((my + row_i * ch) * 4)
                cur_page.paste(card_pil.resize((cw * 4, ch * 4), resample=Image.Resampling.BILINEAR), (xi, yi))
                if show_cut_lines:
                    pg_draw.rectangle([xi, yi, xi + cw * 4, yi + ch * 4], outline=(180, 180, 180), width=1)

                pbar.progress((idx + 1) / total)

                if gi == 5 or idx == total - 1:
                    c.showPage()
                    prev = cur_page.resize((420, 594), resample=Image.Resampling.BILINEAR)
                    b2 = io.BytesIO()
                    prev.save(b2, "JPEG", quality=72)
                    previews.append(b2.getvalue())
                    cur_page = Image.new("RGB", (840, 1188), (255, 255, 255))
                    pg_draw = ImageDraw.Draw(cur_page)

            c.save()
            pdf_buf.seek(0)
            st.session_state.pdf_data = pdf_buf.getvalue()
            st.session_state.preview_bytes_list = previews
            st.session_state.last_params = sidebar_params.copy()

            custom_count = len(st.session_state.card_overrides)
            st.success(f"?? 摰?嚗len(previews)} ??A4嚗銝?{custom_count} 撘萎蝙?典摰Ｚˊ?身摰?)
            if miss_list:
                st.warning(f"?? {len(miss_list)} 蝑銝摨?嚗'??.join(miss_list[:20])}")
            if font_log:
                st.info(
                    f"?對? {len(font_log)} 撘萄?????摮?嚗n"
                    + "\n".join(f"  蝚?{n} 蝑???{f}" for n, f in list(font_log.items())[:10])
                )

elif not (uploaded_csv and uploaded_zip):
    st.info("? 隢銝?? csv ??zip 蝝???)


# ??????????????????????????????????????????????????????????????
# 蝯?憿舐內
# ??????????????????????????????????????????????????????????????
if st.session_state.pdf_data and st.session_state.preview_bytes_list:
    st.write("---")
    col_dl, col_view = st.columns([1, 2])
    with col_dl:
        st.subheader("? 瑼?銝?")
        st.download_button(
            label="?? 銝? 2x3 A4 摰?? PDF",
            data=st.session_state.pdf_data,
            file_name="soka_encouragement_cards_A4.pdf",
            mime="application/pdf",
            type="primary",
        )
        st.info("? ???閮剔?祕?之撠?100%)????蝮格??)
    with col_view:
        st.subheader("?? A4 2x3 摰???汗")
        total_p = len(st.session_state.preview_bytes_list)
        page_select = st.slider("???汗?", 1, total_p, 1) if total_p > 1 else 1
        st.write(f"?? 蝚?**{page_select}** / {total_p} ??)
        st.image(
            st.session_state.preview_bytes_list[page_select - 1],
            caption=f"蝚?{page_select} ??A4 撖血??",
        )
