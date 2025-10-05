#!/usr/bin/env python3
"""
Simple Wikibook — Streamlit single-file app

A small, easy-to-run Streamlit app that queries Wikipedia using the public
MediaWiki REST API (no third-party `wikipedia` package required).

Features:
- Search Wikipedia (REST API)
- Show summary, thumbnail, and link to full article
- Optional geocoding using Nominatim (geopy optional) to display a simple map with st.map
- View only, no downloads or installs.

To run: `pip install streamlit requests` then `streamlit run wikibook.py`
"""

import streamlit as st
import requests
import urllib.parse
import traceback

# Optional geocoding
try:
    from geopy.geocoders import Nominatim
    HAVE_GEOPY = True
except Exception:
    HAVE_GEOPY = False

WIKI_SUMMARY_URL = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKI_SEARCH_API = "https://{lang}.wikipedia.org/w/api.php"


def safe_request(url, **kwargs):
    try:
        r = requests.get(url, timeout=10, **kwargs)
        r.raise_for_status()
        return r
    except Exception as e:
        st.error(f"Network error: {e}")
        return None


def search_wikipedia(query: str, lang: str = 'en', limit: int = 10):
    params = {
        'action': 'query',
        'list': 'search',
        'srsearch': query,
        'format': 'json',
        'srlimit': limit,
    }
    url = WIKI_SEARCH_API.format(lang=lang)
    r = safe_request(url, params=params)
    if not r:
        return []
    data = r.json()
    hits = data.get('query', {}).get('search', [])
    return [h.get('title') for h in hits]


def get_summary(title: str, lang: str = 'en') -> dict:
    safe_title = urllib.parse.quote(title.replace(' ', '_'))
    url = WIKI_SUMMARY_URL.format(lang=lang, title=safe_title)
    r = safe_request(url)
    if not r:
        return {}
    data = r.json()
    return {
        'title': data.get('title', title),
        'summary': data.get('extract', ''),
        'thumbnail': data.get('thumbnail', {}).get('source'),
        'url': data.get('content_urls', {}).get('desktop', {}).get('page', f"https://{lang}.wikipedia.org/wiki/{safe_title}"),
    }


def geocode_place(place: str):
    if not HAVE_GEOPY:
        return None
    try:
        geolocator = Nominatim(user_agent='simple_wikibook')
        loc = geolocator.geocode(place, timeout=10)
        if loc:
            return (loc.latitude, loc.longitude)
    except Exception:
        return None
    return None


def app():
    st.set_page_config(page_title='Simple Wikibook', layout='wide')
    st.title('🌍 Simple Wikibook — Lightweight World Encyclopedia')
    st.write('Search Wikipedia and instantly view short summaries. No downloads or external dependencies.')

    with st.sidebar:
        st.header('Options')
        lang = st.selectbox('Language', ['en', 'zh', 'es', 'fr', 'de', 'ja'], index=0)
        enable_map = st.checkbox('Enable geocoding/map (requires geopy)', value=False)

    query = st.text_input('Search or enter exact article title', value='Earth')

    if not query:
        st.info('Enter a search term above to begin.')
        return

    article = get_summary(query, lang=lang)
    if not article or not article.get('summary'):
        hits = search_wikipedia(query, lang=lang)
        if not hits:
            st.warning('No results found.')
            return
        choice = st.selectbox('Select an article', hits)
        article = get_summary(choice, lang=lang)

    st.subheader(article.get('title', ''))
    st.markdown(f"[🔗 Open on Wikipedia]({article.get('url', '')})")
    st.write(article.get('summary', 'No summary available.'))

    thumb = article.get('thumbnail')
    if thumb:
        st.image(thumb, use_column_width=False)

    if enable_map:
        coords = geocode_place(article.get('title', ''))
        if coords:
            import pandas as pd
            df = pd.DataFrame([{'lat': coords[0], 'lon': coords[1]}])
            st.map(df)
        else:
            st.info('No coordinates found for this article.')


if __name__ == '__main__':
    try:
        app()
    except Exception as e:
        st.error(f"Fatal error: {e}")
        st.code(traceback.format_exc())
