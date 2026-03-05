from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def main() -> int:
    root = Path(__file__).resolve().parent.parent

    # Prefer .env, fall back to .env.example for validation.
    load_dotenv(root / ".env")
    if not os.environ.get("HF_TOKEN"):
        load_dotenv(root / ".env.example")

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        print("HF_TOKEN present: False")
        print("Set HF_TOKEN in .env (preferred) and re-run.")
        return 2

    print("HF_TOKEN present: True")

    # 1) Validate token
    try:
        from huggingface_hub import whoami

        info = whoami(token=hf_token)
        user = info.get("name") or info.get("fullname") or "<unknown>"
        print("HF whoami ok: True")
        print(f"HF user: {user}")
    except Exception as exc:
        print("HF whoami ok: False")
        print(f"whoami error: {type(exc).__name__}: {exc}")
        return 3

    # 2) Validate dataset access (AfroLingu-MT is gated)
    try:
        from datasets import load_dataset

        ds = load_dataset(
            os.environ.get("AFROLINGU_MT_DATASET_ID", "UBC-NLP/AfroLingu-MT"),
            split="test",
            streaming=True,
            token=hf_token,
        )
        row = next(iter(ds))
        print("AfroLingu-MT access ok: True")
        print("row keys:", sorted(row.keys()))
        print("langcode:", row.get("langcode"))
        return 0
    except TypeError:
        # Compatibility for older datasets.
        from datasets import load_dataset

        ds = load_dataset(
            os.environ.get("AFROLINGU_MT_DATASET_ID", "UBC-NLP/AfroLingu-MT"),
            split="test",
            streaming=True,
            use_auth_token=hf_token,
        )
        row = next(iter(ds))
        print("AfroLingu-MT access ok: True")
        print("row keys:", sorted(row.keys()))
        print("langcode:", row.get("langcode"))
        return 0
    except Exception as exc:
        print("AfroLingu-MT access ok: False")
        print(f"dataset error: {type(exc).__name__}: {exc}")
        print(
            "If you see 401/403: log into Hugging Face, open the dataset page, and accept the access conditions, then re-run."
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
