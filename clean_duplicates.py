import re

import os, sys, base64, json, tempfile, time
from playwright.sync_api import sync_playwright

def clean_duplicates():
    blog_id = os.environ.get("BLOGGER_BLOG_ID")
    session_b64 = os.environ.get("BLOGGER_SESSION_B64")
    decoded = base64.b64decode(session_b64).decode("utf-8")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, suffix=".json") as tf:
        tf.write(decoded)
        sess_file = tf.name

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state=sess_file, viewport={"width": 1920, "height": 1080})
            page = context.new_page()
            page.goto(f"https://draft.blogger.com/blog/posts/{blog_id}", wait_until="networkidle", timeout=35000)
            time.sleep(3)

            deleted_total = 0
            for loop_pass in range(40):
                rows = page.locator("div.rb4Lrd").all()
                if not rows:
                    break
                seen = set()
                dup_row = None
                dup_title = None
                for r in rows:
                    txt = r.inner_text().split("\n")[0].strip()
                    if not txt or "(無題)" in txt:
                        continue
                    if txt in seen:
                        dup_row = r
                        dup_title = txt
                        break
                    else:
                        seen.add(txt)

                if not dup_row:
                    print(f"Pass {loop_pass+1}: No more duplicates detected! Total unique posts remaining: {len(seen)}")
                    break

                print(f"Deleting duplicate: '{dup_title[:25]}...'")
                dup_row.hover()
                time.sleep(0.5)
                trash_btn = dup_row.locator('[aria-label="この投稿をゴミ箱に移動"], [aria-label="この投稿を破棄"]').first
                if trash_btn.is_visible(timeout=2000):
                    trash_btn.click(force=True)
                else:
                    trash_btn.dispatch_event('click')
                time.sleep(1.0)
                
                # Click confirmation
                conf = page.locator('div[role="alertdialog"] div[role="button"], div[role="dialog"] div[role="button"]').filter(has_text=re.compile(r'ゴミ箱|破棄|削除|確定|確認')).first
                if conf.is_visible(timeout=3000):
                    conf.click(force=True)
                else:
                    page.keyboard.press('Enter')
                time.sleep(3.0)
                deleted_total += 1

            print(f"=== Successfully deleted {deleted_total} duplicates! ===")
    finally:
        if os.path.exists(sess_file):
            os.remove(sess_file)

if __name__ == '__main__':
    clean_duplicates()
