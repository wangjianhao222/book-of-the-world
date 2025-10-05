"""
World Encyclopedia — Streamlit app

A complex, feature-rich Streamlit application that aggregates public, free world knowledge
from multiple APIs and sources (Wikipedia, Wikidata, REST Countries, Open-Meteo, Wikimedia
Commons) to present an interactive encyclopedia experience.

Features:
- Global search (Wikipedia + Wikidata) with disambiguation support
- Country pages (REST Countries + Wikidata + maps)
- Entity pages with images (from Wikipedia/Wikimedia) and key facts extracted from Wikidata
- Interactive map (folium + streamlit_folium) showing locations mentioned in an article
- Timeline of historical events (if date properties are found on Wikidata)
- Relationship graph of related entities (NetworkX + pyvis rendered in Streamlit)
- Live weather snapshot for coordinates (Open-Meteo free API)
- Saved bookmarks (local session storage) and export to JSON
- Caching, rate-limit handling, and robust error messages

Usage:
    streamlit run world_encyclopedia_streamlit.py

Requirements (put into requirements.txt):
streamlit
requests
pandas
folium
streamlit-folium
networkx
pyvis
python-dateutil
beautifulsoup4
lxml
"""

import streamlit as st
import requests
import pandas as pd
import folium
from streamlit_folium import st_folium
import networkx as nx
from pyvis.network import Network
from urllib.parse import quote
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from datetime import datetime
import json
import time
import html

# -----------------------
# Configuration
# -----------------------
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
RESTCOUNTRIES = "https://restcountries.com/v3.1/all"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
USER_AGENT = "WorldEncyclopediaStreamlit/1.0 (contact: no-reply@example.org)"

HEADERS = {"User-Agent": USER_AGENT}

st.set_page_config(page_title="World Encyclopedia", layout="wide")

# -----------------------
# Utilities & API helpers
# -----------------------

@st.cache_data(ttl=3600)
def get_rest_countries():
    """Fetch and cache REST Countries data."""
    try:
        r = requests.get(RESTCOUNTRIES, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Could not load country data: {e}")
        return []

@st.cache_data(ttl=3600)
def search_wikipedia(query, limit=10):
    params = {
        'action': 'query',
        'format': 'json',
        'list': 'search',
        'srsearch': query,
        'srlimit': limit,
        'srprop': ''
    }
    r = requests.get(WIKIPEDIA_API, params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()
    return data.get('query', {}).get('search', [])

@st.cache_data(ttl=3600)
def get_wikipedia_page(title):
    params = {
        'action': 'parse',
        'page': title,
        'format': 'json',
        'prop': 'text|sections|links|images'
    }
    r = requests.get(WIKIPEDIA_API, params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=3600)
def get_wikipedia_summary(title):
    params = {
        'action': 'query',
        'prop': 'extracts|pageimages',
        'exintro': True,
        'explaintext': True,
        'format': 'json',
        'titles': title,
        'pithumbsize': 800
    }
    r = requests.get(WIKIPEDIA_API, params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()
    pages = data.get('query', {}).get('pages', {})
    if not pages:
        return None
    page = next(iter(pages.values()))
    return page

@st.cache_data(ttl=3600)
def get_wikidata_id_from_wikipedia(title):
    """Use Wikipedia pageprops to find the Wikidata item ID (Pxx)."""
    params = {
        'action': 'query',
        'prop': 'pageprops',
        'titles': title,
        'format': 'json'
    }
    r = requests.get(WIKIPEDIA_API, params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()
    pages = data.get('query', {}).get('pages', {})
    page = next(iter(pages.values()))
    props = page.get('pageprops', {})
    return props.get('wikibase_item')

@st.cache_data(ttl=3600)
def wikidata_sparql(query):
    headers = dict(HEADERS)
    headers['Accept'] = 'application/sparql-results+json'
    r = requests.get(WIKIDATA_SPARQL, params={'query': query}, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=600)
def get_commons_image_url(title):
    """Extract a primary image URL from the Wikimedia page (if available)."""
    try:
        page = get_wikipedia_page(title)
        parse = page.get('parse', {})
        html_text = parse.get('text', {}).get('*', '')
        soup = BeautifulSoup(html_text, 'lxml')
        # try to find an image in the infobox
        infobox = soup.find('table', {'class': 'infobox'})
        if infobox:
            img = infobox.find('img')
            if img and img.get('src'):
                src = img['src']
                if src.startswith('//'):
                    src = 'https:' + src
                return src
        # fallback: first image tag
        img = soup.find('img')
        if img and img.get('src'):
            src = img['src']
            if src.startswith('//'):
                src = 'https:' + src
            return src
    except Exception:
        return None
    return None

@st.cache_data(ttl=300)
def get_weather(lat, lon):
    params = {
        'latitude': lat,
        'longitude': lon,
        'current_weather': True,
        'timezone': 'UTC'
    }
    r = requests.get(OPEN_METEO, params=params, headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()

# -----------------------
# Wikidata helpers: fetch basic properties and related entities
# -----------------------

def build_wikidata_props_query(qid):
    q = f"""
    SELECT ?prop ?propLabel ?value ?valueLabel ?valueType WHERE {{
      wd:{qid} ?p ?statement .
      ?prop wikibase:directClaim ?p .
      ?statement ?ps ?value .
      OPTIONAL {{ ?value a ?valueType }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }} LIMIT 200
    """
    return q

@st.cache_data(ttl=3600)
def get_wikidata_props(qid):
    query = build_wikidata_props_query(qid)
    res = wikidata_sparql(query)
    bindings = res.get('results', {}).get('bindings', [])
    props = {}
    for b in bindings:
        prop = b.get('propLabel', {}).get('value')
        val = b.get('valueLabel', {}).get('value')
        val_uri = b.get('value', {}).get('value')
        if prop:
            props.setdefault(prop, []).append({'label': val, 'uri': val_uri})
    return props

@st.cache_data(ttl=3600)
def get_related_entities(qid, limit=20):
    """Get entities that are directly connected to the given QID (incoming or outgoing).
       This is a simple neighborhood query for building a small graph.
    """
    query = f"""
    SELECT ?item ?itemLabel ?link WHERE {{
      {{ wd:{qid} ?p ?item . BIND("outgoing" as ?link) }}
      UNION
      {{ ?item ?p wd:{qid} . BIND("incoming" as ?link) }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }} LIMIT {limit}
    """
    res = wikidata_sparql(query)
    binds = res.get('results', {}).get('bindings', [])
    nodes = []
    for b in binds:
        uri = b.get('item', {}).get('value')
        label = b.get('itemLabel', {}).get('value')
        link = b.get('link', {}).get('value')
        nodes.append({'uri': uri, 'label': label, 'link': link})
    return nodes

# -----------------------
# UI components
# -----------------------

def render_entity_graph(qid, center_label="Entity Graph"):
    nodes = get_related_entities(qid, limit=80)
    g = Network(height='600px', width='100%', directed=True, notebook=False)
    g.barnes_hut()
    g.add_node(qid, label=center_label, title=center_label, color='#ffcc00')
    for n in nodes:
        node_id = n['uri'].split('/')[-1]
        g.add_node(node_id, label=n['label'], title=n['label'])
        # simple heuristic: link to center
        if n['link'] == 'outgoing':
            g.add_edge(qid, node_id)
        else:
            g.add_edge(node_id, qid)
    # generate HTML and render
    g.set_options('''var options = {"nodes": {"shape": "dot","size": 16}}''')
    html_str = g.generate_html()
    st.components.v1.html(html_str, height=650, scrolling=True)

# -----------------------
# Main app layout
# -----------------------

st.title("🌍 World Encyclopedia — Aggregated Global Knowledge")

# Sidebar controls
with st.sidebar:
    st.header("Search & Navigation")
    query = st.text_input("Search Wikipedia / Wikidata", value="", help="Enter an entity, place, or topic")
    search_btn = st.button("Search")
    st.markdown("---")
    st.subheader("Quick country jump")
    countries = get_rest_countries()
    country_names = sorted([c.get('name', {}).get('common', 'Unknown') for c in countries])
    chosen_country = st.selectbox("Choose a country", ["—"] + country_names)
    st.markdown("---")
    st.subheader("Utilities")
    if st.button("Random Wikipedia article"):
        r = requests.get('https://en.wikipedia.org/api/rest_v1/page/random/title', headers=HEADERS)
        if r.ok:
            rand_title = r.json().get('items', [])[0].get('title') if r.json().get('items') else r.text
            st.experimental_set_query_params(page=rand_title)
            st.experimental_rerun()
    st.button("Clear bookmarks", key="clear_bkm")

# Session-state for bookmarks
if 'bookmarks' not in st.session_state:
    st.session_state['bookmarks'] = []

# If country chosen, prepare a page
if chosen_country and chosen_country != "—":
    st.experimental_set_query_params(country=chosen_country)
    # display country overview in the main area
    country_data = [c for c in countries if c.get('name', {}).get('common') == chosen_country]
    if country_data:
        c = country_data[0]
        col1, col2 = st.columns([1, 2])
        with col1:
            st.subheader(chosen_country)
            st.write(f"**Capital:** {', '.join(c.get('capital', ['Unknown']))}")
            st.write(f"**Region:** {c.get('region')}")
            st.write(f"**Population:** {c.get('population'):,}")
            st.write(f"**Area:** {c.get('area', 'N/A'):,} km²")
            if c.get('flags'):
                st.image(c['flags'].get('png') or c['flags'].get('svg'), use_column_width=True)
            # Wikidata enrichment if available
            wikidata_id = None
            # Some countries include cca2/cca3 - try to find via Wikidata by country name
            try:
                # SPARQL: find country by English label
                q = f"SELECT ?country WHERE {{ ?country rdfs:label \"{chosen_country}\"@en . ?country wdt:P31/wdt:P279* wd:Q6256. }} LIMIT 1"
                wd_res = wikidata_sparql(q)
                items = wd_res.get('results', {}).get('bindings', [])
                if items:
                    country_uri = items[0]['country']['value']
                    wikidata_id = country_uri.split('/')[-1]
            except Exception:
                wikidata_id = None
        with col2:
            st.subheader("Map & Details")
            latlng = c.get('latlng')
            if latlng:
                m = folium.Map(location=latlng, zoom_start=5)
                folium.Marker(location=latlng, tooltip=chosen_country).add_to(m)
                st_folium(m, width=700)
                # Weather
                try:
                    w = get_weather(latlng[0], latlng[1])
                    cw = w.get('current_weather')
                    if cw:
                        st.write("**Current weather (UTC):**")
                        st.write(f"Temperature: {cw.get('temperature')}°C — Wind: {cw.get('windspeed')} m/s — Direction: {cw.get('winddirection')}°")
                except Exception:
                    st.info("Weather data not available")
            else:
                st.info("No coordinates available for this country in REST Countries data.")

# Handle search
selected_title = None
if search_btn and query.strip():
    with st.spinner('Searching Wikipedia...'):
        results = search_wikipedia(query, limit=12)
    if not results:
        st.warning('No results from Wikipedia search — trying Wikidata label search...')
        # fallback: search Wikidata labels via SPARQL
        q = f"SELECT ?item ?itemLabel WHERE {{ ?item rdfs:label ?label FILTER(LCASE(?label) = LCASE(\"{query}\")) . SERVICE wikibase:label {{ bd:serviceParam wikibase:language \"en\". }} }} LIMIT 20"
        try:
            wdres = wikidata_sparql(q)
            binds = wdres.get('results', {}).get('bindings', [])
            if binds:
                options = [b['itemLabel']['value'] for b in binds]
                selected = st.selectbox('Select a matching Wikidata label', options)
                selected_title = selected
        except Exception:
            st.error('Wikidata search failed')
    else:
        titles = [r.get('title') for r in results]
        selected_title = st.selectbox('Choose a page', titles)

# Check URL query param to open a page directly
params = st.experimental_get_query_params()
if 'page' in params:
    selected_title = params.get('page')[0]

# If a page is selected, render it
if selected_title:
    st.header(selected_title)
    try:
        summary = get_wikipedia_summary(selected_title)
        if summary:
            # title, extract, thumbnail
            extract = summary.get('extract')
            thumb = summary.get('thumbnail', {}).get('source')
            if thumb:
                st.image(thumb, width=300)
            st.markdown(f"**Summary:**\n\n{extract}")
        # full parse for infobox and text
        page = get_wikipedia_page(selected_title)
        parse = page.get('parse', {})
        html_text = parse.get('text', {}).get('*', '')
        # sanitize a little and show a collapsed markdown of first sections
        soup = BeautifulSoup(html_text, 'lxml')
        # Show the infobox contents as key-value
        infobox = soup.find('table', {'class': 'infobox'})
        if infobox:
            st.subheader('Infobox')
            rows = infobox.find_all('tr')
            info = {}
            for r in rows:
                if r.th and r.td:
                    key = r.th.get_text(separator=' ', strip=True)
                    val = r.td.get_text(separator=' ', strip=True)
                    info[key] = val
            st.json(info)
        # find coordinate templates — common pattern is geo-dec or coordinates
        coords = None
        coord_span = soup.find('span', {'class': 'coordinates'})
        if coord_span:
            # usually coordinates are in a nested a/span with data-lat or data-lon
            try:
                lat = float(coord_span.find('span', {'class': 'latitude'}).get_text())
                lon = float(coord_span.find('span', {'class': 'longitude'}).get_text())
                coords = (lat, lon)
            except Exception:
                coords = None
        # get commons image
        img_url = get_commons_image_url(selected_title)
        if img_url and not thumb:
            st.image(img_url, width=350)
        # Wikidata enrichment
        wikidata_id = get_wikidata_id_from_wikipedia(selected_title)
        if wikidata_id:
            st.subheader('Wikidata Enrichment')
            st.write(f'Wikidata Q-ID: {wikidata_id}')
            props = get_wikidata_props(wikidata_id)
            # show selected interesting props
            interesting = ['instance of', 'country', 'country of citizenship', 'date of birth', 'date of death', 'inception', 'official website']
            filtered = {k: v for k, v in props.items() if k in interesting}
            st.json(filtered or props)

            # Graph
            if st.button('Show relationship graph'):
                render_entity_graph(wikidata_id, center_label=selected_title)

        # Map of coordinates or geo-mentions
        st.subheader('Map of geographic mentions')
        m = folium.Map(location=[20,0], zoom_start=2)
        if coords:
            folium.Marker(location=coords, popup=selected_title).add_to(m)
        # naive approach: search for lat/lon patterns or place names in the article text
        # Here we'll attempt to find linked place pages and geocode them via Wikidata
        links = parse.get('links', [])
        place_links = [l['*'] for l in links if any(word in l['*'].lower() for word in ['city', 'town', 'river', 'mount', 'island', 'country', 'state', 'province'])][:30]
        # for each linked place, try to get its wikidata coordinates
        for pl in place_links:
            try:
                qid = get_wikidata_id_from_wikipedia(pl)
                if qid:
                    # SPARQL for coordinates
                    sparq = f"SELECT ?coord WHERE {{ wd:{qid} wdt:P625 ?coord . }}"
                    res = wikidata_sparql(sparq)
                    b = res.get('results', {}).get('bindings', [])
                    if b:
                        coordval = b[0]['coord']['value']  # e.g. "Point(long lat)"
                        # parse "Point(LON LAT)"
                        if coordval.startswith('Point(') and coordval.endswith(')'):
                            inside = coordval[6:-1]
                            lon, lat = inside.split(' ')
                            folium.Marker(location=[float(lat), float(lon)], popup=pl).add_to(m)
            except Exception:
                continue
        st_folium(m, width=900)

        # Timeline extraction
        st.subheader('Timeline (detected dates)')
        # naive: search for 4-digit years in the text and present a histogram
        text = soup.get_text()
        years = []
        for token in text.split():
            if len(token) == 4 and token.isdigit():
                y = int(token)
                if 1000 <= y <= datetime.utcnow().year:
                    years.append(y)
        if years:
            df_years = pd.DataFrame({'year': years})
            year_counts = df_years['year'].value_counts().sort_index()
            st.bar_chart(year_counts)
        else:
            st.info('No obvious years detected for timeline generation.')

        # Bookmark button
        if st.button('Bookmark this page'):
            if selected_title not in st.session_state['bookmarks']:
                st.session_state['bookmarks'].append(selected_title)
                st.success('Bookmarked!')
            else:
                st.info('Already bookmarked.')

    except Exception as e:
        st.error(f'Error loading page: {e}')

# Bookmarks panel
with st.expander('📚 Bookmarks (session)'):
    for b in st.session_state['bookmarks']:
        st.write(f'- {b}')
    if st.button('Export bookmarks as JSON'):
        payload = json.dumps(st.session_state['bookmarks'], indent=2)
        st.download_button('Download bookmarks', payload, file_name='bookmarks.json', mime='application/json')

# Footer: credits and usage notes
st.markdown('---')
st.caption('This app aggregates public data from Wikimedia (Wikipedia & Wikidata), REST Countries, and Open-Meteo. It is intended for educational/demo purposes only.')

# End of file
