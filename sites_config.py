# ==========================================
# MULTI-SITE CONFIGURATION
# ==========================================
# Centralized configuration for 788 and K67 sites
# All site-specific settings in one place for easy management

SITES = {
    "788": {
        "name": "788",
        "display_name": "🎰 Site 788",
        "api_domain": "https://api.n-t-v-w.com",
        "website_url": "https://778gobb.shop",
        "website_key": "0x4AAAAAAB0oRY23FyZnllMo",  # Turnstile key
        "tenant_id": "8446112",
        "lobby_url": "https://778gobb.shop",
        "launch_url": "https://778gobb.shop/launch",
        "x_client_version": "v234",
    },
    "K67": {
        "name": "K67",
        "display_name": "🎲 Site K67",
        "api_domain": "https://api.n-t-v-w.com",
        "website_url": "https://k677ee.live",
        "website_key": "0x4AAAAAAB0oRY23FyZnllMo",  # Turnstile key (same as 788)
        "tenant_id": "8665392",
        "lobby_url": "https://k677ee.live",
        "launch_url": "https://k677ee.live/launch",
        "x_client_version": "v234",
    }
}

def get_site_config(site_name: str = "788"):
    """Get configuration for a specific site"""
    site_name = site_name.upper() if site_name.upper() in SITES else "788"
    return SITES[site_name]

def get_site_display_name(site_name: str = "788"):
    """Get display name for UI"""
    config = get_site_config(site_name)
    return config.get("display_name", site_name)

def get_all_sites():
    """Get list of all available sites"""
    return list(SITES.keys())
