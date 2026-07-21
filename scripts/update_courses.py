#!/usr/bin/env python3
"""Refresh the DT&I brochure's cached The Knowledge Academy catalogue.

The script primarily discovers course URLs from the provider's public XML
sitemaps. It also checks selected category pages for links. It intentionally
stores only stable catalogue information: title, category, tags and URL.
Prices, dates and availability are not copied because they change frequently.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = 'https://www.theknowledgeacademy.com'
SITEMAP_URL = f'{BASE_URL}/sitemap.xml'
OUTPUT_PATH = Path(os.getenv('CATALOGUE_OUTPUT', 'data/knowledge-academy-courses.json'))
REQUEST_TIMEOUT = 35
MINIMUM_COURSES = int(os.getenv('MINIMUM_COURSES', '150'))
MAX_SITEMAPS = int(os.getenv('MAX_SITEMAPS', '80'))
USER_AGENT = (
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36 '
    'DTI-Academy-Catalogue-Refresh/1.1'
)

CATEGORY_PATHS = {
    'agile-project-management-training': 'Agile Project Management',
    'it-service-management': 'IT Service Management',
    'it-security-and-data-protection': 'Cyber Security & Data Protection',
    'cisco-training': 'Cisco & Networking',
    'office-applications': 'Microsoft Office Applications',
    'microsoft-technical': 'Microsoft & Azure',
    'programming-and-devops': 'Programming & DevOps',
    'app-and-web-development-training': 'Programming & DevOps',
    'data-analytics-and-ai': 'Data Analytics & AI',
    'cloud': 'Cloud Computing',
    'it-infrastructure-and-networking': 'IT Infrastructure & Support',
    'advanced-technology': 'Architecture & Digital Transformation',
    'business-analysis-training': 'Business Analysis & Change',
    'business-improvement': 'Business Improvement & Quality',
    'software-testing-training': 'Software Testing',
    'digital-marketing-courses': 'Digital Marketing & Web',
}

BLOCKED_TERMS = re.compile(
    r'\b(prince2|pmp|msp|scrum|safe|apm-pmq|microsoft-project|project-management-professional)\b',
    re.I,
)
AGILE_ALLOWED = re.compile(r'agilepm|agile-project-management', re.I)
NON_COURSE_SLUGS = {
    'courses', 'course', 'training', 'classroom', 'online', 'onsite', 'locations',
    'offers', 'resources', 'blogs', 'news', 'about-us', 'contact-us', 'reviews',
}
ACRONYMS = {
    'ai': 'AI', 'api': 'API', 'aws': 'AWS', 'ccna': 'CCNA', 'ccnp': 'CCNP',
    'cisa': 'CISA', 'cism': 'CISM', 'cissp': 'CISSP', 'cobit': 'COBIT',
    'css': 'CSS', 'devops': 'DevOps', 'gdpr': 'GDPR', 'html': 'HTML',
    'it': 'IT', 'itil': 'ITIL', 'iso': 'ISO', 'javascript': 'JavaScript',
    'json': 'JSON', 'linux': 'Linux', 'microsoft': 'Microsoft', 'mysql': 'MySQL',
    'python': 'Python', 'sql': 'SQL', 'tcp': 'TCP', 'togaf': 'TOGAF',
    'ui': 'UI', 'ux': 'UX', 'xml': 'XML',
}

@dataclass(frozen=True)
class Course:
    title: str
    category: str
    url: str
    tags: tuple[str, ...]


def normalise_space(value: str) -> str:
    return re.sub(r'\s+', ' ', value or '').strip()


def title_from_slug(slug: str) -> str:
    words = re.sub(r'[-_]+', ' ', slug).split()
    output = []
    for word in words:
        low = word.lower()
        if low in ACRONYMS:
            output.append(ACRONYMS[low])
        elif re.fullmatch(r'[a-z]+\d+', low):
            output.append(low.upper())
        else:
            output.append(word.capitalize())
    title = ' '.join(output)
    title = re.sub(r'\bTraining Course\b$', 'Training', title, flags=re.I)
    return title


def tags_for(title: str, category: str) -> tuple[str, ...]:
    low = title.lower()
    tags = [category]
    rules = [
        (('cisco', 'ccna', 'ccnp', 'encor', 'enarsi'), 'Cisco'),
        (('azure', 'microsoft', 'power bi', 'excel', 'sharepoint', 'teams'), 'Microsoft'),
        (('aws',), 'AWS'),
        (('google cloud',), 'Google Cloud'),
        (('security', 'cyber', 'ethical', 'cissp', 'cisa', 'cism', 'gdpr'), 'Security'),
        (('python', 'java', 'javascript', 'typescript', 'c#', 'sql'), 'Coding'),
        (('docker', 'kubernetes', 'terraform', 'devops', 'jenkins'), 'DevOps'),
        (('data', 'analytics', 'power bi', 'tableau'), 'Data'),
        (('artificial intelligence', 'generative ai', 'chatgpt', 'machine learning', 'copilot'), 'AI'),
        (('testing', 'selenium', 'istqb', 'cypress'), 'Testing'),
        (('agilepm', 'agile project'), 'Agile'),
    ]
    for needles, tag in rules:
        if any(needle in low for needle in needles):
            tags.append(tag)
    return tuple(dict.fromkeys(tags))


def canonical_course(url: str, anchor_text: str = '') -> Course | None:
    parsed = urlparse(urljoin(BASE_URL, url))
    if parsed.netloc not in {'www.theknowledgeacademy.com', 'theknowledgeacademy.com'}:
        return None
    parts = [part for part in parsed.path.split('/') if part]
    # UK canonical course URLs are /courses/<category>/<course>/.
    if len(parts) != 3 or parts[0] != 'courses':
        return None
    category_slug, course_slug = parts[1], parts[2]
    category = CATEGORY_PATHS.get(category_slug)
    if not category or course_slug in NON_COURSE_SLUGS:
        return None
    combined = f'{course_slug} {anchor_text}'
    if BLOCKED_TERMS.search(combined):
        return None
    if category == 'Agile Project Management' and not AGILE_ALLOWED.search(combined):
        return None
    title = normalise_space(anchor_text)
    if not title or len(title) < 4 or title.lower() in {'learn more', 'view course', 'read more', 'enquire now'}:
        title = title_from_slug(course_slug)
    title = re.sub(r'\s*\|.*$', '', title).strip()
    if BLOCKED_TERMS.search(title):
        return None
    clean_url = f'{BASE_URL}/courses/{category_slug}/{course_slug}/'
    return Course(title=title, category=category, url=clean_url, tags=tags_for(title, category))


def get(session: requests.Session, url: str) -> requests.Response:
    response = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    return response


def parse_xml_locations(content: bytes) -> tuple[str, list[tuple[str, str]]]:
    root = ET.fromstring(content)
    kind = root.tag.rsplit('}', 1)[-1]
    entries = []
    for node in root:
        tag = node.tag.rsplit('}', 1)[-1]
        if tag not in {'sitemap', 'url'}:
            continue
        loc = ''
        lastmod = ''
        for child in node:
            child_tag = child.tag.rsplit('}', 1)[-1]
            if child_tag == 'loc': loc = normalise_space(child.text or '')
            elif child_tag == 'lastmod': lastmod = normalise_space(child.text or '')
        if loc:
            entries.append((loc, lastmod))
    return kind, entries


def discover_from_sitemaps(session: requests.Session) -> dict[str, Course]:
    queue = [SITEMAP_URL]
    visited = set()
    found: dict[str, Course] = {}
    while queue and len(visited) < MAX_SITEMAPS:
        sitemap = queue.pop(0)
        if sitemap in visited:
            continue
        visited.add(sitemap)
        try:
            kind, entries = parse_xml_locations(get(session, sitemap).content)
        except Exception as exc:
            print(f'Warning: sitemap failed: {sitemap}: {exc}', file=sys.stderr)
            continue
        if kind == 'sitemapindex':
            # Course and important sitemaps first, then the rest as capacity permits.
            children = [loc for loc, _ in entries]
            children.sort(key=lambda value: (0 if any(k in value.lower() for k in ('course', 'important')) else 1, value))
            queue.extend(children)
        else:
            for loc, _ in entries:
                course = canonical_course(loc)
                if course:
                    found[course.url] = course
    print(f'Sitemap discovery: {len(found)} matching course URLs from {len(visited)} sitemap files.')
    return found


def discover_from_category_pages(session: requests.Session) -> dict[str, Course]:
    found: dict[str, Course] = {}
    for category_slug in CATEGORY_PATHS:
        url = f'{BASE_URL}/courses/{category_slug}/'
        try:
            soup = BeautifulSoup(get(session, url).text, 'html.parser')
        except Exception as exc:
            print(f'Warning: category page failed: {url}: {exc}', file=sys.stderr)
            continue
        for anchor in soup.find_all('a', href=True):
            course = canonical_course(anchor['href'], anchor.get_text(' ', strip=True))
            if course:
                found[course.url] = course
        time.sleep(0.12)
    print(f'Category-page discovery: {len(found)} matching course URLs.')
    return found


def load_existing() -> dict:
    if not OUTPUT_PATH.exists():
        return {'courses': []}
    try:
        return json.loads(OUTPUT_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {'courses': []}


def validate(courses: list[dict], previous_count: int, previous_status: str) -> None:
    count = len(courses)
    if count < MINIMUM_COURSES:
        raise RuntimeError(f'Refusing to replace the catalogue: only {count} courses were found (minimum {MINIMUM_COURSES}).')
    # The repository starts with a manually prepared seed catalogue. Its count is
    # not a valid live baseline, so allow the first successful scrape to replace it.
    # Once a live catalogue exists, protect later runs from a sudden large drop.
    has_live_baseline = previous_status == 'live catalogue refresh'
    if has_live_baseline and previous_count >= MINIMUM_COURSES and count < int(previous_count * 0.55):
        raise RuntimeError(f'Refusing a suspicious catalogue drop from {previous_count} to {count} courses.')
    blocked = [item['title'] for item in courses if BLOCKED_TERMS.search(item['title'])]
    if blocked:
        raise RuntimeError(f'Blocked project-management products entered the catalogue: {blocked[:5]}')
    urls = [item['providerUrl'] for item in courses]
    if len(urls) != len(set(urls)):
        raise RuntimeError('Duplicate provider URLs were found.')


def main() -> int:
    session = requests.Session()
    session.headers.update({
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-GB,en;q=0.9',
    })
    existing = load_existing()
    previous_count = len(existing.get('courses', []))
    previous_status = str(existing.get('status', '')).strip().lower()
    if previous_status != 'live catalogue refresh':
        print(
            f'Initial migration: existing catalogue status is {previous_status or "unknown"!r}; '
            'the first live result will become the safety baseline.'
        )

    found = discover_from_sitemaps(session)
    found.update(discover_from_category_pages(session))

    # De-duplicate titles, preferring shorter canonical URLs.
    by_title: dict[str, Course] = {}
    for course in sorted(found.values(), key=lambda item: (len(item.url), item.url)):
        key = unicodedata.normalize('NFKD', course.title).encode('ascii', 'ignore').decode().lower()
        key = re.sub(r'[^a-z0-9]+', '', key)
        by_title.setdefault(key, course)

    records = [
        {
            'title': course.title,
            'category': course.category,
            'tags': list(course.tags),
            'duration': 'Varies',
            'delivery': 'Provider options',
            'providerUrl': course.url,
        }
        for course in by_title.values()
    ]
    records.sort(key=lambda item: (item['category'].lower(), item['title'].lower()))
    validate(records, previous_count, previous_status)

    payload = {
        'schemaVersion': 1,
        'source': 'The Knowledge Academy',
        'sourceUrl': f'{BASE_URL}/courses/',
        'lastUpdated': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'courseCount': len(records),
        'status': 'live catalogue refresh',
        'courses': records,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_PATH.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    temporary.replace(OUTPUT_PATH)
    print(f'Catalogue written: {OUTPUT_PATH} ({len(records)} courses; previous {previous_count}).')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'Catalogue refresh failed: {exc}', file=sys.stderr)
        raise SystemExit(1)
