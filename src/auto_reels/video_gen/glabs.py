from __future__ import annotations

import base64
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)

from auto_reels.config import WEBHOOK_API_URL, WEBHOOK_API_KEY

MODEL = "veo_31_fast_relaxed"
ASPECT_RATIO = "9:16"
POLL_TIMEOUT = 600
POLL_INTERVAL = 10
CONCURRENCY = 6

console = Console()


def generate_videos(
    veo_prompts_path: Path,
    output_dir: Path,
    image_paths: list[Path] | None = None,
    model: str = MODEL,
) -> list[Path]:
    """Generate Veo3 clips via G-Labs API, up to CONCURRENCY at a time."""
    if not WEBHOOK_API_KEY:
        console.print("  [red]WEBHOOK_API_KEY não configurada[/red]")
        return []

    text = veo_prompts_path.read_text(encoding="utf-8")
    prompts = _parse_veo_prompts(text)
    if not prompts:
        console.print("  [red]Nenhum prompt encontrado em veo_prompts.txt[/red]")
        return []

    output_dir.mkdir(parents=True, exist_ok=True)

    # Build char key → base64 map
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
    results: dict[int, Path | None] = {}

    # Check server capacity before starting
    try:
        health = httpx.get(f"{base}/api/health", timeout=5).json()
        tasks_running = health.get("tasks_running", "?")
        tasks_pending = health.get("tasks_pending", "?")
        console.print(
            f"  [dim]G-Labs health:[/dim] "
            f"[yellow]running={tasks_running}[/yellow]  "
            f"[dim]pending={tasks_pending}[/dim]"
        )
    except Exception:
        console.print("  [yellow]G-Labs health check falhou[/yellow]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(bar_width=30),
        MofNCompleteColumn(),
        TextColumn("[dim]{task.fields[status]}[/dim]"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        overall = progress.add_task(
            f"[cyan]Clipes Veo3[/cyan]",
            total=len(prompts),
            status=f"0/{len(prompts)} concluídos  |  {CONCURRENCY} paralelos",
        )

        # One sub-task row per concurrent slot
        slot_tasks: dict[int, TaskID] = {}
        for slot in range(min(CONCURRENCY, len(prompts))):
            tid = progress.add_task(
                f"  [dim]slot {slot + 1:02d}[/dim]",
                total=None,
                status="aguardando...",
            )
            slot_tasks[slot] = tid

        completed_count = 0
        failed_count = 0

        with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = {
                pool.submit(
                    _generate_one,
                    prompt_info, char_b64, base, headers, output_dir, model, progress,
                    slot_tasks.get(idx % CONCURRENCY),
                ): prompt_info["number"]
                for idx, prompt_info in enumerate(prompts)
            }

            for future in as_completed(futures):
                num = futures[future]
                result = future.result()
                results[num] = result

                if result:
                    completed_count += 1
                else:
                    failed_count += 1

                # Refresh server concurrency info
                try:
                    h = httpx.get(f"{base}/api/health", timeout=3).json()
                    srv = f"srv running={h.get('tasks_running','?')} pending={h.get('tasks_pending','?')}"
                except Exception:
                    srv = ""

                status_parts = [f"[green]{completed_count} ok[/green]"]
                if failed_count:
                    status_parts.append(f"[red]{failed_count} falhou[/red]")
                remaining = len(prompts) - completed_count - failed_count
                if remaining:
                    status_parts.append(f"{remaining} restantes")
                if srv:
                    status_parts.append(f"[dim]{srv}[/dim]")
                progress.update(overall, advance=1, status="  |  ".join(status_parts))

        # Hide slot rows
        for tid in slot_tasks.values():
            progress.update(tid, visible=False)

    downloaded = [results[p["number"]] for p in prompts if results.get(p["number"])]
    console.print(f"  [bold green]{len(downloaded)}/{len(prompts)} clipes gerados[/bold green]" +
                  (f"  [red]({failed_count} falharam)[/red]" if failed_count else ""))
    return downloaded


def _generate_one(
    prompt_info: dict,
    char_b64: dict[str, str],
    base: str,
    headers: dict,
    output_dir: Path,
    model: str,
    progress: Progress,
    slot_task: TaskID | None,
) -> Path | None:
    num = prompt_info["number"]
    scene_chars = _parse_scene_chars(prompt_info["characters"])
    ref_images = [char_b64[c] for c in scene_chars if c in char_b64]
    mode = "components" if ref_images else "text_to_video"

    def _upd(status: str):
        if slot_task is not None:
            chars_str = f"[{', '.join(scene_chars)}]" if scene_chars else "[]"
            progress.update(
                slot_task,
                description=f"  [yellow]#{num:03d}[/yellow] {chars_str}",
                status=status,
            )

    _upd("enviando...")

    payload: dict = {
        "prompt": prompt_info["prompt"],
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
    except Exception as e:
        _upd(f"[red]erro: {e}[/red]")
        return None

    # Poll
    elapsed = 0
    while elapsed < POLL_TIMEOUT:
        try:
            resp = httpx.get(f"{base}/api/status/{task_id}", headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")

            if status == "completed":
                results = data.get("results", [])
                if not results:
                    _upd("[red]completed sem resultado[/red]")
                    return None
                _upd("baixando...")
                video_path = output_dir / f"scene_{num:03d}.mp4"
                result = _download(base, headers, results[0], video_path)
                _upd("[green]concluído[/green]" if result else "[red]falha no download[/red]")
                return result

            if status == "failed":
                _upd(f"[red]falhou[/red]")
                return None

            _upd(f"gerando... {elapsed}s")
        except Exception:
            _upd(f"[yellow]poll error {elapsed}s[/yellow]")

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    _upd("[red]timeout[/red]")
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
    except Exception:
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
