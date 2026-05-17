import streamlit as st
import pandas as pd
import zipfile
import io
import os
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

# 1. 字型設定 (考量 Streamlit Cloud 部署，提供預設字型或自訂上傳)
font_mode = st.sidebar.radio("中文字型來源", ["使用系統預設細明體/微軟正黑體", "自行上傳 TTF 字型檔"])
uploaded_font = None
if font_mode == "自行上傳 TTF 字型檔":
    uploaded_font = st.sidebar.file_uploader("上傳字型 (.ttf)", type=["ttf"])

# 2. 視覺參數微調
font_size_content = st.sidebar.slider("正文字型大小", 20, 50, 28)
font_size_source = st.sidebar.slider("出處字型大小", 14, 30, 18)
text_color = st.sidebar.color_picker("文字顏色", "#FFFFFF")
bg_darkness = st.sidebar.slider("背景遮罩黯淡度 (讓白字更清晰)", 0.0, 1.0, 0.4, step=0.1)
show_cut_lines = st.sidebar.checkbox("顯示 A4 裁切虛線", value=True)

# --- 主畫面：檔案上傳區 ---
col1, col2 = st.columns(2)
with col1:
    uploaded_csv = st.file_uploader("1. 上傳語錄表格 (soka_quotes.csv)", type=["csv"])
with col2:
    uploaded_zip = st.file_uploader("2. 上傳素材壓縮包 (soka_all_materials.zip)", type=["zip"])

# --- 核心處理邏輯 ---
def text_wrap(text, font, max_width, draw):
    """將文字自動根據寬度換行"""
    lines = []
    words = list(text) # 中文字直接拆成單字
    current_line = ""
    
    for word in words:
        test_line = current_line + word
        # 取得文字寬度
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
        # 如果找不到對應圖片，建立一張暖色調純色背景頂替
        card_img = Image.new("RGB", (1000, 1000), (245, 242, 235))
    
    # 調整大小為 1000x1000 確保解析度一致
    card_img = card_img.resize((1000, 1000))
    
    # 套用半透明黑色遮罩，提升文字可讀性
    if bg_darkness > 0:
        overlay = Image.new("RGBA", card_img.size, (0, 0, 0, int(255 * bg_darkness)))
        card_img = Image.alpha_composite(card_img.convert("RGBA"), overlay).convert("RGB")
        
    draw = ImageDraw.Draw(card_img)
    
    # 計算正文排版（限制寬度為 850 像素，留邊框）
    max_text_width = 850
    content_text = str(row['Content'])
    lines = text_wrap(content_text, font_content, max_text_width, draw)
    
    # 計算文字總高度以利置中
    line_height = draw.textbbox((0, 0), "測試", font=font_content)[3] * 1.4
    total_text_height = len(lines) * line_height
    
    # 繪製正文 (垂直偏中上)
    start_y = (1000 - total_text_height) / 2 - 40
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font_content)
        w = bbox[2] - bbox[0]
        x = (1000 - w) / 2
        y = start_y + (i * line_height)
        draw.text((x, y), line, fill=text_color, font=font_content)
        
    # 繪製出處 (靠右下偏置)
    source_text = str(row['Source'])
    if source_text and source_text != "nan":
        bbox_s = draw.textbbox((0, 0), source_text, font=font_source)
        w_s = bbox_s[2] - bbox_s[0]
        x_s = 1000 - w_s - 80
        y_s = 900
        draw.text((x_s, y_s), source_text, fill=text_color, font=font_source)
        
    return card_img

# --- 觸發生成按鈕 ---
if uploaded_csv and uploaded_zip:
    if st.button("🚀 開始批次排版，生成 A4 PDF", type="primary"):
        with st.spinner("正在瘋狂排版中，請稍候..."):
            
            # 讀取資料
            df = pd.read_csv(uploaded_csv)
            zip_file = zipfile.ZipFile(uploaded_zip)
            
            # 載入字型
            if font_mode == "自行上傳 TTF 字型檔" and uploaded_font:
                font_bytes = io.BytesIO(uploaded_font.read())
                font_c = ImageFont.truetype(font_bytes, font_size_content)
                font_bytes.seek(0)
                font_s = ImageFont.truetype(font_bytes, font_size_source)
            else:
                # 自動偵測系統常見中文 Windows/Mac 字型
                possible_fonts = ["msjh.ttc", "pingfang.ttc", "arial.ttf"]
                font_path = "arial.ttf"
                for f in possible_fonts:
                    try:
                        ImageFont.truetype(f, 10)
                        font_path = f
                        break
                    except:
                        continue
                font_c = ImageFont.truetype(font_path, font_size_content)
                font_s = ImageFont.truetype(font_path, font_size_source)

            # 建立 PDF 記憶體緩衝
            pdf_buffer = io.BytesIO()
            c = canvas.Canvas(pdf_buffer, pagesize=A4)
            
            # A4 規格常數計算 (單位: mm)
            a4_w, a4_h = 210, 297
            margin_x = 10  # 左右留白
            margin_y = 15  # 上下留白
            
            card_w = 95    # 單張卡片寬度
            card_h = 89    # 單張卡片高度 (95x2=190 + 20 = 210; 89x3=267 + 30 = 297 完美填滿)
            
            total_cards = len(df)
            
            for index, row in df.iterrows():
                # 1. 生成卡片圖
                card_pil = generate_card_image(row, zip_file, font_c, font_s, bg_darkness, text_color)
                
                # 2. 計算這張卡片在當前 A4 頁面的網格位置 (0 到 5)
                grid_idx = index % 6
                col = grid_idx % 2 # 0(左), 1(右)
                row_idx = grid_idx // 2 # 0(上), 1(中), 2(下)
                
                # ReportLab 座標系起點在左下角，需要作對應轉換
                x_pos = (margin_x + col * card_w) * mm
                y_pos = (a4_h - margin_y - (row_idx + 1) * card_h) * mm
                
                # 將 PIL 圖片轉為 ReportLab 可讀格式並畫上 PDF
                img_byte_arr = io.BytesIO()
                card_pil.save(img_byte_arr, format='JPEG', quality=95)
                img_byte_arr.seek(0)
                
                c.drawImage(canvas.ImageReader(img_byte_arr), x_pos, y_pos, width=card_w*mm, height=card_h*mm)
                
                # 3. 繪製外框/裁切虛線
                if show_cut_lines:
                    c.setStrokeColorRGB(0.7, 0.7, 0.7) # 淺灰色
                    c.setLineWidth(0.5)
                    c.setDash(2, 2) # 虛線樣式
                    c.rect(x_pos, y_pos, card_w*mm, height=card_h*mm)
                
                # 每滿 6 張，或是最後一張時，重刷下一頁 A4
                if grid_idx == 5 or index == total_cards - 1:
                    c.showPage()
            
            c.save()
            pdf_buffer.seek(0)
            
            st.success(f"🎉 成功排版完成！已將 {total_cards} 張小卡完美塞進 PDF 中。")
            
            # 提供下載按鈕
            st.download_button(
                label="📥 下載 2x3 A4 完美列印 PDF",
                data=pdf_buffer,
                file_name="soka_encouragement_cards_A4.pdf",
                mime="application/pdf"
            )
else:
    st.info("💡 請在上方分別上傳表格與圖片壓縮包，系統便會自動解鎖 PDF 生成按鈕。")