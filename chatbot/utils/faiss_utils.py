from pathlib import Path
import os, tempfile, pickle, numpy as np, faiss
from sentence_transformers import SentenceTransformer
from django.conf import settings
from receipt_mgmt.models import Receipt, Item
from chatbot.azure_blob import download_latest, upload_version

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
    Ensure both the FAISS index file and its *.pkl mapping
    are present in settings.FAISS_CACHE_DIR.
    Downloads each blob once per worker lifetime.
    """
    idx_path = _local_path(kind)                     # …/company_index.faiss
    map_path = idx_path.with_suffix(".pkl")          # …/company_index.pkl

    if not idx_path.exists():
        download_latest(kind, idx_path)              # company_latest.faiss

    if not map_path.exists():
        download_latest(f"{kind}_mapping", map_path) # company_mapping_latest.faiss



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

# ──────────────────────────────────────────────────────────────
# 1 NIGHTLY FULL REBUILD
# ──────────────────────────────────────────────────────────────
def full_rebuild():
    """
    Build brand-new indexes (calling create_faiss_indexes) in a temp dir,
    upload them to Azure, then swap each worker’s cache copy in place.
    """
    from .faiss_full_builder import create_faiss_indexes
    tmp_dir = Path(tempfile.mkdtemp())        # e.g. /tmp/tmpabcdef
    create_faiss_indexes(tmp_dir)             # heavy DB scan happens here

    for kind in ("company", "address", "item_description"):
        upload_version(kind, tmp_dir / f"{kind}_index.faiss")   # remote
        # refresh local cache so current worker sees new file immediately
        _local_path(kind).parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp_dir / f"{kind}_index.faiss", _local_path(kind))

# ──────────────────────────────────────────────────────────────
# 2 APPEND-ON-UPLOAD PATH
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
