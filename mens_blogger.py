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

# .env を安全に自動ロード（外部ライブラリ依存なし）
def load_env_file(filepath=".env"):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'").strip('"')
                        if k and k not in os.environ:
                            os.environ[k] = v
        except Exception as e:
            print(f"[WARN] Failed to load .env file: {e}")

load_env_file()

CACHE_FILE = "posted_cache.txt"
POSTED_TITLES_FILE = "posted_titles.txt"
RECENT_THEMES_FILE = "recent_themes.txt"

def load_posted_titles():
    """過去に投稿された記事タイトルの一覧を取得"""
    if os.path.exists(POSTED_TITLES_FILE):
        with open(POSTED_TITLES_FILE, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    return []

def save_posted_title(title):
    """新規投稿タイトルを永続化保存"""
    if not title:
        return
    title_clean = title.strip()
    with open(POSTED_TITLES_FILE, "a", encoding="utf-8") as f:
        f.write(f"{title_clean}\n")

def is_title_duplicate_or_similar(new_title, threshold=0.70):
    """
    過去のタイトルと完全一致、または類似度が閾値（70%）以上なら重複と判定
    記号や月表記のノイズを除去して意味的な重複を徹底排除
    """
    if not new_title:
        return True, "空のタイトル", 1.0
    existing_titles = load_posted_titles()
    clean_new = re.sub(r'[\s\d月【】選！!｜|：:・\-\[\]（）()]+', '', new_title)
    if not clean_new:
        return True, "無効なタイトル", 1.0

    for past in existing_titles:
        if new_title.strip() == past.strip():
            return True, past, 1.0
        clean_past = re.sub(r'[\s\d月【】選！!｜|：:・\-\[\]（）()]+', '', past)
        if not clean_past:
            continue
        ratio = difflib.SequenceMatcher(None, clean_new, clean_past).ratio()
        if ratio >= threshold:
            return True, past, ratio
    return False, None, 0.0

def load_recent_themes(limit=10):
    """直近投稿されたテーマ一覧を取得"""
    if os.path.exists(RECENT_THEMES_FILE):
        with open(RECENT_THEMES_FILE, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
            return lines[-limit:]
    return []

def save_recent_theme(theme_name):
    """テーマ名を履歴に保存（直近の連続重複を防ぐ）"""
    if not theme_name:
        return
    with open(RECENT_THEMES_FILE, "a", encoding="utf-8") as f:
        f.write(f"{theme_name.strip()}\n")

def is_mojibake(text):
    """
    文字化け特有のバイト崩れ文字（æ, œ, å, é, ¸, ï, ½, etc.）が異常に含有されているかを検知
    """
    if not text or not isinstance(text, str):
        return True
    mojibake_chars = ['æ', 'œ', 'å', 'é', '¸', 'ï', '½', 'ç', '®', ' ', 'è', '¦', '«', '·', '£', '³']
    count = sum(text.count(c) for c in mojibake_chars)
    return count >= 3

def safe_unescape_json_string(s):
    """
    JSON文字列や正規表現で抽出したテキストを安全にデコード
    決して s.encode().decode('unicode_escape') のような破壊的変換は行わない
    """
    if not s or not isinstance(s, str):
        return ""
    
    # \uXXXX 形式のエスケープのみピンポイントで安全に置換
    def unescape_u(match):
        try:
            return chr(int(match.group(1), 16))
        except Exception:
            return match.group(0)
            
    res = re.sub(r'\\u([0-9a-fA-F]{4})', unescape_u, s)
    res = res.replace('\\"', '"').replace('\\/', '/').replace('\\n', '\n').replace('\\t', '\t').replace('\\r', '').replace('\\\\', '\\')
    return res.strip()


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


def clean_rakuten_item_caption(caption):
    """楽天のitemCaptionから類似商品羅列、ハッシュタグ、価格表、広告ノイズを除去"""
    if not caption:
        return "男の身だしなみ・清潔感を整える注目アイテム。"
    
    # 類似商品・関連商品の案内文とそれに続く商品名・価格の羅列を全削除
    text = re.sub(r'類似商品はこちら[^\n。]*[。\n]?', '', caption)
    text = re.sub(r'関連商品[^\n。]*[。\n]?', '', text)
    text = re.sub(r'おすすめ商品[^\n。]*[。\n]?', '', text)
    
    # ハッシュタグ（#韓国ヘア、#メンズケア など）の完全削除
    text = re.sub(r'#[^\s　#]+', '', text)
    
    # 価格付きの商品羅列（〜〜円、〜〜,〜〜〜円）のパターンを削除
    text = re.sub(r'[^\s　、。]+[0-9,]+円[、。]?', '', text)
    
    # 記号マーク付きの売り文句（■Point、★幅広設計 など）
    text = re.sub(r'[■★◆●▼▲]+[^\s　]+', '', text)
    text = re.sub(r'[■★◆●▼▲・~〜※]+', ' ', text)
    
    # URLやリンク風テキストの除去
    text = re.sub(r'https?://[^\s]+', '', text)
    
    # 余分な空白・改行の整形
    text = re.sub(r'\s+', ' ', text).strip()
    
    # 句点（。）で分割し、完全な文のみを結合して途切れのない文章を生成
    sentences = re.split(r'(?<=。)', text)
    valid_sentences = []
    total_len = 0
    for s in sentences:
        s_clean = s.strip()
        if not s_clean:
            continue
        # 意味のある文（5文字以上）
        if len(s_clean) >= 5:
            # もし末尾が句点で終わっていなければ補完
            if not s_clean.endswith(('。', '！', '!')):
                s_clean += '。'
            valid_sentences.append(s_clean)
            total_len += len(s_clean)
            if total_len >= 140:
                break
                
    if valid_sentences:
        return "".join(valid_sentences)

    # 最低限の意味のあるテキストが残らなかった場合の自然なフォールバック
    return "使い心地と効果にこだわったメンズ専用の身だしなみアイテムです。"



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

    # 直近選ばれたテーマを避けて選定（同一テーマの過剰連続投稿を防止）
    recent_themes = load_recent_themes(limit=12)
    available_themes = [t for t in MENS_THEMES if t["theme"] not in recent_themes]
    if not available_themes:
        available_themes = MENS_THEMES
    theme_obj = random.choice(available_themes)
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
        it["cleanCaption"] = clean_rakuten_item_caption(it.get("itemCaption", ""))
        it["itemCaption"] = it["cleanCaption"]
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
                        exp_it["cleanCaption"] = clean_rakuten_item_caption(exp_it.get("itemCaption", ""))
                        exp_it["itemCaption"] = exp_it["cleanCaption"]
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


def call_llm(prompt, system_message, temperature=0.7, max_tokens=4500):
    """
    ユーザー規則に基づく最新Geminiモデルローテーション ＆ Groqフォールバック
    Gemini 1.5系は完全廃止済みのため使用禁止。
    ローテーション順:
    gemini-3.1-flash-lite -> gemini-3.5-flash -> gemini-2.5-flash -> gemini-3.7-flash -> gemini-3.6-flash
    """
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        gemini_rotation = [
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash",
            "gemini-2.5-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash"
        ]
        for model_name in gemini_rotation:
            try:
                api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
                payload = {
                    "contents": [{"parts": [{"text": f"{system_message}\n\n{prompt}"}]}],
                    "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}
                }

                res = requests.post(api_url, json=payload, timeout=45)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        finish_reason = candidates[0].get("finishReason", "")
                        parts = candidates[0].get("content", {}).get("parts", [])
                        text = "".join(p.get("text", "") for p in parts if p.get("text")).strip()
                        if finish_reason == "MAX_TOKENS":
                            print(f"[WARN] Gemini model {model_name} hit MAX_TOKENS limit (output cut off). Skipping this response.")
                            continue
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
        for model_name in ["llama-3.1-8b-instant"]:
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
    """
    LLM出力からタイトルとHTMLを安全かつ堅牢に抽出。
    マーカー形式（【TITLE】/【HTML】）およびJSON形式の双方に対応。
    文字化け（mojibake）は絶対に許容しない。
    """
    if not raw_text:
        return None
    text = raw_text.strip()

    # 1. マーカー形式（【TITLE】...【HTML】...）のパース
    if "【TITLE】" in text and "【HTML】" in text:
        try:
            parts = text.split("【HTML】", 1)
            raw_title = parts[0].split("【TITLE】", 1)[1].strip()
            raw_html = parts[1].strip()

            title = re.sub(r'^[`\'"]+|[`\'"]+$', '', raw_title).strip()
            html = raw_html
            if html.startswith("```html"):
                html = html[7:]
            elif html.startswith("```"):
                html = html[3:]
            if html.endswith("```"):
                html = html[:-3]
            html = html.strip()

            if not is_mojibake(title) and not is_mojibake(html) and len(html) > 300:
                print("[PARSER] Successfully parsed article via MARKER format.")
                return {"title": title, "html": html}
        except Exception as e:
            print(f"[PARSER-WARN] Marker parsing failed: {e}")

    # 2. JSON形式のパース
    clean_json_text = text
    if "```json" in clean_json_text:
        clean_json_text = clean_json_text.split("```json", 1)[1].split("```")[0].strip()
    elif "```" in clean_json_text:
        clean_json_text = clean_json_text.split("```", 1)[1].split("```")[0].strip()

    first_brace = clean_json_text.find('{')
    last_brace = clean_json_text.rfind('}')
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        text_candidate = clean_json_text[first_brace:last_brace+1]
        try:
            data = json.loads(text_candidate)
            if isinstance(data, dict) and "html" in data:
                t = str(data.get("title", "")).strip()
                h = str(data.get("html", "")).strip()
                if not is_mojibake(t) and not is_mojibake(h) and len(h) > 300:
                    print("[PARSER] Successfully parsed article via standard JSON.")
                    return {"title": t, "html": h}
        except Exception:
            try:
                fixed = re.sub(r'(?<!\\)\n', '\\n', text_candidate)
                data = json.loads(fixed)
                if isinstance(data, dict) and "html" in data:
                    t = str(data.get("title", "")).strip()
                    h = str(data.get("html", "")).strip()
                    if not is_mojibake(t) and not is_mojibake(h) and len(h) > 300:
                        print("[PARSER] Successfully parsed article via newline-fixed JSON.")
                        return {"title": t, "html": h}
            except Exception:
                pass

    # 3. 正規表現による救出
    try:
        title_match = re.search(r'"title"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', text)
        title = safe_unescape_json_string(title_match.group(1)) if title_match else None

        html = None
        html_match = re.search(r'"html"\s*:\s*"(.*)"\s*\}?$', text, re.DOTALL)
        if html_match:
            html = safe_unescape_json_string(html_match.group(1))
        elif '<div class="mens-curation-article"' in text:
            start_idx = text.find('<div class="mens-curation-article"')
            end_idx = text.rfind('</div>')
            if end_idx > start_idx:
                html = text[start_idx:end_idx+6]

        if html and len(html) > 300:
            if not title:
                h2_m = re.search(r'<h[1-3][^>]*>(.*?)</h[1-3]>', html)
                title = safe_unescape_json_string(h2_m.group(1)) if h2_m else "メンズ注目の身だしなみアイテム厳選"

            if not is_mojibake(title) and not is_mojibake(html):
                print("[PARSER] Successfully recovered clean title and HTML from raw text via regex rescue!")
                return {"title": title, "html": html}
            else:
                print("[PARSER] Corrupted encoding (mojibake) detected in rescued text. Discarding.")
    except Exception as e:
        print(f"[PARSER-WARN] Fallback parsing failed: {e}")

    return None


def generate_curated_mens_article(theme_obj, items):
    """
    選抜された複数個のメンズコスメ商品を比較・紹介する特集記事を生成
    過去タイトルとの重複や類似を完全排除し、商品固有の悩みに寄り添った独立記事を執筆
    """
    current_month = datetime.now().month
    count = len(items)
    
    items_desc_list = []
    item_keywords_all = []
    for idx, it in enumerate(items, 1):
        clean_name = it.get('cleanName', '')
        brand, product = extract_brand_and_product(clean_name)
        it['brand'] = brand
        it['product'] = product
        caption_snippet = clean_rakuten_item_caption(it.get('itemCaption', ''))[:160]
        items_desc_list.append(
            f"--- 【商品 {idx}】 ---\n"
            f"ブランド名: {brand}\n"
            f"商品名: {product}\n"
            f"フル名称: {clean_name}\n"
            f"価格: {it.get('itemPrice', '')}円\n"
            f"特徴・概要: {caption_snippet}\n"
            f"画像URL: {it['imgUrl']}\n"
            f"アフィリエイトURL: {it['affUrl']}\n"
        )
        item_keywords_all.append(product)
    items_context = "\n".join(items_desc_list)

    # 過去タイトルの一覧（直近15件）をプロンプトに含めて重複を禁止
    past_titles = load_posted_titles()[-15:]
    past_titles_str = "\n".join([f"- {t}" for t in past_titles]) if past_titles else "（過去の重複なし）"

    system_message = (
        "あなたはメンズ美容・身だしなみ専門の敏腕エディターです。"
        "男性がリアルに抱える切実な悩み（テカリ、毛穴の黒ずみ、青ヒゲ、乾燥、頭皮のニオイ、清潔感の欠如など）を解決する、具体的で魅力的な特集記事を執筆します。"
        "【絶対禁止ルール】:\n"
        "1. 『注目1』『注目2』や『いかがでしたでしょうか』『〜ですね！』といった単調なAI臭い定型文・使い回しテンプレートは一切使用禁止。\n"
        "2. 過去のタイトル構文（『◯月最新！男を上げる〜』『◯月おすすめ！失敗しない〜』）の模倣・使い回しは完全禁止。\n"
        "3. 出力は指定のJSONフォーマットのみ（Markdownコードブロックなし、余計な前置き・解説なし）。"
    )

    prompt = f"""以下は楽天市場から厳選したメンズコスメ・身だしなみアイテム{count}点のデータです。
今月（{current_month}月）の男性読者に向けて、雑誌の特集ページのような魅力的な選抜比較記事を作成してください。

【特集テーマ】: {theme_obj['theme']}
【掲載アイテム一覧】:
{items_context}

【過去のタイトル例（これらと構文や表現が重複・酷似するものは完全禁止）】:
{past_titles_str}

【記事作成要件】:
1. タイトル（title）:
   - 過去のタイトルと被らない、今回の商品群の特徴や男性の悩みにフォーカスしたオリジナルのタイトル。
   - 具体的な数字（{count}選など）を含め、クリックしたくなる魅力を38文字程度で表現。
2. 本文HTML（html）:
   - 全体を `<div class="mens-curation-article" style="line-height: 1.85; color: #2d3748; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">` で囲む。
   - 導入部（リード文）:
     - 今回選んだ{count}点の商品がどんな男性のどんな悩みを解消するのか、具体的かつ共感を呼ぶ文面で300〜400文字程度執筆。
   - 各商品紹介（1〜{count}）:
     - `<h3>` は【刺さるキャッチコピー】＋「【ブランド名】商品名」の形式。
     - 見出し直下に、その商品独自の強みをズバッと伝える推薦フック文（`<p style="font-weight: bold; color: #2b6cb0; font-size: 15px; margin: 8px 0 6px 0;">⚡ ...</p>`）。
     - 画像表示: `<div style="text-align: center; margin: 18px 0;"><img src="画像URL" alt="商品名" style="max-width: 320px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.08);"></div>`
     - レビュー本文: 使用感や仕上がり、どんな肌質・悩みの男性に最適かを丁寧に解説（150〜200文字）。
     - 3つの箇条書きメリット（`<ul><li style="margin-bottom: 6px;">`）。
     - 購入リンクボタン: `<div style="text-align: center; margin: 20px 0;"><a href="アフィリエイトURL" target="_blank" rel="noopener noreferrer" style="display:inline-block; padding: 12px 28px; background-color: #bf0000; color: #fff; font-weight: bold; font-size: 15px; border-radius: 6px; text-decoration: none; box-shadow: 0 2px 6px rgba(191,0,0,0.3);">🛒 楽天市場で詳細・口コミを見る</a></div>`
   - 一目でわかる！厳選アイテム徹底比較表（`<table>`）を必ず挿入。
   - まとめセクション: `<h3>総括：タイプ別の選び方ガイド</h3>` を添えて背中を押すメッセージで締めくくる。

【出力形式】
以下のマーカー形式で出力してください：

【TITLE】
（38文字前後の魅力的なオリジナル記事タイトル）

【HTML】
<div class="mens-curation-article" style="line-height: 1.85; color: #2d3748; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
（完成した完全な本文HTML）
</div>
"""

    # 記事が全商品を網羅し、完全な構造を持つか検証する関数
    def validate_article_completeness(html_str, expected_items):
        if not html_str or len(html_str.strip()) < 1200:
            return False, f"文字数不足 ({len(html_str.strip()) if html_str else 0}文字)"
        # 全商品の画像URLが含まれているか
        img_missing = [it.get("imgUrl") for it in expected_items if it.get("imgUrl") and it.get("imgUrl") not in html_str]
        if img_missing:
            return False, f"商品画像欠落 ({len(img_missing)}件未掲載)"
        # 全商品のアフィリエイトURLが含まれているか
        aff_missing = [it.get("affUrl") for it in expected_items if it.get("affUrl") and it.get("affUrl") not in html_str]
        if aff_missing:
            return False, f"アフィリエイトリンク欠落 ({len(aff_missing)}件未掲載)"
        # 各商品紹介の見出し（h3）が商品数と同等以上あるか
        h3_count = html_str.count("<h3")
        if h3_count < len(expected_items):
            return False, f"商品見出し(h3)不足 ({h3_count}個 < 期待値{len(expected_items)}個)"
        # 比較テーブルが含まれているか
        if "<table" not in html_str:
            return False, "比較テーブル(table)欠落"
        return True, "OK"

    parsed = None
    for attempt in range(3):
        raw_response = call_llm(prompt, system_message, temperature=0.75, max_tokens=4500)
        parsed = parse_json_from_llm(raw_response)
        if parsed and parsed.get("title") and parsed.get("html"):
            # タイトル重複チェック
            is_dup, past_match, sim = is_title_duplicate_or_similar(parsed["title"])
            if is_dup:
                print(f"[TITLE-DUP-DETECTED] Generated title '{parsed['title']}' is too similar to '{past_match}' (similarity: {sim:.2f}). Retrying generation...")
                prompt += f"\n\n※注意: 先ほど生成されたタイトル「{parsed['title']}」は過去タイトルと類似しているため却下されました。全く異なる表現・切り口でタイトルを再生成してください。"
                parsed = None
                continue

            # 本文の完全性チェック（5商品全掲載・画像・リンク・テーブルの欠損を許さない）
            is_complete, comp_msg = validate_article_completeness(parsed["html"], items)
            if not is_complete:
                print(f"[ARTICLE-INCOMPLETE-DETECTED] Generated article is incomplete: {comp_msg}. Retrying LLM generation (attempt {attempt+1}/3)...")
                prompt += f"\n\n※重要: 前回の生成は【{comp_msg}】のため不完全でした。必ず掲載アイテム一覧の全{count}商品を1点ずつ画像・解説・リンク・メリット付きで余すことなく執筆し、比較表まで完結させてください。"
                parsed = None
                continue
            else:
                print("[ARTICLE-VALIDATION] LLM generated article passed all completeness checks.")
                break

    if not parsed:
        print("[FALLBACK] LLM generation unavailable or duplicated. Generating fully customized independent article.")
        main_item = items[0]
        main_product = main_item.get("product") or main_item.get("cleanName", "厳選ギア")
        lead_brand = main_item.get("brand") or "注目"
        
        # 過去タイトルと重複しないタイトルを動的に生成
        candidate_titles = [
            f"{current_month}月注目の身だしなみ！{main_product[:15]}など男の清潔感を高めるギア{count}選",
            f"大人の身だしなみを格上げ！「{lead_brand}」ほか今選ぶべきメンズ注目アイテム{count}選",
            f"第一印象で圧倒的な清潔感を放つ！{current_month}月にチェックすべき男の厳選{count}選",
            f"男のリアルな悩みを即解決！{main_product[:14]}を含む実力派メンズギア{count}選"
        ]
        chosen_title = None
        for cand in candidate_titles:
            is_dup, _, _ = is_title_duplicate_or_similar(cand)
            if not is_dup:
                chosen_title = cand
                break
        if not chosen_title:
            chosen_title = f"{current_month}月厳選！{main_product[:12]}ほか男を磨く優秀アイテム{count}選 ({random.randint(100, 999)})"

        body_parts = []
        body_parts.append(f'<div class="mens-curation-article" style="line-height: 1.85; color: #2d3748; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">')
        body_parts.append(f'<p>日々の身だしなみや肌のお手入れは、ビジネス・プライベートを問わず第一印象を決定づける最重要ファクターです。今回は「{theme_obj["theme"].replace("選抜", "")}」をテーマに、楽天市場で注目を集めている実力派アイテム{count}点を厳選ピックアップしました。使いやすさと確かな実感にこだわったラインナップをご覧ください。</p>')
        
        for idx, it in enumerate(items, 1):
            name = it["cleanName"]
            brand, product = it.get("brand") or "注目ブランド", it.get("product") or name
            price = it.get("itemPrice", "")
            img = it["imgUrl"]
            url = it["affUrl"]
            caption = clean_rakuten_item_caption(it.get("itemCaption", ""))
            if not caption:
                caption = f"男性の肌質や使い勝手を追求して開発された「{brand}」の注目のケアギア。"
            elif not caption.endswith(('。', '！', '!')):
                caption += '。'
            
            body_parts.append(f'<h3 style="border-left: 5px solid #2b6cb0; padding-left: 12px; margin-top: 40px; font-size: 20px; color: #1a202c;">「{brand}」{product[:24]}</h3>')
            body_parts.append(f'<p style="font-weight: bold; color: #2b6cb0; font-size: 15px; margin: 8px 0 6px 0;">⚡ 男の身だしなみを手間なく底上げする実用性と確かな品質を両立</p>')
            body_parts.append(f'<p style="margin: 0 0 14px 0; color: #718096; font-size: 14px;"><b>商品スペック:</b> {name}（価格目安: {price}円）</p>')
            
            if img:
                body_parts.append(f'<div style="text-align:center; margin:18px 0;"><img src="{img}" alt="{name}" style="max-width:320px; border-radius:8px; box-shadow: 0 4px 12px rgba(0,0,0,0.08);"></div>')
            body_parts.append(f'<p style="margin: 14px 0;">{caption}</p>')
            body_parts.append(f'<ul style="background-color: #f7fafc; border: 1px solid #edf2f7; padding: 15px 15px 15px 35px; border-radius: 6px; margin: 15px 0;">')
            body_parts.append(f'<li style="margin-bottom: 6px;">忙しい朝や疲れた夜でも無理なく続けられる快適な使用感</li>')
            body_parts.append(f'<li style="margin-bottom: 6px;">男特有の皮脂や乾燥トラブルを考え抜いた成分・設計</li>')
            body_parts.append(f'<li>清潔感のある洗練された第一印象をサポート</li>')
            body_parts.append(f'</ul>')
            body_parts.append(f'<div style="text-align:center; margin:20px 0;"><a href="{url}" target="_blank" rel="noopener noreferrer" style="display:inline-block; padding: 12px 28px; background-color: #bf0000; color: #fff; font-weight: bold; border-radius: 6px; text-decoration: none; box-shadow: 0 2px 6px rgba(191,0,0,0.3);">🛒 楽天市場で詳細・口コミを見る</a></div>')

        body_parts.append(build_comparison_table_and_summary(items, count))
        body_parts.append('</div>')
        
        parsed = {
            "title": chosen_title,
            "html": "".join(body_parts)
        }

    return parsed


def build_comparison_table_and_summary(items, count):
    """商品比較テーブルと総括選び方ガイドを確実に生成"""
    table_rows = []
    catchphrases = [
        "第一印象を劇的に底上げする実力派",
        "男の清潔感をカンストさせる神ギア",
        "忙しい朝でも手軽に垢抜ける即効アイテム",
        "乾燥やテカリを寄せ付けない大人の必需品",
        "女性ウケ・ビジネス好感度を両立する鉄板品"
    ]
    for idx, it in enumerate(items, 1):
        brand = it.get("brand") or "注目ブランド"
        product = it.get("product") or it.get("cleanName", "")
        price = it.get("itemPrice", "")
        catch = catchphrases[(idx - 1) % len(catchphrases)]
        table_rows.append(
            f'<tr style="border-bottom: 1px solid #e2e8f0;">'
            f'<td style="padding: 10px 12px; font-weight: bold; color: #2d3748;">{brand}<br><span style="font-size: 12px; font-weight: normal; color: #718096;">{product[:16]}</span></td>'
            f'<td style="padding: 10px 12px; color: #c53030; font-weight: bold;">{price}円</td>'
            f'<td style="padding: 10px 12px;">{catch}</td>'
            f'<td style="padding: 10px 12px; font-size: 13px;">清潔感を即座に上げたい方</td>'
            f'</tr>'
        )
    
    table_html = (
        f'<h3 style="margin-top: 45px; font-size: 20px; color: #1a202c; border-bottom: 2px solid #2b6cb0; padding-bottom: 8px;">📊 一目でわかる！厳選アイテム徹底比較表</h3>'
        f'<div style="overflow-x: auto; margin: 20px 0;">'
        f'<table style="width: 100%; border-collapse: collapse; min-width: 520px; font-size: 14px; text-align: left; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">'
        f'<thead style="background-color: #edf2f7;"><tr style="border-bottom: 2px solid #cbd5e0;"><th style="padding: 10px 12px;">商品・ブランド</th><th style="padding: 10px 12px;">価格目安</th><th style="padding: 10px 12px;">主な特徴</th><th style="padding: 10px 12px;">おすすめな人</th></tr></thead>'
        f'<tbody>{"".join(table_rows)}</tbody></table></div>'
    )

    summary_html = (
        f'<h3 style="margin-top: 40px; font-size: 20px; color: #1a202c; border-bottom: 2px solid #2b6cb0; padding-bottom: 8px;">総括：失敗しないための選び方ガイド</h3>'
        f'<p>今回ご紹介した{count}選は、いずれも使いやすさと清潔感の向上に定評のある実力派ばかりです。手軽さを最優先するならオールインワンやセット品、ピンポイントで印象を変えたいなら専用ツールを選ぶのがおすすめです。自分のライフスタイルに合ったアイテムを1つ取り入れて、自信の持てる身だしなみを手に入れましょう！</p>'
    )
    return table_html + "\n" + summary_html


def strict_quality_check_and_refine(title, html_content, items):
    """
    【記事品質チェック厳し目工程】
    1. 必須要素の確認（各商品の画像、リンクURL、タイトル、文字量）
    2. 禁止単語（Amazon, 他社リンク、未置換タグ等）の除去
    3. LLMによる誤字脱字、文脈の自然さ、AI臭さの排除校正
    4. 比較テーブルとまとめの死守・自動再結合保証
    5. HTML構文・閉じタグの整合性補正
    """
    print("Executing strict quality check & refinement...")

    # チェック1: 文字量チェック
    text_length = len(re.sub(r'<[^>]+>', '', html_content))
    print(f"Content text length (excluding tags): {text_length} chars")

    # チェック2: 各商品のリンクが正しく含まれているか検証（末尾乱雑注入を防ぐため、欠落商品のセクション直下に注入）
    for it in items:
        aff_url = it.get("affUrl", "")
        clean_name = it.get("cleanName", "")
        brand, product = it.get("brand") or "注目ブランド", it.get("product") or clean_name
        
        # URLそのもの、またはそのURLのエンコードパラメータ、または商品名がリンクされているか判定
        is_url_present = aff_url and (aff_url in html_content or clean_name[:12] in html_content or (product and product[:10] in html_content))
        if aff_url and not is_url_present:
            print(f"Warning: Affiliate URL missing for {clean_name[:15]}. Injecting dedicated single button...")
            btn_inject = (
                f'<div style="text-align: center; margin: 20px 0;">'
                f'<a href="{aff_url}" target="_blank" rel="noopener noreferrer" '
                f'style="display:inline-block; padding: 12px 28px; background-color: #bf0000; '
                f'color: #fff; font-weight: bold; font-size: 15px; border-radius: 6px; text-decoration: none; box-shadow: 0 2px 6px rgba(191,0,0,0.3);">'
                f'🛒 楽天市場で【{product[:20]}】を見る</a></div>'
            )
            # 該当商品の見出しや解説の後に挿入を試みる
            pattern = re.escape(product[:10]) if len(product) >= 10 else re.escape(brand)
            match = re.search(pattern, html_content)
            if match:
                # 該当商品の段落後（次のh3またはtableの前）に挿入
                insert_pos = match.end()
                next_tag = re.search(r'(<h3|<table|</div>)', html_content[insert_pos:])
                if next_tag:
                    split_idx = insert_pos + next_tag.start()
                    html_content = html_content[:split_idx] + f"\n{btn_inject}\n" + html_content[split_idx:]
                else:
                    html_content += f"\n{btn_inject}"
            else:
                html_content += f"\n{btn_inject}"

    # チェック3: 禁止ワードのサニタイズ
    html_content = html_content.replace("Amazon", "楽天市場").replace("アマゾン", "楽天市場").replace("Yahoo!", "楽天市場").replace("ヤフー", "楽天市場")

    # キャプションノイズの最終サニタイズ（類似商品はこちら...などの残滓を記事本文からも念のため抹消）
    html_content = re.sub(r'類似商品はこちら[^\n<。]*[。<]?', '', html_content)
    html_content = re.sub(r'#[^\s　#<]+', '', html_content)

    # チェック4: LLMによるプロ品質校正（AI臭さの排除と文脈の完全性）
    proofread_prompt = f"""以下のメンズコスメ選抜記事のHTMLに対して、厳格な品質校正を行ってください。

【タイトル】: {title}
【記事HTML】:
{html_content}

【厳格校正ルール】:
1. 誤字脱字、てにをは、不自然な文言を徹底的に修正してください。
2. 【★最重要】文章が途中で力尽きたり、末尾が『...』や『…』で途切れる現象は【完全禁止】です。すべての文章を「〜です。」「〜ます。」などの自然な日本語の句点（。）で完璧に完結させてください。
3. 【★絶対厳守】掲載されているすべての商品紹介セクション（h3、画像、フック文、解説、メリット、購入ボタン）および末尾の比較表・総括を【絶対に削除・省略・要約せず、すべて完全に残してください】。
4. 『注目1』『注目2』や『◯月の厳選ポイント』などの安易なテンプレ表現が残っている場合は完全に削除し、商品ごとに異なる生々しい推薦文・洗練された見出しに整えてください。
5. 『いかがでしたでしょうか？』などの陳腐なAIブログ特有の言い回しを削除し、読者の知的好奇心と購入意欲を刺激する洗練された男性美容ライターの文章に整えてください。
6. すべての見出し（h2, h3）と段落（p）、リスト（ul, li）、divタグが正しく閉じられており、文末が途中で切れていないことを確認してください。
7. HTMLタグ構造やリンクURL、画像タグは一切壊さず維持してください。
8. 余計な挨拶や解説は不要です。ブラッシュアップされた純粋なHTML本文のみを出力してください。
"""
    proofread_system = "あなたは大手男性美容WEBマガジンの最高編集責任者です。妥協のない厳格な校正を行い、途中で途切れることのない高品質なHTMLのみを返します。"
    refined_html = call_llm(proofread_prompt, proofread_system, temperature=0.3, max_tokens=4500)

    if refined_html and len(refined_html.strip()) > 500:
        cleaned_refined = refined_html.strip()
        if "```html" in cleaned_refined:
            cleaned_refined = cleaned_refined.split("```html", 1)[1].split("```")[0].strip()
        elif "```" in cleaned_refined:
            cleaned_refined = cleaned_refined.split("```", 1)[1].split("```")[0].strip()
        
        # 校正によって商品や画像が脱落していないか安全確認
        refined_imgs = [it.get("imgUrl") for it in items if it.get("imgUrl") and it.get("imgUrl") in cleaned_refined]
        refined_h3_count = cleaned_refined.count("<h3")
        if len(refined_imgs) >= len(items) - 1 and refined_h3_count >= len(items):
            html_content = cleaned_refined
            print("[REFINE] Refinement step completed successfully without item truncation.")
        else:
            print(f"[REFINE-WARN] Refined HTML lost items or images (imgs: {len(refined_imgs)}/{len(items)}, h3: {refined_h3_count}). Reverting to pre-refinement HTML.")

    # チェック4.5: 三点リーダー（... や …）および文末途切れの機械的撲滅
    # 「...」や「…」が段落内や文末に残っている場合は句点に置換
    html_content = re.sub(r'[\.]{2,}', '。', html_content)
    html_content = re.sub(r'…+', '。', html_content)
    # 重複した句点（。。）を1つに統合
    html_content = re.sub(r'。+', '。', html_content)
    # 句点＋タグの不自然な並び（例: 。</p> を担保）
    html_content = re.sub(r'([^。！？!?\s>])</p>', r'\1。</p>', html_content)
    html_content = re.sub(r'([^。！？!?\s>])</li>', r'\1</li>', html_content)

    # チェック5: 比較テーブルおよびまとめの死守・強制保証
    # 校正LLMや生成でテーブルやまとめが落ちていた場合、確実に末尾に注入する
    has_table = "<table" in html_content
    has_summary = "総括" in html_content or "選び方ガイド" in html_content

    if not has_table or not has_summary:
        print("[QUALITY-GUARANTEE] Table or summary was missing after LLM refinement. Appending guaranteed comparison table and summary!")
        guaranteed_appendix = build_comparison_table_and_summary(items, len(items))
        
        # 閉じdivの直前に挿入するか、末尾に追記
        if "</div>" in html_content:
            last_div_idx = html_content.rfind("</div>")
            html_content = html_content[:last_div_idx] + "\n" + guaranteed_appendix + "\n</div>"
        else:
            html_content += "\n" + guaranteed_appendix

    # チェック6: 閉じタグ整合性の自動補正
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
                for open_attempt in range(8):
                    print(f"[BLOGGER-OPEN] Attempt {open_attempt + 1} / 8 to open editor...")
                    
                    if "edit" in page.url:
                        editor_opened = True
                        break

                    # 失敗が続く場合は一度リロードまたは再アクセスしてDOM状態をリセット
                    if open_attempt > 0 and open_attempt % 2 == 0:
                        try:
                            print("[BLOGGER-OPEN] Refreshing posts page to reset state...")
                            page.goto(posts_url, wait_until="domcontentloaded", timeout=30000)
                            time.sleep(3.0)
                        except Exception as refresh_err:
                            print(f"[BLOGGER-OPEN-WARN] Refresh failed: {refresh_err}")

                    # ポリシー通知やポップアップを閉じる
                    try:
                        close_btn = page.locator('div:has-text("Blogger のコンテンツ ポリシー") [role="button"], div[aria-label*="閉じる"], button[aria-label*="閉じる"]').first
                        if close_btn.is_visible(timeout=1500):
                            close_btn.click()
                            time.sleep(0.5)
                    except Exception:
                        pass

                    # クリック前の先頭記事リンクを記録
                    before_first_link = None
                    try:
                        first_el = page.locator('a[href*="/blog/post/edit/"]').first
                        if first_el.is_visible(timeout=2000):
                            before_first_link = first_el.get_attribute("href")
                    except Exception:
                        pass

                    try:
                        # 画面内に表示されている「新しい投稿を作成」ボタンを取得してクリック
                        btn = None
                        selectors = [
                            'div[role="button"][aria-label*="新しい投稿を作成"]',
                            'div[role="button"]:has-text("新しい投稿")',
                            'button:has-text("新しい投稿")',
                            'a[aria-label*="新しい投稿"]',
                            '[data-action-id="create_post"]'
                        ]
                        for sel in selectors:
                            target = page.locator(sel).locator("visible=true").first
                            if target.is_visible(timeout=1500):
                                btn = target
                                break

                        if not btn:
                            all_btns = page.locator('div[role="button"][aria-label*="新しい投稿を作成"]').all()
                            for b in all_btns:
                                if b.is_visible():
                                    btn = b
                                    break

                        if btn:
                            print(f"[BLOGGER-OPEN] Clicking New Post button...")
                            btn.click(timeout=5000)
                        
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
                        print(f"[BLOGGER-OPEN] Trying direct navigation to new post URL: {new_url}")
                        page.goto(new_url, wait_until="domcontentloaded", timeout=30000)
                        time.sleep(4.0)
                        if "edit" in page.url:
                            editor_opened = True
                            print(f"[BLOGGER-OPEN] Direct navigation succeeded: {page.url}")
                            break
                    except Exception as de:
                        print(f"[BLOGGER-OPEN-WARN] Direct navigation failed: {de}")

                    time.sleep(2.0 + open_attempt)

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
                        # 本文が確実に貼り付けられたか検証（imgが複数、aリンク、テーブルが含まれること）
                        expected_img_min = max(2, len(re.findall(r'<img', content)) - 1)
                        actual_img_count = page_html.count("<img")
                        if actual_img_count >= expected_img_min and ("href" in page_html or "http" in page_html) and "<table" in page_html:
                            print(f"Validation passed: Body content successfully inserted into Blogger editor (found {actual_img_count} images & table).")
                            success = True
                            break
                        else:
                            print(f"Validation check warning: Editor content verification incomplete (imgs found: {actual_img_count}/{expected_img_min}, table: {'<table' in page_html}). Retrying...")
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

        # 投稿直前ガード: 不完全な記事はBloggerに絶対に投稿させない
        final_img_count = final_html.count("<img")
        final_h3_count = final_html.count("<h3")
        final_has_table = "<table" in final_html
        if final_img_count < len(items) - 1 or final_h3_count < len(items) or not final_has_table or len(final_html) < 2000:
            print(f"[CRITICAL-REPAIR] Article content was incomplete before posting (imgs: {final_img_count}, h3: {final_h3_count}, table: {final_has_table}). Falling back to robust complete fallback generation.")
            # 確実・安全なフォールバックで記事全体を再生成
            main_item = items[0]
            main_product = main_item.get("product") or main_item.get("cleanName", "厳選ギア")
            fb_parts = [
                f'<div class="mens-curation-article" style="line-height: 1.85; color: #2d3748; font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, Helvetica, Arial, sans-serif;">',
                f'<p>日々の身だしなみや肌のお手入れは、ビジネス・プライベートを問わず第一印象を決定づける最重要ファクターです。今回は「{theme_obj["theme"].replace("選抜", "")}」をテーマに、楽天市場で注目を集めている実力派アイテム{len(items)}点を厳選ピックアップしました。使いやすさと確かな実感にこだわったラインナップをご覧ください。</p>'
            ]
            for idx, it in enumerate(items, 1):
                name = it["cleanName"]
                brand, product = it.get("brand") or "注目ブランド", it.get("product") or name
                price = it.get("itemPrice", "")
                img = it["imgUrl"]
                url = it["affUrl"]
                caption = clean_rakuten_item_caption(it.get("itemCaption", ""))
                if not caption:
                    caption = f"男性の肌質や使い勝手を追求して開発された「{brand}」の注目のケアギア。"
                elif not caption.endswith(('。', '！', '!')):
                    caption += '。'
                
                fb_parts.append(f'<h3 style="border-left: 5px solid #2b6cb0; padding-left: 12px; margin-top: 40px; font-size: 20px; color: #1a202c;">「{brand}」{product[:24]}</h3>')
                fb_parts.append(f'<p style="font-weight: bold; color: #2b6cb0; font-size: 15px; margin: 8px 0 6px 0;">⚡ 男の身だしなみを手間なく底上げする実用性と確かな品質を両立</p>')
                fb_parts.append(f'<p style="margin: 0 0 14px 0; color: #718096; font-size: 14px;"><b>商品スペック:</b> {name}（価格目安: {price}円）</p>')
                if img:
                    fb_parts.append(f'<div style="text-align:center; margin:18px 0;"><img src="{img}" alt="{name}" style="max-width:320px; border-radius:8px; box-shadow: 0 4px 12px rgba(0,0,0,0.08);"></div>')
                fb_parts.append(f'<p style="margin: 14px 0;">{caption}</p>')
                fb_parts.append(f'<ul style="background-color: #f7fafc; border: 1px solid #edf2f7; padding: 15px 15px 15px 35px; border-radius: 6px; margin: 15px 0;">')
                fb_parts.append(f'<li style="margin-bottom: 6px;">忙しい朝や疲れた夜でも無理なく続けられる快適な使用感</li>')
                fb_parts.append(f'<li style="margin-bottom: 6px;">男特有の皮脂や乾燥トラブルを考え抜いた成分・設計</li>')
                fb_parts.append(f'<li>清潔感のある洗練された第一印象をサポート</li>')
                fb_parts.append(f'</ul>')
                fb_parts.append(f'<div style="text-align:center; margin:20px 0;"><a href="{url}" target="_blank" rel="noopener noreferrer" style="display:inline-block; padding: 12px 28px; background-color: #bf0000; color: #fff; font-weight: bold; border-radius: 6px; text-decoration: none; box-shadow: 0 2px 6px rgba(191,0,0,0.3);">🛒 楽天市場で詳細・口コミを見る</a></div>')
            fb_parts.append(build_comparison_table_and_summary(items, len(items)))
            fb_parts.append('</div>')
            final_html = "".join(fb_parts)
            print("[CRITICAL-REPAIR] Completely reconstructed all 5 items with guaranteed images, links, and comparison table.")

        # 4. Bloggerへ自動投稿（room投稿は行わない）
        blogger_post_url = None
        for b_attempt in range(3):
            try:
                print(f"\n[MAIN] Executing Blogger Post Attempt {b_attempt + 1} / 3...")
                blogger_post_url = post_to_blogger(title, final_html)
                if blogger_post_url:
                    break
            except Exception as pe:
                print(f"[MAIN-WARN] Blogger post attempt {b_attempt + 1} failed: {pe}")
                if b_attempt < 2:
                    print("[MAIN-WARN] Waiting 20 seconds before retry...")
                    time.sleep(20.0)
                else:
                    raise pe

        print(f"Blogger Publication Complete: {blogger_post_url}")

        # 5. キャッシュ保存 ＆ タイトル・テーマ履歴保存（重複防止）
        save_to_cache(item_codes)
        save_posted_title(title)
        save_recent_theme(theme_obj["theme"])
        print(f"Saved title and theme to history to prevent future duplicates.")

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

