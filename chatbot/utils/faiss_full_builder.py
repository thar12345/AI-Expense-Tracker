from pathlib import Path
import os, tempfile, pickle, numpy as np, faiss
from sentence_transformers import SentenceTransformer
from django.conf import settings
from receipt_mgmt.models import Receipt, Item
from chatbot.azure_blob import download_latest, upload_version
from typing import Optional 

# ──────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────
CACHE = settings.FAISS_CACHE_DIR             # e.g. /tmp/faiss_cache
MODEL = "all-MiniLM-L6-v2"                   # embedding model used everywhere

# ──────────────────────────────────────────────────────────────
# Utility helpers (private)
# ──────────────────────────────────────────────────────────────
def _local_path(kind: str) -> Path:
    """Return the on-disk path for a given kind's .faiss file."""
    return CACHE / f"{kind}_index.faiss"


def ensure_cached(kind: str):
    """
    Make sure <kind>_index.faiss exists in CACHE.
    Downloads the blob once per container lifetime.
    """
    path = _local_path(kind)
    if not path.exists():
        download_latest(kind, path)


def load_index(kind: str):
    """
    Public helper that returns a *faiss.Index* object,
    downloading the file first if needed.
    """
    ensure_cached(kind)
    return faiss.read_index(str(_local_path(kind)))


def save_index(kind: str, idx, mapping: dict[int, str]):
    """
    Overwrite both the blob (remote) and cache (local) copy
    with the supplied *idx* and *mapping*.
    Steps:
      1. Write index to a temp file
      2. Upload temp file as new version and promote to *_latest*
      3. Move temp file into cache to keep local workers up-to-date
      4. Rewrite mapping *.pkl* next to the cache file
    """
    tmp = tempfile.NamedTemporaryFile(delete=False)
    faiss.write_index(idx, tmp.name)
    tmp.close()

    upload_version(kind, Path(tmp.name))          # → Azure
    os.replace(tmp.name, _local_path(kind))       # → local cache

    with open(_local_path(kind).with_suffix(".pkl"), "wb") as fh:
        pickle.dump(mapping, fh)

# ------------------------------------------------------------------
# Heavy-weight builder
# ------------------------------------------------------------------
def create_faiss_indexes(out_dir: Path):                  
    """
    Build three FAISS indexes (company, address, item_description)
    and write them + *.pkl mapping files into *out_dir*.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    model = SentenceTransformer(MODEL)

    # ---------- 1. Companies ----------
    companies = list(
        Receipt.objects.values_list("company", flat=True).distinct()
    )
    _build_one(
        texts=companies,
        kind="company",
        model=model,
        out_dir=out_dir,
    )

    # ---------- 2. Addresses ----------
    addresses = list(
        Receipt.objects.exclude(address="").values_list("address", flat=True).distinct()
    )
    _build_one(
        texts=addresses,
        kind="address",
        model=model,
        out_dir=out_dir,
    )

    # ---------- 3. Item descriptions ----------
    descriptions = list(
        Item.objects.values_list("description", flat=True).distinct()
    )
    _build_one(
        texts=descriptions,
        kind="item_description",
        model=model,
        out_dir=out_dir,
        batch=1000,          # embed in batches – optional
    )

    print("✓ All FAISS indexes created")

# ------------------------------------------------------------------
# Helper (private)
# ------------------------------------------------------------------
def _build_one(*, texts, kind, model, out_dir: Path, batch: Optional[int] = None ):
    """
    Build a single IndexFlatL2 and write:
        <kind>_index.faiss
        <kind>_mapping.pkl
    Batch-encodes if *batch* is given.
    """
    if not texts:
        print(f"[FAISS] No data for {kind}; creating empty index")
        dim = model.get_sentence_embedding_dimension()
        idx = faiss.IndexFlatL2(dim)
        mapping = {}
    else:
        # optional batching
        if batch:
            vecs = []
            for i in range(0, len(texts), batch):
                vecs.append(model.encode(texts[i : i + batch]))
            vectors = np.vstack(vecs).astype("float32")
        else:
            vectors = model.encode(texts).astype("float32")

        dim = vectors.shape[1]
        idx = faiss.IndexFlatL2(dim)
        idx.add(vectors)
        mapping = {i: t for i, t in enumerate(texts)}

    # write files  (FIX 3: use Path)
    faiss.write_index(idx, str(out_dir / f"{kind}_index.faiss"))
    with open(out_dir / f"{kind}_mapping.pkl", "wb") as fh:
        pickle.dump(mapping, fh)

    print(f"[FAISS] {kind} → {idx.ntotal:,} vectors")

# ──────────────────────────────────────────────────────────────
# 1️⃣  NIGHTLY FULL REBUILD
# ──────────────────────────────────────────────────────────────
def full_rebuild():
    tmp_dir = Path(tempfile.mkdtemp())
    create_faiss_indexes(tmp_dir)

    for kind in ("company", "address", "item_description"):
        # upload index
        upload_version(kind, tmp_dir / f"{kind}_index.faiss")

        # upload mapping
        upload_version(f"{kind}_mapping", tmp_dir / f"{kind}_mapping.pkl")

        # refresh local cache (index + mapping)
        _local_path(kind).parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp_dir / f"{kind}_index.faiss", _local_path(kind))
        os.replace(tmp_dir / f"{kind}_mapping.pkl",
                   _local_path(kind).with_suffix(".pkl"))

# ──────────────────────────────────────────────────────────────
# 2️⃣  APPEND-ON-UPLOAD PATH
# ──────────────────────────────────────────────────────────────
def append_for_receipt(receipt_id: int):
    """
    Called by a Celery task after a new Receipt is saved.
    • Encodes company, address, and item descriptions.
    • Appends them to the relevant local FAISS index in RAM.
    • Persists the updated index back to Azure and cache.
    """
    rec = Receipt.objects.get(pk=receipt_id)
    model = SentenceTransformer(MODEL)

    # --- Company vector --------------------------------------
    if rec.company:
        idx, mapping = _append_one(
            kind="company",
            vectors=model.encode([rec.company]),
            labels=[rec.company],
        )
        save_index("company", idx, mapping)

    # --- Address vector --------------------------------------
    if rec.address:
        idx, mapping = _append_one(
            kind="address",
            vectors=model.encode([rec.address]),
            labels=[rec.address],
        )
        save_index("address", idx, mapping)

    # --- Item description vectors ----------------------------
    items = list(
        Item.objects.filter(receipt=rec).values_list("description", flat=True)
    )
    if items:
        idx, mapping = _append_one(
            kind="item_description",
            vectors=model.encode(items),
            labels=items,
        )
        save_index("item_description", idx, mapping)

# Helper that does the actual add() + mapping update
def _append_one(kind: str, vectors, labels):
    """
    • Ensures the index file is cached locally
    • Adds *vectors* to the in-memory FAISS index
    • Extends the mapping dict with *labels*
    Returns the updated (idx, mapping) pair.
    """
    ensure_cached(kind)

    idx = faiss.read_index(str(_local_path(kind)))
    with open(_local_path(kind).with_suffix(".pkl"), "rb") as fh:
        mapping = pickle.load(fh)

    start = idx.ntotal                     # current size before append
    idx.add(vectors.astype("float32"))     # append new vectors
    for i, lbl in enumerate(labels):
        mapping[start + i] = lbl           # extend mapping dict

    return idx, mapping
