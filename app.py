# ==========================================
# 創價學會每日箴言與風景底圖全自動抓取腳本 (Colab 專用)
# ==========================================

import requests
from bs4 import BeautifulSoup
import pandas as pd
import os
import time
import shutil
from google.colab import files

print("🚀 專案初始化中...")

# 1. 建立存放資料的資料夾
base_dir = 'soka_card_project'
img_dir = os.path.join(base_dir, 'images')
os.makedirs(img_dir, exist_ok=True)

# 2. 定義月份與天數 (抓取大約 300 天的資料，這邊跑全年度)
months = ["january", "february", "march", "april", "may", "june", 
          "july", "august", "september", "october", "november", "december"]
days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

quotes_list = []
count = 0
max_cards = 300 # 設定抓取目標上限為 300 組

print("📥 開始抓取語錄與高畫質風景底圖 (預計需要幾分鐘，請稍候)...")

for m_idx, month in enumerate(months):
    if count >= max_cards:
        break
        
    for day in range(1, days_in_month[m_idx] + 1):
        if count >= max_cards:
            break
            
        date_str = f"{m_idx+1}月{day}日"
        url = f"https://www.sokaglobal.org/cht/resources/daily-encouragement/{month}-{day}.html"
        
        try:
            # 爬取網頁文字
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                
                # 抓取網頁中的文字區塊 (根據官網結構優化)
                page_text = soup.get_text()
                
                # 尋找核心語錄 (利用「摘自：」作為錨點進行智慧切取)
                if "摘自：" in page_text:
                    lines = [l.strip() for l in page_text.split('\n') if l.strip()]
                    content = ""
                    source = ""
                    
                    for i, line in enumerate(lines):
                        if "摘自：" in line:
                            source = line
                            # 通常語錄就在「摘自：」的前一行
                            if i > 0:
                                content = lines[i-1]
                            break
                    
                    # 如果抓取邏輯太嚴格沒抓到，就用備用方案
                    if not content:
                        content = f"這是 {date_str} 的池田先生指導語錄，請於 Excel 中微調。"
                else:
                    continue # 如果沒有核心內容就跳過
                
                # 3. 下載對應的隨機高畫質風景底圖 (使用 Picsum 高畫質風景圖庫)
                # 使用 count 作為隨機種子，確保 300 張風景絕對不重複！
                img_url = f"https://picsum.photos/id/{10 + count}/1000/1000" 
                img_res = requests.get(img_url, timeout=10)
                
                img_filename = f"bg_{count+1:03d}.jpg"
                img_path = os.path.join(img_dir, img_filename)
                
                if img_res.status_code == 200:
                    with open(img_path, 'wb') as f:
                        f.write(img_res.content)
                
                # 紀錄到清單中
                quotes_list.append({
                    "ID": f"{count+1:03d}",
                    "Date": date_str,
                    "Content": content,
                    "Source": source,
                    "Image_Name": img_filename
                })
                
                count += 1
                print(f"✅ 已成功下載第 {count}/300 組 [{date_str}] 的文字與底圖")
                
            else:
                print(f"⚠️ 網頁跳過: {month}-{day}")
        except Exception as e:
            print(f"❌ {date_str} 發生錯誤: {e}")
            
        # 禮貌性停頓 0.5 秒，避免對網站伺服器造成負擔
        time.sleep(0.5)

# 4. 儲存成 CSV 表格
df = pd.DataFrame(quotes_list)
csv_path = os.path.join(base_dir, 'soka_quotes.csv')
df.to_csv(csv_path, index=False, encoding='utf-8-sig')
print("\n📊 語錄 CSV 表格建立完成！")

# 5. 打包圖片資料夾成 ZIP 壓縮檔
print("📦 正在將 300 張風景圖打包壓縮...")
zip_path = shutil.make_archive('soka_images_backup', 'zip', img_dir)
print("📦 圖片打包完成！")

print("\n🎉 所有任務搞定！瀏覽器即將自動彈出下載視窗...")
# 6. 自動觸發下載到你的電腦
files.download(csv_path)       # 下載表格
files.download(zip_path)       # 下載圖片壓縮包
print("✨ 檢查你的電腦下載資料夾吧！應該會看到 soka_quotes.csv 與 soka_images_backup.zip")
