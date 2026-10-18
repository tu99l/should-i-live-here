# Setup: run Should I Live Here? yourself

Back to the [README](../README.md).

## What you need
- A Mac with **Python 3.11+** and **Homebrew** (for the share link tool).
- To try the iMessage bot: an **iPhone** with iMessage. The bot uses Photon's shared iMessage line, so Android
  phones (SMS) can't reach it.

## 1. Install
```bash
git clone https://github.com/tu99l/should-i-live-here.git
cd should-i-live-here
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
brew install cloudflared        # only for the roommates' share link
```
On an Intel Mac, if `pip` fails building `cryptography`, run
`.venv/bin/pip install --only-binary=cryptography cryptography` first.

## 2. Add your keys to `.env`
Open it with `open -e .env`, paste each key after its `=`, and save. `.env` is git-ignored: **never commit it or
paste keys into chat**. Every key is optional; each one turns on more of the app.

| Key | Where to get it | What it turns on |
| --- | --- | --- |
| *(none)* | | The 12 demo listings near UCLA, "Load demo group", the scoring and fair pick, short texts like "laundry 5, rent 3" |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com) | Reading wishes in people's own words, reading pasted listings, the plain-English summary |
| `GOOGLE_MAPS_API_KEY` | Google Cloud console: enable **Routes API** and **Places API (New)**, and set a billing cap first | Walk/bike/transit times to anywhere, "near a gym"-style wishes, finding any place by name |
| `RENTCAST_API_KEY` | [rentcast.io](https://www.rentcast.io/api): free **Developer** plan (50 requests/month), then activate it in the API dashboard | "Find real listings near here" and the welcome screen's live search. Each area is fetched once and cached; the app stops at 45 new areas a month (`RENTCAST_MONTHLY_CAP`) so you're never charged |
| `PHOTON_API_KEY` + `PHOTON_PROJECT_ID` | [Photon dashboard](https://app.beta.photon.codes): your project's id and **API keys** | Adding roommates by phone and the iMessage bot |

Every Gemini, Google and RentCast answer is saved in `cache/`, so anything already looked up works again with no
network and no cost.

## 3. Run it
Use one terminal tab per line, from the project folder:
```bash
.venv/bin/uvicorn app.main:app --port 8000      # the website: http://localhost:8000
.venv/bin/python -m app.photon_bot              # the iMessage bot (needs the Photon keys)
.venv/bin/python scripts/share_link.py          # the roommates' view-only link (needs cloudflared)
```
- The website opens on the welcome screen. Add `#app` to the address to skip it.
- `share_link.py` prints a link like `https://<random>.trycloudflare.com/share/<secret>`. The page also shows it
  under the pick, and the bot texts it. The `<random>` part changes every time it starts, so start it once and
  leave it running. Through that link only the view-only results page answers; nothing can be edited or cost money.
- Run the bot on **one laptop only**: the group lives in that laptop's `data/group.local.json`.

## 4. Try it with a roommate
1. Welcome screen: say what you want, where you go, how many people, your name.
2. "+ Add a roommate": their name and phone number.
3. They text anything to the number shown, from their iPhone's Messages app. The bot answers with a checklist.
4. Whatever they text fills their card and updates the pick. Text "pick" for the current pick and the map link.

## Demo-day checklist
- Start all three commands above before judging and keep them running (they stop if the terminal closes).
- Use the demo laptop with browser extensions off (ad blockers can block the map), and hard refresh (Cmd+Shift+R).
- "Load demo group" gives Alex, Sam and Jordan for a demo without phones. Demo moments are in `TASKS.md`.
- Gemini can occasionally take a minute to read a long text; short texts ("laundry 5") are instant.

## Troubleshooting
| You see | Why, and what to do |
| --- | --- |
| "iMessage is not set up" | `PHOTON_API_KEY` / `PHOTON_PROJECT_ID` missing from this laptop's `.env` |
| The bot says "I don't know this number yet" | That phone isn't in the group: add them with "+ Add a roommate" |
| A roommate's texts never arrive | They aren't on iMessage (Android/SMS), or weren't added before texting |
| "Stopped to avoid charges" on a search | The monthly RentCast cap is reached; areas already searched still work |
| "Couldn't reach Gemini / Google Maps" | No network or no key; demo data and anything cached still work |
| The map is blank or unstyled | An ad blocker blocked the map files: turn extensions off or use a private window |
| `Address already in use` | The app is already running in another tab (or stop it with Ctrl+C there) |

## Where things are saved (all git-ignored)
- `data/group.local.json`: the group (people, phone numbers, wishes, listings). Phone numbers never leave this laptop
  except to Photon.
- `data/share.local.json`: the share link's secret part. `cache/`: saved API answers and the bot's bookkeeping.
- "Start over" on the page clears the group; deleting `data/group.local.json` does the same.

## Tests
```bash
.venv/bin/python -m pytest -q
```
132 tests. Nothing in them calls the internet or sends a text: Gemini, Google, RentCast and Photon are all faked.
