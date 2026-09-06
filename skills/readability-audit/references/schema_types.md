# Supported Schema Types Reference

This reference file documents the supported schema.org structures and expected completeness fields for `check_structured_data.py`.

## Supported Schemas & Expected Fields

### 1. Product
Used for e-commerce or product landing pages.
- `name`: Product title or brand name.
- `offers`: Pricing and availability container (supports single object, array of offers, AggregateOffer, or priceSpecification).
  - `offers.price`, `offers.lowPrice`, `offers.highPrice`, or `offers.priceSpecification.price`: Numerical price value or string.
  - `offers.availability`: Stock status URI or text (e.g. `http://schema.org/InStock`, `InStock`, `OutOfStock`).

### 2. FAQPage
Used for Q&A and help documentation pages.
- `mainEntity`: Array of question entities.
  - `name`: Question text string.
  - `acceptedAnswer.text`: Plain text or HTML answer string.

### 3. Organization / LocalBusiness / Store / Restaurant
Used for brand identity, corporate homepages, and local business metadata.
- `name`: Official organization or business name.
- `url`: Canonical website URL.
- `logo`: Brand logo URL.
- `telephone`: Official phone number.

### 4. Article / NewsArticle / BlogPosting
Used for news, blog posts, and editorial content.
- `headline` or `name`: Article title.
- `author`: Author entity or string.
- `datePublished`: Publication ISO date.
- `image`: Featured article image URL.

### 5. BreadcrumbList
Used for site hierarchy navigation.
- `itemListElement`: Array of breadcrumb items.

### 6. Recipe
Used for culinary and food content.
- `name`: Recipe name.
- `recipeIngredient`: Array of ingredient strings.
- `recipeInstructions`: Preparation steps string or array.
- `image`: Recipe photo URL.

### 7. Event / BusinessEvent / MusicEvent
Used for events, webinars, and ticketing pages.
- `name`: Event title.
- `startDate`: Start ISO date/time.
- `location`: Location entity or text.

### 8. SoftwareApplication / MobileApplication / WebApplication
Used for software products and apps.
- `name`: Application name.
- `operatingSystem`: OS requirements string.
- `offers`: Pricing container.

### 9. VideoObject
Used for embedded video media.
- `name`: Video title.
- `thumbnailUrl`: Thumbnail image URL.
- `uploadDate`: Upload date string.

---

## Supported JSON-LD Structuring Features

- **`@graph` Containers & `@id` Resolution**: Resolves cross-referenced graph nodes across blocks via `@id` URI mapping.
- **URI Prefix Normalization**: Automatically normalizes full schema URIs (e.g. `https://schema.org/Product` -> `Product`).
- **CDATA & HTML Entity Protection**: Strips CDATA/comments and uses safe unescaping fallbacks.
- **Microdata & RDFa Detection**: Returns `"microdata_detected"` and `"rdfa_detected"` boolean flags.
