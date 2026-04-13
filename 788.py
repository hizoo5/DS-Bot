import json
import random
import string
import base64
import time
import uuid
import requests
import ddddocr
import capsolver
from datetime import datetime
from urllib.parse import urlparse, parse_qs
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from Crypto.Cipher import DES
from Crypto.Util.Padding import pad
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import threading
import urllib3
import sqlite3
from queue import Queue
import hashlib

# Suppress SSL warnings globally
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# OPTIMIZATION: CONCURRENT USER MANAGEMENT
# ==========================================
class SessionPool:
    """Manages a pool of reusable sessions for multiple users"""
    def __init__(self, max_sessions=20):
        self.pool = Queue(maxsize=max_sessions)
        self.lock = threading.Lock()
        for _ in range(max_sessions):
            session = self._create_session()
            self.pool.put(session)
    
    def _create_session(self):
        session = requests.Session()
        session.verify = False
        retry_strategy = Retry(total=2, backoff_factor=0.1, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session
    
    def get(self, timeout=5):
        try:
            return self.pool.get(timeout=timeout)
        except:
            return self._create_session()
    
    def put(self, session):
        try:
            self.pool.put_nowait(session)
        except:
            pass

# Token cache with TTL (5 minutes)
token_cache = {}
token_cache_lock = threading.Lock()

def get_cached_token(cache_key):
    with token_cache_lock:
        if cache_key in token_cache:
            token, timestamp = token_cache[cache_key]
            if time.time() - timestamp < 300:  # 5 min TTL
                return token
            else:
                del token_cache[cache_key]
    return None

def cache_token(cache_key, token):
    with token_cache_lock:
        token_cache[cache_key] = (token, time.time())

# Executor for parallel tasks
executor = ThreadPoolExecutor(max_workers=20)
session_pool = SessionPool(max_sessions=20)

# ==========================================
# WORD POOLS (Fallback if file missing)
# ==========================================
try:
    from word_pool import verbs, nouns, intl_names
except ImportError:
    verbs =["running", "travel", "jumping", "coding", "hacking", "flying"]
    nouns =["rocket", "tiger", "dragon", "laptop", "server", "matrix"]
    intl_names =["maria", "joseph", "samir", "liam", "emma", "noah"]

# ==========================================
# 1. CAPTCHA SOLVERS
# ==========================================
# Configure capsolver for Turnstile
capsolver.api_key = "CAP-0DC960CE6197F1A690593E6B22149C15F72B75B4F80B26212B7A0C4EDE76E7B6"

class TurnstileSolver:
    """Solves Cloudflare Turnstile by loading page and capturing token"""
    
    def __init__(self, websitekey: str = "0x4AAAAAAB0oRY23FyZnllMo", proxy_url: str = None):
        self.websitekey = websitekey
        self.websiteurl = "https://778gobb.shop"
        self.proxy_url = proxy_url
    
    def solve(self, website_url: str = None) -> str:
        """Get Turnstile token - try direct page load first (fastest), then capsolver"""
        if website_url:
            self.websiteurl = website_url
        
        try:
            # METHOD 1 (FAST): Try extracting cf_clearance directly from page load with proxy
            print("[*] Getting Turnstile token...")
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            
            if self.proxy_url:
                session.proxies = {"http": self.proxy_url, "https": self.proxy_url}
            
            try:
                res = session.get(self.websiteurl, timeout=15, allow_redirects=True)
                cf_clearance = session.cookies.get('cf_clearance')
                
                if cf_clearance:
                    print(f"[✓] Got cf_clearance")
                    return cf_clearance
            except Exception as e:
                print(f"[DEBUG] Direct page load failed: {str(e)[:50]}")
            
            # METHOD 2 (FALLBACK): Try capsolver
            print("[*] Using capsolver...")
            
            for capsolver_retry in range(2):
                try:
                    task_response = requests.post(
                        "https://api.capsolver.com/createTask",
                        headers={"Content-Type": "application/json"},
                        json={
                            "clientKey": "CAP-0DC960CE6197F1A690593E6B22149C15F72B75B4F80B26212B7A0C4EDE76E7B6",
                            "task": {
                                "type": "AntiTurnstileTaskProxyLess",
                                "websiteURL": self.websiteurl,
                                "websiteKey": self.websitekey
                            }
                        },
                        timeout=10
                    )
                    
                    task_data = task_response.json()
                    
                    if task_data.get('errorId') != 0:
                        if capsolver_retry < 1:
                            time.sleep(0.5)
                            continue
                        return None
                    
                    if task_data.get('errorId') == 0:
                        task_id = task_data.get('taskId')
                        
                        # Poll for result (max 10 attempts)
                        for attempt in range(10):
                            time.sleep(1)
                            
                            try:
                                result_response = requests.post(
                                    "https://api.capsolver.com/getTaskResult",
                                    headers={"Content-Type": "application/json"},
                                    json={
                                        "clientKey": "CAP-0DC960CE6197F1A690593E6B22149C15F72B75B4F80B26212B7A0C4EDE76E7B6",
                                        "taskId": task_id
                                    },
                                    timeout=10
                                )
                                
                                result_data = result_response.json()
                                status = result_data.get('status')
                                
                                if status == 'ready':
                                    solution = result_data.get('solution', {})
                                    token = solution.get('token', '')
                                    
                                    if token:
                                        print(f"[✓] Turnstile solved")
                                        return token
                                
                                if status == 'failed':
                                    break
                               
                            except Exception as e:
                                pass
                        
                except Exception as e:
                    if capsolver_retry < 1:
                        time.sleep(0.5)
                        continue
                    return None
            
            print("[!] Turnstile failed, using fallback token")
            return None
                
        except Exception as e:
            print(f"[ERROR] Turnstile solving failed: {str(e)[:50]}")
            return None

class LocalCaptchaSolver:
    def __init__(self):
        self.ocr = ddddocr.DdddOcr(show_ad=False)

    def solve_from_base64(self, b64_string: str) -> str:
        if not b64_string: return ""
        if "base64," in b64_string:
            b64_string = b64_string.split("base64,")[1]
        image_bytes = base64.b64decode(b64_string)
        return self.ocr.classification(image_bytes).strip()


class RegistrationBot:
    def __init__(self, base_url: str, proxy_url: str, cached_x_token: str = None):
        self.base_url = base_url.rstrip('/')
        # Use session pool instead of creating new session
        self.session = session_pool.get(timeout=2) or requests.Session()
        self.session.verify = False
        
        self.turnstile_solver = TurnstileSolver(proxy_url=proxy_url)
        self.session.proxies = {"http": proxy_url, "https": proxy_url}
        self.proxy_url = proxy_url
        
        # 1. OPSEC: DYNAMIC DEVICE FINGERPRINTING
        self._set_device_profile()
            
        # Generate device and trace IDs
        self.device_id = str(uuid.uuid4())
        self.trace_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        
        # Auth tokens
        self.auth_tag = None
        self.token_data = None
        self.x_tag = None
        self.userid = None
        self.bearer_token = None
        self.x_token = cached_x_token
        
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Content-Type": "application/json",
            "Tenantid": TENANT_ID,
            "X-Trace-Id": self.trace_id,
            "X-Device-Type": "DesktopOS",
            "X-Device-Id": self.device_id,
            "Client-Language": "en-PH",
            "X-Client-Version": X_CLIENT_VERSION,
            "X-Request-Source": "web_client",
            "Origin": LOBBY_URL,
            "Referer": f"{LOBBY_URL}/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site"
        })

    def _send_preflight_options(self, endpoint: str) -> bool:
        """Send OPTIONS preflight request (CORS) with retry logic"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                url = f"{self.base_url}{endpoint}"
                
                # Determine the correct Access-Control-Request-Headers based on endpoint
                if "auth.registe" in endpoint:
                    request_headers = "channelid,client-language,content-type,tenantid,x-client-version,x-device-id,x-device-type,x-fingerprint-id,x-fingerprint-request-id,x-request-source,x-token,x-trace-id"
                elif "auth.login" in endpoint:
                    request_headers = "channelid,client-language,content-type,tenantid,x-client-version,x-device-id,x-device-type,x-request-source,x-token,x-trace-id"
                elif "pay.create" in endpoint:
                    request_headers = "authorization,channelid,client-language,content-type,tenantid,userid,x-auth-tag,x-client-version,x-device-id,x-device-type,x-tag,x-token-data,x-trace-id"
                else:
                    request_headers = "*"
                
                headers = {
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": request_headers,
                    "Origin": LOBBY_URL,
                    "Referer": f"{LOBBY_URL}/",
                    "User-Agent": self.user_agent,
                    "Accept": "*/*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "cross-site"
                }
                res = self.session.options(url, headers=headers, timeout=15)
                if res.status_code in [200, 204]:
                    print(f"[DEBUG] Preflight {endpoint}: {res.status_code}")
                    return True
                else:
                    print(f"[DEBUG] Preflight {endpoint}: {res.status_code} (retry {attempt + 1}/{max_retries})")
            except Exception as e:
                error_str = str(e)[:80]
                print(f"[DEBUG] Preflight failed for {endpoint} (retry {attempt + 1}/{max_retries}): {error_str}")
                if attempt < max_retries - 1:
                    time.sleep(0.5 * (attempt + 1))  # Backoff sleep
                    continue
        print(f"[WARNING] Preflight {endpoint} failed after {max_retries} retries, continuing anyway...")
        return True  # Continue anyway (preflight is often not critical)
    
    def get_x_token_from_lobby(self, skip_if_cached=False, force_fresh=False):
        """GET lobby page, solve Turnstile, extract X-Token. ALWAYS get fresh token (no caching)."""
        try:
            print("[*] Getting X-Token...")
            
            # Try cache first ONLY if not forcing fresh
            cache_key = "x_token_default"
            if not force_fresh:
                cached = get_cached_token(cache_key)
                if cached:
                    self.x_token = cached
                    print("[✓] Using cached X-Token (age < 5min)")
                    return True
            else:
                # Clear cache if forcing fresh
                with token_cache_lock:
                    if cache_key in token_cache:
                        del token_cache[cache_key]
                        print("[*] Cache cleared for fresh token")
            
            # GET the lobby page
            print("[*] Fetching lobby page to solve Turnstile...")
            res = self.session.get(LOBBY_URL, timeout=10)
            
            if res.status_code != 200:
                print(f"[!] Lobby page failed: {res.status_code}, using fallback")
                self.x_token = "0.er7a8FV8udYFV8udYFsh6XsoK_wFay3LjDe1SVeBwK3gptCS4wI1yfQ"
                return True
            
            # Solve Turnstile
            print("[*] Solving Turnstile challenge...")
            turnstile_token = self.turnstile_solver.solve(LOBBY_URL)
            if not turnstile_token:
                print("[!] Turnstile failed, using fallback token")
                self.x_token = "0.er7a8FV8udYFV8udYFsh6XsoK_wFay3LjDe1SVeBwK3gptCS4wI1yfQ"
                return True
            
            self.x_token = f"1.{turnstile_token}" if not turnstile_token.startswith("1.") else turnstile_token
            
            # Cache the fresh token
            cache_token(cache_key, self.x_token)
            print(f"[✓] X-Token obtained and cached (TTL: 5min)")
            
            return True
        except Exception as e:
            print(f"[!] X-Token error: {str(e)[:50]}, using fallback")
            self.x_token = "0.er7a8FV8udYFV8udYFsh6XsoK_wFay3LjDe1SVeBwK3gptCS4wI1yfQ"
            return True
    
    def register_account(self, mobile_10_digit: str, password: str, ref_code: str = "") -> bool:
        """Register account with X-Token from lobby challenge and optional referral code"""
        max_register_retries = 3
        for register_attempt in range(max_register_retries):
            try:
                # Check IP before registration (verify proxy is working)
                print(f"[DEBUG] Session proxies configured: {self.session.proxies}")
                print(f"[DEBUG] Checking proxy IP before registration...")
                current_ip = self.get_proxy_ip()
                print(f"[✓] Current IP for registration: {current_ip}")
                
                # CRITICAL: Get FRESH X-Token before EACH registration attempt
                # X-Token can expire, causing "timeout-or-duplicate" error
                if register_attempt > 0:
                    print(f"[*] Refreshing X-Token for retry {register_attempt}...")
                    if not self.get_x_token_from_lobby(skip_if_cached=False, force_fresh=True):
                        print(f"[ERROR] Failed to get fresh X-Token for retry")
                        return False
                
                # STEP 1: Send preflight OPTIONS (non-critical, ignore failures)
                self._send_preflight_options("/api/frontend/trpc/auth.registe")
                
                # STEP 2: Check if we have X-Token
                if not self.x_token:
                    print("[ERROR] No X-Token available. Need to get it from lobby first.")
                    return False
                
                # STEP 3: Register account with X-Token header
                # Add small delay (1-2s) to ensure X-Token is fresh and API is ready
                time.sleep(random.uniform(1.0, 2.0))
                
                registration_payload = {
                    "json": {
                        "channelId": 0,
                        "username": mobile_10_digit,
                        "password": password,
                        "phoneNumber": mobile_10_digit,  # 10 digits only
                        "registerDevice": self.device_id,
                        "registerDeviceModel": self.register_device_model,  # Dynamic device model (iOS/Android spoofing)
                        "registerType": "Phone",
                        "appType": "DesktopOS"  # Keep as DesktopOS for API compatibility (web bot)
                    }
                }
                
                # Add referral code if provided (for DUMMY mode)
                if ref_code:
                    # Use parentId field for referral registration
                    parent_id = int(ref_code) if ref_code.isdigit() else ref_code
                    registration_payload["json"]["parentId"] = parent_id
                    print(f"[DEBUG] Adding referral code (parentId): {ref_code}")
                
                headers = self.session.headers.copy()
                headers.update({
                    "X-Trace-Id": ''.join(random.choices(string.ascii_uppercase + string.digits, k=8)),
                    "X-Device-Id": self.device_id,
                    "X-Token": self.x_token,
                    "Content-Type": "application/json",
                    "Channelid": "",
                    "X-Fingerprint-Id": "",
                    "X-Fingerprint-Request-Id": ""
                })
                
                print(f"[DEBUG] Registration payload: {json.dumps(registration_payload)}")
                print(f"[DEBUG] X-Token being sent: {self.x_token[:80]}...")
                print(f"[DEBUG] PROXY URL: {self.proxy_url}")
                print(f"[DEBUG] Session proxies BEFORE request: {self.session.proxies}")
                
                res = self.session.post(
                    f"{self.base_url}/api/frontend/trpc/auth.registe",
                    headers=headers,
                    json=registration_payload,
                    timeout=15
                )
                
                print(f"[DEBUG] Registration Response: {res.status_code}")
                print(f"[DEBUG] Registration Response Body: {res.text[:500]}")
                
                # Try to extract tokens from headers even on failure
                self._extract_auth_tokens_from_headers(res.headers)
                
                if res.status_code == 200:
                    try:
                        response_data = res.json()
                        self._extract_auth_tokens(response_data)
                    except:
                        pass
                    print(f"[DEBUG] Registration success")
                    return True
                elif res.status_code == 403:
                    # Handle 403 specifically - could be timeout or duplicate
                    try:
                        error_data = res.json()
                        reason = error_data.get("reason", "unknown")
                        
                        if reason == "timeout-or-duplicate":
                            # If it's a timeout, retry with fresh X-Token
                            # If it's a duplicate, don't retry (it will fail again)
                            if register_attempt < max_register_retries - 1:
                                print(f"[!] Got 403 timeout-or-duplicate, refreshing X-Token and retrying...")
                                time.sleep(2 ** register_attempt)  # Exponential backoff
                                continue
                            else:
                                print(f"[ERROR] 403 timeout-or-duplicate after {register_attempt + 1} attempts")
                                return False
                    except:
                        pass
                    
                    print(f"[ERROR] Registration failed (403): {res.text[:300]}")
                    return False
                else:
                    error_text = res.text[:300]
                    print(f"[ERROR] Registration failed ({register_attempt + 1}/{max_register_retries}): {error_text}")
                    if register_attempt < max_register_retries - 1 and res.status_code >= 500:
                        print(f"[*] Retrying registration...")
                        time.sleep(2 ** register_attempt)  # Exponential backoff
                        continue
                    return False
                    
            except Exception as e:
                print(f"[ERROR] Registration exception ({register_attempt + 1}/{max_register_retries}): {str(e)[:80]}")
                if register_attempt < max_register_retries - 1:
                    time.sleep(1)
                    continue
                return False
        
        return False
    
    def login_account(self, mobile_10_digit: str, password: str) -> bool:
        """Login to account with X-Token"""
        try:
            # STEP 1: Send preflight OPTIONS
            self._send_preflight_options("/api/frontend/trpc/auth.login")
            
            # STEP 2: Check if we have X-Token
            if not self.x_token:
                print("[ERROR] No X-Token available for login")
                return False
            
            # STEP 3: Login with X-Token
            time.sleep(random.uniform(0.1, 0.3))
            
            login_payload = {
                "json": {
                    "username": mobile_10_digit,
                    "password": password,
                    "deviceId": self.device_id
                }
            }
            
            headers = self.session.headers.copy()
            headers.update({
                "X-Trace-Id": ''.join(random.choices(string.ascii_uppercase + string.digits, k=8)),
                "X-Token": self.x_token,
                "Content-Type": "application/json"
            })
            
            res = self.session.post(
                f"{self.base_url}/api/frontend/trpc/auth.login",
                headers=headers,
                json=login_payload,
                timeout=15
            )
            
            print(f"[DEBUG] Login Response: {res.status_code}")
            
            if res.status_code == 200:
                # Extract tokens from response headers first
                self._extract_auth_tokens_from_headers(res.headers)
                
                # Also try to extract from response body
                try:
                    response_data = res.json()
                    self._extract_auth_tokens(response_data)
                except:
                    pass
                
                print(f"[DEBUG] Login successful, tokens extracted")
                return self.auth_tag is not None
            else:
                print(f"[ERROR] Login failed: {res.text[:300]}")
                return False
                
        except Exception as e:
            print(f"[ERROR] Login failed: {str(e)}")
            return False
    
    def _extract_auth_tokens(self, response_data: dict):
        """Extract authentication tokens from response"""
        try:
            if isinstance(response_data, dict):
                # For registration responses with nested data
                nested_data = response_data.get("result", {}).get("data", {}).get("json", {}).get("data", {})
                if nested_data:
                    self.userid = nested_data.get("userId") or ""
                    self.bearer_token = nested_data.get("token") or ""
                    print(f"[DEBUG] Extracted from registration: userId={self.userid}, token={self.bearer_token[:20] if self.bearer_token else 'None'}...")
                    return
                
                # Try to get from body first
                x_token_data = response_data.get("X-Token-Data", response_data.get("x-token-data", {}))
                
                if isinstance(x_token_data, str):
                    try:
                        x_token_data = json.loads(x_token_data)
                    except:
                        pass
                
                # Extract tokens
                if isinstance(x_token_data, dict):
                    self.auth_tag = x_token_data.get("authTag") or response_data.get("authTag") or ""
                    self.token_data = x_token_data.get("tokenData") or response_data.get("tokenData") or ""
                    self.x_tag = x_token_data.get("tag") or response_data.get("tag") or ""
                    self.userid = x_token_data.get("userId") or response_data.get("userId") or ""
                else:
                    # Fallback to direct extraction from response
                    self.auth_tag = response_data.get("authTag") or response_data.get("X-Auth-Tag") or ""
                    self.token_data = response_data.get("tokenData") or response_data.get("X-Token-Data") or ""
                    self.x_tag = response_data.get("tag") or response_data.get("X-Tag") or ""
                    self.userid = response_data.get("userId") or response_data.get("userid") or ""
                
                # Extract bearer token (might be in authTag as "token;hash" format)
                if self.auth_tag and ";" in self.auth_tag:
                    self.bearer_token = self.auth_tag.split(";")[0]
                elif self.auth_tag:
                    self.bearer_token = self.auth_tag
                
                print(f"[DEBUG] Auth tokens extracted: tag={self.auth_tag[:50] if self.auth_tag else 'None'}...")
        except Exception as e:
            print(f"[ERROR] Failed to extract tokens: {str(e)}")
    
    def _extract_auth_tokens_from_headers(self, headers: dict):
        """Extract authentication tokens from response headers"""
        try:
            # Try to extract from headers (they override body values)
            x_token_data_header = headers.get('X-Token-Data', headers.get('x-token-data', ''))
            
            if x_token_data_header:
                try:
                    # If it's a JSON string, parse it
                    if x_token_data_header.startswith('{'):
                        token_data_obj = json.loads(x_token_data_header)
                        self.auth_tag = token_data_obj.get("authTag") or self.auth_tag
                        self.token_data = token_data_obj.get("tokenData") or self.token_data
                        self.x_tag = token_data_obj.get("tag") or self.x_tag
                        self.userid = token_data_obj.get("userId") or self.userid
                except:
                    self.token_data = x_token_data_header
            
            # Extract other headers
            x_auth_tag = headers.get('X-Auth-Tag', headers.get('x-auth-tag', ''))
            if x_auth_tag:
                self.auth_tag = x_auth_tag
                if ";" in self.auth_tag:
                    self.bearer_token = self.auth_tag.split(";")[0]
                else:
                    self.bearer_token = self.auth_tag
            
            x_tag = headers.get('X-Tag', headers.get('x-tag', ''))
            if x_tag:
                self.x_tag = x_tag
            
            print(f"[DEBUG] Tokens extracted from headers")
        except Exception as e:
            print(f"[ERROR] Failed to extract tokens from headers: {str(e)}")
    
    def make_deposit(self, amount: int = 10000, pay_type_sub_id: int = 1691) -> str:
        """Create deposit/payment request and return payment URL"""
        try:
            if not self.bearer_token:
                print(f"[ERROR] No bearer token available for deposit. userid={self.userid}, bearer={self.bearer_token}")
                return ""
            
            # STEP 1: Send preflight OPTIONS
            self._send_preflight_options("/api/frontend/trpc/pay.create")
            
            # STEP 2: Create payment request
            print(f"[*] Creating deposit request for payTypeSubId={pay_type_sub_id}, amount={amount}")
            time.sleep(random.uniform(2.0, 3.0))
            
            deposit_payload = {
                "json": {
                    "amount": amount,
                    "processMode": "THREE_PARTY_PAYMENT",
                    "payTypeSubId": pay_type_sub_id,
                    "participateReward": False,
                    "lobbyUrl": LAUNCH_URL
                }
            }
            
            headers = self.session.headers.copy()
            trace_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            headers.update({
                "X-Trace-Id": trace_id,
                "X-Tag": self.x_tag or "",
                "X-Auth-Tag": self.auth_tag or "",
                "X-Token-Data": self.token_data or "",
                "Userid": str(self.userid) if self.userid else "",
                "Authorization": f"Bearer {self.bearer_token}" if self.bearer_token else "",
                "Channelid": "",
                "Content-Type": "application/json"
            })
            
            print(f"[DEBUG] Deposit payload: {json.dumps(deposit_payload)}")
            print(f"[DEBUG] Deposit request - Bearer token: {self.bearer_token[:30] if self.bearer_token else 'None'}...")
            print(f"[DEBUG] Deposit request - User ID: {self.userid}")
            print(f"[DEBUG] Deposit request - PayTypeSubId: {pay_type_sub_id}")
            
            res = self.session.post(
                f"{self.base_url}/api/frontend/trpc/pay.create",
                headers=headers,
                json=deposit_payload,
                timeout=15
            )
            
            print(f"[DEBUG] Deposit Response: {res.status_code}")
            
            # Extract tokens from response headers
            self._extract_auth_tokens_from_headers(res.headers)
            
            if res.status_code == 200:
                response_data = res.json()
                
                # Extract payment URL from nested structure
                pay_url = (
                    response_data.get("result", {}).get("data", {}).get("json", {}).get("payUrl") or
                    response_data.get("data", {}).get("json", {}).get("payUrl") or
                    response_data.get("json", {}).get("payUrl") or
                    response_data.get("payUrl") or
                    ""
                )
                
                if pay_url:
                    print(f"[✓] Payment URL obtained ({len(pay_url)} chars)")
                    return pay_url
                else:
                    print(f"[ERROR] No payUrl found in response")
                    print(f"[DEBUG] Response structure: {json.dumps(response_data, indent=2)}")
                    return ""
            else:
                print(f"[ERROR] Deposit failed: {res.status_code}")
                print(f"[DEBUG] Response: {res.text}")
                return ""
                
        except Exception as e:
            print(f"[ERROR] Deposit failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return ""
    
    def execute_full_workflow(self, mode="MAIN", recommender_id="", max_retries=3):
        """Complete workflow: MAIN (register only) or DUMMY (register + deposit)"""
        mobile_10_digit = self.generate_mobile_number()
        password = self.generate_password()
        tx_password = self.generate_password() 
        nickname = self.generate_nickname()
        fullname = self.generate_fullname()
        
        results = {
            "success": False,
            "username": mobile_10_digit,
            "password": password,
            "ip": "",
            "invite_link": "",
            "deposit_channel_1": "",
            "deposit_channel_2": "",
            "mode": mode
        }
        
        # CRITICAL: Get FRESH X-Token for EVERY account (don't cache - API rejects duplicates)
        print(f"[*] Getting fresh X-Token for this account...")
        if not self.get_x_token_from_lobby(skip_if_cached=False, force_fresh=False):
            return {"success": False, "error": "Failed to get X-Token from lobby page"}
        
        # STEP 1: REGISTER
        print(f"[*] Step 1: Registering account ({mode} mode)...")
        if not self.register_account(mobile_10_digit, password, ref_code=recommender_id):
            return {"success": False, "error": "Registration failed"}
        
        # Extract and format invite link
        if self.userid:
            results["invite_link"] = f"https://778gobb.shop/?pid={self.userid}"
            print(f"[✓] Invite link: {results['invite_link']}")
        
        # Get IP address
        results["ip"] = self.get_proxy_ip()
        
        # For MAIN mode, stop here (no deposits)
        if mode == "MAIN":
            results["success"] = True
            return results
        
        # For DUMMY mode, continue with deposits
        wait_time = random.uniform(0.1, 0.3)
        time.sleep(wait_time)
        
        # OPTIMIZATION: Get both deposit links in PARALLEL
        deposit_futures = []
        deposit_futures.append(executor.submit(self.make_deposit, 10000, 1691))
        deposit_futures.append(executor.submit(self.make_deposit, 10000, 1692))
        
        # Collect results
        deposits = []
        for future in as_completed(deposit_futures, timeout=30):
            try:
                deposits.append(future.result())
            except Exception as e:
                deposits.append("")
                print(f"[!] Deposit error: {str(e)[:50]}")
        
        if len(deposits) >= 2:
            results["deposit_channel_1"] = deposits[0]
            results["deposit_channel_2"] = deposits[1]
            if deposits[0]:
                print(f"[✓] Channel 1 obtained")
            if deposits[1]:
                print(f"[✓] Channel 2 obtained")
        
        # Mark as success if registration succeeded (deposits are optional for referral)
        results["success"] = True
        return results

    
    def _set_device_profile(self):
        """Randomizes the digital fingerprint to simulate iPhones and Androids with varied behaviors."""
        is_ios = random.choice([True, False])
        if is_ios:
            # iOS Device Profiles with varied versions and models
            ios_versions = ["15_4", "15_5", "16_1", "16_5", "16_6", "16_7", "17_0", "17_1", "17_2"]
            ios_version = random.choice(ios_versions)
            iphone_models = ["iPhone 12", "iPhone 13", "iPhone 14", "iPhone 15"]
            iphone_model = random.choice(iphone_models)
            
            self.user_agent = f"Mozilla/5.0 ({iphone_model}; CPU iPhone OS {ios_version.replace('_', ' ')} like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/{ios_version.replace('_', '.')} Mobile/15E148 Safari/604.1"
            self.register_device_model = f"web iOS {ios_version.replace('_', '.')} {iphone_model}"
        else:
            # Android Device Profiles with varied versions and models
            android_versions = ["10", "11", "12", "13", "14", "15"]
            android_version = random.choice(android_versions)
            android_models = [
                "SM-S911B", "SM-G991B", "SM-A125F", "SM-A315F",  # Samsung
                "Pixel 4", "Pixel 5", "Pixel 6", "Pixel 7",  # Google
                "CPH2415", "CPH2449",  # OPPO
                "M2010J19SG", "M2010J19SY",  # Xiaomi (Redmi)
                "RMX2185", "RMX3063"  # Realme
            ]
            android_model = random.choice(android_models)
            chrome_version = random.randint(108, 125)
            
            self.user_agent = f"Mozilla/5.0 (Linux; Android {android_version}; {android_model}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Mobile Safari/537.36"
            self.register_device_model = f"web Windows NT 10.0 Android {android_version} {android_model}"

    def get_proxy_ip(self) -> str:
        try:
            print(f"[DEBUG] Getting IP through proxy: {self.session.proxies}")
            ip_text = self.session.get("https://api.ipify.org", timeout=10).text.strip()
            print(f"[DEBUG] IP returned: {ip_text}")
            return ip_text
        except Exception as e:
            print(f"[DEBUG] get_proxy_ip error: {str(e)}")
            return "Unknown IP"

    def shorten_word(self, word: str) -> str:
        length = len(word)
        if length < 4: return word
        return word[:length // 2] if random.choice([True, False]) else word[:(length * 3) // 4]

    def generate_password(self) -> str:
        parts =[random.choice(verbs), random.choice(nouns), random.choice(intl_names)]
        random.shuffle(parts)
        parts[0] = self.shorten_word(parts[0]).capitalize()
        parts[1] = self.shorten_word(parts[1]).lower()
        parts[2] = self.shorten_word(parts[2]).lower()
        joined = "".join(parts)
        return joined[:10] + str(random.randint(10, 99))

    def generate_nickname(self) -> str:
        return (self.shorten_word(random.choice(intl_names)) + self.shorten_word(random.choice(nouns)) + str(random.randint(10, 99))).lower()

    def generate_fullname(self) -> str:
        return f"{random.choice(intl_names).capitalize()} {random.choice(nouns).capitalize()}"

    def generate_mobile_number(self) -> str:
        """Generate valid Philippine mobile number (10 digits) with correct carrier prefix"""
        # Valid Philippine carrier prefixes (2nd digit must be 0-9)
        valid_prefixes = [
            # Smart prefixes: 905-909, 917-918
            "905", "906", "907", "908", "909", "917", "918",
            # Globe prefixes: 915-916, 920-929
            "915", "916", "920", "921", "922", "923", "924", "925", "926", "927", "928", "929",
            # Dito prefixes: 9171-9189
            "917", "918"
        ]
        prefix = random.choice(valid_prefixes)
        rest = ''.join(random.choices(string.digits, k=7))
        return f"{prefix}{rest}"


# ==========================================
# 2. TELEGRAM BOT C2 INTERFACE
# ==========================================
BOT_TOKEN = "8717189735:AAGqnwPoiexXduhAD0qUOUsjZ7oMkPel_bw"
TARGET_URL = "https://api.n-t-v-w.com"
LOBBY_URL = "https://778gobb.shop"  # Fixed: Use the actual domain, not the redirect
LAUNCH_URL = "https://778gobb.shop/launch"
TENANT_ID = "8446112"
X_CLIENT_VERSION = "v234"

# ==========================================
# PROXY ROTATION POOL (Multiple sub-accounts)
# ==========================================
PROXY_POOL = [
    {"username": "smart-Hesuyasu_area-PH_state-AUTONOMOUSREGIONINMUSLIMMINDANAO", "password": "Hesusayu11"},
    {"username": "smart-Ayong22_area-PH_state-BICOLREGION", "password": "Ayongpale12"},
    {"username": "smart-doriano_area-PH_state-CAGAYANVALLEY", "password": "Samiraraah23"},
    {"username": "smart-Samir03_area-PH_state-CENTRALVISAYAS", "password": "Samiraraah23"},
    {"username": "smart-Samir03_area-PH_state-CORDILLERA", "password": "Samiraraah23"},
    {"username": "smart-s9mf8o8tpkmb_area-PH_state-DAVAOREGION", "password": "ToX5OB8bMGaN3vpu"},
    {"username": "smart-Hesuyasu_area-PH_state-EASTERNVISAYAS", "password": "Hesusayu11"},
    {"username": "smart-Ayong22_area-PH_state-ILOCOREGION", "password": "Ayongpale12"},
    {"username": "smart-doriano_area-PH_state-CALABARZON", "password": "Samiraraah23"},
    {"username": "smart-Samir03_area-PH_state-MIMAROPA", "password": "Samiraraah23"},
    {"username": "smart-s9mf8o8tpkmb_area-PH_state-NORTHERNMINDANAO", "password": "ToX5OB8bMGaN3vpu"},
]

# Proxy rotation counter
proxy_rotation_index = 0

def get_next_proxy() -> str:
    """Get next proxy from pool and rotate"""
    global proxy_rotation_index
    proxy_cred = PROXY_POOL[proxy_rotation_index % len(PROXY_POOL)]
    proxy_url = f"http://{proxy_cred['username']}:{proxy_cred['password']}@proxy.smartproxy.net:3120"
    proxy_rotation_index += 1
    print(f"[DEBUG] Using proxy #{proxy_rotation_index % len(PROXY_POOL)}: {proxy_cred['username'][:40]}...")
    return proxy_url

# Cache Turnstile token for reuse across multiple accounts
cached_x_token = None
token_cache_time = None

bot = telebot.TeleBot(BOT_TOKEN)
user_state = {}

def get_batch_name():
    return datetime.now().strftime("batch_%Y%m%d_%H%M%S")

def safe_send_message(chat_id, text, reply_markup=None, parse_mode="HTML", retries=3):
    """Send message with retry logic (handles connection issues)"""
    for attempt in range(retries):
        try:
            return bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e:
            print(f"[*] Telegram send retry {attempt + 1}/{retries}: {str(e)[:50]}")
            if attempt < retries - 1:
                time.sleep(1)
            else:
                print(f"[ERROR] Failed to send message after {retries} retries")
                return None

def safe_edit_message(chat_id, msg_id, text, reply_markup=None, parse_mode="HTML", retries=3):
    """Edit message with retry logic (handles connection issues) - fallback to delete & send"""
    for attempt in range(retries):
        try:
            return bot.edit_message_text(text, chat_id, msg_id, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e:
            error_str = str(e)[:80]
            print(f"[DEBUG] Telegram edit retry {attempt + 1}/{retries}: {error_str}")
            if attempt < retries - 1:
                time.sleep(1 + attempt)
            else:
                # Fallback: Try to delete old message and send new one
                try:
                    print(f"[DEBUG] Edit failed, trying to delete old message and send new one...")
                    bot.delete_message(chat_id, msg_id)
                    time.sleep(0.5)
                    return bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
                except Exception as e2:
                    print(f"[ERROR] Failed both edit and fallback: {str(e2)[:50]}")
                    return None

def get_menu_markup():
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🔢 Set Count", callback_data="set_count"))
    markup.row(
        InlineKeyboardButton("👤 Set Main", callback_data="set_main"),
        InlineKeyboardButton("👥 Set Dummy", callback_data="set_dummy")
    )
    markup.row(
        InlineKeyboardButton("🚀 Generate", callback_data="generate"),
        InlineKeyboardButton("❌ Cancel", callback_data="cancel")
    )
    return markup

def get_result_markup(current, target):
    markup = InlineKeyboardMarkup()
    buttons =[]
    if current < target:
        buttons.append(InlineKeyboardButton("⏩ Next", callback_data="generate"))
    buttons.append(InlineKeyboardButton("🏁 Finish", callback_data="finish"))
    markup.row(*buttons)
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    user_state[chat_id] = {
        "mode": "MAIN", 
        "ref_code": "", 
        "count": 1, 
        "current": 0,
        "batch_name": get_batch_name(),
        "results":[]
    }
    
    text = (
        "⚙️ <b>Username Generator</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔀 Mode        : {user_state[chat_id]['mode']}\n"
        f"🔢 Count       : {user_state[chat_id]['count']}\n"
        "🔑 Passwords   : ✅ ON\n"
        "🌐 IP Addresses: ✅ ON\n"
        "📱 PH Mobile   : ✅ ON\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Tap a button to change settings."
    )
    
    # Retry logic for Telegram API
    for retry_attempt in range(3):
        try:
            msg = bot.send_message(chat_id, text, reply_markup=get_menu_markup(), parse_mode="HTML")
            user_state[chat_id]["menu_msg_id"] = msg.message_id
            break
        except Exception as e:
            print(f"[*] Telegram send_message retry {retry_attempt + 1}/3: {str(e)[:50]}")
            if retry_attempt < 2:
                time.sleep(1)
            else:
                print(f"[ERROR] Failed to send welcome message after 3 retries")


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    state = user_state.get(chat_id)
    
    if not state:
        bot.answer_callback_query(call.id, "Session expired. Type /start")
        return

    if call.data == "cancel":
        bot.delete_message(chat_id, call.message.message_id)
        
    elif call.data == "set_count":
        msg = safe_send_message(chat_id, "🔢 <b>Enter the inv count (1–50):</b>\n\nJust type a number and send it.", parse_mode="HTML")
        if msg:
            state["prompt_msg_id"] = msg.message_id
            bot.register_next_step_handler(msg, process_inv_count)

    elif call.data == "set_main":
        state["mode"] = "MAIN"
        state["ref_code"] = ""
        state["count"] = 1
        refresh_menu(chat_id)
        
    elif call.data == "set_dummy":
        msg = safe_send_message(chat_id, "🔗 <b>Please send the referral link</b>\n<i>(e.g., https://778gobb.shop/?pid=763397002)</i>", parse_mode="HTML")
        if msg:
            state["prompt_msg_id"] = msg.message_id
            bot.register_next_step_handler(msg, process_ref_link)
        
    elif call.data == "generate":
        state["current"] += 1
        
        # Try to edit or send new message
        try:
            safe_edit_message(
                chat_id, 
                call.message.message_id,
                f"⏳ <b>Executing...</b> Entry {state['current']} / {state['count']}", 
                parse_mode="HTML"
            )
            working_msg_id = call.message.message_id
        except:
            # Fallback: send new message
            temp_msg = safe_send_message(chat_id, f"⏳ <b>Executing...</b> Entry {state['current']} / {state['count']}", parse_mode="HTML")
            working_msg_id = temp_msg.message_id if temp_msg else None
        
        if not working_msg_id:
            safe_send_message(chat_id, "❌ Failed to interact with Telegram", parse_mode="HTML")
            state["current"] -= 1
            return
        
        try:
            # Create NEW bot instance for EACH account with ROTATING proxy
            proxy = get_next_proxy()
            print(f"[*] Creating bot instance for entry {state['current']} with fresh proxy...")
            print(f"[DEBUG] Proxy URL being used: {proxy}")
            registration_bot = RegistrationBot(base_url=TARGET_URL, proxy_url=proxy)
            
            mode = state.get("mode", "MAIN")
            
            print(f"[*] Attempting account creation for entry {state['current']}...")
            
            result = registration_bot.execute_full_workflow(mode=mode, recommender_id=state.get("ref_code", ""))
            
            if result and result["success"]:
                state["results"].append(result)
                
                # Format output based on mode
                if mode == "MAIN":
                    output = (
                        f"📋 <b>MAIN ENTRY {state['current']} / {state['count']}</b> ✅\n\n"
                        f"📱 <b>Number</b>   : <code>{result['username']}</code>\n"
                        f"🔑 <b>Password</b>  : <code>{result['password']}</code>\n"
                        f"🌐 <b>IP Address</b> : <code>{result['ip']}</code>\n"
                        f"🔗 <b>Invite Link</b> : <code>{result.get('invite_link', 'N/A')}</code>"
                    )
                else:  # DUMMY mode
                    output = (
                        f"📋 <b>DUMMY ENTRY {state['current']} / {state['count']}</b> ✅\n\n"
                        f"📱 <b>Number</b>   : <code>{result['username']}</code>\n"
                        f"🔑 <b>Password</b>  : <code>{result['password']}</code>\n"
                        f"🌐 <b>IP Address</b> : <code>{result['ip']}</code>\n"
                        f"🔗 <b>Invite Link</b> : <code>{result.get('invite_link', 'N/A')}</code>\n"
                        f"💳 <b>D-Link C1</b>  : <code>{result.get('deposit_channel_1', 'N/A')}</code>\n"
                        f"💳 <b>D-Link C2</b>  : <code>{result.get('deposit_channel_2', 'N/A')}</code>"
                    )
                
                safe_edit_message(
                    chat_id, 
                    working_msg_id, 
                    output, 
                    reply_markup=get_result_markup(state["current"], state["count"]), 
                    parse_mode="HTML"
                )
            else:
                error_msg = f"❌ <b>Failed:</b>\n{result.get('error', 'Unknown error') if result else 'No result'}" if result else "❌ <b>Error:</b> Unknown error"
                
                # Show successful results so far if any
                if state["results"]:
                    summary = f"<b>✅ {len(state['results'])} Account(s) Registered Before Error:</b>\n\n"
                    for idx, res in enumerate(state["results"], 1):
                        summary += (
                            f"<b>#{idx}</b> 📱 <code>{res['username']}</code>\n"
                            f"    🔑 <code>{res['password']}</code> • 🌐 <code>{res['ip']}</code>\n"
                        )
                    
                    error_msg = f"{summary}\n\n{error_msg}"
                
                safe_edit_message(chat_id, working_msg_id, error_msg, parse_mode="HTML")
                state["current"] -= 1
        except Exception as e:
            state["current"] -= 1
            print(f"[ERROR] Exception during generation: {str(e)}")
            import traceback
            traceback.print_exc()
            
            error_msg = f"❌ <b>Exception:</b>\n<code>{str(e)[:150]}</code>"
            
            # Show successful results so far if any
            if state["results"]:
                summary = f"<b>✅ {len(state['results'])} Account(s) Registered Before Error:</b>\n\n"
                for idx, res in enumerate(state["results"], 1):
                    summary += (
                        f"<b>#{idx}</b> 📱 <code>{res['username']}</code>\n"
                        f"    🔑 <code>{res['password']}</code> • 🌐 <code>{res['ip']}</code>\n"
                    )
                
                error_msg = f"{summary}\n\n{error_msg}"
            
            safe_edit_message(chat_id, working_msg_id, error_msg, parse_mode="HTML")
    
    elif call.data == "finish":
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass
        
        if state["results"]:
            date_str = datetime.now().strftime("%Y-%m-%d")
            summary = f"✨ <b>Done!</b>\n\n🏷️ <code>{state['batch_name']}</code> ({date_str})\n\n"
            
            for idx, res in enumerate(state["results"], 1):
                mode_label = res['mode'] if 'mode' in res else state['mode']
                summary += (
                    f"<b>Entry {idx}:</b>\n"
                    f"📱 Number: <code>{res['username']}</code>\n"
                    f"🔑 Password: <code>{res['password']}</code>\n"
                    f"🌐 IP: <code>{res['ip']}</code>\n"
                    f"🔗 Ref Link: <code>{res.get('invite_link', 'N/A')}</code>\n"
                )
                
                # Add deposit links if DUMMY mode
                if state['mode'] == "DUMMY":
                    summary += (
                        f"💳 D-Link C1: <code>{res.get('deposit_channel_1', 'N/A')}</code>\n"
                        f"💳 D-Link C2: <code>{res.get('deposit_channel_2', 'N/A')}</code>\n"
                    )
                
                summary += "\n"
            
            safe_send_message(chat_id, summary, parse_mode="HTML")
        else:
            safe_send_message(chat_id, "❌ No accounts generated yet.", parse_mode="HTML")
        
        state["current"] = 0
        state["batch_name"] = get_batch_name()
        state["results"] = []
        
        # Show menu again
        refresh_menu(chat_id)


def process_inv_count(message):
    chat_id = message.chat.id
    state = user_state.get(chat_id)
    
    bot.delete_message(chat_id, message.message_id)
    if state and state.get("prompt_msg_id"):
        try: bot.delete_message(chat_id, state["prompt_msg_id"])
        except: pass

    try:
        count = int(message.text)
        max_count = 20 if state.get("mode") == "DUMMY" else 1
        
        if 1 <= count <= max_count:
            state["count"] = count
        else:
            max_msg = 20 if state.get("mode") == "DUMMY" else 1
            msg = safe_send_message(chat_id, f"❌ Please enter a number between 1 and {max_msg}.")
            if msg:
                time.sleep(2)
                try:
                    bot.delete_message(chat_id, msg.message_id)
                except:
                    pass
    except ValueError:
        msg = safe_send_message(chat_id, "❌ Invalid number.")
        if msg:
            time.sleep(2)
            try:
                bot.delete_message(chat_id, msg.message_id)
            except:
                pass
        
    refresh_menu(chat_id)


def process_ref_link(message):
    chat_id = message.chat.id
    state = user_state.get(chat_id)
    link = message.text
    
    try:
        bot.delete_message(chat_id, message.message_id)
    except:
        pass
    
    if state and state.get("prompt_msg_id"):
        try:
            bot.delete_message(chat_id, state["prompt_msg_id"])
        except:
            pass

    try:
        parsed_url = urlparse(link)
        # Try to get 'pid' parameter first (new format), fallback to 'r'
        ref_code = parse_qs(parsed_url.query).get('pid', parse_qs(parsed_url.query).get('r', ['']))[0]
        
        if ref_code:
            state["mode"] = "DUMMY"
            state["ref_code"] = ref_code
            
            msg = safe_send_message(chat_id, "🔢 <b>Enter the account count (1–20):</b>\n\nJust type a number and send it.", parse_mode="HTML")
            if msg:
                state["prompt_msg_id"] = msg.message_id
                bot.register_next_step_handler(msg, process_inv_count)
            return 
        else:
            msg = safe_send_message(chat_id, "❌ Invalid link. No '?pid=' parameter found.")
            if msg:
                time.sleep(2)
                try:
                    bot.delete_message(chat_id, msg.message_id)
                except:
                    pass
    except Exception as e:
        msg = safe_send_message(chat_id, f"❌ Error parsing link: {str(e)[:50]}")
        if msg:
            time.sleep(2)
            try:
                bot.delete_message(chat_id, msg.message_id)
            except:
                pass
        
    refresh_menu(chat_id)


def refresh_menu(chat_id):
    state = user_state[chat_id]
    
    ref_info = ""
    if state['mode'] == "DUMMY" and state.get('ref_code'):
        ref_info = f"🔗 Ref Code | ID    : {state['ref_code']}\n"
    
    text = (
        "⚙️ <b>Username Generator</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔀 Mode        : {state['mode']}\n"
        f"🔢 Count       : {state['count']}\n"
        f"{ref_info}"
        "🔑 Passwords   : ✅ ON\n"
        "🌐 IP Addresses: ✅ ON\n"
        "📱 PH Mobile   : ✅ ON\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Tap a button to change settings."
    )
    
    if state.get("menu_msg_id"):
        safe_edit_message(chat_id, state["menu_msg_id"], text, reply_markup=get_menu_markup(), parse_mode="HTML")
    else:
        msg = safe_send_message(chat_id, text, reply_markup=get_menu_markup(), parse_mode="HTML")
        if msg:
            state["menu_msg_id"] = msg.message_id


if __name__ == "__main__":
    print("[*] Starting Telegram Bot C2 Server...")
    
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=10, skip_pending=True)
        except KeyboardInterrupt:
            print("\n[*] Bot stopped by user")
            break
        except Exception as e:
            print(f"[ERROR] Bot polling error: {str(e)[:100]}")
            print("[*] Reconnecting in 5 seconds...")
            time.sleep(5)
            # Continue loop to retry
