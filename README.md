# Monsters and Memories Companion

A level-by-level planner for **Monsters & Memories**: what to do next, gear by slot, quests, camps, armor sets, spells and zone maps with your own pins. Each character follows its level slider. Players sign in to keep their characters, progress and pins on every device.

Each character runs in one of two modes, picked when it's created and switchable from the character header:

- **Guided** shows the plan for the level: what to do next, quests, hunting spots, armor sets, bags and spells, plus the gear card. Gear tips and armor-set pieces drop out once what the character wears already beats them.
- **Classic** is a character sheet: a class emblem, starting stats with the 10-point bonus pool to spend, and the equipment picker, with totals added up. "Recommend upgrades" and its sub-option "Show where to find them" are off by default; with them off, drop sources stay hidden in item windows until the player asks. On the map, Classic shows only the player's own pins: plan spots appear only when the player opens one from the sheet ("Show on map"), and the zone's camps and quests are listed only with "Show where to find them" on.

The zone maps are Leaflet image overlays with no zoom snapping; the whole map fits the box the first time the box has a size (`fitIfReady()`), and zoom stops at a little past the image's own size.

**Map places.** Each zone map shows typed places with icons: guild halls, markets, exits, boats and teleporters, camps, named mobs, quests and landmarks. A row of filters sits above the map, with an "Only my level" switch. Labels appear once you zoom in past the whole-map view, highest priority first and never on top of each other; places the map already prints (`onMap`) show their name on hover only. They come from three sources: `places` in `site/curated.json` (Night Harbor's 44 are read off the map's own labels), places players suggest and a moderator approves, and each player's own pins (now with a kind, levels, and where an exit leads). The side panel adds the zones next door (from the wiki's "Travel To & From", read by the scanner into `links` on each zone), your class's guild, and the ways out. Share buttons copy links like `?zone=night-harbor` or `?place=nh-g-wiz`; a link opened while signed out is kept until after sign-in.

**Community places.** Run `supabase/places.sql` once in the SQL Editor, then add yourself as a moderator with the line at the end of that file. Signed-in players get "Suggest for everyone" on their own pins; moderators get a Review button on the map. Until the table exists the site simply hides those buttons.

**Respawn timers.** "Killed it" on any camp (Where to hunt, the map's camp list, or a camp or named pin) starts a countdown, 10 minutes by default and adjustable per camp. Timers are saved with the account as end times, so the phone and the PC show the same countdown; a tray lists them, the tab title says when one is up, and players can turn on browser alerts. "Taken?" lists the nearest other camps for your level, same zone first, then the zones next door.

Starting stats per race and class come from the race pages on storiesofmnm.com (`races` in `site/data/wiki.json`, refreshed with the daily full scan).

The Stats card also records what the player chose at character creation: a **deity** and the four **traits** (Major Combat, Minor Combat, Major Non-Combat, Minor Non-Combat). Traits come from the tables on storiesofmnm.com's new player guide (`traits` in `site/data/wiki.json`, refreshed with the daily full scan, with who may take each one); stat and resist traits are added into the totals. Which gods each race and class may follow, and the starting cities each choice allows, are hand-copied into `deities` in `site/curated.json` from the community wiki's "Starting City by Race, Class, and Deity" table, because that wiki sits behind a bot check the scanner can't pass. Guided (or Classic with upgrade tips on) suggests a Major Combat trait for the class's main stat and the night-vision trait when the race can take it.

The first time someone signs in, Wallabik Ningel (a gnome Master Elementalist) walks them around the page; the steps are `tourSteps()` in the script, each with its own pose from `site/img/wallabik/` (transparent WebP, all on one 428×382 canvas at the same scale with his feet on the same line, so he doesn't jump in size between steps). The ? button or Settings replays it.

Players pick a look under **Settings** (it opens by itself the first time someone signs in): **Field journal** (paper, ink and margin notes; the default, styled by the `html[data-look="journal"]` block at the end of the stylesheet) or **Game window**, which uses the area themes below.

Both looks share the ten area themes in the Theme menu (and in Settings): in the journal each area is a paper and ink pair (`:root[data-look="journal"][data-theme=…]`, eight colors each, everything else mixed from them); in the game look it is lit like the area. The game look's themes each named after an area of the world (Night Harbor at night is the default). They live as CSS variables at the top of the stylesheet in `site/index.html`; the theme menu list is `THEMES` in the script. Six use a darkened community zone map as the sign-in backdrop (`site/img/vista-*.webp`).

Each look also has a light and a dark mode (`html[data-mode="light"|"dark"]`), picked in the Theme menu or Settings: Light, Dark or Match device (follows the device's own setting). Until someone picks, the journal is light and the game window dark, as before. The dark journal ("by lamplight") and the light game window ("daylight") each have their own palette per area theme, in the `[data-mode]` blocks of the stylesheet; they were generated from the original palettes in OKLCH and checked for WCAG AA contrast. Hard-coded black outlines and shadows in the game look are tokens (`--k`, `--tsh`, `--sh`, `--sha`) so the light mode can soften them. The choice is saved with the account (`mode`) and in the browser (`mnm-mode`), and the head script applies it before the page paints.

- `site/` is the static website, served by GitHub Pages
- `site/data/wiki.json` is a copy of storiesofmnm.com. A GitHub Action refreshes it every 6 hours.
- `site/config.js` holds the Supabase URL and the public anon key
- `supabase/schema.sql` creates the `user_data` table and its row-level security
- `scanner/mnm_companion.py` is the stdlib-only wiki scanner. `scripts/scan.sh` runs it against the site data.

## Setup

1. **Supabase**
   1. Create a project.
   2. Open **SQL Editor** and run `supabase/schema.sql`.
   3. Under **Authentication → URL Configuration**, set *Site URL* to your Pages URL (for example `https://<user>.github.io/mnm-companion/`) and add the same URL under *Redirect URLs*.
   4. Optional: enable Discord or Google under **Authentication → Providers**, then list them in `providers` in `site/config.js`.
   5. For **Ask the guide**: run `supabase/ask.sql` in the SQL Editor, deploy `supabase/functions/ask/index.ts` as an Edge Function named `ask`, and add an `ANTHROPIC_API_KEY` secret under **Edge Functions → Secrets**. Optional secrets: `ASK_DAILY_LIMIT` (questions per player per day, default 25) and `ASK_MODEL`.
2. **Config.** Put the Project URL and the anon public key in `site/config.js`. Never put the `service_role` key in this repo. `donateUrl` adds a "Support the site" link; `ask: false` hides the AI helper.
3. **GitHub Pages.** Go to **Settings → Pages → Source** and choose **GitHub Actions**. Every push to `site/` deploys the site.
4. **Wiki refresh.** `Refresh wiki data` runs every 6 hours. You can also start it from the **Actions** tab.

## Run locally

```sh
cd site && python3 -m http.server 8000   # then open http://localhost:8000
./scripts/scan.sh                        # refresh the wiki copy by hand
```

## Credits

Live data comes from [storiesofmnm.com](https://storiesofmnm.com). The map images come from the [Monsters & Memories community wiki](https://monstersandmemories.miraheze.org/), and each map credits its maker in the app. Monsters & Memories is the work of its developers. This is an unofficial fan tool.
