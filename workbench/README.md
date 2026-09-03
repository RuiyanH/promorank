# MarketRank Workbench

Internal, historical candidate-exploration UI for the MarketRank v1 release.

## Product boundary

This application reads the checked-in static release at
`public/data/demo-release.json`. It lets reviewers browse a small set of opaque
demo customers, inspect each ordered top-12 candidate slate and its source
evidence, review full-cohort retrieval diagnostics, and record structured
feedback events with UUID identities in local browser storage.

It is not a consumer storefront, a live recommender, or a trained-ranker
serving layer. It intentionally contains no price, inventory, probability,
confidence, revenue, discount, free-text feedback, or shared persistence.

## Routes

- `/` — release overview and interpretation boundaries
- `/customers` — searchable demo-customer browser
- `/customers/[customerRef]` — candidate detail and local review workbench
- `/quality` — source diagnostics, definitions, and limitations

## Local verification

```bash
npm ci
npm run lint
npm run build
npm test
```

The test suite validates the release adapter against a small internal fixture
and the generated release, checks contract failure modes and feedback
idempotency, and server-renders all four routes from the production build.
