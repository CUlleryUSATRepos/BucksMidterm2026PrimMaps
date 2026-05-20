from pathlib import Path
import re
import json

import pandas as pd
import geopandas as gpd
import folium


ROOT = Path(__file__).resolve().parents[1]

PROCESSED_CSV = ROOT / "output" / "processed" / "precinct_results_processed.csv"
MAP_GEOJSON = ROOT / "dashboard_source" / "precinct_main_map.geojson"

OUT_DEM = ROOT / "output" / "maps_dem"
OUT_REP = ROOT / "output" / "maps_rep"

OUT_DEM.mkdir(parents=True, exist_ok=True)
OUT_REP.mkdir(parents=True, exist_ok=True)

# Change this later if you want to include tiny precinct-level races.
# 304 = countywide only.
# 10 = broader local races too.
MIN_PRECINCTS = 10


PARTY_CONFIG = {
    "Dem": {
        "output_dir": OUT_DEM,
        "color": "#1877C9",
        "light": "#D8ECFF",
    },
    "Rep": {
        "output_dir": OUT_REP,
        "color": "#D73027",
        "light": "#FFE0DC",
    },
}


def slugify(s):
    s = str(s).lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:120]


def build_contest_wide(processed, contest_name):
    contest_results = processed.loc[
        processed["Contest Name"].eq(contest_name)
    ].copy()

    contest_wide = (
        contest_results
        .pivot_table(
            index=["precinctid", "municipality_district"],
            columns="Candidate Name",
            values="Votes",
            aggfunc="sum",
            fill_value=0
        )
        .reset_index()
    )

    contest_wide.columns.name = None

    candidate_cols = [
        c for c in contest_wide.columns
        if c not in ["precinctid", "municipality_district"]
    ]

    contest_wide["contest_total_votes"] = contest_wide[candidate_cols].sum(axis=1)

    contest_wide["winner"] = contest_wide[candidate_cols].idxmax(axis=1)
    contest_wide["winner_votes"] = contest_wide[candidate_cols].max(axis=1)

    if len(candidate_cols) > 1:
        contest_wide["second_place_votes"] = (
            contest_wide[candidate_cols]
            .apply(lambda row: row.sort_values(ascending=False).iloc[1], axis=1)
        )
    else:
        contest_wide["second_place_votes"] = 0

    contest_wide["margin_votes"] = contest_wide["winner_votes"] - contest_wide["second_place_votes"]

    contest_wide["margin_pct"] = (
        contest_wide["margin_votes"] / contest_wide["contest_total_votes"] * 100
    ).round(2)

    contest_wide["winner_share_pct"] = (
        contest_wide["winner_votes"] / contest_wide["contest_total_votes"] * 100
    ).round(2)

    contest_wide["contest_name"] = contest_name
    contest_wide["contest_base"] = contest_results["contest_base"].iloc[0]
    contest_wide["contest_party"] = contest_results["contest_party"].iloc[0]

    return contest_wide, candidate_cols


def winner_color(row, party_color, light_color):
    if pd.isna(row.get("contest_total_votes")) or row.get("contest_total_votes", 0) <= 0:
        return "#eeeeee"

    margin = row.get("margin_pct", 0)

    if margin >= 50:
        return party_color
    if margin >= 25:
        return party_color
    if margin >= 10:
        return "#66A9E8" if party_color == "#1877C9" else "#F46D61"

    return light_color


def safe_int(value):
    if pd.isna(value):
        return 0
    return int(value)


def safe_text(value):
    if pd.isna(value):
        return ""
    return str(value)


def make_popup(row, candidate_cols):
    total_votes = safe_int(row.get("contest_total_votes", 0))

    if total_votes == 0:
        return (
            f"<b>{safe_text(row.get('municipality_district', ''))}</b>"
            f"<br><b>{safe_text(row.get('contest_name', ''))}</b>"
            f"<br>No results for this contest in this precinct."
        )

    parts = [
        f"<b>{safe_text(row.get('municipality_district', ''))}</b>",
        f"<br><b>{safe_text(row.get('contest_name', ''))}</b>",
        f"<br>Total votes: {total_votes:,}",
        f"<br>Winner: {safe_text(row.get('winner', ''))}",
        f"<br>Margin: {safe_int(row.get('margin_votes', 0)):,} votes ({row.get('margin_pct', 0)}%)",
        "<hr>",
    ]

    for c in candidate_cols:
        val = safe_int(row.get(c, 0))
        parts.append(f"{c}: {val:,}<br>")

    return "".join(parts)



def build_map_for_contest(map1, processed, contest_name, party):
    contest_wide, candidate_cols = build_contest_wide(processed, contest_name)

    contest_map = map1.merge(
        contest_wide,
        on=["precinctid", "municipality_district"],
        how="left"
    )

    cfg = PARTY_CONFIG[party]

    # Use WGS84 for Folium
    contest_map = contest_map.to_crs(epsg=4326)

    bounds = contest_map.total_bounds
    center_lat = (bounds[1] + bounds[3]) / 2
    center_lon = (bounds[0] + bounds[2]) / 2

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=10,
        tiles="cartodbpositron"
    )

    title_html = f"""
    <div style="
        position: fixed;
        top: 12px;
        left: 50px;
        z-index: 9999;
        background: white;
        padding: 10px 14px;
        border: 1px solid #ccc;
        border-radius: 8px;
        font-family: Arial, sans-serif;
        font-size: 16px;
        max-width: 520px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.18);
    ">
        <b>{contest_name}</b><br>
        Shaded by winner and margin within the {party} primary.
    </div>
    """
    m.get_root().html.add_child(folium.Element(title_html))

    def style_function(feature):
        props = feature["properties"]
        fill = props.get("_fill_color", "#eeeeee")

        return {
            "fillColor": fill,
            "color": "#555555",
            "weight": 0.6,
            "fillOpacity": 0.75,
        }

    contest_map["_fill_color"] = contest_map.apply(
        lambda row: winner_color(row, cfg["color"], cfg["light"]),
        axis=1
    )

    contest_map["_popup"] = contest_map.apply(
        lambda row: make_popup(row, candidate_cols),
        axis=1
    )

    keep_cols = [
        "precinctid",
        "municipality_district",
        "contest_name",
        "contest_total_votes",
        "winner",
        "winner_votes",
        "second_place_votes",
        "margin_votes",
        "margin_pct",
        "winner_share_pct",
        "_fill_color",
        "_popup",
        "geometry",
    ]

    for c in candidate_cols:
        keep_cols.insert(-3, c)

    export_gdf = contest_map[keep_cols].copy()

    folium.GeoJson(
        data=json.loads(export_gdf.to_json()),
        style_function=style_function,
        tooltip=folium.GeoJsonTooltip(
            fields=["municipality_district", "winner", "margin_pct", "contest_total_votes"],
            aliases=["Precinct:", "Winner:", "Margin %:", "Votes:"],
            localize=True,
            sticky=True,
        ),
        popup=folium.GeoJsonPopup(
            fields=["_popup"],
            labels=False,
            max_width=450,
        ),
        name=contest_name,
    ).add_to(m)

    folium.LayerControl().add_to(m)

    out_file = cfg["output_dir"] / f"{slugify(contest_name)}.html"
    m.save(out_file)

    return out_file, contest_wide["precinctid"].nunique()


def main():
    print("Loading processed results...")
    processed = pd.read_csv(PROCESSED_CSV)
    map1 = gpd.read_file(MAP_GEOJSON)

    print("Processed rows:", len(processed))
    print("Map rows:", len(map1))

    contest_summary = (
        processed
        .groupby(["Contest Name", "contest_base", "contest_party"], as_index=False, dropna=False)
        .agg(
            precincts=("precinctid", "nunique"),
            total_votes=("Votes", "sum"),
            candidates=("Candidate Name", "nunique")
        )
        .sort_values(["contest_party", "precincts", "total_votes"], ascending=[True, False, False])
    )

    contest_summary = contest_summary[
        contest_summary["contest_party"].isin(["Dem", "Rep"])
        & contest_summary["precincts"].ge(MIN_PRECINCTS)
    ].copy()

    print("\nContests selected for maps:", len(contest_summary))
    print(contest_summary.head(30).to_string(index=False))

    made = []

    for _, row in contest_summary.iterrows():
        contest_name = row["Contest Name"]
        party = row["contest_party"]

        try:
            out_file, precinct_count = build_map_for_contest(
                map1=map1,
                processed=processed,
                contest_name=contest_name,
                party=party
            )

            made.append({
                "contest_name": contest_name,
                "party": party,
                "precincts": precinct_count,
                "file": str(out_file),
            })

            print(f"Saved {party} map:", out_file)

        except Exception as e:
            print(f"FAILED: {contest_name} -- {e}")

    made_df = pd.DataFrame(made)
    made_df.to_csv(ROOT / "output" / "processed" / "maps_created.csv", index=False)

    print("\nDone.")
    print("Maps created:", len(made_df))
    print("Index saved:", ROOT / "output" / "processed" / "maps_created.csv")


if __name__ == "__main__":
    main()