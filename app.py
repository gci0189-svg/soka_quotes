import os
from PIL import Image, ImageDraw, ImageFont


def generate_card(
    background_path,
    output_path,
    text,
    source_text,
    font_path,
    font_size=60,
    source_font_size=32,
):
    # 1. 讀取背景圖片
    if not os.path.exists(background_path):
        raise FileNotFoundError(f"找不到背景圖片: {background_path}")

    image = Image.open(background_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    img_width, img_height = image.size

    # 2. 載入字型
    try:
        font = ImageFont.truetype(font_path, font_size)
        source_font = ImageFont.truetype(font_path, source_font_size)
    except IOError:
        print(f"無法載入字型 {font_path}，將使用系統預設字型。")
        font = ImageFont.load_default()
        source_font = ImageFont.load_default()

    # 3. 處理正文（保留手動換行 \n）
    lines = text.split("\n")

    # 計算正文的總高度，以便整體垂直置中
    line_heights = []
    line_widths = []
    for line in lines:
        # 取得單行文字的邊框大小
        bbox = draw.textbbox((0, 0), line, font=font)
        line_width = bbox[2] - bbox[0]
        line_height = bbox[3] - bbox[1]
        line_widths.append(line_width)
        line_heights.append(line_height)

    # 設定行距比例
    line_spacing_factor = 1.4
    total_text_height = sum(line_heights) + int(
        (len(lines) - 1) * font_size * (line_spacing_factor - 1)
    )

    # 計算正文起始的 Y 座標（垂直置中，稍微往上偏一點給出處留空間）
    start_y = (img_height - total_text_height) // 2 - 40

    # 4. 繪製正文（含黑色描邊效果）
    current_y = start_y
    for i, line in enumerate(lines):
        # 計算水平置中 X 座標
        x = (img_width - line_widths[i]) // 2

        # 繪製文字與描邊 (stroke_width 設為 4 實現黑框效果)
        draw.text(
            (x, current_y),
            line,
            font=font,
            fill="white",
            stroke_width=4,
            stroke_fill="black",
        )

        # 累加下一行的 Y 座標
        current_y += line_heights[i] + int(
            font_size * (line_spacing_factor - 1)
        )

    # 5. 繪製出處（固定在底部區域，字體較小）
    if source_text:
        source_bbox = draw.textbbox((0, 0), source_text, font=source_font)
        source_width = source_bbox[2] - source_bbox[0]
        source_x = (img_width - source_width) // 2
        # 出處 Y 座標固定在距離底部約 12% 處
        source_y = img_height - int(img_height * 0.12)

        draw.text(
            (source_x, source_y),
            source_text,
            font=source_font,
            fill="white",
            stroke_width=3,
            stroke_fill="black",
        )

    # 6. 儲存輸出圖片
    image.save(output_path, "JPEG", quality=95)
    print(f"卡片已成功生成並儲存至: {output_path}")


# --- 測試執行參數 ---
if __name__ == "__main__":
    # 請根據您的實際路徑填寫
    BG_PATH = "background.jpg"  # 您的背景圖路徑
    OUT_PATH = "output_card.jpg"  # 輸出圖路徑
    FONT_PATH = "思源黑體 Medium.ttf"  # 字型檔案路徑

    # 您設定的手動換行文字
    INPUT_TEXT = (
        "好，讓我們輕鬆地邁出新步伐！\n"
        "人生就是和有限生命的競賽。\n"
        "既然如此，\n"
        "那每天就必須不斷地前進。"
    )

    SOURCE_TEXT = "摘自：《新人間革命》第二十卷〈橋樑〉"

    # 執行生成
    # generate_card(BG_PATH, OUT_PATH, INPUT_TEXT, SOURCE_TEXT, FONT_PATH, font_size=60)
