# Bot User-Agent Reference

List of User-Agent strings for common AI assistants and search crawlers.

> [!NOTE]
> **Which crawler does what** (live AI search / assistant retrieval vs. model training, and whether a
> robots.txt rule actually applies to it) is recorded separately in `ai_crawler_classes.json`, which
> `check_robots.py` reads. That file's entries marked `"verified": true` were checked against each
> operator's own crawler documentation; the User-Agent strings below were not.

> [!CAUTION]
> **Verification Disclaimer:** The values in this table were assembled from general knowledge and unverified documentation samples. They have **NOT** been live-tested or independently verified against current provider documentation. All User-Agent strings are marked as `Unverified-Pending` and MUST be verified before relying on test results for final submission.

| Bot Name | User-Agent String | Official Documentation / Source | Verification Status | Last Verified |
|---|---|---|---|---|
| GPTBot | `Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)` | https://platform.openai.com/docs/gptbot | Unverified-Pending | Never |
| ChatGPT-User | `Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot` | https://platform.openai.com/docs/plugins/bot | Unverified-Pending | Never |
| ClaudeBot | `Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.5735.199 Mobile Safari/537.36 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)` *(Note: Suspicious mobile-device embedding — verify against official Anthropic docs)* | https://support.anthropic.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web | Unverified-Pending (Suspicious) | Never |
| PerplexityBot | `PerplexityBot/1.0` *(Placeholder)* | https://docs.perplexity.ai/ | Unverified-Pending | Never |
| Bytespider | `Bytespider; spider-feedback@bytedance.com` | https://zhanzhang.toutiao.com/ | Unverified-Pending | Never |
| CCBot | `CCBot/2.0 (https://commoncrawl.org/faq/)` | https://commoncrawl.org/faq/ | Unverified-Pending | Never |
| Google-Extended | `Mozilla/5.0 (compatible; Google-Extended/1.0; +http://www.google.com/bot.html)` | https://developers.google.com/search/docs/crawling-indexing/overview-google-crawlers | Unverified-Pending | Never |
| Googlebot | `Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)` | https://developers.google.com/search/docs/crawling-indexing/overview-google-crawlers | Unverified-Pending | Never |
| Bingbot | `Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)` | https://www.bing.com/webmasters/help/which-crawlers-does-bing-use-8c184ec0 | Unverified-Pending | Never |

