# Real-robot maps

`live_navigation_20261023_1938.yaml` and its PGM are the saved map used by the
current robot. This map is site-specific; it is not a generic campus map.
Run `scripts/start_mapping.sh`, save a new map with `scripts/save_map.sh`, then
select its YAML with `scripts/start_autonomy.sh --map` when the environment changes.

`web_goals.example.json` contains the saved destinations for this exact map.
To use them as the initial local destination store, before starting the web UI:

```bash
cp -n maps/web_goals.example.json maps/web_goals.json
```

The writable `web_goals.json` and backup are ignored by Git. Destinations are
keyed by map contents, dimensions, resolution and origin; a different map needs
its own destinations.
