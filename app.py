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
auto_darkness = st.sidebar.checkbox("✨ 智能自動遮罩", value=False)
if auto_darkness:
    st.sidebar.caption("依底圖亮度自動計算，下方可微調。")
    bg_darkness = st.sidebar.slider("偏移量（+ 加深 / - 減淺）", -0.30, 0.30, 0.0, step=0.05)
else:
    bg_darkness = st.sidebar.slider("手動遮罩黯淡度", 0.0, 1.0, 0.0, step=0.05)

st.sidebar.markdown("---")
st.sidebar.markdown("**✨ 文字清晰強化**")
stroke_width  = st.sidebar.slider("文字描邊寬度", 0, 5, 3, step=1)
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

    # ── 正文：整句 Fallback 字型選擇 ──────────────────────────
    raw_content = str(row.get('Content', '')).replace(' ', '')

    if custom_text is not None:
        lines = manual_wrap(custom_text)
        full_text_for_check = custom_text.replace('\n', '')
    else:
        # 先用主字型跑 smart_wrap 決定斷行，再決定字型
        temp_font, _ = pick_font_for_text(raw_content, font_size)
        lines        = smart_wrap(raw_content, temp_font, 840, draw)
        full_text_for_check = raw_content

    # 整句決定用哪個字型（一張卡全部行用同一字型）
    font_content, font_used = pick_font_for_text(full_text_for_check, font_size)

    # ── 出處字型（整句切換）──────────────────────────────────
    src = str(row.get('Source', ''))
    if src and src != 'nan':
        font_source, _ = pick_font_for_text(src, size_source)
    else:
        font_source, _ = pick_font_for_text('', size_source)

    # ── 繪製正文 ──────────────────────────────────────────────
    bh      = draw.textbbox((0, 0), '高', font=font_content)
    lh      = (bh[3] - bh[1]) * line_spacing_mult
    total_h = len(lines) * lh
    start_y = (1000 - total_h) / 2 - 20

    for i, line in enumerate(lines):
        bx = draw.textbbox((0, 0), line, font=font_content)
        x  = (1000 - (bx[2] - bx[0])) / 2
        y  = start_y + i * lh
        draw_text_pro(draw, (x, y), line, font_content, fill_rgb,
                      stroke_w=stroke_w, img=card, glow_str=glow_str)
        draw = ImageDraw.Draw(card, 'RGBA')  # 發光後重建

    # ── 繪製出處 ──────────────────────────────────────────────
    if src and src != 'nan':
        bs = draw.textbbox((0, 0), src, font=font_source)
        xs = (1000 - (bs[2] - bs[0])) / 2
        draw_text_pro(draw, (xs, 900), src, font_source, fill_rgb,
                      stroke_w=stroke_w, img=card, glow_str=glow_str)

    return card.convert('RGB'), matched, actual, font_used

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

            # 文字編輯框
            default_text = override.get(
                'content',
                str(row_p.get('Content', '')).replace(' ', '')
            )
            custom_text = st.text_area(
                "手動斷句（Enter 換行；清空則恢復智能斷行）",
                value=default_text,
                height=140,
                key=f"text_area_{preview_row}",
                help="直接按 Enter 換行。清空則自動使用智能斷行。"
            )

            # 個別字體大小
            current_size = override.get('font_size', g_font_size_content)
            custom_size  = st.slider(
                "此卡片正文字體大小",
                min_value=20, max_value=70,
                value=int(current_size), step=2,
                key=f"size_slider_{preview_row}"
            )

            col_save, col_reset = st.columns(2)
            with col_save:
                if st.button("💾 儲存此卡設定", key=f"save_{preview_row}"):
                    entry = {}
                    if custom_text.strip():
                        entry['content'] = custom_text
                    if custom_size != g_font_size_content:
                        entry['font_size'] = custom_size
                    st.session_state.card_overrides[row_key] = entry
                    st.success(f"✅ 第 {preview_row} 筆已儲存！")

            with col_reset:
                if st.button("🔄 還原預設", key=f"reset_{preview_row}"):
                    st.session_state.card_overrides.pop(row_key, None)
                    st.success("已還原為全局設定。")

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
            # 即時預覽：用 text_area 當前值（未必已儲存）
            live_override = {}
            if custom_text.strip():
                live_override['content']   = custom_text
            live_override['font_size'] = custom_size

            card_p, _, used_dark, font_used = generate_card(
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
            st.image(buf_p.getvalue(),
                     caption=f"第 {preview_row} 筆 ｜ 遮罩 {used_dark:.2f} ｜ 字體 {custom_size} ｜ 字型：{font_label}",
                     width=420)

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
                if font_used and '芫荽' not in font_used:
                    font_log[int(idx) + 1] = os.path.basename(font_used)

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
