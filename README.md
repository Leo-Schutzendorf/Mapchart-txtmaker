# Election Map — Setup Instructions

## Folder structure (what you need)

```
your_folder/
├── app.py               ← Flask server (new)
├── namechanges.py       ← your existing file, unchanged
├── templates/
│   └── index.html       ← the web frontend (new)
└── setup.bat            ← one-time installer (Windows)
```

Your original script file is no longer needed — its logic is built into app.py.

---

## First-time setup (do this once)

1. Put all the files above in the same folder.
2. Double-click **setup.bat** — it installs Flask and the other required packages.

---

## Running the app

1. Open a terminal / command prompt in your folder.
   - Windows: Shift+right-click in the folder → "Open PowerShell window here"
2. Type:  `python app.py`
3. You'll see something like:  `Running on http://127.0.0.1:5000`
4. Open your browser and go to:  **http://127.0.0.1:5000**

---

## Using the app

- Type an election year (e.g. 2012) and click **Generate**.
- Each state scrapes one by one — you'll see a progress bar. Takes ~30–60 seconds.
- Once done, a JSON block appears. Click **Copy JSON**.
- Go to https://mapchart.net/usa-counties.html
- Click Menu → Load / Save → Load from JSON → paste → Load.

## Caching

Results are cached in memory while the server is running.
If you generate a map, closing and reopening the app clears the cache.
(For permanent caching, ask for an upgrade to save results to disk.)
