import os, sys, base64, json, tempfile, time
from playwright.sync_api import sync_playwright

def clean_duplicates():
    blog_id = os.environ.get("BLOGGER_BLOG_ID")
    session_b64 = os.environ.get("BLOGGER_SESSION_B64")
    if not blog_id or not session_b64:
        print("Missing credentials.")
        return

    decoded = base64.b64decode(session_b64).decode("utf-8")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, suffix=".json") as tf:
        tf.write(decoded)
        sess_file = tf.name

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state=sess_file, viewport={"width": 1920, "height": 1080})
            page = context.new_page()

            page.goto(f"https://draft.blogger.com/blog/posts/{blog_id}", wait_until="networkidle", timeout=30000)
            time.sleep(3)

            # Look through posts list and identify duplicates
            # Each post row in Blogger posts table:
            # Check row titles, if title already seen, trash the duplicate!
            deleted_count = 0
            for pass_idx in range(25):
                rows_data = page.evaluate('''() => {
                    const rows = Array.from(document.querySelectorAll('div.rb4Lrd'));
                    return rows.map((r, index) => {
                        const titleEl = r.querySelector('div.aIe0cc, a.mU1nid, span.S6M6ae, div[role="link"]');
                        const title = titleEl ? titleEl.innerText.trim() : r.innerText.split('\\n')[0].trim();
                        return { index, title };
                    });
                }''')
                
                seen_titles = set()
                duplicate_indices = []
                for item in rows_data:
                    t = item['title']
                    if not t or '(無題)' in t:
                        continue
                    if t in seen_titles:
                        duplicate_indices.append(item['index'])
                    else:
                        seen_titles.add(t)

                if not duplicate_indices:
                    print("No more duplicates found on page.")
                    break

                print(f"Pass {pass_idx+1}: Found duplicate indices to remove: {duplicate_indices}")
                # Delete the first duplicate found
                target_idx = duplicate_indices[0]
                clicked = page.evaluate('''(idx) => {
                    const rows = Array.from(document.querySelectorAll('div.rb4Lrd'));
                    if (rows[idx]) {
                        const trash = rows[idx].querySelector('[aria-label="この投稿をゴミ箱に移動"], [aria-label="この投稿を破棄"], [aria-label*="ゴミ箱"]');
                        if (trash) {
                            trash.click();
                            return true;
                        }
                    }
                    return false;
                }''', target_idx)

                if clicked:
                    time.sleep(1)
                    page.evaluate('''() => {
                        const dialog = document.querySelector('div[role="alertdialog"], div[role="dialog"]');
                        if (dialog) {
                            const b = Array.from(dialog.querySelectorAll('div[role="button"], button')).find(x => 
                                x.innerText.includes('ゴミ箱') || x.innerText.includes('破棄') || x.innerText.includes('削除')
                            );
                            if (b) b.click();
                        }
                    }''')
                    time.sleep(3)
                    deleted_count += 1
                    print(f"Successfully deleted duplicate #{deleted_count}")
                else:
                    break

            print(f"Total duplicates cleaned: {deleted_count}")
    finally:
        if os.path.exists(sess_file):
            os.remove(sess_file)

if __name__ == "__main__":
    clean_duplicates()
