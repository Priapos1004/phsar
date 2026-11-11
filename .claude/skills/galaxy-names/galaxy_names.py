"""The naming pass's two API steps against the deployed backend (SKILL.md runs them).

`fetch` saves the live map and writes the reviewers' input: `digest.md`, every group's
name and profile with the latest rebuild's dropped names, and one file per sector with
every member. `apply` renames groups by the uuids `fetch` saw, so a refit since makes the
server refuse them, then re-reads the map.
"""

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import httpx
from dotenv import dotenv_values

ENV = Path(__file__).resolve().parents[3] / "phsar" / ".env"


def login(api: str) -> httpx.Client:
    env = dotenv_values(ENV)
    client = httpx.Client(base_url=api, timeout=60)
    r = client.post("/auth/login", data={"username": env["ADMIN_USERNAME"], "password": env["ADMIN_PASSWORD"]})
    r.raise_for_status()
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return client


def groups(galaxy: dict) -> dict[str, dict]:
    return {f"S{g['number']}": g for g in galaxy["sectors"]} | {f"R{g['number']}": g for g in galaxy["regions"]}


def profile(members: list[dict]) -> str:
    trained = [m for m in members if m["trained"]] or members
    genres = Counter(g for m in trained for g in m["genres"])
    scores = [m["score"] for m in members if m["score"] is not None]
    years = [m["year"] for m in members if m["year"] is not None]
    return (f"{len(members)} stars ({sum(not m['trained'] for m in members)} placed, "
            f"{sum(m['between'] for m in members)} between) · median score "
            f"{statistics.median(scores) if scores else 0:.1f} · median year "
            f"{int(statistics.median(years)) if years else '–'} · genres: "
            + ", ".join(f"{g} {c / len(trained):.0%}" for g, c in genres.most_common(6)))


def member(m: dict) -> str:
    title = m["title"] + (f" [{m['name_eng']}]" if m["name_eng"] and m["name_eng"] != m["title"] else "")
    score = f"{m['score']:.2f}" if m["score"] is not None else "–"
    flags = ("" if m["trained"] else " (placed)") + (" (between)" if m["between"] else "")
    return f"- {title} — {m['year'] or '–'}, {score}{flags}"


def write_digest(galaxy: dict, rebuild: dict, out: Path) -> None:
    by = {"sector": defaultdict(list), "region": defaultdict(list)}
    for star in galaxy["stars"]:
        by["sector"][star["sector"]].append(star)
        by["region"][star["region"]].append(star)
    summary = rebuild.get("result_summary") or {}
    overview = [f"# Galaxy map fitted {galaxy['fitted_at']}", "",
                f"{len(galaxy['stars'])} stars, {len(galaxy['sectors'])} sectors, {len(galaxy['regions'])} regions. "
                "Each sector's members are in its own file beside this one.", "",
                "Rebuild: " + ", ".join(f"{k} {v}" for k, v in summary.items() if k != "names_dropped"), "",
                "Hand names this rebuild dropped, with the new groups their old trained members went to:"]
    overview += [f"- [{d['level']}] {d['name']}: " + ", ".join(
        f"{'S' if d['level'] == 'sector' else 'R'}{w['number']} {w['label']} {w['share']:.0%}" for w in d["went_to"])
        for d in summary.get("names_dropped", [])] or ["- none"]
    for sector in sorted(galaxy["sectors"], key=lambda g: g["number"]):
        heading = [f"## Sector S{sector['number']} — {sector['name']}", profile(by["sector"][sector["number"]])]
        section = list(heading)
        overview += ["", *heading]
        regions = sorted((r for r in galaxy["regions"] if r["sector"] == sector["number"]), key=lambda g: g["number"])
        sole = " (the sector's only region, shown as the sector)" if len(regions) == 1 else ""
        for region in regions:
            members = sorted(by["region"][region["number"]], key=lambda m: (m["score"] is None, -(m["score"] or 0)))
            heading = [f"### Region R{region['number']} — {region['name']}{sole}", profile(members)]
            overview += ["", *heading]
            section += ["", *heading, ""] + [member(m) for m in members]
        (out / f"S{sector['number']}.md").write_text("\n".join(section) + "\n")
    (out / "digest.md").write_text("\n".join(overview) + "\n")


def fetch(args: argparse.Namespace) -> None:
    client = login(args.api)
    galaxy = client.get("/browse/galaxy").raise_for_status().json()
    latest = client.get("/admin/jobs", params={"kind": "galaxy_rebuild", "status": "succeeded", "limit": 1}).json()["items"]
    # The list projects some summary keys away; the job itself carries the whole summary.
    rebuild = client.get(f"/admin/jobs/{latest[0]['uuid']}").json() if latest else {}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "map.json").write_text(json.dumps(galaxy))
    write_digest(galaxy, rebuild, args.out)
    print(f"fitted {galaxy['fitted_at']} · rebuild {rebuild.get('uuid')} · digest at {args.out / 'digest.md'}")


def apply(args: argparse.Namespace) -> None:
    snapshot = groups(json.loads((args.out / "map.json").read_text()))
    renames: dict[str, str | None] = json.loads(args.renames.read_text())
    client = login(args.api)
    live = groups(client.get("/browse/galaxy").raise_for_status().json())
    changed = [key for key in renames if live.get(key, {}).get("uuid") != snapshot[key]["uuid"]
               or live[key]["name"] != snapshot[key]["name"]]
    if changed:
        sys.exit(f"Refit or renamed since fetch: {', '.join(changed)}. Fetch again and re-review.")
    for key, name in renames.items():
        answer = client.patch(f"/admin/galaxy/groups/{snapshot[key]['uuid']}", json={"name": name}).raise_for_status().json()
        print(f"{key}: {snapshot[key]['name']} → {answer['name']}")
    after = client.get("/browse/galaxy").raise_for_status().json()
    (args.out / "map.json").write_text(json.dumps(after))
    names = [g["name"] for g in groups(after).values()]
    print("duplicates:", [n for n, c in Counter(names).items() if c > 1] or "none", "· longest:", max(names, key=len))


def main() -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--api", required=True, help="the deployed backend's base URL")
    common.add_argument("--out", required=True, type=Path, help="a scratch directory for fetch's files")
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(required=True)
    commands.add_parser("fetch", parents=[common]).set_defaults(run=fetch)
    apply_parser = commands.add_parser("apply", parents=[common])
    apply_parser.add_argument("renames", type=Path)
    apply_parser.set_defaults(run=apply)
    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
