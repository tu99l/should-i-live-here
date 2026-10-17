# Idea 1: Should I Live Here? (project brief)

Oct 17, 2026 · @freddy

## The pitch

Should I Live Here? helps roommates agree on an apartment: it turns pasted listings into a map, scores each place using real commute data and every roommate's priorities, and lets roommates give their input by text message. The name is a placeholder.

Spoken version, about 30 seconds: "Finding an apartment with roommates means three people, forty tabs and one group chat that never agrees. We built a map where every listing becomes a card with the rent per person, the real walk time to campus and a plain-English verdict. Each roommate tells the app what matters to them, and it picks the place that works best for everyone and shows its math. One of us just went through this near UCLA, so we built the tool we wanted."

## The problem and who it is for

The user is a student or young renter choosing a shared apartment near a campus, starting with UCLA and Westwood. Three things make it painful:

- Listings sit on different sites, and the useful facts (rent per person versus whole-unit price, laundry, parking, real walking time) are buried or missing.
- Each roommate weighs those facts differently, so the group chat never converges.
- Scams and misleading pricing are common; one of us found a listing with fake photos and another with a confusing per-bed pricing structure during a 12-listing search.

This is a problem we have lived, which makes the demo and the Q&A easy to answer honestly.

## How it works end to end

&#91;embedded content: how it works · 7 steps, 1 optional\]

Gemini only reads the pasted text and explains results; Google supplies the real distances; our own scoring and group-decision code makes the call. The dashed box is added only if the Photon test passes.

## Stack and keys

Claude Code writes the code, but it is not part of the finished app. The maps data does not come from Gemini: it comes from Google Maps Platform, which is a separate Google product with its own key.

| Piece | What it does | Key from |
| --- | --- | --- |
| Claude Code | Writes the code on each teammate's laptop | Your Claude account |
| Gemini API | Turns pasted listing text into structured fields and writes the plain-English explanations | Google AI Studio |
| Google Maps Platform | Real walk and bike times, nearby groceries and transit | Google Cloud console (enable the routing and places APIs; billing is likely required) |
| Our scoring code | Weights, the score breakdown, the group decision | None |
| Photon 2.0 beta (optional) | Sends and receives the iMessages | Photon dashboard (free beta) |
| Leaflet with OpenStreetMap tiles | The map and hover cards, reused from the earlier UCLA apartment map | None |

The three keys are Gemini, Maps and Photon:

- Keep all of them in a `.env` file that is listed in `.gitignore`, and commit a `.env.example` with fake values. The repo has to be public for Devpost.
- Each teammate makes their own keys, or shares one privately by text. If a key ever lands in git, delete it and create a new one.
- Set a billing cap on the Google Cloud project before the first Maps call, and cache every response.
- The existing Gemini key from AI Studio probably will not work for Maps; check in the Cloud console and test one address first.
- Backend language is not decided. Python is a sensible default because Google's Gemini SDK and Photon both support it, but confirm Photon's expected route at their booth.

## Why it is not just an API wrapper

The judging rubric (slide 12 of the LA Hacks pitching deck) calls a basic app, API wrapper or template build a score of 1 on Technical Depth, and a generic idea a 1 on Originality. The scores below are our own estimates, not official.

| Rubric category | The risk | How this build answers it |
| --- | --- | --- |
| Technical Depth | "Paste text, Gemini gives a verdict" is the wrapper pattern | The scoring is our own code with user-set weights and a visible breakdown; Gemini only extracts fields and explains. Distances come from Google APIs, not the model. |
| Product Thinking and Impact | A vague user | A named user (student roommates near a campus) and a lived problem. |
| Originality and Insight | Apartment finders already exist | The twist is the group decision: every roommate's priorities in, a fair pick out, conflicts flagged. Roommates give input by iMessage through Photon instead of making accounts. |
| Execution and Polish | A fragile live demo | Pre-loaded demo listings, cached API results, validated Gemini output, "unknown" shown instead of guessed values. |

Wrapper test to run before the pitch: if Gemini were removed, would anything useful remain? Could a pasted ChatGPT prompt give the same result? Every displayed number must come from an API or the pasted text, never from the model's memory.

## Track and prize fit

Submit under Applied Intelligence (one main track is required on Devpost), then opt into the company challenges that really fit. Prize details below come from the LA Hacks tracks page and Photon's own post in the event Discord.

| Track or challenge | How this project fits | Open item |
| --- | --- | --- |
| Applied Intelligence (main track) | AI applied to an everyday decision for a real community | None |
| MLH, Best Use of Gemini API | Gemini extracts listing facts and writes explanations | Write a short note on which Gemini features are used |
| MLH, Best Domain Name from GoDaddy Registry | A creative domain for the app | Ask the MLH table how to claim it |
| Photon, iMessage track ($400 cash and $300 credits for first, $300 for second) | Roommates give priorities by text and receive the fair pick | Beta; group-chat support and setup unconfirmed |
| Sentry (optional) | Easy add-on for a web app | Needs two or more Sentry products; only if time is left |

Skipped on purpose: Model Learning, Beyond the Digital, veri.studio, Workday, Visa, Base44 and Paper (not using either; Base44's challenge requires building on Base44).

## Build order, owners and checkpoints

Build the web version first; Photon is added only after steps 2 to 5 work end to end. The deadline is 12:00 PM Sunday with no buffer, so the target is to submit by 11:00 AM. Owners are a suggestion: swap them if your teammate is stronger at code.

| # | Step | Owner | Target | Done when |
| --- | --- | --- | --- | --- |
| 1 | Repo, .env, .gitignore, CLAUDE.md; pick one backend language | Both | 2:30 PM | Both can run the app locally; no keys in the repo |
| 2 | Gemini turns pasted listing text into validated structured fields | Freddy | 4:00 PM | Three sample listings parse correctly; missing fields show "unknown" |
| 3 | Own scoring function with user-set weights and a visible breakdown | Freddy | 5:00 PM | Score changes when weights change; no model-generated scores |
| 4 | Google routing and places lookup, cached, with a billing cap set | Freddy | 6:00 PM | Real walk or bike time shown on each card |
| 5 | Map with price-colored markers and hover cards (reuse the earlier UCLA map) | Teammate | 5:00 PM | Pre-loaded demo listings render with full cards |
| 6 | Group decision: several roommates' priorities, fairest pick, conflicts flagged | Freddy | 8:00 PM | App names one pick and says who it favors least |
| 7 | Photon iMessage test and integration (gated) | Whoever is free | Start about 6:00 PM | Agent replies to a text on a real phone by 7:00 PM, otherwise cut it |
| 8 | Design pass: palette, one font pair, empty states, loading messages | Teammate | 10:00 PM | Screens look like one product |
| 9 | Draft Devpost, thumbnail (5:3), README | Teammate | 11:00 PM | Draft saved; edit later |
| 10 | Sleep in shifts; stability fixes only after the freeze | Both | 1:00 to 6:00 AM | Main flow still works on a fresh browser |
| 11 | Feature freeze, tag the build | Both | 6:00 AM | No new features |
| 12 | Demo video recorded and uploaded to YouTube | Teammate | 9:00 AM | Link works (it must be YouTube) |
| 13 | Devpost submitted with all teammates added | Both | 11:00 AM | Each teammate used the email they applied with |

If time runs short, cut in this order: the scam-warning checks, then Photon, then extra polish. Never cut steps 2 to 5.

## Demo script

LA Hacks judging gives you 2 minutes of pitch and 3 of questions per table, and 3 minutes plus 4 of questions on stage for the Top 5. The deck suggests a "movie" path: problem, tension, resolution. One of you demos while the other talks, and the talking is split evenly.

Two-minute table version:

1. Hook, 15 seconds: the group chat that never agrees on an apartment.
2. Paste three listings, 25 seconds: the map fills in and cards appear.
3. Hover a card, 20 seconds: rent per person, real walk time, nearby groceries, and the score breakdown.
4. The tension, 35 seconds: two roommates with different priorities rank the places differently; the app flags who would be unhappy.
5. The resolution, 15 seconds: it names the fairest pick and shows the math. If Photon works, show the roommate's phone receiving the pick by text.
6. Close, 10 seconds: what we learned and what is next.

Three-minute stage version adds a one-slide diagram of how it works and a line on what was hard.

Prepare for the likely question, "How is this different from Zillow or ChatGPT?" Answer: they show one person's search; this combines real commute and neighborhood data with every roommate's priorities and shows the math, so a group can agree.

Rules for the demo: use pre-loaded listings, never type a new prompt live, keep a backup video open in a tab, and use a phone hotspot if the venue Wi-Fi is slow.

## Risks and fallbacks

| Risk | Fallback |
| --- | --- |
| Google routing and places calls cost money or hit quotas | Set a billing cap first, cache every result, pre-load the demo listings |
| Photon beta setup fails or group chat is unavailable | Use one-on-one texts per roommate, or a simple web page for roommate priorities; the web app already stands alone |
| Gemini returns malformed or wrong fields | Validate the output, show "unknown" for anything missing, never guess |
| Venue Wi-Fi or API rate limits during judging | Pre-saved results, phone hotspot, backup video |
| Keys or tokens leak in the public repo | Keep .env and any MCP config out of git; delete and replace a key if it ever leaks |
| Scope grows | Follow the cut order in the build plan; do not scrape Zillow, have users paste listing text |

## Questions for the booths and organizers

- [ ] Photon: does the beta support iMessage group chats, and what setup or hardware is needed?
- [ ] Photon: is a TypeScript or Python SDK the expected route, and can Claude Code build against it?
- [ ] MLH: how do we claim the GoDaddy domain prize?
- [ ] Organizers: how many company challenges can one project enter, and is the team size limit published?
- [ ] Organizers: are AI coding tools and existing open-source code allowed (disclose in Devpost either way)?
