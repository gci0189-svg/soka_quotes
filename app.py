import streamlit as st
import pandas as pd
import zipfile
import io
import os
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

st.set_page_config(page_title="創價鼓勵小卡產生器", layout="wide", page_icon="🍀")

st.title("🍀 創價鼓勵小卡 A4 2x3 批次產生器 (檔名模糊智慧配對版)")
st.write("已加入檔名模糊匹配機制（例如表格寫 001.jpg 可自動配對 bg_001.jpg），徹底解決底圖不顯示問題。")

# --- 側邊欄 ---
st.sidebar.header("🎨 小卡視覺調整面板")
font_mode = st.sidebar.radio("中文字型來源", ["使用 GitHub 倉庫內置字型 (芫荽.ttf)", "自行從電腦上傳 TTF"])
uploaded_font = None
if font_mode == "自行從電腦上傳 TTF":
    uploaded_font = st.sidebar.file_uploader("上傳字型 (.ttf)", type=["ttf"])

font_size_content = st.sidebar.slider("正文字型大小", 20, 60, 38, step=2)
font_size_source = st.sidebar.slider("出處字型大小", 14, 40, 22, step=2)
text_color = st.sidebar.color_picker("文字顏色", "#FFFFFF")
bg_darkness = st.sidebar.slider("背景遮罩黯淡度 (讓白字更清晰)", 0.0, 1.0, 0.3, step=0.05)
show_cut_lines = st.sidebar.checkbox("顯示 A4 裁切虛線", value=True)

# --- 主畫面 ---
col1, col2 = st.columns(2)
with col1:
    uploaded_csv = st.file_uploader("1. 上傳語錄表格 (soka_quotes.csv)", type=["csv"])
with col2:
    uploaded_zip = st.file_uploader("2. 上傳素材壓縮包 (soka_all_materials.zip)", type=["zip"])

# Session State
if "pdf_data" not in st.session_state:
    st.session_state.pdf_data = None
if "preview_bytes_list" not in st.session_state:
    st.session_state.preview_bytes_list = []

def text_wrap(text, font, max_width, draw):
    lines = []
    words = list(text)
    current_line = ""
    for word in words:
        test_line = current_line + word
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            current_line = test_line
        else:
            if current_line: lines.append(current_line)
            current_line = word
    if current_line: lines.append(current_line)
    return lines

def generate_card_image(row, zip_file, zip_namelist, font_content, font_source, bg_darkness, text_color):
    target_name = str(row['Image_Name']).strip()
    img_data = None
    matched_path = None
    
    # 💡 終極模糊匹配：先找完美結尾，找不到就改用關鍵字包含搜尋
    for name in zip_namelist:
        if name.endswith(target_name):
            matched_path = name
            break
            
    if not matched_path:
        # 比如 target_name 是 "001.jpg"，而 ZIP 裡叫 "bg_001.jpg"
        for name in zip_namelist:
            if target_name in name:
                matched_path = name
                break

    if matched_path:
        try:
            img_data = zip_file.read(matched_path)
            card_img = Image.open(io.BytesIO(img_data)).convert("RGBA")
        except:
            img_data = None

    # 如果還是徹底找不到，用溫和的粉米色打底防禦，絕對不給黑底
    if img_data is None:
        card_img = Image.new("RGBA", (1000, 1000), (245, 242, 235, 255))
    
    card_img = card_img.resize((1000, 1000), resample=Image.Resampling.BILINEAR)
    draw = ImageDraw.Draw(card_img, "RGBA")
    
    # 畫半透明遮罩
    if bg_darkness > 0:
        draw.rectangle([0, 0, 1000, 1000], fill=(0, 0, 0, int(255 * bg_darkness)))
        
    max_text_width = 800
    content_text = str(row['Content']).replace(" ", "")
    lines = text_wrap(content_text, font_content, max_text_width, draw)
    
    sample_bbox = draw.textbbox((0, 0), "高", font=font_content)
    line_height = (sample_bbox[3] - sample_bbox[1]) * 1.5
    start_y = (1000 - (len(lines) * line_height)) / 2 - 30
    
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font_content)
        x = (1000 - (bbox[2] - bbox[0])) / 2
        y = start_y + (i * line_height)
        # 文字黑色陰影
        draw.text((x+2, y+2), line, fill=(0, 0, 0, 255), font=font_content)
        # 文字主色
        draw.text((x, y), line, fill=text_color, font=font_content)
        
    source_text = str(row['Source'])
    if source_text and source_text != "nan":
        bbox_s = draw.textbbox((0, 0), source_text, font=font_source)
        x_s = 1000 - (bbox_s[2] - bbox_s[0]) - 80
        y_s = 880
        draw.text((x_s+1, y_s+1), source_text, fill=(0, 0, 0, 255), font=font_source)
        draw.text((x_s, y_s), source_text, fill=text_color, font=font_source)
        
    return card_img.convert("RGB")

if uploaded_csv and uploaded_zip:
    if st.button("🚀 開始批次排版並生成預覽", type="primary"):
        with st.spinner("正在進行智慧檔名匹配並讀取素材底圖中..."):
            df = pd.read_csv(uploaded_csv)
            zip_file = zipfile.ZipFile(uploaded_zip)
            zip_namelist = [n for n in zip_file.namelist() if not n.endswith('/')] # 排除資料夾路徑，只留檔案
            
            font_c, font_s = None, None
            if font_mode == "自行從電腦上傳 TTF" and uploaded_font:
                font_bytes = io.BytesIO(uploaded_font.read())
                font_c = ImageFont.truetype(font_bytes, font_size_content)
                font_bytes.seek(0)
                font_s = ImageFont.truetype(font_bytes, font_size_source)
            else:
                font_paths = ["fonts/芫荽.ttf", "芫荽.ttf"]
                for p in font_paths:
                    if os.path.exists(p):
                        font_c = ImageFont.truetype(p, font_size_content)
                        font_s = ImageFont.truetype(p, font_size_source)
                        break
                if font_c is None:
                    font_c = ImageFont.load_default()
                    font_s = ImageFont.load_default()

            pdf_buffer = io.BytesIO()
            c = canvas.Canvas(pdf_buffer, pagesize=A4)
            
            margin_x, margin_y = 10, 15
            card_w, card_h = 95, 89
            
            total_cards = len(df)
            progress_bar = st.progress(0)
            
            current_page_img = Image.new("RGB", (840, 1188), (255, 255, 255))
            page_draw = ImageDraw.Draw(current_page_img)
            temp_preview_bytes = []

            for index, row in df.iterrows():
                card_pil = generate_card_image(row, zip_file, zip_namelist, font_c, font_s, bg_darkness, text_color)
                
                grid_idx = index % 6
                col = grid_idx % 2
                row_idx = grid_idx // 2
                
                # ReportLab PDF 繪製
                x_pos_pdf = (margin_x + col * card_w) * mm
                y_pos_pdf = (297 - margin_y - (row_idx + 1) * card_h) * mm
                
                img_byte_arr = io.BytesIO()
                card_pil.save(img_byte_arr, format='JPEG', quality=85)
                img_byte_arr.seek(0)
                c.drawImage(canvas.ImageReader(img_byte_arr), x_pos_pdf, y_pos_pdf, width=card_w*mm, height=card_h*mm)
                
                if show_cut_lines:
                    c.setStrokeColorRGB(0.7, 0.7, 0.7)
                    c.setLineWidth(0.3)
                    c.rect(x_pos_pdf, y_pos_pdf, card_w*mm, card_h*mm)
                
                # 預覽圖繪製
                x_pos_img = (margin_x + col * card_w) * 4
                y_pos_img = (margin_y + row_idx * card_h) * 4
                
                resized_preview_card = card_pil.resize((card_w * 4, card_h * 4), resample=Image.Resampling.BILINEAR)
                current_page_img.paste(resized_preview_card, (x_pos_img, y_pos_img))
                
                if show_cut_lines:
                    page_draw.rectangle([x_pos_img, y_pos_img, x_pos_img + card_w*4, y_pos_img + card_h*4], outline=(180, 180, 180), width=1)
                
                progress_bar.progress((index + 1) / total_cards)
                
                if grid_idx == 5 or index == total_cards - 1:
                    c.showPage()
                    b = io.BytesIO()
                    current_page_img.save(b, format="JPEG", quality=75)
                    temp_preview_bytes.append(b.getvalue())
                    
                    current_page_img = Image.new("RGB", (840, 1188), (255, 255, 255))
                    page_draw = ImageDraw.Draw(current_page_img)
            
            c.save()
            pdf_buffer.seek(0)
            
            st.session_state.pdf_data = pdf_buffer.getvalue()
            st.session_state.preview_bytes_list = temp_preview_bytes
            st.success(f"🎉 智慧模糊配對排版完成！共生成 {len(temp_preview_bytes)} 頁 A4 排版。")

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
                type="primary"
            )
            st.info("💡 溫馨提醒：列印 PDF 時請將印表機設定為「實際大小(100%)」或「不縮放」，裁切線才會最準確喔！")
            
        with col_view:
            st.subheader("👀 A4 每頁排版即時預覽")
            total_p = len(st.session_state.preview_bytes_list)
            
            if total_p > 1:
                page_select = st.slider("切換預覽頁數", 1, total_p, 1)
            else:
                page_select = 1
                
            st.write(f"📄 當前正在預覽第 **{page_select}** / {total_p} 頁")
            st.image(st.session_state.preview_bytes_list[page_select - 1], caption=f"第 {page_select} 頁 A4 實際排版樣貌", use_container_width=True)
else:
    st.info("💡 請在上方欄位分別拖入 csv 與 zip 素材包，系統就會啟動批次 PDF 排版與即時預覽功能。")
