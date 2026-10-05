import json
import os
import re

try:
    import markdown as _md
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False

_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_DIR, "config.json")
EXAMPLE_CONFIG_FILE = os.path.join(_DIR, "config.example.json")

FALLBACK_MODELS = ["Загрузка моделей..."]


def load_config() -> dict:
    path = CONFIG_FILE if os.path.exists(CONFIG_FILE) else EXAMPLE_CONFIG_FILE
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(data: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def parse_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


_DOMAIN_RE = re.compile(
    r'\b([a-zA-Z0-9][a-zA-Z0-9\-]*(?:\.[a-zA-Z0-9][a-zA-Z0-9\-]*)*\.[a-zA-Z]{2,})\b'
)


def extract_domains(text: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for d in _DOMAIN_RE.findall(text):
        d = d.lower().rstrip(".")
        parts = d.split(".")
        if all(p.isdigit() for p in parts):  # skip IPs
            continue
        if len(parts) < 2 or len(parts[-1]) < 2:
            continue
        if d not in seen:
            seen.add(d)
            result.append(d)
    return result


def extract_variables(text: str) -> list[str]:
    """{variable} placeholders, excluding reserved {content}."""
    seen: set[str] = set()
    result: list[str] = []
    for v in re.findall(r'\{([^}]+)\}', text):
        if v != "content" and v not in seen:
            seen.add(v)
            result.append(v)
    return result


def parse_sites(text: str) -> list[dict]:
    """Parse lines of 'https://example.invalid:login:password' into wp_cfg dicts."""
    sites = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        proto = "https"
        if "://" in line:
            proto, rest = line.split("://", 1)
        else:
            rest = line
        # rsplit from right so password may contain colons
        parts = rest.rsplit(":", 2)
        if len(parts) != 3:
            continue
        domain, username, password = parts
        sites.append({"url": f"{proto}://{domain}", "username": username, "password": password})
    return sites
