from pathlib import Path
import json
import re

import pandas as pd
import geopandas as gpd


ROOT = Path(__file__).resolve().parents[1]

PROCESSED_CSV = ROOT / "output" / "processed" / "precinct_results_processed.csv"
MAP_GEOJSON = ROOT / "dashboard_source" / "precinct_main_map.geojson"
PARTY_COUNTS_CSV = ROOT / "dashboard_source" / "precinct_split_party_counts.csv"
OUT_HTML = ROOT / "output" / "primary_results_dashboard.html"

MIN_PRECINCTS = 10


def slugify(s):
    s = str(s).lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:100]


def build_contest_payload(processed, contest_name, contest_key, party_counts):
    contest_results = processed.loc[processed["Contest Name"].eq(contest_name)].copy()

    wide = (
        contest_results
        .pivot_table(
            index=["precinctid", "municipality_district"],
            columns="Candidate Name",
            values="Votes",
            aggfunc="sum",
            fill_value=0,
        )
        .reset_index()
    )

    wide.columns.name = None

    candidate_cols = [
        c for c in wide.columns
        if c not in ["precinctid", "municipality_district"]
    ]

    candidate_totals = wide[candidate_cols].sum().sort_values(ascending=False)
    candidate_cols = candidate_totals.index.tolist()

    wide["contest_total_votes"] = wide[candidate_cols].sum(axis=1)
    wide["winner"] = wide[candidate_cols].idxmax(axis=1)
    wide["winner_votes"] = wide[candidate_cols].max(axis=1)

    if len(candidate_cols) > 1:
        wide["second_place_votes"] = wide[candidate_cols].apply(
            lambda row: row.sort_values(ascending=False).iloc[1],
            axis=1,
        )
    else:
        wide["second_place_votes"] = 0

    wide["margin_votes"] = wide["winner_votes"] - wide["second_place_votes"]
    wide["margin_pct"] = (
        wide["margin_votes"] / wide["contest_total_votes"] * 100
    ).round(2)

    contest_party = str(contest_results["contest_party"].iloc[0])

    party_lookup = {}
    for _, prow in party_counts.iterrows():
        precinctid = str(prow["precinctid"])
        party_lookup[precinctid] = {
            "D_registered": int(prow.get("D", 0)) if not pd.isna(prow.get("D", 0)) else 0,
            "R_registered": int(prow.get("R", 0)) if not pd.isna(prow.get("R", 0)) else 0,
            "Oth_registered": int(prow.get("Oth", 0)) if not pd.isna(prow.get("Oth", 0)) else 0,
            "total_registered": int(prow.get("total_voters", 0)) if not pd.isna(prow.get("total_voters", 0)) else 0,
        }

    by_precinct = {}

    for _, row in wide.iterrows():
        precinctid = str(row["precinctid"])
        total_votes = int(row["contest_total_votes"]) if not pd.isna(row["contest_total_votes"]) else 0

        reg = party_lookup.get(
            precinctid,
            {
                "D_registered": 0,
                "R_registered": 0,
                "Oth_registered": 0,
                "total_registered": 0,
            },
        )

        if contest_party == "Dem":
            party_registered = reg["D_registered"]
        elif contest_party == "Rep":
            party_registered = reg["R_registered"]
        else:
            party_registered = 0

        party_turnout_rate_pct = (
            round(total_votes / party_registered * 100, 2)
            if party_registered
            else 0
        )

        candidates = {}
        for c in candidate_cols:
            value = row.get(c, 0)
            candidates[c] = int(value) if not pd.isna(value) else 0

        by_precinct[precinctid] = {
            "precinctid": precinctid,
            "municipality_district": str(row["municipality_district"]),
            "total_votes": total_votes,
            "winner": str(row["winner"]) if not pd.isna(row["winner"]) else "",
            "winner_votes": int(row["winner_votes"]) if not pd.isna(row["winner_votes"]) else 0,
            "second_place_votes": int(row["second_place_votes"]) if not pd.isna(row["second_place_votes"]) else 0,
            "margin_votes": int(row["margin_votes"]) if not pd.isna(row["margin_votes"]) else 0,
            "margin_pct": float(row["margin_pct"]) if not pd.isna(row["margin_pct"]) else 0,
            "D_registered": reg["D_registered"],
            "R_registered": reg["R_registered"],
            "Oth_registered": reg["Oth_registered"],
            "total_registered": reg["total_registered"],
            "party_registered": party_registered,
            "party_turnout_rate_pct": party_turnout_rate_pct,
            "candidates": candidates,
        }

    precinct_ids = set(str(x) for x in wide["precinctid"].unique())

    party_col = "D" if contest_party == "Dem" else "R" if contest_party == "Rep" else None
    party_registered_total = 0

    if party_col:
        party_registered_total = int(
            party_counts.loc[
                party_counts["precinctid"].astype(str).isin(precinct_ids),
                party_col,
            ].fillna(0).sum()
        )

    total_votes_cast_in_race = int(candidate_totals.sum())
    party_turnout_rate_total_pct = (
        round(total_votes_cast_in_race / party_registered_total * 100, 2)
        if party_registered_total
        else 0
    )

    max_rate = max([p["party_turnout_rate_pct"] for p in by_precinct.values()] or [0])

    return {
        "key": contest_key,
        "contest_name": contest_name,
        "contest_base": contest_results["contest_base"].iloc[0],
        "contest_party": contest_party,
        "candidate_totals": {k: int(v) for k, v in candidate_totals.items()},
        "candidate_cols": candidate_cols,
        "party_registered_total": party_registered_total,
        "total_votes_cast_in_race": total_votes_cast_in_race,
        "party_turnout_rate_total_pct": party_turnout_rate_total_pct,
        "max_rate": max_rate,
        "by_precinct": by_precinct,
    }


def main():
    print("Loading data...")

    processed = pd.read_csv(PROCESSED_CSV)
    map1 = gpd.read_file(MAP_GEOJSON)

    party_counts = pd.read_csv(PARTY_COUNTS_CSV)
    if "precinct_split_id" in party_counts.columns and "precinctid" not in party_counts.columns:
        party_counts = party_counts.rename(columns={"precinct_split_id": "precinctid"})

    party_counts["precinctid"] = party_counts["precinctid"].astype(str).str.strip()

    print("Party-count rows:", len(party_counts))

    if map1.crs is None:
        map1 = map1.set_crs(4326)
    else:
        map1 = map1.to_crs(4326)

    contest_summary = (
        processed
        .groupby(["Contest Name", "contest_base", "contest_party"], as_index=False, dropna=False)
        .agg(
            precincts=("precinctid", "nunique"),
            total_votes=("Votes", "sum"),
            candidates=("Candidate Name", "nunique"),
        )
        .sort_values(
            ["contest_party", "precincts", "total_votes"],
            ascending=[True, False, False],
        )
    )

    contest_summary = contest_summary[
        contest_summary["contest_party"].isin(["Dem", "Rep"])
        & contest_summary["precincts"].ge(MIN_PRECINCTS)
    ].copy()

    print("Contests included:", len(contest_summary))

    contests = []
    contest_data = {}

    for i, row in contest_summary.reset_index(drop=True).iterrows():
        contest_name = row["Contest Name"]
        contest_key = f"{slugify(contest_name)}_{i}"

        contests.append(
            {
                "key": contest_key,
                "name": contest_name,
                "base": row["contest_base"],
                "party": row["contest_party"],
                "precincts": int(row["precincts"]),
                "total_votes": int(row["total_votes"]),
                "candidates": int(row["candidates"]),
            }
        )

        contest_data[contest_key] = build_contest_payload(
            processed=processed,
            contest_name=contest_name,
            contest_key=contest_key,
            party_counts=party_counts,
        )

    geo = map1[["precinctid", "municipality_district", "geometry"]].copy()
    precinct_geojson = json.loads(geo.to_json())

    html_template = r"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Bucks County Primary Results Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

  <style>
    html, body {
      margin: 0;
      padding: 0;
      height: 100%;
      font-family: Arial, sans-serif;
    }

    #map {
      height: 100vh;
      width: 100vw;
    }

    #panel {
      position: absolute;
      top: 12px;
      left: 12px;
      z-index: 9999;
      background: white;
      padding: 12px;
      border-radius: 10px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.25);
      width: 405px;
      max-width: calc(100vw - 40px);
      max-height: calc(100vh - 35px);
      overflow-y: auto;
    }

    #panel h2 {
      margin: 0 0 8px 0;
      font-size: 18px;
    }

    label {
      display: block;
      font-weight: bold;
      margin-top: 8px;
      margin-bottom: 4px;
      font-size: 13px;
    }

    select {
      width: 100%;
      padding: 7px;
      font-size: 14px;
    }

    #summary, #legend {
      margin-top: 10px;
      font-size: 13px;
      line-height: 1.35;
    }

    .swatch {
      display: inline-block;
      width: 13px;
      height: 13px;
      border: 1px solid #777;
      vertical-align: middle;
      margin-right: 5px;
    }

    .note {
      color: #555;
      font-size: 12px;
      margin-top: 6px;
    }

    .leaflet-popup-content {
      font-size: 13px;
    }

    .leaflet-tooltip.result-tooltip {
      white-space: normal;
      width: 430px;
      max-width: 430px;
      line-height: 1.35;
      font-size: 12px;
      padding: 8px 10px;
    }

    .tooltip-title {
      font-weight: bold;
      font-size: 13px;
      margin-bottom: 2px;
    }

    .tooltip-contest {
      font-size: 12px;
      color: #444;
      margin-bottom: 7px;
      border-bottom: 1px solid #ddd;
      padding-bottom: 5px;
    }

    .tooltip-table {
      border-collapse: collapse;
      width: 100%;
      margin-top: 4px;
      margin-bottom: 6px;
      table-layout: fixed;
    }

    .tooltip-table td {
      padding: 2px 4px;
      border-bottom: 1px solid #eee;
      vertical-align: top;
    }

    .tooltip-table td:first-child {
      width: 82%;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .tooltip-table td:last-child {
      width: 18%;
      text-align: right;
      font-weight: bold;
      white-space: nowrap;
    }

    .tooltip-meta {
      margin-top: 6px;
      color: #333;
    }

    #detailsToggle {
      display: none;
      width: 100%;
      margin-top: 8px;
      padding: 7px;
      border: 1px solid #aaa;
      background: #f7f7f7;
      border-radius: 6px;
      font-size: 13px;
      cursor: pointer;
    }

    @media (max-width: 700px) {
      #panel {
        top: 8px;
        left: 8px;
        right: 8px;
        width: auto;
        max-width: none;
        max-height: 38vh;
        padding: 10px;
        border-radius: 9px;
        overflow-y: auto;
      }

      #panel.expanded {
        max-height: 62vh;
      }

      #panel h2 {
        font-size: 16px;
        margin-bottom: 6px;
      }

      label {
        font-size: 12px;
        margin-top: 6px;
        margin-bottom: 3px;
      }

      select {
        font-size: 13px;
        padding: 6px;
      }

      #detailsToggle {
        display: block;
      }

      #panel:not(.expanded) #summary,
      #panel:not(.expanded) #legend {
        display: none;
      }

      #summary, #legend {
        font-size: 12px;
        line-height: 1.3;
      }

      .note {
        font-size: 11px;
      }

      .leaflet-top.leaflet-left {
        top: 160px;
      }

      .leaflet-tooltip.result-tooltip {
        width: 310px;
        max-width: 310px;
        font-size: 11px;
      }

      .tooltip-title {
        font-size: 12px;
      }

      .tooltip-contest {
        font-size: 11px;
      }

      .tooltip-table td:first-child {
        width: 78%;
        max-width: 230px;
      }

      .tooltip-table td:last-child {
        width: 22%;
      }
    }

    @media (max-width: 430px) {
      #panel {
        max-height: 34vh;
      }

      #panel.expanded {
        max-height: 58vh;
      }

      .leaflet-top.leaflet-left {
        top: 145px;
      }

      .leaflet-tooltip.result-tooltip {
        width: 280px;
        max-width: 280px;
      }

      .tooltip-table td:first-child {
        max-width: 205px;
      }
    }

    @media (max-width: 700px) {
      #panel {
        top: 8px;
        left: 8px;
        right: 8px;
        width: auto;
        max-width: none;
        max-height: 46vh;
        padding: 10px;
        border-radius: 9px;
      }

      #panel h2 {
        font-size: 16px;
        margin-bottom: 6px;
      }

      label {
        font-size: 12px;
        margin-top: 6px;
        margin-bottom: 3px;
      }

      select {
        font-size: 13px;
        padding: 6px;
      }

      #summary, #legend {
        font-size: 12px;
        line-height: 1.3;
      }

      .note {
        font-size: 11px;
      }

      .leaflet-top.leaflet-left {
        top: 48vh;
      }

      .leaflet-tooltip.result-tooltip {
        width: 310px;
        max-width: 310px;
        font-size: 11px;
      }

      .tooltip-title {
        font-size: 12px;
      }

      .tooltip-contest {
        font-size: 11px;
      }

      .tooltip-table td:first-child {
        width: 78%;
        max-width: 230px;
      }

      .tooltip-table td:last-child {
        width: 22%;
      }
    }

    @media (max-width: 430px) {
      #panel {
        max-height: 42vh;
      }

      .leaflet-top.leaflet-left {
        top: 44vh;
      }

      .leaflet-tooltip.result-tooltip {
        width: 280px;
        max-width: 280px;
      }

      .tooltip-table td:first-child {
        max-width: 205px;
      }
    }
  </style>
</head>

<body>
  <div id="panel">
    <h2>Bucks County primary results</h2>

    <label for="partySelect">Primary</label>
    <select id="partySelect">
      <option value="Dem">Democratic</option>
      <option value="Rep">Republican</option>
    </select>

    <label for="contestSelect">Race</label>
    <select id="contestSelect"></select>

    <button id="detailsToggle" type="button">Show race details</button>

    <div id="summary"></div>
    <div id="legend"></div>
  </div>

  <div id="map"></div>

  <script>
    const precinctGeoJson = __PRECINCT_GEOJSON__;
    const contests = __CONTESTS__;
    const contestData = __CONTEST_DATA__;

    const panel = document.getElementById("panel");
    const partySelect = document.getElementById("partySelect");
    const contestSelect = document.getElementById("contestSelect");
    const detailsToggle = document.getElementById("detailsToggle");
    const summaryDiv = document.getElementById("summary");
    const legendDiv = document.getElementById("legend");

    const map = L.map("map");

    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
      attribution: "&copy; OpenStreetMap contributors &copy; CARTO"
    }).addTo(map);

    const geoLayer = L.geoJson(precinctGeoJson, {
      style: styleFeature,
      onEachFeature: function(feature, layer) {
        layer.bindTooltip("", {
          sticky: true,
          direction: "auto",
          className: "result-tooltip"
        });
        layer.bindPopup("");
      }
    }).addTo(map);

    map.fitBounds(geoLayer.getBounds());

    function getActiveContest() {
      return contestData[contestSelect.value];
    }

    function getPrecinctData(feature) {
      const active = getActiveContest();
      if (!active) return null;
      const precinctid = String(feature.properties.precinctid);
      return active.by_precinct[precinctid] || null;
    }

    function partyGradientColor(data, active) {
      const maxRate = Number(active.max_rate || 0);
      const rate = Number(data.party_turnout_rate_pct || 0);
      const ratio = maxRate ? Math.max(0, Math.min(1, rate / maxRate)) : 0;

      if (active.contest_party === "Dem") {
        if (ratio >= 0.80) return "#084594";
        if (ratio >= 0.60) return "#2171b5";
        if (ratio >= 0.40) return "#4292c6";
        if (ratio >= 0.20) return "#9ecae1";
        if (ratio > 0) return "#deebf7";
        return "#eeeeee";
      }

      if (active.contest_party === "Rep") {
        if (ratio >= 0.80) return "#99000d";
        if (ratio >= 0.60) return "#cb181d";
        if (ratio >= 0.40) return "#ef3b2c";
        if (ratio >= 0.20) return "#fb6a4a";
        if (ratio > 0) return "#fee5d9";
        return "#eeeeee";
      }

      return "#eeeeee";
    }

    function styleFeature(feature) {
      const active = getActiveContest();
      const data = getPrecinctData(feature);

      if (!active || !data || !data.total_votes || data.total_votes <= 0) {
        return {
          fillColor: "#eeeeee",
          color: "#555",
          weight: 0.6,
          fillOpacity: 0.42
        };
      }

      return {
        fillColor: partyGradientColor(data, active),
        color: "#555",
        weight: 0.6,
        fillOpacity: 0.82
      };
    }

    function candidateRowsHtml(data, active) {
      let html = "";
      for (const name of active.candidate_cols) {
        const votes = data.candidates[name] || 0;
        html += `
          <tr>
            <td title="${name}">${name}</td>
            <td>${Number(votes).toLocaleString()}</td>
          </tr>
        `;
      }
      return html;
    }

    function popupHtml(feature) {
      const data = getPrecinctData(feature);
      const active = getActiveContest();
      const precinctName = feature.properties.municipality_district || "";

      if (!active || !data || !data.total_votes || data.total_votes <= 0) {
        return `
          <b>${precinctName}</b><br>
          No results for this contest in this precinct.
        `;
      }

      return `
        <b>${precinctName}</b><br>
        <b>${active.contest_name}</b><br>
        <hr>
        <table class="tooltip-table">
          ${candidateRowsHtml(data, active)}
        </table>
        <hr>
        Total votes cast in race: <b>${Number(data.total_votes).toLocaleString()}</b><br>
        ${active.contest_party} registered voters: <b>${Number(data.party_registered || 0).toLocaleString()}</b><br>
        Party turnout rate: <b>${data.party_turnout_rate_pct || 0}%</b><br>
        Winner: <b>${data.winner}</b><br>
        Margin: <b>${Number(data.margin_votes).toLocaleString()}</b> votes (${data.margin_pct}%)
      `;
    }

    function tooltipText(feature) {
      const data = getPrecinctData(feature);
      const active = getActiveContest();
      const precinctName = feature.properties.municipality_district || "";

      if (!active || !data || !data.total_votes || data.total_votes <= 0) {
        return `
          <div class="tooltip-title">${precinctName}</div>
          <div class="tooltip-contest">${active.contest_name}</div>
          <div>No results for this contest in this precinct.</div>
        `;
      }

      return `
        <div class="tooltip-title">${precinctName}</div>
        <div class="tooltip-contest">${active.contest_name}</div>
        <table class="tooltip-table">
          ${candidateRowsHtml(data, active)}
        </table>
        <div class="tooltip-meta">
          ${active.contest_party} registered voters: <b>${Number(data.party_registered || 0).toLocaleString()}</b><br>
          Party turnout rate: <b>${data.party_turnout_rate_pct || 0}%</b>
        </div>
      `;
    }

    function populateContestDropdown() {
      const party = partySelect.value;
      const previousKey = contestSelect.value;
      const previousContest = contests.find(c => c.key === previousKey);
      const previousBase = previousContest ? previousContest.base : null;

      const filtered = contests.filter(c => c.party === party);

      contestSelect.innerHTML = "";

      for (const contest of filtered) {
        const option = document.createElement("option");
        option.value = contest.key;
        option.textContent = `${contest.name} (${contest.precincts} precincts)`;
        contestSelect.appendChild(option);
      }

      // When switching Dem/Rep, stay on the same office/race if the other party has it.
      if (previousBase) {
        const matchingContest = filtered.find(c => c.base === previousBase);

        if (matchingContest) {
          contestSelect.value = matchingContest.key;
        }
      }

      refreshMap();
    }

    function refreshSummary() {
      const active = getActiveContest();

      if (!active) {
        summaryDiv.innerHTML = "";
        legendDiv.innerHTML = "";
        return;
      }

      let totals = "";
      for (const name of active.candidate_cols) {
        const votes = active.candidate_totals[name] || 0;
        totals += `${name}: <b>${Number(votes).toLocaleString()}</b><br>`;
      }

      summaryDiv.innerHTML = `
        <b>${active.contest_name}</b><br>
        Precincts with results: ${Object.keys(active.by_precinct).length}<br>
        ${active.contest_party} registered voters in race geography: <b>${Number(active.party_registered_total || 0).toLocaleString()}</b><br>
        Total votes cast in race: <b>${Number(active.total_votes_cast_in_race || 0).toLocaleString()}</b><br>
        Party turnout rate: <b>${active.party_turnout_rate_total_pct || 0}%</b><br>
        <div class="note">Map is shaded by ${active.contest_party} party turnout rate in each precinct, scaled against the highest precinct rate in this race. Vote-for-multiple races can exceed 100% because each voter may cast votes for more than one candidate.</div>
        <hr>
        ${totals}
      `;

      const isDem = active.contest_party === "Dem";
      const lowColor = isDem ? "#deebf7" : "#fee5d9";
      const midColor = isDem ? "#4292c6" : "#ef3b2c";
      const highColor = isDem ? "#084594" : "#99000d";

      legendDiv.innerHTML = `
        <b>Map shading</b><br>
        <span class="swatch" style="background:#eeeeee;"></span>No results in precinct<br>
        <span class="swatch" style="background:${lowColor};"></span>Lower party turnout rate<br>
        <span class="swatch" style="background:${midColor};"></span>Middle party turnout rate<br>
        <span class="swatch" style="background:${highColor};"></span>Higher party turnout rate
      `;
    }

    function zoomToActiveContest() {
      const active = getActiveContest();

      if (!active) {
        map.fitBounds(geoLayer.getBounds(), {padding: [20, 20]});
        return;
      }

      const totalMapPrecincts = precinctGeoJson.features.length;
      const activePrecinctCount = Object.keys(active.by_precinct).length;

      // Countywide or near-countywide races stay at full-county view.
      if (activePrecinctCount >= totalMapPrecincts) {
        map.fitBounds(geoLayer.getBounds(), {padding: [20, 20]});
        return;
      }

      const bounds = L.latLngBounds([]);

      geoLayer.eachLayer(function(layer) {
        const data = getPrecinctData(layer.feature);

        if (data && data.total_votes && data.total_votes > 0) {
          bounds.extend(layer.getBounds());
        }
      });

      if (bounds.isValid()) {
        map.fitBounds(bounds.pad(0.12), {padding: [30, 30]});
      }
    }


    function refreshMap() {
      geoLayer.eachLayer(function(layer) {
        layer.setStyle(styleFeature(layer.feature));
        layer.setTooltipContent(tooltipText(layer.feature));
        layer.setPopupContent(popupHtml(layer.feature));
      });

      refreshSummary();
      zoomToActiveContest();
    }

    detailsToggle.addEventListener("click", function() {
      panel.classList.toggle("expanded");
      detailsToggle.textContent = panel.classList.contains("expanded")
        ? "Hide race details"
        : "Show race details";
      setTimeout(function() {
        map.invalidateSize();
      }, 150);
    });

    partySelect.addEventListener("change", populateContestDropdown);
    contestSelect.addEventListener("change", refreshMap);

    populateContestDropdown();
  </script>
</body>
</html>
"""

    html = (
        html_template
        .replace("__PRECINCT_GEOJSON__", json.dumps(precinct_geojson))
        .replace("__CONTESTS__", json.dumps(contests))
        .replace("__CONTEST_DATA__", json.dumps(contest_data))
    )

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")

    print("Saved dashboard:", OUT_HTML)


if __name__ == "__main__":
    main()
