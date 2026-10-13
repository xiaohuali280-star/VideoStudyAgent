import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

if __name__ == "__main__":
    schema = create_app(Settings(_env_file=None)).openapi()
    (BACKEND_ROOT / "openapi.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("Exported backend/openapi.json")
