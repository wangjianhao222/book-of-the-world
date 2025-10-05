#!/usr/bin/env python3
"""
Simple Wikibook — Streamlit single-file app

A small, easy-to-run Streamlit app that queries Wikipedia using the public
MediaWiki REST API (no third-party `wikipedia` package required).

Features:
- Search Wikipedia (REST API)
- Show summary, thumbnail, and link to full article
- Optional geocoding using Nominatim (geopy optional) to display a simple map with st.map
- Download article summary as Markdown or plain text

Notes:
- This file avoids attempting automatic pip installs to prevent permission errors.
- To run: create a virtual environment, `pip install streamlit requests`, then run:
    streamlit run wikibook.py

Author: Simplified version generated on user request.
"""

import streamlit as st
import requests
import urllib.parse
import traceback
import sys

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


@st.cache_data(max_entries=128)
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


@st.cache_data(max_entries=256)
def get_summary(title: str, lang: str = 'en') -> dict:
    safe_title = urllib.parse.quote(title.replace(' ', '_'))
    url = WIKI_SUMMARY_URL.format(lang=lang, title=safe_title)
    r = safe_request(url)
    if not r:
        return {}
    data = r.json()
    # normalized fields
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


def article_to_markdown(article: dict) -> str:
    md = f"# {article.get('title','')}

"
    md += f"Source: {article.get('url','')}

"
    md += f"{article.get('summary','')}
"
    return md


def app():
    st.set_page_config(page_title='Simple Wikibook', layout='wide')
    st.title('Simple Wikibook — World Encyclopedia (light)')
    st.write('Search Wikipedia and view short summaries. No heavy dependencies.')

    with st.sidebar:
        st.header('Options')
        lang = st.selectbox('Language', ['en', 'zh', 'es', 'fr', 'de', 'ja'], index=0)
        enable_map = st.checkbox('Enable geocoding/map (geopy required)', value=False)

    query = st.text_input('Search or enter exact article title', value='Earth')
    col1, col2 = st.columns([3,1])

    with col2:
        if st.button('Search'):
            pass
        st.write('Tips: try place names, countries, historic events.')

    with col1:
        if not query:
            st.info('Enter a search term and press Search')
            return

        # First try exact title summary
        article = get_summary(query, lang=lang)
        if not article or not article.get('summary'):
            # fallback to search
            hits = search_wikipedia(query, lang=lang, limit=10)
            if not hits:
                st.warning('No results found.')
                return
            choice = st.selectbox('Choose an article', hits)
            article = get_summary(choice, lang=lang)

        st.subheader(article.get('title',''))
        st.markdown(f"[Open on Wikipedia]({article.get('url','')})")
        st.write(article.get('summary',''))

        thumb = article.get('thumbnail')
        if thumb:
            st.image(thumb, use_column_width=False)

        # map
        if enable_map:
            coords = geocode_place(article.get('title',''))
            if coords:
                try:
                    import pandas as pd
                    df = pd.DataFrame([{'lat': coords[0], 'lon': coords[1]}])
                    st.map(df.rename(columns={'lat':'lat','lon':'lon'}))
                except Exception:
                    st.info('Pandas is required for map fallback. Install pandas to enable map.')
            else:
                st.info('No coordinates found.')

        # downloads
        md = article_to_markdown(article)
        st.download_button('Download summary as Markdown', data=md, file_name=f"{article.get('title','article')}.md", mime='text/markdown')
        st.download_button('Download summary as plain text', data=article.get('summary',''), file_name=f"{article.get('title','article')}.txt", mime='text/plain')


if __name__ == '__main__':
    try:
        app()
    except Exception as e:
        print('Fatal error:', e)
        print(traceback.format_exc())
