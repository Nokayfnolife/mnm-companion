# Monsters and Memories Companion

A level-by-level planner for **Monsters & Memories**: what to do next, gear by slot, quests, camps, armor sets, spells and zone maps with your own pins. Each character follows its level slider. Players sign in to keep their characters, progress and pins on every device.

Each character runs in one of two modes, picked when it's created and switchable from the character header:

- **Guided** shows the plan for the level: what to do next, quests, hunting spots, armor sets, bags and spells, plus the gear card. Gear tips and armor-set pieces drop out once what the character wears already beats them.
- **Classic** is a character sheet: a class emblem, starting stats with the 10-point bonus pool to spend, and the equipment picker, with totals added up. "Recommend upgrades" and its sub-option "Show where to find them" are off by default; with them off, drop sources stay hidden in item windows until the player asks.

Starting stats per race and class come from the race pages on storiesofmnm.com (`races` in `site/data/wiki.json`, refreshed with the daily full scan).

Players pick a look under **Settings** (it opens by itself the first time someone signs in): **Field journal** (paper, ink and margin notes; the default, styled by the `html[data-look="journal"]` block at the end of the stylesheet) or **Game window**, which uses the area themes below.

Both looks share the ten area themes in the Theme menu (and in Settings): in the journal each area is a paper and ink pair (`:root[data-look="journal"][data-theme=…]`, eight colors each, everything else mixed from them); in the game look it is lit like the area. The game look's themes each named after an area of the world (Night Harbor at night is the default). They live as CSS variables at the top of the stylesheet in `site/index.html`; the theme menu list is `THEMES` in the script. Six use a darkened community zone map as the sign-in backdrop (`site/img/vista-*.webp`).

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
