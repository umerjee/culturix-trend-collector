"""
Not imported anywhere — reference for the settings a real Scrapy project's
settings.py needs to run TrendVelocityPipeline. Copy what you need into your
actual settings.py once a spider exists.
"""

# process_item/open_spider/close_spider are async def — requires the asyncio reactor.
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

ITEM_PIPELINES = {
    "culturix_scraping.pipelines.TrendVelocityPipeline": 300,
}

# likes/hour-equivalent a post must cross to fire the content-engine hook (hooks.py)
VELOCITY_THRESHOLD = 500.0

# Respect robots.txt by default — flip deliberately per-source, not globally.
ROBOTSTXT_OBEY = True

# Bandwidth note: Scrapy never fetches image/video URLs on its own — only if a
# spider explicitly yields Requests for them, or enables ImagesPipeline/
# FilesPipeline (neither is configured here). The actual bandwidth saving is
# in the spider itself: parse the JSON response for the fields you need
# (view_count, like_count, ...) and simply never issue a Request for the
# thumbnail/video CDN URLs also present in that payload.
