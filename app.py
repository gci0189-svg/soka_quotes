import streamlit as st
import pandas as pd
import zipfile
import io
import os
import re
from PIL import Image, ImageDraw, ImageFont
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

font_size_content = st.sidebar.slider("正文字型大小", 20, 60, 38, step=2)
font_size_source  = st.sidebar.slider("出處字型大小",  14, 40, 22, step=2)
text_color        = st.sidebar.color_picker("文字顏色", "#FFFFFF")
bg_darkness       = st.sidebar.slider("背景遮罩黯淡度", 0.0, 1.0, 0.3, step=0.05)
show_cut_lines    = st.sidebar.checkbox("顯示 A4 裁切虛線", value=True)

sidebar_params = dict(
    font_mode=font_mode, font_size_content=font_size_content,
    font_size_source=font_size_source, text_color=text_color,
    bg_darkness=bg_darkness, show_cut_lines=show_cut_lines,
)

# ── 主畫面上傳 ────────────────────────────────────────────────
col1, col2 = st.columns(2)
with col1:
    uploaded_csv = st.file_uploader("1. 上傳語錄表格 (soka_quotes.csv)", type=["csv"])
with col2:
    uploaded_zip = st.file_uploader("2. 上傳素材壓縮包 (soka_all_materials.zip)", type=["zip"])

for k, v in [("pdf_data", None), ("preview_bytes_list", []), ("last_params", None)]:
    if k not in st.session_state:
        st.session_state[k] = v

if st.session_state.pdf_data and st.session_state.last_params != sidebar_params:
    st.sidebar.warning("⚠️ 參數已變更，請重新點擊「開始批次排版」以套用。")

# ── 工具函式 ──────────────────────────────────────────────────

def hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple:
    """'#FFFFFF' → (255, 255, 255, alpha)。Pillow RGBA 模式必須傳 tuple，不能傳 hex 字串。"""
    h = hex_color.lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


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
    """
    從 zip 的原始 bytes 建立圖片索引。
    ★ 接受 bytes 而非 UploadedFile，避免 Streamlit Cloud 上 seek 失效問題。
    回傳 (index_dict, all_image_paths, zip_file_object)
    index key 涵蓋：basename小寫、stem小寫、數字串多種變體、prefix_數字格式。
    """
    IMG_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'}
    index, all_paths = {}, []

    # 用 BytesIO 包住，確保可以反覆 seek
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))

    for name in zf.namelist():
        if '__MACOSX' in name or name.endswith('/'):
            continue
        bn = os.path.basename(name)
        if not bn or bn.startswith('.'):
            continue
        ext = os.path.splitext(bn)[1].lower()
        if ext not in IMG_EXT:
            continue

        all_paths.append(name)
        stem = os.path.splitext(bn)[0]

        index.setdefault(bn.lower(), name)
        index.setdefault(stem.lower(), name)

        nums = re.findall(r'\d+', stem)
        for num in nums:
            n_int = int(num)
            for key in [num, str(n_int),
                        str(n_int).zfill(2),
                        str(n_int).zfill(3),
                        str(n_int).zfill(4)]:
                index.setdefault(key, name)

        # prefix_數字 格式（e.g. stem='bg_001' → keys: 'bg_1','bg_01','bg_001','bg_0001'）
        m = re.match(r'^([a-zA-Z_\-]+)(\d+)$', stem)
        if m:
            prefix, num_part = m.group(1), m.group(2)
            n_int = int(num_part)
            for pad in [0, 2, 3, 4]:
                k = prefix + (str(n_int) if pad == 0 else str(n_int).zfill(pad))
                index.setdefault(k.lower(), name)
                index.setdefault((k + '.jpg').lower(), name)
                index.setdefault((k + '.jpeg').lower(), name)
                index.setdefault((k + '.png').lower(), name)

    return index, all_paths, zf


def find_in_index(raw_img_name: str, index: dict):
    raw = str(raw_img_name).strip()
    if raw.endswith('.0'):
        raw = raw[:-2]

    stem_raw = os.path.splitext(raw)[0]
    candidates = [raw.lower(), stem_raw.lower()]

    nums = re.findall(r'\d+', stem_raw)
    for num in nums:
        n_int = int(num)
        for key in [num, str(n_int),
                    str(n_int).zfill(2),
                    str(n_int).zfill(3),
                    str(n_int).zfill(4)]:
            candidates.append(key)

    m = re.match(r'^([a-zA-Z_\-]+)(\d+)(\.[a-zA-Z]+)?$', raw)
    if m:
        prefix, num_part = m.group(1), m.group(2)
        n_int = int(num_part)
        for pad in [0, 2, 3, 4]:
            k = prefix + (str(n_int) if pad == 0 else str(n_int).zfill(pad))
            candidates.append(k.lower())
            for ext in ['.jpg', '.jpeg', '.png']:
                candidates.append((k + ext).lower())

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
        for p in ["fonts/芫荽.ttf", "芫荽.ttf"]:
            if os.path.exists(p):
                fc = ImageFont.truetype(p, size_content)
                fs = ImageFont.truetype(p, size_source)
                break
    if fc is None:
        fc = ImageFont.load_default()
        fs = ImageFont.load_default()
    return fc, fs


def generate_card_image(row, zf, zip_index, font_c, font_s,
                        bg_darkness, text_color_hex):
    """
    ★ zf 是從 BytesIO 建立的 ZipFile，可以反覆 read() 不會失效。
    ★ text_color_hex 是 '#RRGGBB'，內部轉 tuple 再傳給 Pillow。
    """
    card_img = None
    matched  = None
    raw_name = str(row.get('Image_Name', '')).strip()

    try:
        matched = find_in_index(raw_name, zip_index)
        if matched:
            img_data = zf.read(matched)
            card_img = Image.open(io.BytesIO(img_data)).convert("RGBA")
    except Exception:
        card_img = None

    if card_img is None:
        card_img = Image.new("RGBA", (1000, 1000), (220, 217, 210, 255))

    card_img = card_img.resize((1000, 1000), resample=Image.Resampling.BILINEAR)
    draw = ImageDraw.Draw(card_img, "RGBA")

    if bg_darkness > 0:
        draw.rectangle([0, 0, 1000, 1000], fill=(0, 0, 0, int(255 * bg_darkness)))

    # ★ 關鍵：hex 字串 → RGBA tuple，絕對不能直接傳 hex 字串給 Pillow RGBA 模式
    fill_main   = hex_to_rgba(text_color_hex, 255)
    fill_shadow = (0, 0, 0, 180)

    content_text = str(row.get('Content', '')).replace(" ", "")
    lines = text_wrap(content_text, font_c, 800, draw)

    bh     = draw.textbbox((0, 0), "高", font=font_c)
    lh     = (bh[3] - bh[1]) * 1.5
    start_y = (1000 - len(lines) * lh) / 2 - 30

    for i, line in enumerate(lines):
        bx = draw.textbbox((0, 0), line, font=font_c)
        x  = (1000 - (bx[2] - bx[0])) / 2
        y  = start_y + i * lh
        draw.text((x+2, y+2), line, fill=fill_shadow, font=font_c)
        draw.text((x,   y  ), line, fill=fill_main,   font=font_c)

    source_text = str(row.get('Source', ''))
    if source_text and source_text != "nan":
        bs = draw.textbbox((0, 0), source_text, font=font_s)
        xs = 1000 - (bs[2] - bs[0]) - 80
        ys = 880
        draw.text((xs+1, ys+1), source_text, fill=fill_shadow, font=font_s)
        draw.text((xs,   ys  ), source_text, fill=fill_main,   font=font_s)

    return card_img.convert("RGB"), matched


# ── 診斷 ──────────────────────────────────────────────────────

if uploaded_csv and uploaded_zip:

    with st.expander("🔍 診斷：查看 ZIP 內容 & 前 10 筆配對", expanded=False):
        if st.button("執行診斷（不生成 PDF）"):
            zip_bytes_d = uploaded_zip.read()   # ★ 先讀成 bytes
            df_d = pd.read_csv(uploaded_csv)
            idx_d, paths_d, zf_d = build_zip_index(zip_bytes_d)

            st.write(f"**ZIP 合法圖片數：{len(paths_d)}**")
            st.write("ZIP 前 20 個圖片路徑：")
            st.code("\n".join(paths_d[:20]))

            rows_out = []
            for _, r in df_d.head(10).iterrows():
                raw = str(r.get('Image_Name', ''))
                hit = find_in_index(raw, idx_d)
                rows_out.append({"Image_Name (CSV)": raw,
                                 "配對到的 ZIP 路徑": hit or "❌ 找不到"})
            st.write("**前 10 筆配對結果：**")
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

    # ── 正式生成 ──────────────────────────────────────────────
    if st.button("🚀 開始批次排版並生成預覽", type="primary"):
        with st.spinner("正在安全建構 A4 2x3 排版..."):

            # ★★★ 關鍵修正：先把 UploadedFile 讀成 bytes，
            #      再用 BytesIO 包住給 ZipFile，確保可以反覆 seek/read
            zip_bytes = uploaded_zip.read()
            df = pd.read_csv(uploaded_csv)
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
                    bg_darkness, text_color
                )
                if not matched_path:
                    miss_list.append(str(row.get('Image_Name', idx)))

                gi    = idx % 6
                col_i = gi % 2
                row_i = gi // 2

                xp = (margin_x + col_i * card_w) * mm
                yp = (297 - margin_y - (row_i + 1) * card_h) * mm

                buf = io.BytesIO()
                card_pil.save(buf, format='JPEG', quality=85)
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
                    prev.save(b2, format="JPEG", quality=70)
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
            use_container_width=True,
        )

elif not (uploaded_csv and uploaded_zip):
    st.info("💡 請在上方分別拖入 csv 與 zip 素材包，系統就會啟動批次 PDF 排版。")
