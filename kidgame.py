"""Supports cleaning gamelist.xml files, and keeping a separate easy to edit list of favorites and kidgames"""
import argparse
import os.path
import xml.etree.ElementTree as ET
import json
import os
import glob
import ffmpeg
import signal
import sys
from shutil import copyfile
import re

DEFAULT_GAMELIST_DIRS = (os.path.expanduser("~/RetroPie/roms"),
                         os.path.expanduser("~/.emulationstation/gamelists"))

DEFAULT_TOKENS = ("kidgame", "favorite", "hidden")

DEFAULT_KIDLIST_PATH = os.path.expanduser(
    "/opt/retropie/configs/all/emulationstation/kidlist.json")

DEFAULT_FORMAT_CACHE = os.path.expanduser(
    os.path.expanduser("~/.emulationstation/format_cache.json"))

TEXT_REPLACEMENTS = (("&amp;", "&"), ("&quot;", "\""), ("&copy;", "©"),
                     ("&nbsp;", " "), ("&#039;", "&apos;"))


class Game:
    """Represents a single game of a system"""
    def __init__(self, name, system):
        """Constructor"""
        self.name = name
        self.system = system

    @property
    def display_name(self):
        """Name that is displayed"""
        return self.name

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

    def __str__(self):
        """Returns string representation"""
        return f"'{self.display_name}' ({self.name}) of {self.system.name}"

    @property
    def tags(self):
        """Returns the tags present in the games path"""
        paren_start = self.name.find(" (")

        tags = []
        if paren_start > 0:
            # Split all the tokens at commas
            tokens = re.findall(r"\(([^/)]+)\)", self.name)
            for token in tokens:
                for t in token.split(","):
                    tags.append(t.strip())
        return tags


class KidlistGame(Game):
    """Game as represented by a kidlist"""
    def __init__(self, system_kidlist, name):
        """Constructor"""
        Game.__init__(self, name, system_kidlist)

    def is_type(self, token):
        """Returns whether this game has its token set"""
        if token == "hidden" and self.system.hide_all:
            return True
        return self.name in self.system.get_list(token)

    def set_type(self, token, value):
        """Sets the token of this game to value"""
        if self.is_type(token) == value:
            # No change
            return

        token_list = self.system.get_list(token)
        if value:
            token_list.append(self.name)
            self.system.add_change(f"Marked {self.name} as {token}")
        else:
            token_list.remove(self.name)
            self.system.add_change(f"Marked {self.name} as not {token}")


class GamelistGame(Game):
    """Game as represented by a gamelist.xml"""
    def __init__(self, element, gamelist, root):
        """Constructor"""
        Game.__init__(
            self, GamelistGame.get_name_from_path(element.find("path").text),
            gamelist)
        self._element = element
        self._root = root

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
            self.add_change(f"Marked {self.display_name} as {token}")
        else:
            sub_element = self._element.find(token)
            self._element.remove(sub_element)
            self.add_change(f"Marked {self.display_name} as not {token}")

    def add_change(self, change, notice=False):
        """Adds a change to the list"""
        self.system.add_change(change, notice)

    def get_property(self, token, default=None, escaped=False):
        """Returns the value of a token, or the default if it's not found"""
        element = self._element.find(token)
        if element is not None:
            if escaped:
                return str(ET.tostring(element)).replace(
                    f"<{token}>", "").replace(f"</{token}>",
                                              "").replace(f"<{token} />", "")
            return default if element.text is None else element.text
        return default

    def set_text_property(self, token, value):
        """Sets the value of a token to the given text value"""
        element = self._element.find(token)
        if element is not None:
            element.text = value

    def get_path(self, token):
        """Returns the value of a token as a resolved path"""
        relative = self.get_property(token)
        if relative:
            return os.path.abspath(os.path.join(self._root, relative))
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
    def genres(self):
        """The genere of the game"""
        genres = self.get_property("genre")
        if genres is None:
            return ["N/A"]
        return map(lambda x: x.strip(), genres.split(" / "))

    @property
    def image(self):
        """Image of game"""
        return self.get_path("image")

    @property
    def video(self):
        """Video of game"""
        return self.get_path("video")

    @property
    def path(self):
        """Path of game rom"""
        return self.get_path("path")

    @property
    def exists(self):
        """Whether or not the rom is on disk"""
        return os.path.exists(self.path)

    @property
    def element(self):
        """Read only access to the element"""
        return self._element

    @property
    def year(self):
        return int(self.get_property("releasedate")[:4])

    @property
    def video_well_formatted(self):
        """Whether the video is properly formatted"""
        video_path = self.video
        if video_path and os.path.exists(video_path):
            try:
                probe = ffmpeg.probe(video_path)
                video_stream = next((stream for stream in probe['streams']
                                     if stream['codec_type'] == 'video'), None)
                return video_stream['pix_fmt'] in ['yuv420p']
            except ffmpeg._run.Error as error:
                print(
                    f"Error probing {video_path} (video for {self.display_name})"
                )
                return False
        return False

    @property
    def detail_string(self):
        """Detailed information about the game"""

        tags = ", ".join([tag for tag in DEFAULT_TOKENS if self.get_property(tag) ])        
        if tags:
            tags = f"\n{tags}"
        
        result = (f"{self.display_name} ({self.year})\n" 
        f"({self.name} on {self.system.name})"
        f"{tags}"
        )
        return result


    def format_video(self):
        """Ensures the video is in a good format"""
        video_path = self.video
        if video_path and os.path.exists(video_path):
            temp_path = "%s-new%s" % os.path.splitext(video_path)
            print(f"Converting {video_path}")
            try:
                ffmpeg.input(video_path).output(
                    temp_path, pix_fmt="yuv420p").overwrite_output().run(
                        capture_stdout=True, capture_stderr=True)
                os.rename(temp_path, video_path)
                return True
            except ffmpeg._run.Error as error:
                print(f"ERROR: Failed processing {video_path}")
                print(error)
                return False
        return False


class System:
    """Represents a system"""
    def __init__(self, name):
        """Constructor for a system"""
        self.name = name
        self.changes = []

    def game(self, name):
        """Returns a game of the system"""
        raise RuntimeError("Cannot call game of base class System")

    def __str__(self):
        """Returns string representation"""
        return self.name


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

    def add_change(self, change, notice=False):
        """Adds a change to the list"""
        self._kidlist.add_change(self.name, change, notice)

    @property
    def hide_all(self):
        """Returns whether the full system is hidden"""
        return "hide_all" in self._dict and self._dict["hide_all"]

    @property
    def games(self):
        """Returns an iterator of games represented by this system"""
        game_names = set()
        for games in self._dict.values():
            if isinstance(games, list):
                for game in games:
                    game_names.add(game)
        for name in game_names:
            yield self.game(name)

    def clean(self, gamelist):
        """Removes games not found in gamelist"""
        for game in self.games:
            if gamelist.game(game.name) is None:
                changed = False
                for game_names in self._dict.values():
                    if isinstance(game_names, list):
                        before = len(game_names)
                        game_names[:] = [
                            name for name in game_names if name != game.name
                        ]
                        if len(game_names) != before:
                            changed = True
                if changed:
                    self.add_change(
                        f"Removed {game.name}, not found in gamelist")


class Kidlist:
    """Class that keeps track of my own list of properties"""
    def __init__(self, systems=None, path=DEFAULT_KIDLIST_PATH):
        """Constructor"""
        self.changes = {}
        self.notices = {}
        self._path = path
        self._dict = {}
        self._systems_whitelist = systems
        if os.path.exists(path):
            with open(path, "r") as handle:
                self._dict = json.load(handle)

    def get_system(self, system_name):
        """Returns a KidlistSystem"""
        if self._systems_whitelist and system_name not in self._systems_whitelist:
            return None
        return SystemKidlist(self, system_name)

    @property
    def backup_path(self):
        """Returns the path this file backs up to when saving a new one"""
        return "%s-bak%s" % os.path.splitext(self._path)

    def backup(self):
        """Backup"""
        copyfile(self._path, self.backup_path)

    def save(self):
        """Saves all changes"""
        # Save
        with open(self._path, "w") as handle:
            json.dump(self._dict, handle, indent=2, sort_keys=True)

    def restore_backup(self):
        """Restores from backup"""
        copyfile(self.backup_path, self._path)

    def add_change(self, system, change, notice=False):
        """Add a change to the list"""
        working = self.notices if notice else self.changes
        if system not in self.changes:
            working[system] = []
        working[system].append(change)

    @property
    def systems(self):
        """Returns an iterator of systems"""
        for system_name in self._dict:
            if self._systems_whitelist and system_name not in self._systems_whitelist:
                continue
            yield self.get_system(system_name)

    def clean(self, gamelists):
        """Removes missing games or systems"""
        for system_kidlist in self.systems:
            system_gamelist = gamelists.get_system(system_kidlist.name)
            if system_gamelist is not None:
                system_kidlist.clean(system_gamelist)
            else:
                self.add_change(system_kidlist.name,
                                "WARNING! No gamelist found!")


class SystemGamelist(System):
    """Class that wraps a specific gamelist.xml"""
    def __init__(self, path, name, gamelists):
        """Constructor"""
        System.__init__(self, name)
        self._path = path
        self._tree = ET.parse(self._path)
        self.changes = []
        self.notices = []
        self._gamelists = gamelists

    @property
    def backup_path(self):
        """Returns the path this file backs up to when saving a new one"""
        return "%s-bak%s" % os.path.splitext(self._path)

    def restore_backup(self):
        """Restores from backup"""
        copyfile(self.backup_path, self._path)

    def backup(self):
        """Backup"""
        copyfile(self._path, self.backup_path)

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
            yield GamelistGame(rom, self,
                               os.path.dirname(os.path.abspath(self._path)))

    def game(self, name):
        """Returns a specific game by its name"""
        for game in self.games:
            if game.name == name:
                return game
        return None

    def game_by_path(self, path):
        """Returns a game from its path"""
        name = GamelistGame.get_name_from_path(path)
        return self.game(name)

    def add_change(self, change, notice=False):
        """Adds a change to list of changes"""
        if notice:
            self.notices.append(change)
        else:
            self.changes.append(change)

    def remove_games(self, to_remove):
        """Removes games from this system"""
        root = self._tree.getroot()
        for game in to_remove:
            comment = None
            if isinstance(game, tuple):
                game, comment = game
            root.remove(game.element)
            change = f"Removed {game.display_name} ({game.name})"
            if comment is not None:
                change = f"{change} - {comment}"
            self.add_change(change)

    def remove_incomplete(self, remove_empty=False):
        """Checks the files"""
        to_remove = set()
        for game in self.games:
            for field in ["video", "image"]:
                path = game.get_path(field)
                if not path:
                    if remove_empty:
                        to_remove.add((game, f"Empty {field}"))
                elif not os.path.exists(path):
                    to_remove.add((game, f"Missing {field}"))

        self.remove_games(to_remove)

    def clean(self):
        """Clean the xml"""
        to_remove = set()
        paths = {}
        names = {}
        for game in self.games:
            if not game.exists:
                to_remove.add((game, "missing rom"))
                continue

            # Check name
            if game.display_name not in names:
                names[game.display_name] = []
            names[game.display_name].append(game)

            # Check path
            path = game.path
            if path in paths:
                to_remove.add((game, "duplicate path"))
                master = paths[path]._element
                rom = game._element
                # Merge attributes
                master.attrib.update(rom.attrib)
                for child in rom:
                    if master.find(rom.tag) is None:
                        master.append(child)
                continue
            # Save the unique entry for this path
            paths[path] = game

        # Check the duplicate names
        for name, games in names.items():
            if len(games) > 1:
                filtered = list(filter(lambda game: "USA" in game.tags, games))
                if len(filtered) == 1:
                    for game in games:
                        if "USA" not in game.tags:
                            to_remove.add(
                                (game, "Duplicate name, missing USA tag"))
                else:
                    paths = ", ".join([game.path for game in games])
                    self.add_change(
                        f"Multiple games with name {name}: ({paths})", True)

        # Now remove the ones marked for removal
        self.remove_games(to_remove)

        # Remove special characters
        for game in self.games:
            modified = False
            for field in "desc", "developer", "developer":
                description = game.get_property(field)
                if description is not None:
                    before = game.get_property(field, None, True)
                    for replacement in TEXT_REPLACEMENTS:
                        description = description.replace(*replacement)
                    modified = modified or game.get_property(
                        field, None, True) != before
            if modified:
                game.set_text_property(field, description)
                self.add_change(f"Cleaned text of {game.name}")

            if "Plateform" in game.genres:
                game.set_text_property(
                    "genre",
                    game.get_property("genre").replace("Plateform",
                                                       "Platform"))
                self.add_change(f"Cleaned genre of {game.name}")

    def format_videos(self, dry_run, cache=None):
        """Ensures all the videos for the roms are in a good format"""
        if cache is None:
            cache = {}
        for game in self.games:
            path = game.video
            if path is None:
                # No video for this one
                continue

            if cache is not None and path in cache:
                if cache[path]:
                    continue
            else:
                cache[path] = game.video_well_formatted
            if not cache[path]:
                self.add_change(f"Converted video for {game.display_name}")
                if not dry_run:
                    if game.format_video() and cache is not None:
                        cache[path] = True

            self._gamelists.save_cache()

    def get_games_by_genre(self, genre):
        """Returns all the games in this system that have the given genre"""
        return [
            game for game in self.games
            if genre.lower() in [g.lower() for g in game.genres]
        ]

    def find_games(self, partial):
        """Returns all games that contain `partial`"""
        return [
            game for game in self.games if any([
                partial.lower() in name.lower()
                for name in [game.display_name, game.name]
            ])
        ]

    @property
    def unscraped_games(self):
        """Returns all the games that are not in the gamelist"""
        all_roms = glob.glob(os.path.join(os.path.dirname(self._path),
                                          "*.zip"))
        scraped_roms = [game.path for game in self.games]
        return filter(lambda rom: rom not in scraped_roms, all_roms)


class Gamelists:
    """Class that represents the gamelists on the machine"""
    def __init__(self,
                 systems=None,
                 dirs=DEFAULT_GAMELIST_DIRS,
                 format_cache=DEFAULT_FORMAT_CACHE):
        """Constructor"""
        self._dirs = dirs
        self._open_systems = {}
        self._systems_whitelist = systems
        self._format_cache_path = format_cache
        self._format_cache = {}
        if os.path.exists(format_cache):
            with open(format_cache, "r") as handle:
                self._format_cache = json.load(handle)

    def get_gamelist_path(self, system_name):
        """Finds a gamelist.xml if possible"""
        for directory in self._dirs:
            path = os.path.join(directory, system_name, "gamelist.xml")
            if os.path.exists(path):
                return path
        return None

    def get_system_from_path(self, gamelist_path):
        """Returns the system name from a gamelist.xml path"""
        name = os.path.basename(os.path.dirname(
            os.path.abspath(gamelist_path)))
        if name in [".", "/", ""]:
            return None
        return self.get_system(name)

    def get_system(self, system_name):
        """Returns a SystemGamelist"""
        if self._systems_whitelist and system_name not in self._systems_whitelist:
            return None

        if system_name not in self._open_systems:
            path = self.get_gamelist_path(system_name)
            if path is None:
                return None
            self._open_systems[system_name] = SystemGamelist(
                path, system_name, self)
        return self._open_systems[system_name]

    def backup(self):
        """Backs-up all open systems"""
        for system in self._open_systems.values():
            if system.changes:
                system.backup()

    def save(self):
        """Saves all open systems"""
        for system in self._open_systems.values():
            if system.changes:
                system.save()

    def save_cache(self):
        """Writes the cache to disk"""
        try:
            with open(self._format_cache_path, "w") as handle:
                json.dump(self._format_cache, handle, indent=2, sort_keys=True)
        except:
            print("Error saving cache!")
            print(self._format_cache)

    @property
    def systems(self):
        """Returns an iterable list of systems"""
        for directory in self._dirs:
            for gamelist in glob.glob(
                    os.path.join(directory, "*", "gamelist.xml")):

                if os.path.islink(os.path.dirname(gamelist)):
                    # Ignore symlinks
                    continue
                system = self.get_system_from_path(gamelist)
                if system is None:
                    continue
                if self._systems_whitelist and system.name not in self._systems_whitelist:
                    continue
                yield system

    @property
    def changes(self):
        """Returns a list of changes that were made"""
        changes = {}
        for system_name, system in self._open_systems.items():
            changes[system_name] = system.changes
        return changes

    @property
    def notices(self):
        """Returns any notices"""
        return {
            system.name: system.notices
            for system in self._open_systems.values()
        }

    def clean(self, ignore=("retropie")):
        """Does cleaning of the systems"""
        for system in self.systems:
            if system.name not in ignore:
                system.clean()

    def format_videos(self, dry_run):
        """Ensures the videos are formatted correctly"""
        for system in self.systems:
            system.format_videos(dry_run, self._format_cache)

    def remove_incomplete(self, ignore=("retropie")):
        """Checks for missing images or videos"""
        for system in self.systems:
            if system.name not in ignore:
                system.remove_incomplete()

    def restore_backup(self, ignore=("retropie")):
        """Restores backups"""
        for system in self.systems:
            if system.name not in ignore:
                system.restore_backup()

    def get_games_by_genre(self, genre):
        """Returns a dictionary of systems to game lists"""
        result = {}
        for system in self.systems:
            games = system.get_games_by_genre(genre)
            if games:
                result[system] = games
        return result

    def find_games(self, partial):
        """Returns all games that contain `partial`"""
        games = []
        for system in self.systems:
            games.extend(system.find_games(partial))
        return games


def underline(message):
    """Prints an underlined message"""
    print(message)
    print("=" * len(message))


def parse_args():
    """Parse arguments"""
    parser = argparse.ArgumentParser(
        description="Exports or applies kidgame tag to gameslist.xml file")
    parser.add_argument(
        "action",
        help=
        "Action {sync,clean,info,format-videos,remove-incomplete,clean-kidlist,clean-roms,genres,genre}",
        default=["info"],
        nargs="*")
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
        "For `sync` action, set status only if both lists agree, otherwise unset (remove)",
        action="store_true",
        default=False)
    args = parser.parse_args()

    return args


def sync(kidlist, gamelists, union=True, tokens=DEFAULT_TOKENS):
    """Syncs the two sources of truth"""
    for system in gamelists.systems:
        system_kidlist = kidlist.get_system(system.name)
        for gamelist_game in system.games:
            kidlist_game = system_kidlist.game(gamelist_game.name)
            for token in tokens:
                flagged_kidlist = kidlist_game.is_type(token)
                flagged_gamelist = gamelist_game.is_type(token)
                new_status = flagged_gamelist or flagged_kidlist if union else flagged_gamelist and flagged_kidlist
                kidlist_game.set_type(token, new_status)
                gamelist_game.set_type(token, new_status)


def print_genres(gamelists, sort_by_count=True):
    """Prints some information about the sate of affairs"""

    genres = {}
    for system in gamelists.systems:
        for gamelist_game in system.games:
            for genre in gamelist_game.genres:
                if genre not in genres:
                    genres[genre] = 0
                genres[genre] += 1

    underline("Genres")
    for genre, count in sorted(genres.items(),
                               reverse=True,
                               key=lambda item: item[sort_by_count]):
        print(f"{genre}: {count}")
    print()


def print_games_with_genre(gamelists,
                           genre,
                           action=None,
                           kidlist=None,
                           tokens=DEFAULT_TOKENS):
    """Prints all games with the given genre"""
    just_list = action is None or action == "list"
    for system, games in gamelists.get_games_by_genre(genre).items():
        if just_list:
            underline(system.name)
        for game in games:
            if just_list:
                print(game.display_name)
            if action in tokens:
                if kidlist is not None:
                    kidlist.get_system(system.name).game(game.name).set_token(
                        action, True)
                game.set_token(action, True)
        if action == "remove":
            system.remove_games(games)
        if just_list:
            print()


def print_info(kidlist, gamelists, tokens=DEFAULT_TOKENS):
    """Prints some information about the sate of affairs"""
    genres = {}
    for system in gamelists.systems:
        underline(system.name)
        system_kidlist = kidlist.get_system(system.name)
        print(f"Total: {len(list(system.games))}")
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
                for genre in gamelist_game.genres:
                    if genre not in genres:
                        genres[genre] = 0
                    genres[genre] += 1
            print(f"{token} - both: {both_count} one: {only_one_count}")
        print()


def find_games(argument, gamelists, system):
    """Finds the best game, or games based on the clue"""
    if os.path.exists(argument):
        game_system = gamelists.get_system_from_path(argument)
        if system is not None and game_system.name != system.name:
            return f"{argument} is not in {system.name} (it's in {game_system.name})"
        if system is None:
            system = game_system
        if system is None:
            return f"Could not determine the system for {argument}"

        game = system.game_by_path(argument)
        if game is None:
            return f"Could not find {argument} in {system.name} (need to scrape?)"
        return [game]
    else:
        games = system.find_games(
            argument) if system is not None else gamelists.find_games(argument)
        if len(games) == 0:
            return f"Could not find any games named {argument}"
        if len(games) > 1:
            for game in games:
                for candidate in [game.name, game.display_name]:
                    if argument.lower() == candidate.lower():
                        # Found a direct match
                        return [game]
        return games


def add_remove(add,
               arguments,
               kidlist,
               gamelists,
               tokens=DEFAULT_TOKENS,
               default_token="favorite"):
    """Adds or removes (based on `add`) a game to a list"""

    # Read the token from the arguments
    if not len(arguments):
        print("Error! Nothing to add/remove")
        return

    token = default_token
    if arguments[0] in tokens:
        token = arguments[0]
        arguments = arguments[1:]

    if not len(arguments):
        print("Error! Nothing to add/remove")
        return

    # Read the system from the arguments
    system_all = None
    for candidate in gamelists.systems:
        if candidate.name == arguments[0]:
            system_all = candidate
            arguments = arguments[1:]
            break

    for argument in arguments:
        search_result = find_games(argument, gamelists, system_all)
        if isinstance(search_result, str):
            print(search_result)
            continue
        if len(search_result) > 1:
            print(f"Found multiple games: ")
            for game in search_result:
                print(game)
            continue
        game = search_result[0]
        system = game.system
        game.set_type(token, add)
        kidlist.get_system(system.name).game(game.name).set_type(token, add)


def print_game_info(gamelists, arguments):
    """Prints some info about games"""
    # Read the system from the arguments
    system_all = None
    for candidate in gamelists.systems:
        if candidate.name == arguments[0]:
            system_all = candidate
            arguments = arguments[1:]
            break

    for argument in arguments:
        underline(argument)
        games = find_games(argument, gamelists, system_all)
        if isinstance(games, str):
            print(games.detail_string)
            continue
        for game in games:
            print(game.detail_string)
            print()


def clean_roms(gamelists, dry_run):
    """Removes roms from disk that are not in the gamelist.xml"""
    print("Please wait...")
    changes = []
    for system in gamelists.systems:
        for game in system.unscraped_games:
            changes.append(f"Removed {game} from disk")
            if not dry_run:
                os.remove(game)
    return changes


def main():
    """Main Method"""
    args = parse_args()
    if args is None:
        print("use --help for usage")
        return

    # Load the two sources of truth
    gamelists = Gamelists(args.systems)
    kidlist = Kidlist(args.systems)
    other_changes = []

    action, action_arguments = args.action[0], args.action[1:]

    if action == "sync":
        sync(kidlist, gamelists, not args.require_both)
    elif action == "info":
        if len(action_arguments) == 0:
            print_info(kidlist, gamelists)
        else:
            print_game_info(gamelists, action_arguments)
    elif action == "genre":
        if len(action_arguments) >= 1:
            print_games_with_genre(
                gamelists, action_arguments[0],
                action_arguments[1] if len(action_arguments) > 1 else None)
        else:
            print("ERROR: You must specify a genre")
            return
    elif action == "genres":
        sort_by_count = False
        if action_arguments:
            sort_by_count = action_arguments[0] == "count"
        print_genres(gamelists, sort_by_count)
    elif action in ["clean", "clean-gamelists"]:
        gamelists.clean()
    elif action == "clean-kidlist":
        kidlist.clean(gamelists)
    elif action == "clean-roms":
        other_changes = clean_roms(gamelists, args.dry_run)
    elif action == "format-videos":
        gamelists.format_videos(args.dry_run)
    elif action == "remove-incomplete":
        gamelists.remove_incomplete()
    elif action == "revert":
        gamelists.restore_backup()
        kidlist.restore_backup()
        print("Restored backups")
        return
    elif action == "backup":
        gamelists.backup()
        kidlist.backup()
    elif action in ["add", "remove", "set", "unset"]:
        add_remove(action in ["add", "set"], action_arguments, kidlist,
                   gamelists)
    else:
        print(f"Unknown action '{action}'")

    if other_changes:
        print(f"Changes:")
        for change in other_changes:
            print(change)

    # Print any changes
    for source_type, source in {
            "kidlist": kidlist,
            "gamelist": gamelists
    }.items():
        some_changes = False
        for system, notices in source.notices.items():
            if len(notices):
                underline(f"Notices about {system}'s {source_type}")
                for notice in notices:
                    print(notice)

        for system, changes in source.changes.items():
            if len(changes):
                underline(f"Changes to {system}'s {source_type}")
                for change in changes:
                    print(change)
                    some_changes = True
                print()
        if some_changes:
            if not args.dry_run:
                source.backup()
                source.save()
                print(f"Saved {source_type} (backups made)")
            else:
                print(f"Would have saved {source_type}")

    print("Done")


if __name__ == "__main__":
    main()
