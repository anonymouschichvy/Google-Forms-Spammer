<h1 align="center">Google Forms Spammer</h1>

<p align="center">
  <a href="https://www.python.org/">
    <img src="https://img.shields.io/badge/python-3.10%2B-blue.svg?style=for-the-badge&logo=python&logoColor=white" alt="Python Version">
  </a>
  <a href="https://opensource.org/licenses/MIT">
    <img src="https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge" alt="License: MIT">
  </a>
  <a href="https://docs.python.org/3/library/asyncio.html">
    <img src="https://img.shields.io/badge/Engine-Asyncio%20%2F%20Aiohttp-orange.svg?style=for-the-badge&logo=python&logoColor=white" alt="Asynchronous Engine">
  </a>
  <a href="https://github.com/anonymouschichvy/Google-Forms-Spammer">
    <img src="https://img.shields.io/badge/Scraper-FB__PUBLIC__LOAD__DATA-blueviolet.svg?style=for-the-badge" alt="Scraper Type">
  </a>
</p>

A high-performance, asynchronous, CLI-driven Google Forms mass-submission tool. By utilizing direct JSON configuration scraping (`FB_PUBLIC_LOAD_DATA_`) and metadata token mapping, this tool bypasses heavy browser automation (such as Selenium or Playwright) to execute concurrent HTTP submissions at extreme speeds.

---

## 🛠️ How It Works (Under the Hood)

The engine fetches, parses, maps, and fires requests efficiently using the following lifecycle:

```mermaid
graph TD
    A[Start: Provide Google Form URL] --> B{Check URL Type}
    B -->|forms.gle| C[Resolve redirect to viewform]
    B -->|docs.google.com| D[Direct URL]
    C --> E[Fetch HTML Page via GET]
    D --> E
    E -->|If Direct fails| F[Fallback: Retry using random HTTP Proxy]
    E --> G[Parse HTML using regex & JSON parser]
    F --> G
    G --> H[Extract Questions & Meta: fbzx, pageHistory]
    H --> I{Execution Path}
    I -->|--load profile.json| J[Load saved answers & merge with fresh meta]
    I -->|Interactive| K[Prompt user question-by-question]
    K -->|--save profile.json| L[Write to JSON & Exit]
    K --> M[Set submission count & concurrency]
    J --> M
    M --> N[Initialize asyncio Event Loop]
    N --> O[Spawn concurrent aiohttp workers]
    O --> P{Submit Response}
    P -->|Pool Answer| Q[Select random answer from pool]
    P -->|Static Answer| R[Encode payload with sentinel & meta fields]
    Q --> S[Send POST requests]
    R --> S
    S --> T[tqdm progress bar updates]
    T --> U[Done: Display speed & success rates]
```

---

## ✨ Features & Capabilities

- **⚡ Blazing Fast Engine**: Scraping is done instantly by extracting fields, choices, and internal validations directly from the Google Forms inline Javascript array (`FB_PUBLIC_LOAD_DATA_`).
- **🌪️ Asynchronous Concurrency**: Built with `asyncio` and `aiohttp` to dispatch hundreds of submissions concurrently with rate limits handled via connection pools.
- **💾 Profile Management**: Build a questionnaire response profile once, save it to a local JSON file (`profile.json`), and reload it for automated execution.
- **🎲 Dynamic Answer Pools**: Customize response variations using the `pool:option1|option2` syntax to rotate inputs and make submissions look organic.
- **🛡️ Security token mapping**: Automatically extracts and submits crucial security tokens (`fbzx`, `pageHistory`, `partialResponse`) to bypass basic anti-bot headers.
- **🌐 Proxy Failover & Rotation**: Supports SOCKS4, SOCKS5, HTTP, and HTTPS proxies with automatic redirection/scraping failover.
- **🚪 Graceful Interruption**: Catches `Ctrl+C` cleanly, letting active workers finish their current request before summarizing stats.

---

### Question Type Support Matrix

| Question Type (from Image) | Status | Code Mapping | Notes & Input Formats |
| :--- | :---: | :--- | :--- |
| **Short answer** | **Supported** | Code `0` (`"Short Answer"`) | Accepts free text or random pool options (e.g., `pool:text1\|text2`). |
| **Paragraph** | **Supported** | Code `1` (`"Paragraph"`) | Accepts free text or random pool options. |
| **Multiple choice** | **Supported** | Code `2` (`"Multiple Choice"`) | Matches choices exactly. Supports `pool:all` or specific pools. |
| **Checkboxes** | **Supported** | Code `4` (`"Checkbox"`) | Supports multi-select via comma-separated options (e.g., `Option A, Option B`). |
| **Dropdown** | **Supported** | Code `3` (`"Dropdown"`) | Matches choices exactly. |
| **File upload** | ❌ **Unsupported** | *N/A (Code 11)* | Google Form file uploads require Google user authentication and saving files to Google Drive, which cannot be done via headless, anonymous HTTP POST submissions. |
| **Linear scale** | **Supported** | Code `5` (`"Linear Scale"`) | Accepts numeric values within the scale range. |
| **Rating** | **Supported** | Code `18` (`"Star Rating"`) | Accepts numeric values within the rating range. |
| **Multiple choice grid** | **Supported** | Code `7` (`"MC Grid"`) | Matches options per row. |
| **Checkbox grid** | **Supported** | Code `13` (`"Checkbox Grid"`) | Supports comma-separated selections per row. |
| **Date** | **Supported** | Code `9` (`"Date"`) | Expects `YYYY-MM-DD` formatting, processed via [_split_date](file:///c:/Users/Ervin%20Regio/Desktop/MACOSX/Google-Forms-Spammer/main.py#L316-L321). |
| **Time** | **Supported** | Code `10` (`"Time"`) | Expects `HH:MM` formatting, processed via [_split_time](file:///c:/Users/Ervin%20Regio/Desktop/MACOSX/Google-Forms-Spammer/main.py#L324-L329). |

---

## 📦 Setup & Installation

### 1. Clone the Repository
```bash
git clone https://github.com/anonymouschichvy/Google-Forms-Spammer.git
cd Google-Forms-Spammer
```

### 2. Install Dependencies
Install python dependencies (compatible with Python 3.10+):
```bash
pip install -r requirements.txt
```

> [!NOTE]
> If you plan to use SOCKS4 or SOCKS5 proxies, make sure to install `aiohttp-socks` by running:
> ```bash
> pip install aiohttp-socks
> ```

---

## 📖 Usage Guide

The tool supports three main modes of execution:

### Mode A: Fully Interactive
Guides you through each form question, allowing you to enter static answers or define dynamic pools, then prompts for the number of submissions and concurrency.
```bash
python main.py
```

<p align="center">
  <img src="images/result2.png" alt="Google Forms Spammer CLI" width="90%">
  <br>
  <em>Figure 1: Example command execution showing argument parsing and interactive prompting.</em>
</p>

---

### Mode B: Automating with Saved Profiles
1. **Create and save a response profile** (without running submissions):
   ```bash
   python main.py --url "https://docs.google.com/forms/d/e/.../viewform" --save profile.json
   ```
2. **Run submissions using the profile**:
   ```bash
   python main.py --load profile.json --times 100 --concurrency 50
   ```

---

### Mode C: High-Volume Submissions with Proxies
Pass a newline-separated list of proxies to rotate IP addresses and avoid `429 Too Many Requests` rate limiting.
```bash
python main.py --load profile.json --times 1000 --proxies proxy_list.txt --concurrency 100
```

#### Success Rate & Performance Evidence
Upon launching, the client console reports execution stats and success rate progress logs:

<p align="center">
  <img src="images/result1.png" alt="Submission run success rate evidence" width="90%">
  <br>
  <em>Figure 2: Success rate evidence showing 12.5% completion over 1,000 attempts under high proxy rotation.</em>
</p>

<p align="center">
  <img src="images/result.png" alt="Execution outcomes success rate evidence" width="90%">
  <br>
  <em>Figure 3: Success rate evidence showing 13.9% completion stats and throughput metrics.</em>
</p>

---

#### Google Forms Dashboard Evidence (Submissions Verification)
The administrative responses panel verifies that the spammer works successfully, writing payloads directly to the Google Form database:

<p align="center">
  <img src="images/form1.png" alt="Form submission evidence" width="80%">
  <br>
  <em>Figure 4: Form submission evidence showing 143 out of 145 successful responses recorded for the custom name signature.</em>
</p>

<p align="center">
  <img src="images/form2.png" alt="Form grade distribution evidence" width="80%">
  <br>
  <em>Figure 5: Form submission evidence showing randomized grade distributions across 399 total responses.</em>
</p>

<p align="center">
  <img src="images/form2.1.png" alt="Form response missed questions evidence" width="80%">
  <br>
  <em>Figure 6: Form submission evidence showing answer distribution logs for frequently wrong answer.</em>
</p>

---

## 🎲 Dynamic Option Pools Syntax

Inject randomization into form submissions using the `pool:` syntax when prompting or editing profiles:

| Question Type | Syntax Format | Execution Result |
| :--- | :--- | :--- |
| **Short Text / Paragraph** | `pool:Awesome!\|Excellent\|Very good` | Rotates randomly between these three options. |
| **Multiple Choice / Dropdown** | `pool:all` | Picks any random choice from the form's native choices. |
| **Multiple Choice / Dropdown** | `pool:Option A\|Option C` | Restricts choice rotation specifically to Option A or Option C. |
| **Checkboxes (Multi-select)** | `pool:all` | Selects one or more random options. |
| **Checkboxes (Multi-select)** | `pool:Opt A,Opt B\|Opt C` | Alternates between submitting (Opt A + Opt B) or just (Opt C). |
| **Scale / Star Ratings** | `pool:1\|3\|5` | Selects rating values 1, 3, or 5. |
| **Date & Time Fields** | `YYYY-MM-DD` / `HH:MM` | Formatted static inputs (e.g. `2026-07-02` or `14:30`). |

---

## 🧩 Answer Profiles (`profile.json`) Deep Dive

When you save a profile using `--save <file>`, a structured JSON representation of the form is exported. Below is an example detailing text entries, checkboxes, dropdowns, and security signatures:

```json
{
  "url": "https://docs.google.com/forms/d/e/1FAIpQLSe9wGlMsp0cb67EbhPhogKYIigUYiy6tgwX8kWIrCI4-kuIXQ/viewform",
  "answers": {
    "entry.668699418": "Submitter Text",
    "entry.1378462663": [
      "The laws that protect inventions and literary works",
      "A set of standards that we must follow when we are online"
    ],
    "entry.1653704751": [
      ["Cyber Security"],
      ["Netiquette"]
    ],
    "entry.1654288663": "Patent",
    "entry.1392604932": "5"
  },
  "randomize": {
    "entry.668699418": false,
    "entry.1378462663": true,
    "entry.1653704751": true,
    "entry.1654288663": false,
    "entry.1392604932": false
  },
  "type_codes": {
    "entry.668699418": 0,
    "entry.1378462663": 2,
    "entry.1653704751": 4,
    "entry.1654288663": 3,
    "entry.1392604932": 5
  },
  "meta": {
    "fbzx": "-5693751389381057521",
    "page_history": "0,1",
    "partial_response": "[null,null,\"-5693751389381057521\"]"
  }
}
```

### Profile Field Structure:
* **`url`**: The canonical Google Forms URL.
* **`answers`**: Maps question IDs to answers (single values or list arrays for pools/checkboxes).
* **`randomize`**: Booleans toggling whether the engine selects randomly from the answer array.
* **`type_codes`**: Internal Google Form integer mapping representing field formats (ensuring fields like dates, times, and select grids encode correctly).
* **`meta`**: Tokens dynamically extracted from the page HTML context to build valid POST headers (`fbzx`, `pageHistory`, `partialResponse`).

---

## 🌐 Proxy Configuration & Connection Failovers

The proxy loader supports lists of SOCKS4, SOCKS5, HTTP, and HTTPS proxies.

### Formatting (One proxy per line):
```text
# Standard HTTP Proxy
http://102.34.56.78:8080

# SOCKS5 Proxy with user authentication
socks5://username:password@12.34.56.78:1080

# SOCKS4 Proxy without authentication
socks4://98.76.54.32:1080

# Bare host (defaults to HTTP)
111.22.33.44:3128
```

### Scraping & Submitting Resiliency:
1. **Initial Scraping Redundancy**: If Google blocks your direct IP during the setup scrape phase, the script automatically cycles through loaded HTTP proxies up to 10 times to secure form configurations.
2. **IP Rotation**: Workers select a random proxy from the loaded list for every individual submission, distributing load evenly across IPs.
3. **SSL Handling**: Custom SSL handshakes are disabled to avoid client certificate negotiation failures when routing through public proxies.

---

## ⚙️ Command-Line Arguments

| Argument | Description |
| :--- | :--- |
| `--url URL` | Directly specifies the Google Form URL. |
| `--load FILE` | Path to a saved answer profile (`.json`). |
| `--save FILE` | Saves the mapped questionnaire and answers to a file and exits. |
| `--times N` | Total number of responses to submit. |
| `--concurrency N` | Maximum number of concurrent connections (default: `25`). |
| `--proxies FILE` | Path to a text file containing proxies (one per line). |
| `--refresh-meta` | Forces refreshing metadata (`fbzx`, `pageHistory`) from the live form. |
| `--dump-html FILE` | Dumps the parsed form HTML to a file (useful for debugging). |

---

## ⚠️ reCAPTCHA Bypass

If the google form has reCAPTCHA verification triggered, submissions might trigger bot defenses. To resolve this:

<p align="center">
  <img src="images/captcha.png" alt="reCAPTCHA verification challenge" width="55%">
  <br>
  <em>Figure 7: Re-captcha redirection challenge indicator.</em>
</p>

1. **Copy the verification link** provided in the console error log.
2. **Open the link** in a standard web browser and solve the puzzle.
3. Once completed, copy the **redirected URL** from your browser's address bar.
4. Run the script pointing to this **new URL** using the `--url` argument:
   ```bash
   python main.py --url "<NEW_COMPLETED_CAPTCHA_URL>" --proxies proxy_list.txt
   ```

---

## 🐞 Troubleshooting & Limitations

- **CAPTCHA**: Forms using enterprise-grade strict client-side dynamic CAPTCHAs cannot be bypassed without manual solving.
- **Email Collection**: Forms requiring Google OAuth session login ("Collect email addresses") are not supported as they require browser-signed OAuth credentials.
- **Direct Fetch Block**: If metadata fetching fails on start, run the script with a proxy list (`--proxies`) to scrape the form structure.
- **Structure Changes**: If a multi-page form is edited by the creator, load the profile with `--refresh-meta` to update security signatures.

---

## ⚠️ Disclaimer

> [!WARNING]
> This tool is intended strictly for educational purposes, development testing, and validation of form load capacity. The author is not responsible for any misuse, spam campaigns, or violation of Google Forms Terms of Service. Use responsibly.
