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

BLUESKY_HISTORY_FILE = "bluesky_post_history.txt"
BLUESKY_ENGAGEMENT_FILE = "bluesky_engagement_history.txt"
LATEST_POST_FILE = "latest_blogger_post.json"

BLUESKY_HANDLE = os.environ.get("BLUESKY_HANDLE", "tigyu-cosme.bsky.social")
BLUESKY_APP_PASSWORD = os.environ.get("BLUESKY_APP_PASSWORD", "ebeq-ainb-o63m-tfwc")

# ユーザー規則に基づく最新Gemini対応モデル一覧（Gemini 1.5は完全廃止済みのため除外）
GEMINI_MODELS = [
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

def load_posted_history():
    if os.path.exists(BLUESKY_HISTORY_FILE):
        with open(BLUESKY_HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def record_posted_history(item_identifier):
    with open(BLUESKY_HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{item_identifier}\n")

def load_engagement_history():
    if os.path.exists(BLUESKY_ENGAGEMENT_FILE):
        with open(BLUESKY_ENGAGEMENT_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def record_engagement_history(identifier):
    with open(BLUESKY_ENGAGEMENT_FILE, "a", encoding="utf-8") as f:
        f.write(f"{identifier}\n")

def optimize_image_bytes(raw_bytes, max_bytes=850000):
    """Blueskyのアップロード上限（Blob最大2MB、推奨1MB未満）に合わせて画像をリサイズ・軽量化"""
    if len(raw_bytes) <= max_bytes:
        return raw_bytes
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        
        max_dim = 1200
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        
        quality = 85
        while quality >= 35:
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=quality, optimize=True)
            res = out.getvalue()
            if len(res) <= max_bytes:
                return res
            quality -= 15
        return res
    except Exception as e:
        print(f"[WARN] Image optimization failed: {e}")
        return raw_bytes[:max_bytes] if len(raw_bytes) > 2000000 else raw_bytes

def fetch_item_image_bytes(image_url):
    """商品画像URLから画像バイトを取得し軽量化"""
    if not image_url:
        return None
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(image_url, headers=headers, timeout=12)
        if res.status_code == 200 and len(res.content) > 1000:
            return optimize_image_bytes(res.content)
    except Exception as e:
        print(f"[WARN] Failed to fetch item image from {image_url}: {e}")
    return None

def generate_tigyu_post_text(theme_name, item, blogger_url):
    """
    最新Geminiモデルを活用し、「チー牛ラボ 〜劇的垢抜けアイテム研究〜」として
    AI臭さのないリアルで熱量の高い推薦ポスト文を生成。
    「垢抜けたいならこれを使え！」「これがおすすめだ！」を軸に毎回異なるトーンで作成。
    """
    clean_name = item.get("cleanName") or item.get("itemName") or "厳選アイテム"
    price = item.get("itemPrice", "")
    price_info = f"（約{price:,}円）" if price else ""
    gemini_key = os.environ.get("GEMINI_API_KEY")

    # 多彩な切り口（テンプレート使い回しを完全に禁止）
    hooks_angles = [
        "「垢抜けたいなら真っ先にこれを使え！」と断言する理由",
        "「色々試したけど、結局これが一番清潔感出た…！」という本気のおすすめ",
        "見た目の印象を劇的に変えたいメンズが今すぐ手に入れるべき神ギア",
        "肌や身だしなみで損したくない男子へ。まずコレ使っとけば間違いないやつ",
        "脱チー牛・清潔感カンストを目指すなら絶対外せない劇的垢抜けアイテム"
    ]
    chosen_angle = random.choice(hooks_angles)

    prompt = f"""
あなたはBlueskyアカウント「チー牛ラボ 〜劇的垢抜けアイテム研究〜」（@tigyu-cosme.bsky.social）の運営者です。
元々垢抜けずに悩み、メンズ美容やスキンケアで劇的に人生が変わった男性が、リアルな本音で投稿します。

【今回の厳選アイテム】
- テーマ: {theme_name}
- 商品名: {clean_name} {price_info}
- 今回の切り口: {chosen_angle}

【厳格な執筆ルール】
1. AI特有の定型句（「こんにちは」「今回は〜をご紹介します」「〜はいかがでしょうか」「ぜひ試してみてね」）は【一切禁止】。
2. テンプレート感のある機械的な文章は禁止。毎回オリジナルの熱量で、Twitter/Blueskyの生身のユーザーのように書いてください。
3. 「垢抜けたいならこれを使え！」「これガチでおすすめだ」「清潔感爆上がりする」といった、男子に強く刺さる説得力のある本音の推薦文にしてください。
4. この商品を使うことでどう劇的に垢抜けるのか、何が他のものと違うのかを具体的に1〜2点だけ絞って熱く語ってください。
5. 出力は「推薦本文のみ（100〜140文字程度）」にしてください。URLやハッシュタグはシステムが後から付与するので、本文中にはURL・ハッシュタグ・挨拶を含めないでください。
"""
    system_instruction = "あなたは「チー牛ラボ 〜劇的垢抜けアイテム研究〜」の熱狂的な男性美容研究者です。AI臭さを徹底的に排除した、生々しく説得力のあるリアルな本音ポスト文のみを出力します。"

    text = None
    if gemini_key:
        random_models = list(GEMINI_MODELS)
        random.shuffle(random_models)
        for model in random_models:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
                payload = {
                    "contents": [{"parts": [{"text": f"{system_instruction}\n\n{prompt}"}]}],
                    "generationConfig": {"temperature": 0.85, "maxOutputTokens": 300}
                }
                res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=15)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts and parts[0].get("text"):
                            gen_text = parts[0]["text"].strip()
                            gen_text = gen_text.replace("```", "").replace("\n\n", "\n").strip()
                            # URLやハッシュタグが混入していれば除去
                            gen_text = re.sub(r'https?://[^\s]+', '', gen_text).strip()
                            gen_text = re.sub(r'#[^\s]+', '', gen_text).strip()
                            if len(gen_text) >= 40:
                                text = gen_text
                                print(f"[BLUESKY-LLM] Generated text using {model}: {text[:50]}...")
                                break
            except Exception as e:
                print(f"[BLUESKY-LLM] Gemini model {model} attempt failed: {e}")
                continue

    if not text:
        # フォールバック（多様なリアル表現から選択）
        fallbacks = [
            f"垢抜けたいならまずコレ使え！{theme_name}でガチ推ししたいのが「{clean_name}」。テカリや清潔感不足で損してる男子はこれ投入するだけで肌と顔まわりの印象が劇的に変わる。迷ったらまずこれから試してほしい逸品。",
            f"清潔感を手っ取り早くカンストさせたいなら絶対これだ！「{clean_name}」は使い心地も仕上がりも別格。見た目変えたいけど何買えばいいか分からない人は、まずこれ使ってみてほしい。劇的に垢抜けます。",
            f"【チー牛脱却の必須ギア】肌や見た目の印象で悩んでるなら、騙されたと思って「{clean_name}」使ってみてほしい。一発で肌の清潔感底上げされて自己肯定感バグる。垢抜け男子のガチ推しアイテム。"
        ]
        text = random.choice(fallbacks)

    return text

def build_bluesky_post_payload(post_text, blogger_url, affiliate_url, clean_item_name):
    """
    BlueskyのTextBuilderを用いて、リッチリンク・ハッシュタグを適切に配置した投稿データを作成
    上限300文字/バイト制限に余裕を持たせた設計。
    """
    tb = client_utils.TextBuilder()

    # 1. 本文
    tb.text(post_text.strip() + "\n\n")

    # 2. Bloggerまとめ記事へのリンク
    tb.text("📖 徹底比較・詳細レビュー:\n")
    tb.link("👉 ブログ記事を読む", blogger_url)
    tb.text("\n\n")

    # 3. 厳選アイテムの楽天アフィリンク
    if affiliate_url:
        tb.text("🛒 今回の劇的垢抜けアイテム:\n")
        tb.link("👉 楽天でチェック", affiliate_url)
        tb.text("\n\n")

    # 4. 厳選ハッシュタグ
    tags = ["垢抜け", "メンズコスメ", "清潔感", "メンズスキンケア"]
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

def post_to_bluesky_from_blogger(blogger_url, article_title, theme_obj, items):
    """
    Blogger投稿完了時に直接呼び出されるエントリーポイント
    Bloggerの記事URL、タイトル、選抜アイテム情報を受け取り、最もおすすめの1点に焦点を当ててBlueskyに投稿
    """
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] Starting Bluesky post for 'チー牛ラボ'...")

    if not BLUESKY_APP_PASSWORD:
        print("[WARN] BLUESKY_APP_PASSWORD is not set. Skipping Bluesky post. (Set BLUESKY_APP_PASSWORD in .env or GitHub Secrets)")
        return False

    client = Client()
    try:
        client.login(BLUESKY_HANDLE, BLUESKY_APP_PASSWORD)
        print(f"[AUTH] Successfully logged in to Bluesky as @{BLUESKY_HANDLE}")
    except Exception as e:
        print(f"[ERROR] Failed to login to Bluesky: {e}")
        return False

    # 投稿する厳選アイテムを1点選定（過去にBlueskyで投稿していないものを優先）
    history_set = load_posted_history()
    target_item = None
    for it in items:
        code = str(it.get("itemCode") or "")
        if code and code not in history_set:
            target_item = it
            break
    if not target_item and items:
        target_item = random.choice(items)

    if not target_item:
        print("[ERROR] No valid items to post.")
        return False

    theme_name = theme_obj.get("theme", "メンズコスメ選抜")
    clean_name = target_item.get("cleanName", "おすすめアイテム")
    affiliate_url = target_item.get("affUrl", "")
    item_code = str(target_item.get("itemCode") or "")

    print(f"[SELECT] Picked featured item for Bluesky: {clean_name}")

    # Geminiで垢抜け本音レビュー文を生成
    post_text = generate_tigyu_post_text(theme_name, target_item, blogger_url)
    tb = build_bluesky_post_payload(post_text, blogger_url, affiliate_url, clean_name)

    # アイテム画像の取得
    image_bytes = fetch_item_image_bytes(target_item.get("imgUrl"))

    try:
        if image_bytes:
            response = client.send_image(
                text=tb,
                image=image_bytes,
                image_alt=f"{clean_name} - チー牛ラボ劇的垢抜けアイテム"
            )
            print(f"[SUCCESS] Posted with image to Bluesky! URI: {response.uri}")
        else:
            response = client.send_post(text=tb)
            print(f"[SUCCESS] Posted text only to Bluesky! URI: {response.uri}")

        if item_code:
            record_posted_history(item_code)

        # エンゲージメント
        time.sleep(random.uniform(2.5, 5.0))
        run_mens_engagement_cycle(client)
        return True

    except Exception as e:
        print(f"[ERROR] Failed to send post to Bluesky: {e}")
        return False

def save_latest_blogger_post_info(blogger_url, article_title, theme_obj, items):
    """次回単独実行時にも利用できるよう、最新のBlogger記事・商品情報をJSONに保存"""
    data = {
        "blogger_url": blogger_url,
        "article_title": article_title,
        "theme_obj": theme_obj,
        "items": items,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    with open(LATEST_POST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def main():
    """コマンドラインから単独実行する場合"""
    print("=== Standalone Bluesky Post for チー牛ラボ ===")
    if not os.path.exists(LATEST_POST_FILE):
        print(f"[INFO] {LATEST_POST_FILE} not found. Please run mens_blogger.py first or trigger via workflow.")
        sys.exit(0)

    with open(LATEST_POST_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    success = post_to_bluesky_from_blogger(
        blogger_url=data.get("blogger_url"),
        article_title=data.get("article_title"),
        theme_obj=data.get("theme_obj"),
        items=data.get("items", [])
    )
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
