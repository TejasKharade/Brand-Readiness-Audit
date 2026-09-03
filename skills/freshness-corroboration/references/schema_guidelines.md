# Schema.org JSON-LD Guidelines & Templates for AI Discoverability

## Minimum Recommended Organization Schema

```json
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "name": "Brand Name",
  "url": "https://example.com",
  "logo": "https://example.com/logo.png",
  "sameAs": [
    "https://www.wikidata.org/wiki/Q12345",
    "https://en.wikipedia.org/wiki/Brand_Name",
    "https://twitter.com/brand",
    "https://linkedin.com/company/brand"
  ],
  "description": "Clear concise 1-2 sentence brand summary for machine extraction."
}
```

## Product Schema Checklist

- `@type`: `Product`
- `name`: Product title
- `description`: Detailed specification text
- `offers`: `@type`: `Offer`, `price`, `priceCurrency`, `availability`
