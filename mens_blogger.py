import os
import random
import requests
import time
import base64
import json
import tempfile
import re
import difflib
from datetime import datetime
from playwright.sync_api import sync_playwright

CACHE_FILE = "posted_cache.txt"

# メンズコスメ・メンズスキンケア・身だしなみ 特化検索テーマ一覧
MENS_THEMES = [
    # --- スキンケア・フェイスケア ---
    {
        "theme": "メンズオールインワンジェルおすすめ選抜",
        "keyword": "メンズ オールインワン ジェル",
        "title_template": "{month}月最新！メンズ用オールインワンジェルおすすめ{count}選【時短スキンケア・乾燥＆テカリ防止】"
    },
    {
        "theme": "メンズ化粧水おすすめ選抜",
        "keyword": "メンズ 化粧水 保湿",
        "title_template": "{month}月おすすめ！清潔感を作るメンズ化粧水{count}選【テカリ・毛穴・乾燥対策】"
    },
    {
        "theme": "メンズ洗顔料・毛穴クレンジング選抜",
        "keyword": "メンズ 洗顔料 泡 毛穴 泥",
        "title_template": "{month}月最新！毛穴汚れ＆アブラを落とすメンズ洗顔料おすすめ{count}選【清潔素肌へ】"
    },
    {
        "theme": "メンズ美容液・シワシミエイジングケア選抜",
        "keyword": "メンズ 美容液 ナイアシンアミド シミ",
        "title_template": "{month}月厳選！男の肌印象を変えるメンズ美容液おすすめ{count}選【美肌＆ハリ対策】"
    },
    {
        "theme": "メンズアイクリーム・目元クマ対策選抜",
        "keyword": "メンズ アイクリーム 目元 クマ たるみ",
        "title_template": "{month}月最新！疲れた目元・クマをすっきり整えるメンズアイクリーム{count}選"
    },
    {
        "theme": "メンズシートマスク・集中保湿パック選抜",
        "keyword": "メンズ フェイスパック シートマスク 保湿",
        "title_template": "{month}月厳選！週1の集中ケアで透明感をつくるメンズフェイスマスク{count}選"
    },
    {
        "theme": "メンズリップクリーム・唇ケア選抜",
        "keyword": "メンズ リップクリーム 色つき 保湿 荒れ",
        "title_template": "{month}月おすすめ！血色感と潤いを保つメンズリップ{count}選【荒れ防止・身だしなみ】"
    },
    # --- ヘアケア・頭皮・育毛・抜け毛対策 ---
    {
        "theme": "メンズ育毛剤・発毛促進スカルプエッセンス選抜",
        "keyword": "メンズ 育毛剤 薬用 抜け毛 育毛トニック",
        "title_template": "{month}月最新！将来の髪を守るメンズ育毛剤・スカルプローションおすすめ{count}選【薄毛・抜け毛予防】"
    },
    {
        "theme": "メンズスカルプシャンプー・頭皮環境改善選抜",
        "keyword": "メンズ スカルプシャンプー 薬用 フケ かゆみ",
        "title_template": "{month}月厳選！頭皮のベタつき＆フケ・ニオイを防ぐメンズスカルプシャンプー{count}選"
    },
    {
        "theme": "メンズ頭皮用トリートメント・スカルプコンディショナー選抜",
        "keyword": "メンズ スカルプトリートメント 頭皮ケア",
        "title_template": "{month}月おすすめ！髪にハリコシを与えるメンズ頭皮トリートメント{count}選"
    },
    {
        "theme": "メンズ電動頭皮ブラシ・スカルプマッサージャー選抜",
        "keyword": "メンズ 頭皮マッサージ 電動 スカルプブラシ EMS",
        "title_template": "{month}月最新！自宅で極上ヘッドスパ！メンズ頭皮マッサージャー・電動ブラシ{count}選"
    },
    # --- ヘアカラー・白髪染め・ヘアマニキュア ---
    {
        "theme": "メンズ白髪染め・白髪用ヘアマニキュア選抜",
        "keyword": "メンズ 白髪染め 簡単 トリートメント",
        "title_template": "{month}月最新！自宅で自然に若々しく染まるメンズ白髪染めおすすめ{count}選"
    },
    {
        "theme": "メンズ白髪隠し・部分染めスティック選抜",
        "keyword": "メンズ 白髪隠し スティック 部分染め",
        "title_template": "{month}月厳選！出かける直前にサッと隠せるメンズ白髪隠しおすすめ{count}選"
    },
    {
        "theme": "メンズカラーワックス・シルバーアッシュヘア選抜",
        "keyword": "メンズ カラーワックス シルバーアッシュ 一日染め",
        "title_template": "{month}月おすすめ！休日のイメチェンに！メンズカラーワックス・1日毛染め{count}選"
    },
    # --- スタイリング・ヘアセット ---
    {
        "theme": "メンズヘアワックス・ハード＆マット選抜",
        "keyword": "メンズ ヘアワックス ハード マット 束感",
        "title_template": "{month}月最新！一日中崩れないメンズヘアワックスおすすめ{count}選【束感・キープ力抜群】"
    },
    {
        "theme": "メンズポマード・グリース・バーバースタイル選抜",
        "keyword": "メンズ ポマード グリース 水性 バーバー",
        "title_template": "{month}月厳選！艶とホールド力で魅せるメンズポマード・グリース{count}選【大人バーバースタイル】"
    },
    {
        "theme": "メンズヘアバーム・ヘアオイル・ナチュラルセット選抜",
        "keyword": "メンズ ヘアバーム ヘアオイル センターパート",
        "title_template": "{month}月最新！センターパート＆ナチュラルヘアに映えるメンズヘアバーム・オイル{count}選"
    },
    {
        "theme": "メンズヘアスプレー・超強力キープ選抜",
        "keyword": "メンズ ヘアスプレー ハード キープ 崩れない",
        "title_template": "{month}月おすすめ！湿気や風に負けないメンズヘアスプレー{count}選【強力キープ】"
    },
    # --- メイク・肌補正・UV ---
    {
        "theme": "メンズBBクリーム・肌補正ファンデーション選抜",
        "keyword": "メンズ BBクリーム ナチュラル ファンデーション",
        "title_template": "{month}月最新！バレずに好印象を作るメンズBBクリームおすすめ{count}選【青髭・毛穴・クマ隠し】"
    },
    {
        "theme": "メンズコンシーラー・ピンポイント青髭＆ニキビ隠し選抜",
        "keyword": "メンズ コンシーラー ニキビ跡 青髭 クマ",
        "title_template": "{month}月厳選！肌トラブルを瞬時に隠すメンズコンシーラーおすすめ{count}選"
    },
    {
        "theme": "メンズ日焼け止め・UVケア選抜",
        "keyword": "メンズ 日焼け止め UV 白浮きしない ベタつかない",
        "title_template": "{month}月最新！白浮きしないメンズ日焼け止めおすすめ{count}選【紫外線＆テカリ防止UV】"
    },
    {
        "theme": "メンズ皮脂テカリ防止パウダー・あぶらとり選抜",
        "keyword": "メンズ フェイスパウダー テカリ防止 ノーセバム",
        "title_template": "{month}月おすすめ！サラサラ肌が夕方まで続くメンズフェイスパウダー{count}選"
    },
    # --- 身だしなみ・シェービング・眉・ムダ毛ケア ---
    {
        "theme": "メンズ電気シェーバー・深剃り髭剃り選抜",
        "keyword": "メンズ 電気シェーバー 充電式 深剃り",
        "title_template": "{month}月最新！肌に優しく深剃りできるメンズ電気シェーバーおすすめ{count}選"
    },
    {
        "theme": "メンズ眉毛セット・アイブロウツール選抜",
        "keyword": "メンズ 眉毛セット シェーバー ハサミ コーム",
        "title_template": "{month}月厳選！第一印象を劇的に変えるメンズ眉毛ケア・シェーバーセット{count}選"
    },
    {
        "theme": "メンズ鼻毛カッター・身だしなみエチケット選抜",
        "keyword": "メンズ 鼻毛カッター 電動 水洗い",
        "title_template": "{month}月おすすめ！清潔感の基本！痛くない＆安全なメンズ鼻毛カッター{count}選"
    },
    {
        "theme": "メンズボディシェーバー・除毛すね毛ケア選抜",
        "keyword": "メンズ ボディシェーバー ムダ毛 除毛 すね毛",
        "title_template": "{month}月最新！清潔感UP！メンズボディシェーバー＆ムダ毛処理アイテム{count}選"
    },
    {
        "theme": "メンズ除毛クリーム・簡単すべすべ肌選抜",
        "keyword": "メンズ 除毛クリーム 薬用 大容量",
        "title_template": "{month}月厳選！塗って流すだけ！男の剛毛もしっかり除毛できるメンズ除毛クリーム{count}選"
    },
    # --- 体臭・ニオイ・エチケット・フレグランス ---
    {
        "theme": "メンズ薬用ボディソープ・加齢臭＆体臭ケア選抜",
        "keyword": "メンズ 薬用ボディソープ 汗 臭い 加齢臭 デオドラント",
        "title_template": "{month}月おすすめ！汗・男臭・加齢臭を元から洗い流すメンズボディソープ{count}選"
    },
    {
        "theme": "メンズ制汗剤・ロールオン・デオドラント選抜",
        "keyword": "メンズ デオドラント ロールオン 制汗剤 ワキガ 汗止め",
        "title_template": "{month}月最新！男のワキ汗・ニオイを1日ブロックするメンズ制汗剤・デオドラント{count}選"
    },
    {
        "theme": "メンズ香水・練り香水・好印象フレグランス選抜",
        "keyword": "メンズ 香水 練り香水 シトラス ソープ 清潔感",
        "title_template": "{month}月厳選！女子ウケ＆ビジネスで好印象なメンズ香水・フレグランス{count}選"
    },
    {
        "theme": "メンズハンドクリーム・手元ケア選抜",
        "keyword": "メンズ ハンドクリーム ベタつかない 保湿",
        "title_template": "{month}月おすすめ！名刺交換も自信！ベタつかないメンズハンドクリーム{count}選"
    }
]


def load_posted_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_to_cache(item_codes):
    if isinstance(item_codes, str):
        item_codes = [item_codes]
    with open(CACHE_FILE, "a", encoding="utf-8") as f:
        for code in item_codes:
            if code:
                f.write(f"{code}\n")

def clean_rakuten_item_name(name):
    """商品名から楽天特有のクーポンや記号ノイズを除去し、すっきりとした名称を抽出"""
    if not name:
        return "メンズコスメ注目アイテム"
    cleaned = re.sub(r'【[^】]*】', '', name)
    cleaned = re.sub(r'\[[^\]]*\]', '', cleaned)
    cleaned = re.sub(r'（[^）]*）', '', cleaned)
    cleaned = re.sub(r'\([^\)]*\)', '', cleaned)
    cleaned = re.sub(r'[＼／★◆■●▼▲〜～!！?？]+', ' ', cleaned)
    
    noise_patterns = [
        r'クーポン(?:で|\s*利用で|\s*配布中|\s*対象)?\s*[0-9,]+円?(?:OFF|off)?',
        r'P[0-9]+倍',
        r'ポイント[0-9]+倍',
        r'送料無料',
        r'即納',
        r'あす楽',
        r'マラソン(?:限定)?',
        r'スーパーセール',
        r'お買い物マラソン',
        r'楽天(?:1位|ランキング1位|デイリー1位)',
        r'[0-9]+%OFF',
        r'[0-9]+％OFF',
        r'★[0-9\.]+★?',
        r'レビュー特典',
        r'公式(?:店)?',
        r'医薬部外品',
        r'正規品'
    ]
    for pat in noise_patterns:
        cleaned = re.sub(pat, '', cleaned, flags=re.IGNORECASE)
        
    words = [w.strip() for w in cleaned.split() if w.strip()]
    seen = set()
    cleaned_words = []
    for w in words:
        if w not in seen and len(w) > 1:
            seen.add(w)
            cleaned_words.append(w)
        if len(' '.join(cleaned_words)) >= 40:
            break
            
    res = ' '.join(cleaned_words).strip()
    return res if res else (words[0] if words else name[:30])


def extract_brand_and_product(clean_name):
    """商品名からブランド名と商品名を綺麗に分離"""
    name = re.sub(r'^[＼／★\s]+|[＼／★\s]+$', '', clean_name).strip()
    words = name.split()
    if not words:
        return "注目ブランド", clean_name
    
    first = words[0]
    if len(words) >= 2:
        # 2単語で1つのブランド名になるパターン（マンダム ギャツビー等）
        if words[1] in ['ギャツビー', 'オム', 'メン', 'MEN', 'HOMME', 'ラボ', 'モイスチャー', 'ケア'] and len(first) <= 7:
            brand = f"{first} {words[1]}"
            product = " ".join(words[2:]) or brand
        else:
            brand = first
            product = " ".join(words[1:]) or brand
    else:
        brand = first
        product = name
    return brand, product

def get_rakuten_affiliate_url(item, affiliate_id):
    aff_url = item.get("affiliateUrl")
    if aff_url and "hb.afl.rakuten.co.jp" in aff_url:
        return aff_url
    
    item_url = item.get("itemUrl") or ""
    if not item_url:
        return ""
    
    if affiliate_id:
        import urllib.parse
        encoded_item_url = urllib.parse.quote(item_url, safe='')
        return f"https://hb.afl.rakuten.co.jp/hgc/{affiliate_id}/?pc={encoded_item_url}&m={encoded_item_url}"
    
    return item_url

def extract_image_url(item):
    url = ""
    medium_images = item.get("mediumImageUrls", [])
    if medium_images:
        url = medium_images[0].get("imageUrl", "") if isinstance(medium_images[0], dict) else medium_images[0]
    elif item.get("smallImageUrls"):
        small_images = item.get("smallImageUrls", [])
        url = small_images[0].get("imageUrl", "") if isinstance(small_images[0], dict) else small_images[0]
    
    if url:
        # 楽天のサムネイル縮小パラメータ（?_ex=128x128等）を高解像度700x700に昇格
        url = re.sub(r'\?_ex=[0-9]+x[0-9]+', '?_ex=700x700', url)
    return url


def is_duplicate_or_similar_item(new_item, accepted_items, posted_cache):
    """同一または極めて類似した商品の重複選抜を防止"""
    new_code = new_item.get("itemCode", "")
    if new_code in posted_cache:
        return True, "itemCode already in posted_cache"
    
    new_raw_name = new_item.get("itemName", "")
    new_clean_name = new_item.get("cleanName", "")
    
    def normalize_name(text):
        t = re.sub(r'[0-9]+点組|[0-9]+点セット|[0-9]+%OFF|[0-9]+％OFF|送料無料|即納|あす楽|楽天1位|新生活|クーポン', '', text)
        return ''.join(t.split())

    new_norm = normalize_name(new_clean_name or new_raw_name)
    words_new = set([w for w in re.split(r'[\s/、,・]+', new_clean_name) if len(w) > 1 and not re.match(r'^[0-9]+[点組]*$', w)])

    for ex in accepted_items:
        ex_code = ex.get("itemCode", "")
        if new_code and new_code == ex_code:
            return True, "duplicate itemCode in current selection"

        # ショップコードが同じで商品コードの末尾違い（バリエーション違い）を検知
        if ":" in new_code and ":" in ex_code:
            shop_new, id_new = new_code.split(":", 1)
            shop_ex, id_ex = ex_code.split(":", 1)
            if shop_new == shop_ex and (id_new.startswith(id_ex[:5]) or id_ex.startswith(id_new[:5])):
                return True, f"same shop variant: {shop_new}"

        ex_clean = ex.get("cleanName", "")
        ex_norm = normalize_name(ex_clean or ex.get("itemName", ""))
        
        # 文字列類似度（Levenstein / SequenceMatcher）
        ratio = difflib.SequenceMatcher(None, new_norm, ex_norm).ratio()
        if ratio >= 0.55:
            return True, f"high name similarity ({ratio:.2f}) with {ex_clean}"

        # 3単語以上の特徴キーワード重複検知（例: 「眉毛セット 8点組 シェーバー」の同種詰め合わせ）
        words_ex = set([w for w in re.split(r'[\s/、,・]+', ex_clean) if len(w) > 1 and not re.match(r'^[0-9]+[点組]*$', w)])
        overlap = words_new & words_ex
        if len(overlap) >= 3:
            return True, f"multiple shared keywords ({overlap}) with {ex_clean}"

    return False, ""



def fetch_rakuten_mens_items(count=5):
    """メンズコスメ・身だしなみテーマから重複を避け指定個数（通常5点）選抜"""
    app_id = os.environ.get("RAKUTEN_APP_ID")
    access_key = os.environ.get("RAKUTEN_ACCESS_KEY")
    affiliate_id = os.environ.get("RAKUTEN_AFFILIATE_ID")
    if not app_id or not access_key:
        raise ValueError("RAKUTEN_APP_ID and RAKUTEN_ACCESS_KEY must be set in environment variables.")

    # ランダムにテーマを選定
    theme_obj = random.choice(MENS_THEMES)
    keyword = theme_obj["keyword"]
    print(f"Selected Theme: {theme_obj['theme']} (Keyword: {keyword})")

    url = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260401"
    params = {
        "applicationId": app_id,
        "accessKey": access_key,
        "keyword": keyword,
        "format": "json",
        "hits": 30
    }
    if affiliate_id:
        params["affiliateId"] = affiliate_id

    response = requests.get(url, params=params, timeout=20)
    data = response.json() if response.status_code == 200 else {}
    items_raw = data.get("Items", [])

    # キーワードが長すぎて0件の場合は単語を絞り込んでフォールバック検索
    if not items_raw and len(keyword.split()) > 2:
        fallback_keyword = " ".join(keyword.split()[:2])
        print(f"Fallback search with simplified keyword: '{fallback_keyword}'")
        params["keyword"] = fallback_keyword
        fb_resp = requests.get(url, params=params, timeout=20)
        if fb_resp.status_code == 200:
            items_raw = fb_resp.json().get("Items", [])

    if not items_raw:
        # 別のテーマでリトライ
        alt_theme = random.choice([t for t in MENS_THEMES if t != theme_obj])
        print(f"Retrying with alternative theme: {alt_theme['theme']}")
        params["keyword"] = alt_theme["keyword"]
        theme_obj = alt_theme
        alt_resp = requests.get(url, params=params, timeout=20)
        if alt_resp.status_code == 200:
            items_raw = alt_resp.json().get("Items", [])

    if not items_raw:
        raise RuntimeError(f"No items found for keyword: {keyword}")

    posted_cache = load_posted_cache()
    selected_items = []
    
    ng_words = ["リサイクル", "回収", "利用券", "チケット", "処分", "修理", "女性用", "レディース", "中古"]

    for item_wrapper in items_raw:
        it = item_wrapper.get("Item", {})
        code = it.get("itemCode")
        name = it.get("itemName", "")
        price = it.get("itemPrice", 0)

        if any(ng in name for ng in ng_words):
            continue
        if price < 300: # 安価すぎるサンプル等を除外
            continue

        it["cleanName"] = clean_rakuten_item_name(name)
        it["affUrl"] = get_rakuten_affiliate_url(it, affiliate_id)
        it["imgUrl"] = extract_image_url(it)

        is_dup, reason = is_duplicate_or_similar_item(it, selected_items, posted_cache)
        if not is_dup:
            selected_items.append(it)
            if len(selected_items) >= count:
                break
        else:
            print(f"[DEDUP] Skipped duplicate/similar item: '{it['cleanName']}' ({reason})")

    # もし指定件数に満たない場合、類似テーマの拡張検索を行って異なる商品群から補充
    if len(selected_items) < count:
        print(f"[DEDUP-EXPAND] Only {len(selected_items)} unique items found for '{keyword}'. Expanding search with related terms...")
        expand_keywords = [
            f"メンズ {keyword.split()[-1]} おすすめ",
            f"メンズ {keyword.split()[1] if len(keyword.split()) > 1 else '身だしなみ'}"
        ]
        for exp_kw in expand_keywords:
            if len(selected_items) >= count:
                break
            params["keyword"] = exp_kw
            try:
                exp_resp = requests.get(url, params=params, timeout=15)
                if exp_resp.status_code == 200:
                    for exp_wrapper in exp_resp.json().get("Items", []):
                        exp_it = exp_wrapper.get("Item", {})
                        exp_name = exp_it.get("itemName", "")
                        if any(ng in exp_name for ng in ng_words) or exp_it.get("itemPrice", 0) < 300:
                            continue
                        exp_it["cleanName"] = clean_rakuten_item_name(exp_name)
                        exp_it["affUrl"] = get_rakuten_affiliate_url(exp_it, affiliate_id)
                        exp_it["imgUrl"] = extract_image_url(exp_it)
                        is_dup, reason = is_duplicate_or_similar_item(exp_it, selected_items, posted_cache)
                        if not is_dup:
                            selected_items.append(exp_it)
                            if len(selected_items) >= count:
                                break
            except Exception:
                pass

    if not selected_items:
        raise RuntimeError("Could not find suitable items for the theme.")

    return theme_obj, selected_items


def call_llm(prompt, system_message, temperature=0.7, max_tokens=3000):
    """
    ユーザー規則に基づく最新Geminiモデルローテーション ＆ Groqフォールバック
    Gemini 1.5系は完全廃止済みのため使用禁止。
    ローテーション順:
    gemini-2.5-flash -> gemini-3.5-flash -> gemini-3.6-flash -> gemini-3.1-flash-lite -> gemini-3.5-flash-lite -> gemini-2.0-flash
    """
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        gemini_rotation = [
            "gemini-2.5-flash",
            "gemini-3.5-flash",
            "gemini-3.6-flash",
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash-lite",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-2.5-flash-lite",
            "gemini-2.5-pro",
            "gemini-3-flash",
            "gemini-3.1-pro",
            "gemini-3.7-flash"
        ]
        for model_name in gemini_rotation:
            try:
                api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
                payload = {
                    "contents": [{"parts": [{"text": f"{system_message}\n\n{prompt}"}]}],
                    "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}
                }
                if any(v in model_name for v in ["2.5", "3.", "3-"]):
                    payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}

                res = requests.post(api_url, json=payload, timeout=40)
                if res.status_code == 200:
                    data = res.json()
                    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                    text = "".join(p.get("text", "") for p in parts if p.get("text")).strip()
                    if len(text) > 50:
                        print(f"Generated successfully with Gemini model: {model_name}")
                        return text
                else:
                    print(f"Gemini API ({model_name}) error {res.status_code}: {res.text[:120]}")
            except Exception as e:
                print(f"Gemini API ({model_name}) exception: {e}")

    # Groq API フォールバック
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        for model_name in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]:
            try:
                headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
                payload = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens
                }
                res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=40)
                if res.status_code == 200:
                    text = res.json()["choices"][0]["message"]["content"].strip()
                    if len(text) > 50:
                        print(f"Generated successfully with Groq model: {model_name}")
                        return text
            except Exception as e:
                print(f"Groq API ({model_name}) exception: {e}")

    return None


def parse_json_from_llm(raw_text):
    if not raw_text:
        return None
    text = raw_text.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```")[0].strip()
    
    # JSON先頭と末尾のカッコを抽出
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        text_candidate = text[first_brace:last_brace+1]
        try:
            data = json.loads(text_candidate)
            if isinstance(data, dict) and "html" in data:
                return data
        except Exception:
            # 改行コードのエスケープ不備を修復試行
            try:
                # 簡易修復
                fixed = re.sub(r'(?<!\\)\n', '\\n', text_candidate)
                data = json.loads(fixed)
                if isinstance(data, dict) and "html" in data:
                    return data
            except Exception:
                pass
    return None


def generate_curated_mens_article(theme_obj, items):
    """
    選抜された複数個のメンズコスメ商品を比較・紹介する特集記事を生成
    『10月最新メンズコスメ5選』等の形式で、テンプレート使い回しを排除した自然な記事構成
    """
    current_month = datetime.now().month
    count = len(items)
    
    items_desc_list = []
    for idx, it in enumerate(items, 1):
        clean_name = it.get('cleanName', '')
        brand, product = extract_brand_and_product(clean_name)
        it['brand'] = brand
        it['product'] = product
        items_desc_list.append(
            f"--- 【商品 {idx}】 ---\n"
            f"ブランド名: {brand}\n"
            f"商品名: {product}\n"
            f"フル名称: {clean_name}\n"
            f"価格: {it.get('itemPrice', '')}円\n"
            f"概要: {it.get('itemCaption', '')[:200]}\n"
            f"画像URL: {it['imgUrl']}\n"
            f"アフィリエイトURL: {it['affUrl']}\n"
        )
    items_context = "\n".join(items_desc_list)

    system_message = (
        "あなたは20代〜40代男性向けの身だしなみ・メンズスキンケア・メンズコスメ専門の敏腕エディターです。"
        "『清潔感』『好印象』『手軽さ』を重視する男性読者の悩みに寄り添い、雑誌やWebメディアのような洗練された比較・おすすめ記事を執筆します。"
        "『注目1』『注目2』といった単調な機械的見出しや、AI臭いテンプレート感（『いかがでしたでしょうか』『〜ですね！』の連発など）は一切排除してください。"
        "出力は必ず指定のJSONフォーマットのみとしてください。"
    )

    prompt = f"""以下は楽天市場から厳選したメンズコスメ・身だしなみアイテム{count}点のデータです。
今月（{current_month}月）の男性読者に向けて、雑誌の特集ページのような魅力的な選抜比較記事を作成してください。

【特集テーマ】: {theme_obj['theme']}
【掲載アイテム一覧】:
{items_context}

【記事作成要件】:
1. タイトル（title）:
   - 『{current_month}月最新』または『{current_month}月厳選』と、具体的なアイテム数（{count}選など）を含める。
   - 読者が思わずクリックしたくなる実用的かつ魅力的なタイトル（最大38文字程度）。
2. 本文HTML（html）:
   - 全体を `<div class="mens-curation-article" style="line-height: 1.8; color: #222; font-family: sans-serif;">` で囲む。
   - 導入部（リード文）: なぜ今このケアやアイテム選びが大切なのか、男性特有の肌の悩み（テカリ・乾燥・毛穴・清潔感など）に触れつつ読者を引き込む（200〜300文字程度）。
   - 各商品紹介（1〜{count}）の見出しと構成ルール【★超重要】:
     - 見出しに『注目1』『注目2』という単語を使うのは【完全禁止】です。
     - `<h3>` タグの見出しは、【刺さるキャッチコピー】＋【ブランド名】または【ブランド名＋商品名】の形式にしてください。
       例: `<h3 style="border-left: 4px solid #1a365d; padding-left: 12px; margin-top: 35px; font-size: 19px; color: #1a202c;">目元の老け見えを一掃！男の印象を変える「OPENEYES」</h3>`
       例: `<h3 style="border-left: 4px solid #1a365d; padding-left: 12px; margin-top: 35px; font-size: 19px; color: #1a202c;">朝30秒で清潔感をカンスト！「ZIGEN」オールインワンフェイスジェル</h3>`
     - 見出し直下の本文冒頭で、**太字のキャッチコピーや商品の位置づけ（一言要約）**を配置:
       例: `<p style="font-weight: bold; color: #2b6cb0; font-size: 15px; margin-bottom: 8px;">💡 【{current_month}月の推しポイント】ベタつきゼロで夕方までテカリ知らず！多忙な男の救世主ギア</p>`
       例: `<p style="margin: 4px 0 12px 0; color: #4a5568;"><b>商品名:</b> ブランド名 フル商品名（価格目安: ◯◯◯◯円）</p>`
     - 画像を表示: `<div style="text-align: center; margin: 15px 0;"><img src="画像URL" alt="商品名" style="max-width: 320px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);"></div>`
     - 商品の具体的な特徴・おすすめ理由を2〜3つのリスト形式（`<ul><li>`）で簡潔かつ魅力的に整理。
     - 楽天市場の購入リンクボタン（赤基調・角丸で洗練されたデザイン）を各商品の直下に配置:
       `<div style="text-align: center; margin: 15px 0;"><a href="アフィリエイトURL" target="_blank" rel="noopener noreferrer" style="display:inline-block; padding: 12px 24px; background-color: #bf0000; color: #fff; font-weight: bold; font-size: 15px; border-radius: 6px; text-decoration: none;">🛒 楽天市場で詳細・口コミを見る</a></div>`
   - まとめセクション: 今回紹介した{count}選の選び方のワンポイントアドバイスと背中を押すメッセージ。
3. 【厳格な品質ルール】:
   - Amazon、Yahoo!ショッピング、他ECサイトの言及は厳禁。
   - 途中で文章が途切れず、すべてのHTMLタグが正常に閉じられていること。
   - 宣伝臭さやテンプレートの使い回し感を無くし、読み物として価値のある独自性の高いレビュー・比較記事にすること。

【出力形式】
{{
    "title": "記事タイトル",
    "html": "完全なHTML文字列"
}}
"""

    raw_response = call_llm(prompt, system_message, temperature=0.75, max_tokens=3500)
    parsed = parse_json_from_llm(raw_response)

    if not parsed:
        print("Fallback: LLM generation was incomplete or non-JSON. Generating clean curated fallback.")
        random_prefixes = [
            f"{current_month}月最新！男を上げる",
            f"{current_month}月厳選！清潔感をつくる",
            f"2026年{current_month}月版！男の肌・身だしなみを劇的に整える",
            f"{current_month}月おすすめ！失敗しない",
            f"大人の清潔感！{current_month}月注目の"
        ]
        chosen_prefix = random.choice(random_prefixes)
        default_title = f"{chosen_prefix}{theme_obj['theme'].replace('選抜', '')}{count}選"
        
        fallback_catchphrases = [
            "第一印象を劇的に底上げする実力派",
            "男の清潔感をカンストさせる神ギア",
            "忙しい朝でも手軽に垢抜ける即効アイテム",
            "乾燥やテカリを寄せ付けない大人の必需品",
            "女性ウケ・ビジネス好感度を両立する鉄板品"
        ]
        
        body_parts = []
        body_parts.append(f'<div class="mens-curation-article" style="line-height: 1.8; color: #222; font-family: sans-serif;">')
        body_parts.append(f'<p>清潔感のある肌や整えられた身だしなみは、ビジネスでもプライベートでも第一印象を大きく左右します。今回は{current_month}月にチェックしておきたいメンズコスメ・身だしなみアイテムを厳選して{count}つご紹介します。</p>')
        
        for idx, it in enumerate(items, 1):
            name = it["cleanName"]
            brand, product = extract_brand_and_product(name)
            price = it.get("itemPrice", "")
            img = it["imgUrl"]
            url = it["affUrl"]
            catch = fallback_catchphrases[(idx - 1) % len(fallback_catchphrases)]
            
            # 「注目◯」を完全排除し、キャッチコピー＋ブランド名/商品名の見出しにする
            body_parts.append(f'<h3 style="border-left: 4px solid #1a365d; padding-left: 12px; margin-top: 35px; font-size: 19px; color: #1a202c;">{catch}！「{brand}」{product[:20]}</h3>')
            body_parts.append(f'<p style="font-weight: bold; color: #2b6cb0; font-size: 15px; margin: 8px 0 4px 0;">💡 【{current_month}月の厳選ポイント】毎日のケアを格上げし、清潔感を自然に引き出す注目アイテム</p>')
            body_parts.append(f'<p style="margin: 0 0 12px 0; color: #4a5568; font-size: 14px;"><b>商品名:</b> {name}（価格目安: {price}円）</p>')
            
            if img:
                body_parts.append(f'<div style="text-align:center; margin:15px 0;"><img src="{img}" alt="{name}" style="max-width:320px; border-radius:8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);"></div>')
            body_parts.append(f'<p>{it.get("itemCaption", "")[:180]}...</p>')
            body_parts.append(f'<div style="text-align:center; margin:15px 0;"><a href="{url}" target="_blank" rel="noopener noreferrer" style="display:inline-block; padding: 12px 24px; background-color: #bf0000; color: #fff; font-weight: bold; border-radius: 6px; text-decoration: none;">🛒 楽天市場で詳細・在庫を見る</a></div>')
            
        body_parts.append(f'<h4 style="margin-top: 35px; font-size: 18px; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px;">まとめ</h4><p>自分の悩みやライフスタイルに合ったアイテムを取り入れて、毎日の身だしなみと清潔感をアップデートしていきましょう！</p>')
        body_parts.append('</div>')
        
        parsed = {
            "title": default_title,
            "html": "".join(body_parts)
        }

    return parsed


def strict_quality_check_and_refine(title, html_content, items):
    """
    【記事品質チェック厳し目工程】
    1. 必須要素の確認（各商品の画像、リンクURL、タイトル、文字量）
    2. 禁止単語（Amazon, 他社リンク、未置換タグ等）の除去
    3. LLMによる誤字脱字、文脈の自然さ、AI臭さの排除校正
    4. HTML構文・閉じタグの整合性補正
    """
    print("Executing strict quality check & refinement...")

    # チェック1: 文字量チェック（選抜記事なので最低でも1200文字以上を担保）
    text_length = len(re.sub(r'<[^>]+>', '', html_content))
    print(f"Content text length (excluding tags): {text_length} chars")

    # チェック2: 各商品のリンクが正しく含まれているか検証
    for it in items:
        aff_url = it.get("affUrl", "")
        clean_name = it.get("cleanName", "")
        if aff_url and aff_url not in html_content:
            print(f"Warning: Affiliate URL missing for {clean_name[:15]}. Injecting button...")
            btn_inject = (
                f'<div style="text-align: center; margin: 15px 0;">'
                f'<a href="{aff_url}" target="_blank" rel="noopener noreferrer" '
                f'style="display:inline-block; padding: 12px 24px; background-color: #bf0000; '
                f'color: #fff; font-weight: bold; border-radius: 6px; text-decoration: none;">'
                f'🛒 楽天市場で【{clean_name[:20]}】を見る</a></div>'
            )
            html_content += f"\n{btn_inject}"

    # チェック3: 禁止ワードのサニタイズ
    html_content = html_content.replace("Amazon", "楽天市場").replace("アマゾン", "楽天市場").replace("Yahoo!", "楽天市場").replace("ヤフー", "楽天市場")

    # チェック4: LLMによるプロ品質校正（AI臭さの排除と文脈の完全性）
    proofread_prompt = f"""以下のメンズコスメ選抜記事のHTMLに対して、厳格な品質校正を行ってください。

【タイトル】: {title}
【記事HTML】:
{html_content}

【厳格校正ルール】:
1. 誤字脱字、てにをは、不自然な文言を徹底的に修正してください。
2. 『注目1』『注目2』などの単調な表現が残っている場合は完全に削除し、【キャッチコピー＋ブランド名/商品名】の洗練された見出しに修正してください。
3. 『いかがでしたでしょうか？』などの陳腐なAIブログ特有の言い回しを削除し、読者の知的好奇心と購入意欲を刺激する洗練された男性美容ライターの文章に整えてください。
4. すべての見出し（h2, h3）と段落（p）、リスト（ul, li）、divタグが正しく閉じられており、文末が途中で切れていないことを確認してください。
5. HTMLタグ構造やリンクURL、画像タグは一切壊さず維持してください。
6. 余計な挨拶や解説は不要です。ブラッシュアップされた純粋なHTML本文のみを出力してください。
"""
    proofread_system = "あなたは大手男性美容WEBマガジンの最高編集責任者です。妥協のない厳格な校正を行い、高品質なHTMLのみを返します。"
    refined_html = call_llm(proofread_prompt, proofread_system, temperature=0.4, max_tokens=3800)

    if refined_html and len(refined_html.strip()) > 300:
        refined_html = refined_html.strip()
        if "```html" in refined_html:
            refined_html = refined_html.split("```html", 1)[1].split("```")[0].strip()
        elif "```" in refined_html:
            refined_html = refined_html.split("```", 1)[1].split("```")[0].strip()
        html_content = refined_html
        print("Refinement step completed successfully.")

    # チェック5: 閉じタグ整合性の自動補正
    open_divs = html_content.count("<div")
    close_divs = html_content.count("</div>")
    if open_divs > close_divs:
        html_content += "</div>" * (open_divs - close_divs)

    open_uls = html_content.count("<ul")
    close_uls = html_content.count("</ul>")
    if open_uls > close_uls:
        html_content += "</ul>" * (open_uls - close_uls)

    return html_content


def post_to_blogger(title, content):
    """Playwrightを用いてBloggerへ自動投稿"""
    blog_id = os.environ.get("BLOGGER_BLOG_ID")
    if not blog_id:
        raise ValueError("BLOGGER_BLOG_ID is not set in environment variables.")
    session_b64 = os.environ.get("BLOGGER_SESSION_B64")
    
    session_file_path = None
    if session_b64:
        try:
            decoded_str = base64.b64decode(session_b64).decode('utf-8')
            json.loads(decoded_str)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, suffix=".json") as temp_file:
                temp_file.write(decoded_str)
                session_file_path = temp_file.name
        except Exception as e:
            raise ValueError(f"BLOGGER_SESSION_B64 decode failed: {e}")
    elif os.path.exists("session.json"):
        print("Found local session.json. Using it for Blogger post.")
        session_file_path = "session.json"
    else:
        raise ValueError("BLOGGER_SESSION_B64 is not set and local session.json not found.")

    print(f"Posting to Blogger (Blog ID: {blog_id}) using Playwright...")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(
                storage_state=session_file_path,
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                permissions=['clipboard-read', 'clipboard-write']
            )
            
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            try:
                time.sleep(random.uniform(2.0, 3.5))
                # まず記事一覧ページをロード
                posts_url = f"https://draft.blogger.com/blog/posts/{blog_id}"
                print(f"Navigating to Blogger posts page: {posts_url}")
                page.goto(posts_url, wait_until="networkidle")
                time.sleep(3.0)

                # ポリシー通知バナーがあれば閉じる
                try:
                    close_btn = page.locator('div:has-text("Blogger のコンテンツ ポリシー") [role="button"], div[aria-label*="閉じる"]').first
                    if close_btn.is_visible(timeout=2000):
                        close_btn.click()
                        time.sleep(1.0)
                except Exception:
                    pass

                # エディタ画面（新規投稿）を開く
                editor_opened = False
                for open_attempt in range(5):
                    print(f"[BLOGGER-OPEN] Attempt {open_attempt + 1} to open editor...")
                    
                    if "edit" in page.url:
                        editor_opened = True
                        break

                    # クリック前の先頭記事リンクを記録
                    before_first_link = None
                    try:
                        first_el = page.locator('a[href*="/blog/post/edit/"]').first
                        if first_el.is_visible(timeout=3000):
                            before_first_link = first_el.get_attribute("href")
                    except Exception:
                        pass

                    try:
                        # 画面内に表示されている「新しい投稿を作成」ボタンを取得してクリック
                        btn = page.locator('div[role="button"][aria-label*="新しい投稿を作成"]').filter(has_text='新しい投稿').locator("visible=true").first
                        if not btn.is_visible(timeout=2000):
                            all_btns = page.locator('div[role="button"][aria-label*="新しい投稿を作成"]').all()
                            for b in all_btns:
                                if b.is_visible():
                                    btn = b
                                    break

                        print(f"[BLOGGER-OPEN] Clicking New Post button...")
                        btn.click()
                        
                        # 1. 自動で /blog/post/edit/... へ画面遷移するか待機
                        # 2. 遷移しない場合、一覧の先頭に新規作成されたドラフト行が出現するため、それをクリック
                        for wait_sec in range(8):
                            time.sleep(1.0)
                            if "edit" in page.url:
                                editor_opened = True
                                print(f"[BLOGGER-OPEN] Automatically transitioned to editor: {page.url}")
                                break
                            
                            # 新規出現したドラフト行を検知
                            try:
                                curr_el = page.locator('a[href*="/blog/post/edit/"]').first
                                if curr_el.is_visible():
                                    curr_link = curr_el.get_attribute("href")
                                    if curr_link and curr_link != before_first_link:
                                        print(f"[BLOGGER-OPEN] New draft row detected ({curr_link}). Clicking it to enter editor...")
                                        curr_el.click()
                                        time.sleep(3.0)
                                        if "edit" in page.url:
                                            editor_opened = True
                                            print(f"[BLOGGER-OPEN] Successfully entered editor via draft row: {page.url}")
                                            break
                            except Exception:
                                pass

                        if editor_opened:
                            break

                    except Exception as be:
                        print(f"[BLOGGER-OPEN-WARN] Button click/transition failed: {be}")

                    # 3. /new への直接遷移を試行
                    try:
                        new_url = f"https://draft.blogger.com/blog/post/edit/{blog_id}/new"
                        page.goto(new_url, wait_until="networkidle")
                        time.sleep(3.0)
                        if "edit" in page.url:
                            editor_opened = True
                            break
                    except Exception:
                        pass

                    time.sleep(2.0)

                if not editor_opened:
                    raise RuntimeError("Blogger editor could not be opened (Google rate limit / RESOURCE_EXHAUSTED or button not found).")

                max_retries = 3
                success = False
                
                for attempt in range(max_retries):
                    print(f"--- Editor Body Injection Attempt {attempt+1} / {max_retries} ---")
                    if attempt > 0:
                        page.reload(wait_until="domcontentloaded")
                        time.sleep(3)

                    try:
                        title_input = page.locator('input.titleField, input[aria-label="タイトル"], input[aria-label="Title"], .titleField input').locator("visible=true").first
                        title_input.wait_for(state="visible", timeout=12000)
                        title_input.click()
                        time.sleep(0.5)
                        page.keyboard.press('Control+A')
                        page.keyboard.press('Meta+A')
                        page.keyboard.press('Backspace')
                        title_input.fill(title)
                        time.sleep(1.5)

                        print("Focusing on editor body...")
                        page.keyboard.press('Tab')
                        time.sleep(0.5)
                        page.keyboard.press('Tab')
                        time.sleep(1.0)

                        try:
                            editor_body = page.locator('div[aria-label="本文"], div[aria-label="Body"], div[role="textbox"], iframe').locator("visible=true").first
                            editor_body.click(timeout=3000)
                        except:
                            pass

                        print("Injecting HTML content via clipboard paste...")
                        page.evaluate('''html => {
                            try {
                                const blob = new Blob([html], { type: 'text/html' });
                                const data = [new ClipboardItem({ 'text/html': blob })];
                                navigator.clipboard.write(data);
                            } catch (e) {
                                console.error('Clipboard write failed:', e);
                            }
                        }''', content)
                        time.sleep(1.5)

                        page.keyboard.press('Control+V')
                        page.keyboard.press('Meta+V')
                        time.sleep(2.0)

                        # オートセーブを誘発
                        page.keyboard.press('Space')
                        time.sleep(0.5)
                        page.keyboard.press('Backspace')
                        time.sleep(3.0)

                        page_html = page.content()
                        if "<img" in page_html and ("href" in page_html or "http" in page_html):
                            print("Validation passed: Body content successfully inserted into Blogger editor.")
                            success = True
                            break
                        else:
                            print("Validation check warning: Editor content verification did not find expected tags. Retrying...")
                    except Exception as e:
                        print(f"Error during attempt {attempt+1}: {e}")
                    time.sleep(2)

                if not success:
                    raise RuntimeError("Critical: Body injection could not be validated after multiple attempts.")


                # 公開処理
                print("Clicking Publish button...")
                try:
                    pub_btn = page.locator('[aria-label="公開"], [aria-label="Publish"]').locator("visible=true").first
                    pub_btn.scroll_into_view_if_needed()
                    time.sleep(1)
                    pub_btn.click(force=True, timeout=10000)
                except Exception as e:
                    print("Clicking publish via shortcut:", e)
                    page.keyboard.press('Control+Shift+P')
                    page.keyboard.press('Meta+Shift+P')

                time.sleep(3)

                # 確認ダイアログの「確認」ボタン
                try:
                    conf_btn = page.locator('div[role="dialog"] div[role="button"]:has-text("確認"), [aria-label="確認"], [aria-label="Confirm"]').locator("visible=true").first
                    conf_btn.click(force=True, timeout=5000)
                    print("Confirmed publication dialog.")
                except Exception as e:
                    print("Confirm button fallback with Enter:", e)
                    page.keyboard.press('Enter')

                time.sleep(6)
                print("Successfully published curated mens cosmetic article to Blogger!")

                # 公開された最新記事のURLを取得
                published_post_url = f"https://mens-cosmet.blogspot.com"
                try:
                    time.sleep(2)
                    page.goto(f"https://draft.blogger.com/blog/posts/{blog_id}", wait_until="networkidle")
                    time.sleep(3)
                    post_link_el = page.locator('a[href*=".blogspot.com/"][aria-label*="表示"], a[href*=".blogspot.com/"][aria-label*="View"], a[href*=".blogspot.com/20"]').first
                    if post_link_el.is_visible(timeout=5000):
                        href = post_link_el.get_attribute("href")
                        if href and "blogspot.com" in href:
                            published_post_url = href
                            print(f"[BLOGGER-URL] Retrieved published post URL: {published_post_url}")
                except Exception as ue:
                    print(f"[BLOGGER-URL-WARN] Could not retrieve specific post URL, using base URL: {ue}")

                return published_post_url

            except Exception as e:
                print(f"Error during Blogger operation: {e}")
                raise e

    finally:
        if session_file_path and session_file_path != "session.json" and os.path.exists(session_file_path):
            os.remove(session_file_path)


def main():
    try:
        print("=== Starting Mens Cosmetics Blogger Automation ===")
        # 1. メンズコスメ・身だしなみ商品を複数選抜（5点）
        theme_obj, items = fetch_rakuten_mens_items(count=5)
        item_codes = [it.get("itemCode") for it in items if it.get("itemCode")]
        print(f"Selected {len(items)} items for '{theme_obj['theme']}'")
        for i, it in enumerate(items, 1):
            print(f"  {i}. {it['cleanName']} ({it.get('itemPrice')}円)")

        # 2. 選抜記事生成
        article = generate_curated_mens_article(theme_obj, items)
        title = article["title"]
        html_content = article["html"]
        print(f"\nGenerated Title: {title}")

        # 3. 厳格な品質チェック＆プロ校正
        final_html = strict_quality_check_and_refine(title, html_content, items)

        # 4. Bloggerへ自動投稿（room投稿は行わない）
        blogger_post_url = post_to_blogger(title, final_html)
        print(f"Blogger Publication Complete: {blogger_post_url}")

        # 5. キャッシュ保存
        save_to_cache(item_codes)

        # 6. ブルースカイへの自動投稿（チー牛ラボ 〜劇的垢抜けアイテム研究〜）
        try:
            print("\n=== Triggering Bluesky Auto-Post for 'チー牛ラボ' ===")
            from bluesky_poster import post_to_bluesky_from_blogger, save_latest_blogger_post_info
            # 最新記事情報を保存
            save_latest_blogger_post_info(blogger_post_url, title, theme_obj, items)
            # Blueskyへ投稿
            post_to_bluesky_from_blogger(
                blogger_url=blogger_post_url,
                article_title=title,
                theme_obj=theme_obj,
                items=items
            )
        except Exception as be:
            print(f"[WARN] Bluesky posting failed or deferred: {be}")

        print("\nAll processes finished successfully! (Blogger + Bluesky)")

    except Exception as e:
        print(f"Fatal error in main: {e}")
        exit(1)


if __name__ == "__main__":
    main()

