"""Export the canonical dataset JSON Schema → shared/schemas/dataset.schema.json.

    python -m scripts.export_dataset_schema
"""
import json
from pathlib import Path

from core.models import Dataset

out = Path(__file__).resolve().parents[2] / "shared" / "schemas" / "dataset.schema.json"
schema = Dataset.model_json_schema()
schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
schema["title"] = "ResQWork dataset"
schema["description"] = ("One organization's employees, shifts and existing schedule. Upload as JSON, "
                         "or as CSV (converted to this shape server-side).")
out.write_text(json.dumps(schema, indent=2) + "\n")
print(f"wrote {out}")
