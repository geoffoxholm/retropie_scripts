"""Supports cleaning gamelist.xml files, and keeping a separate easy to edit list of favorites and kidgames"""
import argparse
import os.path
import xml.etree.ElementTree as ET
import json
import os
import glob
import collections
import ffmpeg

DEFAULT_GAMELIST_DIRS = (os.path.expanduser("~/RetroPie/roms"),
                         os.path.expanduser("~/.emulationstation/gamelists"))

DEFAULT_TOKENS = ("kidgame", "favorite", "hidden")

DEFAULT_KIDLIST_PATH = os.path.expanduser(
    "/opt/retropie/configs/all/emulationstation/kidlist.json")


class Game:
    """Represents a single game of a system"""
    def __init__(self, name):
        """Constructor"""
        self.name = name

    @property
    def kidgame(self):
        """Returns the kidgame status"""
        return self.is_type("kidgame")

    @kidgame.setter
    def set_kidgame(self, value):
        """Sets the kidgame status"""
        return self.set_type("kidgame", value)

    @property
    def favorite(self):
        """Returns the favorite status"""
        return self.is_type("favorite")

    @favorite.setter
    def set_favorite(self, value):
        """Sets the favorite status"""
        return self.set_type("favorite", value)

    @property
    def hidden(self):
        """Returns the hidden status"""
        return self.is_type("hidden")

    @hidden.setter
    def set_hidden(self, value):
        """Sets the hidden status"""
        return self.set_type("hidden", value)

    def is_type(self, token):
        """Whether the game has the 'token' set"""
        raise RuntimeError("Connot call is_type on base-class")

    def set_type(self, token, value):
        """Sets whether the game has the 'token' set"""
        raise RuntimeError("Cannot call set_type on base-class")


class KidlistGame(Game):
    """Game as represented by a kidlist"""
    def __init__(self, system_kidlist, name):
        """Constructor"""
        Game.__init__(self, name)
        self._system_kidlist = system_kidlist

    def is_type(self, token):
        """Returns whether this game has its token set"""
        if token == "hidden" and self._system_kidlist.hide_all:
            return True
        return self.name in self._system_kidlist.get_list(token)

    def set_type(self, token, value):
        """Sets the token of this game to value"""
        if self.is_type(token) == value:
            # No change
            return

        token_list = self._system_kidlist.get_list(token)
        if value:
            token_list.append(self.name)
            self._system_kidlist.add_change(f"Marked {self.name} as {token}")
        else:
            token_list.remove(self.name)
            self._system_kidlist.add_change(
                f"Marked {self.name} as not {token}")


class GamelistGame(Game):
    """Game as represented by a gamelist.xml"""
    def __init__(self, element, root, gamelist):
        """Constructor"""
        Game.__init__(
            self, GamelistGame.get_name_from_path(element.find("path").text))
        self._element = element
        self._root = root
        self._gamelist = gamelist

    @staticmethod
    def get_name_from_path(rom_path):
        """Returns the unique name of a game from its path"""
        return os.path.splitext(os.path.basename(rom_path))[0]

    def is_type(self, token):
        """Whether this game has token set to true"""
        sub_element = self._element.find(token)
        return sub_element is not None and sub_element.text == "true"

    def set_type(self, token, value):
        """Sets the token of this game to value"""
        if self.is_type(token) == value:
            # No change
            return

        if value:
            kidgame = ET.SubElement(self._element, token)
            kidgame.text = "true"
            self._gamelist.add_change(f"Marked {self.name} as {token}")
        else:
            sub_element = self._element.find(token)
            self._element.remove(sub_element)
            self._gamelist.add_change(f"Marked {self.name} as not {token}")

    def get_property(self, token, default=None):
        """Returns the value of a token, or the default if it's not found"""
        element = self._element.find(token)
        return element.text if element is not None else default

    def get_path(self, token):
        """Returns the value of a token as a resolved path"""
        relative = self.get_property(token)
        if relative:
            return os.path.join(self._root, relative)
        return None

    @property
    def display_name(self):
        """The display name of the rom"""
        return self.get_property("name")

    @property
    def description(self):
        """The description of the rom"""
        return self.get_property("desc")

    @property
    def genre(self):
        """The genere of the game"""
        return self.get_property("genre")

    @property
    def image(self):
        """Image of game"""
        return self.get_property("image")

    @property
    def video(self):
        """Video of game"""
        return self.get_property("video")

    @property
    def path(self):
        """Path of game rom"""
        return self.get_property("path")


class System:
    """Represents a system"""
    def __init__(self, name):
        """Constructor for a system"""
        self.name = name
        self.changes = []

    def game(self, name):
        """Returns a game of the system"""
        raise RuntimeError("Cannot call game of base class System")


class SystemKidlist(System):
    """System kidlist"""
    def __init__(self, kidlist, system):
        """Constructor"""
        System.__init__(self, system)
        if system not in kidlist._dict:
            kidlist._dict[system] = {}
        self._dict = kidlist._dict[system]
        self._kidlist = kidlist

    def game(self, name):
        """Gets a game with the given name"""
        return KidlistGame(self, name)

    def get_list(self, token):
        """Ensures a list of type token exists, and returns it"""
        if token not in self._dict:
            self._dict[token] = []
        return self._dict[token]

    def add_change(self, change):
        """Adds a change to the list"""
        self._kidlist.add_change(self.name, change)

    @property
    def hide_all(self):
        """Returns whether the full system is hidden"""
        return "hide_all" in self._dict and self._dict["hide_all"]


class Kidlist:
    """Class that keeps track of my own list of properties"""
    def __init__(self, path=DEFAULT_KIDLIST_PATH):
        """Constructor"""
        self.changes = {}
        self._path = path
        self._dict = {}
        if os.path.exists(path):
            with open(path, "r") as handle:
                self._dict = json.load(handle)

    def get_system(self, system_name):
        """Returns a KidlistSystem"""
        return SystemKidlist(self, system_name)

    def save(self):
        """Saves all changes"""
        with open(self._path, "w") as handle:
            json.dump(self._dict, handle, indent=2, sort_keys=True)

    def add_change(self, system, change):
        """Add a change to the list"""
        if system not in self.changes:
            self.changes[system] = []
        self.changes[system].append(change)


class SystemGamelist(System):
    """Class that wraps a specific gamelist.xml"""
    def __init__(self, path, name):
        """Constructor"""
        System.__init__(self, name)
        self._path = path
        self._tree = ET.parse(self._path)
        self.changes = []

    def save(self):
        """Saves any changes"""
        self._tree.write(self._path, xml_declaration=True, encoding="UTF-8")
        # Add a blank line
        with open(self._path, "a") as handle:
            handle.write("\n")

    @property
    def games(self):
        """Returns iterable list of games"""
        for rom in self._tree.getroot():
            yield GamelistGame(rom,
                               os.path.dirname(os.path.abspath(self._path)),
                               self)

    def game(self, name):
        """Returns a specific game by its name"""
        for game in self.games:
            if game.name == name:
                return game
        return None

    def add_change(self, change):
        """Adds a change to list of changes"""
        self.changes.append(change)


class Gamelists:
    """Class that represents the gamelists on the machine"""
    def __init__(self, dirs=DEFAULT_GAMELIST_DIRS):
        """Constructor"""
        self._dirs = dirs
        self._open_systems = {}

    def get_gamelist_path(self, system_name):
        """Finds a gamelist.xml if possible"""
        for directory in self._dirs:
            path = os.path.join(directory, system_name, "gamelist.xml")
            if os.path.exists(path):
                return path
        return None

    @staticmethod
    def get_system_name_from_path(gamelist_path):
        """Returns the system name from a gamelist.xml path"""
        name = os.path.basename(os.path.dirname(
            os.path.abspath(gamelist_path)))
        if name in [".", "/", ""]:
            return None
        return name

    def get_system(self, system_name):
        """Returns a SystemGamelist"""
        if system_name not in self._open_systems:
            path = self.get_gamelist_path(system_name)
            if path is None:
                raise RuntimeError(
                    f"Could not find gamelist.xml for {system_name}")
            self._open_systems[system_name] = SystemGamelist(path, system_name)
        return self._open_systems[system_name]

    def save(self):
        """Saves all open systems"""
        for system in self._open_systems.values():
            if system.changes:
                system.save()

    @property
    def systems(self):
        """Returns an iterable list of systems"""
        for directory in self._dirs:
            for gamelist in glob.glob(
                    os.path.join(directory, "*", "gamelist.xml")):

                if os.path.islink(os.path.dirname(gamelist)):
                    # Ignore symlinks
                    continue
                name = Gamelists.get_system_name_from_path(gamelist)
                yield SystemGamelist(gamelist, name)

    @property
    def changes(self):
        """Returns a list of changes that were made"""
        changes = {}
        for system in self._open_systems:
            changes[system] = system.changes
        return changes


def underline(message):
    """Prints an underlined message"""
    print(message)
    print("=" * len(message))


def parse_args():
    """Parse arguments"""
    parser = argparse.ArgumentParser(
        description="Exports or applies kidgame tag to gameslist.xml file")
    parser.add_argument("action",
                        help="Action {sync,clean,info}",
                        default=None,
                        nargs="?")
    parser.add_argument("--format-videos",
                        help="Format the videos for OMX player",
                        dest="actions",
                        action="append_const",
                        const="format-videos")
    parser.add_argument("--dry-run",
                        help="Don't actually modify anything",
                        action="store_true",
                        default=False)
    parser.add_argument("--systems",
                        default=None,
                        nargs="+",
                        help="Which system(s) to run on")
    parser.add_argument(
        "--require-both",
        help=
        "When syncing, set status only if both lists agree, otherwise unset",
        action="store_true",
        default=False)
    args = parser.parse_args()

    return args


def sync(kidlist, gamelists, systems, union=True, tokens=DEFAULT_TOKENS):
    """Syncs the two sources of truth"""

    for system in gamelists.systems:
        if systems:
            if system.name not in systems:
                continue
        system_kidlist = kidlist.get_system(system.name)
        for gamelist_game in system.games:
            kidlist_game = system_kidlist.game(gamelist_game.name)
            for token in tokens:
                flagged_kidlist = kidlist_game.is_type(token)
                flagged_gamelist = gamelist_game.is_type(token)
                new_status = flagged_gamelist or flagged_kidlist if union else flagged_gamelist and flagged_kidlist
                kidlist_game.set_type(token, new_status)
                gamelist_game.set_type(token, new_status)


def print_info(kidlist, gamelists, systems, tokens=DEFAULT_TOKENS):
    """Prints some information about the sate of affairs"""
    for system in gamelists.systems:
        if systems:
            if system.name not in systems:
                continue
        underline(system.name)
        system_kidlist = kidlist.get_system(system.name)
        for token in tokens:
            both_count = 0
            only_one_count = 0
            for gamelist_game in system.games:
                kidlist_game = system_kidlist.game(gamelist_game.name)
                flagged_kidlist = kidlist_game.is_type(token)
                flagged_gamelist = gamelist_game.is_type(token)
                both = flagged_kidlist and flagged_gamelist
                either = flagged_kidlist or flagged_gamelist
                both_count += both
                only_one_count += either and not both
            print(f"{token} - both: {both_count} one: {only_one_count}")
        print()


def main():
    """Main Method"""
    args = parse_args()
    if args == None:
        print("use --help for usage")
        return

    # Load the two sources of truth
    gamelists = Gamelists()
    kidlist = Kidlist()

    if args.action == "sync":
        sync(kidlist, gamelists, args.systems, not args.require_both)

    if args.action == "info":
        print_info(kidlist, gamelists, args.systems)

    # Print any changes
    for source_type, source in {
            "kidlist": kidlist,
            "gamelist": gamelists
    }.items():
        some_changes = False
        for system, changes in source.changes.items():
            underline(f"Changes to {system}'s {source_type}")
            for change in changes:
                print(change)
                some_changes = True
        if some_changes:
            if not args.dry_run:
                source.save()
                print(f"Saved {source_type}")
            else:
                print(f"Would have saved {source_type}")


if __name__ == "__main__":
    main()
