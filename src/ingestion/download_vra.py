
import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import requests


BASE_URL = (
    "https://sistemas.anac.gov.br/dadosabertos/"
    "Voos%20e%20opera%C3%A7%C3%B5es%20a%C3%A9reas/"
    "Voo%20Regular%20Ativo%20%28VRA%29/"
)

MONTHS = [
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "data" / "bronze" / "anac" / "vra"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"


class LinkParser(HTMLParser):
    """Extrai os links encontrados no índice HTML da ANAC."""

    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for name, value in attrs:
                if name == "href":
                    self.links.append(value)


def calculate_sha256(file_path):
    """Calcula o hash SHA-256 do arquivo baixado."""
    sha256 = hashlib.sha256()

    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


def get_csv_url(session, year, month):
    """Localiza o CSV de um determinado mês no índice da ANAC."""

    month_folder = f"{month:02d} - {MONTHS[month - 1]}/"
    folder_url = urljoin(BASE_URL, f"{year}/{month_folder}")

    response = session.get(folder_url, timeout=30)

    if response.status_code == 404:
        return None

    response.raise_for_status()

    parser = LinkParser()
    parser.feed(response.text)

    expected_filename = f"VRA_{year}{month}.csv"

    for link in parser.links:
        if link.rstrip("/").endswith(expected_filename):
            return urljoin(folder_url, link)

    return None


def download_file(session, url, destination):
    """Baixa o CSV sem manter todo o conteúdo na memória."""

    temporary_file = destination.with_suffix(".csv.part")

    with session.get(url, stream=True, timeout=(30, 180)) as response:
        response.raise_for_status()

        with open(temporary_file, "wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file.write(chunk)

    temporary_file.replace(destination)


def load_manifest():
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, "r", encoding="utf-8") as file:
            return json.load(file)

    return []


def save_manifest(manifest):
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(MANIFEST_PATH, "w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=4, ensure_ascii=False)


def ingest_month(session, year, month, manifest):
    filename = f"VRA_{year}{month}.csv"
    destination = OUTPUT_DIR / str(year) / filename

    # Evita baixar novamente um arquivo já registrado.
    existing = next(
        (
            item for item in manifest
            if item["filename"] == filename
            and item["year"] == year
            and item["month"] == month
        ),
        None,
    )

    if destination.exists() and existing:
        print(f"[EXISTENTE] {filename}")
        return

    print(f"[BUSCANDO] {filename}")

    try:
        url = get_csv_url(session, year, month)

        if url is None:
            print(f"[INDISPONÍVEL] {year}-{month:02d}")
            return

        destination.parent.mkdir(parents=True, exist_ok=True)

        download_file(session, url, destination)

        metadata = {
            "year": year,
            "month": month,
            "filename": filename,
            "source_url": url,
            "downloaded_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "size_bytes": destination.stat().st_size,
            "sha256": calculate_sha256(destination),
        }

        manifest[:] = [
            item for item in manifest
            if not (
                item["year"] == year
                and item["month"] == month
            )
        ]

        manifest.append(metadata)
        save_manifest(manifest)

        print(
            f"[OK] {filename} | "
            f"{metadata['size_bytes']:,} bytes"
        )

    except requests.RequestException as error:
        print(f"[ERRO] {filename}: {error}")


def main():
    parser = argparse.ArgumentParser(
        description="Download dos arquivos VRA da ANAC."
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Baixa todos os meses de 2022 a 2026.",
    )

    parser.add_argument("--year", type=int, default=2022)
    parser.add_argument("--month", type=int, default=1)

    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({
        "User-Agent": "FlightPulse-DataPipeline/1.0"
    })

    manifest = load_manifest()

    if args.all:
        periods = [
            (year, month)
            for year in range(2022, 2027)
            for month in range(1, 13)
        ]
    else:
        if args.year < 2000 or not 1 <= args.month <= 12:
            parser.error("Informe um ano e mês válidos.")

        periods = [(args.year, args.month)]

    print("=" * 55)
    print("FLIGHTPULSE | ANAC VRA INGESTION")
    print("=" * 55)

    for year, month in periods:
        ingest_month(session, year, month, manifest)
        time.sleep(0.3)

    print("\nProcesso de ingestão finalizado.")
    print(f"Arquivos registrados: {len(manifest)}")


if __name__ == "__main__":
    main()
