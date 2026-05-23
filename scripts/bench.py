"""Sequential vs. concurrent registration benchmark.

Measures wall-clock time to register N items one at a time and then
again concurrently (bounded by ``SEMAPHORE_LIMIT``). Prints a formatted
table and optionally writes it to a file.

By default :class:`FakeVLM` and :class:`FakeEmbedder` stand in for the
real providers so the benchmark runs offline without API keys. Pass
``--live`` to exercise the configured providers end-to-end.

Usage::

    python scripts/bench.py
    python scripts/bench.py --n 5 --mode sequential
    python scripts/bench.py --n 20 --live
    python scripts/bench.py --output artefacts/bench_results.txt
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _load_fake_providers():
    """Return the :class:`FakeVLM` and :class:`FakeEmbedder` classes."""
    from tests.fakes import FakeEmbedder, FakeVLM

    return FakeVLM, FakeEmbedder


async def _register_sequentially(
    image_files,
    status,
    repo,
    fake_vlm=None,
    fake_embedder=None,
):
    """Register images one at a time and return the elapsed seconds.

    Args:
        image_files: List of ``(bytes, filename)`` tuples.
        status: ``"lost"`` or ``"found"``.
        repo: Active repository.
        fake_vlm: Optional fake VLM injected for offline runs.
        fake_embedder: Optional fake embedder for offline runs.

    Returns:
        Wall-clock duration in seconds.
    """
    from src.models import Item
    from src.services.ai_service import (
        clear_embed_cache,
        describe_item_async,
        embed_async,
    )

    clear_embed_cache()
    start = time.perf_counter()

    for data, name in image_files:
        filename = repo.save_image(data, name)
        image_path = str(Path("data/images") / filename)
        desc = await describe_item_async(image_path, "", vlm=fake_vlm)
        vec = await embed_async(desc.to_search_text(), embedder=fake_embedder)
        item = Item(
            status=status,
            filename=filename,
            original_name=name,
            vlm_description=desc.to_dict(),
            embedding=vec.tolist(),
        )
        await repo.insert_item(item)

    return time.perf_counter() - start


async def _register_concurrently(
    image_files,
    status,
    repo,
    fake_vlm=None,
    fake_embedder=None,
):
    """Register images concurrently and return the elapsed seconds.

    When fakes are supplied the service-layer functions are temporarily
    rebound to versions that thread the fakes through; this keeps the
    benchmark from contacting any real provider while still exercising
    :func:`register_batch` and the semaphore.

    Args:
        image_files: List of ``(bytes, filename)`` tuples.
        status: ``"lost"`` or ``"found"``.
        repo: Active repository.
        fake_vlm: Optional fake VLM for offline runs.
        fake_embedder: Optional fake embedder for offline runs.

    Returns:
        Wall-clock duration in seconds.
    """
    from src.concurrency.pipeline import register_batch
    from src.services.ai_service import clear_embed_cache

    clear_embed_cache()
    start = time.perf_counter()

    if fake_vlm is not None or fake_embedder is not None:
        import src.services.ai_service as svc

        _orig_describe = svc.describe_item_async
        _orig_embed = svc.embed_async

        async def _fake_describe(path, text, *, vlm=None):
            """Forward the call with the test fake spliced in."""
            return await _orig_describe(path, text, vlm=fake_vlm or vlm)

        async def _fake_embed(text, *, embedder=None):
            """Forward the call with the test embedder spliced in."""
            return await _orig_embed(text, embedder=fake_embedder or embedder)

        svc.describe_item_async = _fake_describe
        svc.embed_async = _fake_embed
        try:
            await register_batch(image_files, status, repo)
        finally:
            svc.describe_item_async = _orig_describe
            svc.embed_async = _orig_embed
    else:
        await register_batch(image_files, status, repo)

    return time.perf_counter() - start


def _print_table(rows: list[dict], output_path: str | None = None) -> None:
    """Render the benchmark results as a Unicode ASCII table.

    Args:
        rows: One row per benchmark mode with ``mode``, ``n``, and
            ``time`` keys.
        output_path: When provided, also writes the rendered table to disk.
    """
    lines = [
        "",
        "+-----------------+------+-------------+---------+",
        "| Mode            |  N   |  Wall time  | Speedup |",
        "+-----------------+------+-------------+---------+",
    ]
    seq_time = next((r["time"] for r in rows if r["mode"] == "Sequential"), None)
    for r in rows:
        speedup = (
            f"{seq_time / r['time']:.1f}x"
            if seq_time and seq_time != r["time"]
            else "1.0x"
        )
        lines.append(
            f"| {r['mode']:<15} | {r['n']:>4} | {r['time']:>10.2f}s | {speedup:>7} |"
        )
    lines += [
        "+-----------------+------+-------------+---------+",
        "",
    ]
    table = "\n".join(lines)
    print(table)
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(table)
        print(f"Results saved to: {output_path}")


async def _run(args: argparse.Namespace) -> None:
    """Execute the benchmark according to the parsed CLI args.

    Collects sample images from ``data/samples/``, drives the requested
    benchmark mode(s) against a fresh in-memory database, and prints
    the resulting timing table.
    """
    from src.config import settings
    from src.storage.sqlite_repo import SQLiteRepository

    data_dirs = [
        _ROOT / "data" / "samples" / "lost",
        _ROOT / "data" / "samples" / "found",
    ]
    image_files: list[tuple[bytes, str]] = []
    for d in data_dirs:
        if d.exists():
            for p in sorted(d.glob("*.png"))[: args.n]:
                image_files.append((p.read_bytes(), p.name))
    image_files = image_files[: args.n]

    if not image_files:
        print(
            "Error: no sample images found. Run data/_make_samples.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    n = len(image_files)
    print(f"\nBenchmark: {n} images | semaphore={settings.SEMAPHORE_LIMIT} | mode={args.mode}")
    print(f"Provider: {'offline (FakeVLM)' if not args.live else 'live'}")

    fake_vlm, fake_embedder = (None, None) if args.live else _load_fake_providers()
    if fake_vlm:
        fake_vlm = fake_vlm()
        fake_embedder = fake_embedder()

    rows: list[dict] = []

    if args.mode in ("sequential", "both"):
        repo = SQLiteRepository(":memory:")
        await repo.initialize()
        t = await _register_sequentially(image_files, "lost", repo, fake_vlm, fake_embedder)
        await repo.close()
        print(f"Sequential: {t:.2f}s")
        rows.append({"mode": "Sequential", "n": n, "time": t})

    if args.mode in ("concurrent", "both"):
        repo = SQLiteRepository(":memory:")
        await repo.initialize()
        t = await _register_concurrently(image_files, "lost", repo, fake_vlm, fake_embedder)
        await repo.close()
        print(f"Concurrent: {t:.2f}s")
        rows.append({"mode": f"Concurrent (sem={settings.SEMAPHORE_LIMIT})", "n": n, "time": t})

    _print_table(rows, args.output)


def main() -> None:
    """CLI entry point: parse arguments and dispatch to :func:`_run`."""
    parser = argparse.ArgumentParser(description="Sequential vs. concurrent benchmark")
    parser.add_argument("--n", type=int, default=12, help="Number of images to register")
    parser.add_argument(
        "--mode",
        choices=["sequential", "concurrent", "both"],
        default="both",
        help="Which mode(s) to benchmark (default: both)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use real AI providers (requires .env with API keys)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional path to save results (e.g. artefacts/bench_results.txt)",
    )
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
