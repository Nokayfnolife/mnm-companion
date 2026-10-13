# MnM Companion

A level-by-level planner for **Monsters & Memories**: what to do next, gear by slot, quests, camps, armor sets, spells and zone maps with your own pins. Each character follows its level slider. Players sign in to keep their characters, progress and pins on every device.

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
2. **Config.** Put the Project URL and the anon public key in `site/config.js`. Never put the `service_role` key in this repo.
3. **GitHub Pages.** Go to **Settings → Pages → Source** and choose **GitHub Actions**. Every push to `site/` deploys the site.
4. **Wiki refresh.** `Refresh wiki data` runs every 6 hours. You can also start it from the **Actions** tab.

## Run locally

```sh
cd site && python3 -m http.server 8000   # then open http://localhost:8000
./scripts/scan.sh                        # refresh the wiki copy by hand
```

## Credits

Live data comes from [storiesofmnm.com](https://storiesofmnm.com). The map images come from the [Monsters & Memories community wiki](https://monstersandmemories.miraheze.org/), and each map credits its maker in the app. Monsters & Memories is the work of its developers. This is an unofficial fan tool.
