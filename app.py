import streamlit as st
import pandas as pd
import zipfile
import io
import os
import re
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

# 頁面基本設定
st.set_page_config(page_title="創價鼓勵小卡產生器", layout="wide", page_icon="🍀")

st.title("🍀 創價鼓勵小卡 A4 2x3 批次產生器")
st.write("請上傳先前由 Colab 下載的素材包，一鍵生成適合列印與裁切的 A4 PDF 檔案。")

# --- 側邊欄控制面板 ---
st.sidebar.header("🎨 小卡視覺調整面板")

# 1. 字型設定
font_mode = st.sidebar.radio("中文字型來源", ["使用 GitHub 倉庫內置字型 (芫荽.ttf)", "自行從電腦上傳 TTF"])
uploaded_font = None
if font_mode == "自行從電腦上傳 TTF":
    uploaded_font = st.sidebar.file_uploader("上傳字型 (.ttf)", type=["ttf"])

# 2. 視覺參數微調
font_size_content = st.sidebar.slider("正文字型大小", 20, 60, 38, step=2)
font_size_source = st.sidebar.slider("出處字型大小", 14, 40, 22, step=2)
text_color = st.sidebar.color_picker("文字顏色", "#FFFFFF")
bg_darkness = st.sidebar.slider("背景遮罩黯淡度 (讓白字更清晰)", 0.0, 1.0, 0.3, step=0.05)
show_cut_lines = st.sidebar.checkbox("顯示 A4 裁切虛線", value=True)

# --- 主畫面：檔案上傳區 ---
col1, col2 = st.columns(2)
with col1:
    uploaded_csv = st.file_uploader("1. 上傳語錄表格 (soka_quotes.csv)", type=["csv"])
with col2:
    uploaded_zip = st.file_uploader("2. 上傳素材壓縮包 (soka_all_materials.zip)", type=["zip"])

# --- 核心處理邏輯 ---
def text_wrap(text, font, max_width, draw):
    """將文字根據寬度精準自動換行"""
    lines = []
    words = list(text)  # 中文字直接拆成單字
    current_line = ""
    
    for word in words:
        test_line = current_line + word
        bbox = draw.textbbox((0, 0), test_line, font=font)
        line_width = bbox[2] - bbox[0]
        
        if line_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return lines

def generate_card_image(row, zip_file, font_content, font_source, bg_darkness, text_color):
    """在記憶體中將文字壓在背景圖上，生成單張卡片"""
    img_name = f"images/{row['Image_Name']}"
    
    # 從 ZIP 中讀取圖片
    try:
        img_data = zip_file.read(img_name)
        card_img = Image.open(io.BytesIO(img_data)).convert("RGB")
    except Exception:
        # 備用暖色調背景
        card_img = Image.new("RGB", (1000, 1000), (245, 242, 235))
    
    # 確保解析度為 1000x1000 正方形
    card_img = card_img.resize((1000, 1000))
    
    # 套用半透明黑色遮罩，提升文字可讀性
    if bg_darkness > 0:
        overlay = Image.new("RGBA", card_img.size, (0, 0, 0, int(255 * bg_darkness)))
        card_img = Image.alpha_composite(card_img.convert("RGBA"), overlay).convert("RGB")
        
    draw = ImageDraw.Draw(card_img)
    
    # 計算正文排版（限制寬度為 800 像素，預留左右安全邊距）
    max_text_width = 800
    content_text = str(row['Content']).replace(" ", "")  # 移除多餘空格
    lines = text_wrap(content_text, font_content, max_text_width, draw)
    
    # 計算行高與總高度（加入 1.5 倍行距讓書法體不擁擠）
    sample_bbox = draw.textbbox((0, 0), "高", font=font_content)
    char_height = sample_bbox[3] - sample_bbox[1]
    line_height = char_height * 1.5
    total_text_height = len(lines) * line_height
    
    # 繪製正文 (垂直完美置中偏上)
    start_y = (1000 - total_text_height) / 2 - 30
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font_content)
        w = bbox[2] - bbox[0]
        x = (1000 - w) / 2
        y = start_y + (i * line_height)
        
        # 增加輕微文字陰影，確保白字在任何風景下都清晰可見
        draw.text((x+2, y+2), line, fill="#000000", font=font_content)
        draw.text((x, y), line, fill=text_color, font=font_content)
        
    # 繪製出處 (右下角固定邊距)
    source_text = str(row['Source'])
    if source_text and source_text != "nan":
        bbox_s = draw.textbbox((0, 0), source_text, font=font_source)
        w_s = bbox_s[2] - bbox_s[0]
        x_s = 1000 - w_s - 80
        y_s = 880
        # 出處同樣加陰影
        draw.text((x_s+1, y_s+1), source_text, fill="#000000", font=font_source)
        draw.text((x_s, y_s), source_text, fill=text_color, font=font_source)
        
    return card_img

# --- 觸發生成按鈕 ---
if uploaded_csv and uploaded_zip:
    if st.button("🚀 開始批次排版，生成 A4 PDF", type="primary"):
        with st.spinner("正在讀取素材並渲染高畫質小卡中..."):
            
            # 讀取資料
            df = pd.read_csv(uploaded_csv)
            zip_file = zipfile.ZipFile(uploaded_zip)
            
            # 精準字型尋找邏輯
            font_c, font_s = None, None
            
            if font_mode == "自行從電腦上傳 TTF" and uploaded_font:
                font_bytes = io.BytesIO(uploaded_font.read())
                font_c = ImageFont.truetype(font_bytes, font_size_content)
                font_bytes.seek(0)
                font_s = ImageFont.truetype(font_bytes, font_size_source)
            else:
                # 依序偵測你上傳在 GitHub 上的路徑
                font_paths = [
                    "fonts/芫荽.ttf", 
                    "芫荽.ttf",
                    "font.ttf"
                ]
                for p in font_paths:
                    if os.path.exists(p):
                        try:
                            font_c = ImageFont.truetype(p, font_size_content)
                            font_s = ImageFont.truetype(p, font_size_source)
                            break
                        except:
                            continue
                
                # 【已修正】如果都找不到，拋出警告並用系統預設
                if font_c is None or font_s is None:
                    st.warning("⚠️ 倉庫中未找到指定字型，暫時切換為預設字型。")
                    font_c = ImageFont.load_default()
                    font_s = ImageFont.load_default()

            # 建立 PDF 緩衝區
            pdf_buffer = io.BytesIO()
            c = canvas.Canvas(pdf_buffer, pagesize=A4)
            
            # A4 精準對齊網格常數 (單位: mm)
            a4_w, a4_h = 210, 297
            margin_x = 10  # 左右邊界留白
            margin_y = 15  # 上下邊界留白
            
            card_w = 95    # 單張卡片寬度 95mm
            card_h = 89    # 單張卡片高度 89mm (2x3 完美填滿 A4 可列印區)
            
            total_cards = len(df)
            
            # 建立 Streamlit 進度條
            progress_bar = st.progress(0)
            
            for index, row in df.iterrows():
                # 1. 渲染卡片影像
                card_pil = generate_card_image(row, zip_file, font_c, font_s, bg_darkness, text_color)
                
                # 2. 計算當頁 A4 的網格位置 (0~5)
                grid_idx = index % 6
                col = grid_idx % 2          # 0為左欄，1為右欄
                row_idx = grid_idx // 2      # 0上、1中、2下
                
                # ReportLab 座標系轉換（起點在左下角）
                x_pos = (margin_x + col * card_w) * mm
                y_pos = (a4_h - margin_y - (row_idx + 1) * card_h) * mm
                
                # 將圖片轉為 JPEG 壓縮流，餵給 PDF
                img_byte_arr = io.BytesIO()
                card_pil.save(img_byte_arr, format='JPEG', quality=90)
                img_byte_arr.seek(0)
                
                c.drawImage(canvas.ImageReader(img_byte_arr), x_pos, y_pos, width=card_w*mm, height=card_h*mm)
                
                # 3. 繪製裁切線
                if show_cut_lines:
                    c.setStrokeColorRGB(0.7, 0.7, 0.7)  # 質感淺灰色，方便裁切又不影響美觀
                    c.setLineWidth(0.3)
                    c.setDash(2, 2)  # 虛線
                    c.rect(x_pos, y_pos, card_w*mm, card_h*mm)
                
                # 更新進度條
                progress_bar.progress((index + 1) / total_cards)
                
                # 每滿 6 張或到最後一張，換頁
                if grid_idx == 5 or index == total_cards - 1:
                    c.showPage()
            
            c.save()
            pdf_buffer.seek(0)
            
            st.success(f"🎉 完美排版完成！已成功將 {total_cards} 條箴言轉換為 A4 2x3 印刷規格 PDF。")
            
            # 提供大按鈕下載
            st.download_button(
                label="📥 下載 2x3 A4 完美列印 PDF",
                data=pdf_buffer,
                file_name="soka_encouragement_cards_A4.pdf",
                mime="application/pdf"
            )
else:
    st.info("💡 請在上方欄位分別拖入 csv 與 zip 素材包，系統就會啟動批次 PDF 排版功能。")
