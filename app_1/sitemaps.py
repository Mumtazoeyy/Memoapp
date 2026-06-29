from django.contrib.sitemaps import Sitemap
from django.urls import reverse

class HomeSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.5

    def items(self):
        # Hanya mengembalikan list dengan nama route 'home'
        return ['home']

    def location(self, item):
        return reverse(item)