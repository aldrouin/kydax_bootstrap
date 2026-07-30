# Kydax Bootstrap

Home Assistant custom integration that provisions a fresh HA box for a
restaurant venue in one go. A fresh box only needs HACS and Kydax
Bootstrap installed manually — bootstrap does the rest:

- **Installs the components** listed in the venue bundle straight from
  GitHub releases: the Kydax integrations (kydax_sound, kydax_light,
  kydax_test) and frontend plugins such as kiosk-mode. Restarts HA when
  files changed, then resumes automatically.
- **Creates the Kydax configurations** (config entries) from the bundle —
  the same portable payloads the integrations export, plus the site values
  asked by the wizard (Symetrix address, light source, local light
  entities).
- **Builds the customer dashboard**: tabs, cards for the kydax entities,
  background image, and the kiosk-mode lock (header/sidebar hidden for
  non-admin users).
- **Centralized auto-update**: one nightly 4 AM check for every component
  in the bundle, opt-in via a switch (default off), `[critical]` releases
  install regardless, a single restart for everything. kydax_light's own
  updater stands down automatically when bootstrap is present.

## The bundle

One JSON file describes a venue: components (repo + version), the
kydax_sound and kydax_light configurations, the dashboard (views use
`$sound:<suffix>` / `$light:<suffix>` placeholders resolved through the
entity registry), and update policy. Export it from a configured venue via
Options → Export, import it on the next venue and run the wizard.

## Install

HACS → custom repository `aldrouin/kydax_bootstrap` → install → add the
"Kydax Bootstrap" integration and follow the wizard.

## Manual steps that stay manual

- Creating the non-admin HA user for the tablet (Settings → People), and
  pointing the kiosk browser at `/restaurant`.
- Installing HACS itself.
