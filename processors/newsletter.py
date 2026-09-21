"""Newsletter processor with URL extraction and category handling.

Processes newsletter emails by category:
- RESEARCH: Extract article URL, create inbox.org entry, archive
- PRODUCT_UPDATE: Check relevance to spaces, create task if relevant, archive
- DAILY_NEWS: Archive without entry
- COMPETITOR: Archive (FYI only)
- SPAM: Immediate archive

URL extraction uses source-specific patterns discovered through manual processing.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime
import re
import base64
import yaml


@dataclass
class NewsletterResult:
    """Result of newsletter processing."""
    action: str           # RESEARCH_QUEUED, PRODUCT_TASK_CREATED, ARCHIVED, SKIPPED, ERROR
    category: str         # RESEARCH, PRODUCT_UPDATE, DAILY_NEWS, COMPETITOR, SPAM
    article_url: Optional[str]
    inbox_entry: Optional[str]
    summary: str
    should_archive: bool   # REQUEST to the caller, not a record of an action.
    email_id: str

    @property
    def archived(self) -> bool:
        """Deprecated alias for should_archive.

        The old name read as past tense and cost a silent bug on 2026-08-09: a
        caller logged "ARCHIVED (32)" from these results while never calling the
        Gmail API, because nothing in this module archives anything. The
        processor only ever REQUESTS archival; the caller must perform it.
        """
        return self.should_archive


# URL extraction patterns by source
# Discovered through manual processing of AVC, HBR, Ben's Bites, Paul Veradittakit
URL_PATTERNS = {
    'paragraph.com': {
        'pattern': r'href=["\']([^"\']*paragraph\.com/@[^"\']+)["\']',
        'exclude': ['/api/', '/settings/', 'email-track', 'metrics'],
        'clean': lambda u: u.split('?')[0],  # Remove tracking params
        'find_in': 'html',
        'sources': ['avc', 'paragraph']
    },
    'bensbites.com': {
        'pattern': r'https://www\.bensbites\.com/p/[^\s]+',
        'find_in': 'text',  # Look in plain text, not HTML
        'sources': ["ben's bites", 'bensbites']
    },
    'veradiverdict.com': {
        'pattern': r'https://www\.veradiverdict\.com/p/[^\s]+',
        'find_in': 'text',
        'sources': ['paul veradittakit', 'veradiverdict', 'pantera']
    },
    'hbr.org': {
        'pattern': r'href=["\']([^"\']*hbr\.org/\d{4}/\d{2}/[^"\']+)["\']',
        'fallback': r'href=["\']([^"\']*link\.hbr\.org/view/[^"\']+)["\']',
        'find_in': 'html',
        'sources': ['hbr', 'harvard business']
    },
    'stratechery.com': {
        'pattern': r'https://stratechery\.com/\d{4}/[^\s]+',
        'find_in': 'text',
        'sources': ['stratechery', 'ben thompson']
    },
    'substack.com': {
        # Generic Substack pattern - find "View this post on the web" links
        'pattern': r'View this post on the web at (https://[^\s]+)',
        'find_in': 'text',
        'sources': []  # Fallback for unknown Substack newsletters
    }
}

# Source name normalization
SOURCE_NAMES = {
    'avc': 'AVC',
    'paragraph': 'AVC',
    "ben's bites": "Ben's Bites",
    'bensbites': "Ben's Bites",
    'paul veradittakit': 'Paul Veradittakit',
    'veradiverdict': 'Paul Veradittakit',
    'pantera': 'Paul Veradittakit',
    'hbr': 'HBR',
    'harvard business': 'HBR',
    'stratechery': 'Stratechery',
    'ben thompson': 'Stratechery',
}


class NewsletterProcessor:
    """Process newsletter emails by category."""

    def __init__(self, space_path: Path, gmail_service=None, products_config: Dict = None):
        """
        Initialize newsletter processor.

        Args:
            space_path: Path to the space (e.g., ~/Data/0-personal)
            gmail_service: Gmail API service for fetching email bodies
            products_config: Product registry config (loaded from products.yaml)
        """
        self.space_path = space_path
        self.gmail_service = gmail_service
        self.products_config = products_config or self._load_products_config()

    def _load_products_config(self) -> Dict:
        """Load product registry from config file."""
        config_path = Path(__file__).parent.parent / 'config' / 'products.yaml'
        if config_path.exists():
            return yaml.safe_load(config_path.read_text())
        return {'products': {}}

    def process(self, email, classification: Dict) -> NewsletterResult:
        """
        Process newsletter based on classification.

        Args:
            email: Email object with id, subject, sender, date, body_text
            classification: Dict with action, type, tracks, etc.

        Returns:
            NewsletterResult with processing outcome
        """
        action = classification.get('action', 'archive_only')
        category = self._detect_category(classification)

        if action == 'prepare_for_research':
            return self._process_research(email, category)
        elif action == 'check_product_update':
            return self._process_product_update(email, classification)
        elif action == 'aggregate_daily_news':
            return self._process_daily_news(email, classification)
        else:
            return self._process_archive_only(email, category)

    def _detect_category(self, classification: Dict) -> str:
        """Detect newsletter category from classification."""
        action = classification.get('action', '')
        nl_type = classification.get('type', '')

        if action == 'prepare_for_research':
            return 'RESEARCH'
        elif action == 'check_product_update':
            return 'PRODUCT_UPDATE'
        elif nl_type == 'daily_news':
            return 'DAILY_NEWS'
        elif nl_type == 'competitor':
            return 'COMPETITOR'
        elif nl_type == 'spam':
            return 'SPAM'
        else:
            return 'OTHER'

    def _process_research(self, email, category: str) -> NewsletterResult:
        """Extract URL and create inbox entry for research newsletters."""
        # 1. Extract article URL
        article_url = self._extract_article_url(email)

        if not article_url:
            # Not an error. A newsletter with no article link (a digest with
            # inline text only, a mention notification the classifier called
            # research) has nothing to queue; it stays in the inbox for a
            # person. Counting it as ERROR put "errors=8" in every nightly
            # Completed line and a Winston alert every morning (2026-09-06/07)
            # for mail that was never going to be processed differently.
            return NewsletterResult(
                action='SKIPPED',
                category=category,
                article_url=None,
                inbox_entry=None,
                summary=f"no article link in: {email.subject[:40]}...",
                should_archive=False,
                email_id=email.id
            )

        # 2. Generate inbox entry
        source = self._detect_source(email)
        today = datetime.now().strftime("%Y-%m-%d %a")
        email_date = email.date.strftime('%Y-%m-%d')

        inbox_entry = f"""** TODO [[{article_url}][{source}: {email.subject}]] :research:
Captured On: [{today}]
Source: {source} newsletter ({email_date})
"""

        # 3. Write to inbox.org
        inbox_path = self.space_path / 'org' / 'inbox.org'
        entry_written = False

        if inbox_path.exists():
            content = inbox_path.read_text()
            # Find "* Inbox" heading
            inbox_pos = content.find("* Inbox\n")
            if inbox_pos != -1:
                insert_pos = inbox_pos + len("* Inbox\n")
                new_content = content[:insert_pos] + inbox_entry + content[insert_pos:]
                inbox_path.write_text(new_content)
                entry_written = True

        return NewsletterResult(
            action='RESEARCH_QUEUED',
            category=category,
            article_url=article_url,
            inbox_entry=inbox_entry if entry_written else None,
            summary=f"{source}: {email.subject[:40]}... → inbox.org",
            should_archive=True,
            email_id=email.id
        )

    def _process_product_update(self, email, classification: Dict) -> NewsletterResult:
        """Check product relevance and create task if relevant."""
        product_key = classification.get('product', '')
        target_space = classification.get('space', '')

        # Check if product exists in registry
        products = self.products_config.get('products', {})
        product_info = products.get(product_key, {})

        if not product_info:
            # Unknown product, just archive
            return NewsletterResult(
                action='ARCHIVED',
                category='PRODUCT_UPDATE',
                article_url=None,
                inbox_entry=None,
                summary=f"Unknown product '{product_key}': {email.subject[:30]}... → archived",
                should_archive=True,
                email_id=email.id
            )

        # Check relevance keywords in subject/body
        relevance_keywords = product_info.get('relevance_keywords', [])
        email_text = f"{email.subject} {email.body_text or ''}".lower()

        relevant_keywords = [kw for kw in relevance_keywords if kw.lower() in email_text]

        if relevant_keywords:
            # Create inbox task
            product_name = product_info.get('name', product_key)
            today = datetime.now().strftime("%Y-%m-%d %a")
            tags = f":{target_space.replace('-', '')}:" if target_space else ''

            inbox_entry = f"""** TODO Review: {product_name} update - {email.subject[:50]} {tags}
Captured On: [{today}]
Source: {product_name} newsletter ({email.date.strftime('%Y-%m-%d')})
Relevant keywords: {', '.join(relevant_keywords)}
"""

            # Write to inbox.org
            inbox_path = self.space_path / 'org' / 'inbox.org'
            if inbox_path.exists():
                content = inbox_path.read_text()
                inbox_pos = content.find("* Inbox\n")
                if inbox_pos != -1:
                    insert_pos = inbox_pos + len("* Inbox\n")
                    new_content = content[:insert_pos] + inbox_entry + content[insert_pos:]
                    inbox_path.write_text(new_content)

            return NewsletterResult(
                action='PRODUCT_TASK_CREATED',
                category='PRODUCT_UPDATE',
                article_url=None,
                inbox_entry=inbox_entry,
                summary=f"{product_name}: {email.subject[:30]}... → task (keywords: {', '.join(relevant_keywords[:2])})",
                should_archive=True,
                email_id=email.id
            )
        else:
            # Not relevant enough, just archive
            return NewsletterResult(
                action='ARCHIVED',
                category='PRODUCT_UPDATE',
                article_url=None,
                inbox_entry=None,
                summary=f"{product_info.get('name', product_key)}: {email.subject[:30]}... → archived (no relevant keywords)",
                should_archive=True,
                email_id=email.id
            )

    def _process_daily_news(self, email, classification: Dict) -> NewsletterResult:
        """
        Process daily news email for aggregation into digest.

        Instead of creating individual tasks, daily news emails are aggregated
        into a single "Daily News Digest" task with links to each newsletter.
        """
        category = classification.get('category', 'general')
        source = self._detect_source(email) or email.sender_name or email.sender.split('@')[0]
        gmail_url = f"https://mail.google.com/mail/u/0/#inbox/{email.id}"

        # Return info for aggregation (actual aggregation done at batch level)
        return NewsletterResult(
            action='DAILY_NEWS_ITEM',
            category='DAILY_NEWS',
            article_url=gmail_url,
            inbox_entry=f"- [[{gmail_url}][{source}: {email.subject[:50]}]]",
            summary=f"Daily news: {source} - {email.subject[:30]}...",
            should_archive=True,
            email_id=email.id
        )

    def _process_archive_only(self, email, category: str) -> NewsletterResult:
        """Archive newsletter without creating any entry."""
        return NewsletterResult(
            action='ARCHIVED',
            category=category,
            article_url=None,
            inbox_entry=None,
            summary=f"{category}: {email.subject[:40]}... → archived",
            should_archive=True,
            email_id=email.id
        )

    def _extract_article_url(self, email) -> Optional[str]:
        """Extract article URL using source-specific patterns."""
        # Get email bodies
        html_body = self._get_html_body(email)
        text_body = email.body_text or ''
        sender_lower = email.sender.lower()

        # Try each URL pattern
        for domain, config in URL_PATTERNS.items():
            # Check if this pattern applies to this sender
            sources = config.get('sources', [])
            if sources and not any(s in sender_lower for s in sources):
                continue

            # Also check if domain appears in content
            if domain.lower() not in html_body.lower() and domain.lower() not in text_body.lower():
                if sources:  # Only skip if we have specific sources
                    continue

            pattern = config['pattern']
            find_in = config.get('find_in', 'html')
            search_in = text_body if find_in == 'text' else html_body

            matches = re.findall(pattern, search_in, re.IGNORECASE)

            # Filter out excluded patterns
            excludes = config.get('exclude', [])
            for url in matches:
                if not any(ex in url.lower() for ex in excludes):
                    # Apply cleanup function if provided
                    clean_func = config.get('clean')
                    if clean_func and callable(clean_func):
                        url = clean_func(url)
                    return url.replace('&amp;', '&')

            # Try fallback pattern if available
            if 'fallback' in config:
                fallback_matches = re.findall(config['fallback'], html_body, re.IGNORECASE)
                if fallback_matches:
                    return fallback_matches[0].replace('&amp;', '&')

        return None

    def _get_html_body(self, email) -> str:
        """Get HTML body of email, fetching via Gmail API if needed."""
        if hasattr(email, 'body_html') and email.body_html:
            return email.body_html

        if self.gmail_service:
            try:
                msg = self.gmail_service.users().messages().get(
                    userId='me',
                    id=email.id,
                    format='full'
                ).execute()

                payload = msg.get('payload', {})
                return self._extract_html_from_payload(payload)
            except Exception:
                pass

        return ''

    def _extract_html_from_payload(self, payload: Dict) -> str:
        """Recursively extract HTML body from email payload."""
        mime_type = payload.get('mimeType', '')

        if mime_type == 'text/html':
            data = payload.get('body', {}).get('data', '')
            if data:
                return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')

        # Check parts
        for part in payload.get('parts', []):
            result = self._extract_html_from_payload(part)
            if result:
                return result

        return ''

    def _detect_source(self, email) -> str:
        """Detect and normalize newsletter source name."""
        sender_lower = (email.sender_name or email.sender).lower()

        for pattern, name in SOURCE_NAMES.items():
            if pattern in sender_lower:
                return name

        # Fallback: use sender name
        return email.sender_name or email.sender.split('@')[0].title()


def batch_process_newsletters(
    emails: List,
    classifications: Dict[str, List],
    space_path: Path,
    gmail_service=None,
    dry_run: bool = False
) -> Dict[str, List[NewsletterResult]]:
    """
    Batch process newsletter emails.

    Args:
        emails: List of Email objects
        classifications: Dict from batch_classify (INFORMATIONAL, etc.)
        space_path: Path to space
        gmail_service: Gmail API service
        dry_run: If True, don't actually process

    Returns:
        Dict of results by action type
    """
    processor = NewsletterProcessor(space_path, gmail_service)

    # Build email lookup
    email_map = {e.id: e for e in emails}

    results = {
        'RESEARCH_QUEUED': [],
        'PRODUCT_TASK_CREATED': [],
        'DAILY_NEWS_ITEM': [],
        'ARCHIVED': [],
        'ERROR': []
    }

    # Process INFORMATIONAL emails that have newsletter rules
    for classification in classifications.get('INFORMATIONAL', []):
        email_id = classification.get('external_id', '').split('/')[-1]
        email = email_map.get(email_id)

        if not email:
            continue

        # Use newsletter_action from classifier (populated from rules)
        # Falls back to 'action' field for backwards compatibility
        nl_action = classification.get('newsletter_action') or classification.get('action', 'archive_only')
        nl_rule = classification.get('newsletter_rule') or {}

        # Build classification dict that newsletter processor expects
        nl_classification = {
            'action': nl_action,
            'type': nl_rule.get('type', ''),
            'topics': nl_rule.get('topics', []),
            'category': nl_rule.get('category', ''),
            'product': nl_rule.get('product', ''),
            'space': nl_rule.get('space', ''),
        }

        if dry_run:
            category = processor._detect_category(nl_classification)
            print(f"  [DRY RUN] {nl_action}: {email.subject[:50]}...")
            continue

        result = processor.process(email, nl_classification)
        results[result.action].append(result)

    # Aggregate daily news items into single task
    if results['DAILY_NEWS_ITEM'] and not dry_run:
        _create_daily_digest_task(results['DAILY_NEWS_ITEM'], space_path)

    return results


def _create_daily_digest_task(daily_news_results: List[NewsletterResult], space_path: Path):
    """
    Create a single Daily News Digest task from multiple daily news emails.

    Groups news by category (ai_tech, crypto, general) and creates a single
    task with links to all newsletters.
    """
    today = datetime.now().strftime("%Y-%m-%d %a")
    today_short = datetime.now().strftime("%b %d")

    # Group by category
    by_category = {}
    for result in daily_news_results:
        # Extract category from the inbox_entry or default to 'general'
        cat = 'General'
        if 'crypto' in result.summary.lower() or 'coindesk' in result.summary.lower():
            cat = 'Crypto'
        elif 'ai' in result.summary.lower() or 'superhuman' in result.summary.lower() or 'rundown' in result.summary.lower():
            cat = 'AI/Tech'

        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(result)

    # Build task content
    task_lines = [f"** TODO Daily News Digest - {today_short} :news:daily:"]
    task_lines.append(":PROPERTIES:")
    task_lines.append(f":CREATED: [{today}]")
    task_lines.append(":END:")
    task_lines.append("")

    for cat, items in sorted(by_category.items()):
        task_lines.append(f"**{cat}:**")
        for item in items:
            task_lines.append(item.inbox_entry)
        task_lines.append("")

    task_entry = "\n".join(task_lines)

    # Write to inbox.org
    inbox_path = space_path / 'org' / 'inbox.org'
    if inbox_path.exists():
        content = inbox_path.read_text()
        inbox_pos = content.find("* Inbox\n")
        if inbox_pos != -1:
            insert_pos = inbox_pos + len("* Inbox\n")
            new_content = content[:insert_pos] + task_entry + content[insert_pos:]
            inbox_path.write_text(new_content)
