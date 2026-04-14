"""
Create Poshmark draft listings.
v7: Groups photos by item using vision. One listing per group, all group photos uploaded.
Listing content (title, description, price, category) is generated dynamically from photos.
"""
import asyncio
import json
import base64
import os
import glob
import re

AUTH_PROFILES = "/home/cymolt/poshmark_listings/.openclaw_state/agents/main/agent/auth-profiles.json"
OLLAMA_BASE_URL    = os.environ.get("OLLAMA_BASE_URL", "http://192.168.86.34:11434/v1")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")  # kept for reference
COOKIES_FILE  = "/home/cymolt/poshmark_listings/auth.json"
INBOUND_DIR   = "/home/cymolt/poshmark_listings/.openclaw_state/media/inbound"
SAMESITE_MAP  = {"no_restriction":"None","unspecified":"None","lax":"Lax","strict":"Strict","none":"None"}

VISION_MODEL  = "gemma3:27b"   # Ollama vision model (photo classification)
TEXT_MODEL    = "llama3.1:8b"  # Ollama text model (listing generation)

# ── Brand floor prices (from memory/brands.md) ────────────────────────────────
BRAND_FLOORS = {
    "burberry": 45, "patagonia": 35, "zara": 15, "gap": 8,
    "carter": 6, "carters": 6, "old navy": 6, "h&m": 5,
}

# ── Valid Poshmark Kids categories (exact names as shown in dropdown) ─────────
KIDS_CATEGORIES = [
    "Shirts & Tops", "Bottoms", "Dresses", "Jackets & Coats",
    "Matching Sets", "One Pieces", "Pajamas", "Shoes",
    "Accessories", "Swim", "Costumes", "Other",
]

# ── Map generic category names → exact Poshmark dropdown label ────────────────
CATEGORY_MAP = {
    "shirts & tops": "Shirts & Tops",
    "tops": "Shirts & Tops",
    "shirt": "Shirts & Tops",
    "top": "Shirts & Tops",
    "bottoms": "Bottoms",
    "pants": "Bottoms",
    "pants & leggings": "Bottoms",
    "leggings": "Bottoms",
    "shorts": "Bottoms",
    "skirts": "Bottoms",
    "skirt": "Bottoms",
    "dresses": "Dresses",
    "dress": "Dresses",
    "jackets & coats": "Jackets & Coats",
    "jacket": "Jackets & Coats",
    "coat": "Jackets & Coats",
    "outerwear": "Jackets & Coats",
    "matching sets": "Matching Sets",
    "sets": "Matching Sets",
    "set": "Matching Sets",
    "one pieces": "One Pieces",
    "one-pieces": "One Pieces",
    "onesie": "One Pieces",
    "romper": "One Pieces",
    "jumpsuit": "One Pieces",
    "pajamas": "Pajamas",
    "sleepwear": "Pajamas",
    "shoes": "Shoes",
    "accessories": "Accessories",
    "swim": "Swim",
    "swimwear": "Swim",
}

# ── Map size strings → Poshmark size tab + label ──────────────────────────────
# Tab options: Baby, Girls, Boys, Custom
SIZE_MAP = {
    "preemie": ("Baby", "Preemie"),
    "newborn": ("Baby", "Newborn"),
    "0-3m": ("Baby", "0-3 Months"), "0-3 months": ("Baby", "0-3 Months"),
    "3-6m": ("Baby", "3-6 Months"), "3-6 months": ("Baby", "3-6 Months"),
    "6-9m": ("Baby", "6-9 Months"), "6-9 months": ("Baby", "6-9 Months"),
    "9-12m": ("Baby", "9-12 Months"), "9-12 months": ("Baby", "9-12 Months"),
    "12-18m": ("Baby", "12-18 Months"), "12-18 months": ("Baby", "12-18 Months"),
    "18-24m": ("Baby", "18-24 Months"), "18-24 months": ("Baby", "18-24 Months"),
    "3m": ("Baby", "3 Months"), "6m": ("Baby", "6 Months"),
    "9m": ("Baby", "9 Months"), "12m": ("Baby", "12 Months"),
    "18m": ("Baby", "18 Months"), "24m": ("Baby", "24 Months"),
    "2t": ("Girls", "2T"), "3t": ("Girls", "3T"), "4t": ("Girls", "4T"),
    "5t": ("Girls", "5T"),
    "2": ("Girls", "2T"), "3": ("Girls", "3T"), "4": ("Girls", "4T"), "5": ("Girls", "5T"),
    "1-2 years": ("Girls", "2T"), "2-3 years": ("Girls", "3T"),
    "3-4 years": ("Girls", "4T"), "3-4": ("Girls", "4T"),
    "4-5 years": ("Girls", "5T"),
    "5-6 years": ("Girls", "6"), "6": ("Girls", "6"),
    "6-7 years": ("Girls", "7"), "7": ("Girls", "7"),
    "7-8 years": ("Girls", "8"), "8": ("Girls", "8"),
    "8-9 years": ("Girls", "9"), "9": ("Girls", "9"),
    "9-10 years": ("Girls", "10"), "10": ("Girls", "10"),
    "10-11 years": ("Girls", "11"), "11": ("Girls", "11"),
    "11-12 years": ("Girls", "12"), "12": ("Girls", "12"),
    "13": ("Girls", "13"), "14": ("Girls", "14"), "xs": ("Girls", "XS"),
    "s": ("Girls", "S"), "m": ("Girls", "M"), "l": ("Girls", "L"), "xl": ("Girls", "XL"),
}


def encode_image(path, max_px=1024):
    """Resize image to max_px on the longest side and return base64 JPEG string."""
    from PIL import Image
    import io
    with Image.open(path) as img:
        img = img.convert("RGB")
        img.thumbnail((max_px, max_px), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return base64.standard_b64encode(buf.getvalue()).decode("utf-8")


ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


def vision_call_with_retry(client, content, max_tokens=600, retries=4, base_delay=5, model=None):
    """
    Call vision model via Ollama with backoff.
    On error, retries with exponential backoff. Falls back to Anthropic Haiku if ANTHROPIC_API_KEY is set.
    """
    import time
    for attempt in range(retries):
        try:
            effective_model = model or VISION_MODEL
            extra = {"response_format": {"type": "json_object"}} if effective_model == TEXT_MODEL else {}
            resp = client.chat.completions.create(
                model=effective_model, max_tokens=max_tokens,
                messages=[{"role": "user", "content": content}],
                **extra,
            )
            text = resp.choices[0].message.content if resp.choices[0].message.content else None
            if text is None:
                raise ValueError("Empty response from model")
            return text.strip()
        except Exception as e:
            if attempt == retries - 1 and ANTHROPIC_API_KEY:
                print(f"  ⚠️  Ollama failed ({e}) — falling back to Anthropic Haiku...")
                return vision_call_anthropic_fallback(content, max_tokens)
            elif attempt < retries - 1:
                wait = base_delay * (2 ** attempt)
                print(f"  ⏳ Ollama error ({type(e).__name__}) — retrying in {wait}s (attempt {attempt+2}/{retries})...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Vision API failed after retries")


def vision_call_anthropic_fallback(openrouter_content, max_tokens=600):
    """
    Fallback vision call using Anthropic Haiku when Ollama is unavailable.
    Converts OpenAI-format content to Anthropic format.
    """
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Convert OpenAI-format content to Anthropic format
    anthropic_content = []
    for block in openrouter_content:
        if block["type"] == "image_url":
            url = block["image_url"]["url"]
            if url.startswith("data:image/jpeg;base64,"):
                img_data = url.split(",", 1)[1]
                anthropic_content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": img_data}
                })
        elif block["type"] == "text":
            anthropic_content.append({"type": "text", "text": block["text"]})

    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": anthropic_content}]
    )
    return resp.content[0].text.strip()


def parse_json_response(raw):
    """Strip preamble, markdown fences, and trailing text then parse JSON."""
    raw = raw.strip()
    # Strip markdown code fences
    if "```" in raw:
        parts = raw.split("```")
        # Pick the part that contains a JSON object
        for part in parts:
            part = part.lstrip("json").strip()
            if "{" in part:
                raw = part
                break
    # Strip any preamble before the first { and any trailing text after the last }
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in response: {raw[:200]!r}")
    raw = raw[start:end + 1]
    # Fix missing opening quotes on property names, e.g. ,\ndept": -> ,\n"dept":
    # The pattern only matches unquoted keys because " is not a word char.
    raw = re.sub(r'([{,]\s*)(\w+)":', r'\1"\2":', raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Truncation fallback: find the last complete key-value pair and close the object
        last_pos = None
        for m in re.finditer(
            r'(,|\{)\s*"[^"]+"\s*:\s*(?:"(?:[^"\\]|\\.)*"|\d+(?:\.\d+)?|true|false|null|\[(?:[^\[\]]*)])',
            raw
        ):
            last_pos = m.end()
        if last_pos is not None:
            fixed = raw[:last_pos] + "}"
            try:
                result = json.loads(fixed)
                print("  WARNING: JSON was truncated; recovered by closing after last complete key-value pair.")
                return result
            except json.JSONDecodeError:
                pass
        raise


def scan_inbound():
    """Return all image files in the inbound folder, sorted oldest-first."""
    files = []
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG"):
        files.extend(glob.glob(os.path.join(INBOUND_DIR, ext)))
    files = sorted(set(files), key=os.path.getmtime)
    print(f"Found {len(files)} image(s) in inbound folder.")
    return files


def load_api_key():
    with open(AUTH_PROFILES) as f:
        profiles = json.load(f)
    return profiles["profiles"]["anthropic:pi-automation-agency"]["token"]


def normalize_cookie(c):
    nc = {"name":c["name"],"value":c["value"],"domain":c["domain"],"path":c.get("path","/"),
          "httpOnly":c.get("httpOnly",False),"secure":c.get("secure",False),
          "sameSite":SAMESITE_MAP.get(c.get("sameSite","None").lower(),"None")}
    if "expirationDate" in c:
        nc["expires"] = c["expirationDate"]
    return nc


CLASSIFICATION_CACHE = "/home/cymolt/poshmark_listings/.openclaw_state/classification_cache.json"

def load_classification_cache():
    try:
        with open(CLASSIFICATION_CACHE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_classification_cache(cache):
    with open(CLASSIFICATION_CACHE, "w") as f:
        json.dump(cache, f, indent=2)


def classify_photo(client, path, index, cache):
    """
    Classify a single photo: garment type, print/color, brand, size if visible.
    Results are cached by file path to avoid redundant API calls on re-runs.
    """
    import time

    # Return cached result if available
    if path in cache:
        result = cache[path]
        result["index"] = index
        print(f"    (cached) → {result.get('photo_type')} | {result.get('garment_type')} | {result.get('print')} | {result.get('brand')} {result.get('size')}")
        return result

    img_data = encode_image(path)
    content = [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_data}"}},
        {"type": "text", "text": (
            "Classify this clothing photo. Return ONLY valid JSON, no markdown:\n"
            '{"photo_type": "garment|tag|other", '
            '"garment_type": "top|pants|shorts|dress|onesie|jacket|set|unknown", '
            '"print": "solid|floral|cherry|stripe|check|plaid|graphic|other — be specific e.g. yellow-floral or red-cherry", '
            '"color": "main background color", '
            '"brand": "brand name or unknown", '
            '"size": "size if visible on tag or unknown"}'
        )}
    ]
    raw = vision_call_with_retry(client, content, max_tokens=150)
    result = parse_json_response(raw)
    result["index"] = index
    result["path"] = path

    # Cache and save immediately so partial progress survives failures
    cache[path] = {k: v for k, v in result.items() if k != "index"}
    save_classification_cache(cache)

    time.sleep(1)  # brief pause between Ollama calls
    return result


def group_photos_by_item(api_key, photo_paths):
    """
    2-pass grouping:
    Pass 1 — classify each photo individually (garment type + print + color).
    Pass 2 — group by matching garment_type + print key.
    Tag photos are assigned to the item whose brand/size they show.
    Returns groups (list of path lists) and descriptions.
    """
    import time
    from openai import OpenAI
    client = OpenAI(api_key="ollama", base_url=OLLAMA_BASE_URL, timeout=300)

    print(f"  Pass 1: classifying {len(photo_paths)} photos individually...")
    cache = load_classification_cache()
    classifications = []
    for i, path in enumerate(photo_paths):
        print(f"    [{i+1}/{len(photo_paths)}] {path.split('/')[-1][:20]}")
        c = classify_photo(client, path, i, cache)
        if "index" not in c:
            c["index"] = i
        print(f"      → {c.get('photo_type')} | {c.get('garment_type')} | {c.get('print')} | {c.get('brand')} {c.get('size')}")
        classifications.append(c)

    print("  Pass 2: grouping by garment type + print...")

    def normalize_print(pr):
        """Normalize texture-only prints to 'solid' so waffle/stripe-texture/ribbed all cluster together."""
        pr = pr.lower().strip()
        # These are fabric textures, not patterns — treat as solid
        texture_words = ("waffle", "ribbed", "stripe", "knit", "crinkle", "linen", "solid", "plain", "texture")
        if any(w in pr for w in texture_words) and not any(p in pr for p in ("floral", "cherry", "check", "plaid", "graphic", "dot", "print", "animal")):
            return "solid"
        return pr

    # Build group key: garment_type + normalized_print
    groups_map = {}  # key → list of indices
    tag_photos = []  # tag photos to assign after
    other_photos = []  # unassigned

    for c in classifications:
        if c.get("photo_type") == "tag":
            tag_photos.append(c)
            continue
        gt = c.get("garment_type", "unknown").lower().strip()
        pr = normalize_print(c.get("print", "unknown"))
        # Exclude color from key — lighting variation causes cream/off-white/white to split
        key = f"{gt}|{pr}"
        if key not in groups_map:
            groups_map[key] = []
        groups_map[key].append(c["index"])

    # Assign tag photos to the best matching group by garment_type + print in tag description
    for tag in tag_photos:
        tag_print = normalize_print(tag.get("print", ""))
        tag_gt = tag.get("garment_type", "").lower().strip()
        best_key = None
        # Match on garment_type + print
        for key in groups_map:
            gt_k, pr_k = key.split("|")
            if tag_gt and tag_gt == gt_k and tag_print and tag_print == pr_k:
                best_key = key; break
        # Fall back: match on print only
        if not best_key and tag_print:
            for key in groups_map:
                _, pr_k = key.split("|")
                if tag_print == pr_k or tag_print in pr_k or pr_k in tag_print:
                    best_key = key; break
        # Last resort: first group
        if not best_key and groups_map:
            best_key = list(groups_map.keys())[0]
        if best_key:
            groups_map[best_key].append(tag["index"])
        else:
            other_photos.append(tag["index"])

    # Merge or discard singleton groups (1 photo)
    singleton_keys = [k for k, v in groups_map.items() if len(v) == 1]
    for sk in singleton_keys:
        sg_gt, sg_pr = sk.split("|")
        best_key = None
        # Try matching by print first
        for key in groups_map:
            if key == sk:
                continue
            gt_k, pr_k = key.split("|")
            if sg_pr == pr_k or sg_pr in pr_k or pr_k in sg_pr:
                best_key = key; break
        if best_key:
            groups_map[best_key].extend(groups_map.pop(sk))
            print(f"  Merged singleton [{sk}] into [{best_key}]")
        else:
            # No match found — discard the singleton (likely a misclassified photo)
            discarded = groups_map.pop(sk)
            print(f"  Discarded unmatched singleton [{sk}] (photo indices: {discarded})")

    # Build output — convert index lists back to file paths
    groups = [[photo_paths[i] for i in sorted(indices)] for indices in groups_map.values() if indices]
    descriptions = []
    for key, indices in groups_map.items():
        if not indices:
            continue
        gt, pr = key.split("|")
        # Find brand/size from any photo in this group
        brand = "Unknown"
        size = ""
        for c in classifications:
            if c["index"] in indices:
                if c.get("brand", "unknown").lower() not in ("unknown", ""):
                    brand = c["brand"]
                if c.get("size", "unknown").lower() not in ("unknown", ""):
                    size = c["size"]
        descriptions.append(f"{brand} {gt} — {pr} print — {size}".strip(" —"))

    print(f"  Found {len(groups)} group(s) after 2-pass classification")
    return groups, descriptions


def generate_listing(photo_paths, group_description):
    """
    Send grouped photos to vision model to extract item details and generate
    a full listing: title, description, brand, size, condition, category, price.
    Returns a listing dict ready for fill_listing().
    Images are resized before sending to stay within free-tier limits.
    """
    import time
    from openai import OpenAI
    client = OpenAI(api_key="ollama", base_url=OLLAMA_BASE_URL, timeout=300)

    time.sleep(2)  # brief pause between Ollama calls

    categories_str = ", ".join(KIDS_CATEGORIES)
    brand_floors_str = ", ".join(f"{b.title()} (floor ${p})" for b, p in BRAND_FLOORS.items())

    content = [{"type": "text", "text": (
        "You are an expert Poshmark reseller specializing in baby and kids clothing.\n"
        f"Brand floor prices: {brand_floors_str}\n"
        f"Valid Poshmark Kids categories: {categories_str}\n\n"
        "Pricing: NWT = floor+20%, Like New = floor, Gently Used = floor-10%. "
        "Unknown brand: estimate $5-$20 based on type and condition.\n"
        "Title format: [Brand] [Item Type] [Size] [Color] [Condition]\n\n"
        f"Item to list: {group_description}\n\n"
        "Return ONLY valid JSON, no markdown:\n"
        '{"brand":"...","size":"...","condition":"NWT|Like New|Gently Used",'
        '"item_type":"...","color":"...","dept":"Kids","category":"...",'
        '"subcategory":null,"title":"...","description":"2-3 sentences + 4-5 hashtags",'
        '"list_price":"12"}'
    )}]

    raw = None
    for attempt in range(3):
        raw = vision_call_with_retry(client, content, max_tokens=2000, model=TEXT_MODEL)
        print(f"  [generate_listing] raw response (attempt {attempt+1}): {repr(raw[:200]) if raw else repr(raw)}")
        if raw and raw.strip():
            break
        print(f"  ⚠️  Empty response from {TEXT_MODEL} (attempt {attempt+1}/3) — retrying in 5s...")
        import time as _t; _t.sleep(5)
    if not raw or not raw.strip():
        raise RuntimeError(f"generate_listing: {TEXT_MODEL} returned empty response after 3 attempts")
    data = parse_json_response(raw)

    # Apply brand floor safety net
    brand_key = data.get("brand", "").lower()
    floor = next((v for k, v in BRAND_FLOORS.items() if k in brand_key), None)
    try:
        price = int(data.get("list_price", "0"))
    except (ValueError, TypeError):
        price = 0
    if floor and price < floor:
        data["list_price"] = str(floor)
        print(f"  Price ${price} below floor ${floor} for {data['brand']} — bumped to ${floor}")

    print(f"  Generated: {data['title'][:60]}")
    print(f"     Brand: {data['brand']} | Size: {data['size']} | Condition: {data['condition']} | Price: ${data['list_price']}")
    return data


# ── Cookie banner ─────────────────────────────────────────────────────────────

async def dismiss_cookie_banner(page, label=""):
    tag = f" [{label}]" if label else ""
    try:
        ok_btn = page.locator('button.btn--primary:has-text("Ok"), button.btn--primary:has-text("OK")')
        count = await ok_btn.count()
        for i in range(count):
            btn = ok_btn.nth(i)
            if await btn.is_visible():
                await btn.click(force=True)
                await page.wait_for_timeout(400)
                print(f"  🍪 Cookie banner dismissed{tag}")
                return
    except Exception:
        pass
    try:
        dismissed = await page.evaluate("""
            (function() {
                var banner = document.querySelector('.cookie-banner, [class*="cookie-consent"], [class*="gdpr"]');
                if (!banner) return false;
                var btns = banner.querySelectorAll('button');
                for (var b of btns) {
                    if (b.textContent.trim().match(/^(Ok|OK|Accept)$/)) { b.click(); return true; }
                }
                banner.remove();
                return true;
            })()
        """)
        if dismissed:
            await page.wait_for_timeout(400)
            print(f"  🍪 Cookie banner dismissed (JS){tag}")
    except Exception:
        pass


# ── JS fill ───────────────────────────────────────────────────────────────────

async def js_fill(page, selector, value, label):
    import re as _re
    ph_match = _re.search(r'placeholder=["\']([^"\']+)["\']', selector)
    keyword = ph_match.group(1)[:12] if ph_match else None

    for attempt in range(20):
        try:
            if keyword:
                result = await page.evaluate("""
                    ([kw, val]) => {
                        var el = [...document.querySelectorAll('input,textarea')]
                            .find(e => e.placeholder.includes(kw));
                        if (!el) return 'not_found';
                        el.scrollIntoView({block:'center'}); el.focus();
                        var proto = el.tagName==='TEXTAREA'
                            ? window.HTMLTextAreaElement.prototype
                            : window.HTMLInputElement.prototype;
                        var ns = Object.getOwnPropertyDescriptor(proto,'value');
                        if (ns) ns.set.call(el, val);
                        el.dispatchEvent(new Event('input',{bubbles:true}));
                        el.dispatchEvent(new Event('change',{bubbles:true}));
                        return 'ok';
                    }
                """, [keyword, value])
            else:
                result = await page.evaluate("""
                    ([sel, val]) => {
                        var el = document.querySelector(sel);
                        if (!el) return 'not_found';
                        el.scrollIntoView({block:'center'}); el.focus();
                        var ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value')
                            || Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value');
                        if (ns) ns.set.call(el, val);
                        el.dispatchEvent(new Event('input',{bubbles:true}));
                        el.dispatchEvent(new Event('change',{bubbles:true}));
                        return 'ok';
                    }
                """, [selector, value])

            if result == 'ok':
                print(f"  ✅ {label} (attempt {attempt+1})")
                return True
            await page.wait_for_timeout(500)
        except Exception as e:
            print(f"  ❌ {label} error: {e}")
            return False
    print(f"  ❌ {label}: not found after retries")
    return False


# ── Category selection ────────────────────────────────────────────────────────

async def select_category(page, dept, category, subcategory):
    """Select Department > Category in Poshmark's dropdown.
    After Kids is selected, subcategories appear as LI elements (not A tags).
    """
    try:
        await dismiss_cookie_banner(page, "before category")

        # Normalize category name via CATEGORY_MAP
        posh_category = CATEGORY_MAP.get(category.lower().strip(), category)

        await page.locator('.listing-editor__category-container').first.click()
        await page.wait_for_timeout(1000)

        # Department — always an A tag
        dept_loc = page.locator(f'a.dropdown__link:has-text("{dept}")').first
        await dept_loc.wait_for(state="visible", timeout=8000)
        await dept_loc.click()
        await page.wait_for_timeout(1200)
        print(f"  ✅ Department: {dept}")

        # Category — after clicking dept, subcats appear as LI.dropdown__link
        cat_loc = page.locator(f'li.dropdown__link:has-text("{posh_category}")').first
        await cat_loc.wait_for(state="visible", timeout=8000)
        await cat_loc.scroll_into_view_if_needed()
        await cat_loc.click()
        await page.wait_for_timeout(1200)
        print(f"  ✅ Category: {posh_category}")

        return True
    except Exception as e:
        print(f"  ❌ Category failed: {e}")
        return False


# ── Size selection ────────────────────────────────────────────────────────────

async def select_size(page, size_str):
    """Open the size dropdown, pick the right tab (Baby/Girls/Boys), and click the size."""
    if not size_str or size_str.lower() in ("unknown", ""):
        print("  ⚠️  Size unknown — skipping")
        return False

    size_key = size_str.lower().strip()
    mapping = SIZE_MAP.get(size_key)
    if not mapping:
        # Try partial match
        for k, v in SIZE_MAP.items():
            if k in size_key or size_key in k:
                mapping = v
                break
    if not mapping:
        print(f"  ⚠️  Size '{size_str}' not in size map — skipping")
        return False

    tab_name, size_label = mapping
    try:
        # Open size dropdown
        size_dd = page.locator('div.dropdown__selector:has-text("Select Size")').first
        if await size_dd.count() == 0:
            # Already selected — find current value container
            size_dd = page.locator('[class*="listing-editor__size"], [class*="size"] .dropdown__selector').first
        await size_dd.click()
        await page.wait_for_timeout(800)

        # Click the tab (Baby / Girls / Boys / Custom)
        tab = page.locator(f'li.navigation--horizontal__tab:has-text("{tab_name}")').first
        if await tab.count() > 0:
            await tab.click()
            await page.wait_for_timeout(600)

        # Click the size option (plain LI)
        size_opt = page.locator(f'li:has-text("{size_label}")').first
        await size_opt.wait_for(state="visible", timeout=5000)
        await size_opt.click()
        await page.wait_for_timeout(600)
        print(f"  ✅ Size: {size_label} ({tab_name})")
        return True
    except Exception as e:
        print(f"  ❌ Size selection failed: {e}")
        return False


# ── Photo upload ──────────────────────────────────────────────────────────────

async def apply_photo_modal(page, photo_label):
    """Wait for the crop modal and click Apply to accept the photo."""
    modal = page.locator('[data-test="modal-body"].listing-editor__image-modal').first
    try:
        await modal.wait_for(state="visible", timeout=10000)
    except Exception:
        await page.wait_for_timeout(2000)
        return

    # Click Apply button
    for selector in ['button[data-et-name="apply"]', 'button.btn--primary:has-text("Apply")']:
        try:
            btn = page.locator(selector).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                await page.wait_for_timeout(1000)
                try:
                    await modal.wait_for(state="hidden", timeout=5000)
                except Exception:
                    pass
                print(f"  📷 Photo applied: {photo_label}")
                return
        except Exception:
            pass

    # JS fallback
    await page.evaluate('() => { var b = document.querySelector(\'button[data-et-name="apply"]\'); if(b) b.click(); }')
    await page.wait_for_timeout(1500)
    print(f"  📷 Photo applied (JS): {photo_label}")


async def upload_all_photos(page, photo_paths):
    """
    Upload all photos for a listing.
    First photo → cover shot via named input.
    Additional photos → find next available file input slot after each upload.
    """
    for slot_idx, photo_path in enumerate(photo_paths):
        label = photo_path.split("/")[-1][:20]

        if slot_idx == 0:
            # Cover shot — use the primary named input
            file_input = page.locator('input[name="img-file-input"]').first
        else:
            # Additional photos — Poshmark reveals more file inputs after each upload.
            # Wait briefly for a new slot to appear, then use the next available input.
            await page.wait_for_timeout(800)
            # Get all visible file inputs and use the one at slot_idx
            # (each upload reveals the next empty slot)
            file_input = page.locator('input[type="file"]').nth(slot_idx)
            if await file_input.count() == 0:
                # Try triggering the "add more" area — look for empty photo slot button
                add_btn = page.locator('[class*="add-photo"], [class*="upload-photo"], [data-test*="add-photo"]').first
                if await add_btn.count() > 0:
                    await add_btn.click()
                    await page.wait_for_timeout(500)
                # Retry locating the input
                file_input = page.locator('input[type="file"]').nth(slot_idx)

        try:
            await file_input.set_input_files(photo_path)
            await apply_photo_modal(page, label)
        except Exception as e:
            print(f"  ❌ Photo {slot_idx+1} upload failed: {e}")
            break

    print(f"  ✅ {len(photo_paths)} photo(s) uploaded")


# ── Save draft ────────────────────────────────────────────────────────────────

async def dismiss_any_modal(page):
    """Close any open modal backdrop by clicking its close button or pressing Escape."""
    try:
        backdrop = page.locator('[data-test="modal"], .modal-backdrop').first
        if await backdrop.count() > 0 and await backdrop.is_visible():
            close_btn = page.locator('.modal__close-btn, button.btn--close').first
            if await close_btn.count() > 0 and await close_btn.is_visible():
                await close_btn.click()
                await page.wait_for_timeout(600)
            else:
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(600)
    except Exception:
        pass


async def save_draft(page):
    """Click Cancel → Save Draft. Returns the Poshmark listing ID if captured, else True, or False on failure."""
    try:
        await dismiss_cookie_banner(page, "before cancel")
        await dismiss_any_modal(page)
        cancel_btn = page.locator('button:has-text("Cancel"), a:has-text("Cancel")').first
        await cancel_btn.wait_for(state="visible", timeout=10000)

        # Grab listing ID from the Cancel/Discard button's data attribute before clicking
        listing_id = await cancel_btn.get_attribute("data-et-prop-listing_id")

        await cancel_btn.click(force=True)
        await page.wait_for_timeout(1500)
        print("  ✅ Cancel clicked")

        await dismiss_cookie_banner(page, "before save draft")
        save_btn = page.locator('button[data-et-name="save_draft"]').first
        if await save_btn.count() == 0:
            save_btn = page.locator('button:has-text("Save Draft")').first
        try:
            await save_btn.wait_for(state="visible", timeout=8000)
        except Exception:
            pass
        await save_btn.click(force=True)
        await page.wait_for_timeout(2000)

        # If we didn't get the ID from the button, try extracting from the URL redirect
        if not listing_id:
            current_url = page.url
            import re
            m = re.search(r'/listing/([a-f0-9]+)', current_url)
            if m:
                listing_id = m.group(1)

        print(f"  ✅ Save Draft clicked! listing_id={listing_id}")
        return listing_id or True
    except Exception as e:
        print(f"  ❌ Save Draft failed: {e}")
        return False


# ── Fill one listing ──────────────────────────────────────────────────────────

async def fill_listing(page, listing, photos, idx):
    print(f"\n{'='*60}")
    print(f"Listing {idx+1}: {listing['title'][:55]}")
    print(f"Photos: {len(photos)}")
    print(f"{'='*60}")

    await page.goto("https://poshmark.com/create-listing", wait_until="networkidle", timeout=60000)
    await page.wait_for_timeout(2500)

    if "login" in page.url.lower():
        print("  ERROR: Not logged in!")
        return False

    await dismiss_cookie_banner(page, "page load")
    await page.wait_for_timeout(1500)

    # Upload all photos (cover + additional)
    await upload_all_photos(page, photos)
    await page.wait_for_timeout(500)

    # Title
    await dismiss_cookie_banner(page, "before title")
    if not await js_fill(page, 'input[placeholder="What are you selling? (required)"]', listing["title"], "Title"):
        print("  ❌ Title failed — aborting")
        return False

    await page.wait_for_timeout(400)

    # Description
    await dismiss_cookie_banner(page, "before description")
    desc_escaped = listing["description"].replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    await js_fill(page, 'textarea[placeholder="Describe it! (required)"]', desc_escaped, "Description")
    await page.wait_for_timeout(400)

    # Category
    await select_category(page, listing["dept"], listing["category"], listing.get("subcategory"))
    await page.wait_for_timeout(500)

    # Size
    await dismiss_cookie_banner(page, "before size")
    await select_size(page, listing.get("size", ""))
    await page.wait_for_timeout(400)

    # Brand
    await dismiss_cookie_banner(page, "before brand")
    if await js_fill(page, 'input[placeholder="Enter the Brand/Designer"]', listing["brand"], "Brand"):
        await page.wait_for_timeout(1000)
        await dismiss_cookie_banner(page, "after brand")
        try:
            await page.locator('input[placeholder="Enter the Brand/Designer"]').first.press("Escape")
        except Exception:
            pass

    await page.wait_for_timeout(400)

    # Price
    await dismiss_cookie_banner(page, "before price")
    if not await js_fill(page, "input.listing-price-input", listing["list_price"], "List price"):
        await js_fill(page, 'input[data-vv-name="listingPrice"]', listing["list_price"], "List price (alt)")

    await page.wait_for_timeout(300)

    # Screenshot
    await dismiss_cookie_banner(page, "before screenshot")
    await page.screenshot(path=f"/home/cymolt/poshmark_listings/before_draft_{idx+1}.png")
    print(f"  📸 before_draft_{idx+1}.png")

    # Save
    result = await save_draft(page)
    await page.wait_for_timeout(1000)
    await page.screenshot(path=f"/home/cymolt/poshmark_listings/after_draft_{idx+1}.png")
    print(f"  📸 after_draft_{idx+1}.png")
    return result  # listing_id string, True, or False


PENDING_LISTINGS_FILE = "/home/cymolt/poshmark_listings/pending_listings.json"


def save_pending_listings(listings_to_create):
    data = []
    for item in listings_to_create:
        data.append({
            "listing": item["listing"],
            "photos": item["photos"],
            "description": item["description"],
            "status": "pending",
        })
    with open(PENDING_LISTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved {len(data)} pending listing(s) to {PENDING_LISTINGS_FILE}")


def load_pending_listings():
    with open(PENDING_LISTINGS_FILE) as f:
        return json.load(f)


def format_whatsapp_summary(listings_to_create):
    """Format a concise pricing summary to send to Master Jack via WhatsApp."""
    lines = [f"📦 {len(listings_to_create)} listing(s) ready for review:\n"]
    for i, item in enumerate(listings_to_create, 1):
        l = item["listing"]
        lines.append(
            f"{i}. {l['title']}\n"
            f"   💰 ${l['list_price']} | {l['condition']} | {l['size']}\n"
            f"   📷 {len(item['photos'])} photo(s)"
        )
    lines.append("\nReply APPROVE to save all as Poshmark drafts.")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

OPENCLAW_BIN = "/home/cymolt/.npm-global/bin/openclaw"
WHATSAPP_NOTIFY_TO = "+14046442028"
POSHMARK_CLOSET = "poshmark.com/closet/POSHMARK_USER_REDACTED"


def send_whatsapp_notification(results):
    """Send a WhatsApp summary of drafted listings via OpenClaw CLI."""
    import subprocess
    successful = [r for r in results if r["success"]]
    failed = len(results) - len(successful)
    count = len(successful)
    if count == 0:
        msg = f"⚠️ Poshmark draft run finished but 0 listings were saved ({failed} failed)."
    else:
        titles = ", ".join(r["title"][:40] for r in successful)
        msg = (
            f"✅ {count} draft{'s' if count != 1 else ''} saved to Poshmark! "
            f"Review at {POSHMARK_CLOSET}. "
            f"Listings: {titles}"
        )
        if failed:
            msg += f" ({failed} failed)"
    print(f"\n  📲 Sending WhatsApp notification to {WHATSAPP_NOTIFY_TO}...")
    try:
        result = subprocess.run(
            [OPENCLAW_BIN, "message", "send",
             "--channel", "whatsapp",
             "--target", WHATSAPP_NOTIFY_TO,
             "--message", msg],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print("  ✅ WhatsApp notification sent.")
        else:
            print(f"  ⚠️  WhatsApp send failed (exit {result.returncode}): {result.stderr.strip()[:200]}")
    except Exception as e:
        print(f"  ⚠️  WhatsApp send error: {e}")


async def run_preview(api_key):
    """
    Phase 1: Vision grouping + listing generation.
    Saves pending_listings.json and prints a WhatsApp-ready summary.
    Run this when new photos arrive. Send the summary to Master Jack and wait for APPROVE.
    """
    inbound_photos = scan_inbound()
    if not inbound_photos:
        print("No photos in inbound folder. Nothing to do.")
        return

    print(f"\nGrouping {len(inbound_photos)} photo(s) by item...")
    groups, descriptions = group_photos_by_item(api_key, inbound_photos)
    print(f"Found {len(groups)} item group(s):")
    for i, (group, desc) in enumerate(zip(groups, descriptions)):
        print(f"  Group {i+1}: {len(group)} photo(s) — {desc}")

    print(f"\nGenerating listing details for {len(groups)} group(s)...")
    listings_to_create = []
    for group, desc in zip(groups, descriptions):
        print(f"\n  Analyzing group: {desc[:60]}")
        listing = generate_listing(group, desc)
        listings_to_create.append({"listing": listing, "photos": group, "description": desc})

    save_pending_listings(listings_to_create)

    print("\n" + "="*60)
    print("WHATSAPP SUMMARY (send this to Master Jack):")
    print("="*60)
    print(format_whatsapp_summary(listings_to_create))


async def run_create():
    """
    Phase 2: Playwright draft creation.
    Reads pending_listings.json and creates Poshmark drafts.
    Run this after Master Jack replies APPROVE.
    """
    from playwright.async_api import async_playwright

    if not os.path.exists(PENDING_LISTINGS_FILE):
        print("No pending_listings.json found. Run preview first.")
        return

    listings_to_create = load_pending_listings()
    print(f"Loaded {len(listings_to_create)} pending listing(s).")

    with open(COOKIES_FILE) as f:
        cookies = [normalize_cookie(c) for c in json.load(f) if "poshmark" in c.get("domain","")]
    print(f"Loaded {len(cookies)} Poshmark cookies")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        await context.add_cookies(cookies)
        page = await context.new_page()

        results = []
        for i, item in enumerate(listings_to_create):
            result = await fill_listing(page, item["listing"], item["photos"], i)
            listing_id = result if isinstance(result, str) else None
            success = bool(result)
            results.append({
                "title": item["listing"]["title"],
                "price": item["listing"]["list_price"],
                "photos": item["photos"],
                "success": success,
                "listing_id": listing_id,
                "listing": item["listing"],
            })
            await page.wait_for_timeout(2000)

        await browser.close()

    print("\n" + "="*60)
    print("FINAL RESULTS")
    print("="*60)
    for r in results:
        status = "✅ Draft saved" if r["success"] else "❌ Failed"
        print(f"  {status} — ${r['price']} — {len(r['photos'])} photo(s) — {r['title'][:50]}")
        if r["listing_id"]:
            print(f"     listing_id: {r['listing_id']}")

    # Move photos to processed/{listing_id}/ for successful drafts
    PROCESSED_DIR = "/home/cymolt/poshmark_listings/processed"
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    for r in results:
        if not r["success"]:
            continue
        listing_id = r["listing_id"] or f"unknown_{r['title'][:20].replace(' ','_')}"
        dest_dir = os.path.join(PROCESSED_DIR, listing_id)
        os.makedirs(dest_dir, exist_ok=True)
        # Move photos
        import shutil
        for photo_path in r["photos"]:
            if os.path.exists(photo_path):
                shutil.move(photo_path, os.path.join(dest_dir, os.path.basename(photo_path)))
        # Save listing metadata
        meta = {
            "listing_id": listing_id,
            "title": r["listing"]["title"],
            "brand": r["listing"].get("brand"),
            "size": r["listing"].get("size"),
            "condition": r["listing"].get("condition"),
            "list_price": r["listing"].get("list_price"),
            "category": r["listing"].get("category"),
            "poshmark_url": f"https://poshmark.com/listing/{listing_id}",
            "drafted_at": __import__('datetime').datetime.now().isoformat(),
            "status": "draft",
        }
        with open(os.path.join(dest_dir, "listing.json"), "w") as f:
            json.dump(meta, f, indent=2)
        print(f"  📁 Photos moved to processed/{listing_id}/")

    # Clear classification cache for moved photos
    cache = load_classification_cache()
    for r in results:
        if r["success"]:
            for photo_path in r["photos"]:
                cache.pop(photo_path, None)
    save_classification_cache(cache)

    # Clean up pending file
    try:
        os.remove(PENDING_LISTINGS_FILE)
        print("Cleared pending_listings.json")
    except Exception:
        pass

    send_whatsapp_notification(results)


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "--preview"

    if mode == "--preview":
        api_key = load_api_key()
        asyncio.run(run_preview(api_key))
    elif mode == "--create":
        asyncio.run(run_create())
    elif mode == "--auto":
        api_key = load_api_key()
        asyncio.run(run_preview(api_key))
        asyncio.run(run_create())
    else:
        print(f"Usage: python3 create_drafts_v7.py [--preview|--create|--auto]")
        print("  --preview  Analyse photos, generate listings, print WhatsApp summary (default)")
        print("  --create   Read pending_listings.json and save Poshmark drafts")
        print("  --auto     Run preview + create in one shot, then notify via WhatsApp")
