"""
Constants and registry configurations for AI Crawler Access & Protocol Audit.
Standard library only.
"""

BOT_UA = "Mozilla/5.0 (compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot)"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

LIVE_SEARCH_BOTS = {
    "oai-searchbot": "OpenAI Search / ChatGPT Search",
    "perplexitybot": "Perplexity AI Search",
    "claude-web": "Anthropic Claude Web Search",
    "google-extended": "Google Gemini / Extended"
}

TRAINING_BOTS = {
    "gptbot": "OpenAI Model Training",
    "ccbot": "Common Crawl Training Scraper",
    "bytespider": "ByteDance Training Scraper"
}

HARMFUL_PATH_PATTERNS = [
    r"^/$", r"^/\*$", r"^/docs", r"^/documentation", r"^/blog",
    r"^/products?", r"^/pricing", r"^/about", r"^/guides?"
]

PAGE_MEDIA_EXTS = (
    '.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif', '.ico',
    '.pdf', '.zip', '.tar', '.txt', '.json', '.css',
    '.js', '.m3u8', '.mp4', '.mov', '.ts', '.webm', '.avi',
    '.mp3', '.wav', '.woff', '.woff2'
)

NON_HTML_EXTS = (
    '.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif', '.ico',
    '.pdf', '.zip', '.gz', '.tar', '.xml', '.txt', '.json',
    '.css', '.js', '.m3u8', '.mp4', '.mov', '.ts', '.webm',
    '.avi', '.mp3', '.wav', '.woff', '.woff2'
)

IMPORTANT_PATH_PATTERNS = r"/(docs?|documentation|guides?|learn|api|manual|products?|items?|pricing|plans|security|trust|about|compliance|support)/"
