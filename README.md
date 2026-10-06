# Aviation Spares Supplier Intelligence

A zero-cost-first Streamlit portfolio app for aviation materials sourcing and supplier comparison.

## What it does

- Searches and filters aviation spares offers
- Normalizes listed prices to USD
- Scores offers using price, lead time, stock and reliability
- Maps supplier locations
- Exports filtered intelligence to CSV
- Supports optional Apify Actor collection for live supplier/product URLs

## Public API enrichment

The initial version uses:

- **Frankfurter** for currency conversion
- **Nominatim / OpenStreetMap** for geocoding

These were selected from the `public-apis/public-apis` catalogue as no-key public APIs. Availability and fair-use limits remain subject to each provider.

## Apify integration

The app supports a configurable Actor instead of hard-coding one supplier scraper. Set the following in Streamlit Secrets when you are ready for live runs:

```toml
APIFY_TOKEN = "your-token"
APIFY_ACTOR_ID = "username/actor-name"
```

Do **not** commit API tokens to GitHub.

Apify's API supports running an Actor and receiving its default dataset items. The app uses a synchronous Actor-run pattern so a user can start collection from the Streamlit UI and inspect the returned dataset.

## Local run

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Create a public GitHub repository, suggested name: `aviation-spares-supplier-intelligence`.
2. Upload the files in this project.
3. Create a Streamlit Community Cloud app with `app.py` as the entrypoint.
4. Add `APIFY_TOKEN` / `APIFY_ACTOR_ID` in Streamlit Secrets only if you want live Apify collection.

## Demo data

`data/sample_spares.csv` contains fictional/sample records for portfolio demonstration only. It is not approved procurement data and must not be treated as proof of stock, price, certification, traceability or airworthiness.

## Roadmap

- Source-specific Apify extraction templates
- Better part-number normalization and duplicate clustering
- RFQ shortlist builder
- Supplier history and price-change tracking
- Optional Supabase persistence
- Email-ready sourcing report
