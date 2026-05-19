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
