# kidgame.py

This program allows you to keep your own list of favorites in a `kidlist.json` file. This helps ensure that your `favorite`, `kidgame`, and `hidden` tags persist even if you refresh your `gamelist.xml`.

## Usage

```sh
python3 kidgame.py
python3 kidgame.py info
python3 kidgame.py sync [--require-both]
pyothn3 kidgame.py <add|remove|set|unset> [(favorite)|kidgame|hidden] [system] <path or name> <path or name>
python3 kidgame.py genres [count|(alpha)]
python3 kidgame.py genre <genre> 
python3 kidgame.py genre <genre> list
python3 kidgame.py genre <genre> remove [--dry-run] [--systems <system> ...]
python3 kidgame.py genre <genre> favorite [--dry-run] [--systems <system> ...]
python3 kidgame.py genre <genre> hidden [--dry-run] [--systems <system> ...]
python3 kidgame.py genre <genre> kidgame [--dry-run] [--systems <system> ...]
python3 kidgame.py format-videos [--dry-run] [--systems <system> ...]
python3 kidgame.py clean [--dry-run] [--systems <system> ...]
python3 kidgame.py clean-gamelists [--dry-run] [--systems <system> ...]
python3 kidgame.py clean-kidlist [--dry-run] [--systems <system> ...]
python3 kidgame.py remove-incomplete [--dry-run] [--systems <system> ...]
python3 kidgame.py backup [--systems <system> ...]
python3 kidgame.py revert [--systems <system> ...]
```

### Actions

* **info** (default) - Lists some basic information about each system's lists
* **sync** - Makes sure the gamelists and kidlist are in sync. Use `--require-both` to remove flags that are not set in both systems. You'd use this if you remove something from a list, for example.
* **add/remove** - Lets you add games by name or path to the favorites (or hidden or kidgame) lists
* **genres** - List all the genres found. If `count` is specified it will sort by the number, otherwise alphebetic
* **genre** - Perform an action on a genre. Following `genre` you can add any of `{list,remove,hidden,kidgame,favorite}`. If omitted, then `list` is assumed
* **format-videos** - Ensures all the videos are in a format that can be played by OMX player
* **clean** or **clean-gamelist** - Removes missing roms from the `gamelist.xml`. Converts escaped characters that do not need to be escaped (removes `&amp` from descriptions). Renames `Plateform` genre to `Platform`. 
* **clean-kidlist** - Removes games from the `kidlist` that are not found in the associated `gamelist`
* **remove-incomplete** - Removes games from `gamelist` if the video or image is missing (so that you can rescrape)
* **backup** - Saves the gamelists and kidlist. If systems is specified then only those `gamelist.xml` will be saved (the full kidlist will be saved)
* **revert** - Restores the previous backup of the gamelists and kidlist (see `backup` for description of how `--systems` is used)

### Options

* **`--dry-run`** if specified, will not save anything
* **`--systems`** if specified, only the systems listed after this argument will be processed
* **`--require-both`** only applies to `sync` (see above)
