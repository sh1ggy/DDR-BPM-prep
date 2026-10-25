"""
Konami song table (`make konami_music`): writes data/konami.tsv, every DDR WORLD
song by Konami's own song ID, linked to the prep song it is:

    konami_id   title (Konami's)   name (prep song, or empty)   zenius_id

The parse writes each linked ID into that song's JSON as "konami_id", which is
what the app matches synced e-amusement scores on. A row with no name is a
song in the game with no simfile yet. The table is gitignored: this script
rebuilds it, keeping any name already in it, so a hand-set name survives.

Songs come from the signed-in play data music_data pages, the only ones that
list unlock and event songs. Sign in on p.eagate.573.jp in a browser, copy the
session cookie, and store it in the macOS Keychain (the prompt keeps it out of
shell history):

    security add-generic-password -a "$USER" -s eagate-session -U -w

Store the cookie's value alone (sent as M573SSID) or a whole "name=value; ..."
Cookie header. The script never prints it. The public music list adds each
song's artist and levels, which tell same-title songs apart. Requests are
sequential, 3 s apart plus jitter, and stop at the first page that isn't play
data (signed out, maintenance). Every page is kept under build/konami/, and
`-l` rebuilds the table from those without fetching. Run after `make parse`:
linking reads build/songs/.
"""

import env

import csv
import html
import json
import random
import re
import subprocess
import sys
import time
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

host = "https://p.eagate.573.jp"
keychain_service = "eagate-session"
gap = 3.0
difficulties = ("BEGINNER", "BASIC", "DIFFICULT", "EXPERT", "CHALLENGE")
prep_difficulties = dict(zip(difficulties, ("beginner", "easy", "medium", "hard", "challenge")))

pages_dir = env.build_dir / "konami"
offline = "-l" in sys.argv


def cookie() -> str:
    found = subprocess.run(
        ["security", "find-generic-password", "-s", keychain_service, "-w"],
        capture_output=True,
        text=True,
    )
    if found.returncode != 0:
        sys.exit(f'No Keychain item "{keychain_service}"; see this file\'s docstring.')
    value = found.stdout.strip()
    return value if "=" in value else f"M573SSID={value}"


def page(path: Path, url: str, header: str) -> str:
    """The page saved at [path]; fetched first unless running offline."""
    if not offline:
        request = urllib.request.Request(
            url, headers={"Cookie": header, "User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            path.write_text(response.read().decode("utf-8", errors="replace"))
        time.sleep(gap + random.random())
    if not path.exists():
        sys.exit(f"{path} missing; run without -l to fetch it.")
    return path.read_text()


def text(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def pages(source: str) -> int:
    return max(len(re.findall(r'class="page_num"', source)), 1)


def parse_play_data(source: str) -> list[tuple[str, str]]:
    """(Konami ID, title) of each song on one music_data page."""
    if 'id="music_list"' not in source:
        sys.exit("signed out" if "login.html" in source else "not a play data page")
    songs = []
    for card in source.split('class="music-card"')[1:]:
        found = re.search(r"(?:index|img)=([0-9A-Za-z]{32})", card)
        name = re.search(r'class="music-name"[^>]*>(.*?)</div>', card, re.S)
        if found and name:
            songs.append((found.group(1), text(name.group(1))))
    return songs


def parse_public(source: str) -> dict[str, dict]:
    """Artist and SP levels ("-" for no chart) by Konami ID, from one music list page."""
    songs = {}
    for row in source.split('<tr class="data">')[1:]:
        found = re.search(r"img=([0-9A-Za-z]{32})", row)
        artist = re.search(r'class="artist">(.*?)</div>', row, re.S)
        sp = row.split('class="label">SP')[-1].split('class="label">DP')[0]
        if found:
            songs[found.group(1)] = {
                "artist": text(artist.group(1)) if artist else "",
                "sp": dict(re.findall(r'class="diff (\w+)">Lv\. <div class="level">([^<]*)</div>', sp)),
            }
    return songs


def fetch_all() -> tuple[dict[str, str], dict[str, dict]]:
    pages_dir.mkdir(parents=True, exist_ok=True)
    header = "" if offline else cookie()
    titles: dict[str, str] = {}
    for mode in ("single", "double"):
        offset, count = 0, 1
        while offset < count:
            source = page(
                pages_dir / f"{mode}_{offset}.html",
                f"{host}/game/ddr/ddrworld/playdata/music_data_{mode}.html"
                f"?offset={offset}&filter=0&filtertype=0&display=score",
                header,
            )
            songs, count = parse_play_data(source), pages(source)
            titles.update(songs)
            env.logger.info(f"{mode} page {offset + 1}/{count}: {len(songs)} songs")
            offset += 1
    public: dict[str, dict] = {}
    offset, count = 0, 1
    while offset < count:
        source = page(
            pages_dir / f"public_{offset}.html",
            f"{host}/game/ddr/ddrworld/music/index.html"
            f"?offset={offset}&filter=7&filtertype=0&playmode=2",
            "",
        )
        public.update(parse_public(source))
        count = pages(source)
        offset += 1
    return titles, public


def loose(title: str) -> str:
    return re.sub(
        r"[^0-9a-z぀-ヿ㐀-鿿]", "", unicodedata.normalize("NFKC", title).lower()
    )


def link(titles: dict[str, str], public: dict[str, dict]) -> tuple[dict[str, str], dict[str, list]]:
    """
    Prep song name by Konami ID, matched on title, and the IDs left with
    several equally good songs. Between same-title songs
    the artist, then the levels, decide; a lone same-title song that matches
    neither is a different song. Scraped folders that don't ship (removed.txt)
    are linked too, by their simfile titles.
    """
    songs = {}
    # Path.glob, not glob.glob: one song is named ".59".
    for file in env.build_songs_dir.glob("*.json"):
        song = json.loads(file.read_text())
        songs[song["name"]] = song
    by_title = defaultdict(set)
    for song in songs.values():
        for title in (song["title"], song["titletranslit"], song["name"]):
            by_title[loose(title)].add(song["name"])
    for folder in env.seed_dir.glob("*/*"):
        for simfile in [*folder.glob("*.sm"), *folder.glob("*.ssc")]:
            head = simfile.read_text(errors="ignore")[:4000]
            for tag in ("TITLE", "TITLETRANSLIT"):
                found = re.search(rf"#{tag}:([^;]*);", head)
                if found:
                    by_title[loose(found.group(1))].add(folder.name)
            by_title[loose(folder.name)].add(folder.name)

    def artist(k, song):
        return loose(k["artist"]) in (loose(song["artist"]), loose(song["artisttranslit"]))

    def levels(k, song):
        sp = song.get("sp", {})
        return all(str(sp.get(prep_difficulties.get(d), "-")) == v for d, v in k["sp"].items())

    names, ties = {}, {}
    for konami_id, title in titles.items():
        k = public.get(konami_id)
        candidates = sorted(by_title.get(loose(title), ()))
        if k and len(candidates) > 1:
            shipped = [c for c in candidates if c in songs]
            for same in (artist, levels):
                shipped = [c for c in shipped if same(k, songs[c])] or shipped
            candidates = shipped
        if (
            k and len(candidates) == 1 and candidates[0] in songs
            and not artist(k, songs[candidates[0]]) and not levels(k, songs[candidates[0]])
        ):
            candidates = []
        if len(candidates) == 1:
            names[konami_id] = candidates[0]
        elif candidates:
            ties[konami_id] = candidates
    # A tie whose other songs are all taken (an original beside its public cover) is settled.
    taken = Counter(names.values())
    for konami_id, candidates in ties.items():
        left = [c for c in candidates if not taken[c]]
        if len(left) == 1:
            names[konami_id] = left[0]
            taken[left[0]] += 1
    return names, {i: c for i, c in ties.items() if i not in names}


def main():
    titles, public = fetch_all()
    names, ties = link(titles, public)
    old = {}
    if Path(env.konami_file).exists():
        with open(env.konami_file, newline="") as file:
            old = {row["konami_id"]: row for row in csv.DictReader(file, delimiter="\t")}
    zenius = {}
    with open("scripts/scrape/songs.txt") as file:
        for line in file:
            if line.strip() and not line.startswith("#"):
                simfile_id, _, title = line.rstrip("\n").split("\t")
                zenius[title] = simfile_id
    rows = []
    for konami_id, title in titles.items():
        name = old.get(konami_id, {}).get("name") or names.get(konami_id, "")
        rows.append([konami_id, title, name, zenius.get(name, "")])
    rows.sort(key=lambda row: (unicodedata.normalize("NFKC", row[1]).casefold(), row[0]))
    with open(env.konami_file, "w", newline="") as file:
        writer = csv.writer(file, delimiter="\t", lineterminator="\n")
        writer.writerow(["konami_id", "title", "name", "zenius_id"])
        writer.writerows(rows)
    unnamed = [row[1] for row in rows if not row[2] and row[0] not in ties]
    print(f"{len(rows)} songs → {env.konami_file}; {len(unnamed)} with no prep song:")
    for title in unnamed:
        print(f"  {title}")
    for row in rows:
        if not row[2] and row[0] in ties:
            print(f"Pick one by hand for {row[1]}: {ties[row[0]]}")
    twice = [n for n, c in Counter(row[2] for row in rows if row[2]).items() if c > 1]
    if twice:
        print(f"Linked to two Konami songs, fix by hand: {twice}")


if __name__ == "__main__":
    main()
