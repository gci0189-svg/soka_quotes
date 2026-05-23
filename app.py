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
# 調整為直接讀取根目錄字型檔案路徑
FONT_CHAIN = [
    ("思源黑體 Medium.ttf",     0),   # 主字型：思源黑體 Medium（清晰有力）
    ("源樣黑體 Heavy.otf",      0),   # 備用 1：源樣黑體 Heavy（粗體強調）
    ("源泉圓體.otf",            0),   # 備用 2：源泉圓體（圓潤）
    ("芫荽.ttf",               0),   # 備用 3：芫荽手寫
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),  # 系統保底
]

# module-level 字型快取（不用 st.cache，避免序列化問題）
_font_obj_cache: dict = {}

def _get_font(path: str, size: int, index: int = 0):
    """載入字型物件，快取於 module level dict，失敗回傳 None。"""
    key = (path, size, index)
    if key not in _font_obj_cache:
        try:
            if path and os.path.exists(path):
                _font_obj_cache[key] = ImageFont.truetype(path, size, index=index)
            else:
                _font_obj_cache[key] = None
        except Exception:
            _font_obj_cache[key] = None
    return _font_obj_cache[key]

# module-level 缺字偵測快取（key = (font_path, char)）
_glyph_ok_cache: dict = {}

def _char_renders(font_obj, char: str) -> bool:
    """
    特徵比對法偵測缺字（極高準確度）：
    比對目標字元與該字型專屬的「缺字預留字元（如 \\ufffd, \\u0000）」渲染圖是否相同。
    若相同，或亮像素極少，則判定為不支援。
    """
    if font_obj is None:
        return False
    key = (id(font_obj), char)
    if key not in _glyph_ok_cache:
        try:
            # 1. 渲染目標字元
            img = Image.new('L', (60, 60), 0)
            d   = ImageDraw.Draw(img)
            d.text((5, 5), char, font=font_obj, fill=255)
            data = list(img.getdata())
            bright = sum(1 for p in data if p > 30)
            
            # 若基本上無亮度（極少亮點），代表為無法渲染的空白
            if bright <= 3:
                _glyph_ok_cache[key] = False
                return False
            
            # 2. 獲取/快取該字型的兩種常見「缺字豆腐塊/替代字元」渲染特徵
            tofu1_key = f"tofu1_{id(font_obj)}"  # \ufffd (常見替代字元)
            tofu2_key = f"tofu2_{id(font_obj)}"  # \u0000 (空控制字元)
            
            if tofu1_key not in _glyph_ok_cache:
                img_t1 = Image.new('L', (60, 60), 0)
                d_t1   = ImageDraw.Draw(img_t1)
                d_t1.text((5, 5), "\ufffd", font=font_obj, fill=255)
                _glyph_ok_cache[tofu1_key] = list(img_t1.getdata())
                
            if tofu2_key not in _glyph_ok_cache:
                img_t2 = Image.new('L', (60, 60), 0)
                d_t2   = ImageDraw.Draw(img_t2)
                d_t2.text((5, 5), "\u0000", font=font_obj, fill=255)
                _glyph_ok_cache[tofu2_key] = list(img_t2.getdata())
            
            tofu1_data = _glyph_ok_cache[tofu1_key]
            tofu2_data = _glyph_ok_cache[tofu2_key]
            
            # 3. 如果目標字元的渲染結果與任一種缺字豆腐塊特徵完全一致，代表該字型不支援
            if data == tofu1_data or data == tofu2_data:
                _glyph_ok_cache[key] = False
            else:
                _glyph_ok_cache[key] = True
        except Exception:
            _glyph_ok_cache[key] = False
    return _glyph_ok_cache[key]

def _text_all_render(font_obj, text: str) -> bool:
    """整句掃描：只要有一個字元無法渲染就回傳 False。"""
    for ch in text:
        if ch in (' ', '\n', '\u200b', '\r'):
            continue
        if not _char_renders(font_obj, ch):
            return False
    return True

def pick_font(text: str, size: int):
    """
    整句切換 Fallback：
    依 FONT_CHAIN 順序，找第一個能完整渲染整句的字型。
    回傳 (font_object, font_basename)
    """
    for path, idx in FONT_CHAIN:
        font = _get_font(path, size, idx)
        if font is None:
            continue
        if _text_all_render(font, text):
            return font, os.path.basename(path)
    # 終極保底：直接回傳最後一個能載入的字型
    for path, idx in reversed(FONT_CHAIN):
        font = _get_font(path, size, idx)
        if font:
            return font, os.path.basename(path)
    return ImageFont.load_default(), "default"

# ══════════════════════════════════════════════════════════════
# 側邊欄 (已依需求調整範圍與預設值)
# ══════════════════════════════════════════════════════════════
st.sidebar.header("🎨 小卡視覺調整面板")

st.sidebar.markdown("**📝 全局文字設定**")
g_font_size_content = st.sidebar.slider("正文字型大小（全局）", 20, 100, 60, step=1)
g_font_size_source  = st.sidebar.slider("出處字型大小", 14, 70, 40, step=1)
line_spacing        = st.sidebar.slider("行距倍數", 1.2, 4.5, 2.0, step=0.1)
text_color          = st.sidebar.color_picker("文字顏色", "#FFFFFF")

st.sidebar.markdown("---")
st.sidebar.markdown("**🌄 背景設定**")
auto_darkness = st.sidebar.checkbox("✨ 智能自動遮罩", value=False)
if auto_darkness:
    st.sidebar.caption("依底圖亮度自動計算，下方可微調。")
    bg_darkness = st.sidebar.slider("偏移量（+ 加深 / - 減淺）", -0.30, 0.30, 0.0, step=0.05)
else:
    bg_darkness = st.sidebar.slider("手動遮罩黯淡度", 0.0, 1.0, 0.0, step=0.05)

st.sidebar.markdown("---")
st.sidebar.markdown("**✨ 文字清晰強化**")
stroke_width  = st.sidebar.slider("文字描邊寬度", 0, 16, 8, step=1)
glow_strength = st.sidebar.slider("文字發光強度（0=關閉）", 0, 8, 0, step=1)

st.sidebar.markdown("---")
show_cut_lines = st.sidebar.checkbox("顯示 A4 裁切虛線", value=True)

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
]:
    if k not in st.session_state:
        st.session_state[k] = v

# ══════════════════════════════════════════════════════════════
# 核心智慧排版工具函式 (全新中文避頭尾自適應演算法)
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
    """
    智慧子句優先自適應排版演算法 (支援中文避頭尾與均勻切分)
    """
    # 避頭字元
    PUNCT_START_FORBIDDEN = set('，、。！？；：」』）｝〉》】」”’）,.;!?﹐︰＇＂）］｝〉》」』】﹞－_—')
    # 避尾字元
    PUNCT_END_FORBIDDEN = set('「『（｛〈《【“‘（［｛〈《「『【〔')

    def w(t): return draw.textbbox((0, 0), t, font=font)[2]
    
    text = text.strip()
    if not text:
        return []
        
    # 1. 依中文標點符號，保留標點將整句切分為天然子句
    pattern = re.compile(r'([^，、。！？；：﹐\n]+[，、。！？；：﹐\n]*)')
    clauses = pattern.findall(text)
    
    if not clauses:
        clauses = [text]
        
    final_lines = []
    
    # 2. 逐個處理子句
    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue
            
        # 如果子句寬度在小卡安全限制內，直接作為完整的一行
        if w(clause) <= max_w:
            final_lines.append(clause)
        else:
            # 如果單個子句過長，則從中間點對稱且均勻地切分成兩行或多行
            remaining = clause
            while w(remaining) > max_w:
                n = len(remaining)
                mid = n // 2
                
                # 避頭：避免切分後，新行的開頭字元出現在禁忌清單中
                while mid < n and remaining[mid] in PUNCT_START_FORBIDDEN:
                    mid += 1
                    
                # 避尾：避免切分後，當前行末尾出現前括號等禁忌字元
                while mid > 1 and remaining[mid - 1] in PUNCT_END_FORBIDDEN:
                    mid -= 1
                    
                # 切出前半段
                part = remaining[:mid]
                final_lines.append(part)
                remaining = remaining[mid:]
                
            if remaining:
                final_lines.append(remaining)
                
    # 3. 自適應平衡最後兩行字數，防止尾行出現孤字孤詞 (如僅剩 1~3 字)
    if len(final_lines) >= 2:
        last_line = final_lines[-1]
        prev_line = final_lines[-2]
        if len(last_line) <= 3 and len(prev_line) >= 8:
            merged = prev_line + last_line
            mid = len(merged) // 2
            # 平衡分割點同樣需要遵守避頭原則
            while mid < len(merged) and merged[mid] in PUNCT_START_FORBIDDEN:
                mid += 1
            if mid < len(merged):
                final_lines[-2] = merged[:mid]
                final_lines[-1] = merged[mid:]
                
    return final_lines

def manual_wrap(text: str) -> list:
    return [l for l in text.split('\n') if l.strip()] or [text]

def draw_text_pro(draw, img, pos, text, font, fill_rgb, stroke_w=3, glow_str=0):
    """整句用同一 font 物件渲染，確保視覺統一。"""
    x, y = pos
    r, g, b = fill_rgb
    bright = r * 0.299 + g * 0.587 + b * 0.114
    sc = (15, 15, 15, 220) if bright > 128 else (240, 240, 240, 200)

    # 發光層
    if glow_str > 0:
        gl = Image.new('RGBA', img.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(gl)
        gd.text((x, y), text, font=font, fill=(r, g, b, 150))
        img.alpha_composite(gl.filter(ImageFilter.GaussianBlur(radius=glow_str)))
        draw = ImageDraw.Draw(img, 'RGBA')

    # 描邊層
    if stroke_w > 0:
        for dx in range(-stroke_w, stroke_w + 1):
            for dy in range(-stroke_w, stroke_w + 1):
                if abs(dx) + abs(dy) <= stroke_w + 1 and not (dx == 0 and dy == 0):
                    draw.text((x + dx, y + dy), text, font=font, fill=sc)

    # 主色層
    draw.text((x, y), text, font=font, fill=(r, g, b, 255))
    return draw  # 回傳可能已重建的 draw

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

    override    = overrides.get(str(row_idx), {})
    custom_text = override.get('content', None)
    custom_src  = override.get('source', None)  # 取得自訂出處設定
    font_size   = override.get('font_size', g_size_content)

    # ── 底圖 ──────────────────────────────────────────────────
    matched = find_in_index(str(row.get('Image_Name', '')), zip_index)
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

    # ── 正文：整句 Fallback 字型選擇 ──────────────────────────
    raw_content = str(row.get('Content', '')).replace(' ', '')

    if custom_text is not None:
        # 若自訂文字包含手動換行 "\n" 則使用手動換行，否則仍使用智能斷行
        if '\n' in custom_text:
            lines = manual_wrap(custom_text)
        else:
            temp_font, _ = pick_font(custom_text, font_size)
            lines = smart_wrap(custom_text, temp_font, 840, draw)
        check_text = custom_text.replace('\n', '')
    else:
        check_text       = raw_content
        # 先用鏈中第一個可用字型算斷行（字型影響字寬）
        temp_font, _     = pick_font(check_text, font_size)
        lines            = smart_wrap(raw_content, temp_font, 840, draw)

    # 整句決定最終字型（整張卡正文全部用這個）
    font_content, font_name = pick_font(check_text, font_size)

    # ── 出處：支援自訂與防空值過濾 ────────────────────────────
    if custom_src is not None:
        src = custom_src.strip()
    else:
        src = str(row.get('Source', '')).strip()

    # 智慧過濾：若出處內容只包含「摘自：」或為空，則不予繪製
    if src in ("摘自：", "摘自:", "摘自", "nan") or not src:
        src = ""

    if src:
        font_source, _ = pick_font(src, size_source)
    else:
        font_source    = font_content

    # ── 繪製正文 ──────────────────────────────────────────────
    bh      = draw.textbbox((0, 0), '高', font=font_content)
    lh      = (bh[3] - bh[1]) * line_spacing_mult
    total_h = len(lines) * lh
    start_y = (1000 - total_h) / 2 - 20

    for i, line in enumerate(lines):
        bx = draw.textbbox((0, 0), line, font=font_content)
        x  = (1000 - (bx[2] - bx[0])) / 2
        y  = start_y + i * lh
        draw = draw_text_pro(draw, card, (x, y), line, font_content,
                             fill_rgb, stroke_w=stroke_w, glow_str=glow_str)

    # ── 繪製出處（若出處非空才繪製） ───────────────────────────
    if src:
        bs = draw.textbbox((0, 0), src, font=font_source)
        xs = (1000 - (bs[2] - bs[0])) / 2
        draw = draw_text_pro(draw, card, (xs, 900), src, font_source,
                             fill_rgb, stroke_w=stroke_w, glow_str=glow_str)

    return card.convert('RGB'), matched, actual, font_name

# ══════════════════════════════════════════════════════════════
# 快取 zip & csv
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
                hit = find_in_index(str(r['Image_Name']), idx_d)
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

    with tab_single:
        c_left, c_right = st.columns([1, 1])

        with c_left:
            preview_row = st.number_input(
                "預覽第幾筆語錄（0 起算）",
                min_value=0, max_value=max_row, value=0, step=1,
                key="preview_row_num"
            )
            row_p    = df_p.iloc[int(preview_row)]
            row_key  = str(preview_row)
            override = st.session_state.card_overrides.get(row_key, {})

            st.markdown("---")
            st.markdown("**✏️ 個別卡片客製化**")

            # 1. 客製化正文
            raw_content = str(row_p.get('Content', '')).replace(' ', '')
            csv_text = "" if raw_content == "nan" else raw_content
            default_text = override.get('content', csv_text)
            
            custom_text = st.text_area(
                "手動斷句（Enter 換行；清空則恢復智能斷行）",
                value=default_text, height=140,
                key=f"ta_{preview_row}",
                help="直接按 Enter 換行。清空文字框則使用智能斷行。"
            )

            # 2. 客製化出處
            raw_source = str(row_p.get('Source', '')).strip()
            csv_source = "" if raw_source == "nan" else raw_source
            default_source = override.get('source', csv_source)
            
            custom_source = st.text_input(
                "手動修改出處（留空或刪除所有文字即可完全不顯示）",
                value=default_source,
                key=f"ts_{preview_row}",
                help="您可以自由編輯此處文字，或直接清空本欄位以刪除小卡上的出處資訊。"
            )

            # 3. 客製化字型大小 (範圍同步為 20 - 100)
            current_size = int(override.get('font_size', g_font_size_content))
            custom_size  = st.slider(
                "此卡片正文字體大小",
                min_value=20, max_value=100,
                value=current_size if 20 <= current_size <= 100 else g_font_size_content,
                step=1,
                key=f"ss_{preview_row}"
            )

            # ── 自動儲存與同步機制 ───────────────────────────────────
            new_override = {}
            has_changes = False

            # 比對是否有實質性的內容異動
            if custom_text.strip() and custom_text != csv_text:
                new_override['content'] = custom_text
                has_changes = True

            if custom_source != csv_source:
                new_override['source'] = custom_source
                has_changes = True

            if custom_size != g_font_size_content:
                new_override['font_size'] = custom_size
                has_changes = True

            if has_changes:
                st.session_state.card_overrides[row_key] = new_override
                st.caption("✨ *已自動儲存此卡客製化設定*")
            else:
                st.session_state.card_overrides.pop(row_key, None)

            # 還原按鈕控制
            if st.button("🔄 還原此卡為全局設定", key=f"reset_{preview_row}"):
                st.session_state.card_overrides.pop(row_key, None)
                st.session_state.pop(f"ta_{preview_row}", None)
                st.session_state.pop(f"ts_{preview_row}", None)
                st.session_state.pop(f"ss_{preview_row}", None)
                st.rerun()

            if st.session_state.card_overrides:
                st.markdown("---")
                st.markdown(f"**📋 已客製化：{len(st.session_state.card_overrides)} 張**")
                for k, v in sorted(st.session_state.card_overrides.items(),
                                   key=lambda x: int(x[0])):
                    tags = []
                    if 'content'   in v: tags.append("手動斷句")
                    if 'font_size' in v: tags.append(f"字體 {v['font_size']}")
                    if 'source'    in v: tags.append("自訂出處")
                    st.caption(f"第 {k} 筆：{'、'.join(tags)}")

        with c_right:
            live_override = {}
            if custom_text.strip():
                live_override['content'] = custom_text
            live_override['font_size'] = custom_size
            live_override['source']    = custom_source  # 即時預覽出處變更

            card_p, _, used_dark, font_name = generate_card(
                row_p, preview_row, zf_p, idx_p,
                custom_size, g_font_size_source,
                bg_darkness, auto_darkness,
                text_color, line_spacing, stroke_width, glow_strength,
                {row_key: live_override}
            )
            buf_p = io.BytesIO()
            card_p.save(buf_p, format='JPEG', quality=88)
            st.image(buf_p.getvalue(),
                     caption=f"第 {preview_row} 筆 ｜ 遮罩 {used_dark:.2f} ｜ 字體 {custom_size} ｜ 字型：{font_name}",
                     width=420)

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
                pd_draw.rectangle([xi, yi, xi+cw*4, yi+ch*4],
                                   outline=(180, 180, 180), width=1)
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
            zip_idx_b, all_paths_b, zf_b = build_zip_index(st.session_state.zip_bytes_cache)
            st.sidebar.caption(f"📦 ZIP {len(all_paths_b)} 張")

            pdf_buf  = io.BytesIO()
            c        = canvas.Canvas(pdf_buf, pagesize=A4)
            cur_page = Image.new('RGB', (840, 1188), (255, 255, 255))
            pg_draw  = ImageDraw.Draw(cur_page)
            mx, my, cw, ch = 10, 15, 95, 89
            total     = len(df)
            pbar      = st.progress(0)
            previews  = []
            miss_list = []
            font_log  = {}

            for idx, row in df.iterrows():
                card_pil, matched, _, font_name = generate_card(
                    row, idx, zf_b, zip_idx_b,
                    g_font_size_content, g_font_size_source,
                    bg_darkness, auto_darkness,
                    text_color, line_spacing, stroke_width, glow_strength,
                    st.session_state.card_overrides
                )
                if not matched:
                    miss_list.append(str(row.get('Image_Name', idx)))
                if font_name and '思源黑體' not in font_name:
                    font_log[int(idx) + 1] = font_name

                gi    = idx % 6
                col_i = gi % 2
                row_i = gi // 2
                xp    = (mx + col_i * cw) * mm
                yp    = (297 - my - (row_i + 1) * ch) * mm

                buf = io.BytesIO()
                card_pil.save(buf, format='JPEG', quality=88)
                buf.seek(0)
                c.drawImage(canvas.ImageReader(buf), xp, yp, width=cw*mm, height=ch*mm)
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
                    f"ℹ️ {len(font_log)} 張切換了備用字型：\n" +
                    "\n".join(f"  第 {n} 筆 → {f}" for n, f in list(font_log.items())[:10])
                )

elif not (uploaded_csv and uploaded_zip):
    st.info("💡 請在上方分別拖入 csv 與 zip素材包。")

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
