import base64


def safe_image(value, width=None, **kwargs):
    """st.image()'s 'full width' parameter has changed name across Streamlit
    versions (use_column_width -> use_container_width -> width='stretch'),
    and older/newer versions reject whichever one they don't recognize. This
    tries each in turn so the app works regardless of which version is
    actually installed, instead of hard-coding one and breaking on another."""
    if width is not None:
        try:
            st.image(value, width=width, **kwargs)
            return
        except TypeError:
            pass
    for attempt in (
        lambda: st.image(value, use_column_width=True, **kwargs),
        lambda: st.image(value, use_container_width=True, **kwargs),
        lambda: st.image(value, width="stretch", **kwargs),
        lambda: st.image(value, **kwargs),
    ):
        try:
            attempt()
            return
        except TypeError:
            continue
import os
import textwrap
from pathlib import Path
from io import BytesIO

import requests
import streamlit as st
import plotly.graph_objects as go


# ============================================================
# Configuration
# ============================================================

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")
ASSET_DIR = Path(__file__).parent / "assets"

FOOD_HERO = ASSET_DIR / "food-hero.webp"

LOCAL_FOOD = {
    "Biryani": ASSET_DIR / "food-biryani.webp",
    "North Indian": ASSET_DIR / "food-curry.webp",
    "South Indian": ASSET_DIR / "food-bowl.webp",
    "Chinese": ASSET_DIR / "food-tandoor.webp",
    "Italian": ASSET_DIR / "food-veg.webp",
    "Cafe": ASSET_DIR / "food-bowl.webp",
    "Fast Food": ASSET_DIR / "food-tandoor.webp",
    "Continental": ASSET_DIR / "food-hero.webp",
}

CITIES_FALLBACK = [
    "Hyderabad", "Delhi", "Mumbai", "Bangalore", "Chennai", "Pune",
    "Kolkata", "Jaipur", "Ahmedabad", "Lucknow", "Kochi", "Chandigarh",
    "Indore", "Bhopal", "Coimbatore", "Madurai", "Nagpur", "Nashik",
    "Surat", "Vadodara", "Visakhapatnam", "Agra", "Kanpur", "Patna",
    "Rajkot", "Ludhiana", "Meerut", "Ghaziabad", "Faridabad", "Thane",
    "Guwahati",
]

CUISINES_FALLBACK = [
    "North Indian", "South Indian", "Chinese", "Italian", "Continental",
    "Biryani", "Mughlai", "Fast Food", "Cafe", "Desserts",
]


st.set_page_config(
    page_title="Savora",
    page_icon="🍛",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# Session state
# ============================================================

DEFAULT_STATE = {
    "user": None,
    "page": "Dashboard",
    "selected": None,
    "page_num": 1,
    "search": "",
    "area": "All",
    "cuisines": [],
    "cuisine_filter": [],
    "min_rating": 1.0,
    "min_reviews": 0,
    "sort": "Rating (high to low)",
    "page_size": 12,
}

for key, value in DEFAULT_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# Safe Markdown / HTML renderer
# ============================================================

def render_markdown(content, **kwargs):
    """Render Markdown/HTML after removing Python indentation.

    Streamlit can display an indented HTML block as literal code.
    Dedenting every multiline block prevents that failure.
    """
    if content is None:
        return

    cleaned = textwrap.dedent(str(content)).strip()
    return st.markdown(cleaned, **kwargs)




# ============================================================
# API helpers
# ============================================================

def auth_headers():
    user = st.session_state.get("user")
    if not user:
        return {}
    token = user.get("token")
    return {"Authorization": f"Bearer {token}"} if token else {}


@st.cache_data(ttl=30, show_spinner=False)
def _cached_get(endpoint, params_key, token):
    params = dict(params_key) if params_key else {}
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    response = requests.get(
        API_URL + endpoint,
        params=params,
        headers=headers,
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def get_api(endpoint, params=None, token=None, use_cache=True):
    """
    Successful GET responses are cached.
    Failed requests are NOT cached.
    This prevents the old '0 restaurants' problem after a temporary
    backend restart.
    """
    try:
        # "All" is a UI label, never an API filter. Normalising here also
        # protects restored sessions from sending city=All to the API.
        clean_params = {
            key: value for key, value in (params or {}).items()
            if value is not None and not (
                str(key).lower() in {"area", "city"}
                and isinstance(value, str)
                and value.strip().lower() == "all"
            )
        }
        params_key = tuple(
            sorted(
                (str(k), tuple(v) if isinstance(v, list) else str(v))
                for k, v in clean_params.items()
            )
        )

        with st.spinner("Loading…"):
            if use_cache:
                return _cached_get(endpoint, params_key, token)

            response = requests.get(
                API_URL + endpoint,
                params=clean_params,
                headers={"Authorization": f"Bearer {token}"} if token else {},
                timeout=15,
            )
            response.raise_for_status()
            return response.json()

    except (requests.RequestException, ValueError):
        return None


def post_api(endpoint, **kwargs):
    try:
        return requests.post(
            API_URL + endpoint,
            timeout=25,
            **kwargs,
        )
    except requests.RequestException:
        st.error("We couldn’t complete that request right now. Please try again in a moment.")
        return None


def patch_api(endpoint, **kwargs):
    try:
        return requests.patch(
            API_URL + endpoint,
            timeout=20,
            **kwargs,
        )
    except requests.RequestException:
        st.error("We couldn’t complete that request right now. Please try again in a moment.")
        return None


def delete_api(endpoint, **kwargs):
    try:
        return requests.delete(
            API_URL + endpoint,
            timeout=20,
            **kwargs,
        )
    except requests.RequestException:
        st.error("We couldn’t complete that request right now. Please try again in a moment.")
        return None


def api_error_message(response, fallback="We couldn’t complete that request. Please try again."):
    """Return a user-safe API message without exposing response JSON or URLs."""
    try:
        detail = response.json().get("detail")
        return detail if isinstance(detail, str) and detail.strip() else fallback
    except (ValueError, AttributeError):
        return fallback


# ============================================================
# Styling
# ============================================================

def inject_css():
    render_markdown(
        """
        <style>
        :root{
            --orange:#ff5a1f;
            --orange2:#ff7a3d;
            --ink:#17202a;
            --muted:#7b838d;
            --line:#e9e4df;
            --bg:#f6f5f3;
            --green:#159a66;
            --blue:#2f6fed;
            --cream:#fffaf6;
        }
        body, .stApp, [data-testid="stAppViewContainer"] { color:var(--ink); }
        div[data-testid="stMarkdownContainer"] { color:var(--ink); }
        div[data-testid="stCaptionContainer"], .stCaption { color:#5f6670 !important; }

        header[data-testid="stHeader"],
        #MainMenu,
        footer{
            visibility:hidden;
        }

        .stApp{
            background:var(--bg);
        }

        .block-container{
            max-width:1480px;
            padding:1rem 1.7rem 4rem;
        }

        h1,h2,h3,h4{
            color:var(--ink)!important;
            letter-spacing:-.025em;
        }

        .topbar{
            background:#fff;
            border:1px solid var(--line);
            border-radius:20px;
            padding:12px 16px;
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:18px;
            box-shadow:0 8px 28px rgba(30,20,10,.04);
            margin-bottom:18px;
        }

        .brand{
            display:flex;
            align-items:center;
            gap:10px;
            min-width:220px;
        }

        .logo{
            width:42px;
            height:42px;
            border-radius:50%;
            background:linear-gradient(135deg,#ff7a3d,#ff4d16);
            display:flex;
            align-items:center;
            justify-content:center;
            color:#fff;
            font-size:21px;
            font-weight:900;
        }

        .brand-title{
            font-size:18px;
            font-weight:850;
            line-height:1;
        }

        .brand-sub{
            font-size:10px;
            color:var(--muted);
            margin-top:4px;
        }

        .feature-strip{
            display:flex;
            gap:7px;
            flex-wrap:wrap;
            justify-content:flex-end;
        }

        .feature{
            background:#fff8f4;
            border:1px solid #ffe2d4;
            border-radius:12px;
            padding:7px 10px;
            font-size:9px;
            color:#646a72;
        }

        .feature b{
            color:#f0521d;
            display:block;
            font-size:9px;
            margin-bottom:2px;
        }

        .hero{
            background:
                linear-gradient(135deg,#171a1e,#2b2522 55%,#5b2d1e);
            border-radius:24px;
            padding:30px;
            color:#fff;
            min-height:190px;
            position:relative;
            overflow:hidden;
            box-shadow:0 18px 40px rgba(40,20,10,.10);
        }

        .hero:after{
            content:"";
            position:absolute;
            width:380px;
            height:380px;
            right:-120px;
            top:-210px;
            border-radius:50%;
            background:radial-gradient(
                circle,
                rgba(255,111,48,.72),
                transparent 68%
            );
        }

        .hero h1{
            color:#fff!important;
            font-size:36px;
            margin:5px 0 8px;
        }

        .hero p{
            color:#f5f2ef !important;
            background:transparent !important;
            max-width:720px;
            font-size:14px;
            line-height:1.6;
        }

        .eyebrow{
            font-size:10px;
            letter-spacing:.14em;
            text-transform:uppercase;
            color:#ff9d77;
            font-weight:800;
        }

        .metric{
            background:#fff;
            border:1px solid var(--line);
            border-radius:16px;
            padding:15px 17px;
            min-height:102px;
        }

        .metric-label{
            font-size:10px;
            color:#8a9098;
        }

        .metric-value{
            font-size:25px;
            font-weight:850;
            margin-top:5px;
        }

        .metric-note{
            font-size:10px;
            color:#a1a6ad;
        }

        .section{
            font-size:22px;
            font-weight:850;
            margin:25px 0 13px;
        }

        .muted{
            color:#8b929a;
            font-size:11px;
        }

        .chip{
            display:inline-block;
            background:#fff2eb;
            color:#d94d19;
            border:1px solid #ffd9c8;
            border-radius:999px;
            padding:4px 9px;
            font-size:10px;
            margin:2px;
        }

        .trust{
            display:inline-block;
            background:#e9f9f1;
            color:#15875b;
            border-radius:999px;
            padding:4px 8px;
            font-size:10px;
            font-weight:800;
        }

        .flag{
            display:inline-block;
            background:#fff1e8;
            color:#b54b19;
            border-radius:999px;
            padding:4px 8px;
            font-size:10px;
            font-weight:800;
        }

        .small{
            font-size:10px;
            color:#8a9098;
        }

        .card-title{
            font-size:17px;
            font-weight:850;
            margin-bottom:3px;
        }

        .card-address{
            color:#858c94;
            font-size:10px;
            min-height:30px;
        }

        .rating-line{
            font-size:13px;
            font-weight:800;
            margin:6px 0;
        }

        div[data-testid="stVerticalBlockBorderWrapper"]{
            background:#fff!important;
            border-color:#e8e3de!important;
            border-radius:17px!important;
        }

        .stButton>button, .stLinkButton>a{
            border-radius:10px!important;
            font-weight:750!important;
            transition:transform .15s ease, box-shadow .15s ease, background .15s ease!important;
        }
        .stButton>button:hover, .stLinkButton>a:hover{
            transform:translateY(-1px);
            box-shadow:0 6px 16px rgba(23,32,42,.12)!important;
        }
        .stButton>button:active, .stLinkButton>a:active{ transform:translateY(0); }
        .stButton>button[kind="secondary"]{
            color:#29323a!important;
            border:1px solid #d8d2cc!important;
            background:#fff!important;
        }

        .stButton>button[kind="primary"]{
            background:linear-gradient(
                135deg,
                #ff5a1f,
                #ff7841
            )!important;
            color:#fff!important;
            border:0!important;
        }

        .stTabs [aria-selected="true"]{
            color:#ff5a1f!important;
        }

        .stImage img{
            border-radius:13px;
        }

        .auth-wrap{
            margin-top:0;
        }

        /* The sign-in view is intentionally a self-contained screen on
           desktop: the visual leads and the form remains comfortably visible
           without a page-level scroll.  :has() is supported by the Chromium
           browsers Streamlit targets; smaller screens retain normal scrolling
           so no form controls become inaccessible. */
        @media (min-width: 901px) and (min-height: 700px){
            [data-testid="stAppViewContainer"]:has(.auth-left),
            [data-testid="stAppViewContainer"]:has(.auth-left) section.main,
            [data-testid="stAppViewContainer"]:has(.auth-left) .main .block-container{
                height:100vh;
                overflow:hidden;
            }
            [data-testid="stAppViewContainer"]:has(.auth-left) .main .block-container{
                display:flex;
                align-items:center;
                padding-top:1rem;
                padding-bottom:1rem;
            }
        }

        .auth-left{
            background:
                linear-gradient(
                    90deg,
                    rgba(24,17,14,.92) 0%,
                    rgba(48,27,20,.82) 48%,
                    rgba(48,27,20,.34) 100%
                ),
                url("__FOOD_HERO_URI__");
            background-size:cover;
            background-position:center;
            background-repeat:no-repeat;
            border-radius:24px;
            padding:52px;
            color:white;
            min-height:calc(100vh - 2rem);
            max-height:820px;
            display:flex;
            flex-direction:column;
            justify-content:flex-end;
            overflow:hidden;
            box-shadow:0 18px 50px rgba(30,20,10,.16);
        }

        .auth-left .eyebrow{
            color:#ff9d77;
            margin-bottom:12px;
        }

        /* ========================================================
           REFERENCE-STYLE LEFT SIDEBAR
           Uses Streamlit's real sidebar so widgets stay inside the
           dark panel instead of falling below an HTML wrapper.
           ======================================================== */

        section[data-testid="stSidebar"]{
            background:#17191b !important;
            min-width:250px !important;
            max-width:250px !important;
            width:250px !important;
            border-right:1px solid #2b2d30 !important;
        }

        section[data-testid="stSidebar"] > div{
            background:#17191b !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stSidebarContent"]{
            background:#17191b !important;
            padding:0 14px 20px 14px !important;
        }

        section[data-testid="stSidebar"] .stMarkdown{
            color:#e9edf1 !important;
        }

        .sidebar-brand{
            display:flex;
            align-items:center;
            gap:10px;
            padding:14px 10px 20px 10px;
            margin-bottom:8px;
        }

        .sidebar-logo{
            width:42px;
            height:42px;
            min-width:42px;
            border-radius:50%;
            display:flex;
            align-items:center;
            justify-content:center;
            background:#17191b;
            border:2px solid #ff5a1f;
            color:#fff;
            font-size:21px;
            box-shadow:0 0 0 2px rgba(255,90,31,.12);
        }

        .sidebar-brand-title{
            color:#fff;
            font-size:14px;
            font-weight:800;
            line-height:1.15;
        }

        .sidebar-brand-sub{
            color:#9ca2a9;
            font-size:9px;
            margin-top:3px;
            line-height:1.2;
        }

        .side-nav-title{
            color:#ff8a61 !important;
            font-size:9px !important;
            font-weight:850 !important;
            letter-spacing:.16em !important;
            text-transform:uppercase !important;
            padding:8px 10px 12px !important;
        }

        .side-nav-caption{
            color:#92979e !important;
            font-size:10px !important;
            padding:0 10px 12px !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"]{
            width:100% !important;
            margin:0 !important;
            padding:0 !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button{
            width:100% !important;
            min-height:42px !important;
            height:42px !important;
            margin:3px 0 !important;
            padding:0 13px !important;
            border:0 !important;
            border-radius:7px !important;
            background:transparent !important;
            color:#b9bec5 !important;
            box-shadow:none !important;
            font-size:11px !important;
            font-weight:600 !important;
            text-align:left !important;
            justify-content:flex-start !important;
            white-space:nowrap !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover{
            background:#25282b !important;
            color:#ffffff !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"]{
            background:linear-gradient(135deg,#ff5a1f 0%,#ff7040 100%) !important;
            color:#ffffff !important;
            font-weight:700 !important;
            box-shadow:0 7px 18px rgba(255,90,31,.18) !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"]:hover{
            background:linear-gradient(135deg,#ff5a1f 0%,#ff7040 100%) !important;
            color:#ffffff !important;
        }

        .sidebar-divider{
            height:1px;
            background:#2c2e31;
            margin:12px 8px;
        }

        section[data-testid="stSidebar"] .stCaption{
            color:#8c9299 !important;
        }

        /* Keep the main page clean and give it room beside the sidebar. */
        .dashboard-content{
            min-width:0;
            padding-left:4px;
        }

        .dashboard-content{min-width:0;}
        .dashboard-content .hero{min-height:240px;}

        @media (max-width: 900px){
            .auth-left{min-height:440px;padding:30px;}
            .auth-left h1{font-size:32px;}
        }

        .auth-left h1{
            color:white!important;
            font-size:40px;
            line-height:1.03;
        }

        .auth-left p{
            color:#fff5f0 !important;
            background:transparent !important;
            line-height:1.6;
        }

        .notice{
            background:#eef6ff;
            border:1px solid #d9eaff;
            border-radius:14px;
            padding:13px 15px;
            color:#225a93;
            font-size:12px;
        }
        .stTextInput input, .stTextArea textarea, [data-baseweb="select"] > div {
            color:var(--ink)!important;
            background:#fff!important;
            border-color:#d8d2cc!important;
        }
        .stTextInput input::placeholder, .stTextArea textarea::placeholder { color:#69737d!important; }
        .stAlert { border-radius:12px!important; }
        @media (max-width: 760px){
            .block-container{padding:0.8rem 1rem 2.5rem;}
            .topbar{padding:10px 12px;margin-bottom:14px;}
            .brand-sub{display:none;}
            .hero{padding:24px;min-height:unset;}
            .hero h1,.auth-left h1{font-size:30px!important;}
            .metric{min-height:88px;padding:12px;}
            .metric-value{font-size:21px;}
            section[data-testid="stSidebar"]{min-width:0!important;width:auto!important;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# Image helpers
# ============================================================
def image_to_data_uri(path):
    """Convert a local image into a browser-safe base64 data URI."""
    try:
        if not path.exists():
            return ""

        import mimetypes

        mime_type, _ = mimetypes.guess_type(str(path))
        if not mime_type:
            mime_type = "image/webp"

        data = base64.b64encode(path.read_bytes()).decode("utf-8")
        return f"data:{mime_type};base64,{data}"

    except Exception:
        return ""
def decode_base64_image(value):
    if not value:
        return None
    if isinstance(value, str) and "://" in value:
        return None  # this is a URL, not base64 image data — don't try to decode it

    try:
        if isinstance(value, str):
            if value.startswith("data:image"):
                value = value.split(",", 1)[1]
            return base64.b64decode(value)
    except Exception:
        return None

    return None


def image_value(rest):
    images = rest.get("images") or []

    if images:
        raw = decode_base64_image(images[0])
        if raw:
            return raw

    thumbnail = rest.get("thumbnail")
    if isinstance(thumbnail, str) and thumbnail.startswith(("http://", "https://")):
        # Demo records used externally-hosted text placeholders.  Browsers that
        # block third-party media showed empty cards, so use the shipped artwork
        # for those only. Real Google/Foodish URLs still render as supplied.
        if "placehold.co" not in thumbnail:
            return thumbnail
    raw = decode_base64_image(thumbnail)
    if raw:
        return raw

    image_url = rest.get("image_url")
    if isinstance(image_url, str) and image_url.startswith(("http://", "https://")):
        if "placehold.co" not in image_url:
            return image_url

    for cuisine in rest.get("cuisine") or []:
        path = LOCAL_FOOD.get(cuisine)
        if path and path.exists():
            return str(path)

    if FOOD_HERO.exists():
        return str(FOOD_HERO)

    return None


def show_image(rest, width=None):
    value = image_value(rest)
    if value is not None:
        safe_image(value, width=width)


# ============================================================
# Authentication
# ============================================================

def auth_page():
    """Login/signup screen with the food hero image on the left."""
    auth_hero_uri = image_to_data_uri(FOOD_HERO) if FOOD_HERO.exists() else ""

    if auth_hero_uri:
        render_markdown(
            f"<style>.auth-left{{background-image:linear-gradient(90deg,rgba(24,17,14,.92) 0%,rgba(48,27,20,.82) 48%,rgba(48,27,20,.34) 100%),url('{auth_hero_uri}');}}</style>",
            unsafe_allow_html=True,
        )

    render_markdown('<div class="auth-wrap">', unsafe_allow_html=True)

    left, right = st.columns([1.35, .65], gap="large")

    with left:
        render_markdown(
            '''
            <div class="auth-left">
                <div class="eyebrow">AI-powered food discovery</div>
                <h1>Savora</h1>
            </div>
            ''',
            unsafe_allow_html=True,
        )

    with right:
        with st.container(border=True):
            render_markdown("## Welcome back")
            st.caption("Sign in to continue your food journey.")

            login_tab, signup_tab = st.tabs(["Log in", "Create account"])

            with login_tab:
                email = st.text_input("Email address", key="login_email", placeholder="you@example.com")
                password = st.text_input("Password", type="password", key="login_password")

                if st.button("Log in", type="primary", use_container_width=True, key="login_button"):
                    if not email.strip() or not password:
                        st.warning("Enter your email and password.")
                    else:
                        response = post_api("/auth/login", json={"email": email.strip(), "password": password})
                        if response is not None and response.ok:
                            st.session_state.user = response.json()
                            st.session_state.page = "Dashboard"
                            st.cache_data.clear()
                            st.rerun()
                        elif response is not None:
                            try:
                                message = response.json().get("detail", "Login failed.")
                            except Exception:
                                message = "Login failed."
                            st.error(message)

            with signup_tab:
                name = st.text_input("Full name", key="signup_name")
                email = st.text_input("Email address", key="signup_email")
                password = st.text_input("Password", type="password", key="signup_password")
                st.caption("8+ characters · uppercase · number · special character")

                if st.button("Create account", type="primary", use_container_width=True, key="signup_button"):
                    if not name.strip() or not email.strip() or not password:
                        st.warning("Complete all required fields.")
                    else:
                        response = post_api(
                            "/auth/signup",
                            json={"name": name.strip(), "email": email.strip(), "password": password},
                        )
                        if response is not None and response.ok:
                            st.session_state.user = response.json()
                            st.session_state.page = "Dashboard"
                            st.cache_data.clear()
                            st.rerun()
                        elif response is not None:
                            try:
                                message = response.json().get("detail", "Signup failed.")
                            except Exception:
                                message = "Signup failed."
                            st.error(message)

    render_markdown("</div>", unsafe_allow_html=True)


# ============================================================
# Navigation
# ============================================================

def topbar():
    """Compact application header used after authentication."""
    render_markdown(
        '''
        <div class="topbar">
            <div class="brand">
                <div class="logo">♨</div>
                <div>
                <div class="brand-title">Savora</div>
                </div>
            </div>
        </div>
        ''',
        unsafe_allow_html=True,
    )


def sidebar_nav():
    """Reference-style dark left navigation."""
    user = st.session_state.get("user") or {}
    name = user.get("name", "User")
    page = st.session_state.get("page", "Dashboard")

    render_markdown(
        """
        <div class="sidebar-brand">
            <div class="sidebar-logo">♨</div>
            <div>
                <div class="sidebar-brand-title">Savora</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    render_markdown(
        f'<div class="side-nav-title">Dashboard</div>'
        f'<div class="side-nav-caption">Hello, {name}</div>',
        unsafe_allow_html=True,
    )

    # Labels intentionally match the reference image while retaining
    # every feature already present in the project.
    labels = [
        ("⌂", "Dashboard"),
        ("⌕", "Restaurants"),
        ("♡", "Recommendations"),
        ("▣", "Saved"),
        ("✎", "Reviews"),
        ("▥", "Insights"),
        ("♙", "Profile"),
        ("✉", "Contact"),
        ("↪", "Logout"),
    ]

    for icon, label in labels:
        clicked = st.button(
            f"{icon}  {label}",
            key=f"side_nav_{label}",
            use_container_width=True,
            type="primary" if label == page else "secondary",
        )

        if clicked:
            if label == "Logout":
                st.session_state.user = None
                st.session_state.page = "Dashboard"
                st.session_state.selected = None
                st.cache_data.clear()
                st.rerun()

            else:
                st.session_state.page = label
                st.session_state.selected = None
                st.session_state.page_num = 1
                st.rerun()


# ============================================================
# Shared UI
# ============================================================

def metric_row(analytics):
    total_restaurants = analytics.get(
        "total_restaurants",
        analytics.get("restaurants", 0),
    )

    total_reviews = analytics.get(
        "total_reviews",
        analytics.get("reviews", 0),
    )

    verified = analytics.get("verified_reviews", analytics.get("verified", 0))

    positive = analytics.get("positive_reviews", analytics.get("sentiment", {}).get("positive", analytics.get("positive", 0)))

    c1, c2, c3, c4 = st.columns(4)

    values = [
        ("Restaurants", total_restaurants, "Real places in the database"),
        ("Reviews", total_reviews, "Reviews analyzed"),
        ("Trusted", verified, f"{analytics.get('verified_rate', 0)}% pass trust checks"),
        ("Positive", positive, f"{analytics.get('positive_rate', 0)}% positive sentiment"),
    ]

    for col, (label, value, note) in zip(
        [c1, c2, c3, c4],
        values,
    ):
        with col:
            render_markdown(
                f"""
                <div class="metric">
                    <div class="metric-label">{label}</div>
                    <div class="metric-value">{value}</div>
                    <div class="metric-note">{note}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def restaurant_card(rest, prefix="card"):
    rid = rest.get("_id", rest.get("id", ""))
    name = rest.get("name", "Restaurant")

    rating = rest.get(
        "display_rating",
        rest.get(
            "trust_adjusted_rating",
            rest.get(
                "avg_rating",
                rest.get("google_rating", 0),
            ),
        ),
    )

    google_rating = rest.get("google_rating")
    review_count = rest.get("review_count", 0)
    google_count = rest.get("google_rating_count", 0)

    cuisines = rest.get("cuisine") or []
    area = rest.get("area", "")
    address = rest.get("address", "")

    with st.container(border=True):
        show_image(rest)

        render_markdown(
            f'<div class="card-title">{name}</div>',
            unsafe_allow_html=True,
        )

        render_markdown(
            f'<div class="card-address">{address}</div>',
            unsafe_allow_html=True,
        )

        render_markdown(
            f"""
            <div class="rating-line">
                ⭐ {float(rating):.1f}
                <span class="muted">
                    · {google_count:,} Google ratings
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if google_rating is not None:
            st.caption(
                f"Google {google_rating} · "
                f"{review_count} analyzed reviews"
            )

        chips = []
        if area:
            chips.append(area)

        for cuisine in cuisines[:3]:
            chips.append(cuisine)

        if chips:
            render_markdown(
                " ".join(
                    f'<span class="chip">{x}</span>'
                    for x in chips
                ),
                unsafe_allow_html=True,
            )

        c1, c2 = st.columns(2)

        with c1:
            if st.button(
                "View insights",
                key=f"view_{prefix}_{rid}",
                use_container_width=True,
            ):
                st.session_state.selected = rid
                st.session_state.page = "Restaurants"
                st.rerun()

        with c2:
            maps_url = rest.get("google_maps_uri")
            if maps_url:
                st.link_button(
                    "Directions",
                    maps_url,
                    use_container_width=True,
                )


# ============================================================
# Dashboard
# ============================================================

def dashboard():
    render_markdown(
        """
        <div class="hero">
            <div class="eyebrow">
                India's restaurant intelligence layer
            </div>
            <h1>Find food worth trusting.</h1>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    analytics = get_api("/analytics") or {}
    metric_row(analytics)

    render_markdown(
        '<div class="section">Explore restaurants</div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns([1.1, 1, 1])

    with c1:
        if st.button(
            "🍛 Browse restaurants",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.page = "Restaurants"
            st.rerun()

    with c2:
        if st.button(
            "🧠 My recommendations",
            use_container_width=True,
        ):
            st.session_state.page = "Recommendations"
            st.rerun()

    with c3:
        if st.button(
            "📊 Intelligence dashboard",
            use_container_width=True,
        ):
            st.session_state.page = "Insights"
            st.rerun()

    render_markdown(
        '<div class="section">Popular cities</div>',
        unsafe_allow_html=True,
    )

    cities = analytics.get("top_cities", [])

    if cities:
        cols = st.columns(min(5, len(cities)))

        for i, item in enumerate(cities[:5]):
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                city = item[0]
                count = item[1]
            else:
                city = str(item)
                count = ""

            with cols[i % len(cols)]:
                with st.container(border=True):
                    render_markdown(f"### {city}")
                    st.caption(
                        f"{count} restaurants"
                        if count != ""
                        else "Explore"
                    )

                    if st.button(
                        "Explore",
                        key=f"city_{city}",
                        use_container_width=True,
                    ):
                        st.session_state.area = city
                        st.session_state.page = "Restaurants"
                        st.rerun()
    else:
        st.info("Analytics will appear after restaurant data is available.")


# ============================================================
# Restaurant filters
# ============================================================

def load_areas():
    data = get_api("/areas")

    if isinstance(data, list) and data:
        return ["All"] + data

    return ["All"] + CITIES_FALLBACK


def load_cuisines():
    data = get_api("/cuisines")

    if isinstance(data, list) and data:
        return data

    return CUISINES_FALLBACK


def filters():
    areas = load_areas()
    cuisines = load_cuisines()

    if st.session_state.area not in areas:
        st.session_state.area = "Hyderabad" if "Hyderabad" in areas else areas[0]

    if "cuisine_filter" not in st.session_state:
        st.session_state.cuisine_filter = [
            x for x in st.session_state.cuisines if x in cuisines
        ]
    else:
        st.session_state.cuisine_filter = [
            x for x in st.session_state.cuisine_filter if x in cuisines
        ]

    render_markdown('<div class="section">Find your next place to eat</div>', unsafe_allow_html=True)

    with st.container(border=True):
        c1, c2, c3 = st.columns([1, 1, 2])

        with c1:
            st.selectbox("City", areas, key="area")

        with c2:
            st.multiselect("Cuisine", cuisines, key="cuisine_filter", placeholder="All cuisines")

        with c3:
            st.text_input("Search", key="search", placeholder="Restaurant name...")

        c4, c5, c6, c7 = st.columns(4)

        with c4:
            st.slider("Minimum rating", min_value=1.0, max_value=5.0, step=0.1, key="min_rating")

        with c5:
            st.number_input("Minimum reviews", min_value=0, max_value=100000, step=10, key="min_reviews")

        with c6:
            st.selectbox(
                "Sort",
                ["Rating (high to low)", "Most reviewed", "Name (A-Z)", "Trust score"],
                key="sort",
            )

        with c7:
            st.selectbox("Per page", [8, 12, 20], key="page_size")

    st.session_state.cuisines = list(st.session_state.cuisine_filter)
    return st.session_state.sort, st.session_state.page_size


# ============================================================
# Restaurants
# ============================================================

def restaurants_page():
    sort, size = filters()

    sort_map = {
        "Rating (high to low)": "rating",
        "Most reviewed": "reviews",
        "Name (A-Z)": "name",
        "Trust score": "trust",
    }

    params = {
        "min_rating": float(st.session_state.min_rating),
        "min_reviews": int(st.session_state.min_reviews),
        "sort": sort_map.get(sort, "rating"),
    }

    # IMPORTANT:
    # Backend accepts `area`; it also accepts `city` as a legacy alias.
    if st.session_state.area != "All":
        params["area"] = st.session_state.area

    if st.session_state.cuisines:
        params["cuisine"] = st.session_state.cuisines

    if st.session_state.search.strip():
        params["search"] = st.session_state.search.strip()

    restaurants = get_api(
        "/restaurants",
        params=params,
    )

    if restaurants is None:
        st.error("Restaurants are unavailable right now. Please refresh the page or try again shortly.")
        return

    if not isinstance(restaurants, list):
        st.error("Unexpected response from the restaurant API.")
        return

    render_markdown(
        f"""
        <div class="section">
            {len(restaurants)}
            restaurants
            <span class="muted">· ranked for you</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not restaurants:
        st.info(
            "No restaurants match these filters. "
            "Try lowering the minimum rating, removing the "
            "minimum review count or clearing the search."
        )
        return

    with st.expander("🗺️ Show on map"):
        mappable = [
            r for r in restaurants
            if r.get("lat") is not None
            and r.get("lng") is not None
        ]
        if mappable:
            # Plotly renamed Scattermapbox -> Scattermap (and mapbox -> map in
            # layout) in newer versions, and removed the old name entirely.
            # Pick whichever this installed version actually provides so the
            # page works on both old and new Plotly instead of hard-crashing.
            lats = [r["lat"] for r in mappable]
            lons = [r["lng"] for r in mappable]
            labels = [
                f"{r.get('name', '')} · ⭐ "
                f"{r.get('display_rating', r.get('avg_rating', '—'))}"
                for r in mappable
            ]
            center = dict(lat=mappable[0]["lat"], lon=mappable[0]["lng"])

            trace_cls = getattr(go, "Scattermap", None) or getattr(go, "Scattermapbox", None)
            if trace_cls is None:
                st.caption("Map view isn't available with this Plotly version.")
            else:
                fig = go.Figure(trace_cls(
                    lat=lats,
                    lon=lons,
                    mode="markers",
                    marker=dict(size=11, color="#ff5a1f"),
                    text=labels,
                    hoverinfo="text",
                ))
                map_settings = dict(
                    style="open-street-map",  # no API token required
                    center=center,
                    zoom=10,
                )
                layout_key = "map" if hasattr(go, "Scattermap") else "mapbox"
                fig.update_layout(**{
                    layout_key: map_settings,
                    "height": 420,
                    "margin": dict(l=0, r=0, t=0, b=0),
                })
                st.plotly_chart(fig, use_container_width=True)
                st.caption(
                    f"Showing {len(mappable)} of {len(restaurants)} "
                    "filtered restaurants with location data."
                )
        else:
            st.caption("No location data available for the current filters.")

    page_count = max(
        1,
        (len(restaurants) + size - 1) // size,
    )

    if st.session_state.page_num > page_count:
        st.session_state.page_num = 1

    start = (
        (st.session_state.page_num - 1)
        * size
    )

    page_items = restaurants[
        start:start + size
    ]

    if st.session_state.selected:
        render_detail(st.session_state.selected)
        st.divider()

    cols = st.columns(3)

    for i, restaurant in enumerate(page_items):
        with cols[i % 3]:
            restaurant_card(
                restaurant,
                f"restaurant_{i}",
            )

    if page_count > 1:
        st.write("")

        a, b, c = st.columns([1, 2, 1])

        with a:
            if st.button(
                "← Previous",
                disabled=st.session_state.page_num <= 1,
                use_container_width=True,
                key="previous_page",
            ):
                st.session_state.page_num -= 1
                st.rerun()

        with b:
            render_markdown(
                f"""
                <div style="text-align:center;padding:8px">
                    Page {st.session_state.page_num}
                    of {page_count}
                </div>
                """,
                unsafe_allow_html=True,
            )

        with c:
            if st.button(
                "Next →",
                disabled=st.session_state.page_num >= page_count,
                use_container_width=True,
                key="next_page",
            ):
                st.session_state.page_num += 1
                st.rerun()


# ============================================================
# Restaurant detail
# ============================================================

def render_detail(restaurant_id):
    restaurant = get_api(
        f"/restaurants/{restaurant_id}",
        use_cache=False,
    )

    if not restaurant:
        st.error("Restaurant not found.")
        return

    if st.button(
        "← Back to restaurants",
        key="back_detail",
    ):
        st.session_state.selected = None
        st.rerun()

    render_markdown(
        f"## {restaurant.get('name', 'Restaurant')}"
    )

    st.caption(
        restaurant.get("address", "")
    )

    chips = [restaurant.get("area", "")]
    chips.extend(
        restaurant.get("cuisine") or []
    )

    render_markdown(
        " ".join(
            f'<span class="chip">{x}</span>'
            for x in chips
            if x
        ),
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns([1.15, 1])

    with c1:
        show_image(restaurant)

        rating = restaurant.get(
            "display_rating",
            restaurant.get(
                "trust_adjusted_rating",
                restaurant.get(
                    "avg_rating",
                    restaurant.get(
                        "google_rating",
                        0,
                    ),
                ),
            ),
        )

        render_markdown(
            f"### ⭐ {float(rating):.1f} / 5"
        )

        st.caption(
            f"Google rating: "
            f"{restaurant.get('google_rating', '—')} · "
            f"{restaurant.get('google_rating_count', 0):,} "
            f"Google ratings · "
            f"{restaurant.get('review_count', 0)} "
            f"analyzed reviews"
        )

        if restaurant.get("google_maps_uri"):
            st.link_button(
                "Open in Google Maps",
                restaurant["google_maps_uri"],
                use_container_width=True,
            )

        if st.session_state.user:
            me = get_api("/me", token=st.session_state.user["token"], use_cache=False) or {}
            already_saved = restaurant_id in (me.get("liked_restaurant_ids") or [])

            if already_saved:
                if st.button(
                    "♥ Saved — remove",
                    key=f"unsave_{restaurant_id}",
                    use_container_width=True,
                ):
                    response = delete_api(f"/like/{restaurant_id}", headers=auth_headers())
                    if response is not None and response.ok:
                        st.cache_data.clear()
                        st.rerun()
                    elif response is not None:
                        st.error(api_error_message(response))
            else:
                if st.button(
                    "♡ Save to my places",
                    key=f"save_{restaurant_id}",
                    type="primary",
                    use_container_width=True,
                ):
                    response = post_api(
                        f"/like/{restaurant_id}",
                        headers=auth_headers(),
                    )

                    if response is not None and response.ok:
                        st.success(
                            "Saved to your places."
                        )
                        st.cache_data.clear()
                        st.rerun()
                    elif response is not None:
                        st.error(api_error_message(response))

    with c2:
        aspects = restaurant.get(
            "aspect_scores"
        ) or {}

        if aspects:
            fig = go.Figure(
                go.Scatterpolar(
                    r=list(aspects.values()),
                    theta=[
                        str(x).title()
                        for x in aspects.keys()
                    ],
                    fill="toself",
                )
            )

            fig.update_layout(
                polar=dict(
                    radialaxis=dict(
                        range=[0, 5],
                        visible=True,
                    )
                ),
                height=330,
                margin=dict(
                    l=20,
                    r=20,
                    t=20,
                    b=20,
                ),
                showlegend=False,
            )

            st.plotly_chart(
                fig,
                use_container_width=True,
            )

        popular = get_api(
            f"/restaurants/{restaurant_id}/popular-items"
        ) or {}

        items = popular.get("items") or []

        if items:
            render_markdown(
                "### Popular review mentions"
            )

            render_markdown(
                " ".join(
                    f'<span class="chip">{x}</span>'
                    for x in items
                ),
                unsafe_allow_html=True,
            )

    render_markdown(
        "### Reviews & trust intelligence"
    )

    reviews = get_api(
        f"/restaurants/{restaurant_id}/reviews"
    ) or []

    if reviews:
        for review in reviews[:12]:
            trust_score = float(
                review.get("trust_score", 1)
            )

            if review.get("trust_flag") == "verified":
                badge = (
                    '<span class="trust">✓ Trusted</span>'
                )
            else:
                badge = (
                    '<span class="flag">⚠ Flagged</span>'
                )

            stars = int(
                review.get("star_rating", 0)
            )

            render_markdown(
                f"""
                <div style="color:#17202a !important;">
                     <b style="color:#17202a !important;">{'⭐' * stars}</b>
                    · <b style="color:#17202a !important;">
                         {review.get('user_name', 'Anonymous')}
                    </b>
                    · {badge}
                </div>
                """,
                unsafe_allow_html=True,
        )

            st.markdown(
                    f'<div style="color:#5f6670 !important; font-size:12px;">'
                    f'Trust score: {trust_score * 100:.0f}%'
                    f'</div>',
                    unsafe_allow_html=True,
            )

            st.markdown(
                f'<div style="color:#17202a !important; font-size:15px; line-height:1.6;">'
                f'{review.get("text", "")}'
                f'</div>',
                unsafe_allow_html=True,
         )

            review_images = review.get("images") or []
            if review_images:
                img_cols = st.columns(min(len(review_images), 4))
                for i, img_b64 in enumerate(review_images):
                    with img_cols[i % 4]:
                        try:
                            safe_image(base64.b64decode(img_b64))
                        except Exception:
                            pass

            sentiment = review.get(
                "overall_sentiment"
            )

            if sentiment is not None:
                if sentiment >= 0.15:
                    st.caption(
                        "Overall sentiment: Positive"
                    )
                elif sentiment <= -0.15:
                    st.caption(
                        "Overall sentiment: Negative"
                    )
                else:
                    st.caption(
                        "Overall sentiment: Neutral"
                    )

            if st.session_state.user:
                report_col, _ = st.columns([1, 5])
                with report_col:
                    already_reported = st.session_state.get("user", {}).get("user_id") in review.get("reported_by", [])
                    if already_reported:
                        st.caption("🚩 Reported")
                    elif st.button("🚩 Report", key=f"report_{review['_id']}"):
                        resp = post_api(f"/reviews/{review['_id']}/report", headers=auth_headers())
                        if resp is not None and resp.ok:
                            st.toast("Thanks — this review has been flagged for review.")
                            st.cache_data.clear()
                            st.rerun()

            st.divider()

    else:
        st.info(
            "No reviews yet. Be the first to review "
            "this restaurant."
        )

    if st.session_state.user:
        render_markdown("### Write a review")

        text = st.text_area(
            "Your experience",
            key=f"review_text_{restaurant_id}",
            placeholder=(
                "Mention food, service, price, "
                "ambience or hygiene..."
            ),
        )

        rating = st.slider(
            "Your rating",
            1,
            5,
            5,
            key=f"review_rating_{restaurant_id}",
        )

        uploaded = st.file_uploader(
            "Photos (optional, up to 4)",
            type=["jpg", "jpeg", "png"],
            accept_multiple_files=True,
            key=f"review_files_{restaurant_id}",
        )

        if st.button(
            "Publish review",
            type="primary",
            key=f"publish_{restaurant_id}",
        ):
            if not text.strip():
                st.warning(
                    "Write something before publishing."
                )
            else:
                files = [
                    (
                        "images",
                        (
                            file.name,
                            file.getvalue(),
                            file.type,
                        ),
                    )
                    for file in (uploaded or [])[:4]
                ]

                response = post_api(
                    "/reviews",
                    data={
                        "restaurant_id": restaurant_id,
                        "text": text,
                        "star_rating": rating,
                    },
                    files=files,
                    headers=auth_headers(),
                )

                if response is not None and response.ok:
                    st.success(
                        "Review published, analyzed and "
                        "trust-scored."
                    )
                    st.cache_data.clear()
                    st.rerun()

                elif response is not None:
                    st.error(api_error_message(response))

    similar = get_api(
        f"/restaurants/{restaurant_id}/similar"
    ) or []

    if similar:
        render_markdown(
            "### Similar restaurants"
        )

        cols = st.columns(
            min(4, len(similar))
        )

        for i, item in enumerate(similar):
            with cols[i % len(cols)]:
                restaurant_card(
                    item,
                    f"similar_{i}",
                )


# ============================================================
# Recommendations
# ============================================================

def recommendations_page():
    render_markdown(
        "## Personalized recommendations"
    )

    st.caption(
        "Recommendations are generated from restaurants "
        "you save and the review-language patterns associated "
        "with those places."
    )

    recommendations = get_api(
        "/recommendations/me",
        token=st.session_state.user["token"],
    ) or []

    if not recommendations:
        st.info(
            "Save at least 2–3 restaurants to unlock "
            "personalized recommendations."
        )
        return

    cols = st.columns(4)

    for i, restaurant in enumerate(
        recommendations[:12]
    ):
        with cols[i % 4]:
            restaurant_card(
                restaurant,
                f"recommendation_{i}",
            )


# ============================================================
# Saved restaurants
# ============================================================

def saved_page():
    render_markdown(
        "## Saved restaurants"
    )

    saved = get_api(
        "/favorites",
        token=st.session_state.user["token"],
    ) or []

    if not saved:
        st.info(
            "You haven't saved any restaurants yet. "
            "Open a restaurant and choose Save to my places."
        )
        return

    cols = st.columns(3)

    for i, restaurant in enumerate(saved):
        with cols[i % 3]:
            restaurant_card(
                restaurant,
                f"saved_{i}",
            )
            if st.button("✕ Remove", key=f"unsave_{restaurant['_id']}", use_container_width=True):
                response = delete_api(f"/like/{restaurant['_id']}", headers=auth_headers())
                if response is not None and response.ok:
                    st.cache_data.clear()
                    st.rerun()
                elif response is not None:
                    st.error(api_error_message(response))


# ============================================================
# My reviews
# ============================================================

def reviews_page():
    render_markdown("## My reviews")

    rows = get_api(
        "/me/reviews",
        token=st.session_state.user["token"],
    ) or []

    if not rows:
        st.info(
            "You haven't posted a review yet."
        )
        return

    for row in rows:
        with st.container(border=True):
            stars = int(
                row.get("star_rating", 0)
            )

            render_markdown(
                f"### "
                f"{row.get('restaurant_name', 'Restaurant')}"
                f" · {'⭐' * stars}"
            )

            st.write(
                row.get("text", "")
            )

            trust_score = float(
                row.get("trust_score", 1)
            )

            st.caption(
                f"Trust score: "
                f"{trust_score * 100:.0f}% · "
                f"{row.get('trust_flag', '')}"
                + (" · edited" if row.get("edited_at") else "")
            )

            review_id = row["_id"]
            editing_key = f"editing_{review_id}"

            btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 4])
            with btn_col1:
                if st.button("✏️ Edit", key=f"edit_btn_{review_id}"):
                    st.session_state[editing_key] = not st.session_state.get(editing_key, False)
                    st.rerun()
            with btn_col2:
                if st.button("🗑️ Delete", key=f"delete_btn_{review_id}"):
                    response = delete_api(f"/reviews/{review_id}", headers=auth_headers())
                    if response is not None and response.ok:
                        st.cache_data.clear()
                        st.rerun()
                    elif response is not None:
                        st.error(api_error_message(response))

            if st.session_state.get(editing_key):
                new_text = st.text_area("Edit your review", value=row.get("text", ""), key=f"edit_text_{review_id}")
                new_rating = st.slider("Rating", 1, 5, stars, key=f"edit_rating_{review_id}")
                if st.button("Save changes", key=f"save_edit_{review_id}", type="primary"):
                    response = patch_api(
                        f"/reviews/{review_id}",
                        json={"text": new_text, "star_rating": new_rating},
                        headers=auth_headers(),
                    )
                    if response is not None and response.ok:
                        st.session_state[editing_key] = False
                        st.cache_data.clear()
                        st.rerun()
                    elif response is not None:
                        st.error(api_error_message(response))


# ============================================================
# Analytics / insights
# ============================================================

def insights_page():
    render_markdown(
        "## Restaurant intelligence"
    )

    analytics = get_api(
        "/analytics",
        use_cache=False,
    ) or {}

    metric_row(analytics)

    c1, c2 = st.columns(2)

    with c1:
        cities = analytics.get(
            "top_cities",
            [],
        )

        if cities:
            names = []
            counts = []

            for item in cities:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    names.append(item[0])
                    counts.append(item[1])

            if names:
                fig = go.Figure(
                    go.Bar(
                        x=counts[::-1],
                        y=names[::-1],
                        orientation="h",
                    )
                )

                fig.update_layout(
                    height=420,
                    title="Restaurants by city",
                    margin=dict(
                        l=20,
                        r=20,
                        t=50,
                        b=20,
                    ),
                )

                st.plotly_chart(
                    fig,
                    use_container_width=True,
                )

    with c2:
        cuisines = analytics.get(
            "top_cuisines",
            [],
        )

        if cuisines:
            names = []
            counts = []

            for item in cuisines:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    names.append(item[0])
                    counts.append(item[1])

            if names:
                fig = go.Figure(
                    go.Bar(
                        x=counts,
                        y=names,
                        orientation="h",
                    )
                )

                fig.update_layout(
                    height=420,
                    title="Top cuisines",
                    margin=dict(
                        l=20,
                        r=20,
                        t=50,
                        b=20,
                    ),
                )

                st.plotly_chart(
                    fig,
                    use_container_width=True,
                )

    render_markdown(
        "### What this platform analyzes"
    )

    c1, c2, c3 = st.columns(3)

    with c1:
        with st.container(border=True):
            render_markdown("### 🧠 AI sentiment")
            st.write(
                "Reviews are analyzed for food, service, "
                "price, ambience and hygiene signals."
            )

    with c2:
        with st.container(border=True):
            render_markdown("### 🛡 Trust scoring")
            st.write(
                "Review patterns are evaluated to identify "
                "reviews that appear less credible."
            )

    with c3:
        with st.container(border=True):
            render_markdown("### ❤️ Recommendations")
            st.write(
                "Saved restaurants can be used to build "
                "personalized discovery results."
            )


# ============================================================
# Profile
# ============================================================

def profile_page():
    render_markdown("## Your profile")

    me = get_api(
        "/me",
        token=st.session_state.user["token"],
        use_cache=False,
    ) or {}

    c1, c2 = st.columns(2)

    with c1:
        with st.container(border=True):
            render_markdown(
                f"### {me.get('name', 'User')}"
            )

            st.caption(
                me.get("email", "")
            )

            st.write(
                f"Reviews: "
                f"{me.get('review_count', 0)}"
            )

            st.write(
                "Saved places: "
                f"{len(me.get('liked_restaurant_ids', []))}"
            )

    with c2:
        with st.container(border=True):
            phone = st.text_input(
                "Phone",
                value=me.get("phone", "") or "",
                key="profile_phone",
            )

            location = st.text_input(
                "Location",
                value=me.get("location", "") or "",
                key="profile_location",
            )

            if st.button(
                "Save profile",
                type="primary",
                key="save_profile",
            ):
                response = patch_api(
                    "/me",
                    json={
                        "phone": phone,
                        "location": location,
                    },
                    headers=auth_headers(),
                )

                if response is not None and response.ok:
                    st.success(
                        "Profile updated."
                    )
                    st.cache_data.clear()
                elif response is not None:
                    st.error(api_error_message(response))


# ============================================================
# Contact
# ============================================================

def contact_page():
    render_markdown("## Contact us")

    with st.form("contact_form"):
        user = st.session_state.get("user") or {}

        name = st.text_input(
            "Name",
            value=user.get("name", ""),
        )

        email = st.text_input(
            "Email",
        )

        subject = st.text_input(
            "Subject",
        )

        message = st.text_area(
            "Message",
            height=180,
        )

        submitted = st.form_submit_button(
            "Send message",
            type="primary",
        )

        if submitted:
            if not name.strip() or not email.strip() or not message.strip():
                st.warning(
                    "Please complete the required fields."
                )
            else:
                response = post_api(
                    "/contact",
                    json={
                        "name": name,
                        "email": email,
                        "subject": subject,
                        "message": message,
                    },
                )

                if response is not None and response.ok:
                    st.success(
                        "Message received."
                    )
                elif response is not None:
                    st.error(api_error_message(response))


# ============================================================
# Main application
# ============================================================

inject_css()

if not st.session_state.user:
    auth_page()
    st.stop()

topbar()

# Use Streamlit's actual sidebar. This is deliberate: it gives us one
# persistent dark panel that contains the navigation widgets themselves.
with st.sidebar:
    sidebar_nav()

render_markdown('<div class="dashboard-content">', unsafe_allow_html=True)

page = st.session_state.page

if page == "Dashboard":
    dashboard()
elif page == "Restaurants":
    restaurants_page()
elif page == "Recommendations":
    recommendations_page()
elif page == "Saved":
    saved_page()
elif page == "Reviews":
    reviews_page()
elif page == "Insights":
    insights_page()
elif page == "Profile":
    profile_page()
elif page == "Contact":
    contact_page()
else:
    dashboard()

render_markdown('</div>', unsafe_allow_html=True)