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

# --- 側邊欄 ---
st.sidebar.header("🎨 小卡視覺調整面板")
font_mode = st.sidebar.radio("中文字型來源", ["使用 GitHub 倉庫內置字型 (芫荽.ttf)", "自行從電腦上傳 TTF"])
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

# --- 主畫面 ---
col1, col2 = st.columns(2)
with col1:
    uploaded_csv = st.file_uploader("1. 上傳語錄表格 (soka_quotes.csv)", type=["csv"])
with col2:
    uploaded_zip = st.file_uploader("2. 上傳素材壓縮包 (soka_all_materials.zip)", type=["zip"])

for key in ("pdf_data", "preview_bytes_list", "last_params"):
    if key not in st.session_state:
        st.session_state[key] = None if key != "preview_bytes_list" else []

if st.session_state.pdf_data and st.session_state.last_params != sidebar_params:
    st.sidebar.warning("⚠️ 參數已變更，請重新點擊「開始批次排版」以套用。")

# ── 工具函式 ──────────────────────────────────────────────

def text_wrap(text, font, max_width, draw):
    lines, current_line = [], ""
    for ch in list(text):
        test = current_line + ch
        bbox = draw.textbbox((0, 0), test, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            current_line = test
        else:
            if current_line:
                lines.append(current_line)
            current_line = ch
    if current_line:
        lines.append(current_line)
    return lines


def build_zip_index(zip_file):
    """
    建立 zip 圖片索引。
    回傳 (index_dict, all_image_paths)
    index key 涵蓋：basename小寫、stem小寫、所有數字串(原始/去前導零/補零3位)
    """
    IMG_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'}
    index, all_paths = {}, []

    for name in zip_file.namelist():
        if '__MACOSX' in name or name.endswith('/') or os.path.basename(name).startswith('.'):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in IMG_EXT:
            continue

        all_paths.append(name)
        basename = os.path.basename(name)
        stem     = os.path.splitext(basename)[0]

        for key in [basename.lower(), stem.lower()]:
            index.setdefault(key, name)

        for num in re.findall(r'\d+', stem):
            index.setdefault(num, name)
            index.setdefault(num.lstrip('0') or '0', name)
            index.setdefault(num.zfill(3), name)

    return index, all_paths


def find_in_index(raw_img_name, index):
    raw = str(raw_img_name).strip()
    if raw.endswith('.0'):
        raw = raw[:-2]

    candidates = [raw, raw.lower(), os.path.splitext(raw)[0].lower()]
    for num in re.findall(r'\d+', raw):
        candidates += [num, num.lstrip('0') or '0', num.zfill(3)]

    for key in candidates:
        if key in index:
            return index[key]
    return None


def load_fonts(font_mode, uploaded_font, size_content, size_source):
    font_c = font_s = None
    if font_mode == "自行從電腦上傳 TTF" and uploaded_font:
        buf = io.BytesIO(uploaded_font.read())
        font_c = ImageFont.truetype(buf, size_content)
        buf.seek(0)
        font_s = ImageFont.truetype(buf, size_source)
    else:
        for p in ["fonts/芫荽.ttf", "芫荽.ttf"]:
            if os.path.exists(p):
                font_c = ImageFont.truetype(p, size_content)
                font_s = ImageFont.truetype(p, size_source)
                break
    if font_c is None:
        font_c = ImageFont.load_default()
        font_s = ImageFont.load_default()
    return font_c, font_s


def hex_to_rgba(hex_color, alpha=255):
    h = hex_color.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4)) + (alpha,)


def generate_card_image(row, zip_file, zip_index, font_content, font_source,
                        bg_darkness, text_color):
    card_img = None
    matched  = None
    raw_name = str(row.get('Image_Name', '')).strip()

    try:
        matched = find_in_index(raw_name, zip_index)
        if matched:
            img_data = zip_file.read(matched)
            card_img = Image.open(io.BytesIO(img_data)).convert("RGBA")
    except Exception:
        card_img = None

    # 找不到底圖 → 米灰色（絕對不是黑色）
    if card_img is None:
        card_img = Image.new("RGBA", (1000, 1000), (220, 217, 210, 255))

    card_img = card_img.resize((1000, 1000), resample=Image.Resampling.BILINEAR)
    draw     = ImageDraw.Draw(card_img, "RGBA")

    if bg_darkness > 0:
        draw.rectangle([0, 0, 1000, 1000], fill=(0, 0, 0, int(255 * bg_darkness)))

    fill_main   = hex_to_rgba(text_color, 255)
    fill_shadow = (0, 0, 0, 200)

    content_text = str(row.get('Content', '')).replace(" ", "")
    lines = text_wrap(content_text, font_content, 800, draw)

    bbox_h  = draw.textbbox((0, 0), "高", font=font_content)
    lh      = (bbox_h[3] - bbox_h[1]) * 1.5
    start_y = (1000 - len(lines) * lh) / 2 - 30

    for i, line in enumerate(lines):
        bx = draw.textbbox((0, 0), line, font=font_content)
        x  = (1000 - (bx[2] - bx[0])) / 2
        y  = start_y + i * lh
        draw.text((x+2, y+2), line, fill=fill_shadow, font=font_content)
        draw.text((x,   y  ), line, fill=fill_main,   font=font_content)

    source_text = str(row.get('Source', ''))
    if source_text and source_text != "nan":
        bs = draw.textbbox((0, 0), source_text, font=font_source)
        xs = 1000 - (bs[2] - bs[0]) - 80
        ys = 880
        draw.text((xs+1, ys+1), source_text, fill=fill_shadow, font=font_source)
        draw.text((xs,   ys  ), source_text, fill=fill_main,   font=font_source)

    return card_img.convert("RGB"), matched


# ── 診斷區塊 ────────────────────────────────────────────────

if uploaded_csv and uploaded_zip:

    with st.expander("🔍 診斷：查看 ZIP 內容 & 前 10 筆配對結果（建議先執行確認）", expanded=False):
        if st.button("執行診斷（不生成 PDF）"):
            df_d  = pd.read_csv(uploaded_csv)
            zf_d  = zipfile.ZipFile(uploaded_zip)
            idx_d, paths_d = build_zip_index(zf_d)

            st.write(f"**ZIP 合法圖片數：** {len(paths_d)}")
            st.write("**ZIP 前 20 個圖片路徑：**")
            st.code("\n".join(paths_d[:20]))

            st.write("**CSV 前 10 筆 Image_Name 配對結果：**")
            rows_out = []
            for _, r in df_d.head(10).iterrows():
                raw = str(r.get('Image_Name', ''))
                hit = find_in_index(raw, idx_d)
                rows_out.append({"Image_Name (CSV)": raw,
                                 "配對到的 ZIP 路徑": hit or "❌ 找不到"})
            st.table(pd.DataFrame(rows_out))

            # 顯示第一張配對圖預覽
            for _, r in df_d.iterrows():
                raw = str(r.get('Image_Name', ''))
                hit = find_in_index(raw, idx_d)
                if hit:
                    try:
                        st.image(zf_d.read(hit), caption=f"第一張配對圖：{hit}", width=300)
                    except Exception as e:
                        st.error(f"圖片讀取失敗：{e}")
                    break

    # ── 正式生成 ─────────────────────────────────────────────
    if st.button("🚀 開始批次排版並生成預覽", type="primary"):
        with st.spinner("正在安全建構 A4 2x3 排版..."):
            df       = pd.read_csv(uploaded_csv)
            zip_file = zipfile.ZipFile(uploaded_zip)
            zip_index, all_paths = build_zip_index(zip_file)
            st.sidebar.caption(f"📦 ZIP 偵測到 {len(all_paths)} 張圖片")

            font_c, font_s = load_fonts(font_mode, uploaded_font,
                                        font_size_content, font_size_source)

            pdf_buffer = io.BytesIO()
            c          = canvas.Canvas(pdf_buffer, pagesize=A4)
            cur_page   = Image.new("RGB", (840, 1188), (255, 255, 255))
            pg_draw    = ImageDraw.Draw(cur_page)

            margin_x, margin_y = 10, 15
            card_w, card_h     = 95, 89
            total_cards        = len(df)
            progress_bar       = st.progress(0)
            temp_previews      = []
            miss_list          = []

            for index, row in df.iterrows():
                card_pil, matched_path = generate_card_image(
                    row, zip_file, zip_index, font_c, font_s, bg_darkness, text_color
                )
                if not matched_path:
                    miss_list.append(str(row.get('Image_Name', index)))

                grid_idx = index % 6
                col_i    = grid_idx % 2
                row_i    = grid_idx // 2

                x_pdf = (margin_x + col_i * card_w) * mm
                y_pdf = (297 - margin_y - (row_i + 1) * card_h) * mm

                buf = io.BytesIO()
                card_pil.save(buf, format='JPEG', quality=85)
                buf.seek(0)
                c.drawImage(canvas.ImageReader(buf), x_pdf, y_pdf,
                            width=card_w * mm, height=card_h * mm)

                if show_cut_lines:
                    c.setStrokeColorRGB(0.7, 0.7, 0.7)
                    c.setLineWidth(0.3)
                    c.rect(x_pdf, y_pdf, card_w * mm, card_h * mm)

                x_img   = int((margin_x + col_i * card_w) * 4)
                y_img   = int((margin_y + row_i  * card_h) * 4)
                resized = card_pil.resize((card_w * 4, card_h * 4),
                                          resample=Image.Resampling.BILINEAR)
                cur_page.paste(resized, (x_img, y_img))

                if show_cut_lines:
                    pg_draw.rectangle(
                        [x_img, y_img, x_img + card_w*4, y_img + card_h*4],
                        outline=(180, 180, 180), width=1
                    )

                progress_bar.progress((index + 1) / total_cards)

                if grid_idx == 5 or index == total_cards - 1:
                    c.showPage()
                    prev = cur_page.resize((420, 594), resample=Image.Resampling.BILINEAR)
                    b2   = io.BytesIO()
                    prev.save(b2, format="JPEG", quality=70)
                    temp_previews.append(b2.getvalue())
                    cur_page = Image.new("RGB", (840, 1188), (255, 255, 255))
                    pg_draw  = ImageDraw.Draw(cur_page)

            c.save()
            pdf_buffer.seek(0)

            st.session_state.pdf_data           = pdf_buffer.getvalue()
            st.session_state.preview_bytes_list  = temp_previews
            st.session_state.last_params         = sidebar_params.copy()

            if miss_list:
                st.warning(
                    f"⚠️ {len(miss_list)} 筆找不到對應底圖（已用米灰色取代）：\n"
                    + "、".join(miss_list[:20])
                )
            st.success(f"🎉 完成！共生成 {len(temp_previews)} 頁 A4 排版。")

# ── 結果顯示 ─────────────────────────────────────────────────

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
