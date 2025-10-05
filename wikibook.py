#!/usr/bin/env python3
"""
Wikibook — Streamlit app (single-file)

This updated version improves dependency handling in restricted environments where `pip install` into the venv may be denied.
Features added/changed:
- Smarter auto-install strategy: try normal import -> pip --user -> pip --target=./.vendored (local vendor dir) with sys.path insertion.
- Graceful degraded-mode fallbacks: if `wikipedia` is missing, use the MediaWiki REST API via `requests` for search and summary. If `folium` is missing, fall back to Streamlit's `st.map` if `pandas` is available.
- Clear, actionable permission-error messages and UI guidance for operators (how to fix permissions or provide a requirements.txt).
- All text and UI are English. Extra small usability features retained (download, caching, language select).

Notes:
- Installing into `./.vendored` avoids permission errors but may not be allowed on some hosted platforms. This approach is best for development or where you can commit the vendor folder.
- If network/pip are completely blocked, the app will run in a limited mode using Wikipedia's REST API (only summary) and no mapping.

Author: Generated for the user (English). Updated to handle permission denied pip errors.
"""

import sys
import os
import subprocess
import importlib
import traceback
from typing import List, Optional, Tuple

# -----------------------
# Configuration
# -----------------------
REQUIRED_PKGS = [
    "streamlit",
    "wikipedia",
    "folium",
    "pandas",
    "requests",
    "geopy",
]
VENDOR_DIR = os.path.join(os.path.dirname(__file__), ".vendored") if '__file__' in globals() else os.path.join(os.getcwd(), ".vendored")

# runtime flags
_missing_packages = []  # packages that ultimately failed to import
_vendor_used = False

# -----------------------
# Helper: attempt installs with multiple strategies
# -----------------------

def _pip_install(args: List[str]) -> Tuple[bool, str]:
    """Run pip as a subprocess. Return (success, stderr+stdout)."""
    try:
        cmd = [sys.executable, "-m", "pip"] + args
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        out = (proc.stdout or "") + "
" + (proc.stderr or "")
        return (proc.returncode == 0, out)
    except Exception as e:
        return (False, str(e))


def install_package_strategic(pkg: str) -> Tuple[bool, str]:
    """Try to install pkg using several strategies to avoid permission errors.

    1. pip install pkg --user
    2. pip install pkg --target=VENDOR_DIR (creates local vendor dir and injects to sys.path)
    Returns (success, message)
    """
    global _vendor_used

    # first try --user (may still fail if pip can't write user-site)
    ok, out = _pip_install(["install", "--upgrade", pkg, "--user"])
    if ok:
        return True, "installed with --user"

    # If permission denied or other OSError, try local vendor
    try:
        os.makedirs(VENDOR_DIR, exist_ok=True)
        ok2, out2 = _pip_install(["install", "--upgrade", pkg, "--target", VENDOR_DIR])
        if ok2:
            # insert vendor dir to sys.path at runtime so imports succeed
            if VENDOR_DIR not in sys.path:
                sys.path.insert(0, VENDOR_DIR)
            _vendor_used = True
            return True, f"installed to local vendor dir: {VENDOR_DIR}"
        else:
            return False, out2
    except Exception as e:
        return False, str(e)


def ensure_packages(pkgs: List[str]) -> List[str]:
    """Ensure list of packages are importable. Return a list of packages that failed to import.
    Attempts once: import; if ImportError then try install strategically; then re-import.
    """
    failed = []
    for pkg in pkgs:
        import_name = pkg
        # Some packages have different import names; special-case them
        if pkg == 'pandas':
            import_name = 'pandas'
        try:
            importlib.import_module(import_name)
            continue
        except Exception:
            # attempt to install
            success, msg = install_package_strategic(pkg)
            if success:
                try:
                    importlib.invalidate_caches()
                    importlib.import_module(import_name)
                    continue
                except Exception:
                    failed.append(pkg)
            else:
                # installation failed
                failed.append(pkg)
    return failed

# Attempt to ensure dependencies (best effort)
try:
    _failed_pkgs = ensure_packages(REQUIRED_PKGS)
except Exception:
    _failed_pkgs = REQUIRED_PKGS[:]  # worst-case: mark all missing

# -----------------------
# Import optional modules (we'll use fallbacks if they are missing)
# -----------------------
try:
    import streamlit as st
except Exception:
    raise RuntimeError("streamlit is required to run this app. Please install it in your environment.")

# Try to import other optional libraries
have_wikipedia = True
have_folium = True
have_pandas = True
have_requests = True
have_geopy = True

try:
    import wikipedia
except Exception:
    have_wikipedia = False

try:
    import folium
except Exception:
    have_folium = False

try:
    import pandas as pd
except Exception:
    have_pandas = False

try:
    import requests
except Exception:
    have_requests = False

try:
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderUnavailable
except Exception:
    have_geopy = False

# -----------------------
# Utility helpers
# -----------------------

def detect_environment() -> str:
    py = sys.version.replace('
', ' ')
    try:
        cwd = os.getcwd()
    except Exception:
        cwd = '<unknown>'
    venv = sys.prefix
    parts = [f"Python: {py}", f"CWD: {cwd}", f"Prefix: {venv}", f"Vendor dir used: { _vendor_used }"]
    if _failed_pkgs:
        parts.append("Failed installs: " + ", ".join(_failed_pkgs))
    return "
".join(parts)


def format_exception(e: Exception) -> str:
    tb = traceback.format_exc()
    return f"{e.__class__.__name__}: {e}

Traceback:
{tb}"

# -----------------------
# Fallback Wikipedia access using the MediaWiki REST API (if `wikipedia` package missing)
# -----------------------

WIKI_REST_ENDPOINT = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKI_SEARCH_ENDPOINT = "https://{lang}.wikipedia.org/w/api.php"


def wiki_summary_rest(title: str, lang: str = 'en') -> dict:
    """Fetch summary and basic metadata using Wikipedia REST API via requests.
    Returns dict with keys similar to wiki_summary above: title, summary, content (may be short), images, url, toc (empty), coords (None)
    """
    safe_title = requests.utils.requote_uri(title.replace(' ', '_'))
    url = WIKI_REST_ENDPOINT.format(lang=lang, title=safe_title)
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    summary = data.get('extract', '')
    page_url = data.get('content_urls', {}).get('desktop', {}).get('page', f'https://{lang}.wikipedia.org/wiki/{safe_title}')
    images = []
    thumb = data.get('thumbnail', {})
    if thumb.get('source'):
        images.append(thumb['source'])
    return {
        'title': data.get('title', title),
        'summary': summary,
        'content': summary,
        'images': images,
        'url': page_url,
        'toc': [],
        'coords': None,
    }


def wiki_search_rest(query: str, lang: str = 'en', results: int = 10) -> List[str]:
    params = {
        'action': 'query',
        'list': 'search',
        'srsearch': query,
        'format': 'json',
        'srlimit': results,
    }
    r = requests.get(WIKI_SEARCH_ENDPOINT.format(lang=lang), params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    hits = data.get('query', {}).get('search', [])
    return [h.get('title') for h in hits]

# -----------------------
# Wikipedia helpers (use package if available, else REST fallback)
# -----------------------

if have_wikipedia:
    @st.cache_data(max_entries=128)
    def wiki_summary(title: str, lang: str = 'en') -> dict:
        wikipedia.set_lang(lang)
        page = wikipedia.page(title, auto_suggest=True, redirect=True)
        summary = wikipedia.summary(title, sentences=3)
        content = page.content
        images = page.images[:8]
        url = page.url
        toc = []
        lines = content.splitlines()
        for line in lines:
            if line.startswith('==') and line.endswith('=='):
                heading = line.strip('=').strip()
                toc.append(heading)
                if len(toc) >= 20:
                    break
        coords = None
        try:
            if hasattr(page, 'coordinates') and page.coordinates:
                coords = page.coordinates
                if isinstance(coords, dict):
                    coords = (coords.get('lat'), coords.get('lon'))
        except Exception:
            coords = None
        return {'title': page.title, 'summary': summary, 'content': content, 'images': images, 'url': url, 'toc': toc, 'coords': coords}

    @st.cache_data(max_entries=64)
    def wiki_search(query: str, lang: str = 'en', results: int = 10) -> List[str]:
        wikipedia.set_lang(lang)
        try:
            return wikipedia.search(query, results)
        except Exception:
            return []

else:
    # REST fallbacks
    @st.cache_data(max_entries=128)
    def wiki_summary(title: str, lang: str = 'en') -> dict:
        if not have_requests:
            raise RuntimeError('Neither `wikipedia` nor `requests` is available. Install one to use Wikibook.')
        return wiki_summary_rest(title, lang=lang)

    @st.cache_data(max_entries=64)
    def wiki_search(query: str, lang: str = 'en', results: int = 10) -> List[str]:
        if not have_requests:
            return []
        try:
            return wiki_search_rest(query, lang=lang, results=results)
        except Exception:
            return []

# -----------------------
# Geocoding & map helpers
# -----------------------

@st.cache_data(max_entries=64)
def geocode_title(title: str) -> Optional[tuple]:
    """Try to geocode a page title using Nominatim (OpenStreetMap)."""
    if not have_geopy:
        return None
    try:
        geolocator = Nominatim(user_agent='wikibook_geocoder')
        location = geolocator.geocode(title, timeout=10)
        if location:
            return (location.latitude, location.longitude)
    except Exception:
        return None
    return None


def folium_map_html(lat: float, lon: float, title: str = 'Location') -> Optional[str]:
    if not have_folium:
        return None
    m = folium.Map(location=[lat, lon], zoom_start=5)
    folium.Marker([lat, lon], popup=title).add_to(m)
    return m._repr_html_()

# -----------------------
# Export helpers
# -----------------------

def article_to_markdown(article: dict) -> str:
    md = f"# {article['title']}

"
    md += f"Source: {article['url']}

"
    md += f"## Summary

{article['summary']}

"
    if article.get('toc'):
        md += "## Table of Contents

"
        for h in article['toc']:
            md += f"- {h}
"
        md += "
"
    md += "## Full content

"
    md += article.get('content', '')
    return md

# -----------------------
# Streamlit app
# -----------------------

def app():
    st.set_page_config(page_title='Wikibook — World Encyclopedia', layout='wide')
    st.title('Wikibook — World Encyclopedia')
    st.caption('Search, explore, and export Wikipedia content. Degraded-mode friendly when installs are restricted.')

    # Sidebar diagnostics
    with st.sidebar.expander('Environment & Diagnostics', expanded=True):
        st.write(detect_environment())
        if _failed_pkgs:
            st.error('The app attempted to auto-install packages but the following failed: ' + ', '.join(_failed_pkgs))
            st.markdown('**How to fix (choose one):**')
            st.markdown('- If you control the environment, run: `pip install -r requirements.txt` or install the missing packages as an operator.')
            st.markdown('- If you can edit the project, add a `requirements.txt` listing `streamlit
wikipedia
folium
pandas
requests
geopy` and redeploy.')
            st.markdown(f'- As a workaround, this app attempted to install packages into a local vendor directory: `{VENDOR_DIR}`. Check permissions on that path.')

        st.markdown('---')
        lang = st.selectbox('Wikipedia language', options=['en', 'zh', 'es', 'fr', 'de', 'ru', 'ja'], index=0)
        enable_map = st.checkbox('Enable map and geocoding', value=True)
        prefer_summary_sentences = st.slider('Summary length (sentences)', 1, 10, 3)

    col1, col2 = st.columns([3, 1])

    with col2:
        st.header('Quick Actions')
        q_input = st.text_input('Search or enter article title', value='Earth')
        if st.button('Search'):
            query = q_input.strip()
        elif st.button('Random article'):
            try:
                if have_wikipedia:
                    query = wikipedia.random(1)
                else:
                    query = 'Earth'
            except Exception:
                query = 'Earth'
        else:
            query = q_input.strip()

        st.markdown('---')
        show_images = st.checkbox('Show images (top results)', value=True)
        show_full = st.checkbox('Show full article content', value=False)
        download_md = st.checkbox('Enable download as Markdown', value=True)

        st.markdown('---')
        st.write('Package availability:')
        st.write(f'wikipedia: {have_wikipedia}, folium: {have_folium}, pandas: {have_pandas}, requests: {have_requests}, geopy: {have_geopy}')

    with col1:
        st.header('Results')
        if not query:
            st.info('Type a search term or article title and press Search.')
            return

        try:
            search_results = wiki_search(query, lang=lang, results=10)
            if not search_results:
                st.warning('No results found. Try a different query or language.')
                return

            choice = st.selectbox('Choose an article', options=search_results, index=0)
            with st.spinner(f'Fetching article `{choice}`...'):
                article = wiki_summary(choice, lang=lang)

            st.subheader(article['title'])
            st.write(f"Source: {article['url']}")
            st.markdown('**Summary**')
            st.write(article['summary'])

            # images
            if show_images and article.get('images'):
                imgs = article['images'][:6]
                if imgs:
                    img_cols = st.columns(min(len(imgs), 3))
                    for i, img in enumerate(imgs):
                        try:
                            with img_cols[i % len(img_cols)]:
                                st.image(img, caption=f'Image {i+1}', use_column_width=True)
                        except Exception:
                            pass

            # toc
            if article.get('toc'):
                st.markdown('**Table of Contents**')
                st.write(article['toc'])

            # mapping
            coords = article.get('coords')
            if enable_map:
                if not coords:
                    coords = geocode_title(article.get('title', ''))

                if coords and coords[0] and coords[1]:
                    st.markdown('**Location**')
                    m_html = folium_map_html(coords[0], coords[1], title=article.get('title', '')) if have_folium else None
                    if m_html:
                        st.components.v1.html(m_html, height=450)
                    else:
                        # fallback to st.map if pandas is available
                        if have_pandas:
                            try:
                                df = pd.DataFrame([{'lat': coords[0], 'lon': coords[1]}])
                                st.map(df)
                            except Exception:
                                st.info('Map not available in this environment.')
                        else:
                            st.info('Map not available (folium and pandas missing).')
                else:
                    st.info('No coordinates found for this article. Map not shown.')

            if show_full:
                st.markdown('---')
                st.markdown('### Full content')
                st.text_area('Article content (scrollable)', value=article.get('content', ''), height=400)

            # related pages
            try:
                related = wiki_search(article.get('title', ''), lang=lang, results=8)
                if related:
                    st.markdown('**Related pages**')
                    st.write(related)
            except Exception:
                pass

            if download_md:
                md = article_to_markdown(article)
                st.download_button('Download article as Markdown', data=md, file_name=f"{article['title']}.md", mime='text/markdown')
                st.download_button('Download article as plain text', data=article.get('content',''), file_name=f"{article['title']}.txt", mime='text/plain')

        except Exception as e:
            st.error('An error occurred while fetching or rendering the article. See details below.')
            st.code(format_exception(e))


if __name__ == '__main__':
    try:
        app()
    except Exception as e:
        # For environments where Streamlit launch fails, print details
        print('Fatal error while launching the Streamlit app:
', format_exception(e))
