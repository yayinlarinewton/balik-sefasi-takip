"""Conservative reservation-change watcher; site-specific selectors must be validated.

No booking or payment is performed. Only sends notifications for an unambiguous
availability result on the selected boat, date, tour type and start/end times.
Unverified layouts result in UNKNOWN and a diagnostic screenshot, not an alert.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "targets.json").read_text(encoding="utf-8"))
DIAG = ROOT / "diagnostics"
DIAG.mkdir(exist_ok=True)
REPO = os.getenv("GITHUB_REPOSITORY", "")
GHTOKEN = os.getenv("GH_TOKEN", "")
BOT = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
TR = ZoneInfo("Europe/Istanbul")


def fold(s):
    s = unicodedata.normalize("NFKD", str(s)).casefold()
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.translate(str.maketrans("ıİ", "iI"))
    return re.sub(r"\s+", " ", s).strip()


def quiet_wait(page, ms=450):
    page.wait_for_timeout(ms)


def click_exact_or_partial(page, label, *, exact=True):
    """Select only a unique visible matching element; never guess between two."""
    patterns = [re.compile(r"^\s*" + re.escape(label) + r"\s*$", re.I)] if exact else [re.compile(re.escape(label), re.I)]
    for pattern in patterns:
        for role in ("button", "link", "option", "radio"):
            loc = page.get_by_role(role, name=pattern)
            matches = [loc.nth(i) for i in range(min(loc.count(), 50)) if loc.nth(i).is_visible()]
            if len(matches) == 1:
                matches[0].click(timeout=4000)
                quiet_wait(page)
                return True
        loc = page.get_by_text(pattern, exact=exact)
        matches = [loc.nth(i) for i in range(min(loc.count(), 50)) if loc.nth(i).is_visible()]
        if len(matches) == 1:
            matches[0].click(timeout=4000)
            quiet_wait(page)
            return True
    return False


def click_one_of(page, choices):
    for s in choices:
        if click_exact_or_partial(page, s):
            return True
    return False


def next_step(page):
    return click_one_of(page, ["Devam Et", "Devam", "İleri", "Sonraki", "Seç", "Rezervasyona Devam Et"])


def set_date(page, target_date):
    """Prefer input[type=date]; fallback to date-picker day requires visible month/year."""
    el = page.locator('input[type="date"]')
    visible = [el.nth(i) for i in range(el.count()) if el.nth(i).is_visible()]
    if len(visible) == 1:
        visible[0].fill(target_date)
        visible[0].dispatch_event("change")
        quiet_wait(page)
        return True

    day = int(target_date[-2:])
    # Strict fallback: NEVER click day "6" or "7" unless November 2026 is visible.
    txt = fold(page.locator("body").inner_text(timeout=8000))
    if "kasim" not in txt and "november" not in txt:
        return False
    if "2026" not in txt:
        return False
    return click_one_of(page, [str(day), f"{day} Kasım", f"{day} Kasım 2026"])


def click_time(page):
    variants = [
        "19:00 - 01:00", "19:00 – 01:00", "19:00-01:00", "19.00 - 01.00",
        "19:00 / 01:00", "19:00", "19.00"
    ]
    return click_one_of(page, variants)


def save_diag(page, prefix, note):
    try:
        page.screenshot(path=str(DIAG / f"{prefix}.png"), full_page=True, timeout=9000)
    except Exception:
        pass
    try:
        js = """() => [...document.querySelectorAll('button,a,input,select,[role="button"],[role="option"]')]
            .filter(e => e.getClientRects().length)
            .slice(0,180)
            .map(e => ({tag:e.tagName,role:e.getAttribute('role'),text:(e.innerText||e.getAttribute('aria-label')||e.value||'').trim().slice(0,110),
                title:e.getAttribute('title'),type:e.getAttribute('type'),placeholder:e.getAttribute('placeholder')}))"""
        interactives = page.evaluate(js)
        body = page.locator("body").inner_text(timeout=7000)[0:12000]
        out = {"note": note, "url": page.url, "interactives": interactives, "visible_text": body}
        (DIAG / f"{prefix}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        (DIAG / f"{prefix}.txt").write_text(f"{note} - {e}", encoding="utf-8")


def classify_visible_slot(page, date, boat):
    """Conservative slot classification: target slot must include both 19:00 and 01:00.

    A page-level 'Müsait' never counts. A matching slot must show explicit
    availability/occupancy status. In ambiguous layouts return UNKNOWN.
    """
    slots = page.locator("button,li,tr,article,[role='button'],[class*='card'],[class*='slot'],[class*='sefer']")
    candidates = []
    for i in range(min(slots.count(), 220)):
        el = slots.nth(i)
        try:
            if not el.is_visible():
                continue
            t = fold(el.inner_text(timeout=500))
            if len(t) > 420 or len(t) < 7:
                continue
            if re.search(r"19[:.]00", t) and re.search(r"0?1[:.]00", t):
                candidates.append((len(t), t))
        except Exception:
            continue
    if not candidates:
        return "UNKNOWN", "Time-slot container not found"
    candidates.sort()
    best_len, slot_text = candidates[0]
    # If several disjoint matching slots have different statuses, bail out.
    statuses = []
    for n, t in candidates:
        if n > best_len + 45:
            break
        if re.search(r"\b(dolu|yer yok|tukendi|full)\b", t):
            statuses.append("FULL")
        elif re.search(r"\b(musait|az yer|bos yer|kalan [1-9]|available)\b", t):
            statuses.append("OPEN")
        else:
            statuses.append("UNKNOWN")
    if len(set(statuses)) > 1:
        return "UNKNOWN", "Conflicting slot statuses"
    status = statuses[0]
    if status == "OPEN":
        # Verify target context to prevent interpreting another boat/date/tour's slot.
        txt = fold(page.locator("body").inner_text(timeout=7000))
        if fold(boat) not in txt or not any(x in txt for x in ("ekipmansiz", "ekipman siz")):
            return "UNKNOWN", "Boat/tour context not verified"
        day = int(date[-2:])
        if not (date in txt or f"{day} kasim" in txt or f"{day} november" in txt):
            return "UNKNOWN", "Selected date not verified"
    return status, slot_text[:240]


def inspect_one(browser, boat, date, index):
    page = browser.new_page(locale="tr-TR", timezone_id="Europe/Istanbul", viewport={"width":1280,"height":850})
    prefix = f"{index:02d}_{date}_{re.sub('[^a-z0-9]+','-',fold(boat))}"
    try:
        page.goto(CFG["url"], wait_until="domcontentloaded", timeout=30000)
        quiet_wait(page, 1100)
        if not click_exact_or_partial(page, boat):
            save_diag(page, prefix, f"Boat selection not found: {boat}")
            return "UNKNOWN", "Boat selection not found"
        # Let the site move automatically, otherwise continue at most one step.
        if not page.get_by_text(re.compile("ekipmansız|ekipmansiz", re.I)).count():
            next_step(page)
        if not click_one_of(page, ["Ekipmansız Tur", "Ekipmansız", "Ekipmansız Balık Avı"]):
            save_diag(page, prefix, "Equipment-free tour selection not found")
            return "UNKNOWN", "Tour selection not found"
        if not page.locator('input[type="date"]').count():
            next_step(page)
        if not set_date(page, date):
            save_diag(page, prefix, f"Date selection not found: {date}")
            return "UNKNOWN", "Date selection not found"
        quiet_wait(page)
        # Sometimes the time slots appear without a further selection.
        status, note = classify_visible_slot(page, date, boat)
        if status == "UNKNOWN":
            next_step(page)
            status, note = classify_visible_slot(page, date, boat)
        if status == "UNKNOWN":
            save_diag(page, prefix, note)
        print(f"{boat} / {date}: {status} / {note}", flush=True)
        return status, note
    except (PWTimeout, Exception) as exc:
        save_diag(page, prefix, f"Exception: {type(exc).__name__} {exc}")
        return "UNKNOWN", f"Browser error: {type(exc).__name__}"
    finally:
        page.close()


def state_get():
    if not REPO or not GHTOKEN:
        return {}, None
    url = f"https://api.github.com/repos/{REPO}/contents/state.json"
    r = requests.get(url, headers={"Authorization":f"Bearer {GHTOKEN}","Accept":"application/vnd.github+json"}, timeout=15)
    if r.status_code == 404:
        return {}, None
    r.raise_for_status()
    obj = r.json()
    return json.loads(base64.b64decode(obj["content"]).decode("utf-8")), obj["sha"]


def state_put(state, sha):
    if not REPO or not GHTOKEN:
        print("GH_TOKEN or repository missing: no persistent deduplication", file=sys.stderr)
        return False
    url = f"https://api.github.com/repos/{REPO}/contents/state.json"
    payload = {"message":"Update booking monitor states", "content":base64.b64encode((json.dumps(state,ensure_ascii=False,indent=2)+"\n").encode()).decode()}
    if sha:
        payload["sha"] = sha
    r=requests.put(url, json=payload, headers={"Authorization":f"Bearer {GHTOKEN}","Accept":"application/vnd.github+json"}, timeout=15)
    r.raise_for_status()
    return True


def notify(text):
    if not BOT or not CHAT:
        print("Telegram secrets missing. Notification disabled.", file=sys.stderr)
        return False
    resp=requests.post(f"https://api.telegram.org/bot{BOT}/sendMessage",
                       data={"chat_id":CHAT,"text":text,"disable_web_page_preview":True},timeout=20)
    resp.raise_for_status()
    return True


def main():
    now = datetime.now(TR)
    if now >= datetime.fromisoformat(CFG["end_monitoring_at"]):
        print("Monitoring target dates passed; no checks performed.")
        return
    state, sha = state_get()
    checks = []
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        for i,boat in enumerate(CFG["boats"]):
            for j,date in enumerate(CFG["dates"]):
                stat, note=inspect_one(browser, boat, date, i*len(CFG["dates"])+j+1)
                checks.append((f"{boat} | {date}", stat, note))
                time.sleep(0.5)
        browser.close()
    updated = dict(state)
    pending = []
    for key, stat, detail in checks:
        if stat == "UNKNOWN":
            continue  # DO NOT send misleading alerts or destroy previous confirmed state
        previous = state.get(key)
        if stat == "OPEN" and previous != "OPEN":
            pending.append((key, detail))
        updated[key]=stat
    # Do not mark OPEN unless Telegram delivery succeeded: allows retry if message fails.
    success_count=0
    for key, detail in pending:
        msg=(f"⛵ BALIK SEFASI: YER AÇILDI!\n{key}\n"
             f"Ekipmansız Tur • 19:00–01:00\n{detail}\n"
             f"Hemen kontrol edin: {CFG['url']}\n"
             "Not: Yer garanti edilmez, rezervasyonu sizin tamamlamanız gerekir.")
        try:
            if notify(msg):
                success_count+=1
            else:
                updated[key]=state.get(key, "FULL")
        except requests.RequestException as e:
            updated[key]=state.get(key,"FULL")
            print(f"Telegram failure: {e}", file=sys.stderr)
    print(f"Summary: {sum(x[1]=='OPEN' for x in checks)} open, "
          f"{sum(x[1]=='FULL' for x in checks)} full, "
          f"{sum(x[1]=='UNKNOWN' for x in checks)} unknown; {success_count} alerts sent.")
    if updated != state:
        state_put(updated,sha)


if __name__ == "__main__":
    main()
