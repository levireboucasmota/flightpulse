
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]

FILE_PATH = (
    PROJECT_ROOT
    / "data"
    / "bronze"
    / "anac"
    / "vra"
    / "2022"
    / "VRA_20221.csv"
)

DATE_COLUMNS = [
    "Partida Prevista",
    "Partida Real",
    "Chegada Prevista",
    "Chegada Real",
]


def load_data():
    """Carrega o CSV completo preservando os valores originais como texto."""

    df = pd.read_csv(
        FILE_PATH,
        encoding="utf-8-sig",
        sep=";",
        skiprows=1,
        quotechar='"',
        dtype=str,
        keep_default_na=False,
    )

    # Converte campos vazios em valores ausentes.
    df = df.replace(r"^\s*$", pd.NA, regex=True)

    return df


def validate_data(df):
    """Realiza verificações básicas de qualidade."""

    print("\n" + "=" * 55)
    print("1. DIMENSÕES DA BASE")
    print("=" * 55)

    print(f"Registros: {df.shape[0]:,}")
    print(f"Colunas: {df.shape[1]}")

    print("\n" + "=" * 55)
    print("2. VALORES AUSENTES")
    print("=" * 55)

    missing = df.isna().sum()

    for column, quantity in missing.items():
        percentage = (quantity / len(df)) * 100

        print(
            f"{column}: {quantity:,} "
            f"({percentage:.2f}%)"
        )

    print("\n" + "=" * 55)
    print("3. REGISTROS DUPLICADOS")
    print("=" * 55)

    duplicates = df.duplicated().sum()

    print(f"Duplicados completos: {duplicates:,}")

    print("\n" + "=" * 55)
    print("4. SITUAÇÃO DOS VOOS")
    print("=" * 55)

    print(df["Situação Voo"].value_counts(dropna=False))

    print("\n" + "=" * 55)
    print("5. COMPANHIAS E AEROPORTOS")
    print("=" * 55)

    print(
        "Companhias:",
        df["ICAO Empresa Aérea"].nunique()
    )

    print(
        "Aeroportos de origem:",
        df["ICAO Aeródromo Origem"].nunique()
    )

    print(
        "Aeroportos de destino:",
        df["ICAO Aeródromo Destino"].nunique()
    )


def transform_data(df):
    """Converte datas e calcula os atrasos dos voos realizados."""

    for column in DATE_COLUMNS:
        df[column] = pd.to_datetime(
            df[column],
            format="%Y-%m-%d %H:%M:%S",
            errors="coerce",
        )

    realized = df["Situação Voo"].eq("REALIZADO")

    df["Atraso Partida (min)"] = (
        df["Partida Real"] - df["Partida Prevista"]
    ).dt.total_seconds() / 60

    df["Atraso Chegada (min)"] = (
        df["Chegada Real"] - df["Chegada Prevista"]
    ).dt.total_seconds() / 60

    # Não calcula atrasos para voos que não foram realizados.
    df.loc[
        ~realized,
        ["Atraso Partida (min)", "Atraso Chegada (min)"]
    ] = pd.NA

    return df


def analyze_delays(df):
    """Apresenta indicadores iniciais de atraso."""

    realized = df[df["Situação Voo"] == "REALIZADO"]

    print("\n" + "=" * 55)
    print("6. ANÁLISE DOS ATRASOS")
    print("=" * 55)

    print(f"Voos realizados: {len(realized):,}")

    for column in [
        "Atraso Partida (min)",
        "Atraso Chegada (min)",
    ]:
        valid = realized[column].dropna()

        print(f"\n{column}")
        print(f"Registros válidos: {len(valid):,}")
        print(f"Média: {valid.mean():.2f} minutos")
        print(f"Mediana: {valid.median():.2f} minutos")
        print(f"Máximo: {valid.max():.2f} minutos")
        print(f"Mínimo: {valid.min():.2f} minutos")

        print(
            "Atrasos iguais ou superiores a 15 minutos:",
            f"{(valid >= 15).sum():,}"
        )


def main():
    print("=" * 55)
    print("FLIGHTPULSE | DATA VALIDATION")
    print("=" * 55)

    df = load_data()

    validate_data(df)

    df = transform_data(df)

    analyze_delays(df)

    print("\nValidação e transformação concluídas.")


if __name__ == "__main__":
    main()
