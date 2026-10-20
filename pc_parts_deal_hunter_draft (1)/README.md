# PC Parts Deal Hunter — draft

**Purpose:** Search eBay for GPUs, DDR4 RAM, DDR5 RAM, CPUs, motherboards, and PC cases, then send possible deals to a Discord channel.

## Current draft behavior
- Uses eBay's official Browse API, not page scraping.
- Checks a set of editable searches.
- Default cap: $100 total before tax.
- Default threshold: at least 25% below a rough median of active search results.
- Excludes titles containing common parts-only/broken/untested phrases.
- Sends at most 8 alerts per scan.
- Workflow is scheduled every 30 minutes, subject to GitHub Actions scheduling delays.
- No automatic purchases.

## Important caveat
The median comparison is only a rough signal: results can mix different models, capacities, conditions, and included accessories. It is not a verified fair market value or a guarantee of profit. Always inspect the actual listing. Shipping may be absent or estimated in API results. This draft needs live credential setup and testing before use.

## Setup checklist

1. Create a **private** GitHub repository.
2. Upload `bot.py` and `.github/workflows/scan.yml`.
3. Create an app in the eBay Developers Program and obtain production App ID (Client ID) and Cert ID (Client Secret). Confirm your account has access to the Browse API.
4. In Discord, open the target channel settings → **Integrations → Webhooks → New Webhook**. Copy the webhook URL privately.
5. GitHub repository → **Settings → Secrets and variables → Actions → New repository secret**. Add:
   - `EBAY_CLIENT_ID`
   - `EBAY_CLIENT_SECRET`
   - `DISCORD_WEBHOOK_URL`
6. The workflow needs repository write permission to save `seen_items.json`; verify Actions workflow permissions allow it to push. If not, use a persistent store or adjust repository Actions permissions.
7. In the **Actions** tab, enable workflows and manually run **Scan eBay PC part deals** to test.
8. Check logs and Discord. Never paste API keys or webhook URLs into code, commits, screenshots, or chat.

## Adjusting searches
Edit `SEARCHES` in `bot.py` to add/remove models. Edit the workflow environment variables for maximum price, minimum discount, and max alerts. The code currently searches a small set of specific models so the comparison is more useful than a broad search.

## Suggested next improvements
- Store history in a database rather than a committed JSON file.
- Compare only the same exact model, memory capacity, and condition.
- Add sold-price/completed-sale analysis if an authorized data source is available.
- Add per-category budgets and a seller/return-policy review.
- Add tests and API rate-limit/backoff handling.
