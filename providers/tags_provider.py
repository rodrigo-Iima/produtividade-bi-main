import csv
from pathlib import Path
from typing import Dict, List
import re
import unicodedata


def normalize_tag(value: str) -> str:
    """Normalize accents, case and whitespace for tag matching."""
    without_accents = "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )
    return re.sub(r"\s+", " ", without_accents).strip().casefold()


class TagsProvider:

    def __init__(self, csv_path: str | None = None):
        if csv_path is None:
            csv_path = Path(__file__).parent.parent / "resources" / "dim_tags_papel.csv"
        self.csv_path = Path(csv_path)

    def load(self) -> List[Dict[str, str]]:
        with self.csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [
                {
                    "papel": row["Papel"].strip(),
                    "foco": row["Foco"].strip(),
                    "tag_clockify": row["Tag clockify"].strip(),
                }
                for row in reader
            ]
