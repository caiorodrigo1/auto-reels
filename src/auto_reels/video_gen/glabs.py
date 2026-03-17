from __future__ import annotations

import base64
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from auto_reels.config import WEBHOOK_API_URL, WEBHOOK_API_KEY

MODEL = "veo_31_fast_relaxed"
ASPECT_RATIO = "9:16"
POLL_TIMEOUT = 600  # 10 min max per clip
POLL_INTERVAL = 10
CONCURRENCY = 6


def generate_videos(
    veo_prompts_path: Path,
    output_dir: Path,
    image_paths: list[Path] | None = None,
    model: str = MODEL,
) -> list[Path]:
    """Generate Veo3 clips via G-Labs API, up to CONCURRENCY at a time."""
    if not WEBHOOK_API_KEY:
        print("    [ERROR] WEBHOOK_API_KEY não configurada")
        return []

    text = veo_prompts_path.read_text(encoding="utf-8")
    prompts = _parse_veo_prompts(text)
    if not prompts:
        print("    [ERROR] Nenhum prompt encontrado em veo_prompts.txt")
        return []

    print(f"    [INFO] {len(prompts)} prompts encontrados (concorrência: {CONCURRENCY})")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build char key → base64 map from image files (char1.png → "Char1")
    char_b64: dict[str, str] = {}
    for img_path in (image_paths or []):
        if not img_path.exists():
            continue
        m = re.match(r"(char\d+)", img_path.name, re.IGNORECASE)
        if m:
            key = m.group(1).capitalize()
            char_b64[key] = base64.b64encode(img_path.read_bytes()).decode()

    base = WEBHOOK_API_URL.rstrip("/")
    headers = {"Content-Type": "application/json", "X-API-Key": WEBHOOK_API_KEY}

    # results dict: num → Path | None (preserves order)
    results: dict[int, Path | None] = {}

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = {
            pool.submit(_generate_one, prompt_info, char_b64, base, headers, output_dir, model): prompt_info["number"]
            for prompt_info in prompts
        }
        for future in as_completed(futures):
            num = futures[future]
            results[num] = future.result()

    # Return in prompt order
    downloaded = [results[p["number"]] for p in prompts if results.get(p["number"])]
    print(f"    [INFO] {len(downloaded)}/{len(prompts)} clipes gerados")
    return downloaded


def _generate_one(
    prompt_info: dict,
    char_b64: dict[str, str],
    base: str,
    headers: dict,
    output_dir: Path,
    model: str,
) -> Path | None:
    num = prompt_info["number"]
    prompt_text = prompt_info["prompt"]
    scene_chars = _parse_scene_chars(prompt_info["characters"])
    ref_images = [char_b64[c] for c in scene_chars if c in char_b64]

    mode = "components" if ref_images else "text_to_video"
    print(f"    [INFO] Prompt {num:03d} ({prompt_info['time_range']}) mode={mode} chars={scene_chars}")

    payload: dict = {
        "prompt": prompt_text,
        "model": model,
        "mode": mode,
        "aspect_ratio": ASPECT_RATIO,
        "resolution": ["720p"],
    }
    if ref_images:
        payload["reference_images"] = ref_images

    try:
        resp = httpx.post(f"{base}/api/video/generate", headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        task_id = resp.json()["task_id"]
        print(f"    [DEBUG] Prompt {num:03d} task_id: {task_id}")
    except Exception as e:
        print(f"    [ERROR] Submit error prompt {num:03d}: {e}")
        return None

    video_url = _poll(base, headers, task_id, num)
    if not video_url:
        print(f"    [ERROR] Geração falhou para prompt {num:03d}")
        return None

    video_path = output_dir / f"scene_{num:03d}.mp4"
    result = _download(base, headers, video_url, video_path)
    if result:
        print(f"    [OK] Prompt {num:03d} salvo: {result.name}")
    else:
        print(f"    [ERROR] Falha ao baixar vídeo {num:03d}")
    return result


def _poll(base: str, headers: dict, task_id: str, num: int = 0) -> str | None:
    elapsed = 0
    while elapsed < POLL_TIMEOUT:
        try:
            resp = httpx.get(f"{base}/api/status/{task_id}", headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")

            if status == "completed":
                results = data.get("results", [])
                if results:
                    return results[0]
                print(f"    [DEBUG] Completed sem results: {data}")
                return None

            if status == "failed":
                print(f"    [DEBUG] Failed: {data.get('error', data.get('error_detail'))}")
                return None

            print(f"    [DEBUG] Prompt {num:03d} status: {status} ({elapsed}s)")
        except Exception as e:
            print(f"    [DEBUG] Poll error: {e}")

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    print(f"    [DEBUG] Timeout após {POLL_TIMEOUT}s")
    return None


def _download(base: str, headers: dict, url: str, output_path: Path) -> Path | None:
    url = unquote(url)
    parsed = urlparse(url)
    parsed_base = urlparse(base)
    download_url = url.replace(
        f"{parsed.scheme}://{parsed.netloc}",
        f"{parsed_base.scheme}://{parsed_base.netloc}",
    )
    try:
        resp = httpx.get(download_url, headers=headers, timeout=120, follow_redirects=True)
        resp.raise_for_status()
        output_path.write_bytes(resp.content)
        return output_path
    except Exception as e:
        print(f"    [DEBUG] Download error: {e}")
        return None


def _parse_veo_prompts(text: str) -> list[dict]:
    pattern = re.compile(
        r"PROMPT\s+(\d+)\s+\[([^\]]*)\]\s*\|\s*([\d:]+\s*-\s*[\d:]+)\s*:(.*)",
        re.DOTALL,
    )
    prompts = []
    for block in re.split(r"\n(?=PROMPT\s+\d)", text):
        m = pattern.match(block.strip())
        if m:
            prompts.append({
                "number": int(m.group(1)),
                "characters": m.group(2).strip(),
                "time_range": m.group(3).strip(),
                "prompt": m.group(4).strip(),
            })
    return prompts


def _parse_scene_chars(characters_str: str) -> list[str]:
    chars = re.split(r"\s*,\s*|\s+and\s+|\s+e\s+", characters_str)
    return [c.strip() for c in chars if c.strip()]
