WWI — Google Location History Analyzer
This stands for "Where Was I"

Analyze and visualize your Google Location History with local privacy and detailed travel insights.

Why this project?

Google’s Location History exports are massive and hard to use. This app normalizes those JSON files, enriches them with geocoding, and generates clear reports on where you’ve been, how long you stayed, and how far you traveled.

Works with both old Google Takeout exports and new mobile Timeline exports

Preserves privacy: all processing is local, only coordinates are sent to geocoding APIs

Produces actionable CSVs instead of unreadable JSON

### **What It Does:**
1. **Step 1**: Parses raw Google location JSON files (from mobile devices - NOT the takeout version), allows user to filter by date range, and cleans noisy data by filtering down the data points by duration - do not collect many data points timed close together, by distance - do not collect many data points next to each other, and by probability which is a factor set in the google json.  These filters then are duration in seconds, distance in meters, and probability.  Then the application writes out a parsed json file in the same format as the mobile one, with an added section at the front which defines the dates, and all the filter settings.
2. **Step 2**: Geocodes coordinates from the parsed file to cities/countries and generates travel analysis reports (CSV + HTML views). There are 3 views - days in each city, days in each state (or if outside US by country), and city jumps - this shows travel from city to city with distance travelled between each, and total distance travelled.

Data is stored in a folder structure, but also in a DB via a javascript storage manager.  The files in this system are Master - the original JSON from google, and the parsed files which are the result of the app parsing the Master file.  Clearing the browser cache will destroy any of these files.  It would be nice to be able to RELOAD these into the storage manager if the browser is reset, OR allow the user to optionally load them into the storage manager from the local files.

### User Account Setup
In order to allow different people to use this app, there is a simple user model, which is designed to allow/require a user to use their own API keys, and to work only on their data.  This system creates a user file inside processed folder with the folder there as username. So mainapp/processed/<username> will  contain any data files they have parsed.  In addition, inside the config folder there is a folder called users which contains folders for each username. This folder contains that user's api keys and geo_cache file.  It is supposed to also contain the web_config.json file that contains each user's geoappify and google maps API keys, but in our current version this is broken.  All files each user uploads (master files usually) should be stored in their uploads folder - eg /uploads/<username>/location-history.json.

Features

🔑 Multi-user support — isolated workspaces per user/session

📂 Custom parsed JSON format — speeds up re-runs, embeds filters, and preserves determinism

⚡ Caching & batch geocoding — minimize API calls

🗺️ City jump detection — captures short visits (e.g., Mercer Island → Seattle → Hailey)

✈️ Distance & mode inference — calculates miles traveled and travel mode (driving, flight, walking, etc.)

📊 Rich exports:

location_days_by_month_city.csv (or state/country)

city_jumps_with_mode.csv (chronological jumps with distance + inferred mode)

⚙️ Configurable thresholds — distance, time, probability, API batching


(Raw JSON → Parsed JSON → Geocoding → Analysis → Exports)

Quick Start
Requirements

Python 3.9+

Geoapify API key (required)

Google Maps API key (optional)

Install
git clone https://github.com/tgonser/WWI.git
cd WWI
pip install -r requirements.txt

Run
python unified_app.py


Open a browser to:
👉 http://localhost:5000

Multi-User Sessions

This app supports multiple users by isolating workspaces under ./data/<user_id>/:

data/
 └── <user_id>/
      ├── uploads/     # raw Google JSON exports
      ├── parsed/      # normalized parsed JSON
      ├── cache/       # reverse-geocoding cache
      └── exports/     # CSV/HTML outputs

Full file structure-
Folder PATH listing for volume Overflo
Volume serial number is 047D-A18A
C:\USERS\TOM\PROGRAMMING\UAPP3
¦   .env.txt
¦   .gitignore.txt
¦   analyzer_bridge.py
¦   csv_exporter.py
¦   filestructure.txt
¦   geo_utils.py
¦   legacy_analyzer.py
¦   location_analyzer.py
¦   modern_analyzer_bridge.py
¦   next bugs to fix 8_30.txt
¦   parser_app.py
¦   readme.md
¦   requirements.txt
¦   settings.json
¦   testing data density.txt
¦   unified_app.py
¦   
+---config
¦   ¦   geo_cache.json
¦   ¦   secret.txt
¦   ¦   unified_config.json
¦   ¦   users.json
¦   ¦   web_config.json
¦   ¦   
¦   +---users
¦       +---gonz
¦       ¦       config.json
¦       ¦       geo_cache.json
¦       ¦       
¦       +---tom
¦               config.json
¦               geo_cache.json
¦               
+---outputs
¦   +---gonz
¦   ¦   +---analysis_20250903_095651_fefb6d90
¦   ¦           
¦   +---tom
¦       +---analysis_20250904_080505_76e62d37
¦               
+---processed
¦   ¦   
¦   +---gonz
¦   ¦       01-02-22__04-01-22_parsed_2000_0.5_2000.json
¦   ¦       
¦   +---tom
¦           11-01-24__01-04-25_parsed_2000_0.1_600.json
¦           
+---static
¦   +---css
¦   ¦       storage-styles.css
¦   ¦       
¦   +---js
¦           storage-integration.js
¦           storage-manager.js
¦           
+---templates
¦       login.html
¦       processing.html
¦       register.html
¦       results.html
¦       unified_processor.html
¦       
+---uploads
¦   +---gonz
¦   +---tom
        



🔗 See Multi-User Sessions
 for details.

Custom Parsed JSON Format

After parsing, the app writes a normalized JSON file that:

Saves the applied filters (date range, thresholds, probability)

Records all points chronologically with inferred metadata

Can be reused to skip raw parsing on future runs

🔗 See Custom Parsed JSON Format
.

Configuration

API keys:

GEOAPIFY_API_KEY (required)

GOOGLE_MAPS_API_KEY (optional)

Settings:
config/settings.json controls thresholds and defaults:

Distance threshold: ~600–2000 m

Time threshold: ~100–500 s

Probability threshold: ~0.25 (raising above ~0.65–0.8 may skip visits)

.env example:

GEOAPIFY_API_KEY=your_key_here
GOOGLE_MAPS_API_KEY=optional_google_key

Privacy

All processing is local

Only coordinates are sent to geocoding APIs

Results and caches are stored under your own ./data/<user_id>/

You control API usage, batch sizes, and retention

Contributing

Contributions welcome!
Please open issues or PRs for bugs, improvements, or new features.

License

MIT License (recommended — add LICENSE file at repo root).

Documents

Multi-User Sessions

Custom Parsed JSON Format

✨ With this README, newcomers will immediately see:

What the app does

Why it’s useful

How to run it

Where to learn the advanced details