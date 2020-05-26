"""Supports cleaning gamelist.xml files, and keeping a separate easy to edit list of favorites and kidgames"""
import argparse
import os.path
import xml.etree.ElementTree as ET
import json
import os
import glob
import collections
import ffmpeg

# The tokens we copy from gamelist.xml into/outof kidlist.json
TOKENS = ["kidgame", "favorite", "hidden"]

# Single change
Change = collections.namedtuple("Change", ['game', 'action'])


class Changes:
    """Keeps track of changes that were made within a system"""
    def __init__(self):
        """Constructor"""
        self._changes = {}

    def add(self, token, change):
        """Adds a record of a single change"""
        changes_system = self._changes
        if token not in changes_system:
            changes_system[token] = []
        actions = changes_system[token]
        actions.append(change)

    def __len__(self):
        """Length"""
        return sum([len(changes) for changes in self._changes.values()])

    def __str__(self):
        """Converts class to a string"""
        result = ""
        for token, changes in self._changes.items():
            for change in changes:
                result += f"{change.action}: {change.game} to {token}\n"
        return result


def underline(message):
    """Prints an underlined message"""
    print(message)
    print("=" * len(message))


def rom_name(rom):
    """Extracts a rom name from a rom element"""
    return os.path.splitext(os.path.basename(rom.find("path").text))[0]


def apply_kidlist(gamelist_path, kidlist, remove):
    """Sets kidgame=true for allpaths in rom_paths"""
    changes = Changes()
    tree = ET.parse(gamelist_path)
    hide_all = "hide_all" in kidlist and kidlist["hide_all"]

    for token in TOKENS:
        for rom in tree.getroot():
            name = rom_name(rom)
            # When working with 'hidden' we will hide all if the system is marked as `hide_all`
            is_kidgame = (token == "hidden"
                          and hide_all) or (token in kidlist
                                            and name in kidlist[token])
            kidgame_element = rom.find(token)
            if kidgame_element is not None and not is_kidgame:
                if remove:
                    rom.remove(kidgame_element)
                    changes.add(token, Change(name, "remove"))
                else:
                    # TODO Add support for no-op "changes"
                    pass
            elif is_kidgame:
                if token in kidlist and name in kidlist[token]:
                    kidlist[token].remove(name)
                if kidgame_element is None:
                    changes.add(token, Change(name, "add"))
                    kidgame = ET.SubElement(rom, token)
                    kidgame.text = "true"
                else:
                    # TODO Add support for no-op "changes"
                    pass
        if token in kidlist:
            for name in kidlist[token]:
                print(f"Warning! Could not find {name} in {gamelist_path}!")
    return changes, tree


def merge_kidlist(system_name, system_list, kidlist_all, remove, verbose):
    """Adds the roms in `system_list` to `full` at key `system_name`. 
    Optionally removes ones that are no longer in `system_list`"""

    # Make sure the system is in the full kidlist, and all the tokensets are, too
    if system_name not in kidlist_all:
        kidlist_all[system_name] = {}
    kidlist = kidlist_all[system_name]

    for token in TOKENS:
        if token not in kidlist:
            kidlist[token] = []

    hide_all = None
    if "hide_all" in kidlist:
        hide_all = kidlist["hide_all"]

    # Go through all the tokens we care to record
    changes = Changes()
    for token in TOKENS:
        if token == "hidden" and hide_all is not None:
            if verbose:
                print(
                    f"Ignoring hidden tags because {system_name} is marked as hide_all"
                )
            continue

        # Print what we plan to do
        for path in kidlist[token]:
            if path not in system_list[token]:
                if remove:
                    changes.add(token, Change(path, "remove"))
                elif verbose:
                    pass
                    # TODO Add support for no-op "changes"

        for path in system_list[token]:
            if path not in kidlist[token]:
                changes.add(token, Change(path, "add"))

        if remove:
            kidlist[token] = system_list[token]
        else:
            for path in system_list[token]:
                if path not in kidlist[token]:
                    kidlist[token].append(path)

    return changes


def extract(gamelist_path):
    """Extracts the pathnames of kidgames in the gamelist"""
    tree = ET.parse(gamelist_path)
    root = tree.getroot()
    return {
        token: [rom_name(rom) for rom in root if rom.find(token) is not None]
        for token in TOKENS
    }


def load_kidlist(path):
    """Opens the json path"""
    if os.path.exists(path):
        with open(path, "r") as handle:
            return json.load(handle)
    return {}


def save_gamelist(path, gamelist):
    """Writes a gamelist to disk, backing it up"""
    backup_path = "%s-bak%s" % os.path.splitext(path)
    os.rename(path, backup_path)
    gamelist.write(path, xml_declaration=True, encoding="UTF-8")
    with open(path, "a") as handle:
        handle.write("\n")
    print(f"Backed up old list to: {backup_path}")


def clean_gamelist(gamelist_path):
    """Removes duplicate roms from a gamelist"""
    changes = Changes()
    tree = ET.parse(gamelist_path)
    paths = {}
    root = tree.getroot()
    directory = os.path.dirname(os.path.abspath(gamelist_path))
    to_remove = []
    for rom in root:
        name = rom.find("name").text
        path = os.path.join(directory, rom.find("path").text)

        if not os.path.exists(path):
            to_remove.append(rom)
            changes.add("xml", Change(name, "removed missing"))

        if path not in paths:
            paths[path] = rom
        else:
            changes.add("xml", Change(name, "removed duplicate"))
            print(f"Duplicate {path}")
            master = paths[path]
            # Merge attributes
            master.attrib.update(rom.attrib)
            for child in rom:
                if master.find(rom.tag) is None:
                    master.append(child)
            to_remove.append(rom)
    for rom in to_remove:
        root.remove(rom)

    # Remove special characters
    for rom in tree.getroot():
        modified = False
        for element_type in ["desc", "developer"]:
            description = rom.find(element_type)
            if description is not None:
                if description.text is not None:
                    before = description.text[:]
                    description.text = description.text.replace("&amp;", "&")
                    description.text = description.text.replace("&quot;", "\"")
                    if description.text != before:
                        modified = True
        if modified:
            changes.add("xml", Change(name, "clean"))

    return tree, changes


def format_videos(gamelist, directory, dry_run):
    """Checks and corrects the format of video files"""
    changes = Changes()
    for rom in gamelist:
        name = rom.find("name").text
        video_element = rom.find("video")
        if video_element is not None:
            video_path = os.path.relpath(
                os.path.join(directory, video_element.text))
            try:
                temp_path = "%s-new%s" % os.path.splitext(video_path)
                probe = ffmpeg.probe(video_path)
                video_stream = next((stream for stream in probe['streams']
                                     if stream['codec_type'] == 'video'), None)
                if video_stream['pix_fmt'] not in ['yuv420p']:
                    if not dry_run:
                        print(f"Converting {video_path}")
                        ffmpeg.input(video_path).output(
                            temp_path,
                            pix_fmt="yuv420p").overwrite_output().run(
                                capture_stdout=True, capture_stderr=True)
                        os.rename(temp_path, video_path)
                    changes.add("yuv420p", Change(name, "converted"))
            except ffmpeg._run.Error as error:
                print(f"ERROR: Failed processing {video_path}")
                print(error)

    return changes


def add_game(path, token, kidlist):
    """Adds a game (from the path) as a new entry under 'token' in the kidlist_path"""
    if os.path.exists(path):
        full_path = os.path.abspath(path)
        name = os.path.splitext(os.path.basename(path))[0]
        system = get_system_from_gamelist_path(full_path)
        if system is None:
            print(
                "Could not determine what system this rom is for from its path."
            )
            return False
        if system not in kidlist:
            kidlist[system] = {}
        if token not in kidlist[system]:
            kidlist[system][token] = []
        if name not in kidlist[system][token]:
            kidlist[system][token].append(name)
            kidlist[system][token].sort()
            print(f"Adding {name} as a {token} in {system}")
            return True
        else:
            print(f"{name} is already a {token} in {system}")
    else:
        print(f"Could not find {path}")
    return False


def save_kidlist(kidlist, kidlist_path):
    """Saves the kidlist"""
    with open(kidlist_path, "w") as handle:
        json.dump(kidlist, handle, indent=2, sort_keys=True)


def process(gamelist_path,
            system,
            actions,
            kidlist_path,
            dry_run,
            remove=False,
            verbose=False):
    """Processes a single gamelist"""

    # Say what system we're working on
    underline(f"{system}")

    total_changes = 0
    for action in actions:
        change_count = 0
        if action == "extract":
            systemlist = extract(gamelist_path)
            kidlist = load_kidlist(kidlist_path)
            changes = merge_kidlist(system, systemlist, kidlist, remove,
                                    verbose)
            change_count = len(changes)
            if change_count:
                print(f"Made {change_count} changes to {kidlist_path}:")
                print(changes)
                if not dry_run:
                    save_kidlist(kidlist, kidlist_path)

        elif action == "apply":
            kidlist = load_kidlist(kidlist_path)
            changes, new_gamelist = apply_kidlist(
                gamelist_path, kidlist[system] if system in kidlist else {},
                remove)
            change_count = len(changes)
            if change_count:
                print(f"Made {change_count} changes to {gamelist_path}:")
                print(changes)
                if not dry_run:
                    save_gamelist(gamelist_path, new_gamelist)

        elif action == "clean":
            new_gamelist, changes = clean_gamelist(gamelist_path)
            change_count = len(changes)
            if change_count:
                print(f"Made {change_count} changes to {gamelist_path}")
                print(changes)
                if not dry_run:
                    save_gamelist(gamelist_path, new_gamelist)

        elif action == "format-videos":
            gamelist_tree = ET.parse(gamelist_path)
            changes = format_videos(
                gamelist_tree.getroot(),
                os.path.dirname(os.path.abspath(gamelist_path)), dry_run)
            change_count = len(changes)
            if change_count:
                print(f"Formatted {change_count} videos")
                print(changes)
        else:
            print(f"Unknown action: {action}")
        if change_count:
            print()
        total_changes += change_count
    if total_changes:
        print(f"Made {total_changes} total changes")
    else:
        print("up to date")
    print()


def get_system_from_gamelist_path(gamelist_path):
    """Returns the system name from a gamelist path"""
    name = os.path.basename(os.path.dirname(os.path.abspath(gamelist_path)))
    if name in [".", "/", ""]:
        return None
    return name


def parse_args():
    """Parse arguments"""
    parser = argparse.ArgumentParser(
        description="Exports or applies kidgame tag to gameslist.xml file")
    #parser.add_argument("action", help="What to do {extract, apply, clean}")
    parser.add_argument("--clean",
                        help="Clean the gamelist.xml",
                        dest="actions",
                        action="append_const",
                        const="clean")
    parser.add_argument("--extract",
                        help="Extract values from gamelist.xml",
                        dest="actions",
                        action="append_const",
                        const="extract")
    parser.add_argument("--format-videos",
                        help="Format the videos for OMX player",
                        dest="actions",
                        action="append_const",
                        const="format-videos")
    parser.add_argument("--kidgame", help="Add a game to kidgme", default=None)
    parser.add_argument("--favorite",
                        help="Add a game to favorite",
                        default=None)
    parser.add_argument("--hidden", help="Hide a game", default=None)
    parser.add_argument("--apply",
                        help="Apply values to gamelist.xml",
                        dest="actions",
                        action="append_const",
                        const="apply")
    parser.add_argument("--gamelist",
                        help="gamelist.xml file",
                        default=os.path.expanduser("~/RetroPie/roms"))
    parser.add_argument("--dry-run",
                        help="Don't actually modify anything",
                        action="store_true",
                        default=False)
    parser.add_argument("--type", default="kidgame", help=argparse.SUPPRESS)
    parser.add_argument("--add", default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--kidlist",
        help="kidlist.json file",
        default=os.path.expanduser("~/.emulationstation/kidlist.json"))
    parser.add_argument("--system",
                        help="Name of the system (e.g. 'nes')",
                        default=None)
    parser.add_argument(
        "--remove",
        default=False,
        action="store_true",
        help="Whether to remove items from the gamelist or kidgame when merging"
    )
    parser.add_argument("--verbose",
                        default=False,
                        action="store_true",
                        help="Output more")
    args = parser.parse_args()

    # Default actions, if none are specified
    if not args.actions and not args.add:
        args.actions = ["extract", "apply", "clean"]

    # It doesn't make sense to ask for removals if we're doing a both-way update
    if args.remove and all(
        [action in args.actions for action in ["extract", "apply"]]):
        print(
            "You cannot use `--remove` if you specify both `extract` and `apply`"
        )
        return None

    # Need a valid gamelist
    if not os.path.exists(args.gamelist):
        print(f"Gamelist not found: {args.gamelist}")
        return None

    # Check if we need the system, and don't have it
    if not os.path.isdir(args.gamelist) and args.system is None and any(
        [action in ["extract", "apply"] for action in args.actions]):
        args.system = get_system_from_gamelist_path(args.gamelist)
        if args.system is None:
            print(
                f"Could not guess system name from path ({args.gamelist}), please use --system"
            )
            return None

    for token in ["hidden", "kidgame", "favorite"]:
        path = vars(args)[token]
        if path:
            if args.add is not None:
                print("You can only do one game addition at a time")
                return None
            args.add = path
            args.type = token

    return args


def main():
    """Main Method"""
    args = parse_args()
    if args:
        if args.add:
            kidlist = load_kidlist(args.kidlist)
            success = add_game(args.add, args.type, kidlist)
            if success:
                save_kidlist(kidlist, args.kidlist)
        else:
            if os.path.isdir(args.gamelist):
                # User gave a directory, look for gamelists
                gamelists = glob.glob(
                    os.path.join(args.gamelist, "*", "gamelist.xml"))
                for gamelist in gamelists:
                    if not os.path.islink(os.path.dirname(gamelist)):
                        system = get_system_from_gamelist_path(gamelist)
                        process(gamelist, system, args.actions, args.kidlist,
                                args.dry_run, args.remove, args.verbose)
                    elif args.verbose:
                        print("Skipping symlink system: ",
                              get_system_from_gamelist_path(gamelist))
            else:
                # User gave a single gamelist
                system = args.system
                if args.system is None:
                    system = get_system_from_gamelist_path(args.gamelist)
                process(args.gamelist, system, args.actions, args.kidlist,
                        args.dry_run, args.remove, args.verbose)
        print("done")
    else:
        print("use --help to see usage")


if __name__ == "__main__":
    main()
