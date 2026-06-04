import os
import re
import sys
import scrapy
import threading
import nltk
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from urllib.parse import urlparse

# Descargar recursos de NLTK
nltk.download('punkt')
nltk.download('wordnet')
nltk.download('omw-1.4')

KEYWORDS = {"fiesta", "fiestas de", "festividad", "fiestas patronales"}

class TimeoutException(Exception):
    pass

class PageItem(scrapy.Item):
    url = scrapy.Field()
    page_number = scrapy.Field()
    markdown = scrapy.Field()
    image_urls = scrapy.Field()
    images = scrapy.Field()
    twitter = scrapy.Field()
    instagram = scrapy.Field()
    facebook = scrapy.Field()

class MySmartSpider(scrapy.Spider):
    name = "mysmartspider"
    start_urls = []
    allowed_domain = ""
    visited_urls = set()
    page_count = 0

    found_twitters = set()
    found_instagrams = set()
    found_facebooks = set()

    custom_settings = {
        "FEED_FORMAT": "jsonlines",
        "FEED_URI": "scraped_output.jl",
        "LOG_ENABLED": False,
        "DOWNLOAD_DELAY": 0,
        "CONCURRENT_REQUESTS": 32,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 32,
        "AUTOTHROTTLE_ENABLED": False,
        "ROBOTSTXT_OBEY": True,
        "ITEM_PIPELINES": {
            'scrapy.pipelines.images.ImagesPipeline': 1,
        },
        "IMAGES_STORE": os.path.join(os.getcwd(), 'downloaded_images'),
    }

    def parse(self, response):
        url = response.url
        if url in self.visited_urls:
            return
        self.visited_urls.add(url)
        self.page_count += 1
        print(f"Scrapeando página {self.page_count}: {url}")

        timer = threading.Timer(900, lambda: (_ for _ in ()).throw(TimeoutException()))
        timer.start()
        try:
            paragraphs = response.xpath("//p//text()").getall()
            text = " ".join(paragraphs).lower()
            html_text = response.text.lower()
            relevant = any(k in text for k in KEYWORDS)

            img_urls = []
            if relevant:
                img_srcs = response.xpath("//img/@src").getall()
                img_urls = [response.urljoin(src) for src in img_srcs if src.strip()]

            twitter_username = None
            instagram_username = None
            facebook_username = None

            tw_match = re.search(r'twitter\\.com/(?!share|intent|home)([a-z0-9_]{1,15})', html_text)
            if tw_match:
                twitter_username = tw_match.group(1)
                MySmartSpider.found_twitters.add(twitter_username)

            ig_match = re.search(r'instagram\\.com/([a-z0-9_.]+)', html_text)
            if ig_match:
                instagram_username = ig_match.group(1)
                MySmartSpider.found_instagrams.add(instagram_username)

            fb_match = re.search(r'facebook\\.com/([a-z0-9_.\\-]+)', html_text)
            if fb_match:
                fb_candidate = fb_match.group(1)
                if not any(x in fb_candidate for x in ['sharer', 'share', 'dialog']):
                    facebook_username = fb_candidate
                    MySmartSpider.found_facebooks.add(facebook_username)

            if relevant:
                yield PageItem(
                    url=url,
                    page_number=self.page_count,
                    markdown=text,
                    image_urls=img_urls,
                    twitter=twitter_username,
                    instagram=instagram_username,
                    facebook=facebook_username
                )

            links = response.xpath("//a/@href").getall()
            for link in links:
                abs_link = response.urljoin(link)
                parsed_link = urlparse(abs_link)
                if parsed_link.netloc == self.allowed_domain and abs_link not in self.visited_urls:
                    priority = 10 if any(k in abs_link.lower() for k in KEYWORDS) else 0
                    yield scrapy.Request(abs_link, callback=self.parse, priority=priority)

        except TimeoutException:
            print(f"⏰ Tiempo excedido para la página: {url}")
        except Exception as e:
            print(f"⚠️ Error al procesar {url}: {e}")
        finally:
            timer.cancel()

def main():
    if len(sys.argv) < 2:
        print("❌ Error: Debes proporcionar la URL como argumento.")
        print("Uso: python my_scrapy.py https://www.ejemplo.com")
        sys.exit(1)

    url = sys.argv[1]

    output_file = "scraped_output.jl"
    if os.path.exists(output_file):
        os.remove(output_file)

    print(f"🕷️ Iniciando el scraping desde: {url}")
    MySmartSpider.start_urls = [url]
    parsed = urlparse(url)
    MySmartSpider.allowed_domain = parsed.netloc
    MySmartSpider.visited_urls = set()

    process = CrawlerProcess(get_project_settings())
    process.crawl(MySmartSpider)
    process.start()

    print("\n✅ Scraping completado.")
    print("📄 Textos guardados en scraped_output.jl")
    print("🖼️ Imágenes en ./downloaded_images")

    print("\n🔍 Redes sociales encontradas:")
    print("Twitter:", MySmartSpider.found_twitters)
    print("Instagram:", MySmartSpider.found_instagrams)
    print("Facebook:", MySmartSpider.found_facebooks)

if __name__ == "__main__":
    main()