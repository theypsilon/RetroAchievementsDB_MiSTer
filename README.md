# RetroAchievementsDB MiSTer

This repository publishes a custom MiSTer Downloader database for
[RetroAchievements](https://retroachievements.org/) enabled
[MiSTer cores](https://github.com/MiSTer-devel).

The generated database installs the RetroAchievements MiSTer runtime, the
achievement sound, and the `_RA_Cores/` folder containing release-backed RA core
RBFs and matching MGL launchers. It is intended for use with
[Downloader](https://github.com/MiSTer-devel/Downloader_MiSTer) and
[Update All](https://github.com/theypsilon/Update_All_MiSTer).

The RetroAchievements core forks are maintained by
[odelot](https://github.com/odelot).

## Installation

The primary installation path is
[Update All](https://github.com/theypsilon/Update_All_MiSTer). Enable this
database from the Update All Settings screen, under the Other Cores submenu,
then run Update All to fetch the RetroAchievements runtime and cores.

As an alternative when not using Update All, install the generated Downloader
drop-in database from the `db` branch:

```text
https://raw.githubusercontent.com/theypsilon/RetroAchievementsDB_MiSTer/db/downloader_theypsilon_RetroAchievementsDB_MiSTer.zip
```

Extract the `.ini` file from that ZIP into the root of your MiSTer SD card, next
to `downloader.ini`, then run Downloader or Update All.

Manual configuration is also possible by adding this section to `downloader.ini`:

```ini
[theypsilon/RetroAchievementsDB_MiSTer]
db_url = https://raw.githubusercontent.com/theypsilon/RetroAchievementsDB_MiSTer/db/db.json.zip
```

## Contents

The database is generated automatically from the latest releases of
RetroAchievements core forks under `odelot/*_MiSTer`. Publishing is skipped when
the generated database has no real content changes compared with the current
published DB.
