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

# ── 側邊欄 ───────────────────────────────────────────────────
st.sidebar.header("🎨 小卡視覺調整面板")
font_mode = st.sidebar.radio("中文字型來源",
    ["使用 GitHub 倉庫內置字型 (芫荽.ttf)", "自行從電腦上傳 TTF"])
uploaded_font = None
if font_mode == "自行從電腦上傳 TTF":
    uploaded_font = st.sidebar.file_uploader("上傳字型 (.ttf)", type=["ttf"])

st.sidebar.markdown("---")
st.sidebar.markdown("**📝 文字設定**")
font_size_content = st.sidebar.slider("正文字型大小", 20, 70, 46, step=2)
font_size_source  = st.sidebar.slider("出處字型大小", 14, 40, 28, step=2)
line_spacing      = st.sidebar.slider("行距倍數", 1.2, 2.5, 1.6, step=0.1)
text_color        = st.sidebar.color_picker("文字顏色", "#FFFFFF")

st.sidebar.markdown("---")
st.sidebar.markdown("**🌄 背景設定**")
bg_darkness   = st.sidebar.slider("背景遮罩黯淡度", 0.0, 1.0, 0.50, step=0.05)

st.sidebar.markdown("---")
st.sidebar.markdown("**✨ 文字清晰強化**")
stroke_width  = st.sidebar.slider("文字描邊寬度（防暈）", 0, 5, 2, step=1)
glow_strength = st.sidebar.slider("文字發光強度（0=關閉）", 0, 8, 3, step=1)

st.sidebar.markdown("---")
show_cut_lines = st.sidebar.checkbox("顯示 A4 裁切虛線", value=True)

sidebar_params = dict(
    font_mode=font_mode, font_size_content=font_size_content,
    font_size_source=font_size_source, line_spacing=line_spacing,
    text_color=text_color, bg_darkness=bg_darkness,
    stroke_width=stroke_width, glow_strength=glow_strength,
    show_cut_lines=show_cut_lines,
)

# ── 主畫面上傳 ────────────────────────────────────────────────
col1, col2 = st.columns(2)
with col1:
    uploaded_csv = st.file_uploader("1. 上傳語錄表格 (soka_quotes.csv)", type=["csv"])
with col2:
    uploaded_zip = st.file_uploader("2. 上傳素材壓縮包 (soka_all_materials.zip)", type=["zip"])

for k, v in [("pdf_data", None), ("preview_bytes_list", []),
             ("last_params", None), ("zip_bytes_cache", None),
             ("csv_cache", None), ("zip_index_cache", None),
             ("preview_card_bytes", None), ("preview_row_idx", 0)]:
    if k not in st.session_state:
        st.session_state[k] = v

# ── 工具函式 ──────────────────────────────────────────────────

def hex_to_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def text_wrap(text, font, max_width, draw):
    lines, cur = [], ""
    for ch in text:
        test = cur + ch
        w = draw.textbbox((0, 0), test, font=font)[2]
        if w <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def build_zip_index(zip_bytes: bytes):
    IMG_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'}
    index, all_paths = {}, []
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    for name in zf.namelist():
        if '__MACOSX' in name or name.endswith('/'):
            continue
        bn = os.path.basename(name)
        if not bn or bn.startswith('.'):
            continue
        if os.path.splitext(bn)[1].lower() not in IMG_EXT:
            continue
        all_paths.append(name)
        stem = os.path.splitext(bn)[0]
        index.setdefault(bn.lower(), name)
        index.setdefault(stem.lower(), name)
        for num in re.findall(r'\d+', stem):
            n = int(num)
            for key in [num, str(n), str(n).zfill(2), str(n).zfill(3), str(n).zfill(4)]:
                index.setdefault(key, name)
        m = re.match(r'^([a-zA-Z_\-]+)(\d+)$', stem)
        if m:
            prefix, num_part = m.group(1), m.group(2)
            n = int(num_part)
            for pad in [0, 2, 3, 4]:
                k = prefix + (str(n) if pad == 0 else str(n).zfill(pad))
                for suffix in ['', '.jpg', '.jpeg', '.png']:
                    index.setdefault((k + suffix).lower(), name)
    return index, all_paths, zf


def find_in_index(raw_img_name: str, index: dict):
    raw = str(raw_img_name).strip()
    if raw.endswith('.0'):
        raw = raw[:-2]
    stem_raw = os.path.splitext(raw)[0]
    candidates = [raw.lower(), stem_raw.lower()]
    for num in re.findall(r'\d+', stem_raw):
        n = int(num)
        for key in [num, str(n), str(n).zfill(2), str(n).zfill(3), str(n).zfill(4)]:
            candidates.append(key)
    m = re.match(r'^([a-zA-Z_\-]+)(\d+)(\.[a-zA-Z]+)?$', raw)
    if m:
        prefix, num_part = m.group(1), m.group(2)
        n = int(num_part)
        for pad in [0, 2, 3, 4]:
            k = prefix + (str(n) if pad == 0 else str(n).zfill(pad))
            for suffix in ['', '.jpg', '.jpeg', '.png']:
                candidates.append((k + suffix).lower())
    for key in candidates:
        if key in index:
            return index[key]
    return None


def load_fonts(font_mode, uploaded_font, size_content, size_source):
    fc = fs = None
    if font_mode == "自行從電腦上傳 TTF" and uploaded_font:
        buf = io.BytesIO(uploaded_font.read())
        fc = ImageFont.truetype(buf, size_content)
        buf.seek(0)
        fs = ImageFont.truetype(buf, size_source)
    else:
        for p in ["芫荽.ttf", "fonts/芫荽.ttf"]:
            if os.path.exists(p):
                fc = ImageFont.truetype(p, size_content)
                fs = ImageFont.truetype(p, size_source)
                break
    if fc is None:
        fc = ImageFont.load_default()
        fs = ImageFont.load_default()
    return fc, fs


def draw_text_with_glow_stroke(draw, pos, text, font, fill_rgb,
                                stroke_w=2, glow_str=3, img=None):
    """
    專業印刷級文字渲染：
    1. 發光層（blur 暈染，讓字在任何背景都浮出來）
    2. 描邊層（深色輪廓，防止細字消失在亮色背景）
    3. 主色層（乾淨的主文字顏色）
    不用「重疊陰影」—— 那會讓字模糊、死氣沈沈。
    """
    x, y = pos

    # ── 發光層：在底圖上先 blur 一個白色光暈 ──────────────────
    if glow_str > 0 and img is not None:
        glow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow_layer)
        r, g, b = fill_rgb
        # 發光顏色：文字顏色的半透明版
        gd.text((x, y), text, font=font, fill=(r, g, b, 180))
        glow_blurred = glow_layer.filter(
            ImageFilter.GaussianBlur(radius=glow_str)
        )
        # 把發光層合成到主圖（img 必須是 RGBA）
        img.alpha_composite(glow_blurred)

    # ── 描邊層：深色輪廓讓字在亮底上不消失 ───────────────────
    if stroke_w > 0:
        # 計算描邊顏色：文字顏色的互補暗色
        r, g, b = fill_rgb
        stroke_brightness = (r * 0.299 + g * 0.587 + b * 0.114)
        if stroke_brightness > 128:
            stroke_color = (20, 20, 20, 220)   # 亮字 → 深色描邊
        else:
            stroke_color = (235, 235, 235, 200) # 暗字 → 淺色描邊

        for dx in range(-stroke_w, stroke_w + 1):
            for dy in range(-stroke_w, stroke_w + 1):
                if dx == 0 and dy == 0:
                    continue
                if abs(dx) + abs(dy) <= stroke_w + 1:
                    draw.text((x + dx, y + dy), text, font=font,
                              fill=stroke_color)

    # ── 主色層 ────────────────────────────────────────────────
    draw.text((x, y), text, font=font,
              fill=(fill_rgb[0], fill_rgb[1], fill_rgb[2], 255))


def generate_card_image(row, zf, zip_index, font_c, font_s,
                        bg_darkness, text_color_hex,
                        line_spacing_mult, stroke_width, glow_strength):
    """全程 RGBA，最後輸出 RGB。"""
    card_img = None
    matched  = None
    raw_name = str(row.get('Image_Name', '')).strip()

    try:
        matched = find_in_index(raw_name, zip_index)
        if matched:
            card_img = Image.open(io.BytesIO(zf.read(matched))).convert("RGBA")
    except Exception:
        card_img = None

    if card_img is None:
        card_img = Image.new("RGBA", (1000, 1000), (220, 217, 210, 255))

    card_img = card_img.resize((1000, 1000), resample=Image.Resampling.BILINEAR)

    # 遮罩：alpha_composite 正確合成
    if bg_darkness > 0:
        overlay = Image.new("RGBA", (1000, 1000),
                            (0, 0, 0, int(255 * bg_darkness)))
        card_img = Image.alpha_composite(card_img, overlay)

    # 畫文字（RGBA 模式，發光需要 RGBA）
    draw       = ImageDraw.Draw(card_img, "RGBA")
    fill_rgb   = hex_to_rgb(text_color_hex)

    content_text = str(row.get('Content', '')).replace(" ", "")
    lines = text_wrap(content_text, font_c, 820, draw)

    bh      = draw.textbbox((0, 0), "高", font=font_c)
    lh      = (bh[3] - bh[1]) * line_spacing_mult
    total_h = len(lines) * lh
    start_y = (1000 - total_h) / 2 - 20

    for i, line in enumerate(lines):
        bx = draw.textbbox((0, 0), line, font=font_c)
        x  = (1000 - (bx[2] - bx[0])) / 2
        y  = start_y + i * lh
        draw_text_with_glow_stroke(
            draw, (x, y), line, font_c, fill_rgb,
            stroke_w=stroke_width, glow_str=glow_strength,
            img=card_img
        )

    source_text = str(row.get('Source', ''))
    if source_text and source_text != "nan":
        bs = draw.textbbox((0, 0), source_text, font=font_s)
        xs = 1000 - (bs[2] - bs[0]) - 60
        ys = 900
        draw_text_with_glow_stroke(
            draw, (xs, ys), source_text, font_s, fill_rgb,
            stroke_w=max(0, stroke_width - 1),
            glow_str=max(0, glow_strength - 1),
            img=card_img
        )

    return card_img.convert("RGB"), matched


# ── 快取 zip & csv（檔名不變就不重讀）────────────────────────
if uploaded_csv and uploaded_zip:
    csv_name = uploaded_csv.name
    zip_name = uploaded_zip.name
    if st.session_state.get("_csv_name") != csv_name:
        st.session_state["_csv_name"]  = csv_name
        st.session_state.csv_cache     = uploaded_csv.read()
    if st.session_state.get("_zip_name") != zip_name:
        st.session_state["_zip_name"]      = zip_name
        st.session_state.zip_bytes_cache   = uploaded_zip.read()
        idx, paths, zf_obj = build_zip_index(st.session_state.zip_bytes_cache)
        st.session_state.zip_index_cache   = (idx, paths, zf_obj)

# ── 診斷 ──────────────────────────────────────────────────────
if uploaded_csv and uploaded_zip:
    with st.expander("🔍 診斷：查看 ZIP 內容 & 前 10 筆配對", expanded=False):
        if st.button("執行診斷（不生成 PDF）"):
            idx_d, paths_d, zf_d = st.session_state.zip_index_cache
            df_d = pd.read_csv(io.BytesIO(st.session_state.csv_cache))
            st.write(f"**ZIP 合法圖片數：{len(paths_d)}**")
            st.code("\n".join(paths_d[:20]))
            rows_out = []
            for _, r in df_d.head(10).iterrows():
                raw = str(r.get('Image_Name', ''))
                hit = find_in_index(raw, idx_d)
                rows_out.append({"Image_Name (CSV)": raw,
                                 "配對到的 ZIP 路徑": hit or "❌ 找不到"})
            st.table(pd.DataFrame(rows_out))
            for _, r in df_d.iterrows():
                raw = str(r.get('Image_Name', ''))
                hit = find_in_index(raw, idx_d)
                if hit:
                    try:
                        st.image(zf_d.read(hit), caption=f"第一張配對圖：{hit}", width=300)
                    except Exception as e:
                        st.error(f"圖片讀取失敗：{e}")
                    break

# ── ★ 智能即時單張預覽（slider 動就自動更新）────────────────
if uploaded_csv and uploaded_zip and st.session_state.zip_index_cache:
    st.subheader("🖼️ 即時單張預覽")
    st.caption("⚡ 調整左側任何參數，預覽會自動更新，無需手動按鈕。")

    idx_p, _, zf_p   = st.session_state.zip_index_cache
    df_p             = pd.read_csv(io.BytesIO(st.session_state.csv_cache))
    max_row          = len(df_p) - 1

    prev_col1, prev_col2 = st.columns([1, 2])
    with prev_col1:
        preview_row = st.number_input(
            "預覽第幾筆語錄（0 起算）",
            min_value=0, max_value=max_row, value=0, step=1,
            key="preview_row_widget"
        )

    # ★ 直接渲染，不需按鈕 —— 每次 rerun（slider 改變）都會重跑
    font_c_p, font_s_p = load_fonts(font_mode, uploaded_font,
                                    font_size_content, font_size_source)
    row_p   = df_p.iloc[int(preview_row)]
    card_p, _ = generate_card_image(
        row_p, zf_p, idx_p, font_c_p, font_s_p,
        bg_darkness, text_color,
        line_spacing, stroke_width, glow_strength
    )
    buf_p = io.BytesIO()
    card_p.save(buf_p, format="JPEG", quality=88)

    with prev_col2:
        st.image(buf_p.getvalue(),
                 caption=f"第 {preview_row} 筆 ｜ {str(row_p.get('Content',''))[:20]}…",
                 width=420)

    st.divider()

    # ── 正式批次生成 ──────────────────────────────────────────
    if st.button("🚀 開始批次排版並生成預覽", type="primary"):
        with st.spinner("正在建構 A4 2x3 排版..."):
            zip_bytes = st.session_state.zip_bytes_cache
            df        = pd.read_csv(io.BytesIO(st.session_state.csv_cache))
            zip_index, all_paths, zf = build_zip_index(zip_bytes)
            st.sidebar.caption(f"📦 ZIP 偵測到 {len(all_paths)} 張圖片")

            font_c, font_s = load_fonts(font_mode, uploaded_font,
                                        font_size_content, font_size_source)

            pdf_buf  = io.BytesIO()
            c        = canvas.Canvas(pdf_buf, pagesize=A4)
            cur_page = Image.new("RGB", (840, 1188), (255, 255, 255))
            pg_draw  = ImageDraw.Draw(cur_page)

            margin_x, margin_y = 10, 15
            card_w,   card_h   = 95, 89
            total              = len(df)
            pbar               = st.progress(0)
            previews           = []
            miss_list          = []

            for idx, row in df.iterrows():
                card_pil, matched_path = generate_card_image(
                    row, zf, zip_index, font_c, font_s,
                    bg_darkness, text_color,
                    line_spacing, stroke_width, glow_strength
                )
                if not matched_path:
                    miss_list.append(str(row.get('Image_Name', idx)))

                gi    = idx % 6
                col_i = gi % 2
                row_i = gi // 2

                xp = (margin_x + col_i * card_w) * mm
                yp = (297 - margin_y - (row_i + 1) * card_h) * mm

                buf = io.BytesIO()
                card_pil.save(buf, format='JPEG', quality=88)
                buf.seek(0)
                c.drawImage(canvas.ImageReader(buf), xp, yp,
                            width=card_w * mm, height=card_h * mm)

                if show_cut_lines:
                    c.setStrokeColorRGB(0.7, 0.7, 0.7)
                    c.setLineWidth(0.3)
                    c.rect(xp, yp, card_w * mm, card_h * mm)

                xi = int((margin_x + col_i * card_w) * 4)
                yi = int((margin_y + row_i  * card_h) * 4)
                cur_page.paste(
                    card_pil.resize((card_w*4, card_h*4),
                                    resample=Image.Resampling.BILINEAR),
                    (xi, yi)
                )
                if show_cut_lines:
                    pg_draw.rectangle([xi, yi, xi+card_w*4, yi+card_h*4],
                                      outline=(180, 180, 180), width=1)

                pbar.progress((idx + 1) / total)

                if gi == 5 or idx == total - 1:
                    c.showPage()
                    prev = cur_page.resize((420, 594), resample=Image.Resampling.BILINEAR)
                    b2   = io.BytesIO()
                    prev.save(b2, format="JPEG", quality=72)
                    previews.append(b2.getvalue())
                    cur_page = Image.new("RGB", (840, 1188), (255, 255, 255))
                    pg_draw  = ImageDraw.Draw(cur_page)

            c.save()
            pdf_buf.seek(0)

            st.session_state.pdf_data           = pdf_buf.getvalue()
            st.session_state.preview_bytes_list = previews
            st.session_state.last_params        = sidebar_params.copy()

            if miss_list:
                st.warning(
                    f"⚠️ {len(miss_list)} 筆找不到對應底圖（米灰色取代）：\n"
                    + "、".join(miss_list[:30])
                )
            st.success(f"🎉 完成！共生成 {len(previews)} 頁 A4 排版。")

elif not (uploaded_csv and uploaded_zip):
    st.info("💡 請在上方分別拖入 csv 與 zip 素材包，系統就會啟動批次 PDF 排版。")

# ── 結果顯示 ──────────────────────────────────────────────────
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
        st.info("💡 列印時請設為「實際大小(100%)」或「不縮放」，裁切線才會最準確。")

    with col_view:
        st.subheader("👀 A4 2x3 實際排版整頁預覽")
        total_p     = len(st.session_state.preview_bytes_list)
        page_select = st.slider("切換預覽頁數", 1, total_p, 1) if total_p > 1 else 1
        st.write(f"📄 第 **{page_select}** / {total_p} 頁（每頁 6 張小卡）")
        st.image(
            st.session_state.preview_bytes_list[page_select - 1],
            caption=f"第 {page_select} 頁 A4 實印排版",
        )
