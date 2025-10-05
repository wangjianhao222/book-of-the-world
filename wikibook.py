#!/usr/bin/env python3
"""
Wikibook — Streamlit app (single-file)
Features:
- Auto-install missing Python packages at startup (best-effort)
- Environment detection and informative error messages
- Wikipedia-based world-encyclopedia search (supports language selection)
- Article summary, full content, images, table of contents, related pages
- Geolocation: extract coordinates from Wikipedia or geocode title; show interactive Folium map
- Export: download article as Markdown and as plain text
- Caching for repeated queries
- Friendly UI with sidebar controls and robust exception handling

Notes:
- Auto-install is intended for development/demo environments. On production services, prefer using requirements.txt.
- If running in a locked environment (no network or no pip), auto-install will fail gracefully and the app will show instructions.

Author: Generated for the user (English)
"""

import sys
import subprocess
import importlib
import pkgutil
import traceback
from typing import List, Optional

# -----------------------
# Auto-install helper
# -----------------------
REQUIRED_PKGS = [
    "streamlit",
    "wikipedia",
    "folium",
    "pandas",
    "requests",
    "geopy",
]


def install_package(pkg: str) -> None:
    """Install a package using pip. Raises CalledProcessError on failure."""
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])


def ensure_packages(pkgs: List[str]) -> List[str]:
    """Ensure list of packages are importable. Return a list of packages that failed to import.
    This will attempt to pip install missing packages once.
    """
    failed = []
    for pkg in pkgs:
        # Some packages have different import names (e.g. wikipedia -> wikipedia)
        import_name = pkg
        try:
            importlib.import_module(import_name)
        except Exception:
            try:
                install_package(pkg)
                importlib.invalidate_caches()
                importlib.import_module(import_name)
            except Exception:
                failed.append(pkg)
    return failed


# Attempt to ensure dependencies (best effort)
_failed_pkgs = ensure_packages(REQUIRED_PKGS)

# After attempting installs, import modules (use descriptive fallback messages later)
try:
    import streamlit as st
    import wikipedia
    import folium
    import pandas as pd
    import requests
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderUnavailable
except Exception:
    # We'll continue — the app will show helpful instructions in the UI instead of crashing
    pass

# -----------------------
# Utility functions
# -----------------------

def detect_environment() -> str:
    """Return a short diagnostic string about Python and runtime environment."""
    py = sys.version.replace("\n", " ")
    try:
        import os
        cwd = os.getcwd()
    except Exception:
        cwd = "<unknown>"
    venv = sys.prefix
    return f"Python: {py}\nCWD: {cwd}\nPrefix: {venv}"


def format_exception(e: Exception) -> str:
    tb = traceback.format_exc()
    return f"{e.__class__.__name__}: {e}\n\nTraceback:\n{tb}"


# -----------------------
# Wikipedia helpers
# -----------------------

@st.cache_data(max_entries=128)
def wiki_summary(title: str, lang: str = "en") -> dict:
    wikipedia.set_lang(lang)
    page = wikipedia.page(title, auto_suggest=True, redirect=True)

    # page content pieces
    summary = wikipedia.summary(title, sentences=3)
    content = page.content
    images = page.images[:8]
    url = page.url
    # Wikipedia library doesn't reliably expose TOC; we'll try to get sections by splitting
    toc = []
    # naive TOC: first 10 headings in the pagecontent
    lines = content.splitlines()
    for line in lines:
        if line.startswith("==") and line.endswith("=="):
            heading = line.strip("=").strip()
            toc.append(heading)
            if len(toc) >= 20:
                break

    # Try to get coordinates if present (wikipedia library has coordinates attr for some pages)
    coords = None
    try:
        if hasattr(page, "coordinates") and page.coordinates:
            coords = page.coordinates  # usually (lat, lon)
            if isinstance(coords, dict):
                # some variants return dict
                coords = (coords.get("lat"), coords.get("lon"))
    except Exception:
        coords = None

    return {
        "title": page.title,
        "summary": summary,
        "content": content,
        "images": images,
        "url": url,
        "toc": toc,
        "coords": coords,
    }


@st.cache_data(max_entries=64)
def wiki_search(query: str, lang: str = "en", results: int = 10) -> List[str]:
    wikipedia.set_lang(lang)
    try:
        return wikipedia.search(query, results)
    except Exception:
        return []


@st.cache_data(max_entries=64)
def geocode_title(title: str) -> Optional[tuple]:
    """Fallback: try to geocode a page title using Nominatim (OpenStreetMap)."""
    try:
        geolocator = Nominatim(user_agent="wikibook_geocoder")
        location = geolocator.geocode(title, timeout=10)
        if location:
            return (location.latitude, location.longitude)
    except GeocoderUnavailable:
        return None
    except Exception:
        return None


# -----------------------
# Map rendering helper
# -----------------------

def folium_map_html(lat: float, lon: float, title: str = "Location") -> str:
    m = folium.Map(location=[lat, lon], zoom_start=5)
    folium.Marker([lat, lon], popup=title).add_to(m)
    # Use _repr_html_ for embedding in Streamlit
    return m._repr_html_()


# -----------------------
# Export helpers
# -----------------------

def article_to_markdown(article: dict) -> str:
    md = f"# {article['title']}\n\n"
    md += f"Source: {article['url']}\n\n"
    md += f"## Summary\n\n{article['summary']}\n\n"

    if article.get("toc"):
        md += "## Table of Contents\n\n"
        for h in article["toc"]:
            md += f"- {h}\n"
        md += "\n"

    md += "## Full content\n\n"
    md += article["content"]

    return md


# -----------------------
# Streamlit UI
# -----------------------

def app():
    st.set_page_config(page_title="Wikibook — World Encyclopedia", layout="wide")

    # Header
    st.title("Wikibook — World Encyclopedia")
    st.caption("A Streamlit single-file demo: search, explore and export Wikipedia content with maps.")

    # Environment and dependency diagnostics in sidebar
    with st.sidebar.expander("Environment & Diagnostics", expanded=False):
        st.write(detect_environment())
        if _failed_pkgs:
            st.warning("The app tried to auto-install some packages but the following failed: \n" + ", ".join(_failed_pkgs))
            st.markdown(
                "If you see missing-package errors, please install them manually (e.g. `pip install folium wikipedia streamlit`)."
            )

        st.markdown("---")
        st.write("**App options**")
        lang = st.selectbox("Wikipedia language", options=["en", "zh", "es", "fr", "de", "ru", "ja"], index=0)
        enable_map = st.checkbox("Enable map and geocoding (Folium)", value=True)
        prefer_summary_sentences = st.slider("Summary length (sentences)", 1, 10, 3)

    # Main controls
    col1, col2 = st.columns([3, 1])

    with col2:
        st.header("Quick Actions")
        q_input = st.text_input("Search or enter article title", value="Earth")
        if st.button("Search"):
            query = q_input.strip()
        elif st.button("Random article"):
            try:
                query = wikipedia.random(1)
            except Exception:
                query = "Earth"
        else:
            query = q_input.strip()

        st.markdown("---")
        show_images = st.checkbox("Show images (top results)", value=True)
        show_full = st.checkbox("Show full article content", value=False)
        download_md = st.checkbox("Enable download as Markdown", value=True)

    with col1:
        st.header("Results")

        if not query:
            st.info("Type a search term or article title in the left panel and press Search.")
            return

        # perform search and show candidate matches
        try:
            search_results = wiki_search(query, lang=lang, results=10)
            if not search_results:
                st.warning("No results found. Try a different query or language.")
                return

            # Pick best candidate (first) but allow user to choose
            choice = st.selectbox("Choose an article", options=search_results, index=0)

            with st.spinner(f"Fetching article `{choice}`..."):
                article = wiki_summary(choice, lang=lang)

            st.subheader(article["title"]) 
            st.write(f"Source: [Open on Wikipedia]({article['url']})")

            # summary
            st.markdown("**Summary**")
            st.write(article["summary"])

            # images
            if show_images and article.get("images"):
                imgs = article["images"][:6]
                img_cols = st.columns(min(len(imgs), 3))
                for i, img in enumerate(imgs):
                    try:
                        with img_cols[i % len(img_cols)]:
                            st.image(img, caption=f"Image {i+1}", use_column_width=True)
                    except Exception:
                        # ignore image display problems
                        pass

            # Table of contents
            if article.get("toc"):
                st.markdown("**Table of Contents**")
                st.write(article["toc"])

            # map
            coords = article.get("coords")
            if enable_map:
                if not coords:
                    coords = geocode_title(article["title"])  # fallback geocoding

                if coords and coords[0] and coords[1]:
                    st.markdown("**Location**")
                    m_html = folium_map_html(coords[0], coords[1], title=article["title"])
                    # embed HTML
                    st.components.v1.html(m_html, height=450)
                else:
                    st.info("No coordinates found for this article. Map not shown.")

            # full content viewing
            if show_full:
                st.markdown("---")
                st.markdown("### Full content")
                st.text_area("Article content (scrollable)", value=article["content"], height=400)

            # related pages
            try:
                related = wikipedia.search(article["title"], results=8)
                if related:
                    st.markdown("**Related pages**")
                    st.write(related)
            except Exception:
                pass

            # downloads
            if download_md:
                md = article_to_markdown(article)
                st.download_button("Download article as Markdown", data=md, file_name=f"{article['title']}.md", mime="text/markdown")
                st.download_button("Download article as plain text", data=article["content"], file_name=f"{article['title']}.txt", mime="text/plain")

        except Exception as e:
            st.error("An error occurred while fetching or rendering the article. See details below.")
            st.code(format_exception(e))


if __name__ == "__main__":
    try:
        app()
    except Exception as e:
        print("Fatal error while launching the Streamlit app:\n", format_exception(e))
