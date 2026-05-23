"""End-to-end demo script - runs the full pipeline offline using FakeVLM.

Walks through every layer of the system without contacting a real AI
provider:

1. Repository initialisation.
2. Lost-item registration (image -> VLM -> embed -> database).
3. Found-item registration.
4. Top-k match retrieval.
5. Cost report.

No API keys are required: :class:`FakeVLM` and :class:`FakeEmbedder`
from :mod:`tests.fakes` stand in for the real providers.

Usage::

    python scripts/demo.py [--db PATH]

A fresh SQLite database is created for each demo run, in-memory by default.
"""

from __future__ import annotations

import argparse
import asyncio
import struct
import sys
import tempfile
import zlib
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import settings
from src.core.matcher import find_matches
from src.models import Item
from src.services.ai_service import (
    clear_embed_cache,
    describe_item_async,
    embed_async,
)
from src.services.cost_meter import get_cost_meter
from src.storage.sqlite_repo import SQLiteRepository


def _make_png(width: int = 2, height: int = 2, color: tuple = (128, 64, 32)) -> bytes:
    """Return the raw bytes of a tiny solid-colour PNG.

    Generating PNGs by hand avoids a Pillow dependency for the demo.

    Args:
        width: Pixel width.
        height: Pixel height.
        color: ``(R, G, B)`` tuple with values in ``[0, 255]``.

    Returns:
        Bytes of a valid single-channel-true-colour PNG file.
    """
    r, g, b = color
    raw = b"".join(b"\x00" + bytes([r, g, b] * width) for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        """Pack a length/tag/data/CRC PNG chunk."""
        c = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", c)

    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat_data = zlib.compress(raw)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr_data)
        + chunk(b"IDAT", idat_data)
        + chunk(b"IEND", b"")
    )


def _section(title: str) -> None:
    """Print a centred section banner to the terminal."""
    width = 60
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)


async def run_demo(db_path: str) -> None:
    """Drive the full demo from registration through cost reporting.

    Args:
        db_path: SQLite path or ``":memory:"`` for the demo database.
    """
    _section("Smart Lost & Found - End-to-End Demo")
    print(f"Database : {db_path}")
    print(f"Provider : {settings.LLM_PROVIDER} / {settings.LLM_MODEL}")

    from tests.fakes import FakeEmbedder, FakeVLM

    fake_vlm = FakeVLM()
    fake_embedder = FakeEmbedder()
    clear_embed_cache()

    repo = SQLiteRepository(db_path)
    await repo.initialize()

    try:
        _section("1. Register a LOST item")

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(_make_png(color=(0, 0, 128)))
            lost_img = f.name

        filename_lost = repo.save_image(Path(lost_img).read_bytes(), "dark_blue_bag.png")
        stored_lost = str(Path(settings.IMAGES_DIR) / filename_lost)

        desc_lost = await describe_item_async(
            stored_lost, "navy backpack with laptop", vlm=fake_vlm
        )
        vec_lost = await embed_async(desc_lost.to_search_text(), embedder=fake_embedder)

        lost_item = await repo.insert_item(
            Item(
                status="lost",
                filename=filename_lost,
                original_name="dark_blue_bag.png",
                user_text="navy backpack with laptop",
                vlm_description=desc_lost.to_dict(),
                embedding=vec_lost.tolist(),
            )
        )
        print(f"  Registered lost item   -> ID={lost_item.id}")
        print(f"  VLM class              : {desc_lost.object_class}")
        print(f"  Colors                 : {desc_lost.colors}")
        if desc_lost.brand:
            print(f"  Brand                  : {desc_lost.brand}")

        _section("2. Register two FOUND items")

        for i, (color, label, txt) in enumerate(
            [
                ((0, 0, 200), "blue_wallet.png", "blue wallet"),
                ((200, 0, 0), "red_phone.png", "red smartphone"),
            ],
            start=1,
        ):
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(_make_png(color=color))
                img_path = f.name

            filename_f = repo.save_image(Path(img_path).read_bytes(), label)
            stored_f = str(Path(settings.IMAGES_DIR) / filename_f)

            desc_f = await describe_item_async(stored_f, txt, vlm=fake_vlm)
            vec_f = await embed_async(desc_f.to_search_text(), embedder=fake_embedder)

            found_item = await repo.insert_item(
                Item(
                    status="found",
                    filename=filename_f,
                    original_name=label,
                    user_text=txt,
                    vlm_description=desc_f.to_dict(),
                    embedding=vec_f.tolist(),
                )
            )
            print(
                f"  [{i}] Registered found item -> ID={found_item.id}  "
                f"class={desc_f.object_class}"
            )

        _section("3. Find top-3 matches for the LOST item")

        fresh_lost = await repo.get_item(lost_item.id)
        matches = await find_matches(fresh_lost, repo, k=3)

        if not matches:
            print("  (no found items to match against)")
        else:
            for rank, m in enumerate(matches, start=1):
                print(f"  #{rank}  ID={m.candidate_id}  score={m.score:.4f}  {m.reason}")

        _section("4. All registered items")

        all_items = await repo.list_items(None)
        print(f"  {'ID':<6} {'Status':<8} {'Class':<20} {'Original Name'}")
        print("  " + "-" * 55)
        for it in all_items:
            cls = (it.vlm_description or {}).get("object_class", "-")
            print(f"  {it.id!s:<6} {it.status:<8} {cls:<20} {it.original_name or '-'}")

        _section("5. Cost Report")
        try:
            print(get_cost_meter().report())
        except Exception as exc:
            print(f"  (cost report unavailable: {exc})")

        _section("Demo complete")
        print("  All phases passed successfully.\n")

    finally:
        await repo.close()


def main() -> None:
    """Parse CLI args and execute :func:`run_demo`."""
    parser = argparse.ArgumentParser(description="Smart Lost & Found end-to-end demo")
    parser.add_argument(
        "--db",
        default=":memory:",
        help="SQLite path (default: in-memory, no file created)",
    )
    args = parser.parse_args()
    asyncio.run(run_demo(args.db))


if __name__ == "__main__":
    main()
