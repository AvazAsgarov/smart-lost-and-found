"""Demo harness for the Topic 1 AI module.

Two modes:

  python demo_ai.py             # uses real providers from env (API keys required)
  python demo_ai.py --offline   # uses fake deterministic providers (no network)

The offline mode is what we use during grading to confirm the pipeline shape
works without burning API credits. Students should run both modes during
development.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from ai import describe_item, embed, top_k
from ai.providers.base import EmbeddingProvider, VLMProvider


class _OfflineVLM(VLMProvider):
    """Looks at the file name to pretend it identified the object."""

    def describe(self, image_path: str, prompt: str, *, json_schema=None) -> str:
        name = Path(image_path).stem.lower()
        if "umbrella" in name:
            payload = {
                "object_class": "umbrella",
                "colors": ["black"], "brand": None,
                "distinguishing_marks": [], "location_hints": [],
                "confidence": 0.8,
            }
        elif "backpack" in name:
            payload = {
                "object_class": "backpack",
                "colors": ["navy"], "brand": "JanSport",
                "distinguishing_marks": ["worn front zipper"], "location_hints": [],
                "confidence": 0.85,
            }
        elif "phone" in name:
            payload = {
                "object_class": "phone",
                "colors": ["black"], "brand": "Apple",
                "distinguishing_marks": ["cracked screen corner"], "location_hints": [],
                "confidence": 0.9,
            }
        elif "wallet" in name:
            payload = {
                "object_class": "wallet",
                "colors": ["brown"], "brand": None,
                "distinguishing_marks": ["leather, tri-fold"], "location_hints": [],
                "confidence": 0.75,
            }
        elif "keys" in name:
            payload = {
                "object_class": "key ring",
                "colors": ["silver"], "brand": None,
                "distinguishing_marks": ["3 keys, blue keychain"], "location_hints": [],
                "confidence": 0.8,
            }
        else:
            payload = {
                "object_class": "unknown object",
                "colors": [], "brand": None,
                "distinguishing_marks": [], "location_hints": [],
                "confidence": 0.3,
            }
        return json.dumps(payload)


class _OfflineEmbedder(EmbeddingProvider):
    """Hashes the text to a deterministic 64-D unit vector."""

    @property
    def dimension(self) -> int:
        return 64

    def embed(self, text: str) -> np.ndarray:
        if not text.strip():
            raise ValueError("Cannot embed empty string.")
        rng = np.random.default_rng(seed=abs(hash(text)) % (2**31))
        v = rng.standard_normal(64).astype(np.float32)
        v /= np.linalg.norm(v)
        return v


def run_demo(offline: bool) -> None:
    here = Path(__file__).parent
    lost_dir = here / "data" / "lost"
    found_dir = here / "data" / "found"

    if not lost_dir.exists() or not found_dir.exists():
        print(f"!! Sample data missing under {here / 'data'}", file=sys.stderr)
        print("   Expected lost/ and found/ subdirectories.", file=sys.stderr)
        sys.exit(2)

    vlm = _OfflineVLM() if offline else None
    embedder = _OfflineEmbedder() if offline else None

    def process(folder: Path) -> list[tuple[str, np.ndarray, str]]:
        out = []
        for img in sorted(folder.glob("*.png")) + sorted(folder.glob("*.jpg")):
            try:
                desc = describe_item(str(img), "", vlm=vlm)
                vec = embed(desc.to_search_text(), embedder=embedder)
                out.append((img.name, vec, desc.to_search_text()))
                print(f"  - {img.name}: {desc.object_class} ({desc.confidence:.2f})")
            except Exception as e:
                print(f"  ! {img.name} failed: {e}", file=sys.stderr)
        return out

    print(f"Processing LOST items (mode={'offline' if offline else 'online'})...")
    lost = process(lost_dir)
    print("\nProcessing FOUND items...")
    found = process(found_dir)

    if not lost or not found:
        print("\nNo items processed; nothing to match.", file=sys.stderr)
        sys.exit(2)

    query_name, query_vec, query_text = lost[0]
    cand_vecs = [v for (_, v, _) in found]
    cand_names = [n for (n, _, _) in found]
    matches = top_k(query_vec, cand_vecs, k=min(3, len(found)))

    print(f"\nTop matches for LOST item: {query_name!r}")
    print(f"  query: {query_text}")
    for m in matches:
        print(f"  -> {cand_names[m.candidate_id]}  score={m.score:+.3f}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--offline", action="store_true",
                   help="Use fake providers (no API keys, no network).")
    args = p.parse_args()
    run_demo(offline=args.offline)


if __name__ == "__main__":
    main()
