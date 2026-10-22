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
    {"theme": "メンズ洗顔料・毛穴汚れ＆イチゴ鼻集中ケア", "keyword": "メンズ 洗顔 毛穴 泥 クレイ 炭 黒ずみ", "problem": "毛穴の黒ずみ・アブラ・角栓"},
    {"theme": "メンズ酵素洗顔パウダー・角質オフケア", "keyword": "メンズ 酵素洗顔 パウダー 個包装", "problem": "古い角質・肌のゴワつき・くすみ"},
    {"theme": "メンズ高保湿化粧水・乾燥肌＆インナードライ対策", "keyword": "メンズ 化粧水 高保湿 セラミド ヒアルロン酸", "problem": "カサつき・粉ふき・インナードライ"},
    {"theme": "メンズ皮脂テカリ防止化粧水・オイルコントロール", "keyword": "メンズ 化粧水 テカリ防止 皮脂 吸着 さっぱり", "problem": "夕方の顔のテカリ・ギトギト脂・化粧崩れ"},
    {"theme": "メンズ薬用美白・ビタミンCシミ対策美容液", "keyword": "メンズ 美容液 ビタミンC誘導体 シミ そばかす メラノ", "problem": "紫外線ダメージ・シミ・くすみ・色ムラ"},
    {"theme": "メンズエイジングケア美容液・レチノール＆ナイアシンアミド", "keyword": "メンズ 美容液 レチノール ナイアシンアミド ハリ シワ", "problem": "小ジワ・肌のたるみ・年齢サイン・ハリ不足"},
    {"theme": "メンズオールインワンジェル・朝10秒の時短スキンケア", "keyword": "メンズ オールインワン ジェル ポンプ 時短", "problem": "朝のスキンケアの手間・面倒くささ・乾燥"},
    {"theme": "メンズ乳液・水分油分バランスクリーム", "keyword": "メンズ 乳液 バリア機能 うるおい ベタつかない", "problem": "化粧水後の乾燥・肌バリアの低下・ゴワつき"},
    {"theme": "メンズアイクリーム・目の下のクマ＆疲労感ケア", "keyword": "メンズ アイクリーム クマ たるみ 目元 アイクレマ", "problem": "青グマ・茶グマ・目元の老け見え・どんより顔"},
    {"theme": "メンズシートマスク・大事な日の前夜の集中パック", "keyword": "メンズ フェイスパック シートマスク CICA 保湿 個包装", "problem": "大事な商談・デート前の肌コンディション調整"},
    {"theme": "メンズリップケア・荒れ知らずのうるおい高保湿リップ", "keyword": "メンズ リップクリーム 高保湿 セラミド 無香料 荒れ防止", "problem": "冬の唇の皮むけ・ガサガサ・血色の悪さ"},
    {"theme": "メンズ色付きリップ・血色感UPで健康的な口元に", "keyword": "メンズ リップ 色付き 血色 ナチュラル ナチュラルレッド", "problem": "唇の血色の悪さ・不健康に見える顔色"},
    {"theme": "メンズCICAシカクリーム・ニキビ肌荒れ鎮静ケア", "keyword": "メンズ CICA シカクリーム 肌荒れ ニキビ 赤み", "problem": "赤ら顔・繰り返すニキビ・カミソリ負けの赤み"},
    {"theme": "メンズピールオフパック・角栓ごっそり毛穴パック", "keyword": "メンズ ピールオフパック 鼻パック 毛穴角栓 剥がすパック", "problem": "頑固な小鼻の角栓・毛穴のザラつき"},
    {"theme": "メンズ導入美容液・ブースターローション", "keyword": "メンズ 導入美容液 ブースター 浸透 先行美容液", "problem": "スキンケアが肌に入っていかない・浸透力の低下"},
    {"theme": "メンズBBクリーム・青ヒゲ＆毛穴バレずにカバー", "keyword": "メンズ BBクリーム ナチュラル ベージュ 青髭 毛穴隠し", "problem": "夕方の青ヒゲ・毛穴の凹凸・クマ・赤み"},
    {"theme": "メンズCCクリーム・自然なトーンアップ＆透明感", "keyword": "メンズ CCクリーム トーンアップ 素肌感 色ムラ補正", "problem": "顔全体のくすみ・お疲れ顔・暗い肌トーン"},
    {"theme": "メンズコンシーラー・ピンポイントニキビ跡・シミ隠し", "keyword": "メンズ コンシーラー スティック クマ ニキビ跡 部分隠し", "problem": "目立つ赤ニキビ跡・ピンポイントの濃いシミ"},
    {"theme": "メンズフェイスパウダー・夕方までサラサラ陶器肌", "keyword": "メンズ フェイスパウダー 無色 テカリ防止 ノーセバム サラサラ", "problem": "Tゾーンのテカリ・マスク蒸れ・メイク崩れ"},
    {"theme": "メンズ日焼け止めジェル・白浮きゼロ＆ベタつきなしUV", "keyword": "メンズ 日焼け止め ウォータープルーフ SPF50 さっぱり ジェル", "problem": "紫外線による日焼け・シミ予備軍・白浮き"},
    {"theme": "メンズUVスティック・手を汚さずサッと塗り直せる日焼け止め", "keyword": "メンズ UVスティック サンスティック 直塗り 手が汚れない", "problem": "外出先での日焼け止めの塗り直し・ベタつき"},
    {"theme": "メンズクレンジングバーム・毛穴黒ずみ＆BBクリーム完全オフ", "keyword": "メンズ クレンジング バーム 毛穴 メイク落とし 毛穴汚れ", "problem": "BBクリームの落とし残し・毛穴に詰まった汚れ"},
    {"theme": "メンズアイブロウペンシル・自然な美眉で第一印象激変", "keyword": "メンズ アイブロウ ペンシル 眉墨 落ちにくい グレー ブラウン", "problem": "薄い眉毛・まばら眉・ぼやけた目元の印象"},
    {"theme": "メンズ眉毛スタイリングセット・ハサミ＆コーム＆毛抜き", "keyword": "メンズ 眉毛セット ハサミ コーム 毛抜き 眉カット", "problem": "ボサボサ眉毛・自己流手入れの失敗"},
    {"theme": "メンズ電気シェーバー・肌に優しく夕方までツルツルの深剃り", "keyword": "メンズ 電気シェーバー 往復式 回転式 深剃り お風呂剃り", "problem": "カミソリ負け・ヒリヒリ感・夕方のジョリジョリ青ヒゲ"},
    {"theme": "メンズシェービングジェル・濃密刃滑りでカミソリ負け回避", "keyword": "メンズ シェービングジェル 薬用 透明 ヒゲ剃り ひきしめ", "problem": "ヒゲ剃り時の肌荒れ・逆剃りの痛み・出血"},
    {"theme": "メンズアフターシェーブローション・ヒゲ剃り後の肌鎮静", "keyword": "メンズ アフターシェーブローション 抑毛 保湿 鎮静 引き締め", "problem": "ヒゲ剃り直後のヒリつき・乾燥・赤み"},
    {"theme": "メンズ鼻毛カッター・痛くない＆安全設計の身だしなみ必需品", "keyword": "メンズ 鼻毛カッター 電動 水洗い 安全カッター", "problem": "不意に飛び出る鼻毛・商談時の清潔感リスク"},
    {"theme": "メンズ薬用スカルプシャンプー・頭皮の脂＆フケかゆみ根絶", "keyword": "メンズ 薬用スカルプシャンプー アミノ酸系 フケ かゆみ 頭皮臭", "problem": "頭皮のベタつき・夕方の頭皮のニオイ・フケ"},
    {"theme": "メンズ育毛剤・抜け毛を防ぎ強いハリコシ髪を育てる", "keyword": "メンズ 育毛剤 医薬部外品 薬用 発毛促進 抜け毛予防 トニック", "problem": "抜け毛の増加・頭頂部のボリューム不足・細毛"},
    {"theme": "メンズ電動頭皮ブラシ・自宅で本格サロン級ヘッドスパ", "keyword": "メンズ 頭皮マッサージ 電動 スカルプブラシ EMS 完全防水", "problem": "頭皮のコリ・目の疲れ・血行不良による薄毛不安"},
    {"theme": "メンズ頭皮用炭酸スプレー・パチパチ爽快スカルプトニック", "keyword": "メンズ 炭酸 スカルプスプレー ジェット 頭皮冷却 リフレッシュ", "problem": "夏の頭皮の蒸れ・汗の不快感・仕事中のリフレッシュ"},
    {"theme": "メンズマットヘアワックス・ツヤなし自然な束感＆超キープ", "keyword": "メンズ ヘアワックス マット ドライ クレイ 束感 崩れない", "problem": "ペタッと潰れる軟毛・ワックス特有のギトギト感"},
    {"theme": "メンズ水性ポマード＆グリース・大人の色気と艶バーバースタイル", "keyword": "メンズ ポマード グリース 水性 バーバー 艶 クラシック 水で流せる", "problem": "バーバースタイルの崩れ・シャンプーで落ちにくい油分"},
    {"theme": "メンズヘアバーム・センターパート＆毛流れナチュラルセット", "keyword": "メンズ ヘアバーム オーガニック ナチュラル センターパート 濡れ髪", "problem": "作り込みすぎない自然な毛流れ・アホ毛の広がり"},
    {"theme": "メンズヘアオイル・パサつき補修＆自然なツヤ出し", "keyword": "メンズ ヘアオイル ダメージ補修 サラサラ 洗い流さないトリートメント", "problem": "カラー・パーマによる髪の傷み・乾燥毛のパサつき"},
    {"theme": "メンズ超強力ヘアスプレー・強風や湿気でも1日崩さない", "keyword": "メンズ ヘアスプレー ハード 超強力キープ 雨 湿気 ロック", "problem": "雨の日の湿気崩れ・自転車や風によるスタイリング崩壊"},
    {"theme": "メンズ白髪隠しスティック・出かける直前にサッとカバー", "keyword": "メンズ 白髪隠し スティック 部分染め マスカラ シャンプーで落ちる", "problem": "生え際やもみあげのチラ見え白髪・急な外出"},
    {"theme": "メンズ白髪染めトリートメント・毎日の入浴で自然に若返り", "keyword": "メンズ 白髪染め トリートメント 徐々に染まる 頭皮に優しい", "problem": "美容院に行く時間がない・急に真っ黒になる不自然さ"},
    {"theme": "メンズボディシェーバー・VIO＆すね毛を清潔に整える", "keyword": "メンズ ボディシェーバー ムダ毛処理 VIO対応 すね毛 防水", "problem": "短パン時の濃すぎるすね毛・蒸れやすいアンダーヘア"},
    {"theme": "メンズ除毛クリーム・最短5分で剛毛ごっそりツルすべ肌", "keyword": "メンズ 除毛クリーム 薬用 大容量 低刺激 剛毛", "problem": "カミソリによる肌荒れ・毛抜きで抜く激痛"},
    {"theme": "メンズ薬用デオドラントボディソープ・加齢臭＆汗臭を元から断つ", "keyword": "メンズ 薬用ボディソープ 加齢臭 体臭 殺菌 デオドラント 柿渋", "problem": "ミドル脂臭・加齢臭・運動後の男臭"},
    {"theme": "メンズ高密着ワキ用ロールオン・汗ジミ＆ニオイを1日完全ブロック", "keyword": "メンズ デオドラント ロールオン 制汗剤 ワキガ 汗止め アルミニウムフリー", "problem": "白シャツの黄ばみ・ワキ汗ジミ・ワキガ臭"},
    {"theme": "メンズ足用消臭クリーム・長時間の革靴でも靴を脱げる清潔足へ", "keyword": "メンズ 足 消臭クリーム 薬用 殺菌 防臭 革靴 ムレ", "problem": "居酒屋のお座敷で靴を脱ぐ恐怖・足の強烈なニオイ"},
    {"theme": "メンズ練り香水・ふんわり香ってビジネスでも好印象なソリッドパフューム", "keyword": "メンズ 練り香水 ソリッドパフューム シトラス サボン 清潔感 つけすぎない", "problem": "香水のつけすぎによるスメハラ・きつい人工香料"},
    {"theme": "メンズ高保湿ハンドクリーム・名刺交換で魅せるベタつかない手元", "keyword": "メンズ ハンドクリーム ベタつかない さらさら スマホ操作 保湿 手荒れ", "problem": "カサカサの手・ささくれ・スマホ画面への指紋ベタつき"},
    {"theme": "メンズ舌ブラシ＆口臭予防ジェル・至近距離の会話も怖くない", "keyword": "メンズ 口臭予防 舌ブラシ 舌ジェル 薬用 オーラルケア 息スッキリ", "problem": "朝の口臭・タバコやコーヒー後の口内ネバつき"},
    {"theme": "メンズ爪切り＆ガラス製爪やすり・指先の清潔感で差をつける", "keyword": "メンズ 爪切り 高級 ガラス 爪やすり ネイルケア 清潔感", "problem": "ガタガタの爪・伸びた爪・名刺交換時の指先の不潔感"},
    {"theme": "メンズファブリックスプレー・スーツのタバコ・焼肉臭を瞬時に消臭", "keyword": "メンズ ファブリックスプレー 衣類消臭 除菌 スーツ 香水代わり", "problem": "洗えないスーツに染み付いたタバコ臭・飲み会の油のニオイ"},
    {"theme": "メンズシャワージェル・欧米プレミアムなバスタイム", "keyword": "メンズ シャワージェル 高級 香り ボディウォッシュ", "problem": "マンネリ化したバスタイム・安っぽい石鹸の匂い"},
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

KNOWN_MENS_BRANDS = [
    ("SHISEIDO MEN", "資生堂メン"),
    ("BULK HOMME", "バルクオム"),
    ("QUATTRO BOTANICO", "クワトロボタニコ"),
    ("LIPPS BOY", "リップスボーイ"),
    ("LIPPS", "リップス"),
    ("OCEAN TRICO", "オーシャントリコ"),
    ("GATSBY", "ギャツビー"),
    ("LUCIDO", "ルシード"),
    ("UNO", "ウーノ"),
    ("OXY", "オキシー"),
    ("UL・OS", "ウルオス"),
    ("NULL", "ヌル"),
    ("ZIGEN", "ジゲン"),
    ("THE FUTURE", "ザフューチャー"),
    ("WOOMEN", "ウーメン"),
    ("HMENZ", "エイチメンズ"),
    ("DISM", "ディズム"),
    ("MARO17", "マーロ17"),
    ("MARO", "マーロ"),
    ("ANGFA", "アンファー"),
    ("スカルプD", "スカルプD"),
    ("LAB SERIES", "ラボシリーズ"),
    ("CLINIQUE FOR MEN", "クリニーク フォー メン"),
    ("CLINIQUE", "クリニーク"),
    ("KIEHL'S", "キールズ"),
    ("AESOP", "イソップ"),
    ("THREE", "スリー"),
    ("BAUM", "バウム"),
    ("NIVEA MEN", "ニベアメン"),
    ("メンズビオレ", "メンズビオレ"),
    ("サクセス", "サクセス"),
    ("TAVARAT", "タバラット"),
    ("BROSH", "ブロッシュ"),
    ("クールグリース", "クールグリース"),
    ("バブロポマード", "バブロポマード"),
    ("ナプラ", "ナプラ"),
    ("ミルボン", "ミルボン"),
    ("アリミノ", "アリミノ"),
    ("中野製薬", "ナカノ"),
    ("デミ", "デミ"),
    ("ウエラ", "ウエラ")
]

def clean_rakuten_item_name(name):
    """
    楽天の長文SEOキーワード、クーポン、宣伝文句、容量表記を完全消去し、
    読者が一目で理解できる自然で洗練された商品名（12〜20文字程度）へクレンジング
    """
    if not name:
        return "実力派メンズケアアイテム"
        
    cleaned = name
    # 括弧とその中身を全除去（【楽天1位】、【送料無料】、【SPF50+】など）
    cleaned = re.sub(r'【[^】]*】', ' ', cleaned)
    cleaned = re.sub(r'\[[^\]]*\]', ' ', cleaned)
    cleaned = re.sub(r'（[^）]*）', ' ', cleaned)
    cleaned = re.sub(r'\([^\)]*\)', ' ', cleaned)
    cleaned = re.sub(r'「[^」]*」', ' ', cleaned)
    cleaned = re.sub(r'『[^』]*』', ' ', cleaned)
    
    # 楽天の常套句・スペック・宣伝文句を徹底消去
    noise_patterns = [
        r'クーポン(?:で|\s*利用で|\s*配布中|\s*対象)?\s*[0-9,]+円?(?:OFF|off)?',
        r'P[0-9]+倍', r'ポイント[0-9]+倍', r'送料無料', r'即納', r'あす楽',
        r'マラソン(?:限定)?', r'スーパーセール', r'お買い物マラソン',
        r'楽天(?:1位|ランキング1位|デイリー1位)',
        r'[0-9]+%OFF', r'[0-9]+％OFF', r'★[0-9\.]+★?',
        r'レビュー(?:特典|プレゼント|高評価)', r'公式(?:店|ショップ)?',
        r'医薬部外品', r'正規品', r'日本製', r'国内製造', r'男女兼用', r'レディース',
        r'ギフト', r'プレゼント', r'贈り物', r'父の日', r'母の日', r'バレンタイン',
        r'お試し', r'サンプル', r'詰替(?:え|用)?', r'大容量', r'限定',
        r'SPF\s*[0-9]+\+*', r'PA\s*\++',
        r'ウォータープルーフ', r'ノンケミカル', r'ノンシリコン', r'オーガニック'
    ]
    for pat in noise_patterns:
        cleaned = re.sub(pat, ' ', cleaned, flags=re.IGNORECASE)
        
    cleaned = re.sub(r'[＼／★◆■●▼▲〜～!！?？|｜:：;；+＋_＿]+', ' ', cleaned)
    
    # 一般的な宣伝・検索用キーワードの除外
    banned_words = {
        "メンズ", "男性", "男", "用", "向け", "おすすめ", "人気", "スキンケア", "コスメ",
        "セット", "対策", "予防", "ケア", "グッズ", "アイテム", "市販", "ランキング",
        "メール便", "定形外", "ネコポス", "小型宅配便", "宅配便", "あす楽対応", "ゴルフ",
        "用に", "水に強い", "自然な肌色", "テカリ防止", "日焼止めクリーム", "日焼け止め"
    }
    
    words = []
    for w in cleaned.split():
        w_clean = w.strip()
        if len(w_clean) <= 1:
            continue
        if w_clean in banned_words:
            continue
        # 数字＋単位（100g, 150ml, 30gなど）や型番（TLU-001など）を除外
        if re.match(r'^[0-9]+(?:g|ml|mL|本|個|枚|回分|点|点セット)$', w_clean, re.IGNORECASE):
            continue
        if re.match(r'^[A-Z0-9\-]{4,}$', w_clean):
            continue
        words.append(w_clean)
        
    # ブランド名＋商品名のスッキリした組み合わせを構成
    res = " ".join(words[:4]).strip()
    if len(res) > 22:
        res = res[:22].strip()
    return res if res else "注目ケアアイテム"


def clean_rakuten_item_caption(caption, brand="", product=""):
    """
    itemCaptionから全成分・製造販売元・モニター注意書き・宣伝文句を徹底排除し、
    商品の使用感や特徴のみを凝縮した自然な紹介文（60〜110文字）を抽出
    """
    if not caption:
        return f"{brand}が男性のために開発した、毎日の使いやすさと確かな効果を両立する実力派ケアアイテムです。"
    
    text = caption
    # 類似商品、関連商品、広告定型文の全削除
    text = re.sub(r'類似商品はこちら[^\n。]*[。\n]?', '', text)
    text = re.sub(r'関連商品[^\n。]*[。\n]?', '', text)
    text = re.sub(r'おすすめ商品[^\n。]*[。\n]?', '', text)
    text = re.sub(r'関連キーワード[：:][^\n。]*[。\n]?', '', text)
    text = re.sub(r'お客様のお使いの(?:PC|モニター|スマートフォン|端末)[^\n。]*[。\n]?', '', text)
    text = re.sub(r'(?:製造販売元|発売元|製造元|広告文責|輸入者|区分|TEL|問い合わせ)[：:][^\n。]*[。\n]?', '', text)
    text = re.sub(r'【?全成分】?[：:][^\n。]*[。\n]?', '', text)
    text = re.sub(r'#[^\s　#]+', '', text)
    text = re.sub(r'[^\s　、。]+[0-9,]+円[、。]?', '', text)
    text = re.sub(r'https?://[^\s]+', '', text)
    text = re.sub(r'[■★◆●▼▲・~〜※【】『』［］\[\]]+', ' ', text)
    text = re.sub(r'[-=─━―]{3,}', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    sentences = re.split(r'[。\n]+', text)
    meaningful_sentences = []
    total_len = 0
    
    ng_sentence_keywords = [
        "株式会社", "サイバール", "クイックレスポンス", "電話番号", "モニター", "若干の違い",
        "クロスポリマー", "ポリマー", "ジメチコン", "エチルヘキシル", "エラスチン", "全成分",
        "メール便", "送料無料", "即日発送", "あす楽", "返品", "交換", "特定商取引",
        "ギフトラッピング", "プレゼント包装", "定形外"
    ]
    
    for s in sentences:
        s_clean = s.strip()
        if len(s_clean) < 8 or len(s_clean) > 85:
            continue
        if any(kw in s_clean for kw in ng_sentence_keywords):
            continue
        if not s_clean.endswith(('。', '！', '!')):
            s_clean += '。'
        meaningful_sentences.append(s_clean)
        total_len += len(s_clean)
        if total_len >= 130:
            break
            
    if meaningful_sentences:
        return "".join(meaningful_sentences)

    return f"{brand}が男性のために開発した、毎日の使いやすさと確かな効果を両立する実力派ケアアイテムです。"


def extract_brand_and_product(clean_name, raw_name=""):
    """
    商品名から既知のブランドと商品名をスマートに分離。
    「日焼け止め」等のカテゴリ一般名がブランド名として誤認されるのを完全に防止。
    """
    target_str = f"{raw_name} {clean_name}" if raw_name else clean_name
    
    # 1. 既知ブランドの探索
    found_brand = None
    for en, ja in KNOWN_MENS_BRANDS:
        pattern = re.compile(rf'(?:{re.escape(en)}|{re.escape(ja)})', re.IGNORECASE)
        if pattern.search(target_str):
            found_brand = ja if ja else en
            break
            
    # 2. ブランドが見つかった場合、商品名側からブランド名を除去
    if found_brand:
        product = clean_name
        product = re.sub(re.escape(found_brand), '', product, flags=re.IGNORECASE).strip()
        words = product.split()
        product = " ".join(words[:3]) if words else "注目ケアアイテム"
        if len(product) > 20:
            product = product[:20].strip()
        return found_brand, product
        
    # 3. 未知ブランドの場合、先頭単語をブランド候補とし、一般名詞はブランドとしない
    words = clean_name.split()
    if not words:
        return "注目ブランド", "実力派アイテム"
        
    general_nouns = {"日焼け止め", "洗顔料", "化粧水", "乳液", "美容液", "ジェル", "クリーム", "ワックス", "バーム", "オイル", "シャンプー", "シェーバー"}
    if words[0] in general_nouns:
        brand = "厳選ブランド"
        product = " ".join(words[:3])
    else:
        brand = words[0]
        product = " ".join(words[1:4]) or brand
        
    if len(product) > 20:
        product = product[:20].strip()
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

    # 直近選ばれたテーマを避けて選定（最低25件の過去テーマと重複しないようにし、テーマの循環ローテーションを保証）
    recent_themes = load_recent_themes(limit=25)
    available_themes = [t for t in MENS_THEMES if t["theme"] not in recent_themes]
    if not available_themes:
        # すべて一巡した場合は直近10件のみを除外して再ローテーション
        recent_themes_short = load_recent_themes(limit=10)
        available_themes = [t for t in MENS_THEMES if t["theme"] not in recent_themes_short]
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

        clean_n = clean_rakuten_item_name(name)
        brand, product = extract_brand_and_product(clean_n, raw_name=name)
        it["cleanName"] = clean_n
        it["brand"] = brand
        it["product"] = product
        it["cleanCaption"] = clean_rakuten_item_caption(it.get("itemCaption", ""), brand=brand, product=product)
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
                        exp_clean = clean_rakuten_item_name(exp_name)
                        exp_brand, exp_product = extract_brand_and_product(exp_clean, raw_name=exp_name)
                        exp_it["cleanName"] = exp_clean
                        exp_it["brand"] = exp_brand
                        exp_it["product"] = exp_product
                        exp_it["cleanCaption"] = clean_rakuten_item_caption(exp_it.get("itemCaption", ""), brand=exp_brand, product=exp_product)
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


def call_llm(prompt, system_message, temperature=0.7, max_tokens=8192):
    """
    ユーザー規則に基づく最新Geminiモデルローテーション ＆ Groqフォールバック
    Gemini 1.5系は完全廃止済みのため使用禁止。
    ローテーション順:
    gemini-2.5-flash -> gemini-3.1-flash-lite -> gemini-3.5-flash -> gemini-3.7-flash -> gemini-3.6-flash -> gemini-2.0-flash
    """
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        gemini_rotation = [
            "gemini-2.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-2.0-flash"
        ]
        for model_name in gemini_rotation:
            try:
                api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
                payload = {
                    "contents": [{"parts": [{"text": f"{system_message}\n\n{prompt}"}]}],
                    "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}
                }

                res = requests.post(api_url, json=payload, timeout=50)
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
        for model_name in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]:
            try:
                headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
                # Groqの最大トークン数はモデルによって異なるため上限を安全に設定
                groq_tokens = min(max_tokens, 6000 if "70b" in model_name else 4096)
                payload = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": temperature,
                    "max_tokens": groq_tokens
                }
                res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=45)
                if res.status_code == 200:
                    text = res.json()["choices"][0]["message"]["content"].strip()
                    if len(text) > 50:
                        print(f"Generated successfully with Groq model: {model_name}")
                        return text
                else:
                    print(f"Groq API ({model_name}) error {res.status_code}: {res.text[:120]}")
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
        brand = it.get('brand') or "注目ブランド"
        product = it.get('product') or clean_name
        caption_snippet = clean_rakuten_item_caption(it.get('itemCaption', ''), brand=brand, product=product)[:120]
        items_desc_list.append(
            f"--- 【商品 {idx}】 ---\n"
            f"ブランド名: {brand}\n"
            f"商品名: {product}\n"
            f"価格目安: {it.get('itemPrice', '')}円\n"
            f"独自特徴・強み: {caption_snippet}\n"
            f"画像URL: {it['imgUrl']}\n"
            f"アフィリエイトURL: {it['affUrl']}\n"
        )
        item_keywords_all.append(product)
    items_context = "\n".join(items_desc_list)

    # 過去タイトルの一覧（直近30件）をプロンプトに含めて重複を禁止
    past_titles = load_posted_titles()[-30:]
    past_titles_str = "\n".join([f"- {t}" for t in past_titles]) if past_titles else "（過去の重複なし）"

    target_problem = theme_obj.get("problem", "男の身だしなみの悩み")

    system_message = (
        "あなたは実力派メンズ美容ジャーナリスト・編集長です。"
        "Google検索・SEOで高く評価され、読者の男性が『まさに自分の悩みの答えがここにある』と唸るような、専門性と熱量の高い一次情報風の特集記事を執筆します。"
        "【絶対厳守の独自性ルール】:\n"
        "1. 『男の清潔感を高めるギア』『男を上げる』『失敗しない』『いかがでしたでしょうか』『〜ですね！』などの安易な陳腐フレーズ・テンプレ構文は完全使用禁止。\n"
        "2. 記事タイトルは、読者の抱える具体的な痛み・悩み（例: 夕方のテカリ、青ヒゲ、頭皮臭、加齢臭など）や、選抜商品の持つ決定的な価値に切り込むこと。\n"
        "3. 過去のタイトル構文の模倣は完全禁止。\n"
        "4. 各商品の紹介文は、成分や処方、テクスチャー、使い心地の違いに踏み込み、5商品すべてが全く異なる個性として引き立つように具体的に書き分けること。"
    )

    prompt = f"""以下は楽天市場から選抜したメンズコスメ・身だしなみアイテム{count}点の詳細データです。
今回のテーマ【{theme_obj['theme']}】（解消する悩み：{target_problem}）にフォーカスし、オリジナリティ溢れる高品質な特集レビュー記事を執筆してください。

【特集テーマ】: {theme_obj['theme']}
【ターゲットの切実な悩み】: {target_problem}
【掲載アイテム一覧】:
{items_context}

【過去のタイトル一覧（これらと構文やキーワード組み合わせが酷似するものは【完全禁止】）】:
{past_titles_str}

【記事作成要件】:
1. タイトル（title）:
   - 過去のタイトル一覧と絶対に被らない、新鮮で引きの強いオリジナルタイトル（32〜42文字程度）。
   - 「男の清潔感を高めるギア」「失敗しない〜」などの使い古されたテンプレ語句は使わず、読者の悩みや商品の強みに焦点を当てること。
2. 本文HTML（html）:
   - 全体を `<div class="mens-curation-article" style="line-height: 1.85; color: #2d3748; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">` で囲む。
   - 導入部（リード文）:
     - 「{target_problem}」について、多くの男性が共感するリアルなシチュエーションを提示し、今回の{count}アイテムがなぜその解決策になるのかを説得力ある文章で300〜400文字執筆。
   - 各商品紹介（1〜{count}）:
     - `<h3>` は【その商品独自の刺さるキャッチコピー】＋「【ブランド名】商品名」の形式。
     - 見出し直下に、推薦フック文（`<p style="font-weight: bold; color: #2b6cb0; font-size: 15px; margin: 8px 0 6px 0;">⚡ ...</p>`）。
     - 画像表示: `<div style="text-align: center; margin: 18px 0;"><img src="画像URL" alt="商品名" style="max-width: 320px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.08);"></div>`
     - レビュー本文: 成分設計、実際の使用感、テクスチャー、香り、仕上がり、どんな肌質・悩みの男性に向いているかを深く掘り下げて解説（160〜220文字）。
     - 3つの具体的なメリット（`<ul><li style="margin-bottom: 6px;">`）。
     - 購入リンクボタン: `<div style="text-align: center; margin: 20px 0;"><a href="アフィリエイトURL" target="_blank" rel="noopener noreferrer" style="display:inline-block; padding: 12px 28px; background-color: #bf0000; color: #fff; font-weight: bold; font-size: 15px; border-radius: 6px; text-decoration: none; box-shadow: 0 2px 6px rgba(191,0,0,0.3);">🛒 楽天市場で詳細・口コミを見る</a></div>`
   - 一目でわかる！厳選アイテム徹底比較表（`<table>`）を必ず挿入。
   - まとめセクション: `<h3>編集部まとめ：後悔しないためのスマートな選び方</h3>` を添えて読者の背中を押すメッセージで締めくくる。

【出力形式】
以下のマーカー形式で出力してください：

【TITLE】
（オリジナルの魅力的な記事タイトル）

【HTML】
<div class="mens-curation-article" style="line-height: 1.85; color: #2d3748; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
（完成した完全な本文HTML）
</div>
"""

    # 記事が全商品を網羅し、完全な構造を持つか検証する関数
    def validate_article_completeness(html_str, expected_items):
        if not html_str or len(html_str.strip()) < 1200:
            return False, f"文字数不足 ({len(html_str.strip()) if html_str else 0}文字)"
        
        # 全商品の画像URLが含まれているか（クエリパラメータ違いやURL短縮も考慮して検証）
        def check_img_present(target_url):
            if not target_url:
                return True
            if target_url in html_str:
                return True
            base = target_url.split("?")[0]
            return base in html_str

        img_missing = [it.get("imgUrl") for it in expected_items if not check_img_present(it.get("imgUrl"))]
        if img_missing:
            return False, f"商品画像欠落 ({len(img_missing)}件未掲載)"
            
        # 全商品のアフィリエイトURLが含まれているか
        def check_aff_present(target_url):
            if not target_url:
                return True
            if target_url in html_str:
                return True
            if "?" in target_url:
                base = target_url.split("?")[0]
                if base in html_str:
                    return True
            return False

        aff_missing = [it.get("affUrl") for it in expected_items if not check_aff_present(it.get("affUrl"))]
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
        raw_response = call_llm(prompt, system_message, temperature=0.8, max_tokens=8192)
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
        
        theme_name = theme_obj.get("theme", "メンズケア")
        target_problem = theme_obj.get("problem", "男の身だしなみの悩み")

        # 過去タイトルと重複せず、テーマ・悩み・商品を前面に出した独自タイトル候補
        candidate_titles = [
            f"【{target_problem.split('・')[0]}対策】大人の男が選ぶ「{lead_brand}」ほか実力派{count}選",
            f"もう悩まない！{theme_name.split('・')[0]}で手に入れる圧倒的な清潔感{count}選",
            f"【{target_problem}】を攻略！「{main_product[:14]}」など本気でおすすめしたい{count}品",
            f"第一印象が劇的に変わる！男の肌・髪を整える注目の「{lead_brand}」ほか{count}選"
        ]
        chosen_title = None
        for cand in candidate_titles:
            is_dup, _, _ = is_title_duplicate_or_similar(cand)
            if not is_dup:
                chosen_title = cand
                break
        if not chosen_title:
            chosen_title = f"【{theme_name.split('・')[0]}】大人の男を格上げする{main_product[:12]}ほか厳選{count}選"

        body_parts = []
        body_parts.append(f'<div class="mens-curation-article" style="line-height: 1.85; color: #2d3748; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">')
        body_parts.append(f'<p>多くの男性が直面する「{target_problem}」という悩み。日々の身だしなみや肌のコンディションは、仕事での信頼感やプライベートでの好印象を左右する極めて重要な要素です。今回は「{theme_name}」に焦点を当て、実力・人気ともに評価の高い{count}アイテムを厳選しました。それぞれの強みや使い心地を詳しくレビューします。</p>')
        
        for idx, it in enumerate(items, 1):
            name = it["cleanName"]
            brand, product = it.get("brand") or "注目ブランド", it.get("product") or name
            price = it.get("itemPrice", "")
            img = it["imgUrl"]
            url = it["affUrl"]
            caption = clean_rakuten_item_caption(it.get("itemCaption", ""))
            if not caption:
                caption = f"男性特有の悩みや使用感を追求して開発された「{brand}」の実力派アイテム。"
            elif not caption.endswith(('。', '！', '!')):
                caption += '。'
            
            body_parts.append(f'<h3 style="border-left: 5px solid #2b6cb0; padding-left: 12px; margin-top: 40px; font-size: 20px; color: #1a202c;">「{brand}」{product[:24]}</h3>')
            body_parts.append(f'<p style="font-weight: bold; color: #2b6cb0; font-size: 15px; margin: 8px 0 6px 0;">⚡ 【{target_problem.split("・")[0]}の解消へ】{brand}が誇るこだわりの処方設計</p>')
            body_parts.append(f'<p style="margin: 0 0 14px 0; color: #718096; font-size: 14px;"><b>アイテム名:</b> {name}（価格目安: {price}円）</p>')
            
            if img:
                body_parts.append(f'<div style="text-align:center; margin:18px 0;"><img src="{img}" alt="{name}" style="max-width:320px; border-radius:8px; box-shadow: 0 4px 12px rgba(0,0,0,0.08);"></div>')
            body_parts.append(f'<p style="margin: 14px 0;">{caption}</p>')
            body_parts.append(f'<ul style="background-color: #f7fafc; border: 1px solid #edf2f7; padding: 15px 15px 15px 35px; border-radius: 6px; margin: 15px 0;">')
            body_parts.append(f'<li style="margin-bottom: 6px;">【{target_problem.split("・")[0]}】を根本からケアする頼もしい使用感</li>')
            body_parts.append(f'<li style="margin-bottom: 6px;">忙しい男性でも無理なく毎日の習慣に組み込める使い勝手</li>')
            body_parts.append(f'<li>清潔感と自信を一段と引き上げる洗練された仕上がり</li>')
            body_parts.append(f'</ul>')
            body_parts.append(f'<div style="text-align:center; margin:20px 0;"><a href="{url}" target="_blank" rel="noopener noreferrer" style="display:inline-block; padding: 12px 28px; background-color: #bf0000; color: #fff; font-weight: bold; border-radius: 6px; text-decoration: none; box-shadow: 0 2px 6px rgba(191,0,0,0.3);">🛒 楽天市場で詳細・口コミを見る</a></div>')

        body_parts.append(build_comparison_table_and_summary(items, count, theme_obj=theme_obj))
        body_parts.append('</div>')
        
        parsed = {
            "title": chosen_title,
            "html": "".join(body_parts)
        }

    return parsed


def build_comparison_table_and_summary(items, count, theme_obj=None):
    """商品比較テーブルと総括選び方ガイドをテーマ・商品固有のデータから動的に生成（定型文を完全排除）"""
    table_rows = []
    theme_name = (theme_obj.get("theme", "") if theme_obj else "").replace("選抜", "").replace("おすすめ", "")
    target_problem = theme_obj.get("problem", "身だしなみの悩み") if theme_obj else "身だしなみの悩み"

    for idx, it in enumerate(items, 1):
        brand = it.get("brand") or "注目ブランド"
        product = it.get("product") or it.get("cleanName", "")
        price = it.get("itemPrice", "")
        caption = it.get("cleanCaption", "") or it.get("itemCaption", "")

        # 商品固有の解説から特徴的なフレーズを抽出
        first_sentence = caption.split("。")[0] if "。" in caption else caption[:35]
        first_sentence = re.sub(r'[!！★◆■●▼▲〜～]+', '', first_sentence).strip()
        custom_feature = first_sentence[:28] if len(first_sentence) >= 8 else f"{brand}こだわりの処方設計"

        # おすすめな人の動的割り当て
        user_targets = [
            f"{target_problem.split('・')[0]}を根本からケアしたい方",
            "朝の身だしなみ時間を圧倒的に短縮したい方",
            "品質や成分、使用感に一切妥協したくない方",
            "ビジネスや対面シーンでの清潔感を底上げしたい方",
            "コストパフォーマンスと確かな実感を両立させたい方"
        ]
        user_target = user_targets[(idx - 1) % len(user_targets)]

        table_rows.append(
            f'<tr style="border-bottom: 1px solid #e2e8f0;">'
            f'<td style="padding: 12px 14px; font-weight: bold; color: #2d3748;">{brand}<br><span style="font-size: 13px; font-weight: normal; color: #718096;">{product[:18]}</span></td>'
            f'<td style="padding: 12px 14px; color: #c53030; font-weight: bold; white-space: nowrap;">{price}円</td>'
            f'<td style="padding: 12px 14px; font-size: 13px; color: #4a5568;">{custom_feature}</td>'
            f'<td style="padding: 12px 14px; font-size: 13px; color: #2b6cb0;">{user_target}</td>'
            f'</tr>'
        )

    table_html = (
        f'<h3 style="margin-top: 45px; font-size: 21px; color: #1a202c; border-bottom: 2px solid #2b6cb0; padding-bottom: 8px;">📊 【徹底比較】今回紹介した{count}アイテムのスペック＆おすすめ早見表</h3>'
        f'<div style="overflow-x: auto; margin: 20px 0;">'
        f'<table style="width: 100%; border-collapse: collapse; min-width: 540px; font-size: 14px; text-align: left; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">'
        f'<thead style="background-color: #edf2f7;"><tr style="border-bottom: 2px solid #cbd5e0;"><th style="padding: 12px 14px;">商品・ブランド</th><th style="padding: 12px 14px;">価格目安</th><th style="padding: 12px 14px;">主な強み・特徴</th><th style="padding: 12px 14px;">こんな男性に最適</th></tr></thead>'
        f'<tbody>{"".join(table_rows)}</tbody></table></div>'
    )

    summary_html = (
        f'<h3 style="margin-top: 40px; font-size: 21px; color: #1a202c; border-bottom: 2px solid #2b6cb0; padding-bottom: 8px;">編集部まとめ：失敗しないためのスマートな選び方</h3>'
        f'<p>今回取り上げた「{theme_name}」は、男性が抱えがちな【{target_problem}】を解消し、周囲に好印象を与えるための心強い味方です。まずは自分のライフスタイルや予算に最もマッチする1品を普段の習慣に取り入れて、違いを体感してみてください。</p>'
    )
    return table_html + "\n" + summary_html


def strict_quality_check_and_refine(title, html_content, items, theme_obj=None):
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
        guaranteed_appendix = build_comparison_table_and_summary(items, len(items), theme_obj=theme_obj)
        
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

                        print("Injecting HTML content...")
                        # 1. BloggerのHTML編集モード (CodeMirror) への直接注入
                        cm_injected = page.evaluate('''html => {
                            try {
                                const cmEl = document.querySelector('.CodeMirror');
                                if (cmEl && cmEl.CodeMirror) {
                                    cmEl.CodeMirror.setValue(html);
                                    if (typeof cmEl.CodeMirror.save === 'function') {
                                        cmEl.CodeMirror.save();
                                    }
                                    // 変更・保存イベントを発火させる
                                    cmEl.CodeMirror.focus();
                                    cmEl.CodeMirror.replaceRange(' ', cmEl.CodeMirror.getCursor());
                                    cmEl.CodeMirror.execCommand('deleteCharBackward');
                                    return true;
                                }
                            } catch (e) {
                                console.error('CodeMirror inject error:', e);
                            }
                            return false;
                        }''', content)

                        if cm_injected:
                            print("[BLOGGER-INJECT] Successfully injected HTML directly into CodeMirror editor.")
                            time.sleep(2.5)
                        else:
                            # 2. リッチテキスト編集モード時のフォールバック (クリップボードペースト)
                            print("[BLOGGER-INJECT] CodeMirror not found. Falling back to clipboard paste...")
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
                            time.sleep(2.0)

                        # CodeMirrorまたはページのHTMLを検証
                        cm_val = page.evaluate('''() => {
                            const cmEl = document.querySelector('.CodeMirror');
                            return (cmEl && cmEl.CodeMirror) ? cmEl.CodeMirror.getValue() : '';
                        }''')
                        page_html = page.content()
                        effective_html = cm_val if cm_val else page_html

                        expected_img_min = max(2, len(re.findall(r'<img', content)) - 1)
                        actual_img_count = effective_html.count("<img")
                        has_links = "href" in effective_html or "http" in effective_html
                        has_table = "<table" in effective_html

                        if actual_img_count >= expected_img_min and has_links and has_table:
                            print(f"Validation passed: Body content successfully inserted into Blogger editor (found {actual_img_count} images & table).")
                            success = True
                            break
                        else:
                            print(f"Validation check warning: Editor content verification incomplete (imgs found: {actual_img_count}/{expected_img_min}, table: {has_table}). Retrying...")
                    except Exception as e:
                        print(f"Error during attempt {attempt+1}: {e}")
                    time.sleep(2)

                if not success:
                    # 失敗時に未完了下書きがBlogger上に残らないよう後始末
                    try:
                        print("[BLOGGER-CLEANUP] Post validation failed. Discarding unfinished draft...")
                        page.goto(f"https://draft.blogger.com/blog/posts/{blog_id}", wait_until="domcontentloaded", timeout=15000)
                        time.sleep(2.0)
                        discard_btn = page.locator('div[aria-label="この投稿を破棄"]').first
                        if discard_btn.is_visible(timeout=3000):
                            discard_btn.dispatch_event('click')
                            time.sleep(1.0)
                            page.keyboard.press('Enter')
                            time.sleep(1.5)
                            print("[BLOGGER-CLEANUP] Discarded unfinished draft successfully.")
                    except Exception as discard_err:
                        print(f"[BLOGGER-CLEANUP-WARN] Failed to discard draft: {discard_err}")

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
        final_html = strict_quality_check_and_refine(title, html_content, items, theme_obj=theme_obj)

        # 投稿直前ガード: 不完全な記事はBloggerに絶対に投稿させない
        final_img_count = final_html.count("<img")
        final_h3_count = final_html.count("<h3")
        final_has_table = "<table" in final_html
        if final_img_count < len(items) - 1 or final_h3_count < len(items) or not final_has_table or len(final_html) < 2000:
            print(f"[CRITICAL-REPAIR] Article content was incomplete before posting (imgs: {final_img_count}, h3: {final_h3_count}, table: {final_has_table}). Falling back to robust complete fallback generation.")
            # 確実・安全なフォールバックで記事全体を再生成
            main_item = items[0]
            main_product = main_item.get("product") or main_item.get("cleanName", "厳選ギア")
            theme_name = theme_obj.get("theme", "メンズケア")
            target_problem = theme_obj.get("problem", "男の身だしなみの悩み")

            fb_parts = [
                f'<div class="mens-curation-article" style="line-height: 1.85; color: #2d3748; font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, Helvetica, Arial, sans-serif;">',
                f'<p>多くの男性が直面する「{target_problem}」という悩み。日々の身だしなみや肌のコンディションは、仕事での信頼感やプライベートでの好印象を左右する極めて重要な要素です。今回は「{theme_name}」に焦点を当て、実力・人気ともに評価の高い{len(items)}アイテムを厳選しました。それぞれの強みや使い心地を詳しくレビューします。</p>'
            ]
            for idx, it in enumerate(items, 1):
                name = it["cleanName"]
                brand, product = it.get("brand") or "注目ブランド", it.get("product") or name
                price = it.get("itemPrice", "")
                img = it["imgUrl"]
                url = it["affUrl"]
                caption = clean_rakuten_item_caption(it.get("itemCaption", ""))
                if not caption:
                    caption = f"男性特有の悩みや使用感を追求して開発された「{brand}」の実力派アイテム。"
                elif not caption.endswith(('。', '！', '!')):
                    caption += '。'
                
                fb_parts.append(f'<h3 style="border-left: 5px solid #2b6cb0; padding-left: 12px; margin-top: 40px; font-size: 20px; color: #1a202c;">「{brand}」{product[:24]}</h3>')
                fb_parts.append(f'<p style="font-weight: bold; color: #2b6cb0; font-size: 15px; margin: 8px 0 6px 0;">⚡ 【{target_problem.split("・")[0]}の解消へ】{brand}が誇るこだわりの処方設計</p>')
                fb_parts.append(f'<p style="margin: 0 0 14px 0; color: #718096; font-size: 14px;"><b>アイテム名:</b> {name}（価格目安: {price}円）</p>')
                if img:
                    fb_parts.append(f'<div style="text-align:center; margin:18px 0;"><img src="{img}" alt="{name}" style="max-width:320px; border-radius:8px; box-shadow: 0 4px 12px rgba(0,0,0,0.08);"></div>')
                fb_parts.append(f'<p style="margin: 14px 0;">{caption}</p>')
                fb_parts.append(f'<ul style="background-color: #f7fafc; border: 1px solid #edf2f7; padding: 15px 15px 15px 35px; border-radius: 6px; margin: 15px 0;">')
                fb_parts.append(f'<li style="margin-bottom: 6px;">【{target_problem.split("・")[0]}】を根本からケアする頼もしい使用感</li>')
                fb_parts.append(f'<li style="margin-bottom: 6px;">忙しい男性でも無理なく毎日の習慣に組み込める使い勝手</li>')
                fb_parts.append(f'<li>清潔感と自信を一段と引き上げる洗練された仕上がり</li>')
                fb_parts.append(f'</ul>')
                fb_parts.append(f'<div style="text-align:center; margin:20px 0;"><a href="{url}" target="_blank" rel="noopener noreferrer" style="display:inline-block; padding: 12px 28px; background-color: #bf0000; color: #fff; font-weight: bold; border-radius: 6px; text-decoration: none; box-shadow: 0 2px 6px rgba(191,0,0,0.3);">🛒 楽天市場で詳細・口コミを見る</a></div>')
            fb_parts.append(build_comparison_table_and_summary(items, len(items), theme_obj=theme_obj))
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

