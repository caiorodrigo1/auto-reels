from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from auto_reels.config import WEBHOOK_API_URL, WEBHOOK_API_KEY

MODEL = "nano_banana_2"
ASPECT_RATIO = "9:16"

console = Console(force_terminal=True)


MAX_PARALLEL = 10


def generate_character_images(characters_text: str, output_dir: Path) -> list[Path]:
    """Parse character prompts from characters.txt and generate images.

    Submits up to MAX_PARALLEL images concurrently to the webhook API.
    """
    prompts = _parse_reference_prompts(characters_text)
    if not prompts:
        console.print("  [yellow]Nenhum prompt de referência encontrado[/yellow]")
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[Path | None] = [None] * len(prompts)

    base = WEBHOOK_API_URL.rstrip("/")
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": WEBHOOK_API_KEY,
    }

    with Progress(
        SpinnerColumn(),
        TextColumn("  [bold]{task.description}"),
        BarColumn(bar_width=25),
        MofNCompleteColumn(),
        TextColumn("[dim]{task.fields[status]}[/dim]"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        overall = progress.add_task(
            "[cyan]Imagens[/cyan]",
            total=len(prompts),
            status=f"0/{len(prompts)} geradas",
        )

        ok = 0
        failed = 0

        # Process in batches of MAX_PARALLEL
        for batch_start in range(0, len(prompts), MAX_PARALLEL):
            batch = prompts[batch_start : batch_start + MAX_PARALLEL]
            batch_indices = list(range(batch_start, batch_start + len(batch)))

            # 1. Submit all in batch
            pending: list[tuple[int, str, str, Path]] = []  # (index, label, task_id, output_path)
            for offset, (label, prompt) in enumerate(batch):
                idx = batch_indices[offset]
                output_path = output_dir / f"char{idx + 1}.png"
                try:
                    resp = httpx.post(
                        f"{base}/api/image/generate",
                        headers=headers,
                        json={"prompt": prompt, "model": MODEL, "aspect_ratio": ASPECT_RATIO},
                        timeout=30,
                    )
                    resp.raise_for_status()
                    task_id = resp.json()["task_id"]
                    pending.append((idx, label, task_id, output_path))
                    console.print(f"    [dim]Enviado: {label}[/dim]")
                except Exception as e:
                    console.print(f"    [red]Erro ao enviar {label}: {e}[/red]")
                    failed += 1
                    progress.update(overall, advance=1)

            if not pending:
                continue

            console.print(f"  [cyan]Aguardando {len(pending)} imagens em paralelo...[/cyan]")

            # 2. Poll all pending tasks until all complete
            remaining_tasks = {task_id: (idx, label, output_path) for idx, label, task_id, output_path in pending}
            elapsed = 0
            interval = 5
            max_wait = 300

            while remaining_tasks and elapsed < max_wait:
                time.sleep(interval)
                elapsed += interval

                done_ids = []
                for task_id, (idx, label, output_path) in remaining_tasks.items():
                    try:
                        resp = httpx.get(f"{base}/api/status/{task_id}", headers=headers, timeout=15)
                        resp.raise_for_status()
                        data = resp.json()
                        status = data.get("status")

                        if status == "completed":
                            image_results = data.get("results", [])
                            if image_results:
                                # Download
                                image_url = unquote(image_results[0])
                                parsed = urlparse(image_url)
                                parsed_base = urlparse(base)
                                download_url = image_url.replace(
                                    f"{parsed.scheme}://{parsed.netloc}",
                                    f"{parsed_base.scheme}://{parsed_base.netloc}",
                                )
                                img_resp = httpx.get(download_url, headers=headers, timeout=60, follow_redirects=True)
                                img_resp.raise_for_status()
                                output_path.write_bytes(img_resp.content)
                                results[idx] = output_path
                                ok += 1
                                console.print(f"    [green]OK: {label}[/green]")
                            else:
                                failed += 1
                                console.print(f"    [red]Sem resultado: {label}[/red]")
                            done_ids.append(task_id)
                            progress.update(overall, advance=1)

                        elif status == "failed":
                            failed += 1
                            done_ids.append(task_id)
                            progress.update(overall, advance=1)
                            console.print(f"    [red]Falhou: {label}[/red]")

                    except Exception:
                        pass  # retry next cycle

                for tid in done_ids:
                    remaining_tasks.pop(tid)

                if remaining_tasks:
                    progress.update(
                        overall,
                        status=f"[green]{ok} ok[/green] | {len(remaining_tasks)} gerando... {elapsed}s",
                    )

            # Timeout stragglers
            for task_id, (idx, label, _) in remaining_tasks.items():
                failed += 1
                progress.update(overall, advance=1)
                console.print(f"    [red]Timeout: {label}[/red]")

        progress.update(overall, status=f"[green]{ok} ok[/green]" + (f" | [red]{failed} falhou[/red]" if failed else ""))

    valid = [r for r in results if r is not None]
    console.print(
        f"  [bold green]{len(valid)}/{len(prompts)} imagens geradas[/bold green]"
        + (f"  [red]({failed} falharam)[/red]" if failed else "")
    )
    return valid


def _generate_single(
    prompt: str,
    output_path: Path,
    progress: Progress | None = None,
    task_id_prog=None,
) -> Path | None:
    """Submit image generation, poll, download."""
    if not WEBHOOK_API_KEY:
        return None

    def _upd(status: str):
        if progress is not None and task_id_prog is not None:
            progress.update(task_id_prog, status=status)

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
    except Exception as e:
        _upd(f"[red]erro: {e}[/red]")
        return None

    # 2. Poll
    image_url = _poll_task(base, headers, task_id, progress=progress, task_id_prog=task_id_prog)
    if not image_url:
        return None

    # 3. Download
    _upd("baixando...")
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
        _upd(f"[red]download erro: {e}[/red]")
        return None


def _poll_task(
    base: str,
    headers: dict,
    task_id: str,
    max_wait: int = 300,
    progress: Progress | None = None,
    task_id_prog=None,
) -> str | None:
    """Poll /api/status/{task_id} until completed."""
    elapsed = 0
    interval = 5

    def _upd(status: str):
        if progress is not None and task_id_prog is not None:
            progress.update(task_id_prog, status=status)

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
                _upd("[red]completed sem resultado[/red]")
                return None

            if status == "failed":
                _upd(f"[red]falhou[/red]")
                return None

            _upd(f"gerando... {elapsed}s")
            time.sleep(interval)
            elapsed += interval

        except Exception as e:
            _upd(f"[yellow]poll error {elapsed}s[/yellow]")
            time.sleep(interval)
            elapsed += interval

    _upd("[red]timeout[/red]")
    return None


def _parse_reference_prompts(text: str) -> list[tuple[str, str]]:
    """Extract CHAR prompts from the reference section of characters.txt."""
    prompts = []
    pattern = r"(CHAR\d+\s*[—–-]\s*[^:]+):\s*\n?(Full body portrait.+?)(?=\n\nCHAR|\n\n===|\Z)"
    for match in re.finditer(pattern, text, re.DOTALL):
        label = match.group(1).strip()
        prompt = match.group(2).strip()
        prompts.append((label, prompt))
    return prompts
