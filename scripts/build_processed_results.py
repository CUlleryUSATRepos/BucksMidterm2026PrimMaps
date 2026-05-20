from pathlib import Path
import re
import pandas as pd
import geopandas as gpd


ROOT = Path(__file__).resolve().parents[1]

RESULTS_CSV = ROOT / "Precincts_19.csv"
MAP_GEOJSON = ROOT / "dashboard_source" / "precinct_main_map.geojson"

OUT_DIR = ROOT / "output" / "processed"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OUT_CSV = OUT_DIR / "precinct_results_processed.csv"


def normalize_precinct_name(s):
    if pd.isna(s):
        return ""

    s = str(s).upper().strip()
    s = s.replace(".", "")
    s = s.replace("#", "")

    s = re.sub(r"\bTWP\b", "TOWNSHIP", s)
    s = re.sub(r"\bBORO\b", "BOROUGH", s)
    s = re.sub(r"\bDIST\b", "DISTRICT", s)
    s = re.sub(r"\bWD\b", "WARD", s)
    s = re.sub(r"\bSAINT\b", "ST", s)

    s = s.replace("RIEGLESVILLE", "RIEGELSVILLE")

    s = re.sub(r"\b(HILLTOWN TOWNSHIP FAIRHILL 2)A\b", r"\1", s)
    s = re.sub(r"\b(NEW BRITAIN TOWNSHIP WEST 2)A\b", r"\1", s)

    s = re.sub(r"\b(\d+)(ST|ND|RD|TH)\b", lambda m: m.group(1), s)
    s = re.sub(r"\s*-\s*", " - ", s)

    s = re.sub(r"\bDISTRICT\b", "", s)
    s = re.sub(r"\bWARD\b", "", s)

    s = re.sub(r"\s+", " ", s).strip()
    return s


def split_primary_contest_name(contest_name):
    if pd.isna(contest_name):
        return pd.Series([None, None])

    s = str(contest_name).strip()
    match = re.match(r"^(.*?)\s*\((Dem|Rep|Lib|Grn|Ind|NP)\)\s*$", s, flags=re.I)

    if match:
        return pd.Series([match.group(1).strip(), match.group(2).strip()])

    return pd.Series([s, None])


def clean_votes(v):
    if pd.isna(v):
        return 0

    return pd.to_numeric(
        str(v).replace(",", "").strip(),
        errors="coerce"
    )


def main():
    print("Loading files...")
    results = pd.read_csv(RESULTS_CSV, skiprows=2)
    map1 = gpd.read_file(MAP_GEOJSON)

    print("Results rows:", len(results))
    print("Map rows:", len(map1))

    results["result_precinct_key"] = results["Precinct"].apply(normalize_precinct_name)
    map1["map_precinct_key"] = map1["municipality_district"].apply(normalize_precinct_name)

    precinct_lookup = (
        map1[["precinctid", "municipality_district", "map_precinct_key"]]
        .drop_duplicates()
    )

    dup_map_keys = precinct_lookup[
        precinct_lookup["map_precinct_key"].duplicated(keep=False)
    ].sort_values("map_precinct_key")

    if len(dup_map_keys):
        print("\nWARNING: duplicated normalized map keys")
        print(dup_map_keys.to_string(index=False))

    matched = results.merge(
        precinct_lookup,
        left_on="result_precinct_key",
        right_on="map_precinct_key",
        how="left"
    )

    unmatched_results = (
        matched.loc[matched["precinctid"].isna(), ["Precinct", "result_precinct_key"]]
        .drop_duplicates()
        .sort_values("Precinct")
    )

    matched_keys = set(results["result_precinct_key"].dropna().unique())
    unmatched_map = (
        map1.loc[
            ~map1["map_precinct_key"].isin(matched_keys),
            ["precinctid", "municipality_district", "map_precinct_key"]
        ]
        .drop_duplicates()
        .sort_values("municipality_district")
    )

    print("\nUnmatched result precinct names:", len(unmatched_results))
    if len(unmatched_results):
        print(unmatched_results.to_string(index=False))

    print("Map precincts with no result match:", len(unmatched_map))
    if len(unmatched_map):
        print(unmatched_map.to_string(index=False))

    if len(unmatched_results) or len(unmatched_map):
        raise ValueError("Precinct matching failed. Fix unmatched precincts before continuing.")

    matched["Votes_clean"] = matched["Votes"].apply(clean_votes).fillna(0).astype(int)

    matched[["contest_base", "contest_party"]] = matched["Contest Name"].apply(
        split_primary_contest_name
    )

    processed = (
        matched
        .groupby(
            [
                "precinctid",
                "municipality_district",
                "Contest Name",
                "contest_base",
                "contest_party",
                "Candidate Name",
            ],
            as_index=False,
            dropna=False
        )
        .agg(
            Votes=("Votes_clean", "sum")
        )
        .sort_values(
            [
                "contest_base",
                "contest_party",
                "precinctid",
                "Candidate Name",
            ]
        )
    )

    processed.to_csv(OUT_CSV, index=False)

    print("\nSaved:", OUT_CSV)
    print("Processed rows:", len(processed))
    print("Processed precinctids:", processed["precinctid"].nunique())
    print("Contests:", processed["Contest Name"].nunique())

    print("\nContest/party preview:")
    preview = (
        processed[["Contest Name", "contest_base", "contest_party"]]
        .drop_duplicates()
        .sort_values(["contest_base", "contest_party"])
    )
    print(preview.head(40).to_string(index=False))


if __name__ == "__main__":
    main()