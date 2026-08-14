# BrickMissing 8.0 Integration Matrix

Updated 2026-08-12: provider selection is in normal UI; owner-scoped Pick a Brick is linked from missing parts. SSRF controls and no-key/timeout/401/403/429/500/malformed/empty paths are tested; prices use Decimal. Live verification requires external credentials and is not claimed.

| Integration | V7 capability | V8 capability | Authentication | Tests | Status |
|---|---|---|---|---|---|
| Rebrickable | Set, part, minifigure and instruction metadata | Owned-set synchronization and instruction fallback | Environment API key | Mocked success, ownership and fallback | COMPLETE |
| BrickEconomy | Set market value | Set market value and price observation | Environment API key | Controlled client/view path | COMPLETE |
| Brickset | Set metadata and LEGO retail price | Set retail/market price lookup and price observation | Environment API key | Success and empty/error responses | COMPLETE |
| BrickLink | OAuth price guide | OAuth 1.0 signed set price guide and price observation | Four environment OAuth values | Success, malformed, 401/403, 429, 500 and timeout | COMPLETE |
| LEGO Pick a Brick | HTML product search and price extraction | Official localized product search link by part number | None | URL construction | REPLACED |

The Pick a Brick replacement intentionally does not scrape LEGO HTML. The V7 parser depended on non-contractual JSON-LD page markup and could silently return incomplete prices after storefront changes. V8 sends users to the official LEGO result page and does not persist an unverified scraped price.
