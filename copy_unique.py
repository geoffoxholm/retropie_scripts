import argparse
import glob
import os.path
import json
import re
import time
import string  # For punctuation characters
from shutil import copyfile
import xml.etree.ElementTree as ET
import configparser

DEFAULT_EXCLUDES = ("* Mature *", "Mahjong", "Lightgun", "Tabletop", "Quiz",
                    "Japanese", "BIOS", "Print Club")
DEFAULT_CATVER = os.path.expanduser("~/Documents/catver.ini")
DEFAULT_MAME_XML = os.path.expanduser("~/Documents/mame2003.xml")


def rom_name_and_tags(path):
    """Returns the name of a rom, and a list of tags"""
    full_name = os.path.splitext(os.path.basename(path))[0]
    paren_start = full_name.find(" (")

    def standardize_name(name):
        replacements = [("&", "and")]
        for replacement in replacements:
            name = name.replace(replacement[0], replacement[1])
        no_punctuation = ''.join(ch for ch in name.lower()
                                 if ch not in set(string.punctuation))
        return no_punctuation

    tags = []
    if paren_start > 0:
        # Split all the tokens at commas
        tokens = re.findall(r"\(([^/)]+)\)", full_name)
        for token in tokens:
            for t in token.split(","):
                tags.append(t.strip())
        return standardize_name(full_name[:paren_start]), tags
    return standardize_name(full_name), tags


def sort_roms(unsorted):
    """Combines roms into bins by their name"""
    sorted_roms = {}
    for rom in unsorted:
        name, tags = rom_name_and_tags(rom)
        tag_string = "|".join(tags)
        if name not in sorted_roms:
            sorted_roms[name] = {}
        if tag_string in sorted_roms[name]:
            raise RuntimeError("Surprising duplication of tags")
        sorted_roms[name][tag_string] = {"path": rom, "tags": tags}
    return sorted_roms


def get_best_rom(hits, show_failure=False):
    """Returns the best hit using some simple rules"""
    hits_orig = hits[:]

    # Acceptable regions
    REGIONS = ["USA", "World"]
    # List of tags that are an auto-rejected
    IGNORE = [
        "Beta", "Beta 1", "Beta 2", "Rev 1", "Rev 2", "Proto 1", "Proto 2",
        "Sample", "Unl", "Proto", "Ge", "Nintendo Switch", "Test Program",
        "Demo", "Genesis Mini", "Enhancement Chip"
    ]
    # If multiple maker tags are present, then pick one in this order
    MAKER = ["Namco", "UBI Soft", "Tengen", "Virtual Console"]
    # Preferred language
    LANGUAGE = ["En"]
    # Strip these out, if one survives then use it
    PREFER_NOT = ["GameCube Edition"]

    # Ignore
    hits = [
        hit for hit in hits
        if not any([ignore in hit["tags"] for ignore in IGNORE])
    ]

    def match_preferred(hits, tokens):
        for token in tokens:
            new_hits = []
            for hit in hits:
                if token in hit["tags"]:
                    if len(hit["tags"]) == 1:
                        return [hit]
                    new_hits.append(hit)
            if len(new_hits):
                return new_hits
        return []

    def match_not_preferred(hits, tokens):
        for token in tokens:
            new_hits = []
            for hit in hits:
                if token not in hit["tags"]:
                    if len(hit["tags"]) == 1:
                        return [hit]
                    new_hits.append(hit)
            if new_hits:
                return new_hits
        return []

    hits_region = match_preferred(hits, REGIONS)
    if len(hits_region) == 1:
        return hits_region[0]["path"]

    if len(hits_region) == 0:
        if show_failure:
            print("Failed to find preferred region")
            if len(hits):
                print(json.dumps(hits, indent=2))
            else:
                print(json.dumps(hits_orig, indent=2))
            input("[Enter to continue]")
        return None
    hits = hits_region

    preferences = [(MAKER, True), (LANGUAGE, True), (PREFER_NOT, False)]

    for preference in preferences:
        new_hits = match_preferred(
            hits, preference[0]) if preference[1] else match_not_preferred(
                hits, preference[0])
        if len(new_hits) == 1:
            return new_hits[0]["path"]

    if show_failure:
        print(json.dumps(hits, indent=2))
        input("[Enter to continue]")
    return None


def copy_roms(source, ignore, target, extension, action, do_copy, show_failure,
              whitelist, blacklist):
    """Copies unique versions of roms in `source` to the folder `target`"""
    paths = [
        path for path in glob.glob(os.path.join(source, f"*.{extension}"))
        if re.search(ignore, os.path.basename(path)) is None
    ]
    roms_by_name = sort_roms(paths)
    successes = 0
    for name, hits in roms_by_name.items():
        if blacklist:
            if name in blacklist:
                print(f"Blacklisting {name}")
                continue

        if whitelist:
            if name not in whitelist:
                print(f"Filtering {name}")
                continue
            path = list(hits.values())[0]["path"]
        else:
            path = get_best_rom(list(hits.values()), show_failure)

        if path is None:
            print(f"Skipping {name}")
            continue

        successes += 1
        target_path = os.path.join(target, os.path.basename(path))

        if action == "link":
            print(f"{name}: {path} ~> {target_path}")
            if do_copy and not os.path.exists(target_path):
                os.symlink(os.path.abspath(path), os.path.abspath(target_path))
        elif action == "copy":
            print(f"{name}: {path} -> {target_path}")
            if do_copy:
                copyfile(os.path.abspath(path), os.path.abspath(target_path))
        elif action == "clean":
            if len(hits.values()) > 1:
                print(hits)
            for hit in hits.values():
                if hit["path"] != path:
                    print(f'rm {hit["path"]}')
                else:
                    pass
                    #print(hit)
        else:
            raise RuntimeError(f"Unknown action {action}")

    if do_copy:
        print(f"Copied {successes} games")
    else:
        print(f"Would have copied {successes} games")


def read_filter(filter_path):
    """Returns a list of game names to keep"""
    tree = ET.parse(filter_path)
    return [
        game.attrib["name"] for game in tree.getroot().findall("game")
        if not any([token in game.attrib for token in ["cloneof"]])
    ]


def read_catver(catver_path):
    """Returns a dictionary of categories for each rom"""
    config = configparser.ConfigParser()
    config.read(catver_path)
    categories = {}
    for name, catstring in config["Category"].items():
        categories[name] = []
        if "* Mature *" in catstring:
            categories[name].append("* Mature *")
            catstring = catstring[:-1 * len("* Mature *")].strip()
        categories[name].extend(catstring.split(" / "))
    return categories


def parse_args():
    """Parse arguments"""
    parser = argparse.ArgumentParser(
        description="Cleans up roms by making a single copy")
    parser.add_argument("source", help="Source directory")
    parser.add_argument("destination", help="Target directory")
    parser.add_argument("--extension",
                        help="File extension to match",
                        default="zip")
    parser.add_argument("--show-failure",
                        help="Show detail about failed romsets",
                        default=False,
                        action="store_true")
    parser.add_argument("--run",
                        help="Actually run the copying",
                        default=False,
                        action="store_true")
    parser.add_argument("--ignore",
                        help="Pattern of filenames to ignore",
                        default=r"^\[")
    parser.add_argument("--action",
                        default="link",
                        help="What to do {link,copy,clean}")
    parser.add_argument(
        "--whitelist",
        help="Only keeps the games found in the specified document",
        default=DEFAULT_MAME_XML)
    parser.add_argument("--catver",
                        help="Path to catver.ini file",
                        default=DEFAULT_CATVER)
    parser.add_argument("--exclude-categories",
                        help="Categories to exclude",
                        default=None,
                        nargs="+")
    args = parser.parse_args()
    if args.action not in ["link", "copy", "clean"]:
        print("--action must be link or copy or clean")
        return None

    if args.exclude_categories is None:
        args.exclude_categories = DEFAULT_EXCLUDES

    return args


def main():
    """Main Method"""
    args = parse_args()
    if args:
        whitelist = None
        if args.whitelist:
            whitelist = read_filter(args.whitelist)

        categories = {}
        if args.catver:
            categories = read_catver(args.catver)

        blacklist = []
        if args.exclude_categories:
            for rom, categories in categories.items():
                if any([
                        category in args.exclude_categories
                        for category in categories
                ]):
                    blacklist.append(rom)
        print(f"Blacklisted {len(blacklist)} games")

        copy_roms(args.source, args.ignore, args.destination, args.extension,
                  args.action, args.run, args.show_failure, whitelist,
                  blacklist)
    else:
        print("run with --help for usage")


if __name__ == "__main__":
    main()
