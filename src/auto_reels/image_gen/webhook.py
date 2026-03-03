from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from auto_reels.config import WEBHOOK_API_URL, WEBHOOK_API_KEY

MODEL = "nano_banana_2"
ASPECT_RATIO = "9:16"


def generate_character_images(characters_text: str, output_dir: Path) -> list[Path]:
    """Parse character prompts from characters.txt and generate images."""
    prompts = _parse_reference_prompts(characters_text)
    if not prompts:
        print("    [DEBUG] Nenhum prompt de referência encontrado")
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for i, (label, prompt) in enumerate(prompts, 1):
        output_path = output_dir / f"char{i}.png"
        print(f"    [INFO] Gerando: {label}")

        path = _generate_single(prompt, output_path)
        if path:
            results.append(path)
            print(f"    [GREEN] Salvo em {path}")
        else:
            print(f"    [RED] Falha ao gerar {label}")

    return results


def _generate_single(prompt: str, output_path: Path) -> Path | None:
    """Submit image generation, poll, download."""
    if not WEBHOOK_API_KEY:
        print("    [DEBUG] WEBHOOK_API_KEY não configurada")
        return None

    base = WEBHOOK_API_URL.rstrip("/")
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": WEBHOOK_API_KEY,
    }

    # 1. Submit
    try:
        resp = httpx.post(
            f"{base}/api/image/generate",
            headers=headers,
            json={"prompt": prompt, "model": MODEL, "aspect_ratio": ASPECT_RATIO},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        task_id = data["task_id"]
        print(f"    [DEBUG] task_id: {task_id}")
    except Exception as e:
        print(f"    [DEBUG] Submit error: {e}")
        return None

    # 2. Poll
    image_url = _poll_task(base, headers, task_id)
    if not image_url:
        return None

    # 3. Download — rewrite URL to use configured base (API may return localhost)
    #    and decode percent-encoded chars (server expects literal filenames)
    image_url = unquote(image_url)
    parsed = urlparse(image_url)
    parsed_base = urlparse(base)
    download_url = image_url.replace(
        f"{parsed.scheme}://{parsed.netloc}",
        f"{parsed_base.scheme}://{parsed_base.netloc}",
    )
    try:
        img_resp = httpx.get(download_url, headers=headers, timeout=60, follow_redirects=True)
        img_resp.raise_for_status()
        output_path.write_bytes(img_resp.content)
        return output_path
    except Exception as e:
        print(f"    [DEBUG] Download error: {e}")
        return None


def _poll_task(base: str, headers: dict, task_id: str, max_wait: int = 300) -> str | None:
    """Poll /api/status/{task_id} until completed."""
    elapsed = 0
    interval = 5

    while elapsed < max_wait:
        try:
            resp = httpx.get(f"{base}/api/status/{task_id}", headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            status = data.get("status")
            if status == "completed":
                results = data.get("results", [])
                if results:
                    return results[0]
                print(f"    [DEBUG] Completed but no results: {data}")
                return None

            if status == "failed":
                print(f"    [DEBUG] Failed: {data.get('error', data.get('error_detail'))}")
                return None

            print(f"    [DEBUG] Status: {status}")
            time.sleep(interval)
            elapsed += interval

        except Exception as e:
            print(f"    [DEBUG] Poll error: {e}")
            time.sleep(interval)
            elapsed += interval

    print(f"    [DEBUG] Timeout after {max_wait}s")
    return None


def _parse_reference_prompts(text: str) -> list[tuple[str, str]]:
    """Extract CHAR prompts from the reference section of characters.txt."""
    prompts = []
    # Match lines like "CHAR1 — NOME:" or "CHAR1 — NOME:\n" followed by the prompt
    pattern = r"(CHAR\d+\s*[—–-]\s*[^:]+):\s*\n?(Full body portrait.+?)(?=\n\nCHAR|\n\n===|\Z)"
    for match in re.finditer(pattern, text, re.DOTALL):
        label = match.group(1).strip()
        prompt = match.group(2).strip()
        prompts.append((label, prompt))
    return prompts
