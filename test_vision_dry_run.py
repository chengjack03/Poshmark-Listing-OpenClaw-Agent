"""Quick dry-run: test 2-pass grouping without Playwright."""
import json, base64, os, glob, time, io

INBOUND_DIR  = "/home/cymolt/poshmark_listings/.openclaw_state/media/inbound"
VISION_MODEL = "qwen/qwen3.6-plus:free"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")


def encode_image(path, max_px=512):
    from PIL import Image
    with Image.open(path) as img:
        img = img.convert("RGB")
        img.thumbnail((max_px, max_px), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return base64.standard_b64encode(buf.getvalue()).decode("utf-8")


def vision_call(client, content, max_tokens=200, retries=5, base_delay=20):
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=VISION_MODEL, max_tokens=max_tokens,
                messages=[{"role": "user", "content": content}],
            )
            text = resp.choices[0].message.content if resp.choices[0].message.content else None
            if text is None:
                raise ValueError("Empty response")
            return text.strip()
        except Exception as e:
            if attempt < retries - 1 and ("429" in str(e) or "Empty" in str(e) or "None" in str(e)):
                wait = base_delay * (2 ** attempt)
                print(f"    ⏳ Waiting {wait}s (retry {attempt+2}/{retries})...")
                time.sleep(wait)
            else:
                raise


def parse_json(raw):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def normalize_print(pr):
    pr = pr.lower().strip()
    texture_words = ("waffle","ribbed","stripe","knit","crinkle","linen","solid","plain","texture")
    if any(w in pr for w in texture_words) and not any(p in pr for p in ("floral","cherry","check","plaid","graphic","dot","print","animal")):
        return "solid"
    return pr


# ── Find photos ───────────────────────────────────────────────────────────────
files = []
for ext in ("*.jpg","*.jpeg","*.png","*.JPG","*.JPEG","*.PNG"):
    files.extend(glob.glob(os.path.join(INBOUND_DIR, ext)))
files = sorted(set(files), key=os.path.getmtime)
print(f"Found {len(files)} photos in inbound")
if not files:
    print("Nothing to do."); raise SystemExit(0)

from openai import OpenAI
client = OpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1")

# ── Pass 1: classify each photo individually ──────────────────────────────────
print(f"\nPass 1: classifying {len(files)} photos...")
classifications = []
for i, path in enumerate(files):
    print(f"  [{i+1}/{len(files)}] {path.split('/')[-1][:30]}")
    img = encode_image(path)
    content = [
        {"type":"image_url","image_url":{"url":"data:image/jpeg;base64,"+img}},
        {"type":"text","text":(
            "Classify this clothing photo. Return ONLY valid JSON, no markdown:\n"
            '{"photo_type":"garment|tag|other",'
            '"garment_type":"top|pants|shorts|dress|onesie|jacket|set|unknown",'
            '"print":"describe the print pattern specifically e.g. yellow-floral, red-cherry, solid, waffle-texture",'
            '"color":"main background color",'
            '"brand":"brand name or unknown",'
            '"size":"size if visible or unknown"}'
        )}
    ]
    raw = vision_call(client, content, max_tokens=150)
    c = parse_json(raw)
    c["index"] = i
    c["path"] = path
    print(f"    → {c.get('photo_type')} | {c.get('garment_type')} | {c.get('print')} | {c.get('brand')} {c.get('size')}")
    classifications.append(c)
    time.sleep(4)

# ── Pass 2: group ─────────────────────────────────────────────────────────────
print("\nPass 2: grouping...")
groups_map = {}
tag_photos = []

for c in classifications:
    if c.get("photo_type") == "tag":
        tag_photos.append(c); continue
    gt  = c.get("garment_type","unknown").lower().strip()
    pr  = normalize_print(c.get("print","unknown"))
    col = c.get("color","unknown").lower().strip()
    key = f"{gt}|{pr}|{col}"
    groups_map.setdefault(key, []).append(c["index"])

for tag in tag_photos:
    tag_pr = normalize_print(tag.get("print",""))
    tag_gt = tag.get("garment_type","").lower().strip()
    best_key = None
    for key in groups_map:
        gt_k, pr_k, _ = key.split("|")
        if tag_gt == gt_k and tag_pr == pr_k:
            best_key = key; break
    if not best_key and tag_pr:
        for key in groups_map:
            _, pr_k, _ = key.split("|")
            if tag_pr == pr_k or tag_pr in pr_k or pr_k in tag_pr:
                best_key = key; break
    if not best_key and groups_map:
        best_key = list(groups_map.keys())[0]
    if best_key:
        groups_map[best_key].append(tag["index"])

print(f"\nGroups found: {len(groups_map)}")
for key, indices in groups_map.items():
    gt, pr, col = key.split("|")
    photo_names = [files[i].split("/")[-1][:16] for i in sorted(indices)]
    print(f"  [{gt} | {pr} | {col}] ({len(indices)} photos): {photo_names}")

print("\nDry run complete.")
