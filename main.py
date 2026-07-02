"""
Google Forms mass-submitter.

Usage:
    python gform.py                                         # interactive
    python gform.py --url URL --save profile.json           # build profile
    python gform.py --url URL --load profile.json --times N # submit
"""

import argparse
import asyncio
import html
import json
import os
import random
import re
import signal
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Any

import aiohttp
import requests
from tqdm import tqdm

# Enable ANSI escape sequences on Windows
if sys.platform == "win32":
    os.system("")

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


# ---------------------------------------------------------------------------
# Console colors
# ---------------------------------------------------------------------------
class C:
    HEADER = '\033[95m'; BLUE = '\033[94m'; CYAN = '\033[96m'; GREEN = '\033[92m'
    WARN = '\033[93m'; FAIL = '\033[91m'; END = '\033[0m'; BOLD = '\033[1m'

def hdr(s):  return f"{C.HEADER}{s}{C.END}"
def ok(s):   return f"{C.GREEN}{s}{C.END}"
def bad(s):  return f"{C.FAIL}{s}{C.END}"
def info(s): return f"{C.CYAN}{s}{C.END}"
def warn(s): return f"{C.WARN}{s}{C.END}"


# ---------------------------------------------------------------------------
# Google Forms question type map
# ---------------------------------------------------------------------------
TYPE_MAP = {
    0: "Short Answer", 1: "Paragraph", 2: "Multiple Choice", 3: "Dropdown",
    4: "Checkbox", 5: "Linear Scale", 7: "MC Grid", 9: "Date", 10: "Time",
    13: "Checkbox Grid", 18: "Star Rating",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class Question:
    entry_id: str
    title: str
    type_code: int
    type_name: str
    options: list[str] = field(default_factory=list)
    required: bool = False


@dataclass
class FormMeta:
    """Hidden fields captured from the form page (needed by some forms)."""
    fbzx: str | None = None
    page_history: str | None = None
    partial_response: str | None = None


@dataclass
class Profile:
    url: str
    answers: dict[str, Any] = field(default_factory=dict)
    randomize: dict[str, bool] = field(default_factory=dict)
    type_codes: dict[str, int] = field(default_factory=dict)   # remember types for correct encoding
    meta: dict[str, str | None] = field(default_factory=dict)  # fbzx / page_history / partial_response


@dataclass
class Stats:
    successes: int = 0
    completed: int = 0


# ---------------------------------------------------------------------------
# Fetch + parse
# ---------------------------------------------------------------------------
FB_RE = re.compile(r"FB_PUBLIC_LOAD_DATA_\s*=\s*(\[.*?\]);", re.DOTALL)
FBZX_RE = re.compile(r'name="fbzx"\s+value="(-?\d+)"')
PAGE_HISTORY_RE = re.compile(r'name="pageHistory"\s+value="([^"]+)"')
PARTIAL_RE = re.compile(r'name="partialResponse"\s+value="([^"]*)"')


def get_submit_url(url: str) -> str:
    """Resolve redirect for forms.gle and return standard /formResponse url."""
    # Resolve forms.gle redirects
    if "forms.gle" in url:
        try:
            r = requests.head(url, allow_redirects=True, timeout=10)
            url = r.url
        except Exception:
            pass
            
    # Split query parameters
    url = url.split("?")[0]

    # Add scheme if missing
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Remove trailing parts like /viewform, /formResponse, /edit
    for suffix in ("viewform", "formResponse", "edit"):
        if url.endswith(suffix):
            url = url[:-len(suffix)]
        elif "/" + suffix in url:
            url = url.split("/" + suffix)[0]

    url = url.rstrip("/")

    # Ensure it uses the /u/0/d/e format
    if "/d/e" in url and "/u/0/d/e" not in url:
        url = url.replace("/d/e", "/u/0/d/e")

    return url + "/formResponse"



def fetch_form(url: str, proxy: str | None = None) -> tuple[str, list, FormMeta, str]:
    """Return (page_html, FB_PUBLIC_LOAD_DATA_ parsed JSON, FormMeta, resolved_url)."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    proxies = {"http": proxy, "https": proxy} if proxy else None
    r = requests.get(url, timeout=15, headers={"User-Agent": UA}, proxies=proxies)
    r.raise_for_status()
    html_text = r.text
    m = FB_RE.search(html_text)
    if not m:
        raise RuntimeError("FB_PUBLIC_LOAD_DATA_ not found. Is this a real Google Form URL?")
    data = json.loads(m.group(1))

    # Calculate page history dynamically by counting page breaks (type 8)
    try:
        raw_list = data[1][1]
        num_page_breaks = sum(1 for q in raw_list if len(q) > 3 and q[3] == 8)
    except Exception:
        num_page_breaks = 0
    page_history_val = ",".join(str(i) for i in range(num_page_breaks + 1))

    meta = FormMeta(
        fbzx=(FBZX_RE.search(html_text).group(1) if FBZX_RE.search(html_text) else None),
        page_history=page_history_val,
        partial_response=(html.unescape(PARTIAL_RE.search(html_text).group(1)) if PARTIAL_RE.search(html_text) else None),
    )
    return html_text, data, meta, r.url


def parse_questions(fb_data: list) -> list[Question]:
    questions: list[Question] = []
    try:
        raw_list = fb_data[1][1]
    except (IndexError, TypeError):
        raise RuntimeError("Unexpected form data structure.")

    for q in raw_list:
        try:
            title = q[1] or ""
            type_code = q[3]
            entries = q[4] if len(q) > 4 and q[4] else []
        except (IndexError, TypeError):
            continue
        if not entries:
            continue

        for entry in entries:
            try:
                if len(entry) < 1 or entry[0] is None:
                    continue
                eid = f"entry.{entry[0]}"
                opts_raw = entry[1] if len(entry) > 1 else None
                required = bool(entry[2]) if len(entry) > 2 else False
                options = []
                if opts_raw:
                    for o in opts_raw:
                        if isinstance(o, list) and o and o[0] is not None:
                            opt_val = str(o[0]).strip()
                            if opt_val:
                                options.append(opt_val)
                questions.append(Question(
                    entry_id=eid,
                    title=title,
                    type_code=type_code,
                    type_name=TYPE_MAP.get(type_code, f"Unknown({type_code})"),
                    options=options,
                    required=required,
                ))
            except (IndexError, TypeError):
                continue
    return questions


# ---------------------------------------------------------------------------
# Interactive answer collection
# ---------------------------------------------------------------------------
def prompt_answer(q: Question) -> tuple[Any, bool]:
    print(ok(f"\n[{q.type_name}] {q.title}"))
    print(f"  entry_id: {q.entry_id}")
    print(f"  required: {q.required}")
    if q.options:
        print(f"  options:  {', '.join(q.options)}")

    # Dynamic user-friendly hints
    hint = ""
    if q.type_code in (0, 1):
        hint = "  (free text, or 'pool:text1|text2|text3')"
    elif q.type_code in (2, 3, 7):
        if q.options:
            hint = "  (type an option exactly, 'pool:all' to randomize all choices, or 'pool:choice1|choice2')"
        else:
            hint = "  (type an option exactly, or 'pool:choice1|choice2')"
    elif q.type_code in (4, 13):
        if q.options:
            hint = "  (comma-separated options, 'pool:all' to randomize all choices, or 'pool:a,b|c')"
        else:
            hint = "  (comma-separated options, or 'pool:a,b|c|a,c')"
    elif q.type_code in (5, 18):
        if q.options:
            hint = f"  (scale option from {q.options[0]} to {q.options[-1]}, 'pool:all', or 'pool:val1|val2')"
        else:
            hint = "  (numeric scale value, or 'pool:1|2|3')"
    elif q.type_code == 9:
        hint = "  (YYYY-MM-DD)"
    elif q.type_code == 10:
        hint = "  (HH:MM)"

    if hint:
        print(hint)


    while True:
        raw = input(hdr("> ")).strip()

        if raw == "":
            if q.required:
                print(bad("This question is required. Please provide a value."))
                continue
            else:
                return "", False

        # Show warnings for potential option typos
        if q.options and not raw.startswith("pool:"):
            if q.type_code in (2, 3, 7):
                if raw not in q.options:
                    print(warn(f"  [Warning] '{raw}' is not in the options list!"))
            elif q.type_code in (4, 13):
                user_opts = [x.strip() for x in raw.split(",")]
                invalid_opts = [o for o in user_opts if o not in q.options]
                if invalid_opts:
                    print(warn(f"  [Warning] options {invalid_opts} are not in the options list!"))
        break

    if raw.startswith("pool:"):
        body = raw[5:].strip()
        if body.lower() in ("all", "*", "any"):
            if q.options:
                if q.type_code in (4, 13):
                    pool = [[o] for o in q.options]
                else:
                    pool = q.options
                return pool, True
            else:
                print(bad("  [Error] No options available to build a pool. Please specify values manually."))
                # Re-prompt by restarting the input loop
                return prompt_answer(q)
        
        if q.type_code in (4, 13):
            pool = [[x.strip() for x in group.split(",")] for group in body.split("|")]
        else:
            pool = [x.strip() for x in body.split("|")]
        return pool, True


    if q.type_code in (4, 13):
        return [x.strip() for x in raw.split(",")], False

    return raw, False


def build_profile_interactively(url: str, questions: list[Question], meta: FormMeta) -> Profile:
    print(hdr(f"\nFound {len(questions)} answerable entries.\n"))
    profile = Profile(url=url)
    for q in questions:
        val, is_pool = prompt_answer(q)
        profile.answers[q.entry_id] = val
        profile.randomize[q.entry_id] = is_pool
        profile.type_codes[q.entry_id] = q.type_code
    profile.meta = {
        "fbzx": meta.fbzx,
        "page_history": meta.page_history,
        "partial_response": meta.partial_response,
    }
    return profile


# ---------------------------------------------------------------------------
# Payload construction with proper multi-select + date/time handling
# ---------------------------------------------------------------------------
def _split_date(v: str) -> dict[str, str] | None:
    m = re.match(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*$", str(v))
    if not m:
        return None
    y, mo, d = m.groups()
    return {"year": y, "month": str(int(mo)), "day": str(int(d))}


def _split_time(v: str) -> dict[str, str] | None:
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(v))
    if not m:
        return None
    h, mi = m.groups()
    return {"hour": str(int(h)), "minute": str(int(mi))}


def build_formdata(profile: Profile) -> list[tuple[str, str]]:
    """
    Resolve pools per-submission and emit a list of tuples that correctly encodes:
      - sentinel fields
      - multi-select (repeated key=value)
      - date (entry.X_year / _month / _day)
      - time (entry.X_hour / _minute)
      - hidden meta fields (fbzx / pageHistory / partialResponse)
    """
    payload = []

    for eid, val in profile.answers.items():
        is_pool = profile.randomize.get(eid, False)
        tcode = profile.type_codes.get(eid)

        # Sentinel field (required by Google Forms to process radio/checkbox selections correctly)
        if tcode in (2, 3, 4, 7, 13):
            payload.append((f"{eid}_sentinel", ""))

        # Pool resolution
        if is_pool and isinstance(val, list) and val:
            val = random.choice(val)

        if val == "" or val is None:
            continue

        # Date
        if tcode == 9:
            parts = _split_date(val if isinstance(val, str) else "")
            if parts:
                payload.append((f"{eid}_year", parts["year"]))
                payload.append((f"{eid}_month", parts["month"]))
                payload.append((f"{eid}_day", parts["day"]))
            continue

        # Time
        if tcode == 10:
            parts = _split_time(val if isinstance(val, str) else "")
            if parts:
                payload.append((f"{eid}_hour", parts["hour"]))
                payload.append((f"{eid}_minute", parts["minute"]))
            continue

        # Multi-select (list of values) -> repeated fields
        if isinstance(val, list):
            for v in val:
                if v not in ("", None):
                    payload.append((eid, str(v)))
        else:
            payload.append((eid, str(val)))

    # Hidden meta fields (some forms reject without these)
    meta = profile.meta or {}
    if meta.get("fbzx"):
        payload.append(("fbzx", meta["fbzx"]))
    if meta.get("page_history"):
        payload.append(("pageHistory", meta["page_history"]))
    if meta.get("partial_response") is not None:
        payload.append(("partialResponse", meta["partial_response"]))

    return payload


# ---------------------------------------------------------------------------
# Async submission with clean cancellation
# ---------------------------------------------------------------------------
async def submit_one(
    url: str,
    profile: Profile,
    proxies: list[str],
    sem: asyncio.Semaphore,
    stop: asyncio.Event,
    pbar: tqdm,
    max_retries: int = 5,
) -> bool:
    if stop.is_set():
        return False
    async with sem:
        for attempt in range(1, max_retries + 1):
            if stop.is_set():
                return False
            proxy = random.choice(proxies) if proxies else None
            is_socks = proxy and proxy.startswith(("socks4", "socks5"))
            proxy_str = proxy if proxy else "Direct"
            
            try:
                if is_socks:
                    from aiohttp_socks import ProxyConnector
                    connector = ProxyConnector.from_url(proxy, ssl=False)
                    async with aiohttp.ClientSession(connector=connector) as session:
                        async with session.post(
                            url,
                            data=build_formdata(profile),
                            timeout=aiohttp.ClientTimeout(total=15),
                            allow_redirects=True,
                        ) as resp:
                            if resp.status != 200:
                                pbar.write(warn(f"[Attempt {attempt}/{max_retries}] {proxy_str} returned status {resp.status}"))
                                if not proxies:
                                    return False
                                continue
                            body = await resp.text()
                            success = ("Your response has been recorded" in body) or ("formResponse" in str(resp.url))
                            if success:
                                return True
                            else:
                                pbar.write(warn(f"[Attempt {attempt}/{max_retries}] {proxy_str} response validation failed"))
                                if not proxies:
                                    return False
                                continue
                else:
                    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False, force_close=True), headers={"User-Agent": UA}) as session:
                        async with session.post(
                            url,
                            data=build_formdata(profile),
                            proxy=proxy,
                            timeout=aiohttp.ClientTimeout(total=15),
                            allow_redirects=True,
                        ) as resp:
                            if resp.status != 200:
                                pbar.write(warn(f"[Attempt {attempt}/{max_retries}] {proxy_str} returned status {resp.status}"))
                                if not proxies:
                                    return False
                                continue
                            body = await resp.text()
                            success = ("Your response has been recorded" in body) or ("formResponse" in str(resp.url))
                            if success:
                                return True
                            else:
                                pbar.write(warn(f"[Attempt {attempt}/{max_retries}] {proxy_str} response validation failed"))
                                if not proxies:
                                    return False
                                continue
            except asyncio.CancelledError:
                raise
            except Exception as e:
                err_name = type(e).__name__
                pbar.write(warn(f"[Attempt {attempt}/{max_retries}] {proxy_str} failed: {err_name}"))
                if not proxies:
                    return False
                continue
        return False


async def worker(
    queue: asyncio.Queue,
    url: str,
    profile: Profile,
    proxies: list[str],
    sem: asyncio.Semaphore,
    stop: asyncio.Event,
    pbar: tqdm,
    stats: Stats,
    max_retries: int = 5,
) -> None:
    while not stop.is_set():
        try:
            _ = queue.get_nowait()
        except asyncio.QueueEmpty:
            break

        if stop.is_set():
            queue.task_done()
            break

        try:
            result = await submit_one(url, profile, proxies, sem, stop, pbar, max_retries)
            if result:
                stats.successes += 1
            stats.completed += 1
        except Exception:
            stats.completed += 1
        finally:
            pbar.update(1)
            queue.task_done()


async def run_submissions(
    profile: Profile,
    times: int,
    concurrency: int,
    proxies: list[str],
    stats: Stats,
    max_retries: int = 5,
) -> tuple[int, int, float]:
    submit_url = get_submit_url(profile.url)
    sem = asyncio.Semaphore(concurrency)
    stop = asyncio.Event()

    # Wire SIGINT/SIGTERM to the stop event (POSIX). On Windows falls back to KeyboardInterrupt.
    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        s = getattr(signal, sig_name, None)
        if s is None:
            continue
        try:
            loop.add_signal_handler(s, stop.set)
        except NotImplementedError:
            pass  # Windows

    # Initialize task queue
    queue = asyncio.Queue()
    for i in range(times):
        queue.put_nowait(i)

    start = time.time()

    pbar = tqdm(total=times, desc="Submitting", ncols=80, dynamic_ncols=True)
    # Spawn worker tasks
    num_workers = min(concurrency, times)
    workers = [
        asyncio.create_task(worker(queue, submit_url, profile, proxies, sem, stop, pbar, stats, max_retries))
        for _ in range(num_workers)
    ]

    try:
        await asyncio.gather(*workers, return_exceptions=True)
    except (KeyboardInterrupt, asyncio.CancelledError):
        stop.set()
        raise
    finally:
        if stop.is_set():
            pbar.write(warn("Interrupted — stopping workers..."))
            for w in workers:
                if not w.done():
                    w.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.gather(*workers, return_exceptions=True),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                pbar.write(warn("Some workers did not stop in time; forcing shutdown."))
        pbar.close()

    elapsed = time.time() - start
    return stats.successes, stats.completed, elapsed


# ---------------------------------------------------------------------------
# Profile IO
# ---------------------------------------------------------------------------
def save_profile(profile: Profile, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(profile), f, indent=2, ensure_ascii=False)
    print(ok(f"Saved profile -> {path}"))


def load_profile(path: str) -> Profile:
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    return Profile(
        url=d["url"],
        answers=d.get("answers", {}),
        randomize=d.get("randomize", {}),
        type_codes={k: int(v) for k, v in d.get("type_codes", {}).items()},
        meta=d.get("meta", {}),
    )


def load_proxies(path: str) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            proxies = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
        
        valid_proxies = []
        for p in proxies:
            if p.startswith(("http://", "https://", "socks4://", "socks5://")):
                valid_proxies.append(p)
            elif p.startswith("socks4a://"):
                valid_proxies.append(p.replace("socks4a://", "socks4://"))
            elif ":" in p:
                valid_proxies.append("http://" + p)
            else:
                valid_proxies.append(p)
                
        print(info(f"Loaded {len(valid_proxies)} proxies from {path}"))
        return valid_proxies
    except Exception as e:
        print(bad(f"Error loading proxy file: {e}"))
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Google Forms mass-submitter")
    p.add_argument("--url")
    p.add_argument("--load", help="Load saved answer profile (JSON)")
    p.add_argument("--save", help="Save built profile and exit (no submission)")
    p.add_argument("--times", type=int)
    p.add_argument("--concurrency", type=int, default=25)
    p.add_argument("--proxies", help="Path to newline-separated proxy list")
    p.add_argument("--max-retries", type=int, default=5,
                   help="Max proxy retries per submission (default: 5)")
    p.add_argument("--dump-html", help="Dump raw form HTML for debugging")
    p.add_argument("--refresh-meta", action="store_true",
                   help="When using --load, re-fetch fbzx/pageHistory from the live form")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    url = args.url or input(hdr("Enter Google Form URL: ")).strip()

    # Load proxies early
    proxies = load_proxies(args.proxies) if args.proxies else []

    # Fetch the form to get fresh metadata (fbzx, page history) and resolve redirects.
    # We try to connect directly first. If that fails, we fallback to random HTTP proxies.
    fb_data = None
    meta = FormMeta()
    html_content = None
    resolved_url = None

    try:
        html_content, fb_data, meta, resolved_url = fetch_form(url)
        url = resolved_url
    except Exception as direct_err:
        print(warn(f"Direct connection to Google Forms failed: {direct_err}"))
        if proxies:
            print(info("Retrying fetch using loaded HTTP proxies..."))
            http_proxies = [p for p in proxies if p.startswith(("http://", "https://"))]
            if not http_proxies:
                print(bad("No HTTP proxies available (only SOCKS proxies loaded). Cannot fetch form metadata."))
                sys.exit(1)
            
            success = False
            for _ in range(10):  # try up to 10 random HTTP proxies
                proxy_for_fetch = random.choice(http_proxies)
                try:
                    html_content, fb_data, meta, resolved_url = fetch_form(url, proxy=proxy_for_fetch)
                    success = True
                    print(ok(f"Successfully fetched form metadata via proxy: {proxy_for_fetch}"))
                    break
                except Exception:
                    continue
            if not success:
                print(bad("Failed to fetch/parse form even with HTTP proxies."))
                sys.exit(1)
            url = resolved_url
        else:
            print(bad("No proxies available to retry fetch. Please check your network connection."))
            sys.exit(1)

    if args.dump_html:
        with open(args.dump_html, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(info(f"Dumped HTML to {args.dump_html}"))

    if args.load:
        profile = load_profile(args.load)
        print(info(f"Loaded profile from {args.load} ({len(profile.answers)} entries)"))
        # Always refresh metadata with latest resolved url, fbzx, and page history
        profile.meta = {
            "fbzx": meta.fbzx,
            "page_history": meta.page_history,
            "partial_response": meta.partial_response,
        }
        profile.url = url
        # Refresh type_codes in case they are missing or updated
        questions = parse_questions(fb_data)
        for q in questions:
            profile.type_codes[q.entry_id] = q.type_code
        print(info("Refreshed fbzx / pageHistory from live form."))
    else:
        questions = parse_questions(fb_data)
        if not questions:
            print(bad("No answerable questions found."))
            sys.exit(1)
        profile = build_profile_interactively(url, questions, meta)
        profile.url = url

    if args.save:
        save_profile(profile, args.save)
        return

    print(info("\nCollected answers:"))
    print(json.dumps(profile.answers, indent=2, default=str, ensure_ascii=False))

    times = args.times
    if times is None:
        while True:
            try:
                times = int(input(hdr("How many times to submit? ")))
                if times < 1:
                    raise ValueError
                break
            except ValueError:
                print(bad("Enter a positive integer."))

    stats = Stats()
    start_time = time.time()
    try:
        successes, completed, elapsed = asyncio.run(
            run_submissions(profile, times, args.concurrency, proxies, stats, args.max_retries)
        )
    except KeyboardInterrupt:
        elapsed = time.time() - start_time
        fails = stats.completed - stats.successes
        rate = stats.completed / elapsed if elapsed > 0 else 0
        print(warn(
            f"\nAborted before completion. {stats.successes} ok, {fails} failed, {stats.completed}/{times} attempted in {elapsed:.2f}s ({rate:.1f} req/s)"
        ))
        sys.exit(130)

    fails = completed - successes
    rate = completed / elapsed if elapsed > 0 else 0
    tag = ok if completed == times else warn
    print(tag(
        f"\nDone. {successes} ok, {fails} failed, {completed}/{times} attempted in {elapsed:.2f}s ({rate:.1f} req/s)"
    ))


if __name__ == "__main__":
    main()