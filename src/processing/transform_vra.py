
from pathlib import Path

import re
import pandas as pd


# --------------------------------------------------
# 1. CONFIGURAÇÕES
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

BRONZE_DIR = (
    PROJECT_ROOT
    / "data"
    / "bronze"
    / "anac"
    / "vra"
)

SILVER_DIR = PROJECT_ROOT / "data" / "silver"


# --------------------------------------------------
# 2. PADRONIZAÇÃO DAS COLUNAS
# --------------------------------------------------

COLUMN_MAPPING = {
    "ICAO Empresa Aérea": "airline_icao",
    "Número Voo": "flight_number",
    "Código Autorização (DI)": "authorization_code",
    "Código Tipo Linha": "line_type",
    "ICAO Aeródromo Origem": "origin_icao",
    "ICAO Aeródromo Destino": "destination_icao",
    "Partida Prevista": "scheduled_departure",
    "Partida Real": "actual_departure",
    "Chegada Prevista": "scheduled_arrival",
    "Chegada Real": "actual_arrival",
    "Situação Voo": "flight_status",
    "Código Justificativa": "justification_code",
}

DATE_COLUMNS = [
    "scheduled_departure",
    "actual_departure",
    "scheduled_arrival",
    "actual_arrival",
]


# --------------------------------------------------
# 3. IDENTIFICAÇÃO DO ANO E MÊS
# --------------------------------------------------

def get_file_period(file_path: Path) -> tuple[int, int]:
    """
    Extrai ano e mês do nome do arquivo.

    Exemplo:
    VRA_20221.csv -> ano 2022, mês 1
    """

    match = re.fullmatch(r"VRA_(\d{4})(\d{1,2})", file_path.stem)

    if not match:
        raise ValueError(
            f"Nome de arquivo fora do padrão esperado: {file_path.name}"
        )

    year = int(match.group(1))
    month = int(match.group(2))

    if not 1 <= month <= 12:
        raise ValueError(f"Mês inválido no arquivo: {file_path.name}")

    return year, month


# --------------------------------------------------
# 4. LEITURA DOS DADOS BRONZE
# --------------------------------------------------

def read_bronze(file_path: Path) -> pd.DataFrame:

    if not file_path.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado: {file_path}"
        )

    return pd.read_csv(
        file_path,
        encoding="utf-8-sig",
        sep=";",
        skiprows=1,
        quotechar='"',
        dtype=str,
        keep_default_na=False,
    )


# --------------------------------------------------
# 5. LIMPEZA E PADRONIZAÇÃO
# --------------------------------------------------

def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:

    df = df.rename(columns=COLUMN_MAPPING)

    expected_columns = list(COLUMN_MAPPING.values())

    missing_columns = [
        col for col in expected_columns
        if col not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Colunas ausentes: {missing_columns}"
        )

    df = df[expected_columns].copy()

    for column in df.columns:
        df[column] = df[column].str.strip()

    for column in DATE_COLUMNS:
        df[column] = df[column].replace(
            ["", "null", "NULL", "None"],
            pd.NA
        )

        df[column] = pd.to_datetime(
            df[column],
            format="mixed",
            errors="coerce",
        )

    return df


# --------------------------------------------------
# 6. CRIAÇÃO DOS INDICADORES
# --------------------------------------------------

def create_metrics(df: pd.DataFrame) -> pd.DataFrame:

    df = df.copy()

    realized = df["flight_status"].eq("REALIZADO")

    # Atraso de partida
    df["departure_delay_min"] = (
        df["actual_departure"]
        - df["scheduled_departure"]
    ).dt.total_seconds() / 60

    # Atraso de chegada
    df["arrival_delay_min"] = (
        df["actual_arrival"]
        - df["scheduled_arrival"]
    ).dt.total_seconds() / 60

    # Não calcula atrasos para voos não realizados
    df.loc[
        ~realized,
        ["departure_delay_min", "arrival_delay_min"]
    ] = pd.NA

    # Deslocamento entre as datas de partida
    df["departure_date_shift_days"] = (
        df["actual_departure"].dt.normalize()
        - df["scheduled_departure"].dt.normalize()
    ).dt.days

    # Indicadores de qualidade
    df["is_cancelled"] = df["flight_status"].eq("CANCELADO")

    df["has_missing_schedule"] = (
        realized
        & (
            df["scheduled_departure"].isna()
            | df["scheduled_arrival"].isna()
        )
    )

    # Atrasos extremos: mantém NA quando não é possível calcular
    df["is_extreme_departure_delay"] = pd.Series(
        pd.NA,
        index=df.index,
        dtype="boolean",
    )

    valid_departure_delay = (
        realized
        & df["departure_delay_min"].notna()
    )

    df.loc[
        valid_departure_delay,
        "is_extreme_departure_delay"
    ] = (
        df.loc[
            valid_departure_delay,
            "departure_delay_min"
        ] > 1440
    )

    # Mudança de data: mantém NA quando não é possível calcular
    df["has_departure_date_shift"] = pd.Series(
        pd.NA,
        index=df.index,
        dtype="boolean",
    )

    valid_date_shift = (
        realized
        & df["departure_date_shift_days"].notna()
    )

    df.loc[
        valid_date_shift,
        "has_departure_date_shift"
    ] = (
        df.loc[
            valid_date_shift,
            "departure_date_shift_days"
        ] != 0
    )

    return df


# --------------------------------------------------
# 7. TRANSFORMAÇÃO DE UM ARQUIVO
# --------------------------------------------------

def transform_file(file_path: Path) -> dict:

    year, month = get_file_period(file_path)

    print(f"\nProcessando: {file_path.name}")

    # Leitura
    df = read_bronze(file_path)

    # Padronização
    df = standardize_columns(df)

    # Indicadores
    df = create_metrics(df)

    # Rastreabilidade da origem
    df["source_year"] = year
    df["source_month"] = month

    # Caminho de saída
    output_dir = SILVER_DIR / str(year)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = (
        output_dir
        / f"vra_{year}_{month:02d}.parquet"
    )

    # Salvamento
    df.to_parquet(
        output_file,
        index=False,
        engine="pyarrow",
        compression="snappy",
    )

    summary = {
        "year": year,
        "month": month,
        "records": len(df),
        "realized": int(df["flight_status"].eq("REALIZADO").sum()),
        "cancelled": int(df["is_cancelled"].sum()),
        "extreme_delays": int(
            df["is_extreme_departure_delay"].sum()
        ),
        "date_shifts": int(
            df["has_departure_date_shift"].sum()
        ),
        "missing_schedule": int(
            df["has_missing_schedule"].sum()
        ),
        "output": output_file,
    }

    print(f"Registros: {summary['records']:,}")
    print(f"Realizados: {summary['realized']:,}")
    print(f"Cancelados: {summary['cancelled']:,}")
    print(f"Salvo em: {output_file}")

    return summary


# --------------------------------------------------
# 8. PIPELINE COMPLETO
# --------------------------------------------------


def main():

    print("=" * 55)
    print("FLIGHTPULSE - TRANSFORMAÇÃO BRONZE PARA SILVER")
    print("=" * 55)

    files = sorted(BRONZE_DIR.rglob("VRA_*.csv"))

    if not files:
        raise FileNotFoundError(
            f"Nenhum arquivo CSV encontrado em: {BRONZE_DIR}"
        )

    print(f"\nArquivos encontrados: {len(files)}")

    summaries = []
    errors = []

    for file_path in files:
        try:
            summary = transform_file(file_path)
            summaries.append(summary)

        except Exception as error:
            errors.append({
                "file": file_path.name,
                "error": str(error),
            })

            print(f"ERRO em {file_path.name}: {error}")

    # Resumo geral
    total_records = sum(
        item["records"] for item in summaries
    )

    total_realized = sum(
        item["realized"] for item in summaries
    )

    total_cancelled = sum(
        item["cancelled"] for item in summaries
    )

    total_extreme_delays = sum(
        item["extreme_delays"] for item in summaries
    )

    total_date_shifts = sum(
        item["date_shifts"] for item in summaries
    )

    total_missing_schedule = sum(
        item["missing_schedule"] for item in summaries
    )

    print("\n" + "=" * 55)
    print("RESUMO FINAL DA CAMADA SILVER")
    print("=" * 55)

    print(f"Arquivos encontrados: {len(files)}")
    print(f"Arquivos processados: {len(summaries)}")
    print(f"Arquivos com erro: {len(errors)}")
    print(f"Total de registros: {total_records:,}")
    print(f"Voos realizados: {total_realized:,}")
    print(f"Voos cancelados: {total_cancelled:,}")
    print(f"Atrasos extremos: {total_extreme_delays:,}")
    print(f"Mudanças de data: {total_date_shifts:,}")
    print(f"Horários previstos ausentes: {total_missing_schedule:,}")

    if errors:
        print("\nARQUIVOS COM ERRO:")

        for item in errors:
            print(f"- {item['file']}: {item['error']}")

    print(f"\nDiretório de saída: {SILVER_DIR}")


if __name__ == "__main__":
    main()
