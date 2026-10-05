import threading
import queue
import random
import re

try:
    import markdown as md_lib
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False

from openrouter import OpenRouterClient
from wordpress import WordPressClient


def _build_toc(content: str, title: str = "Contents") -> str:
    """
    Finds h2/h3 headings, injects id attributes, prepends a TOC block.
    Returns modified content string.
    """
    headings = list(re.finditer(r'<(h[23])([^>]*)>(.*?)</h[23]>', content, re.IGNORECASE | re.DOTALL))
    if not headings:
        return content

    items_html = []
    offset = 0
    result = content

    for i, m in enumerate(headings):
        tag, attrs, text = m.group(1), m.group(2), m.group(3)
        clean = re.sub(r'<[^>]+>', '', text).strip()
        anchor = f"toc-{i}"
        replacement = f"<{tag}{attrs} id=\"{anchor}\">{text}</{tag}>"
        # Adjust for previous replacements shifting positions
        start = m.start() + offset
        end = m.end() + offset
        result = result[:start] + replacement + result[end:]
        offset += len(replacement) - (m.end() - m.start())
        items_html.append(f'<li><a href="#{anchor}">{clean}</a></li>')

    toc = (
        f'<div id="toc" style="background:#f9f9f9;border:1px solid #aaa;'
        f'display:table;margin-bottom:1em;padding:1em;width:350px;">'
        f'<p class="toctitle" style="font-weight:700;text-align:center;">{title}</p>'
        f'<ul class="toc_list">{"".join(items_html)}</ul>'
        f'</div>\n'
    )
    return toc + result


def _extract_title(content: str) -> str:
    # 1. Look for <h1> tag
    m = re.search(r'<h1[^>]*>(.*?)</h1>', content, re.IGNORECASE | re.DOTALL)
    if m:
        return re.sub(r'<[^>]+>', '', m.group(1)).strip()[:200]
    # 2. First non-empty line after stripping tags and markdown heading markers
    for line in content.splitlines():
        clean = re.sub(r'<[^>]+>', '', line).lstrip('#` ').strip()
        if clean:
            return clean[:200]
    return ""


class PostWorker(threading.Thread):
    def __init__(
        self,
        task_queue: queue.Queue,
        log_fn,
        on_task_done,
        on_worker_done,
        on_published,
        wp_cfgs: list[dict],
        or_cfg: dict,
        post_settings: dict,
        delay: float,
        to_html: bool,
    ):
        super().__init__(daemon=True)
        self.q = task_queue
        self.log = log_fn
        self.on_task_done = on_task_done
        self.on_worker_done = on_worker_done
        self.on_published = on_published
        self.or_cfg = or_cfg
        self.settings = post_settings
        self.delay = delay
        self.to_html = to_html
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            ai = OpenRouterClient(
                self.or_cfg["api_key"],
                self.or_cfg["model"],
            )

            while not self._stop.is_set():
                try:
                    task = self.q.get_nowait()
                except queue.Empty:
                    break

                tid = task["id"]
                wp_cfg = task["wp_cfg"]

                try:
                    if self.delay > 0:
                        self.log(f"[#{tid}] Задержка {self.delay}с...")
                        self._stop.wait(self.delay)
                        if self._stop.is_set():
                            self.q.task_done()
                            break

                    self.log(f"[#{tid}] Генерирую контент...")
                    content = ai.generate(task["prompt"])

                    # Strip ```html ... ``` wrapper if AI added it
                    content = re.sub(r'^```(?:html)?\s*\n', '', content.strip(), flags=re.IGNORECASE)
                    content = re.sub(r'\n```\s*$', '', content)

                    if self._stop.is_set():
                        self.log(f"[#{tid}] Остановлено — публикация пропущена")
                        continue

                    if self.to_html and HAS_MARKDOWN:
                        content = md_lib.markdown(content)

                    if self.settings.get("toc"):
                        content = _build_toc(content, self.settings.get("toc_title", "Contents"))

                    title_prompt = task["title_prompt"]
                    if title_prompt:
                        resolved = title_prompt.replace("{content}", content[:2000])
                        self.log(f"[#{tid}] Генерирую заголовок...")
                        title = ai.generate(resolved)
                        title = re.sub(r'<[^>]+>', '', title).strip().strip("\"'").split("\n")[0][:200]
                    else:
                        title = _extract_title(content) or f"Пост {tid}"

                    s = self.settings
                    cats = (
                        random.sample(s["categories"], min(s["cat_pick"], len(s["categories"])))
                        if s["categories"] and s["cat_pick"] > 0 else []
                    )
                    tags = (
                        random.sample(s["tags"], min(s["tag_pick"], len(s["tags"])))
                        if s["tags"] and s["tag_pick"] > 0 else []
                    )
                    comment = random.choice(s["comment_options"])

                    label = title[:60] + ("…" if len(title) > 60 else "")
                    self.log(f'[#{tid}] → {wp_cfg["url"]}: "{label}"')
                    self.log(f"[#{tid}]   Категории: {cats or '—'}  Теги: {tags or '—'}")

                    wp_client = WordPressClient(**wp_cfg)
                    try:
                        post_id = wp_client.new_post(
                            title=title,
                            content=content,
                            categories=cats or None,
                            tags=tags or None,
                            comment_status=comment,
                            post_status=s["post_status"],
                        )
                    except Exception as term_err:
                        if "taxonomy" in str(term_err).lower() or "term" in str(term_err).lower():
                            self.log(f"[#{tid}] ⚠ Нет прав на категории/теги — публикую без них")
                            post_id = wp_client.new_post(
                                title=title,
                                content=content,
                                comment_status=comment,
                                post_status=s["post_status"],
                            )
                        else:
                            raise
                    try:
                        link = wp_client.get_link(post_id)
                    except Exception:
                        link = f"{wp_cfg['url']}/?p={post_id}"
                    self.log(f"[#{tid}] ✓ Опубликовано! ID: {post_id}")
                    self.log(f"[#{tid}]   {link}")
                    self.on_published(wp_cfg["url"], post_id, title, link)

                except Exception as exc:
                    self.log(f"[#{tid}] ✗ Ошибка: {exc}")

                finally:
                    self.q.task_done()
                    self.on_task_done()

        finally:
            self.on_worker_done()
