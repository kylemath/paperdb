#!/usr/bin/env python3
"""Searchable catalog of ~/dropbox/Academic/Papers.

Each folder in a paper's path is a tag. Rebuild with `python3 paperdb.py index`.
Open the browser with `python3 paperdb.py`.
"""

from __future__ import annotations

import html
import json
import os
import plistlib
import re
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(os.environ.get("PAPERS_ROOT", Path.home() / "dropbox" / "Academic" / "Papers"))
HERE = Path(__file__).resolve().parent
DB = HERE / "papers.db"
PAGE = HERE / "index.html"
INCLUDE = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".rtf", ".txt", ".htm", ".html"}
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".rtf": "application/rtf",
    ".txt": "text/plain; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}
STATIC_FILES = {"library.json", "embed.json", "map.html", "index.html", "catalogue.json", "README.md"}
PREVIEWABLE = {".pdf", ".txt", ".htm", ".html"}
UNFILED = "."
CLEANER_VERSION = "2"
JUNK_TITLE = ("corel", "ventura", ".chp", "indd", "doi:", "acrobat", "adobe indesign", "pii:")


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def guess_year(name: str) -> int | None:
    match = re.search(r"(?<!\d)((?:18|19|20)\d{2})(?!\d)", name)
    if match:
        year = int(match.group(1))
        if 1800 <= year <= 2035:
            return year
    match = re.search(r"[A-Za-z](\d{2})(?!\d)", name)
    if match:
        yy = int(match.group(1))
        return 1900 + yy if yy >= 70 else 2000 + yy
    return None


# Longest aliases are tried first. Matching is on whole tokens, so "cell" does not hit "cellular".
JOURNAL_ALIASES: tuple[tuple[str, str], ...] = tuple(
    sorted(
        [
            ("nature reviews neuroscience", "Nat Rev Neurosci"),
            ("nature neuroscience reviews", "Nat Rev Neurosci"),
            ("nat rev neurosci", "Nat Rev Neurosci"),
            ("nature human behaviour", "Nat Hum Behav"),
            ("nathumbeh", "Nat Hum Behav"),
            ("nature communications", "Nat Commun"),
            ("nature neuroscience", "Nat Neurosci"),
            ("nature methods", "Nat Methods"),
            ("nat neurosci", "Nat Neurosci"),
            ("nat commun", "Nat Commun"),
            ("nat methods", "Nat Methods"),
            ("natureneuro", "Nat Neurosci"),
            ("nature neuro", "Nat Neurosci"),
            ("natneuro", "Nat Neurosci"),
            ("natcomm", "Nat Commun"),
            ("journal of neuroscience", "J Neurosci"),
            ("journal of neurophysiology", "J Neurophysiol"),
            ("journal of cognitive neuroscience", "J Cogn Neurosci"),
            ("journal of experimental psychology", "J Exp Psychol"),
            ("journal of biomedical optics", "J Biomed Opt"),
            ("journal of vision", "J Vis"),
            ("journal of physiology", "J Physiol"),
            ("european journal of neuroscience", "Eur J Neurosci"),
            ("cerebral cortex", "Cereb Cortex"),
            ("cereb cortex", "Cereb Cortex"),
            ("current opinion in neurobiology", "Curr Opin Neurobiol"),
            ("curr opin neurobiol", "Curr Opin Neurobiol"),
            ("current opinion", "Curr Opin Neurobiol"),
            ("curropneurobio", "Curr Opin Neurobiol"),
            ("curr op neurobio", "Curr Opin Neurobiol"),
            ("trends in cognitive sciences", "Trends Cogn Sci"),
            ("trends in neurosciences", "Trends Neurosci"),
            ("trends cogn sci", "Trends Cogn Sci"),
            ("trends neurosci", "Trends Neurosci"),
            ("psychological science", "Psychol Sci"),
            ("psychological bulletin", "Psychol Bull"),
            ("psychophysiology", "Psychophysiology"),
            ("psych science", "Psychol Sci"),
            ("psychscience", "Psychol Sci"),
            ("psychol sci", "Psychol Sci"),
            ("neuropsychologia", "Neuropsychologia"),
            ("neuropsychology", "Neuropsychology"),
            ("neuroimage", "NeuroImage"),
            ("neuro image", "NeuroImage"),
            ("j neurophysiol", "J Neurophysiol"),
            ("jneurophysiol", "J Neurophysiol"),
            ("j cogn neurosci", "J Cogn Neurosci"),
            ("j neurosci", "J Neurosci"),
            ("j. neurosci", "J Neurosci"),
            ("jneurosci", "J Neurosci"),
            ("j neuro", "J Neurosci"),
            ("jcogn", "J Cogn Neurosci"),
            ("jocn", "J Cogn Neurosci"),
            ("jneuro", "J Neurosci"),
            ("current biology", "Curr Biol"),
            ("curr biol", "Curr Biol"),
            ("curr bio", "Curr Biol"),
            ("currbiol", "Curr Biol"),
            ("human brain mapping", "Hum Brain Mapp"),
            ("brain research", "Brain Res"),
            ("brain res", "Brain Res"),
            ("vision research", "Vision Res"),
            ("vis res", "Vision Res"),
            ("visual cognition", "Vis Cogn"),
            ("hearing research", "Hear Res"),
            ("hearing res", "Hear Res"),
            ("experimental brain research", "Exp Brain Res"),
            ("exp brain res", "Exp Brain Res"),
            ("clinical neurophysiology", "Clin Neurophysiol"),
            ("clin neurophysiol", "Clin Neurophysiol"),
            ("clinph", "Clin Neurophysiol"),
            ("behavioral and brain sciences", "Behav Brain Sci"),
            ("consciousness and cognition", "Conscious Cogn"),
            ("attention perception", "Atten Percept Psychophys"),
            ("scientific american", "Sci Am"),
            ("scientific reports", "Sci Rep"),
            ("sci rep", "Sci Rep"),
            ("sciam", "Sci Am"),
            ("optics express", "Opt Express"),
            ("opticsexpress", "Opt Express"),
            ("phys med bio", "Phys Med Biol"),
            ("physics in medicine", "Phys Med Biol"),
            ("j exp psychol", "J Exp Psychol"),
            ("jep gen", "J Exp Psychol"),
            ("jep hpp", "J Exp Psychol"),
            ("jephpp", "J Exp Psychol"),
            ("j biomed opt", "J Biomed Opt"),
            ("j physiol", "J Physiol"),
            ("eur j neurosci", "Eur J Neurosci"),
            ("cercrtx", "Cereb Cortex"),
            ("cerecrtx", "Cereb Cortex"),
            ("cerebralcrtx", "Cereb Cortex"),
            ("neuroreport", "NeuroReport"),
            ("psychophys", "Psychophysiology"),
            ("psychphys", "Psychophysiology"),
            ("psychonomic", "Psychon Bull Rev"),
            ("memory cognition", "Mem Cogn"),
            ("frontiers in", "Frontiers"),
            ("frontiers", "Frontiers"),
            ("biorxiv", "bioRxiv"),
            ("annual review", "Annu Rev"),
            ("annu rev", "Annu Rev"),
            ("elife", "eLife"),
            ("plos one", "PLOS One"),
            ("plos biol", "PLOS Biol"),
            ("plos", "PLOS"),
            ("pnas", "PNAS"),
            ("neuron", "Neuron"),
            ("nature", "Nature"),
            ("science", "Science"),
            ("cortex", "Cortex"),
            ("brain", "Brain"),
            ("cognition", "Cognition"),
            ("perception", "Perception"),
            ("tics", "Trends Cogn Sci"),
            ("tins", "Trends Neurosci"),
            ("scan", "SCAN"),
            ("ieee", "IEEE"),
            ("ejn", "Eur J Neurosci"),
            ("jbo", "J Biomed Opt"),
            ("jov", "J Vis"),
            ("jep", "J Exp Psychol"),
            ("jon", "J Neurosci"),
            ("jn", "J Neurosci"),
            ("cell", "Cell"),
            ("ebr", "Exp Brain Res"),
            ("bbs", "Behav Brain Sci"),
            ("annu rev neurosci", "Annu Rev Neurosci"),
            ("ann rev neurosci", "Annu Rev Neurosci"),
            ("annrevneurosci", "Annu Rev Neurosci"),
            ("annu rev psychol", "Annu Rev Psychol"),
            ("ann rev psy", "Annu Rev Psychol"),
            ("annrevpsy", "Annu Rev Psychol"),
            ("philosophical transactions", "Philos Trans R Soc B"),
            ("philos trans", "Philos Trans R Soc B"),
            ("phil trans", "Philos Trans R Soc B"),
            ("ptrsb", "Philos Trans R Soc B"),
            ("brain topography", "Brain Topogr"),
            ("brain topogr", "Brain Topogr"),
            ("archives of neurology", "Arch Neurol"),
            ("arch neurol", "Arch Neurol"),
            ("applied optics", "Appl Opt"),
            ("jofbiomedoptics", "J Biomed Opt"),
            ("j biomed optics", "J Biomed Opt"),
            ("neuroim", "NeuroImage"),
            ("jcogneuro", "J Cogn Neurosci"),
            ("j cog neuro", "J Cogn Neurosci"),
            ("cerebral crtx", "Cereb Cortex"),
            ("nat neuro", "Nat Neurosci"),
            ("neuropsy", "Neuropsychologia"),
            ("brres", "Brain Res"),
            ("plos1", "PLOS One"),
            ("currbio", "Curr Biol"),
            ("cognitive processing", "Cogn Process"),
            ("international journal of psychophysiology", "Int J Psychophysiol"),
            ("int j psychophysiol", "Int J Psychophysiol"),
            ("int j o psychphys", "Int J Psychophysiol"),
            ("int j psychphys", "Int J Psychophysiol"),
            ("journal of neuroscience methods", "J Neurosci Methods"),
            ("j neurosci methods", "J Neurosci Methods"),
            ("jneurosci methods", "J Neurosci Methods"),
            ("jneurosci" "methods", "J Neurosci Methods"),
            ("jnmeth", "J Neurosci Methods"),
            ("advanced healthcare materials", "Adv Healthc Mater"),
            ("adv healthcare mater", "Adv Healthc Mater"),
            ("adv healthc mater", "Adv Healthc Mater"),
            ("advhealthmat", "Adv Healthc Mater"),
            ("nature biomedical engineering", "Nat Biomed Eng"),
            ("nat biomed eng", "Nat Biomed Eng"),
            ("natbioeng", "Nat Biomed Eng"),
            ("scientificrep", "Sci Rep"),
            ("sci reports", "Sci Rep"),
            ("pscyhscience", "Psychol Sci"),
            ("journal of sport and exercise psychology", "J Sport Exerc Psychol"),
            ("j sport exerc psychol", "J Sport Exerc Psychol"),
            ("jsep", "J Sport Exerc Psychol"),
            ("frontiers in pharmacology", "Front Pharmacol"),
            ("front pharmacol", "Front Pharmacol"),
            ("frontpharmaco", "Front Pharmacol"),
            ("bioengineering mdpi", "Bioengineering"),
            ("bioengineering", "Bioengineering"),
            ("journal of stroke and cerebrovascular diseases", "J Stroke Cerebrovasc Dis"),
            ("j stroke cerebrovasc dis", "J Stroke Cerebrovasc Dis"),
            ("j stroke cerebvsc disease", "J Stroke Cerebrovasc Dis"),
            ("tin", "Trends Neurosci"),
        ],
        key=lambda item: len(item[0]),
        reverse=True,
    )
)


def _tokens(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


# Short words that are also journal names. Away from a year they only count near
# the start of the filename, so a title does not become the journal.
AMBIGUOUS_JOURNALS = {"brain", "science", "nature", "cell", "cortex", "neuron", "perception", "cognition"}
STATUS_WORDS = re.compile(
    r"\b(in\s+press|in\s+print|under\s*review|accepted\s+preprint|accepted)\b",
    re.IGNORECASE,
)


def find_journal(text: str) -> tuple[str | None, str]:
    """Return the canonical journal and the filename text before that journal.

    The journal token is the alias sitting closest to the year, so a title that
    merely mentions "brain" does not beat "JoN" next to the date. Authors are the
    text in front of the journal.
    """
    tokens = _tokens(text).split()
    if not tokens:
        return None, text
    year_at = None
    for index, token in enumerate(tokens):
        if re.fullmatch(r"(?:18|19|20)\d{2}", token) or re.fullmatch(r"[a-z]+\d{2}", token):
            year_at = index
            break
    best: tuple[tuple[int, int, int], str, str, int] | None = None
    for alias, canonical in JOURNAL_ALIASES:
        needle = _tokens(alias)
        parts = needle.split()
        if not parts or len(parts) > len(tokens):
            continue
        width = len(parts)
        for index in range(len(tokens) - width + 1):
            if tokens[index : index + width] != parts:
                continue
            if year_at is None:
                ambiguous = width == 1 and parts[0] in AMBIGUOUS_JOURNALS
                if ambiguous and len(tokens) >= 6 and index > 3:
                    break
                distance = index
            else:
                distance = min(abs(index - year_at), abs(index + width - 1 - year_at))
                if distance > 3:
                    break
            rank = (distance, -width, -len(needle))
            if best is None or rank < best[0]:
                best = (rank, canonical, needle, index)
            break
    if best is None:
        return None, text
    _, canonical, needle, token_index = best
    pattern = re.sub(r"\\ ", r"[^A-Za-z0-9]+", re.escape(needle))
    prefix = text
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        if len(_tokens(text[: match.start()]).split()) == token_index:
            prefix = text[: match.start()]
            break
    return canonical, prefix


def _author_names(raw: str) -> list[str]:
    raw = re.sub(r"^\d+\s*[.)]\s*", "", raw.strip())
    raw = raw.replace("_", " ")
    raw = re.sub(r"\bet\s*\.?\s*al\.?\b", " ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\betal\b", " ", raw, flags=re.IGNORECASE)
    lowered_words = re.findall(r"\b[a-z]{3,}\b", raw)
    if len(lowered_words) >= 2:
        return []
    if len(raw.split()) >= 4 and re.search(r"\b(to|with|from|into|via|for|the|and|of)\b", raw, flags=re.IGNORECASE):
        return []
    if "," in raw or "&" in raw or ";" in raw or re.search(r"\band\b", raw, flags=re.IGNORECASE):
        parts = re.split(r"\s*[,;&]\s*|\s+and\s+", raw, flags=re.IGNORECASE)
    elif re.search(r"[A-Za-z]-[A-Za-z]", raw):
        parts = re.split(r"\s*-\s*", raw)
    else:
        parts = raw.split()
    names: list[str] = []
    skip = {"et", "al", "etal", "and", "the", "of", "for", "fig", "figure", "refs", "ref"}
    for part in parts:
        part = re.sub(r"[^A-Za-z.\s-]", "", part).strip(" .-")
        if not part or part.lower() in skip or len(part) < 2:
            continue
        if part.isupper() and len(part) <= 3:
            continue
        part = re.sub(r"\b([A-Z])([A-Z][a-z]+)", r"\1. \2", part)
        if part not in names:
            names.append(part)
        if len(names) == 8:
            break
    return names


def cite_from_filename(filename: str) -> tuple[list[str], str | None, int | None]:
    """Authors, journal, and year as written in the filename. PDF text is not read."""
    stem = Path(filename).stem.replace("_", " ")
    stem = re.sub(r"\s+", " ", stem).strip()
    stem = re.sub(r"^\d+\s*[.)]\s*", "", stem)
    year = guess_year(stem)
    journal, author_src = find_journal(stem)
    author_src = STATUS_WORDS.sub(" ", author_src)
    if year is not None:
        full = str(year)
        at = author_src.find(full)
        if at >= 0:
            author_src = author_src[:at]
        else:
            short = f"{year % 100:02d}"
            match = re.search(rf"[A-Za-z]{short}(?!\d)", author_src)
            if match:
                author_src = author_src[: match.start() + 1]
    if year is None and not re.search(r"et\s*\.?\s*al|,", stem, flags=re.IGNORECASE):
        authors: list[str] = []
    else:
        authors = _author_names(author_src)
    return authors, journal, year


def pretty_stem(stem: str) -> str:
    text = stem.replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text or stem


def usable_title(title: str | None, filename: str) -> str | None:
    if not title:
        return None
    text = html.unescape(title).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    lowered = text.lower()
    if lowered in {"(null)", "null", "untitled", "untitled document", "pdf"}:
        return None
    if lowered.startswith("microsoft word") or lowered.startswith("microsoft powerpoint"):
        return None
    if any(token in lowered for token in JUNK_TITLE):
        return None
    if len(text) < 15 or " " not in text:
        return None
    words = re.findall(r"[A-Za-z]{3,}", text)
    letters = sum(character.isalpha() for character in text)
    if len(words) < 2 or letters < len(text) * 0.55:
        return None
    if len(text.split()) <= 3 and re.search(r"\d+\.\.\d+", text):
        return None
    if lowered == Path(filename).stem.lower():
        return None
    return text


def pdf_meta(path: str) -> tuple[str, str | None, int | None]:
    try:
        result = subprocess.run(
            ["mdls", "-plist", "-", "-name", "kMDItemTitle", "-name", "kMDItemNumberOfPages", path],
            capture_output=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0 or not result.stdout:
            return path, None, None
        data = plistlib.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, plistlib.InvalidFileException, ValueError):
        return path, None, None
    title = data.get("kMDItemTitle")
    pages = data.get("kMDItemNumberOfPages")
    if not isinstance(title, str):
        title = None
    if not isinstance(pages, int) or pages <= 0:
        pages = None
    return path, title, pages


def iter_docs():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [name for name in dirnames if not name.startswith(".") and name != "__MACOSX"]
        relative = os.path.relpath(dirpath, ROOT)
        parts = [] if relative == "." else relative.split(os.sep)
        if any(part.endswith("_files") for part in parts):
            continue
        for name in filenames:
            if name.startswith("."):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in INCLUDE:
                continue
            yield Path(dirpath) / name, parts, name, ext


def load_cache() -> dict[str, tuple]:
    if not DB.exists():
        return {}
    try:
        con = connect()
    except sqlite3.Error:
        return {}
    try:
        version = con.execute("SELECT value FROM meta WHERE key = 'cleaner'").fetchone()
        if version is None or version["value"] != CLEANER_VERSION:
            return {}
        rows = con.execute("SELECT path, size, mtime, pdf_title, pages FROM papers")
        return {row["path"]: (row["size"], row["mtime"], row["pdf_title"], row["pages"]) for row in rows}
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def tag_chain(parts: list[str]) -> list[str]:
    if not parts:
        return [UNFILED]
    chain = []
    for index in range(len(parts)):
        chain.append(os.sep.join(parts[: index + 1]))
    return chain


def build_index() -> None:
    if not ROOT.is_dir():
        sys.exit(f"Papers folder not found: {ROOT}")

    cache = load_cache()
    pending = []
    records = []
    reused = 0
    for path, parts, name, ext in iter_docs():
        try:
            stat = path.stat()
        except OSError:
            continue
        rel_parts = parts
        relpath = name if not rel_parts else os.path.join(*rel_parts, name)
        cached = cache.get(str(path))
        pdf_title = None
        pages = None
        if ext == ".pdf" and cached and cached[0] == stat.st_size and abs(cached[1] - stat.st_mtime) < 1:
            pdf_title = cached[2]
            pages = cached[3]
            reused += 1
        elif ext == ".pdf":
            pending.append(str(path))
        title = usable_title(pdf_title, name) or pretty_stem(Path(name).stem)
        records.append(
            {
                "filename": name,
                "stem": Path(name).stem,
                "title": title,
                "pdf_title": pdf_title,
                "path": str(path),
                "relpath": relpath,
                "folder": os.sep.join(rel_parts),
                "ext": ext,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "pages": pages,
                "year": guess_year(name),
                "tag_paths": tag_chain(rel_parts),
                "needs_meta": ext == ".pdf" and not (cached and cached[0] == stat.st_size and abs(cached[1] - stat.st_mtime) < 1),
            }
        )

    fetched = 0
    if pending:
        print(f"Reading PDF titles for {len(pending)} files…", flush=True)
        meta: dict[str, tuple[str | None, int | None]] = {}
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = [pool.submit(pdf_meta, path) for path in pending]
            for done, future in enumerate(as_completed(futures), start=1):
                path, raw_title, pages = future.result()
                meta[path] = (raw_title, pages)
                if done % 200 == 0 or done == len(pending):
                    print(f"  {done}/{len(pending)}", flush=True)
        for record in records:
            if not record["needs_meta"]:
                continue
            raw_title, pages = meta.get(record["path"], (None, None))
            record["pages"] = pages
            cleaned = usable_title(raw_title, record["filename"])
            record["pdf_title"] = cleaned
            if cleaned:
                record["title"] = cleaned
                fetched += 1

    for record in records:
        authors, journal, parsed_year = cite_from_filename(record["filename"])
        record["authors"] = "; ".join(authors) if authors else None
        record["journal"] = journal
        if record["year"] is None:
            record["year"] = parsed_year

    tags: dict[str, tuple[str, str | None]] = {}
    for record in records:
        paths = record["tag_paths"]
        for index, tag_path in enumerate(paths):
            if tag_path in tags:
                continue
            parent = paths[index - 1] if index else None
            name = "Unfiled" if tag_path == UNFILED else Path(tag_path).name
            tags[tag_path] = (name, parent)

    HERE.mkdir(parents=True, exist_ok=True)
    con = connect()
    try:
        con.executescript(
            """
            DROP TABLE IF EXISTS paper_tags;
            DROP TABLE IF EXISTS papers_fts;
            DROP TABLE IF EXISTS papers;
            DROP TABLE IF EXISTS tags;
            DROP TABLE IF EXISTS meta;

            CREATE TABLE meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE papers (
                id INTEGER PRIMARY KEY,
                filename TEXT NOT NULL,
                stem TEXT NOT NULL,
                title TEXT NOT NULL,
                pdf_title TEXT,
                path TEXT NOT NULL UNIQUE,
                relpath TEXT NOT NULL,
                folder TEXT NOT NULL,
                ext TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime REAL NOT NULL,
                pages INTEGER,
                year INTEGER,
                authors TEXT,
                journal TEXT
            );
            CREATE TABLE tags (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                parent_path TEXT
            );
            CREATE TABLE paper_tags (
                paper_id INTEGER NOT NULL REFERENCES papers(id),
                tag_id INTEGER NOT NULL REFERENCES tags(id),
                depth INTEGER NOT NULL,
                PRIMARY KEY (paper_id, tag_id)
            );
            CREATE INDEX idx_paper_tags_tag ON paper_tags(tag_id);
            CREATE VIRTUAL TABLE papers_fts USING fts5(
                title, filename, stem, relpath, tags, year, authors, journal,
                tokenize = "unicode61 remove_diacritics 2"
            );
            """
        )
        tag_ids: dict[str, int] = {}
        for tag_path, (name, parent) in sorted(tags.items(), key=lambda item: item[0].count(os.sep)):
            cur = con.execute(
                "INSERT INTO tags (name, path, parent_path) VALUES (?, ?, ?)",
                (name, tag_path, parent),
            )
            tag_ids[tag_path] = cur.lastrowid

        for record in records:
            cur = con.execute(
                """
                INSERT INTO papers
                    (filename, stem, title, pdf_title, path, relpath, folder, ext, size, mtime, pages, year, authors, journal)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["filename"],
                    record["stem"],
                    record["title"],
                    record["pdf_title"],
                    record["path"],
                    record["relpath"],
                    record["folder"],
                    record["ext"],
                    record["size"],
                    record["mtime"],
                    record["pages"],
                    record["year"],
                    record["authors"],
                    record["journal"],
                ),
            )
            paper_id = cur.lastrowid
            names = []
            for depth, tag_path in enumerate(record["tag_paths"]):
                names.append(tags[tag_path][0])
                con.execute(
                    "INSERT INTO paper_tags (paper_id, tag_id, depth) VALUES (?, ?, ?)",
                    (paper_id, tag_ids[tag_path], depth),
                )
            con.execute(
                """
                INSERT INTO papers_fts (rowid, title, filename, stem, relpath, tags, year, authors, journal)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    record["title"],
                    record["filename"],
                    record["stem"],
                    record["relpath"],
                    " ".join(names),
                    "" if record["year"] is None else str(record["year"]),
                    record["authors"] or "",
                    record["journal"] or "",
                ),
            )
        stamped = datetime.now(timezone.utc).isoformat(timespec="seconds")
        con.execute("INSERT INTO meta (key, value) VALUES ('indexed_at', ?)", (stamped,))
        con.execute("INSERT INTO meta (key, value) VALUES ('root', ?)", (str(ROOT),))
        con.execute("INSERT INTO meta (key, value) VALUES ('cleaner', ?)", (CLEANER_VERSION,))
        con.commit()
    finally:
        con.close()

    titled = sum(1 for record in records if record["pdf_title"])
    print(f"Indexed {len(records)} documents in {len(tags)} folder tags")
    print(f"  PDF titles kept: {titled} (reused {reused}, newly read {fetched})")
    print(f"Database: {DB}")


def to_fts(query: str) -> str | None:
    clauses = []
    for phrase, word in re.findall(r'"([^"]+)"|(\S+)', query):
        source = phrase or word
        tokens = re.findall(r"\w+", source, flags=re.UNICODE)
        if phrase and tokens:
            clauses.append('"' + " ".join(tokens) + '"')
        else:
            clauses.extend(f'"{token}"*' for token in tokens)
    if not clauses:
        return None
    return " AND ".join(clauses)


def search(query: str, tag_paths: list[str], sort: str, offset: int, limit: int) -> dict:
    match = to_fts(query) if query.strip() else None
    joins = []
    clauses = []
    params: list = []
    if match:
        joins.append("JOIN papers_fts ON papers_fts.rowid = papers.id")
        clauses.append("papers_fts MATCH ?")
        params.append(match)
    for tag_path in tag_paths:
        clauses.append(
            """papers.id IN (
                SELECT pt.paper_id FROM paper_tags pt
                JOIN tags t ON t.id = pt.tag_id
                WHERE t.path = ?
            )"""
        )
        params.append(tag_path)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    join = " ".join(joins)
    if sort == "year":
        order = "papers.year IS NULL, papers.year DESC, papers.title COLLATE NOCASE"
    elif sort == "modified":
        order = "papers.mtime DESC"
    elif sort == "rank" and match:
        order = "bm25(papers_fts), papers.title COLLATE NOCASE"
    else:
        order = "papers.title COLLATE NOCASE"

    con = connect()
    try:
        total = con.execute(f"SELECT COUNT(*) FROM papers {join}{where}", params).fetchone()[0]
        rows = con.execute(
            f"""
            SELECT papers.id, papers.filename, papers.title, papers.relpath, papers.path,
                   papers.ext, papers.size, papers.mtime, papers.pages, papers.year,
                   papers.authors, papers.journal
            FROM papers {join}{where}
            ORDER BY {order}
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
        papers = attach_tags(con, rows)
        counts = {
            row["path"]: row["n"]
            for row in con.execute(
                f"""
                SELECT tags.path AS path, COUNT(DISTINCT papers.id) AS n
                FROM papers {join}
                JOIN paper_tags ON paper_tags.paper_id = papers.id
                JOIN tags ON tags.id = paper_tags.tag_id
                {where}
                GROUP BY tags.path
                """,
                params,
            )
        }
    finally:
        con.close()
    return {"total": total, "offset": offset, "papers": papers, "counts": counts}


def attach_tags(con: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[dict]:
    if not rows:
        return []
    ids = [row["id"] for row in rows]
    marks = ",".join("?" * len(ids))
    grouped: dict[int, list[dict]] = {paper_id: [] for paper_id in ids}
    for row in con.execute(
        f"""
        SELECT pt.paper_id, t.name, t.path
        FROM paper_tags pt
        JOIN tags t ON t.id = pt.tag_id
        WHERE pt.paper_id IN ({marks})
        ORDER BY pt.depth
        """,
        ids,
    ):
        grouped[row["paper_id"]].append({"name": row["name"], "path": row["path"]})
    papers = []
    for row in rows:
        papers.append(
            {
                "id": row["id"],
                "filename": row["filename"],
                "title": row["title"],
                "relpath": row["relpath"],
                "path": row["path"],
                "ext": row["ext"],
                "size": row["size"],
                "mtime": row["mtime"],
                "pages": row["pages"],
                "year": row["year"],
                "authors": row["authors"] or "",
                "journal": row["journal"] or "",
                "tags": grouped[row["id"]],
                "preview": row["ext"] in PREVIEWABLE,
            }
        )
    return papers


def catalog() -> dict:
    con = connect()
    try:
        indexed = con.execute("SELECT value FROM meta WHERE key = 'indexed_at'").fetchone()
        total = con.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        tags = [
            {
                "name": row["name"],
                "path": row["path"],
                "parent": row["parent_path"],
                "count": row["n"],
            }
            for row in con.execute(
                """
                SELECT tags.name, tags.path, tags.parent_path, COUNT(paper_tags.paper_id) AS n
                FROM tags
                LEFT JOIN paper_tags ON paper_tags.tag_id = tags.id
                GROUP BY tags.id
                ORDER BY tags.name COLLATE NOCASE
                """
            )
        ]
    finally:
        con.close()
    return {
        "papers": total,
        "indexed_at": indexed["value"] if indexed else None,
        "root": str(ROOT),
        "tags": tags,
    }


def demo_catalog() -> dict:
    """Snapshot of examplePapers for GitHub Pages. Does not touch papers.db.

    The example folder is flat, so each paper is tagged by the year and journal
    parsed from its filename. PDF titles and page counts come from Spotlight.
    """
    root = HERE / "examplePapers"
    if not root.is_dir():
        sys.exit(f"Example papers folder not found: {root}")
    paths = sorted(
        (
            path
            for path in root.iterdir()
            if path.is_file() and not path.name.startswith(".") and path.suffix.lower() in INCLUDE
        ),
        key=lambda path: path.name.lower(),
    )
    papers = []
    tag_rows: dict[str, dict] = {}

    def touch(name: str, path: str, parent: str | None, group: bool) -> None:
        row = tag_rows.get(path)
        if row is None:
            tag_rows[path] = {"name": name, "path": path, "parent": parent, "group": group, "count": 0}
        tag_rows[path]["count"] += 1

    for paper_id, path in enumerate(paths, start=1):
        try:
            stat = path.stat()
        except OSError:
            continue
        _, raw_title, pages = pdf_meta(str(path))
        display_stem = re.sub(r"^\d+\s*[.)]\s*", "", path.stem)
        title = usable_title(raw_title, path.name) or pretty_stem(display_stem)
        authors, journal, year = cite_from_filename(path.name)
        rel = "examplePapers/" + path.name
        year_name = str(year) if year else "Undated"
        journal_name = journal or "Unknown"
        tags = [
            {"name": "Year", "path": "year", "parent": None, "group": True},
            {"name": year_name, "path": "year/" + (str(year) if year else "undated"), "parent": "year", "group": False},
            {"name": "Journal", "path": "journal", "parent": None, "group": True},
            {
                "name": journal_name,
                "path": "journal/" + journal_name.replace("/", "-"),
                "parent": "journal",
                "group": False,
            },
        ]
        for tag in tags:
            touch(tag["name"], tag["path"], tag["parent"], tag["group"])
        papers.append(
            {
                "id": paper_id,
                "filename": path.name,
                "title": title,
                "relpath": rel,
                "path": rel,
                "href": rel,
                "ext": path.suffix.lower(),
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "pages": pages,
                "year": year,
                "authors": "; ".join(authors) if authors else "",
                "journal": journal or "",
                "folder": "examplePapers",
                "map_tags": ["examplePapers"],
                "tags": tags,
                "preview": True,
            }
        )
    return {
        "count": len(papers),
        "indexed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "examplePapers",
        "tags": sorted(tag_rows.values(), key=lambda tag: (tag["path"].count("/"), tag["name"].lower())),
        "papers": papers,
    }


CITE_VERSION = "1"


def rebuild_fts(con: sqlite3.Connection) -> None:
    con.execute("DROP TABLE IF EXISTS papers_fts")
    con.execute(
        """
        CREATE VIRTUAL TABLE papers_fts USING fts5(
            title, filename, stem, relpath, tags, year, authors, journal,
            tokenize = "unicode61 remove_diacritics 2"
        )
        """
    )
    tag_names: dict[int, list[str]] = {}
    for row in con.execute(
        """
        SELECT pt.paper_id, t.name
        FROM paper_tags pt
        JOIN tags t ON t.id = pt.tag_id
        ORDER BY pt.paper_id, pt.depth
        """
    ):
        tag_names.setdefault(row[0], []).append(row[1])
    for paper in con.execute(
        "SELECT id, title, filename, stem, relpath, year, authors, journal FROM papers"
    ):
        con.execute(
            """
            INSERT INTO papers_fts
                (rowid, title, filename, stem, relpath, tags, year, authors, journal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper["id"],
                paper["title"],
                paper["filename"],
                paper["stem"],
                paper["relpath"],
                " ".join(tag_names.get(paper["id"], [])),
                "" if paper["year"] is None else str(paper["year"]),
                paper["authors"] or "",
                paper["journal"] or "",
            ),
        )


def backfill_citations() -> None:
    """Fill authors and journal from filenames. Does not re-read PDFs."""
    con = connect()
    try:
        columns = {row[1] for row in con.execute("PRAGMA table_info(papers)")}
        if "authors" not in columns:
            con.execute("ALTER TABLE papers ADD COLUMN authors TEXT")
        if "journal" not in columns:
            con.execute("ALTER TABLE papers ADD COLUMN journal TEXT")
        version = con.execute("SELECT value FROM meta WHERE key = 'cite'").fetchone()
        if version is not None and version["value"] == CITE_VERSION:
            return
        for row in con.execute("SELECT id, filename, year FROM papers"):
            authors, journal, parsed_year = cite_from_filename(row["filename"])
            con.execute(
                "UPDATE papers SET authors = ?, journal = ?, year = ? WHERE id = ?",
                (
                    "; ".join(authors) if authors else None,
                    journal,
                    row["year"] if row["year"] else parsed_year,
                    row["id"],
                ),
            )
        rebuild_fts(con)
        con.execute(
            "INSERT INTO meta (key, value) VALUES ('cite', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (CITE_VERSION,),
        )
        con.commit()
        print("Citation fields updated from filenames", flush=True)
    finally:
        con.close()


def map_data() -> dict:
    backfill_citations()
    con = connect()
    try:
        tags: dict[int, list[str]] = {}
        for row in con.execute(
            """
            SELECT pt.paper_id, t.name
            FROM paper_tags pt
            JOIN tags t ON t.id = pt.tag_id
            ORDER BY pt.paper_id, pt.depth
            """
        ):
            tags.setdefault(row[0], []).append(row[1])
        papers = []
        for row in con.execute(
            "SELECT id, title, filename, authors, journal, year, ext FROM papers"
        ):
            names = tags.get(row["id"], [])
            papers.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "filename": row["filename"],
                    "authors": row["authors"] or "",
                    "journal": row["journal"] or "",
                    "year": row["year"],
                    "ext": row["ext"],
                    "folder": names[0] if names else "Unfiled",
                    "tags": names,
                }
            )
    finally:
        con.close()
    return {"papers": papers}


def paper_path(paper_id: int) -> Path | None:
    con = connect()
    try:
        row = con.execute("SELECT path FROM papers WHERE id = ?", (paper_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        return None
    path = Path(row["path"])
    if not path.is_file():
        return None
    return path


def static_file(url_path: str) -> Path | None:
    """A repo file GitHub Pages can serve, limited to the demo catalogue."""
    rel = url_path.lstrip("/")
    if not rel or any(part.startswith(".") or part == ".." for part in Path(rel).parts):
        return None
    allowed = rel in STATIC_FILES or (rel.startswith("examplePapers/") and Path(rel).suffix.lower() in INCLUDE)
    if not allowed:
        return None
    root = HERE.resolve()
    target = (HERE / rel).resolve()
    if target != root and root not in target.parents:
        return None
    if not target.is_file():
        return None
    return target


class Handler(BaseHTTPRequestHandler):
    server_version = "PaperDB/1.0"

    def log_message(self, fmt: str, *args) -> None:
        if str(args[1:2]) not in {"('200',)", "('206',)"}:
            super().log_message(fmt, *args)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path.startswith("/file/"):
            self._file(path[6:])
            return
        found = static_file(path)
        if found is not None:
            self._send_file(found)
            return
        self.send_error(501)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path in {"/", "/index.html"}:
            self._send_bytes(PAGE.read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/map":
            self._send_bytes((HERE / "map.html").read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/api/map":
            self._send_json(map_data())
            return
        if path == "/api/embed":
            embed_path = HERE / "embed.json"
            if not embed_path.exists():
                self._send_json({"error": "embedding not built"}, 404)
                return
            self._send_bytes(embed_path.read_bytes(), "application/json")
            return
        if path == "/api/tags":
            self._send_json(catalog())
            return
        if path == "/api/search":
            self._search(parse_qs(parsed.query))
            return
        if path.startswith("/file/"):
            self._file(path[6:])
            return
        found = static_file(path)
        if found is not None:
            self._send_file(found)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path.startswith("/api/open/"):
            self._launch(path[len("/api/open/") :], reveal=False)
            return
        if path.startswith("/api/reveal/"):
            self._launch(path[len("/api/reveal/") :], reveal=True)
            return
        self.send_error(404)

    def _search(self, query: dict[str, list[str]]) -> None:
        text = query.get("q", [""])[0]
        tags = query.get("tag", [])
        sort = query.get("sort", ["rank"])[0]
        if sort not in {"rank", "title", "year", "modified"}:
            sort = "rank"
        try:
            offset = max(0, int(query.get("offset", ["0"])[0]))
            limit = min(100, max(1, int(query.get("limit", ["50"])[0])))
        except ValueError:
            self._send_json({"error": "bad paging"}, 400)
            return
        try:
            self._send_json(search(text, tags, sort, offset, limit))
        except sqlite3.OperationalError as exc:
            self._send_json({"error": f"search failed: {exc}"}, 400)

    def _file(self, raw_id: str) -> None:
        try:
            paper_id = int(raw_id)
        except ValueError:
            self.send_error(404)
            return
        path = paper_path(paper_id)
        if path is None:
            self.send_error(404, "File is missing. Rebuild the index.")
            return
        self._send_file(path)

    def _send_file(self, path: Path) -> None:
        ctype = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
        try:
            size = path.stat().st_size
            start, end = 0, max(0, size - 1)
            status = 200
            range_header = self.headers.get("Range")
            if range_header and range_header.startswith("bytes=") and size:
                spec = range_header[6:].split(",", 1)[0].strip()
                left, _, right = spec.partition("-")
                if left == "" and right:
                    start = max(0, size - int(right))
                elif left:
                    start = int(left)
                    end = int(right) if right else size - 1
                end = min(end, size - 1)
                if start < 0 or start > end:
                    self.send_error(416)
                    return
                status = 206
            length = 0 if size == 0 else end - start + 1
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if self.command == "HEAD" or length == 0:
                return
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining:
                    chunk = handle.read(min(262144, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ValueError):
            return
        except OSError:
            self.send_error(404)

    def _launch(self, raw_id: str, reveal: bool) -> None:
        try:
            paper_id = int(raw_id)
        except ValueError:
            self._send_json({"error": "bad id"}, 400)
            return
        path = paper_path(paper_id)
        if path is None:
            self._send_json({"error": "file missing"}, 404)
            return
        command = ["open", "-R", str(path)] if reveal else ["open", str(path)]
        subprocess.run(command, check=False)
        self._send_json({"ok": True})

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self._send_bytes(body, "application/json; charset=utf-8", status, cache=False)

    def _send_bytes(self, body: bytes, content_type: str, status: int = 200, cache: bool = True) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if not cache else "no-cache")
        self.end_headers()
        self.wfile.write(body)


def serve(port: int | None = None) -> None:
    if not DB.exists():
        sys.exit(f"No database at {DB}. Run: python3 paperdb.py index")
    if not PAGE.exists():
        sys.exit(f"Missing {PAGE}")
    backfill_citations()
    chosen = port or 8765
    httpd = None
    for candidate in range(chosen, chosen + 10):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
            chosen = candidate
            break
        except OSError:
            continue
    if httpd is None:
        sys.exit("Could not bind a local port")
    url = f"http://127.0.0.1:{chosen}/"
    print(f"Paper library at {url}", flush=True)
    print("Stop with Ctrl-C. Rebuild after adding files: python3 paperdb.py index", flush=True)
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


def print_search(query: str) -> None:
    if not DB.exists():
        sys.exit(f"No database at {DB}. Run: python3 paperdb.py index")
    result = search(query, [], "rank", 0, 20)
    for paper in result["papers"]:
        tags = " / ".join(tag["name"] for tag in paper["tags"])
        print(f"{paper['title']}")
        print(f"  {tags}")
        print(f"  {paper['relpath']}")
        print()
    print(f"{result['total']} matches")


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "search":
        print_search(" ".join(args[1:]))
        return
    if args and args[0] == "index":
        build_index()
        return
    if "--reindex" in args or not DB.exists():
        build_index()
    if not args or "serve" in args or "--reindex" in args:
        port = None
        if "--port" in args:
            port = int(args[args.index("--port") + 1])
        serve(port)


if __name__ == "__main__":
    main()
