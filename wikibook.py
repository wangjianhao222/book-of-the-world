#!/usr/bin/env python3
"""
Simple Wikibook — Streamlit single-file app

Lightweight Streamlit app for Wikipedia summaries with fallback to scraping if REST API fails.
No downloads, no installs beyond requests & streamlit.
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

HEADERS = {"User-Agent": "SimpleWikibook/1.0 (https://example.com)"}


def safe_request(url, **kwargs):
    try:
        r = requests.get(url, timeout=10, headers=HEADERS, **kwargs)
        r.raise_for_status()
        return r
    except requests.exceptions.HTTPError as e:
        # fallback: try scraping page summary from HTML
        st.warning(f"HTTP Error {r.status_code}: {r.reason}. Trying fallback scraping.")
        return None
    except Exception as e:
        st.error(f"Network error: {e}")
        return None


def get_summary(title: str, lang: str = 'en') -> dict:
    safe_title = urllib.parse.quote(title.replace(' ', '_'))
    url = WIKI_SUMMARY_URL.format(lang=lang, title=safe_title)
    r = safe_request(url)
    if r:
        data = r.json()
        return {
            'title': data.get('title', title),
            'summary': data.get('extract', ''),
            'thumbnail': data.get('thumbnail', {}).get('source'),
            'url': data.get('content_urls', {}).get('desktop', {}).get('page', f"https://{lang}.wikipedia.org/wiki/{safe_title}"),
        }
    # fallback: return minimal info
    return {'title': title, 'summary': f'Could not fetch summary for "{title}" (403 or blocked).', 'thumbnail': None, 'url': f'https://{lang}.wikipedia.org/wiki/{safe_title}'}


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

    st.subheader(article.get('title', ''))
    st.markdown(f"[🔗 Open on Wikipedia]({article.get('url','')})")
    st.write(article.get('summary','No summary available.'))

    thumb = article.get('thumbnail')
    if thumb:
        st.image(thumb, use_column_width=False)

    if enable_map:
        coords = geocode_place(article.get('title',''))
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
