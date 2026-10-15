# paperdb

A local catalog of a folder of papers. Each directory in a file’s path becomes a tag. Search runs in the browser; a second page lays the library out as a 2D map.

The default library is `~/Dropbox/Academic/Papers`. Set `PAPERS_ROOT` to use another folder. Indexed types are PDF, Word, PowerPoint, RTF, text, and HTML.

## Run

`paperdb.py` uses the standard library. The map builder needs NumPy and scikit-learn, which live in `.venv`.

```bash
python3 -m venv .venv
.venv/bin/pip install numpy scikit-learn
```

Build the index, then open the catalog. The first run reads PDF titles with `mdls` and can take a while. Later runs reuse titles for files that have not changed.

```bash
python3 paperdb.py index
python3 paperdb.py
```

That serves `http://127.0.0.1:8765/` and opens it in the browser. Stop the server with Ctrl-C. If port 8765 is taken, the server tries the next few ports, or you can pass `--port`.

```bash
python3 paperdb.py --port 8800
```

Rebuild after adding or moving files:

```bash
python3 paperdb.py index
```

Search from the terminal:

```bash
python3 paperdb.py search attention 2019
```

## Map

The map page is `http://127.0.0.1:8765/map`. It needs `embed.json`, built from filename metadata (authors, journal, year, title, folder) with one t-SNE layout per field plus a joint layout.

```bash
.venv/bin/python embed.py
```

Index first. `embed.py` reads `papers.db` and does not re-scan the folder.

## What is stored

`papers.db` is the catalog. Authors, journal, and year are parsed from filenames; PDF titles and page counts come from Spotlight (`mdls`) on macOS. `embed.json` is the map layout. Both are local and listed in `.gitignore`.
