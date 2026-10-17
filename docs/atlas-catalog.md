# Atlas catalog

The system catalog and the signed-in Atlas application live in the Origin repository `shizuha-labs/atlas`. Wiki does not publish the catalog or serve `/atlas/`.

A Wiki page can still contain an Atlas document in an `atlas` fence. Wiki renders that fence by embedding `/atlas/embed`. Editing a map happens in Atlas.

The catalog checker for the shipped model is `scripts/check_catalog.py` in the Atlas repository.
