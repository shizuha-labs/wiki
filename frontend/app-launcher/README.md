# Atlas App Center launcher

This is the static launch surface for the Atlas app. The full architecture explorer, design studio and organization-bound Guide remain in the authorized Wiki workspace. The launcher deliberately does not frame Wiki or weaken its frame-denial headers.

Explore opens `/atlas`; New design opens `/atlas/editor`. The bottom-left Guide entry opens `/atlas?guide=1`. Only a positive safe-integer `shizuha_organization_id` from browser storage is carried as `organization`. There are no dynamic redirects, credentials, remote assets or private model data. The schematic is clearly labeled an illustration, not a live system view.

Run `node frontend/app-launcher/verify.mjs` from the Wiki repository. Package using `node frontend/app-launcher/build.mjs /path/outside/repository/atlas-launcher.tar.gz`. Output creation is exclusive and refuses to replace an existing bundle. The archive contains exactly top-level `index.html`, `atlas.css` and `navigation.mjs`, matching the SCS app-bundle contract. Deployment and blueprint activation are separate authenticated platform operations.
