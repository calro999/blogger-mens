import os
import sys
import json
import random
import time
import re
import io
from datetime import datetime, timezone
import requests
from atproto import Client, client_utils
from PIL import Image

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
        except Exception:
            pass

load_env_file()
load_env_file(".env.local")

BLUESKY_HISTORY_FILE = "bluesky_post_history.txt"
BLUESKY_TEXT_HISTORY_FILE = "bluesky_text_history.txt"
BLUESKY_ENGAGEMENT_FILE = "bluesky_engagement_history.txt"

BLUESKY_HANDLE = os.environ.get("BLUESKY_HANDLE", "tigyu-cosme.bsky.social")
BLUESKY_APP_PASSWORD = os.environ.get("BLUESKY_APP_PASSWORD", "ebeq-ainb-o63m-tfwc")
DEFAULT_BLOG_URL = os.environ.get("TIGYU_BLOG_URL", "https://tigyu-mens.vercel.app")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

# ユーザー規則に基づく最新Gemini対応モデル一覧（Gemini 1.5は完全廃止済みのため除外）
GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-3-flash",
    "gemini-3.1-pro"
]

def load_posted_history():
    if os.path.exists(BLUESKY_HISTORY_FILE):
        with open(BLUESKY_HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def record_posted_history(slug):
    with open(BLUESKY_HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{slug}\n")

def load_text_history():
    if os.path.exists(BLUESKY_TEXT_HISTORY_FILE):
        with open(BLUESKY_TEXT_HISTORY_FILE, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    return []

def record_text_history(text):
    cleaned = re.sub(r'\s+', ' ', text).strip()
    with open(BLUESKY_TEXT_HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{cleaned}\n")

def load_engagement_history():
    if os.path.exists(BLUESKY_ENGAGEMENT_FILE):
        with open(BLUESKY_ENGAGEMENT_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def record_engagement_history(identifier):
    with open(BLUESKY_ENGAGEMENT_FILE, "a", encoding="utf-8") as f:
        f.write(f"{identifier}\n")

def is_similar_to_history(new_text, history_list):
    """過去の投稿テキストと冒頭・末尾・主要フレーズの重複を多角的に厳格判定"""
    if not history_list:
        return False
    new_norm = re.sub(r'[\s、。！？!?,.]', '', new_text)
    for past in history_list[-30:]:
        past_norm = re.sub(r'[\s、。！？!?,.]', '', past)
        # 冒頭12文字が完全一致
        if len(new_norm) >= 12 and len(past_norm) >= 12 and new_norm[:12] == past_norm[:12]:
            return True
        # 末尾12文字が完全一致
        if len(new_norm) >= 12 and len(past_norm) >= 12 and new_norm[-12:] == past_norm[-12:]:
            return True
        # 18文字以上の連続共通部分
        if len(new_norm) >= 18 and len(past_norm) >= 18:
            for i in range(len(new_norm) - 17):
                if new_norm[i:i+18] in past_norm:
                    return True
    return False

def optimize_image_bytes(raw_bytes, max_bytes=850000):
    """Blueskyのアップロード上限（Blob最大2MB、推奨1MB未満）に合わせて画像をリサイズ・軽量化"""
    if len(raw_bytes) <= max_bytes:
        return raw_bytes
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        max_dim = 1600
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        quality = 90
        while quality >= 50:
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=quality, optimize=True)
            res = out.getvalue()
            if len(res) <= max_bytes:
                return res
            quality -= 10
        return res
    except Exception as e:
        print(f"[WARN] Image optimization failed: {e}")
        return raw_bytes[:max_bytes] if len(raw_bytes) > 2000000 else raw_bytes

def fetch_item_image_bytes(image_url):
    """
    商品画像URLから高解像度のオリジナル画像バイトを取得し、クリアな画質を維持したまま最適化
    楽天サムネイル（?_ex=128x128）を700x700またはオリジナルURLへ昇格
    """
    if not image_url:
        return None

    candidates = []
    if "_ex=" in image_url:
        candidates.append(re.sub(r'\?_ex=[0-9]+x[0-9]+', '?_ex=700x700', image_url))
    clean_url = image_url.split("?")[0]
    candidates.append(clean_url)
    if "@0_mall/" in clean_url:
        orig_url = clean_url.replace("https://thumbnail.image.rakuten.co.jp/@0_mall/", "https://image.rakuten.co.jp/")
        candidates.append(orig_url)
    candidates.append(image_url)

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    for u in candidates:
        try:
            res = requests.get(u, headers=headers, timeout=10)
            if res.status_code == 200 and len(res.content) > 10000:
                print(f"[IMAGE-HD] Fetched high-res image from: {u[:80]}... ({len(res.content)} bytes)")
                return optimize_image_bytes(res.content)
        except Exception:
            continue

    try:
        res = requests.get(image_url, headers=headers, timeout=10)
        if res.status_code == 200 and len(res.content) > 1000:
            return optimize_image_bytes(res.content)
    except Exception as e:
        print(f"[WARN] Failed to fetch item image from {image_url}: {e}")
    return None

def generate_dynamic_smart_fallback(title, item_name, cur_month, cur_season, past_texts):
    clean_item = re.sub(r'【.*?】|\[.*?\]|（.*?）', '', item_name).strip()
    words = clean_item.split()
    short_name = " ".join(words[:3]) if len(words) >= 3 else clean_item
    if len(short_name) > 26:
        short_name = short_name[:26].strip()

    persona_templates = [
        {
            "openers": [
                f"学生時代、見た目で損して自己肯定感底辺だった過去の自分に真っ先に手渡したいのが「{short_name}」。",
                f"「どうせ何使っても変わらない」って諦めてた過去の自分をぶん殴りたくなる逸品が「{short_name}」。",
                f"早く知っておけば何年も清潔感で損せずに済んだのに…と本気で悔やんだ神ギアがこれ。",
                f"鏡見るたびに肌や身だしなみで憂鬱になってた時期、これに出会ってたら一瞬で救われてた。"
            ],
            "cores": [
                f"{cur_month}月の{cur_season}特有の乾燥やトラブルを寄せ付けず、使った翌朝から肌治安が別人に仕上がる。",
                f"難しいテクニック一切なしでサッと仕込むだけで、周囲から「なんか雰囲気変わった？」って自然に聞かれるレベル。",
                f"テカリやパサつきを一発でリセットして、男の第一印象で一番大事な『圧倒的な清潔感』を底上げしてくれる。",
                f"ベタつきや違和感が一切残らないから、ズボラで面倒くさがりな自分でも毎日ノンストレスで続いた。"
            ],
            "closers": [
                "見た目に本気で自信持ちたいなら、遠回りせずにまずこれから投資してほしい。",
                "身だしなみで二度と損したくない男子は、騙されたと思って試してみてほしい。",
                "小さな課金で自己肯定感が劇的に跳ね上がるから、迷ってる暇あったら即導入推奨。",
                "「何から変えればいいか分からない」なら、まずこれ握りしめておけば間違いなく勝てる。"
            ]
        },
        {
            "openers": [
                f"至近距離で人と話すとき、相手の視線が自分の肌やパーツにいってヒヤッとしたことないか？",
                f"服をいくらオシャレにしても、顔まわりや細部の清潔感が抜けてたら一発で台無しになる。",
                f"飲み会やオフィスで「この人清潔感あるな」と思われる男子が密かに仕込んでるのが「{short_name}」。",
                f"女子が本能的にチェックしてるのって、ブランド服じゃなくて肌と身だしなみの細部なんだよな。"
            ],
            "cores": [
                f"「{short_name}」は至近距離で見られても隙がないレベルで、毛穴感や清潔感をしっかり整えてくれる。",
                f"清潔感の土台を一瞬で作れるから、急なデートや大事な予定の前でも焦る必要が完全になくなる。",
                f"不潔に見える原因を根本からブロックしてくれるから、会話中の目線にビビることが一切なくなった。",
                f"{cur_month}月の乾燥しやすいコンディションでも、カサつき知らずの清潔感カンスト状態をキープできる。"
            ],
            "closers": [
                "人前で堂々と笑えるようになりたいなら、迷わず自分の身だしなみに課金してほしい。",
                "第一印象で減点されたくない全メンズへ、本気でおすすめしたい必須の武器。",
                "会話中の距離感に自信が持てるようになるから、毎日の対人関係のストレスが激減する。",
                "清潔感を最速でカンストさせたいなら、まずこのアイテムから仕込んでみてくれ。"
            ]
        },
        {
            "openers": [
                f"男の垢抜け投資で「一番コスパ良くて即効性あったギアどれ？」って聞かれたら迷わずこれ。",
                f"朝の貴重な時間を1ミリも無駄にしたくないズボラ男子こそ「{short_name}」を使うべき。",
                f"高いエステや美容医療に手を出す前に、まず毎日の習慣に「{short_name}」を組み込むのが正解。",
                f"手間をかけずに最短ルートで見た目のクオリティを上げたいなら、これ以上の選択肢はない。"
            ],
            "cores": [
                f"毎日のわずか数分で完結するのに、仕上がりと肌の清潔感はサロン級に跳ね上がる。",
                f"手頃な価格帯なのに中身のクオリティがガチすぎて、適当買いとは次元が違う。",
                f"使い心地が軽やかで続けやすいから、習慣化した瞬間から垢抜けスピードが一気に加速する。",
                f"無駄なステップを全部省いて、男が一番必要としてる効果だけをピンポイントで届けてくれる。"
            ],
            "closers": [
                "最小の努力で最大の清潔感を手に入れたいなら、これ一択で間違いない。",
                "面倒くさがりだけどカッコよくなりたい男子は、今すぐルーティンに取り入れてほしい。",
                "コスパもタイパも最高峰。一度この快適さを知ったら二度と手放せなくなる。",
                "時間とお金を無駄に浪費したくないなら、まずこの逸品から試してみてくれ。"
            ]
        },
        {
            "openers": [
                f"{cur_month}月の乾燥と冷え込みで、肌や身だしなみが一気にカサついて清潔感落ちてないか？",
                f"暖房の効いた部屋にいると、夕方に顔がパリパリになったり皮脂崩れして絶望する男へ。",
                f"季節の変わり目に清潔感を落とす男子が多い中、涼しい顔で好印象をキープできる神アイテム。",
                f"秋冬の乾燥対策、何を選べばいいか迷ってるなら「{short_name}」がダントツで心強い。"
            ],
            "cores": [
                f"外気と暖房のダブルパンチから肌を守り抜いて、うるおいと清潔感の黄金バランスをキープしてくれる。",
                f"粉吹きや不快なベタつきを徹底的に防いで、いつ誰に見られても恥ずかしくない清潔肌に整えてくれる。",
                f"乾燥による見た目のくすみや疲れ感をパッと払拭して、イキイキとした清潔感ある印象を取り戻せる。",
                f"重たい使用感が苦手な男でもゴクゴク使える馴染みの良さで、秋冬の過酷な環境を余裕で乗り切れる。"
            ],
            "closers": [
                "今の季節を清潔感あるイケメン肌で乗り切りたいなら、絶対にポーチや洗面台に常備しておくべき。",
                "乾燥で老け見えする前に、今すぐこの名品で清潔感のバリアを張ってほしい。",
                "季節の変わり目こそ差がつくタイミング。周囲と圧倒的な清潔感の差をつけよう。",
                "秋冬の身だしなみで絶対に失敗したくないなら、これを持っておけば間違いない。"
            ]
        }
    ]

    for _ in range(30):
        persona = random.choice(persona_templates)
        op = random.choice(persona["openers"])
        co = random.choice(persona["cores"])
        cl = random.choice(persona["closers"])
        candidate = f"{op} {co} {cl}"
        if not is_similar_to_history(candidate, past_texts):
            return candidate

    return f"{persona_templates[0]['openers'][0]} {persona_templates[0]['cores'][0]} {persona_templates[0]['closers'][0]}"


def generate_tigyu_post_text(article, item):
    """
    最新Geminiモデルを活用し、「チー牛ラボ 〜劇的垢抜けアイテム研究〜」として
    AI臭さのないリアルで熱量の高い推薦ポスト文を生成。
    過去の投稿と重複しない完全にユニークな文章を保証。
    現在の季節・時期に厳格に合わせたリアルなトーンで作成。
    """
    title = article.get("title", "")
    item_name = item.get("name", "厳選アイテム")
    price = item.get("price", "")

    now = datetime.now()
    cur_month = now.month
    cur_season = "秋" if cur_month in [9, 10, 11] else ("冬" if cur_month in [12, 1, 2] else ("春" if cur_month in [3, 4, 5] else "夏"))

    past_texts = load_text_history()

    hooks_angles = [
        "「垢抜けたいなら真っ先にこれを使え！」と断言する理由",
        "「色々試したけど、結局これが一番清潔感出た…！」という本気のおすすめ",
        "見た目の印象を劇的に変えたいメンズが今すぐ手に入れるべき神ギア",
        "肌や身だしなみで損したくない男子へ。まずコレ使っとけば間違いないやつ",
        "脱チー牛・清潔感カンストを目指すなら絶対外せない劇的垢抜けアイテム",
        "正直もっと早く買っておけばよかったと本気で後悔したレベルの逸品",
        "女子ウケや第一印象をガラリと変えたいなら、迷わずこれに課金すべき",
        "カサつきや芋っぽさを一発で払拭してくれる、チー牛救済の即効アイテム",
        "「何から始めればいいか分からない」男子は、とりあえずこれ買えば勝ち確",
        "男の身だしなみで一番費用対効果が高い、ガチ推しの垢抜けツール",
        "清潔感がないと言われて凹んでた過去の自分に全力で渡したい神コスメ",
        "朝の数分で劇的に垢抜ける。面倒くさがり男子にこそ使ってほしいアイテム"
    ]
    random.shuffle(hooks_angles)

    text = None
    if GEMINI_KEY:
        random_models = list(GEMINI_MODELS)
        random.shuffle(random_models)

        for angle in hooks_angles[:4]:
            if text:
                break
            prompt = f"""
あなたはBlueskyアカウント「チー牛ラボ 〜劇的垢抜けアイテム研究〜」（@tigyu-cosme.bsky.social）の運営者です。
元々垢抜けずに悩み、メンズ美容やスキンケアで劇的に人生が変わった男性が、リアルな本音で投稿します。

【現在の時期・季節】
- 現在は {cur_month}月（{cur_season}）です。
- ※重要：過去や時期外れの季節に関する言及は【完全厳禁】です。今の時期（{cur_month}月・{cur_season}の乾燥対策や季節の変わり目、秋冬の身だしなみ）、または年中通して使える清潔感アップ習慣として語ってください。

【今回の厳選アイテム】
- 記事タイトル: {title}
- 商品名: {item_name}（{price}）
- 対象読者: {article.get('targetAudience', '清潔感を出したいZ世代男性')}
- 今回の切り口: {angle}

【厳格な執筆ルール】
1. AI特有の定型句（「こんにちは」「今回は〜をご紹介します」「〜はいかがでしょうか」「ぜひ試してみてね」）は【一切禁止】。
2. テンプレート感のある機械的な文章は禁止。毎回オリジナルの熱量で、Twitter/Blueskyの生身のユーザーのように書いてください。
3. 「垢抜けたいならこれを使え！」「これガチでおすすめだ」「清潔感爆上がりする」といった、男子に強く刺さる説得力のある本音の推薦文にしてください。
4. この商品を使うことでどう劇的に垢抜けるのか、何が他のものと違うのかを具体的に1〜2点だけ絞って熱く語ってください。
5. 出力は「推薦本文のみ（90〜130文字程度）」にしてください。URLやハッシュタグ・挨拶は含めないでください。
"""
            system_instruction = f"あなたは「チー牛ラボ 〜劇的垢抜けアイテム研究〜」の熱狂的な男性美容研究者です。現在は{cur_month}月（{cur_season}）です。季節感を絶対に間違えず、AI臭さを徹底的に排除した、生々しく説得力のあるリアルな本音ポスト文のみを出力します。"

            for model in random_models[:3]:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_KEY}"
                    payload = {
                        "contents": [{"parts": [{"text": f"{system_instruction}\n\n{prompt}"}]}],
                        "generationConfig": {"temperature": 0.92, "maxOutputTokens": 300}
                    }
                    res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=12)
                    if res.status_code == 200:
                        data = res.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts and parts[0].get("text"):
                                gen_text = parts[0]["text"].strip()
                                gen_text = gen_text.replace("```", "").replace("\n\n", "\n").strip()
                                gen_text = re.sub(r'https?://[^\s]+', '', gen_text).strip()
                                gen_text = re.sub(r'#[^\s]+', '', gen_text).strip()

                                if len(gen_text) >= 40 and not is_similar_to_history(gen_text, past_texts):
                                    text = gen_text
                                    print(f"[BLUESKY-LLM] Generated unique text using {model}: {text[:50]}...")
                                    break
                                else:
                                    print(f"[BLUESKY-LLM] Rejected duplicate/similar text. Retrying with another angle/model...")
                except Exception:
                    continue

    if not text:
        text = generate_dynamic_smart_fallback(title, item_name, cur_month, cur_season, past_texts)
        print(f"[BLUESKY-FALLBACK] Used dynamic persona-based fallback: {text[:50]}...")

    return text

def build_bluesky_post_payload(post_text, site_article_url, affiliate_url, item_name):
    """
    BlueskyのTextBuilderを用いて、リッチリンク・ハッシュタグを適切に配置した投稿データを作成
    上限300文字/バイト制限に余裕を持たせた設計。
    """
    tb = client_utils.TextBuilder()

    # 1. 本文
    tb.text(post_text.strip() + "\n\n")

    # 2. ブログ記事へのリンク（多彩な見出し＆ボタン）
    link_intros = [
        ("📖 徹底比較・詳細レビュー:\n", "👉 ブログで比較をチェック"),
        ("🔍 アイテム選びの全貌はこちら:\n", "👉 ブログの検証結果を見る"),
        ("📝 詳しい使い分け・リアル感想:\n", "👉 レビュー詳細を読む"),
        ("💡 失敗しない選び方・比較まとめ:\n", "👉 詳しい記事はこちら"),
        ("⚡️ 詳しい使用感と他社比較:\n", "👉 ブログで全比較を見る"),
    ]
    l_intro, l_btn = random.choice(link_intros)
    tb.text(l_intro)
    tb.link(l_btn, site_article_url)
    tb.text("\n\n")

    # 3. 厳選アイテムの楽天アフィリンク（多彩な見出し＆ボタン）
    if affiliate_url:
        aff_intros = [
            ("🛒 今回の劇的垢抜けアイテム:\n", "👉 楽天で詳細をチェック"),
            ("🔥 ガチ推しの垢抜けギア:\n", "👉 楽天市場で見る"),
            ("✨ 一発で清潔感カンストする名品:\n", "👉 楽天の最安・在庫を見る"),
            ("🛍️ 清潔感爆上げの神アイテム:\n", "👉 楽天で今すぐチェック"),
        ]
        a_intro, a_btn = random.choice(aff_intros)
        tb.text(a_intro)
        tb.link(a_btn, affiliate_url)
        tb.text("\n\n")

    # 4. 厳選ハッシュタグ（ローテーション）
    tag_pool = ["垢抜け", "メンズコスメ", "清潔感", "メンズスキンケア", "メンズ美容", "身だしなみ", "男磨き"]
    random.shuffle(tag_pool)
    tags = tag_pool[:4]
    for i, t in enumerate(tags):
        tb.tag(f"#{t}", t)
        if i < len(tags) - 1:
            tb.text(" ")

    return tb

def run_mens_engagement_cycle(client):
    """
    メンズ美容・垢抜け・スキンケアに関心のある一般ユーザーへ、自然なペースでいいね・フォローを行う
    アカウント立ち上げ初期のインプレッションとフォロワー獲得を加速。
    """
    print("[ENGAGE] Running safe engagement cycle for 'チー牛ラボ'...")
    search_queries = [
        "垢抜けたい",
        "メンズスキンケア",
        "メンズコスメ",
        "肌荒れ 男",
        "清潔感 男",
        "眉毛 整えたい",
        "メンズ 美容",
        "身だしなみ 男"
    ]
    random.shuffle(search_queries)
    engaged_history = load_engagement_history()

    target_likes = random.randint(4, 7)
    target_follows = random.randint(1, 2)
    likes_done = 0
    follows_done = 0

    for query in search_queries[:3]:
        if likes_done >= target_likes and follows_done >= target_follows:
            break
        try:
            res = client.app.bsky.feed.search_posts(params={"q": query, "limit": 20})
            posts = res.posts or []
            random.shuffle(posts)

            for p in posts:
                author_did = p.author.did
                post_uri = p.uri
                post_cid = p.cid

                if author_did == client.me.did or post_uri in engaged_history:
                    continue

                # いいね
                if likes_done < target_likes:
                    try:
                        time.sleep(random.uniform(1.2, 2.5))
                        client.like(uri=post_uri, cid=post_cid)
                        record_engagement_history(post_uri)
                        likes_done += 1
                        print(f"[ENGAGE-LIKE] Liked post ({likes_done}/{target_likes}) from @{p.author.handle}: {p.record.text[:25].replace(chr(10), ' ')}")
                    except Exception as e:
                        print(f"[ENGAGE-WARN] Like failed: {e}")

                # フォロー
                if follows_done < target_follows and author_did not in engaged_history:
                    try:
                        time.sleep(random.uniform(1.5, 3.0))
                        client.follow(subject=author_did)
                        record_engagement_history(author_did)
                        follows_done += 1
                        print(f"[ENGAGE-FOLLOW] Followed user ({follows_done}/{target_follows}): @{p.author.handle}")
                    except Exception as e:
                        print(f"[ENGAGE-WARN] Follow failed: {e}")

                if likes_done >= target_likes and follows_done >= target_follows:
                    break
        except Exception as e:
            print(f"[ENGAGE-WARN] Search query '{query}' failed: {e}")
            continue

    print(f"[ENGAGE-SUMMARY] Engagement finished: {likes_done} likes, {follows_done} follows.")

def post_article_to_bluesky(article):
    if not BLUESKY_APP_PASSWORD:
        print("[WARN] BLUESKY_APP_PASSWORD is not set. Skipping Bluesky post.")
        return False

    client = Client()
    try:
        client.login(BLUESKY_HANDLE, BLUESKY_APP_PASSWORD)
        print(f"[AUTH] Successfully logged in to Bluesky as @{BLUESKY_HANDLE}")
    except Exception as e:
        print(f"[ERROR] Failed to login to Bluesky: {e}")
        return False

    comps = article.get("comparisonTable", [])
    rep_item = comps[0] if comps else {"name": article.get("title", ""), "price": "", "affiliateUrl": "https://item.rakuten.co.jp/"}
    site_article_url = f"{DEFAULT_BLOG_URL.rstrip('/')}/posts/{article['slug']}"
    affiliate_url = rep_item.get("affiliateUrl") or "https://item.rakuten.co.jp/"
    clean_name = rep_item.get("name", "おすすめアイテム")

    print(f"[SELECT] Picked featured item for Bluesky: {clean_name}")

    post_text = generate_tigyu_post_text(article, rep_item)
    tb = build_bluesky_post_payload(post_text, site_article_url, affiliate_url, clean_name)

    # アイテム画像を高画質化・最適化して取得
    img_url = rep_item.get("imageUrl") or article.get("heroImage")
    image_bytes = fetch_item_image_bytes(img_url)

    try:
        if image_bytes:
            print("[BLUESKY] Uploading high-res image to Bluesky...")
            response = client.send_image(
                text=tb,
                image=image_bytes,
                image_alt=f"{clean_name} - チー牛ラボ劇的垢抜けアイテム"
            )
            print(f"[SUCCESS] Posted with image to Bluesky! URI: {response.uri}")
        else:
            response = client.send_post(text=tb)
            print(f"[SUCCESS] Posted text only to Bluesky! URI: {response.uri}")

        record_posted_history(article["slug"])
        record_text_history(post_text)

        # エンゲージメント自動サイクル（いいね4〜7件、フォロー1〜2件）
        time.sleep(random.uniform(2.5, 5.0))
        run_mens_engagement_cycle(client)
        return True

    except Exception as e:
        print(f"[ERROR] Failed to send post to Bluesky: {e}")
        return False

def main():
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] Starting Bluesky post for 'チー牛ラボ'...")
    data_file = "data/posts.json"
    if not os.path.exists(data_file):
        print(f"[ERROR] {data_file} not found.")
        sys.exit(1)

    with open(data_file, "r", encoding="utf-8") as f:
        posts = json.load(f)

    posted_history = load_posted_history()
    target_post = None

    for p in posts:
        if p["slug"] not in posted_history:
            target_post = p
            break

    if not target_post and posts:
        target_post = posts[0]
        print("[INFO] All posts in history. Selecting latest article for promotion.")

    if not target_post:
        print("[ERROR] No posts found to promote.")
        sys.exit(1)

    print(f"[TARGET] Article: {target_post['title']} ({target_post['slug']})")
    success = post_article_to_bluesky(target_post)
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
