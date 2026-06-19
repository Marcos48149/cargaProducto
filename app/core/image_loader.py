import re
from pathlib import Path

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}

SKU_RE = re.compile(r'^([A-Z]{2,4}-[A-Z0-9]+)')


def extract_sku(filename):
    name = Path(filename).stem
    match = SKU_RE.match(name)
    if match:
        return match.group(1)
    return None


def scan_folder(folder_path):
    groups = {}
    folder = Path(folder_path)
    for f in folder.rglob('*'):
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
            sku = extract_sku(f.name)
            if sku:
                groups.setdefault(sku, []).append(str(f))
    return groups
