#!/usr/bin/env python3
"""2D t-SNE of the paper library from filename metadata.

Writes embed.json. The map blends a joint embedding with one embedding per field
(journal, year, title, folder, authors) so the cloud can be pulled toward any of them.
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.manifold import TSNE

import paperdb

HERE = Path(__file__).resolve().parent
OUT = HERE / "embed.json"
STOP = {
    "the", "and", "for", "with", "from", "that", "this", "are", "was", "were",
    "not", "but", "its", "into", "via", "per", "between", "using", "based",
    "during", "without", "within", "across", "toward", "towards", "versus",
    "et", "al", "etal", "pdf", "fig", "figure", "supplement", "supplementary",
}


def tokens(text: str) -> list[str]:
    return [word for word in re.findall(r"[a-z]{3,}", text.lower()) if word not in STOP]


def one_hot(labels: list[str], minimum: int = 1) -> np.ndarray:
    counts = Counter(label for label in labels if label)
    columns = [label for label, count in counts.most_common() if count >= minimum]
    index = {label: i for i, label in enumerate(columns)}
    matrix = np.zeros((len(labels), max(1, len(columns))), dtype=np.float64)
    for row, label in enumerate(labels):
        slot = index.get(label)
        if slot is not None:
            matrix[row, slot] = 1.0
    return matrix


def multi_hot(rows: list[list[str]], minimum: int = 1, limit: int | None = None) -> np.ndarray:
    counts: Counter[str] = Counter()
    for labels in rows:
        counts.update(set(labels))
    ranked = [label for label, count in counts.most_common() if count >= minimum]
    if limit is not None:
        ranked = ranked[:limit]
    index = {label: i for i, label in enumerate(ranked)}
    matrix = np.zeros((len(rows), max(1, len(index))), dtype=np.float64)
    for row, labels in enumerate(rows):
        for label in set(labels):
            slot = index.get(label)
            if slot is not None:
                matrix[row, slot] = 1.0
    return matrix


def hash_block(texts: list[str], dims: int = 12) -> np.ndarray:
    matrix = np.zeros((len(texts), dims), dtype=np.float64)
    for row, text in enumerate(texts):
        if not text:
            continue
        for i, char in enumerate(text.lower()):
            matrix[row, (ord(char) * 13 + i * 7) % dims] += 1.0
        norm = np.linalg.norm(matrix[row])
        if norm:
            matrix[row] /= norm
    return matrix * 0.35


def scale_block(matrix: np.ndarray) -> np.ndarray:
    centered = matrix - matrix.mean(axis=0, keepdims=True)
    rms = float(np.sqrt((centered ** 2).mean()))
    if rms < 1e-8:
        return centered
    return centered / rms


def fit_tsne(matrix: np.ndarray) -> np.ndarray:
    samples = matrix.shape[0]
    perplexity = min(40, max(5, (samples - 1) // 3))
    options = dict(
        n_components=2,
        perplexity=perplexity,
        init="pca",
        learning_rate="auto",
        random_state=0,
        method="barnes_hut",
        verbose=1,
    )
    try:
        model = TSNE(max_iter=750, **options)
    except TypeError:
        model = TSNE(n_iter=750, **options)
    points = model.fit_transform(matrix)
    points -= points.mean(axis=0)
    points /= np.std(points) + 1e-8
    return points


def unstack(points: np.ndarray, keys: list[str], gap: float = 0.03, cap: float = 0.58) -> np.ndarray:
    """Turn a pile of identical papers into a disk, keeping the pile's center."""
    groups: dict[str, list[int]] = defaultdict(list)
    for index, key in enumerate(keys):
        groups[key].append(index)
    placed = points.copy()
    golden = math.pi * (3 - math.sqrt(5))
    for indexes in groups.values():
        count = len(indexes)
        if count < 2:
            continue
        cluster = points[indexes]
        distances = np.sqrt(((cluster - np.median(cluster, axis=0)) ** 2).sum(axis=1))
        center = cluster[np.argsort(distances)[: max(1, count // 2)]].mean(axis=0)
        radius = min(cap, gap * math.sqrt(count))
        for order, index in enumerate(indexes):
            angle = order * golden
            distance = radius * math.sqrt((order + 0.5) / count)
            placed[index, 0] = center[0] + math.cos(angle) * distance
            placed[index, 1] = center[1] + math.sin(angle) * distance
    return placed


def align(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Rotate a layout onto another so blends don't flip the cloud."""
    left = source - source.mean(axis=0)
    right = target - target.mean(axis=0)
    u, _, vt = np.linalg.svd(left.T @ right)
    rotation = u @ vt
    if np.linalg.det(rotation) < 0:
        vt = vt.copy()
        vt[-1] *= -1
        rotation = u @ vt
    aligned = left @ rotation
    aligned *= np.linalg.norm(right) / (np.linalg.norm(aligned) + 1e-8)
    return aligned + target.mean(axis=0)


def folder_labels(paper: dict) -> list[str]:
    if paper.get("map_tags"):
        return [str(label) for label in paper["map_tags"] if label]
    labels = []
    for tag in paper.get("tags") or []:
        if isinstance(tag, str):
            labels.append(tag)
        elif not tag.get("group"):
            labels.append(tag["name"])
    return labels or [paper.get("folder") or "Unfiled"]


def build_embed(papers: list[dict]) -> dict:
    journals = [paper["journal"] or "Unknown" for paper in papers]
    years = [str(paper["year"]) if paper["year"] else "Unknown" for paper in papers]
    titles = [tokens(paper["title"]) for paper in papers]
    folders = [folder_labels(paper) for paper in papers]
    authors = [
        [name.strip() for name in paper["authors"].split(";") if name.strip()]
        if paper["authors"]
        else []
        for paper in papers
    ]
    blocks = {
        "journal": scale_block(np.hstack([one_hot(journals), hash_block(journals, 6)])),
        "year": scale_block(np.hstack([one_hot(years), hash_block(years, 4)])),
        "title": scale_block(np.hstack([multi_hot(titles, minimum=4, limit=280), hash_block([paper["title"] for paper in papers])])),
        "folder": scale_block(np.hstack([multi_hot(folders, minimum=1), hash_block([" / ".join(tags) for tags in folders])])),
        "author": scale_block(np.hstack([multi_hot(authors, minimum=2, limit=400), hash_block([paper["authors"] for paper in papers])])),
    }
    joint = np.hstack(list(blocks.values()))
    print(f"Joint features {joint.shape}", flush=True)
    print("t-SNE joint", flush=True)
    layouts = {"joint": fit_tsne(joint)}
    keys = {
        "journal": journals,
        "year": years,
        "title": [paper["title"] for paper in papers],
        "folder": [" / ".join(tags) for tags in folders],
        "author": [paper["authors"] or "Unknown" for paper in papers],
    }
    for name, block in blocks.items():
        print(f"t-SNE {name} {block.shape}", flush=True)
        block = np.nan_to_num(block, nan=0.0, posinf=0.0, neginf=0.0)
        # A constant field (one folder for the whole demo set) makes PCA inside t-SNE crash.
        if block.shape[0] < 3 or float(np.std(block)) < 1e-8:
            print(f"  {name} has no variation; keeping the joint layout", flush=True)
            layouts[name] = layouts["joint"].copy()
            continue
        layouts[name] = unstack(align(fit_tsne(block), layouts["joint"]), keys[name])
    return {
        "ids": [paper["id"] for paper in papers],
        "layouts": {name: np.round(points, 4).tolist() for name, points in layouts.items()},
    }


def main() -> None:
    if "--demo" in sys.argv:
        library = paperdb.demo_catalog()
        library["embed"] = build_embed(library["papers"])
        for paper in library["papers"]:
            paper.pop("map_tags", None)
        destination = HERE / "library.json"
        destination.write_text(json.dumps(library, ensure_ascii=False, indent=2) + "\n")
        print(f"Wrote {destination} ({library['count']} papers)", flush=True)
        return
    payload = paperdb.map_data()
    OUT.write_text(json.dumps(build_embed(payload["papers"])))
    print(f"Wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
